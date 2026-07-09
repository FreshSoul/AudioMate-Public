import ast
import io
import json
import contextlib
import os
import pprint
import re
import sys
import threading


# ---------------------------------------------------------------------------
# Pre-execution code validation (static checks)
# ---------------------------------------------------------------------------

# Known hallucinated / incorrect WAAPI URIs → correct mapping
_KNOWN_BAD_URIS: dict[str, str] = {
    "ak.wwise.core.object.getCurve": "ak.wwise.core.object.getAttenuationCurve",
    "ak.wwise.core.object.setCurve": "ak.wwise.core.object.setAttenuationCurve",
}

_WAQL_PATTERN = re.compile(r'''['"]\\s*\\$\\s*(?:from|where|select)\\b''', re.IGNORECASE)
_URI_IN_CODE = re.compile(r"""['"](\s*ak\.\w[\w.]*\w\s*)['"]""")
_OBJECT_GET_URI = "ak.wwise.core.object.get"
_OBJECT_GET_SELECTORS = frozenset({
    "parent",
    "children",
    "descendants",
    "ancestors",
    "referencesTo",
})
_GUID_LITERAL = re.compile(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$")
_PLACEHOLDER_BRACE_VALUE = re.compile(r"^\{[^{}]+\}$")
_COMMON_GUESSED_PATHS = (
    "\\Busses",
    "\\Busses\\Default Work Unit\\Main Audio Bus",
    "\\Master-Mixer Hierarchy\\Default Work Unit\\Master Audio Bus",
    "\\Master-Mixer Hierarchy",
    "\\Actor-Mixer Hierarchy",
    "\\Interactive Music Hierarchy",
    "\\Events",
)
_KNOWN_BAD_RETURN_FIELDS = frozenset({
    "@PlaybackLimit",
    "@VolumeDryUsage",
    "@VolumeDry",
    "@SpreadUsage",
    "@Spread",
    "@LowPassFilterUsage",
    "@LowPassFilter",
    "@HighPassFilterUsage",
    "@HighPassFilter",
})
_SAFE_IMPORTS = frozenset({
    "base64",
    "collections",
    "copy",
    "csv",
    "datetime",
    "decimal",
    "functools",
    "glob",
    "itertools",
    "json",
    "math",
    "operator",
    "os",
    "pathlib",
    "random",
    "re",
    "statistics",
    "string",
    "time",
    "uuid",
})


# ---------------------------------------------------------------------------
# Sandbox hardening for dual-use modules.
#
# ``os`` and ``pathlib`` are routinely needed by generated code for
# read-only path computation (``os.path.join``, ``os.path.exists``,
# ``Path.parent``…). But they also expose primitives that bypass our
# deferred-write / user-confirmation pipeline (``os.remove``,
# ``os.system``, ``Path.write_text``…). We allow the import but return a
# wrapper that surfaces the safe API while raising on destructive calls.
#
# ``traceback`` is intentionally NOT in the allowlist: ``traceback.sys is
# sys`` lets sandboxed code call ``traceback.sys.settrace(None)`` and
# defeat the cooperative cancellation in :meth:`CodeExecutor.execute`.
# LLMs rarely need the module — ``try/except`` + ``print`` covers the
# common case.
# ---------------------------------------------------------------------------

_BLOCKED_OS_ATTRS = frozenset({
    # Filesystem mutation
    "remove", "unlink", "rename", "renames", "replace", "rmdir", "removedirs",
    "mkdir", "makedirs", "chmod", "chown", "lchmod", "lchown", "chflags",
    "link", "symlink", "truncate", "ftruncate", "utime",
    # Raw FD ops that bypass _guarded_open
    "open", "write", "fdopen", "pipe", "pipe2", "dup", "dup2",
    # Process control
    "system", "popen", "exec", "execv", "execve", "execvp", "execvpe",
    "execl", "execle", "execlp", "execlpe", "spawnl", "spawnle", "spawnlp",
    "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "fork", "forkpty",
    "kill", "killpg", "abort", "_exit", "startfile",
    # Privilege change
    "setuid", "seteuid", "setreuid", "setresuid",
    "setgid", "setegid", "setregid", "setresgid",
    "umask", "chdir", "fchdir", "chroot",
})

_BLOCKED_PATH_METHODS = frozenset({
    # Write / mutation
    "write_text", "write_bytes", "unlink", "rename", "replace",
    "rmdir", "mkdir", "touch", "chmod", "lchmod", "symlink_to",
    "hardlink_to", "rename", "rename_to",
    # Content reads: in the isolated worker, file reads must go through host
    # tools (read_user_file etc.), never direct disk access — otherwise
    # sandboxed code could exfiltrate ~/.audiomate_secrets.json via Path.read_*.
    "read_text", "read_bytes", "open",
})


def _make_blocked(qualname: str):
    def _blocked(*_args, **_kwargs):
        raise PermissionError(
            f"{qualname}(...) is not allowed in the sandbox. "
            "Use write_user_file()/write_file_tree() for file writes; "
            "subprocess and process-control calls are forbidden."
        )
    return _blocked


def _build_safe_os_module():
    import os as _real_os
    import types as _types
    safe = _types.ModuleType("os")
    for attr in dir(_real_os):
        if attr.startswith("_"):
            continue
        if attr in _BLOCKED_OS_ATTRS:
            setattr(safe, attr, _make_blocked(f"os.{attr}"))
        else:
            setattr(safe, attr, getattr(_real_os, attr))
    # os.path is a submodule of harmless read-only computations — keep it.
    safe.path = _real_os.path
    return safe


def _build_safe_pathlib_module():
    import os as _real_os
    import pathlib as _real_pathlib
    import types as _types
    safe = _types.ModuleType("pathlib")
    safe.PurePath = _real_pathlib.PurePath
    safe.PurePosixPath = _real_pathlib.PurePosixPath
    safe.PureWindowsPath = _real_pathlib.PureWindowsPath

    def _make_safe_path_class(real_cls):
        class _SafePath(real_cls):
            __slots__ = ()
        for method_name in _BLOCKED_PATH_METHODS:
            if hasattr(real_cls, method_name):
                setattr(_SafePath, method_name, _make_blocked(f"Path.{method_name}"))
        _SafePath.__name__ = real_cls.__name__
        _SafePath.__qualname__ = real_cls.__qualname__
        return _SafePath

    safe.PosixPath = _make_safe_path_class(_real_pathlib.PosixPath)
    safe.WindowsPath = _make_safe_path_class(_real_pathlib.WindowsPath)
    safe.Path = safe.WindowsPath if _real_os.name == "nt" else safe.PosixPath
    return safe


# Cached at module load to avoid rebuilding per execution.
_SAFE_OS = _build_safe_os_module()
_SAFE_PATHLIB = _build_safe_pathlib_module()
_SANDBOX_REPLACEMENTS = {"os": _SAFE_OS, "pathlib": _SAFE_PATHLIB}


def _literal_eval_node(node: ast.AST, constants: dict[str, object] | None = None):
    """Best-effort literal evaluator for simple generated-code checks."""
    try:
        return ast.literal_eval(node)
    except Exception:
        pass
    if isinstance(node, ast.Name) and constants and node.id in constants:
        return constants[node.id]
    return None


def _collect_literal_assignments(tree: ast.AST) -> dict[str, object]:
    constants: dict[str, object] = {}
    for stmt in getattr(tree, "body", []):
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = _literal_eval_node(stmt.value, constants)
        if isinstance(value, (dict, list, tuple, str, int, float, bool, type(None))):
            constants[target.id] = value
    return constants


def _get_keyword_node(call: ast.Call, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _validate_object_get_transform_select(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    constants = _collect_literal_assignments(tree)
    warnings: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        uri_node = node.args[0] if node.args else _get_keyword_node(node, "uri")
        uri = _literal_eval_node(uri_node, constants) if uri_node is not None else None
        if uri != _OBJECT_GET_URI:
            continue

        args_node = node.args[1] if len(node.args) >= 2 else _get_keyword_node(node, "args")
        args_value = _literal_eval_node(args_node, constants) if args_node is not None else None
        if not isinstance(args_value, dict):
            continue

        transform = args_value.get("transform")
        if not isinstance(transform, list):
            continue

        for index, transform_item in enumerate(transform):
            if not isinstance(transform_item, dict) or "select" not in transform_item:
                continue
            select_value = transform_item.get("select")
            if not isinstance(select_value, list):
                warnings.append(
                    "Invalid ak.wwise.core.object.get transform[%d].select: select must be "
                    "a one-item list containing one of parent, children, descendants, "
                    "ancestors, referencesTo." % index
                )
                continue
            invalid_selectors = [item for item in select_value if item not in _OBJECT_GET_SELECTORS]
            if len(select_value) != 1 or invalid_selectors:
                invalid_text = ", ".join(str(item) for item in invalid_selectors) or str(select_value)
                warnings.append(
                    "Invalid ak.wwise.core.object.get transform[%d].select value '%s'. "
                    "transform.select only supports parent, children, descendants, "
                    "ancestors, referencesTo. Do not put fields or references such as "
                    "duckedBuses here; request documented properties/references in "
                    "options['return'] after checking ak.wwise.core.object.getPropertyAndReferenceNames."
                    % (index, invalid_text)
                )

    return warnings


def _iter_waapi_call_literals(tree: ast.AST, constants: dict[str, object] | None = None):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "call":
            continue
        owner = func.value
        if not isinstance(owner, ast.Name) or owner.id not in {"waapi_client", "client"}:
            continue
        uri_node = node.args[0] if node.args else _get_keyword_node(node, "uri")
        uri = _literal_eval_node(uri_node, constants) if uri_node is not None else None
        if not isinstance(uri, str) or not uri.startswith("ak."):
            continue
        args_node = node.args[1] if len(node.args) >= 2 else _get_keyword_node(node, "args")
        options_node = node.args[2] if len(node.args) >= 3 else _get_keyword_node(node, "options")
        args_value = _literal_eval_node(args_node, constants) if args_node is not None else None
        options_value = _literal_eval_node(options_node, constants) if options_node is not None else None
        yield uri, args_value, options_value


def _walk_literal_values(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_literal_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_literal_values(item)
    else:
        yield value


def _contains_placeholder(value) -> bool:
    for item in _walk_literal_values(value):
        if not isinstance(item, str):
            continue
        stripped = item.strip()
        if _PLACEHOLDER_BRACE_VALUE.match(stripped) and not _GUID_LITERAL.match(stripped):
            return True
    return False


def _validate_literal_waapi_calls(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    constants = _collect_literal_assignments(tree)
    warnings: list[str] = []

    for uri, args_value, options_value in _iter_waapi_call_literals(tree, constants):
        if _contains_placeholder(args_value) or _contains_placeholder(options_value):
            warnings.append(
                "Placeholder object IDs such as '{Part2_Parent_ID}' were detected. "
                "Use real IDs returned by a previous WAAPI query before calling write/read APIs."
            )

        if isinstance(args_value, dict):
            if "return" in args_value:
                warnings.append(
                    "WAAPI options.return was placed inside args. Put return fields in the third "
                    "waapi_client.call(uri, args, options) argument instead."
                )
            if "options" in args_value:
                warnings.append(
                    "A nested 'options' object was placed inside args. Pass options as the third "
                    "argument to waapi_client.call(uri, args, options)."
                )

        return_fields = []
        if isinstance(options_value, dict) and isinstance(options_value.get("return"), list):
            return_fields.extend(options_value.get("return") or [])
        if isinstance(args_value, dict) and isinstance(args_value.get("return"), list):
            return_fields.extend(args_value.get("return") or [])
        bad_return_fields = [field for field in return_fields if field in _KNOWN_BAD_RETURN_FIELDS]
        if bad_return_fields:
            warnings.append(
                "Likely hallucinated object.get return fields detected: %s. Use "
                "getPropertyAndReferenceNames or the dedicated attenuation curve APIs instead."
                % ", ".join(bad_return_fields)
            )

        if uri != _OBJECT_GET_URI or not isinstance(args_value, dict):
            continue

        if "where" in args_value:
            warnings.append(
                "ak.wwise.core.object.get does not accept a top-level 'where'. Put filters inside "
                "args['transform'] as {'where': [predicate, value]}."
            )

        from_value = args_value.get("from")
        if isinstance(from_value, dict):
            path_value = from_value.get("path")
            if isinstance(path_value, str):
                warnings.append(
                    "ak.wwise.core.object.get from.path must be an array of object paths, not a string. "
                    "Prefer querying by verified id when possible."
                )
            candidate_paths = [path_value] if isinstance(path_value, str) else path_value if isinstance(path_value, list) else []
            for path in candidate_paths:
                if isinstance(path, str) and any(path.rstrip("\\") != common.rstrip("\\") and path.startswith(common.rstrip("\\") + "\\") for common in _COMMON_GUESSED_PATHS):
                    warnings.append(
                        "Hard-coded Wwise root/default paths were detected. Resolve the real target object "
                        "from the current project or selection first, then reuse its returned id/path."
                    )
                    break

        transform = args_value.get("transform")
        if isinstance(transform, list):
            for index, item in enumerate(transform):
                if not isinstance(item, dict):
                    continue
                where_value = item.get("where")
                if not isinstance(where_value, list) or len(where_value) < 2:
                    continue
                predicate, predicate_arg = where_value[0], where_value[1]
                if predicate == "type:isIn" and not (
                    isinstance(predicate_arg, list) and all(isinstance(entry, str) for entry in predicate_arg)
                ):
                    warnings.append(
                        "Invalid ak.wwise.core.object.get transform[%d].where for type:isIn: "
                        "the predicate argument must be a list of object type strings, e.g. "
                        "['Sound', 'MusicSegment']." % index
                    )

    return warnings


def validate_code_patterns(code: str) -> list[str]:
    """Run static checks on generated code and return a list of warnings.

    Returns an empty list if no issues found. Each warning is a short string
    describing the problem and suggested fix.
    """
    if not code:
        return []
    warnings = []

    # 1. Detect known bad WAAPI URIs
    for m in _URI_IN_CODE.finditer(code):
        uri = m.group(1).strip()
        if uri in _KNOWN_BAD_URIS:
            correct = _KNOWN_BAD_URIS[uri]
            warnings.append(
                f"Incorrect WAAPI URI '{uri}' — use '{correct}' instead."
            )

    # 2. Detect WAQL usage (banned)
    if _WAQL_PATTERN.search(code):
        warnings.append(
            "WAQL query syntax detected. WAQL is not supported — use JSON queries with "
            "'from'/'transform' in args and 'return' in options."
        )

    # 3. Detect invalid object.get transform.select values such as duckedBuses.
    warnings.extend(_validate_object_get_transform_select(code))

    # 4. Detect common literal WAAPI argument-shape mistakes before execution.
    warnings.extend(_validate_literal_waapi_calls(code))

    return warnings


class _LenientString(str):
    """String subclass that tolerates accidental dict-style `.get()` access.

    This keeps generated code from crashing when a text-returning helper is
    mistakenly treated like a dict. The default value is returned unchanged.
    """

    def get(self, _key, default=None):
        return default


class _LenientDict(dict):
    """Dict subclass that returns None for missing keys.

    This prevents brittle generated indexing such as item['type'] from
    aborting an entire analysis when one record misses a field.
    """

    def __missing__(self, _key):
        return None


_WAAPI_CLIENT_TOOL_FALLBACKS = frozenset({
    "analyze_audio_file",
    "analyze_wav_file",
    "analyze_selected_source_files_loudness",
    "analyze_project_source_files_loudness",
    "analyze_selected_sources_full_route_loudness",
    "get_project_source_files",
    "get_selected_source_files",
    "get_selected_source_filepaths",
})


class _ToolObjectProxy:
    """Proxy object that wraps callable attribute returns with lenient values."""

    def __init__(self, target, fallback=None):
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_fallback", fallback)

    def __getattr__(self, name):
        target = object.__getattribute__(self, "_target")
        try:
            attr = getattr(target, name)
        except AttributeError as error:
            fallback = object.__getattribute__(self, "_fallback")
            if fallback is None or name not in _WAAPI_CLIENT_TOOL_FALLBACKS:
                raise error
            try:
                attr = getattr(fallback, name)
            except AttributeError:
                raise error
        if callable(attr):
            def _wrapped(*args, **kwargs):
                return _wrap_tool_value(attr(*args, **kwargs))

            return _wrapped
        return _wrap_tool_value(attr)

    def __setattr__(self, name, value):
        target = object.__getattribute__(self, "_target")
        setattr(target, name, value)


def _should_proxy_object(value) -> bool:
    if isinstance(value, (_ToolObjectProxy, _LenientString, _LenientDict)):
        return False
    if isinstance(value, (str, bytes, int, float, bool, dict, list, tuple, set, type(None))):
        return False
    # Proxy tool-like objects (e.g. waapi_client) so method returns are wrapped.
    return any(hasattr(value, attr) for attr in ("call", "get_selected_objects", "get_property", "set_property"))


def _wrap_tool_value(value, fallback=None):
    if isinstance(value, _LenientString) or isinstance(value, _LenientDict):
        return value
    if isinstance(value, str) and not isinstance(value, _LenientString):
        return _LenientString(value)
    if isinstance(value, dict):
        wrapped = _LenientDict()
        for key, item in value.items():
            wrapped[key] = _wrap_tool_value(item)
        return wrapped
    if isinstance(value, list):
        return [_wrap_tool_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_wrap_tool_value(item) for item in value)
    if _should_proxy_object(value):
        return _ToolObjectProxy(value, fallback=fallback)
    return value


def _wrap_tool_callable(func):
    def _wrapped(*args, **kwargs):
        return _wrap_tool_value(func(*args, **kwargs))

    return _wrapped


def _prepare_execution_globals(globals_dict):
    prepared = {}
    tool_fallback = (globals_dict or {}).get("agent_tools")
    for key, value in (globals_dict or {}).items():
        if callable(value):
            prepared[key] = _wrap_tool_callable(value)
        elif key in {"waapi_client", "client"} and tool_fallback is not None:
            prepared[key] = _wrap_tool_value(value, fallback=tool_fallback)
        else:
            prepared[key] = _wrap_tool_value(value)
    return prepared


def _is_known_shape_error(error):
    return (
        isinstance(error, AttributeError) and "'str' object has no attribute 'get'" in str(error)
    ) or (
        isinstance(error, KeyError) and str(error) == "'type'"
    )


def _build_execution_error_message(error):
    message = str(error)
    if _is_known_shape_error(error):
        if isinstance(error, KeyError) and str(error) == "'type'":
            return (
                "A tool result was indexed with ['type'], but that key is missing on at least one item. "
                "Prefer item.get('type', '') or print one sample item first. "
                "Source-file helpers now usually expose 'type', 'objectType', and 'sourceObjectType'."
            )
        return (
            "A tool returned a string, but the code treated it like a dict and called .get(...). "
            "Check the variable on that line and print its value/type first. "
            "For WAAPI results, prefer patterns like: "
            "res = waapi_client.call(...); items = res.get('return', []) or [] "
            "and selected = waapi_client.get_selected_objects(); objects = selected.get('objects', []) or []."
        )
    return message


_WRITE_MODES = frozenset('wax')
CANCELLED_OUTPUT = "[System] 用户已暂停执行。"


class CodeExecutionCancelled(BaseException):
    pass


class _DeferredFileWriter:
    """Buffers file write content in memory for deferred confirmation."""

    def __init__(self, path, mode, encoding=None, **kwargs):
        self.path = os.path.abspath(os.path.expanduser(path))
        self.mode = mode
        self._encoding = encoding if encoding is not None else ('utf-8' if 'b' not in mode else None)
        self._buffer = io.BytesIO() if 'b' in mode else io.StringIO()
        self._is_closed = False
        self.name = self.path

    def write(self, data):
        self._buffer.write(data)
        return len(data)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        pass

    def close(self):
        self._is_closed = True

    @property
    def closed(self):
        return self._is_closed

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def content(self):
        return self._buffer.getvalue()

    def flush_to_disk(self):
        """Write the buffered content to the real file."""
        kw = {}
        if 'b' not in self.mode and self._encoding:
            kw['encoding'] = self._encoding
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        with open(self.path, self.mode, **kw) as f:
            f.write(self.content)


class _DeferredAudioWrite:
    """A staged audio-file mutation (e.g. loudness normalize) awaiting confirmation.

    Mirrors the ``.path`` / ``.flush_to_disk()`` contract of ``_DeferredFileWriter``
    so it can sit in ``CodeExecutor.pending_file_writes`` and be surfaced by the
    same FileWriteConfirmWidget. The actual (atomic) disk write is performed by
    ``apply_callable`` only when ``flush_to_disk`` is called after the user
    confirms — nothing touches disk before that.
    """

    def __init__(self, path, apply_callable):
        self.path = os.path.abspath(os.path.expanduser(path))
        self.name = self.path
        self._apply = apply_callable

    def flush_to_disk(self):
        self._apply()


class CodeExecutor:
    def __init__(self, context_globals=None):
        self.context_globals = _prepare_execution_globals(context_globals or {})
        self.execution_state = dict(self.context_globals)
        self.pending_file_writes = []  # list of _DeferredFileWriter
        self.safe_imports = set(_SAFE_IMPORTS)
        # Optional callback invoked when sandboxed code imports a module outside
        # ``safe_imports``. Signature: ``(module_name: str) -> bool``. Returning
        # True allows the import (and caches its package root in ``safe_imports``
        # so the same module is not asked again this session); False/None raises
        # ImportError. When unset, out-of-allowlist imports raise outright.
        self.ask_import_callback = None
        self._cancel_requested = threading.Event()

    def request_cancel(self):
        self._cancel_requested.set()

    def reset_cancel(self):
        self._cancel_requested.clear()

    def is_cancel_requested(self) -> bool:
        return self._cancel_requested.is_set()

    def _raise_if_cancelled(self):
        if self._cancel_requested.is_set():
            raise CodeExecutionCancelled()

    def _cancel_trace(self, frame, event, arg):
        if event in {"call", "line", "return"}:
            self._raise_if_cancelled()
        return self._cancel_trace

    def update_context(self, extra_globals=None):
        if not extra_globals:
            return
        prepared = _prepare_execution_globals(extra_globals)
        self.context_globals.update(prepared)
        self.execution_state.update(prepared)

    def stage_file_write(self, path, content, *, encoding="utf-8", mode="w"):
        """Buffer one file write so the GUI can confirm it before touching disk."""
        writer = _DeferredFileWriter(path, mode, encoding=encoding)
        writer.write(content if content is not None else "")
        writer.close()
        self.pending_file_writes.append(writer)
        content_value = writer.content
        size = len(content_value.encode(encoding, errors="replace")) if isinstance(content_value, str) else len(content_value)
        return {"path": writer.path, "size": size}

    def stage_audio_write(self, path, apply_callable):
        """Buffer one audio-file mutation (callable) so the GUI confirms it first.

        ``apply_callable`` performs the actual atomic write+backup when invoked;
        it runs only on flush (i.e. after the user confirms), never before.
        """
        op = _DeferredAudioWrite(path, apply_callable)
        self.pending_file_writes.append(op)
        return {"path": op.path}

    def flush_pending_writes(self):
        """Flush all pending deferred file writes to disk. Returns list of result dicts."""
        results = []
        for writer in self.pending_file_writes:
            try:
                writer.flush_to_disk()
                results.append({"path": writer.path, "success": True})
            except Exception as e:
                results.append({"path": writer.path, "success": False, "error": str(e)})
        self.pending_file_writes = []
        return results

    def discard_pending_writes(self):
        """Discard all pending deferred file writes."""
        count = len(self.pending_file_writes)
        self.pending_file_writes = []
        return count

    def _build_safe_builtins(self, mode):
        self.pending_file_writes = []  # reset per execution

        def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            root_name = (name or "").split(".")[0]
            if root_name not in self.safe_imports:
                # Out-of-allowlist import: ask the user (if a callback is wired)
                # whether to allow it. Approval caches the package root for the
                # rest of this session; denial (or no callback) raises.
                approved = False
                if callable(self.ask_import_callback):
                    try:
                        approved = bool(self.ask_import_callback(name))
                    except Exception:
                        approved = False
                if not approved:
                    raise ImportError(f"Import '{name}' is not allowed in {mode}.")
                self.safe_imports.add(root_name)
            # Hand back the hardened wrapper for dual-use modules so
            # ``os.remove`` etc. raise PermissionError before reaching disk.
            if root_name in _SANDBOX_REPLACEMENTS:
                replacement = _SANDBOX_REPLACEMENTS[root_name]
                if not fromlist:
                    return replacement
                # ``from os import path`` etc. — return the replacement so
                # ``__import__`` machinery resolves attributes off it.
                return replacement
            return __import__(name, globals, locals, fromlist, level)

        def _guarded_open(path, mode_arg='r', *args, **kwargs):
            if any(c in mode_arg for c in _WRITE_MODES):
                writer = _DeferredFileWriter(path, mode_arg, *args, **kwargs)
                self.pending_file_writes.append(writer)
                print(f"[File Write] 文件写入已缓存: {writer.path} (等待用户确认)")
                return writer
            return open(path, mode_arg, *args, **kwargs)

        return {
            "print": print,
            "len": len,
            "range": range,
            "enumerate": enumerate,
            "min": min,
            "max": max,
            "sum": sum,
            "sorted": sorted,
            "zip": zip,
            "map": map,
            "filter": filter,
            "any": any,
            "all": all,
            "abs": abs,
            "round": round,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "type": type,
            "isinstance": isinstance,
            "getattr": getattr,
            "hasattr": hasattr,
            "setattr": setattr,
            "chr": chr,
            "ord": ord,
            "repr": repr,
            "hex": hex,
            "oct": oct,
            "bin": bin,
            "format": format,
            "reversed": reversed,
            "iter": iter,
            "next": next,
            "callable": callable,
            "id": id,
            "hash": hash,
            "pow": pow,
            "divmod": divmod,
            "bytes": bytes,
            "bytearray": bytearray,
            "frozenset": frozenset,
            "object": object,
            "super": super,
            "property": property,
            "staticmethod": staticmethod,
            "classmethod": classmethod,
            "vars": vars,
            "dir": dir,
            "slice": slice,
            "Exception": Exception,
            "ValueError": ValueError,
            "RuntimeError": RuntimeError,
            "PermissionError": PermissionError,
            "FileNotFoundError": FileNotFoundError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "AttributeError": AttributeError,
            "IndexError": IndexError,
            "ImportError": ImportError,
            "StopIteration": StopIteration,
            "OSError": OSError,
            "IOError": IOError,
            "IsADirectoryError": IsADirectoryError,
            "NotImplementedError": NotImplementedError,
            "True": True,
            "False": False,
            "None": None,
            "open": _guarded_open,
            "__import__": _guarded_import,
            "locals": locals,
            "globals": globals,
        }

    def _execute_with_last_expression(self, code):
        parsed = ast.parse(code, mode="exec")
        if parsed.body and isinstance(parsed.body[-1], ast.Expr):
            setup_module = ast.Module(body=parsed.body[:-1], type_ignores=[])
            if setup_module.body:
                exec(compile(setup_module, "<assistant>", "exec"), self.execution_state, self.execution_state)
            expression = ast.Expression(parsed.body[-1].value)
            return eval(compile(expression, "<assistant>", "eval"), self.execution_state, self.execution_state)

        exec(compile(parsed, "<assistant>", "exec"), self.execution_state, self.execution_state)
        return None

    def _sanitize_code(self, code: str) -> str:
        sanitized = (code or "").strip()
        if not sanitized:
            return ""

        sanitized = re.sub(
            r"^\s*`{1,3}(?:python_waapi|python|py)?\s*\n?",
            "",
            sanitized,
            count=1,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(r"\n?\s*`{1,3}\s*$", "", sanitized, count=1)

        fenced_match = re.match(r"^```(?:python_waapi|python|py)?\s*\n([\s\S]*?)\n```$", sanitized, flags=re.IGNORECASE)
        if fenced_match:
            sanitized = fenced_match.group(1).strip()

        lines = sanitized.splitlines()
        if lines and re.match(r"^\s*(python_waapi|python|py)\s*$", lines[0], flags=re.IGNORECASE):
            lines = lines[1:]
        return "\n".join(lines).strip()

    def _format_result(self, value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except TypeError:
            return pprint.pformat(value, width=100, sort_dicts=False)

    def execute(self, code, mode="Agent Mode"):
        """
        Executes the provided Python code and returns stdout plus any final expression result.
        The code has access to self.context_globals.
        """
        # Create a string buffer to capture stdout
        output_buffer = io.StringIO()
        self.execution_state["__builtins__"] = self._build_safe_builtins(mode)
        result = None
        code = self._sanitize_code(code)
        if not code:
            return "Execution completed with no output."
        
        # We want to capture print() statements
        with contextlib.redirect_stdout(output_buffer):
            try:
                sys.settrace(self._cancel_trace)
                result = self._execute_with_last_expression(code)
            except CodeExecutionCancelled:
                print(CANCELLED_OUTPUT)
            except Exception as e:
                if not _is_known_shape_error(e):
                    import traceback
                    traceback.print_exc()
                print(f"Error executing code: {_build_execution_error_message(e)}")
            finally:
                sys.settrace(None)

        stdout_text = output_buffer.getvalue().rstrip()
        result_text = self._format_result(result).rstrip()

        if stdout_text and result_text:
            return f"{stdout_text}\n{result_text}"
        if stdout_text:
            return stdout_text
        if result_text:
            return result_text
        return "Execution completed with no output."

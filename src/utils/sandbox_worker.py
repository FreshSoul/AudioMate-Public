"""Sandbox worker — runs untrusted generated Python in an isolated process.

This module has NO Qt / GUI / waapi dependencies on purpose: the worker is
re-exec'd as a bare Python process (see ``main.py`` ``--sandbox-worker``) so it
loads as little as possible and holds none of the host's live objects.

Design (process-isolation plan, stage 1):
  * The worker runs ONE ``execute`` request then exits (one-shot per turn).
  * Every tool the generated code can call (waapi_client, analyze_*, normalize_*,
    write_*, call_structured_tool, run_powershell, fetch_webpage, …) is NOT
    present here. Each is a thin RPC proxy that forwards the call to the host
    process, where the real object lives. The worker is therefore a pure
    untrusted interpreter — it cannot do anything the host doesn't proxy.
  * The generated code's own ``print()`` output is captured via
    redirect_stdout and returned in the ``done`` message, so it never collides
    with the JSON-lines RPC channel on real stdout.

The security boundary is provided by (a) OS-level restrictions applied by the
host when it spawns this process (stage 3) and (b) AST hardening + import
denylist added in stage 2. Stage 1 establishes the process boundary and the
RPC plumbing only.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import pprint
import re
import sys
import threading

from src.utils import sandbox_rpc as rpc


CANCELLED_OUTPUT = "[System] 用户已暂停执行。"


class _Cancelled(BaseException):
    pass


class _Channel:
    """Blocking JSON-lines channel over the worker's real stdin/stdout.

    A single background reader thread owns stdin so that RPC results and cancel
    messages can be demultiplexed while the main thread is blocked waiting for a
    specific RPC result.
    """

    def __init__(self, stdin, stdout):
        self._in = stdin
        self._out = stdout
        self._lock = threading.Lock()
        self._results: dict[int, dict] = {}
        self._results_lock = threading.Lock()
        self._results_cv = threading.Condition(self._results_lock)
        self._cancelled = threading.Event()
        self._execute_msg: dict | None = None
        self._execute_cv = threading.Condition(threading.Lock())
        self._closed = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        for raw in self._in:
            try:
                msg = rpc.decode(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            except Exception:
                continue
            t = msg.get("t")
            if t == rpc.CANCEL:
                self._cancelled.set()
                with self._results_cv:
                    self._results_cv.notify_all()
            elif t == rpc.RPC_RESULT:
                with self._results_cv:
                    self._results[int(msg.get("id", -1))] = msg
                    self._results_cv.notify_all()
            elif t == rpc.EXECUTE:
                with self._execute_cv:
                    self._execute_msg = msg
                    self._execute_cv.notify_all()
        self._closed.set()
        with self._results_cv:
            self._results_cv.notify_all()

    def send(self, message: dict):
        with self._lock:
            self._out.write(rpc.encode(message))
            self._out.flush()

    def wait_for_execute(self) -> dict | None:
        with self._execute_cv:
            while self._execute_msg is None and not self._closed.is_set():
                self._execute_cv.wait(timeout=0.5)
            return self._execute_msg

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def wait_result(self, call_id: int) -> dict:
        with self._results_cv:
            while call_id not in self._results:
                if self._cancelled.is_set():
                    raise _Cancelled()
                if self._closed.is_set():
                    raise RuntimeError("sandbox channel closed before RPC result")
                self._results_cv.wait(timeout=0.5)
            return self._results.pop(call_id)


class _RpcContext:
    """Issues RPC calls to the host and builds the proxy objects/callables that
    stand in for the host's tools inside the sandbox globals."""

    def __init__(self, channel: _Channel):
        self._ch = channel
        self._next_id = 0
        self._id_lock = threading.Lock()

    def _alloc_id(self) -> int:
        with self._id_lock:
            self._next_id += 1
            return self._next_id

    def call(self, target: str, args, kwargs):
        call_id = self._alloc_id()
        self._ch.send(rpc.msg_rpc_call(call_id, target, list(args), dict(kwargs)))
        reply = self._ch.wait_result(call_id)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error") or f"tool '{target}' failed")
        return reply.get("value")

    def confirm(self, kind: str, payload) -> bool:
        call_id = self._alloc_id()
        self._ch.send(rpc.msg_confirm(call_id, kind, payload))
        reply = self._ch.wait_result(call_id)
        return bool(reply.get("ok")) and bool(reply.get("value"))

    def make_callable(self, name: str):
        def _proxy(*args, **kwargs):
            return self.call(name, args, kwargs)
        _proxy.__name__ = name
        return _proxy

    def make_object(self, name: str):
        return _RpcObjectProxy(self, name)


class _RpcObjectProxy:
    """Proxy for an injected object (e.g. waapi_client). Attribute access yields
    a method proxy that RPCs ``"<object>.<method>"`` to the host."""

    def __init__(self, ctx: _RpcContext, base: str):
        object.__setattr__(self, "_ctx", ctx)
        object.__setattr__(self, "_base", base)

    def __getattr__(self, method):
        ctx = object.__getattribute__(self, "_ctx")
        base = object.__getattribute__(self, "_base")
        target = f"{base}.{method}"

        def _method(*args, **kwargs):
            return ctx.call(target, args, kwargs)
        _method.__name__ = method
        return _method


# --- code sanitize + last-expression eval (mirrors CodeExecutor) ---

def _sanitize_code(code: str) -> str:
    sanitized = (code or "").strip()
    if not sanitized:
        return ""
    sanitized = re.sub(r"^\s*`{1,3}(?:python_waapi|python|py)?\s*\n?", "", sanitized, count=1, flags=re.IGNORECASE)
    sanitized = re.sub(r"\n?\s*`{1,3}\s*$", "", sanitized, count=1)
    fenced = re.match(r"^```(?:python_waapi|python|py)?\s*\n([\s\S]*?)\n```$", sanitized, flags=re.IGNORECASE)
    if fenced:
        sanitized = fenced.group(1).strip()
    lines = sanitized.splitlines()
    if lines and re.match(r"^\s*(python_waapi|python|py)\s*$", lines[0], flags=re.IGNORECASE):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _format_result(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return pprint.pformat(value, width=100, sort_dicts=False)


def _run_with_last_expression(code: str, state: dict):
    parsed = ast.parse(code, mode="exec")
    _assert_no_dunder_access(parsed)
    if parsed.body and isinstance(parsed.body[-1], ast.Expr):
        setup_module = ast.Module(body=parsed.body[:-1], type_ignores=[])
        if setup_module.body:
            exec(compile(setup_module, "<assistant>", "exec"), state, state)
        expression = ast.Expression(parsed.body[-1].value)
        return eval(compile(expression, "<assistant>", "eval"), state, state)
    exec(compile(parsed, "<assistant>", "exec"), state, state)
    return None


class SandboxSecurityError(Exception):
    """Raised when code uses a construct the sandbox forbids (dunder access)."""


def _assert_no_dunder_access(tree: ast.AST) -> None:
    """Reject dunder attribute/name access — the spine of every exec-sandbox
    escape (``().__class__.__base__.__subclasses__()``, ``f.__globals__`` …).

    Combined with removing ``getattr``/``type``/``object`` from builtins (so the
    string-based ``getattr(x, "__class__")`` bypass is also gone), this closes
    the object-graph traversal that reaches ``os``/``subprocess`` without import.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attr = node.attr or ""
            if attr.startswith("__") and attr.endswith("__"):
                raise SandboxSecurityError(
                    f"禁止访问双下划线属性 '{attr}'（沙箱安全限制）。"
                )
        elif isinstance(node, ast.Name):
            ident = node.id or ""
            if ident.startswith("__") and ident.endswith("__"):
                raise SandboxSecurityError(
                    f"禁止使用双下划线名称 '{ident}'（沙箱安全限制）。"
                )



def _build_globals(ctx: _RpcContext, manifest: dict) -> dict:
    """Build the sandbox globals from the host-supplied manifest.

    ``manifest`` = {"callables": [names], "objects": [names], "values": {name: json}}
    Callables/objects become RPC proxies; values are passed by value (constants
    the host wants available, e.g. mode strings).
    """
    # A module-level __name__ is required by CPython for `class` statement
    # creation. Set it to a sandbox sentinel rather than "__main__". This is a
    # value injected by us, not user source, so the AST dunder guard is unaffected.
    g: dict = {"__name__": "__sandbox__"}
    for name in manifest.get("objects", []) or []:
        g[name] = ctx.make_object(name)
    for name in manifest.get("callables", []) or []:
        g[name] = ctx.make_callable(name)
    for name, value in (manifest.get("values", {}) or {}).items():
        g[name] = value
    return g


def _build_import_hook(ctx: _RpcContext, safe_imports: set, mode: str):
    real_import = __import__
    # Reuse the in-process executor's hardened os/pathlib replacements
    # (pure-stdlib, no Qt) so `import os` inside the worker also cannot reach
    # os.system / os.remove / raw os.open — defense-in-depth beneath the Job
    # Object's no-child-process limit.
    try:
        from src.utils.execution import _SANDBOX_REPLACEMENTS
    except Exception:
        _SANDBOX_REPLACEMENTS = {}

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = (name or "").split(".")[0]
        # Hard denylist: never importable, not even with user approval. These
        # hand back raw process/native/serialization/introspection power that
        # would defeat the sandbox.
        if root in _IMPORT_DENYLIST or name in _IMPORT_DENYLIST:
            raise ImportError(
                f"Import '{name}' is permanently blocked in the sandbox (security)."
            )
        if root not in safe_imports:
            # Ask the host (which shows the GUI dialog) for out-of-allowlist,
            # non-denylisted modules.
            approved = False
            try:
                approved = ctx.confirm("import", {"module": name})
            except _Cancelled:
                raise
            except Exception:
                approved = False
            if not approved:
                raise ImportError(f"Import '{name}' is not allowed in {mode}.")
            safe_imports.add(root)
        # Hand back hardened os/pathlib so destructive calls raise PermissionError.
        if root in _SANDBOX_REPLACEMENTS:
            return _SANDBOX_REPLACEMENTS[root]
        return real_import(name, globals, locals, fromlist, level)

    return _guarded_import


# Stage-1 import allowlist mirrors the in-process executor's _SAFE_IMPORTS.
_SAFE_IMPORTS = frozenset({
    "base64", "collections", "copy", "csv", "datetime", "decimal", "functools",
    "glob", "itertools", "json", "math", "operator", "os", "pathlib", "random",
    "re", "statistics", "string", "time", "uuid",
})

# Stage-2 import HARD DENYLIST: these can NEVER be imported, even if a user
# clicks "allow" — they hand back raw process/native/serialization/introspection
# power that defeats the sandbox. Checked before the allowlist and before any
# confirmation prompt.
_IMPORT_DENYLIST = frozenset({
    "subprocess", "_posixsubprocess", "ctypes", "_ctypes", "cffi",
    "multiprocessing", "socket", "ssl", "asyncio",
    "marshal", "pickle", "pickletools", "shelve", "dill",
    "importlib", "imp", "builtins", "__builtin__", "runpy",
    "gc", "inspect", "sys", "code", "codeop",
    "pty", "signal", "mmap", "fcntl", "msvcrt", "winreg", "_winapi", "nt",
})

# Stage-2 curated builtins: the in-process executor's safe set MINUS the
# introspection primitives that enable sandbox escape (type/object/getattr/
# setattr/vars/super/globals/locals) and MINUS raw open (worker file I/O must
# go through host tools). type-checking still works via isinstance.
_SAFE_BUILTIN_NAMES = frozenset({
    "print", "len", "range", "enumerate", "min", "max", "sum", "sorted", "zip",
    "map", "filter", "any", "all", "abs", "round", "str", "int", "float", "bool",
    "list", "dict", "set", "tuple", "isinstance", "hasattr", "chr", "ord", "repr",
    "hex", "oct", "bin", "format", "reversed", "iter", "next", "callable", "id",
    "hash", "pow", "divmod", "bytes", "bytearray", "frozenset", "property",
    "staticmethod", "classmethod", "dir", "slice", "Exception", "ValueError",
    "RuntimeError", "PermissionError", "FileNotFoundError", "TypeError",
    "KeyError", "AttributeError", "IndexError", "ImportError", "StopIteration",
    "OSError", "IOError", "IsADirectoryError", "NotImplementedError",
    "True", "False", "None", "zip", "abs",
})



def _execute(channel: _Channel, code: str, mode: str, manifest: dict) -> dict:
    ctx = _RpcContext(channel)
    state = _build_globals(ctx, manifest)

    code = _sanitize_code(code)
    if not code:
        return rpc.msg_done("", "Execution completed with no output.", None)

    safe_imports = set(_SAFE_IMPORTS)
    guarded_import = _build_import_hook(ctx, safe_imports, mode)

    # Curated builtins: only the safe subset (no type/object/getattr/vars/super/
    # globals/locals/open/eval/exec/compile/__import__-as-name). The dunder AST
    # guard + this removal together close the object-graph escape path.
    import builtins as _b
    safe_builtins = {name: getattr(_b, name) for name in _SAFE_BUILTIN_NAMES if hasattr(_b, name)}
    safe_builtins["True"] = True
    safe_builtins["False"] = False
    safe_builtins["None"] = None
    safe_builtins["__import__"] = guarded_import
    # CPython needs __build_class__ in builtins for `class` statements. It is
    # never referenced by name in user source (the compiler emits it), so the
    # AST dunder guard does not reject legitimate class definitions; we just have
    # to make it available. It does not expand the escape surface on its own
    # because the dunder attribute guard still blocks reaching bases/mro/globals.
    safe_builtins["__build_class__"] = getattr(_b, "__build_class__")
    state["__builtins__"] = safe_builtins

    output_buffer = io.StringIO()
    result = None
    error = None
    with contextlib.redirect_stdout(output_buffer):
        try:
            result = _run_with_last_expression(code, state)
        except _Cancelled:
            print(CANCELLED_OUTPUT)
        except SystemExit:
            print(CANCELLED_OUTPUT)
        except Exception as exc:  # noqa: BLE001 — surface to the model, not crash
            import traceback
            traceback.print_exc()
            print(f"Error executing code: {exc}")
            error = str(exc)

    stdout_text = output_buffer.getvalue().rstrip()
    result_text = _format_result(result).rstrip()
    if stdout_text and result_text:
        combined = f"{stdout_text}\n{result_text}"
    elif stdout_text:
        combined = stdout_text
    elif result_text:
        combined = result_text
    else:
        combined = "Execution completed with no output."
    return rpc.msg_done(combined, "", error)


def main() -> int:
    """Worker entry point. Reads one execute request, runs it, emits done, exits."""
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    channel = _Channel(stdin, stdout)
    channel.send(rpc.msg_ready())

    execute_msg = channel.wait_for_execute()
    if execute_msg is None:
        return 0
    manifest = execute_msg.get("manifest") or {}
    try:
        done = _execute(channel, execute_msg.get("code", ""), execute_msg.get("mode", "Agent Mode"), manifest)
    except _Cancelled:
        done = rpc.msg_done(CANCELLED_OUTPUT, "", "cancelled")
    except Exception as exc:  # never leave the host hanging
        done = rpc.msg_done(f"Error executing code: {exc}", "", str(exc))
    channel.send(done)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Background QThread workers and connection helpers."""

import contextlib
import io
import json
import os
import re
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal

from src.services.openai_compatible_client import OpenAICompatibleClient
from src.utils.app_logger import get_logger
from src.tools.base import ToolContext, ToolResultStatus
from src.tools.permissions import is_ask_mode_waapi_uri_allowed


logger = get_logger(__name__)


class WorkerThread(QThread):
    token_received = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, llm_service, messages, system_blocks=None):
        super().__init__()
        self.llm_service = llm_service
        self.messages = messages
        # Optional structured system prompt (list[PromptBlock]). When provided,
        # the worker routes through stream_events so Anthropic gets
        # cache_control hints; otherwise falls back to legacy get_response.
        self.system_blocks = system_blocks
        self.is_interrupted = False

    def run(self):
        started_at = time.perf_counter()
        logger.info("LLM worker started")
        usage_info = None
        try:
            if self.system_blocks:
                from src.engine.prompt_blocks import (
                    assemble_for_anthropic,
                    assemble_as_string,
                )
                from src.llm.provider_events import (
                    TextDelta,
                    ThinkingDelta,
                    UsageInfo,
                    ProviderError,
                    FinishReason,
                )
                from src.llm.service import _is_anthropic_model

                model_name = getattr(self.llm_service, "model", "") or ""
                if _is_anthropic_model(model_name):
                    system_payload = assemble_for_anthropic(self.system_blocks)
                else:
                    system_payload = assemble_as_string(self.system_blocks)

                # Strip any leading system message — system goes via the
                # structured ``system`` parameter now.
                stripped = [
                    m for m in self.messages
                    if m.get("role") != "system"
                ]

                event_stream = self.llm_service.stream_events(
                    stripped, stream=True, system=system_payload,
                )
                for event in event_stream:
                    if self.is_interrupted:
                        logger.info("LLM worker interrupted")
                        break
                    if isinstance(event, TextDelta):
                        if event.text:
                            self.token_received.emit(event.text)
                    elif isinstance(event, ThinkingDelta):
                        # Phase 3 will surface this to UI. For now, drop.
                        pass
                    elif isinstance(event, UsageInfo):
                        usage_info = event
                    elif isinstance(event, ProviderError):
                        self.token_received.emit(event.message)
                    elif isinstance(event, FinishReason):
                        pass
            else:
                generator = self.llm_service.get_response(self.messages, stream=True)
                for chunk in generator:
                    if self.is_interrupted:
                        logger.info("LLM worker interrupted")
                        break
                    self.token_received.emit(chunk)
        except Exception as e:
            logger.exception("LLM worker failed")
            self.token_received.emit(f"\n\n[Error] LLM 请求异常: {e}")
        finally:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            if usage_info is not None:
                logger.info(
                    "LLM worker finished: elapsed_ms=%s input=%s output=%s "
                    "cache_read=%s cache_creation=%s",
                    elapsed_ms,
                    usage_info.input_tokens,
                    usage_info.output_tokens,
                    usage_info.cache_read_input_tokens,
                    usage_info.cache_creation_input_tokens,
                )
                # Hand off to turn-log if available — gathered out-of-band by
                # whoever wires in src.utils.turn_log.
                try:
                    from src.utils.turn_log import record_usage
                    record_usage(
                        model=getattr(self.llm_service, "model", "") or "",
                        elapsed_ms=elapsed_ms,
                        usage=usage_info,
                        system_blocks=self.system_blocks,
                    )
                except Exception:
                    pass
            else:
                logger.info("LLM worker finished: elapsed_ms=%s", elapsed_ms)
            self.finished_signal.emit()

    def stop(self):
        self.is_interrupted = True


class MemoryRefreshThread(QThread):
    finished_signal = pyqtSignal(str)

    def __init__(self, llm_service, messages, parent=None):
        super().__init__(parent)
        self.llm_service = llm_service
        self.messages = messages
        self.is_interrupted = False

    def run(self):
        started_at = time.perf_counter()
        logger.info("Memory refresh worker started")
        response = ""
        try:
            for chunk in self.llm_service.get_response(self.messages, stream=False, max_tokens=1600):
                if self.is_interrupted:
                    logger.info("Memory refresh worker interrupted")
                    return
                response += chunk
        except Exception as exc:
            logger.exception("Memory refresh worker failed")
            response = f"Error calling memory refresh LLM: {exc}"
        finally:
            logger.info("Memory refresh worker finished: elapsed_ms=%s", int((time.perf_counter() - started_at) * 1000))
            self.finished_signal.emit(response)

    def stop(self):
        self.is_interrupted = True


class CodeExecutionThread(QThread):
    finished_signal = pyqtSignal(str)

    def __init__(self, executor, code, mode, parent=None, owner=None):
        super().__init__(parent)
        self.executor = executor
        self.code = code
        self.mode = mode
        self.is_interrupted = False
        # When process isolation is enabled, the thread drives a SandboxHost
        # (subprocess) instead of executor.execute(). ``owner`` is the MainWindow,
        # needed to build the tool table + confirmation callbacks for the host.
        self.owner = owner
        self._sandbox_host = None

    def _process_isolation_enabled(self) -> bool:
        # Process isolation is the secure default. It can be turned OFF via:
        #   * env AUDIOMATE_SANDBOX_ISOLATION in ("0","false","off"), or
        #   * app setting sandbox_process_isolation == False.
        # An explicit env value always wins (useful for debugging/CI).
        env = os.environ.get("AUDIOMATE_SANDBOX_ISOLATION", "").strip().lower()
        if env in ("0", "false", "off", "no"):
            return False
        if env in ("1", "true", "on", "yes"):
            return True
        try:
            from src.utils.storage import load_app_settings
            setting = load_app_settings().get("sandbox_process_isolation", True)
            return bool(setting)
        except Exception:
            return True

    def run(self):
        started_at = time.perf_counter()
        isolation = self._process_isolation_enabled()
        logger.info("Code execution thread started: mode=%s isolation=%s", self.mode, isolation)
        try:
            if isolation and self.owner is not None:
                output = self._run_isolated()
            else:
                output = self.executor.execute(self.code, mode=self.mode)
        except Exception as exc:
            logger.exception("Code execution thread failed")
            output = f"Error executing code: {exc}"
        logger.info("Code execution thread finished: elapsed_ms=%s", int((time.perf_counter() - started_at) * 1000))
        self.finished_signal.emit(output)

    def _run_isolated(self) -> str:
        """Run the code in an isolated worker process via SandboxHost.

        The tool table is the resolved executor context (live waapi_client,
        agent_tools methods, structured-tool helpers); all of it stays in THIS
        process and the worker proxies calls back over RPC. Staged writes,
        confirmation dialogs and undo grouping are unaffected because the tools
        run here.
        """
        from src.utils.sandbox_host import SandboxHost
        tools = build_executor_context(self.owner)
        confirm_import = getattr(self.owner, "request_agent_import_confirmation", None)
        confirm_powershell = getattr(self.owner, "request_powershell_confirmation", None)
        host = SandboxHost(
            tools,
            confirm_import=confirm_import if callable(confirm_import) else None,
            confirm_powershell=confirm_powershell if callable(confirm_powershell) else None,
        )
        self._sandbox_host = host
        output = host.execute(self.code, mode=self.mode, tools=tools)
        if host.spawn_failed:
            # The worker could not even start (AV blocking subprocess, broken
            # frozen path, …). Rather than fail the user's task, fall back to
            # the in-process executor so the app keeps working. Logged loudly.
            logger.warning("Sandbox worker spawn failed; falling back to in-process execution")
            self._sandbox_host = None
            return self.executor.execute(self.code, mode=self.mode)
        return output

    def stop(self):
        self.is_interrupted = True
        host = self._sandbox_host
        if host is not None:
            # Isolated path: cancel then kill the worker process.
            host.request_cancel()
            host.kill()
            return
        request_cancel = getattr(self.executor, "request_cancel", None)
        if callable(request_cancel):
            request_cancel()


class _ModelFetcher(QThread):
    """后台线程：获取用户可用模型列表"""
    finished = pyqtSignal(list)  # list[str]

    def __init__(self, api_key: str, base_url: str, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.base_url = base_url

    def run(self):
        result = OpenAICompatibleClient.fetch_available_models(self.api_key, self.base_url)
        if result.get("ok") and result.get("models"):
            logger.info("Fetched remote model list: count=%s", len(result["models"]))
            self.finished.emit(result["models"])
        else:
            logger.warning("Failed to fetch remote model list: %s", result.get("error", "unknown"))
            self.finished.emit([])


class _WwiseConnector(QThread):
    """后台线程：尝试连接 Wwise，避免阻塞 UI"""
    result = pyqtSignal(bool)

    def __init__(self, waapi_client, parent=None):
        super().__init__(parent)
        self.waapi_client = waapi_client

    def run(self):
        import asyncio
        asyncio.set_event_loop(asyncio.new_event_loop())
        try:
            connected = self.waapi_client.connect()
            logger.info("Wwise connection attempt finished: connected=%s", connected)
            self.result.emit(connected)
        except Exception:
            logger.exception("Wwise connection attempt failed")
            self.result.emit(False)


class _ReadOnlyWwiseClient:
    """ASK Mode proxy: allows only explicitly approved non-destructive calls.

    Strategy: **default deny**. New WAAPI procedures are blocked until the
    permission policy marks them as safe for Ask Mode.
    """

    def __init__(self, base_client):
        self._base_client = base_client

    @property
    def connected(self):
        return self._base_client.connected

    @property
    def has_changes(self):
        return False

    def call(self, uri, args=None, options=None):
        if not is_ask_mode_waapi_uri_allowed(uri, args):
            raise PermissionError(
                f"Ask Mode 默认拒绝未显式标记为只读/安全的 WAAPI 调用: {uri}。"
                "如需修改项目数据或调用未授权过程，请切换到 Agent Mode。"
            )
        return self._base_client.call(uri, args=args, options=options)

    def get_selected_objects(self):
        return self._base_client.get_selected_objects()

    def get_property(self, object_id, property_name):
        return self._base_client.get_property(object_id, property_name)

    def get_schema(self, uri, include_examples=False):
        try:
            return self._base_client.get_schema(uri, include_examples=include_examples)
        except TypeError:
            return self._base_client.get_schema(uri)

    def get_functions(self):
        return self._base_client.get_functions()

    def get_wwise_version(self):
        return self._base_client.get_wwise_version()

    def set_property(self, object_id, property_name, value):
        raise PermissionError("Ask Mode 禁止修改属性。如需修改，请切换到 Agent Mode。")

    def begin_undo_group(self):
        return False

    def end_undo_group(self):
        pass

    def reset_changes(self):
        pass

    def list_source_files(self, filter_mode="all", folder="", recursive=True, return_fields=None):
        return self._base_client.list_source_files(
            filter_mode=filter_mode,
            folder=folder,
            recursive=recursive,
            return_fields=return_fields,
        )


_PYTHON_BLOCK_RE = re.compile(
    r"```(?:python|py)\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


def _extract_python_block(text: str) -> str | None:
    """Return the first ```python``` (or bare ```) code block in ``text``, or None.

    Tolerant of:
    - ```python\\n…\\n``` (preferred)
    - ```py\\n…\\n```
    - bare ```\\n…\\n``` when there is exactly one code block in the reply
    """
    if not text:
        return None
    m = _PYTHON_BLOCK_RE.search(text)
    if m is not None:
        return m.group(1).strip("\n")
    # Tolerate bare ``` … ``` blocks when there's exactly one.
    bare = re.findall(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    if len(bare) == 1:
        return bare[0].strip("\n")
    return None


_SAFE_BUILTINS = {
    name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
    for name in (
        "True", "False", "None",
        "abs", "all", "any", "bool", "dict", "enumerate", "float",
        "int", "isinstance", "len", "list", "map", "max", "min",
        "print", "range", "repr", "set", "sorted", "str", "sum", "tuple", "zip",
    )
    if (isinstance(__builtins__, dict) and name in __builtins__)
       or (not isinstance(__builtins__, dict) and hasattr(__builtins__, name))
}

# Top-level modules a sub-agent may import without prompting the user. Any
# module whose root package is not in this set triggers an interactive
# confirmation dialog routed through PetService.ask_import_permission.
_DEFAULT_ALLOWED_IMPORTS: frozenset = frozenset({
    "json", "re", "os", "sys", "math", "datetime", "time", "random",
    "itertools", "collections", "pathlib", "urllib", "requests",
    "string", "functools", "operator", "typing", "decimal", "fractions",
    "uuid", "hashlib", "base64", "html", "csv",
})


def _make_guarded_import(allowed_set: set, ask_user):
    """Return an ``__import__``-compatible callable for the sandbox.

    ``allowed_set`` is a *mutable* set seeded with the default allow-list
    plus anything the user has already approved in this dispatch. Any
    module whose root package is outside the set triggers ``ask_user(name)``;
    when the callback returns True the package root is cached so subsequent
    imports of the same module are silent.
    """
    real_import = __import__ if not isinstance(__builtins__, dict) else __builtins__["__import__"]

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        # Relative imports (level > 0) inside the sandbox have no parent
        # package, so just defer to the real importer for the error message.
        if level == 0 and name:
            top = name.split(".")[0]
            if top not in allowed_set:
                if ask_user is None or not ask_user(name):
                    raise ImportError(
                        f"sub-agent denied import of '{name}' by user"
                    )
                allowed_set.add(top)
        return real_import(name, globals, locals, fromlist, level)

    return guarded_import


def _make_restricted_plugin_call(plugin_runtime, allowed_plugin_ids):
    """Build a ``call_plugin_tool(name, input_data)`` closure that rejects
    any tool whose owning plugin id is not in ``allowed_plugin_ids``."""
    allowed_ids = set(allowed_plugin_ids or [])
    try:
        allowed_tool_names = {
            tool.get("name") for tool in (plugin_runtime.list_tools(allowed_plugin_ids=allowed_ids) or [])
            if tool.get("name")
        }
    except Exception:
        allowed_tool_names = set()

    def call_plugin_tool(name, input_data=None):
        tool_name = str(name or "")
        if tool_name not in allowed_tool_names:
            raise PermissionError(
                f"sub-agent has no permission to call '{tool_name}'. "
                f"Allowed tools: {sorted(allowed_tool_names) or '(none)'}"
            )
        return plugin_runtime.call_tool(
            tool_name,
            input_data if isinstance(input_data, dict) else {},
            mode="Agent Mode",
        )

    return call_plugin_tool


def _run_sub_agent_loop(
    llm_service,
    pet: dict,
    plugin_runtime,
    allowed_plugin_ids,
    user_prompt: str,
    *,
    max_steps: int = 3,
    max_tokens_per_step: int = 2048,
    ask_import_callback=None,
    extra_globals: dict | None = None,
) -> tuple[str, list[str]]:
    """Run a tiny code-execution loop for the sub-pet.

    Returns ``(final_reply, step_logs)``. ``step_logs`` is a list of short
    `[sub-agent NAME step k]` strings the caller can stream to stdout.

    ``ask_import_callback`` is called with ``module_name`` whenever the
    sandbox sees an import that is not in ``_DEFAULT_ALLOWED_IMPORTS``.
    Returning True allows the import (and caches the package root); False
    raises ImportError. Pass ``None`` to skip the prompt and reject every
    non-whitelisted import outright.
    """
    pet_name = pet.get("name", "sub-pet")
    persona = (pet.get("persona_prompt") or "").strip()

    tool_guidance = ""
    if plugin_runtime is not None and allowed_plugin_ids:
        try:
            tool_guidance = plugin_runtime.build_prompt_guidance(
                allowed_plugin_ids=set(allowed_plugin_ids)
            ) or ""
        except Exception:
            tool_guidance = ""

    base_system_lines = []
    if persona:
        base_system_lines.append(persona)
        base_system_lines.append("")
    base_system_lines.append(
        f"[Dispatch context] You are '{pet_name}', dispatched by the main agent "
        "to handle a specific task. Reply with a concise, actionable answer."
    )
    if tool_guidance:
        base_system_lines.append("")
        base_system_lines.append(tool_guidance.strip())
        base_system_lines.append(
            "To invoke a plugin tool, emit ONE ```python``` code block calling "
            "`call_plugin_tool(\"<tool_name>\", {...})` and print its result. "
            "After the harness runs the code, you will see the captured stdout "
            "as a follow-up user message; then write a final natural-language "
            "answer in a NEW assistant turn (no further code blocks)."
        )
    base_system_lines.append(
        "If no plugin call is needed, just answer in plain text. If you have "
        "already received tool output, summarise it for the main agent without "
        "another code block."
    )
    system_text = "\n".join(base_system_lines)

    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_prompt},
    ]

    call_plugin_tool = _make_restricted_plugin_call(plugin_runtime, allowed_plugin_ids) \
        if plugin_runtime is not None else None

    # Seed a mutable allow-set once per dispatch so user approvals cache
    # across the (up to 3) code-execution rounds inside this loop.
    import_allowed_set = set(_DEFAULT_ALLOWED_IMPORTS)
    guarded_import = _make_guarded_import(import_allowed_set, ask_import_callback)

    step_logs: list[str] = []
    last_reply = ""
    for step in range(1, max_steps + 1):
        reply = ""
        try:
            chunks = []
            for piece in llm_service.get_response(messages, stream=False,
                                                    max_tokens=max_tokens_per_step):
                if isinstance(piece, str):
                    chunks.append(piece)
            reply = "".join(chunks).strip()
        except Exception as exc:
            step_logs.append(f"[sub-agent {pet_name} step {step}] LLM error: {exc}")
            last_reply = f"sub-agent LLM 调用失败：{exc}"
            break

        last_reply = reply
        head = reply.replace("\n", " ")[:80]
        step_logs.append(f"[sub-agent {pet_name} step {step}] {head}")

        code = _extract_python_block(reply)
        if not code or call_plugin_tool is None:
            # No code block (final answer) OR no plugin runtime → return as-is.
            break

        # Execute the code block in a restricted sandbox; capture stdout.
        sandbox_builtins = dict(_SAFE_BUILTINS)
        sandbox_builtins["__import__"] = guarded_import
        sandbox_globals = {
            "__builtins__": sandbox_builtins,
            "call_plugin_tool": call_plugin_tool,
        }
        if extra_globals:
            for k, v in extra_globals.items():
                if k not in sandbox_globals:
                    sandbox_globals[k] = v
        sandbox_locals: dict = {}
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                exec(code, sandbox_globals, sandbox_locals)  # noqa: S102 — restricted env
            stdout_text = captured.getvalue().strip()
        except PermissionError as exc:
            stdout_text = f"[error] permission denied: {exc}"
        except Exception as exc:
            stdout_text = f"[error] {type(exc).__name__}: {exc}"

        if not stdout_text:
            stdout_text = "(no output)"
        # Feed the result back as a follow-up exchange.
        messages.append({"role": "assistant", "content": reply})
        messages.append({
            "role": "user",
            "content": f"工具执行结果：\n{stdout_text}\n\n请基于上述结果给出最终回答（不要再次写代码块）。",
        })

    return last_reply, step_logs


class _SubAgentFuture(dict):
    """Dict-like lazy proxy for a sub-pet dispatch result.

    The worker thread fills in ``ok / pet / reply / reason`` and sets the
    Event. Any dict access (``__getitem__`` / ``get`` / ``__contains__`` /
    iteration) waits on the Event first, so multiple calls in a single
    code block run in parallel and only join when the LLM actually reads
    a field.
    """

    def __init__(self):
        super().__init__()
        # Pre-populate the result schema so naive isinstance(x, dict) checks
        # behave as expected before the work finishes.
        super().__setitem__("ok", False)
        super().__setitem__("pet", "")
        super().__setitem__("reply", "")
        super().__setitem__("reason", "")
        self._done = threading.Event()

    def _fill(self, payload: dict) -> None:
        for key in ("ok", "pet", "reply", "reason"):
            if key in payload:
                super().__setitem__(key, payload[key])
        self._done.set()

    def _wait(self, timeout: float | None = None) -> None:
        # 120s ceiling per individual await is plenty for a single LLM call
        # and prevents the executor from deadlocking if a thread dies oddly.
        self._done.wait(timeout if timeout is not None else 180)

    def __getitem__(self, key):
        self._wait()
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._wait()
        return super().get(key, default)

    def __contains__(self, key):
        self._wait()
        return super().__contains__(key)

    def keys(self):
        self._wait()
        return super().keys()

    def values(self):
        self._wait()
        return super().values()

    def items(self):
        self._wait()
        return super().items()

    def __iter__(self):
        self._wait()
        return super().__iter__()

    def __repr__(self):
        if not self._done.is_set():
            return "<_SubAgentFuture pending>"
        return super().__repr__()


def build_executor_context(owner) -> dict:
    """Build the globals exposed to generated Python code.

    Kept outside MainWindow so runtime permissions/tool wiring can evolve
    without further inflating the GUI class.
    """
    is_ask_mode = hasattr(owner, "mode_selector") and owner.mode_selector.currentText() == "Ask Mode"
    execution_client = _ReadOnlyWwiseClient(owner.waapi_client) if is_ask_mode else owner.waapi_client

    # Wire (or clear) the import-confirmation callback on the shared executor.
    # In Agent Mode, an import outside the safe allow-list prompts the user via
    # a GUI dialog; approval is cached on the executor for the rest of the
    # session. In Ask Mode such imports stay blocked outright.
    _executor = getattr(owner, "code_executor", None)
    if _executor is not None:
        if not is_ask_mode and hasattr(owner, "request_agent_import_confirmation"):
            _executor.ask_import_callback = owner.request_agent_import_confirmation
        else:
            _executor.ask_import_callback = None

    # Route destructive audio writes (normalize) through the same staged
    # confirmation pipeline as write_user_file: in Agent Mode the toolbox stages
    # the write onto the executor's pending list so the FileWriteConfirmWidget
    # gates it; in Ask Mode the write tools are blocked outright (below) so no
    # stager is needed.
    _toolbox = getattr(owner, "agent_tools", None)
    if _toolbox is not None:
        if not is_ask_mode and _executor is not None and hasattr(_executor, "stage_audio_write"):
            _toolbox.file_write_stager = _executor.stage_audio_write
        else:
            _toolbox.file_write_stager = None

    def call_structured_tool(name, input_data=None):
        registry = getattr(owner, "tool_registry", None)
        if registry is None:
            return {"error": "Tool registry is not available."}
        tool = registry.find_tool(str(name or ""))
        if tool is None:
            return {"error": f"Unknown structured tool: {name}"}
        payload = input_data if isinstance(input_data, dict) else {}
        context = ToolContext(
            waapi_client=execution_client,
            toolbox=getattr(owner, "agent_tools", None),
            mode="Ask Mode" if is_ask_mode else "Agent Mode",
            parent_widget=owner,
            extra={"code_executor": getattr(owner, "code_executor", None)},
        )
        validation = tool.validate_input(payload)
        if not validation.valid:
            return {"error": validation.error or "Tool input is invalid."}
        permission = tool.check_permissions(payload, context)
        if not permission.allowed:
            return {"error": permission.reason or "Tool permission denied."}
        if tool.requires_waapi() and not getattr(execution_client, "connected", False):
            return {"error": f"Tool '{tool.name}' requires a live Wwise/WAAPI connection."}
        result = tool.execute(payload, context)
        if result.status == ToolResultStatus.PERMISSION_DENIED:
            return {"error": result.output or "Tool permission denied."}
        if result.is_error:
            return result.data if isinstance(result.data, dict) else {"error": result.output}
        return result.data if result.data is not None else {"output": result.output}

    def get_waapi_schema(uri, include_examples=False):
        resolved_uri = str(uri or "").strip()
        if not resolved_uri:
            return {"error": "WAAPI schema lookup requires a non-empty URI."}
        getter = getattr(execution_client, "get_schema", None)
        if not callable(getter):
            return {"error": "WAAPI schema lookup is not available in this context."}
        try:
            return getter(resolved_uri, include_examples=bool(include_examples))
        except TypeError:
            return getter(resolved_uri)

    def dispatch_codex_agent(prompt: str, cwd: str = "", allow_writes: bool = False, timeout_seconds: int = 900) -> dict:
        return call_structured_tool("external_agent.codex", {
            "prompt": prompt,
            "cwd": cwd,
            "allow_writes": bool(allow_writes),
            "timeout_seconds": timeout_seconds,
        })

    def dispatch_claude_code_agent(prompt: str, cwd: str = "", allow_writes: bool = False, timeout_seconds: int = 900) -> dict:
        return call_structured_tool("external_agent.claude_code", {
            "prompt": prompt,
            "cwd": cwd,
            "allow_writes": bool(allow_writes),
            "timeout_seconds": timeout_seconds,
        })

    def run_powershell(command: str, cwd: str = "", timeout_seconds: int = 120,
                       max_output_chars: int = 24000, shell: str = "auto") -> dict:
        return call_structured_tool("powershell.run", {
            "command": command,
            "cwd": cwd,
            "timeout_seconds": timeout_seconds,
            "max_output_chars": max_output_chars,
            "shell": shell,
        })

    ctx = {
        "waapi_client": execution_client,
        "client": execution_client,
        "agent_tools": owner.agent_tools,
        "call_structured_tool": call_structured_tool,
        "list_structured_tools": lambda: json.loads(owner.tool_registry.build_tools_manifest_prompt(mode="Ask Mode" if is_ask_mode else "Agent Mode")),
        "request_user_file_access": owner.agent_tools.request_user_file_access,
        "list_authorized_files": owner.agent_tools.list_authorized_files,
        "read_user_file": owner.agent_tools.read_user_file,
        "read_csv": owner.agent_tools.read_csv,
        "read_xlsx": owner.agent_tools.read_xlsx,
        "read_docx": owner.agent_tools.read_docx,
        "read_pptx": owner.agent_tools.read_pptx,
        "list_local_directory": owner.agent_tools.list_local_directory,
        "describe_local_path": owner.agent_tools.describe_local_path,
        "analyze_audio_file": owner.agent_tools.analyze_audio_file,
        "analyze_wav_file": owner.agent_tools.analyze_wav_file,
        "analyze_directory_loudness": owner.agent_tools.analyze_directory_loudness,
        "check_directory_loudness_compliance": owner.agent_tools.check_directory_loudness_compliance,
        "detect_audio_anomalies": owner.agent_tools.detect_audio_anomalies,
        "detect_directory_anomalies": owner.agent_tools.detect_directory_anomalies,
        "validate_project_structure": owner.agent_tools.validate_project_structure,
        "analyze_selected_source_files_loudness": owner.agent_tools.analyze_selected_source_files_loudness,
        "analyze_project_source_files_loudness": owner.agent_tools.analyze_project_source_files_loudness,
        "analyze_selected_sources_full_route_loudness": owner.agent_tools.analyze_selected_sources_full_route_loudness,
        "get_project_source_files": owner.agent_tools.get_project_source_files,
        "get_selected_source_files": owner.agent_tools.get_selected_source_files,
        "get_selected_source_filepaths": owner.agent_tools.get_selected_source_filepaths,
        "lookup_waapi_doc": owner.waapi_retriever.lookup_doc,
        "search_waapi_functions": owner.waapi_retriever.search_functions,
        "get_waapi_schema": get_waapi_schema,
        "dispatch_codex_agent": dispatch_codex_agent,
        "dispatch_claude_code_agent": dispatch_claude_code_agent,
        "run_powershell": run_powershell,
        "fetch_webpage": owner.fetch_webpage,
        "get_active_mcp_config": owner.get_active_mcp_config,
        "list_mcp_tools": owner.list_mcp_tools,
        "call_mcp_tool": owner.call_mcp_tool,
        "read_feishu_doc": owner.read_feishu_doc,
    }

    pet_service = getattr(owner, "pet_service", None)
    if pet_service is not None:
        def dispatch_sub_pet(name: str, prompt: str = "") -> dict:
            """Hand a task off to a named sub-pet (independent sub-agent).

            Returns a dict-like ``_SubAgentFuture`` immediately and runs the
            sub-agent LLM call in a background thread. Multiple calls in
            the same code block therefore run CONCURRENTLY (wallclock parallel).
            The future blocks on the worker only when the caller actually
            reads a field, e.g. ``result["reply"]``.

            Schema: ``{"ok": bool, "pet": str, "reply": str, "reason": str}``.
            """
            future = _SubAgentFuture()
            pet = pet_service.find_sub_pet_by_name(str(name or ""))
            if pet is None:
                msg = f"未找到名为 '{name}' 的副宠。"
                print(f"[sub-agent] ❌ {msg}")
                future._fill({"ok": False, "pet": str(name or ""), "reply": "", "reason": msg})
                return future
            user_prompt = (str(prompt or "").strip()
                           or (pet.get("task_template") or "").strip())
            if not user_prompt:
                msg = "未提供 prompt，且该副宠没有 task_template。"
                print(f"[sub-agent {pet.get('name', '')}] ❌ {msg}")
                future._fill({"ok": False, "pet": pet.get("name", ""), "reply": "", "reason": msg})
                return future

            llm = getattr(owner, "llm_service", None)
            if llm is None:
                msg = "LLM service 不可用。"
                print(f"[sub-agent {pet.get('name', '')}] ❌ {msg}")
                future._fill({"ok": False, "pet": pet.get("name", ""), "reply": "", "reason": msg})
                return future

            # Per-pet LLM override: a sub-pet may carry its own base_url /
            # api_key / model (empty fields inherit the main config). Build a
            # FRESH LLMService — never set_config on the shared owner service;
            # these worker threads run concurrently with the main chat.
            try:
                from src.llm.service import LLMService
                from src.pet.store import resolve_pet_llm_config
                resolved = resolve_pet_llm_config(
                    pet,
                    fallback_api_key=getattr(llm, "api_key", "") or "",
                    fallback_base_url=getattr(llm, "base_url", "") or "",
                    fallback_model=getattr(llm, "model", "") or "",
                )
                if resolved["is_override"]:
                    llm = LLMService(
                        api_key=resolved["api_key"],
                        base_url=resolved["base_url"],
                        model=resolved["model"],
                    )
                    print(f"[sub-agent {pet.get('name', '')}] 使用副宠模型: {resolved['model']}")
            except Exception as exc:
                logger.warning("Per-pet LLM override failed; using shared service: %s", exc)

            pet_name = pet.get("name", "")
            pet_id = pet.get("id", "")

            # Resolve which plugin ids this sub-pet is allowed to call. The
            # sub-agent does NOT inherit the default pool — that's an
            # active-main privilege.
            allowed_plugin_ids: set[str] = set()
            try:
                caps = pet.get("capabilities") or {}
                allowed_plugin_ids = {
                    str(pid) for pid in (caps.get("plugin_ids") or []) if pid
                }
            except Exception:
                allowed_plugin_ids = set()

            plugin_runtime = getattr(owner, "plugin_runtime", None)

            run_id = pet_service.register_sub_agent_run(pet_id, pet_name)
            print(f"[sub-agent {pet_name}] 派遣中… (run={run_id[:8]})")
            external_agent = str(pet.get("external_agent") or "").strip().lower()
            external_tool_name = {
                "codex": "external_agent.codex",
                "claude_code": "external_agent.claude_code",
                "claudecode": "external_agent.claude_code",
            }.get(external_agent)

            if external_tool_name:
                def _external_worker():
                    try:
                        result = call_structured_tool(external_tool_name, {
                            "prompt": user_prompt,
                            "cwd": os.getcwd(),
                            "allow_writes": False,
                            "timeout_seconds": 1800,
                        })
                        ok = bool(isinstance(result, dict) and result.get("ok"))
                        reply = ""
                        if isinstance(result, dict):
                            reply = (
                                result.get("output")
                                or result.get("stdout")
                                or result.get("stderr")
                                or result.get("error")
                                or json.dumps(result, ensure_ascii=False)
                            )
                        else:
                            reply = str(result or "")
                        reply = str(reply or "").strip()
                        if not ok:
                            print(f"[sub-agent {pet_name}] ❌ 外部 Agent 返回失败：{reply}")
                            try:
                                pet_service.record_task_completion(
                                    source="pet", title="外部 Agent 派遣",
                                    success=False, pet_id=pet_id, detail=reply[:200],
                                )
                            except Exception:
                                pass
                            pet_service.finish_sub_agent_run(run_id, False, reply[:80])
                            future._fill({
                                "ok": False, "pet": pet_name, "reply": reply,
                                "reason": "external agent failed.",
                            })
                            return
                        print(f"[sub-agent {pet_name}] {reply}")
                        snippet = reply.replace("\n", " ").strip()
                        if len(snippet) > 80:
                            snippet = snippet[:77] + "…"
                        try:
                            pet_service.record_task_completion(
                                source="pet", title="外部 Agent 派遣",
                                success=True, pet_id=pet_id, detail=reply[:200],
                            )
                        except Exception:
                            pass
                        pet_service.finish_sub_agent_run(run_id, True, snippet)
                        future._fill({
                            "ok": True, "pet": pet_name, "reply": reply,
                            "reason": "external agent returned.",
                        })
                    except Exception as exc:
                        msg = f"external agent dispatch failed: {exc}"
                        print(f"[sub-agent {pet_name}] ❌ {msg}")
                        try:
                            pet_service.record_task_completion(
                                source="pet", title="外部 Agent 派遣",
                                success=False, pet_id=pet_id, detail=msg,
                            )
                        except Exception:
                            pass
                        pet_service.finish_sub_agent_run(run_id, False, msg[:80])
                        future._fill({
                            "ok": False, "pet": pet_name, "reply": "",
                            "reason": msg,
                        })

                threading.Thread(target=_external_worker, daemon=True,
                                 name=f"sub-agent-{pet_name or 'external'}").start()
                return future

            def _worker():
                def _ask_import(module_name: str) -> bool:
                    try:
                        return bool(pet_service.ask_import_permission(
                            pet_name or "副宠", module_name,
                        ))
                    except Exception:
                        return False
                agent_tools_obj = getattr(owner, "agent_tools", None)
                sub_extra_globals: dict = {}
                if agent_tools_obj is not None:
                    sub_extra_globals.update({
                        "read_user_file": agent_tools_obj.read_user_file,
                        "read_csv": agent_tools_obj.read_csv,
                        "read_xlsx": agent_tools_obj.read_xlsx,
                        "read_docx": agent_tools_obj.read_docx,
                        "read_pptx": agent_tools_obj.read_pptx,
                    })
                try:
                    reply, step_logs = _run_sub_agent_loop(
                        llm, pet, plugin_runtime, allowed_plugin_ids, user_prompt,
                        ask_import_callback=_ask_import,
                        extra_globals=sub_extra_globals or None,
                    )
                except Exception as exc:
                    print(f"[sub-agent {pet_name}] ❌ loop 异常：{exc}")
                    try:
                        pet_service.record_task_completion(
                            source="pet", title="派遣任务",
                            success=False, pet_id=pet_id,
                            detail=f"loop 异常：{exc}",
                        )
                    except Exception:
                        pass
                    pet_service.finish_sub_agent_run(run_id, False, str(exc)[:80])
                    future._fill({
                        "ok": False, "pet": pet_name, "reply": "",
                        "reason": f"sub-agent 循环异常：{exc}",
                    })
                    return

                for line in step_logs:
                    print(line)

                if reply.lower().startswith("error"):
                    print(f"[sub-agent {pet_name}] ❌ 返回错误：{reply}")
                    try:
                        pet_service.record_task_completion(
                            source="pet", title="派遣任务",
                            success=False, pet_id=pet_id, detail=reply[:200],
                        )
                    except Exception:
                        pass
                    pet_service.finish_sub_agent_run(run_id, False, reply[:80])
                    future._fill({
                        "ok": False, "pet": pet_name, "reply": reply,
                        "reason": "sub-agent 返回错误。",
                    })
                    return

                print(f"[sub-agent {pet_name}] {reply}")

                snippet = reply.replace("\n", " ").strip()
                if len(snippet) > 80:
                    snippet = snippet[:77] + "…"
                try:
                    pet_service.main_pet_announcement.emit(
                        f"{pet_name or '副宠'}：{snippet}" if snippet
                        else f"{pet_name or '副宠'} 已完成委派任务",
                        "info",
                    )
                except Exception:
                    pass
                try:
                    task_title_snippet = (user_prompt or "").strip().splitlines()[0]
                    if len(task_title_snippet) > 60:
                        task_title_snippet = task_title_snippet[:57] + "…"
                    pet_service.record_task_completion(
                        source="pet",
                        title=task_title_snippet or "派遣任务",
                        success=True, pet_id=pet_id, detail=reply[:200],
                    )
                except Exception:
                    pass
                pet_service.finish_sub_agent_run(run_id, True, snippet)
                future._fill({
                    "ok": True, "pet": pet_name, "reply": reply,
                    "reason": "sub-agent 已返回。",
                })

            thread = threading.Thread(target=_worker, daemon=True,
                                       name=f"sub-agent-{pet_name or 'pet'}")
            thread.start()
            return future

        ctx["dispatch_sub_pet"] = dispatch_sub_pet
    else:
        # Even when the pet service is not ready, expose a stub so that
        # generated code calling dispatch_sub_pet gets a clear structured
        # error rather than a NameError.
        def dispatch_sub_pet(name: str, prompt: str = "") -> dict:
            print("[sub-agent] ❌ pet_service 未就绪，无法派遣副宠。")
            return {"ok": False, "pet": str(name or ""), "reply": "",
                    "reason": "pet_service 未就绪。"}
        ctx["dispatch_sub_pet"] = dispatch_sub_pet

    if is_ask_mode:
        def _blocked_normalize(*_a, **_kw):
            raise PermissionError("normalize_audio_loudness is a write operation and is not available in Ask Mode.")

        def _blocked_write_file(*_a, **_kw):
            raise PermissionError("write_user_file is a write operation and is not available in Ask Mode.")

        def _blocked_write_file_tree(*_a, **_kw):
            raise PermissionError("write_file_tree is a write operation and is not available in Ask Mode.")

        def _blocked_import_audio(*_a, **_kw):
            raise PermissionError("import_audio_files_to_selected_wwise is a write operation and is not available in Ask Mode.")

        def _blocked_powershell(*_a, **_kw):
            raise PermissionError("run_powershell is only available in Agent Mode and requires user confirmation.")

        def _ask_mode_batch_normalize(*args, **kwargs):
            # Dry-run (apply=False) is read-only and allowed; applying is blocked.
            if kwargs.get("apply"):
                raise PermissionError(
                    "batch_normalize_directory_to_target with apply=True is a write operation and is not available in Ask Mode."
                )
            return owner.agent_tools.batch_normalize_directory_to_target(*args, **kwargs)

        ctx["normalize_audio_loudness"] = _blocked_normalize
        ctx["batch_normalize_directory_to_target"] = _ask_mode_batch_normalize
        ctx["write_user_file"] = _blocked_write_file
        ctx["write_file_tree"] = _blocked_write_file_tree
        ctx["import_audio_files_to_selected_wwise"] = _blocked_import_audio
        ctx["run_powershell"] = _blocked_powershell
    else:
        ctx["normalize_audio_loudness"] = owner.agent_tools.normalize_audio_loudness
        ctx["batch_normalize_directory_to_target"] = owner.agent_tools.batch_normalize_directory_to_target
        ctx["write_user_file"] = lambda path, content, overwrite=True, mkdir=True, encoding="utf-8": call_structured_tool(
            "write_user_file",
            {"path": path, "content": content, "overwrite": overwrite, "mkdir": mkdir, "encoding": encoding},
        )
        ctx["write_file_tree"] = lambda base_dir, files, encoding="utf-8": call_structured_tool("write_file_tree", {"base_dir": base_dir, "files": files, "encoding": encoding})
        ctx["import_audio_files_to_selected_wwise"] = owner.agent_tools.import_audio_files_to_selected_wwise

    if hasattr(owner, "plugin_runtime"):
        ctx.update(owner.plugin_runtime.context_functions(lambda: "Ask Mode" if is_ask_mode else "Agent Mode"))
    return ctx

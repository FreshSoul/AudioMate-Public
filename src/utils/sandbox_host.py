"""Sandbox host — main-process manager for the isolated code-execution worker.

Spawns the worker (a re-exec of this app with ``--sandbox-worker``), ships it
one ``execute`` request, then services the worker's RPC calls by invoking the
REAL tools in this (main) process and sending results back. Returns the
worker's captured stdout/result string — the same contract as the legacy
``CodeExecutor.execute()`` so the GUI lifecycle downstream is unchanged.

Tools, the live ``waapi_client``, staged-write buffering and the confirmation
dialogs all stay in the main process; the worker only runs untrusted Python and
proxies every tool call back here. The security boundary is the OS restriction
applied at spawn time (stage 3) plus the worker's AST/import hardening (stage 2).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from src.utils import sandbox_rpc as rpc
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

# How long a single worker run may take before we kill it (seconds). Generous —
# real audio/WAAPI work runs in the main process via RPC, not in the worker.
_DEFAULT_TIMEOUT = 600.0


def _worker_argv_env() -> tuple[list[str], dict]:
    """Build (argv, env) to launch the worker as a fresh process.

    Frozen (PyInstaller onedir): re-exec the app exe with the flag — the
    bootloader runs main.py which dispatches to the worker before loading Qt.

    Dev: use the REAL base interpreter (sys._base_executable), NOT the venv
    ``python.exe`` launcher. The launcher spawns the real interpreter as a child
    at startup, which the Job Object's ActiveProcessLimit=1 (no child processes)
    would block. Running the base interpreter directly avoids that startup
    child; the venv's site-packages are made importable via PYTHONPATH.
    """
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        return [sys.executable, "--sandbox-worker"], env

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main_py = os.path.join(project_root, "main.py")
    base_exe = getattr(sys, "_base_executable", None) or sys.executable
    # Make the current (venv) site-packages + project root importable to the
    # base interpreter so the worker can import src.* and third-party deps.
    extra_paths = [p for p in sys.path if p and ("site-packages" in p or p == project_root)]
    if project_root not in extra_paths:
        extra_paths.append(project_root)
    existing = env.get("PYTHONPATH", "")
    combined = os.pathsep.join([p for p in extra_paths if p] + ([existing] if existing else []))
    env["PYTHONPATH"] = combined
    return [base_exe, main_py, "--sandbox-worker"], env


class _ToolDispatcher:
    """Resolves an RPC ``target`` against the host tool table and calls it.

    ``tools`` is the resolved executor-context dict (callables + live objects)
    built by ``build_executor_context``. A bare name calls ``tools[name](*a)``;
    a dotted ``obj.method`` resolves the object from ``tools`` and calls the
    attribute. Anything not present is denied (never silently succeeds).
    """

    def __init__(self, tools: dict):
        self._tools = tools or {}

    def dispatch(self, target: str, args: list, kwargs: dict):
        if "." in target:
            base, _, method = target.partition(".")
            obj = self._tools.get(base)
            if obj is None:
                raise NameError(f"'{base}' is not available in the sandbox")
            fn = getattr(obj, method, None)
            if not callable(fn):
                raise AttributeError(f"'{base}.{method}' is not callable")
            return fn(*args, **kwargs)
        fn = self._tools.get(target)
        if not callable(fn):
            raise NameError(f"'{target}' is not available in the sandbox")
        return fn(*args, **kwargs)


class SandboxHost:
    """Runs one code string in an isolated worker and returns its output string."""

    def __init__(self, tools: dict, *, confirm_import=None, confirm_powershell=None,
                 apply_os_restrictions=None):
        self._dispatcher = _ToolDispatcher(tools)
        self._confirm_import = confirm_import
        self._confirm_powershell = confirm_powershell
        self._apply_os_restrictions = apply_os_restrictions
        self._proc: subprocess.Popen | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        # Set True if the worker process could not be spawned at all — lets the
        # caller fall back to in-process execution so the app never hard-breaks.
        self.spawn_failed = False

    # --- manifest: which names the worker should proxy back to us ---
    def _manifest(self, tools: dict) -> dict:
        objects, callables, values = [], [], {}
        for name, value in tools.items():
            if callable(value) and not _looks_like_object(value):
                callables.append(name)
            else:
                # Live objects (waapi_client, client, agent_tools proxies…)
                objects.append(name)
        return {"objects": objects, "callables": callables, "values": values}

    def request_cancel(self):
        self._cancel.set()
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.stdin.write(rpc.encode(rpc.msg_cancel()))
                proc.stdin.flush()
            except Exception:
                pass

    def is_cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def kill(self):
        with self._lock:
            proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            pass

    def execute(self, code: str, mode: str = "Agent Mode", *, tools: dict = None,
                timeout: float = _DEFAULT_TIMEOUT) -> str:
        tool_table = tools if tools is not None else self._dispatcher._tools
        dispatcher = _ToolDispatcher(tool_table)
        manifest = self._manifest(tool_table)

        argv, env = _worker_argv_env()
        # Hide the worker's console WITHOUT CREATE_NO_WINDOW: that flag, combined
        # with a Job Object, breaks the stdout pipe handshake on Windows. Use
        # STARTUPINFO + SW_HIDE instead, which coexists with the Job Object.
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
                close_fds=True,
                env=env,
            )
        except Exception as exc:
            logger.exception("Failed to spawn sandbox worker")
            self.spawn_failed = True
            return f"Error executing code: 无法启动沙箱进程: {exc}"

        with self._lock:
            self._proc = proc

        # OS-level restriction: assign the worker to a Job Object that forbids
        # child processes (ActiveProcessLimit=1), caps memory, and kills the
        # tree when the handle closes. Keep the handle alive for the run.
        job_handle = None
        try:
            from src.utils import os_sandbox_win
            job_handle = os_sandbox_win.apply_restrictions(proc)
        except Exception:
            logger.exception("Failed to apply OS sandbox restrictions")
        # Legacy/extra hook (tests may inject one).
        if callable(self._apply_os_restrictions):
            try:
                self._apply_os_restrictions(proc)
            except Exception:
                logger.exception("Custom OS restriction hook failed")

        result_holder: dict = {}
        try:
            self._pump(proc, code, mode, manifest, dispatcher, result_holder, timeout)
        finally:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
            if job_handle is not None:
                job_handle.close()  # KILL_ON_JOB_CLOSE ends any survivors
            with self._lock:
                self._proc = None

        if self._cancel.is_set() and "output" not in result_holder:
            return "[System] 用户已暂停执行。"
        return result_holder.get("output", "Execution completed with no output.")

    def _pump(self, proc, code, mode, manifest, dispatcher, result_holder, timeout):
        """Drive the worker: wait for ready, send execute, service RPC until done."""
        deadline_timer = threading.Timer(timeout, self.kill)
        deadline_timer.daemon = True
        deadline_timer.start()
        try:
            # Use readline(), NOT `for line in proc.stdout`: file-iteration does
            # read-ahead buffering and will not yield a single line until the
            # buffer fills or EOF — which deadlocks our request/response protocol
            # where the worker sends one line then waits for our reply.
            while True:
                raw = proc.stdout.readline()
                if not raw:
                    break  # worker closed stdout / exited
                try:
                    msg = rpc.decode(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                except Exception:
                    continue
                t = msg.get("t")
                if t == rpc.READY:
                    self._send(proc, {**rpc.msg_execute(code, mode), "manifest": manifest})
                elif t == rpc.RPC_CALL:
                    self._handle_rpc_call(proc, msg, dispatcher)
                elif t == rpc.CONFIRM:
                    self._handle_confirm(proc, msg)
                elif t == rpc.DONE:
                    result_holder["output"] = msg.get("stdout") or msg.get("result") or \
                        "Execution completed with no output."
                    break
        finally:
            deadline_timer.cancel()

    def _send(self, proc, message: dict):
        try:
            proc.stdin.write(rpc.encode(message))
            proc.stdin.flush()
        except Exception:
            pass

    def _handle_rpc_call(self, proc, msg, dispatcher):
        call_id = int(msg.get("id", -1))
        target = msg.get("target", "")
        args = msg.get("args", []) or []
        kwargs = msg.get("kwargs", {}) or {}
        try:
            value = dispatcher.dispatch(target, args, kwargs)
            self._send(proc, rpc.msg_rpc_result(call_id, True, _jsonable(value)))
        except Exception as exc:
            self._send(proc, rpc.msg_rpc_result(call_id, False, None, str(exc)))

    def _handle_confirm(self, proc, msg):
        call_id = int(msg.get("id", -1))
        kind = msg.get("kind")
        payload = msg.get("payload") or {}
        approved = False
        try:
            if kind == "import" and callable(self._confirm_import):
                approved = bool(self._confirm_import(payload.get("module", "")))
            elif kind == "powershell" and callable(self._confirm_powershell):
                approved = bool(self._confirm_powershell(payload))
        except Exception:
            approved = False
        self._send(proc, rpc.msg_rpc_result(call_id, approved, approved))


def _looks_like_object(value) -> bool:
    """Heuristic: treat plain functions/lambdas/bound methods as callables, and
    everything else callable (class instances exposing __call__, client objects)
    as objects whose methods are proxied. We classify by 'has interesting public
    methods' — but to keep stage 1 simple and correct, only the known live
    objects are objects; bare callables are callables."""
    import types
    return not isinstance(value, (types.FunctionType, types.BuiltinFunctionType,
                                  types.MethodType, types.LambdaType))


def _jsonable(value):
    """Best-effort reduce a tool return value to JSON-safe data for transport.

    Most tools already return dict/list/str/number. AnalysisReport is a dict
    subclass so it passes through. Anything exotic degrades to str via the
    encoder's default=str, but we proactively coerce common containers here.
    """
    import json
    try:
        json.dumps(value, default=str)
        return value
    except Exception:
        return str(value)

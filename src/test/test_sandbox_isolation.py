"""Stage-1 process-isolation sandbox tests.

These exercise the host<->worker RPC boundary directly (no Qt), proving:
  * the worker runs untrusted code in a separate process,
  * tool calls proxy back to the host and run there,
  * import confirmation round-trips,
  * a hung worker can be killed (the cancellation that settrace alone can't do),
  * a worker crash does not take down the host.

OS-level restrictions (stage 3) and AST/import hardening (stage 2) are tested
separately once added.
"""

import math
import os
import sys
import tempfile
import threading
import time

import numpy as np
import soundfile as sf

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.sandbox_host import SandboxHost
from src.utils.agent_tools import AgentToolbox


class _DummyWaapi:
    connected = True

    def get_selected_objects(self):
        return {"objects": [{"id": "{1}", "name": "Sound1"}]}

    def call(self, uri, args=None, options=None):
        return {"return": [{"id": "{1}"}]}


def test_worker_runs_code_and_returns_output():
    host = SandboxHost({})
    out = host.execute('print("hello sandbox")\n1 + 2', mode="Agent Mode", tools={})
    assert "hello sandbox" in out
    assert out.rstrip().endswith("3")


def test_worker_proxies_tool_calls_to_host():
    seen = []

    def analyze_audio_file(path, top_n_frequencies=5):
        seen.append(path)
        return {"path": path, "lufs": -14.0}

    tools = {"analyze_audio_file": analyze_audio_file}
    host = SandboxHost(tools)
    out = host.execute('r = analyze_audio_file("D:/x.wav")\nprint("lufs", r["lufs"])', tools=tools)
    assert "lufs -14.0" in out
    assert seen == ["D:/x.wav"], "the tool must have run in the HOST process"


def test_worker_proxies_live_object_methods():
    tools = {"waapi_client": _DummyWaapi()}
    host = SandboxHost(tools)
    out = host.execute(
        'objs = waapi_client.get_selected_objects()\nprint("n", len(objs["objects"]))',
        tools=tools,
    )
    assert "n 1" in out


def test_real_toolbox_analyze_through_worker():
    """End-to-end: real AgentToolbox.analyze_directory_loudness runs in the host
    while the LLM code that calls it runs in the isolated worker."""
    root = tempfile.mkdtemp(prefix="沙箱E2E_")
    try:
        sr = 48000
        n = int(2.0 * sr)
        t = np.arange(n) / sr
        sf.write(os.path.join(root, "a.wav"), (0.1 * np.sin(2 * math.pi * 1000 * t)).astype(np.float32), sr)

        toolbox = AgentToolbox(None, _DummyWaapi())
        tools = {"analyze_directory_loudness": toolbox.analyze_directory_loudness}
        host = SandboxHost(tools)
        code = (
            f'rep = analyze_directory_loudness(r"{root}")\n'
            'print("count", rep["count"])'
        )
        out = host.execute(code, tools=tools)
        assert "count 1" in out
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def test_import_confirmation_denied_blocks():
    host = SandboxHost({}, confirm_import=lambda module: False)
    out = host.execute('import pandas\nprint("unreachable")', tools={})
    assert "not allowed" in out
    assert "unreachable" not in out


def test_import_confirmation_approved_allows():
    host = SandboxHost({}, confirm_import=lambda module: True)
    out = host.execute('import textwrap\nprint("ok", bool(textwrap))', tools={})
    assert "ok True" in out


def test_safe_import_needs_no_confirmation():
    # csv is on the worker's safe list; no confirm callback wired, still works.
    host = SandboxHost({})
    out = host.execute('import csv\nprint("csv", bool(csv))', tools={})
    assert "csv True" in out


def test_hung_worker_can_be_killed():
    """A busy-loop that sys.settrace alone could not interrupt must die on kill."""
    host = SandboxHost({})

    def _cancel_soon():
        time.sleep(1.0)
        host.request_cancel()
        host.kill()

    threading.Thread(target=_cancel_soon, daemon=True).start()
    start = time.time()
    out = host.execute("while True:\n    pass", tools={}, timeout=30)
    elapsed = time.time() - start
    assert elapsed < 10, f"hung worker should be killed quickly, took {elapsed:.1f}s"
    assert "暂停" in out or out  # cancellation marker or empty, never a hang


def test_user_code_error_is_surfaced_not_crashed():
    host = SandboxHost({})
    out = host.execute('raise ValueError("boom")', tools={})
    assert "boom" in out


def test_tool_failure_surfaces_as_error():
    def broken_tool():
        raise RuntimeError("tool exploded")

    tools = {"broken_tool": broken_tool}
    host = SandboxHost(tools)
    out = host.execute("broken_tool()", tools=tools)
    assert "tool exploded" in out


# --- Stage 2: AST hardening + import denylist ---

ESCAPE_PAYLOADS = [
    # The canonical object-subclass breakout to reach Popen.
    '[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == "Popen"]',
    # Reaching a module's globals via a function object.
    "def f():\n    pass\nf.__globals__",
    # MRO / bases traversal.
    "type(1).__mro__",
    "().__class__.__bases__",
    # subclasses() off a user class.
    "class P: pass\nP.__subclasses__()",
]


def test_ast_guard_blocks_dunder_escapes():
    host = SandboxHost({})
    for payload in ESCAPE_PAYLOADS:
        out = host.execute(payload, tools={})
        assert "unreachable" not in out
        # Either the AST dunder guard fired, or a name like getattr is gone.
        assert ("双下划线" in out or "not defined" in out or "Error executing code" in out), \
            f"escape payload should be blocked, got: {out!r}"


def test_getattr_and_introspection_builtins_removed():
    host = SandboxHost({})
    for name in ["getattr", "setattr", "type", "object", "vars", "globals", "locals",
                 "eval", "exec", "compile", "open", "super"]:
        out = host.execute(f'{name}', tools={})
        assert "not defined" in out, f"{name} should NOT be a sandbox builtin, got: {out!r}"


def test_import_hard_denylist_cannot_be_approved():
    # Even with the host approving every import, denylisted modules stay blocked.
    host = SandboxHost({}, confirm_import=lambda module: True)
    for mod in ["subprocess", "ctypes", "socket", "pickle", "importlib", "sys",
                "inspect", "marshal", "multiprocessing"]:
        out = host.execute(f"import {mod}", tools={})
        assert "permanently blocked" in out, f"{mod} must be hard-blocked, got: {out!r}"


def test_normal_code_still_works_after_hardening():
    host = SandboxHost({})
    cases = [
        ("print(sum([1, 2, 3]))", "6"),
        ("print([x * 2 for x in range(3)])", "[0, 2, 4]"),
        ('print(isinstance(5, int))', "True"),
        ('import json, math\nprint(json.dumps({"v": 1}))', '{"v": 1}'),
        ("class P:\n    def __init__(s, x): s.x = x\n    def go(s): return s.x * 2\nprint(P(7).go())", "14"),
        ('n = 3\nprint(f"n={n}")', "n=3"),
    ]
    for code, expected in cases:
        out = host.execute(code, tools={})
        assert expected in out, f"normal code broke: {code!r} -> {out!r}"


# --- Stage 3: OS restriction + file-read containment ---

def test_worker_cannot_read_arbitrary_files():
    """Sandboxed code must not read files directly: builtin open is gone, raw
    os.open is blocked, and pathlib's content-read methods are blocked. File
    access must go through host tools (read_user_file), not the worker."""
    host = SandboxHost({}, confirm_import=lambda module: True)
    target = os.path.join(tempfile.gettempdir(), "sandbox_secret_probe.txt")
    with open(target, "w", encoding="utf-8") as f:
        f.write("TOP-SECRET-VALUE")
    try:
        # builtin open removed
        out = host.execute(f'open(r"{target}")', tools={})
        assert "not defined" in out
        # raw os.open blocked by hardened os
        out = host.execute(f'import os\nos.open(r"{target}", 0)', tools={})
        assert "not allowed" in out
        # pathlib content reads blocked
        out = host.execute(f'import pathlib\nprint(pathlib.Path(r"{target}").read_text())', tools={})
        assert "TOP-SECRET-VALUE" not in out
        assert "not allowed" in out
    finally:
        os.remove(target)


def test_pathlib_read_only_computation_still_works():
    host = SandboxHost({})
    out = host.execute('import pathlib\nprint(pathlib.Path("a/b.wav").name, pathlib.Path("a/b.wav").suffix)', tools={})
    assert "b.wav" in out and ".wav" in out


def test_hung_worker_killed_under_job_object():
    """The OS Job Object path must still allow a hung worker to be killed."""
    host = SandboxHost({})

    def _cancel_soon():
        time.sleep(1.0)
        host.request_cancel()
        host.kill()

    threading.Thread(target=_cancel_soon, daemon=True).start()
    start = time.time()
    host.execute("x = 0\nwhile True:\n    x += 1", tools={}, timeout=30)
    assert time.time() - start < 10


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.tools.base import ToolContext
from src.tools.external_agent_tools import (
    CodexAgentTool,
    ExternalAgentStatusTool,
    _resolve_executable,
)


def test_external_agent_status_is_read_only():
    tool = ExternalAgentStatusTool()
    assert tool.is_read_only()
    result = tool.execute({}, ToolContext(mode="Ask Mode"))
    assert "codex" in result.data
    assert "claude_code" in result.data
    print("test_external_agent_status_is_read_only: OK")


def test_external_agent_denied_in_ask_mode():
    tool = CodexAgentTool()
    permission = tool.check_permissions({"prompt": "hello"}, ToolContext(mode="Ask Mode"))
    assert permission.allowed is False
    assert "Agent Mode" in permission.reason
    print("test_external_agent_denied_in_ask_mode: OK")


def test_external_agent_command_override_executes_prompt():
    tool = CodexAgentTool()
    result = tool.execute(
        {
            "prompt": "hello-from-audiomate",
            "cwd": PROJECT_ROOT,
            "command": [sys.executable, "-c", "import sys; print(sys.argv[1])", "{prompt}"],
            "timeout_seconds": 10,
        },
        ToolContext(mode="Agent Mode"),
    )
    assert result.data["ok"] is True
    assert "hello-from-audiomate" in result.data["stdout"]
    assert "<prompt>" in result.data["command"]
    print("test_external_agent_command_override_executes_prompt: OK")


def test_external_agent_finds_user_npm_shim_when_path_misses_it():
    if os.name != "nt":
        print("test_external_agent_finds_user_npm_shim_when_path_misses_it: SKIP")
        return
    old_appdata = os.environ.get("APPDATA")
    old_path = os.environ.get("PATH")
    with tempfile.TemporaryDirectory() as tmp:
        appdata = Path(tmp) / "Roaming"
        npm_dir = appdata / "npm"
        npm_dir.mkdir(parents=True)
        shim = npm_dir / "audiomate-fake-codex.cmd"
        shim.write_text("@echo off\r\n", encoding="utf-8")
        os.environ["APPDATA"] = str(appdata)
        os.environ["PATH"] = ""
        try:
            assert _resolve_executable("audiomate-fake-codex") == str(shim)
        finally:
            if old_appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old_appdata
            if old_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = old_path
    print("test_external_agent_finds_user_npm_shim_when_path_misses_it: OK")


def test_external_agent_uses_resolved_executable_path():
    if os.name != "nt":
        print("test_external_agent_uses_resolved_executable_path: SKIP")
        return
    old_appdata = os.environ.get("APPDATA")
    old_path = os.environ.get("PATH")
    seen = {}
    with tempfile.TemporaryDirectory() as tmp:
        appdata = Path(tmp) / "Roaming"
        npm_dir = appdata / "npm"
        npm_dir.mkdir(parents=True)
        shim = npm_dir / "audiomate-run-codex.cmd"
        shim.write_text("@echo off\r\n", encoding="utf-8")
        os.environ["APPDATA"] = str(appdata)
        os.environ["PATH"] = ""

        def runner(command, **kwargs):
            seen["command"] = command
            return SimpleNamespace(returncode=0, stdout="resolved-ok\n", stderr="")

        try:
            tool = CodexAgentTool()
            result = tool.execute(
                {
                    "prompt": "hello",
                    "cwd": PROJECT_ROOT,
                    "command": ["audiomate-run-codex", "{prompt}"],
                    "timeout_seconds": 10,
                },
                ToolContext(mode="Agent Mode", extra={"external_agent_runner": runner}),
            )
        finally:
            if old_appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old_appdata
            if old_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = old_path

    assert result.data["ok"] is True
    assert seen["command"][0] == str(shim)
    assert result.data["command"][0] == str(shim)
    print("test_external_agent_uses_resolved_executable_path: OK")


if __name__ == "__main__":
    test_external_agent_status_is_read_only()
    test_external_agent_denied_in_ask_mode()
    test_external_agent_command_override_executes_prompt()
    test_external_agent_finds_user_npm_shim_when_path_misses_it()
    test_external_agent_uses_resolved_executable_path()

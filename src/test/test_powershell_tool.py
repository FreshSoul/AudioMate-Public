import os
import sys
from types import SimpleNamespace

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.tools import create_default_registry
from src.tools.base import ToolContext, ToolResultStatus
from src.tools.powershell_tool import PowerShellRunTool


def test_powershell_registered():
    registry = create_default_registry()
    assert registry.find_tool("powershell.run") is not None
    print("test_powershell_registered: OK")


def test_powershell_denied_in_ask_mode():
    tool = PowerShellRunTool()
    permission = tool.check_permissions(
        {"command": "Write-Output hello"},
        ToolContext(mode="Ask Mode"),
    )
    assert permission.allowed is False
    assert "Agent Mode" in permission.reason
    print("test_powershell_denied_in_ask_mode: OK")


def test_powershell_requires_command():
    tool = PowerShellRunTool()
    validation = tool.validate_input({"command": ""})
    assert validation.valid is False
    assert "command" in validation.error
    print("test_powershell_requires_command: OK")


def test_powershell_cancelled_before_running():
    calls = []

    def confirm(payload):
        calls.append(("confirm", payload))
        return False

    def runner(*_args, **_kwargs):
        calls.append(("runner", {}))
        return SimpleNamespace(returncode=0, stdout="unreachable", stderr="")

    tool = PowerShellRunTool()
    result = tool.execute(
        {"command": "Write-Output hello", "cwd": PROJECT_ROOT},
        ToolContext(
            mode="Agent Mode",
            extra={
                "confirm_powershell": confirm,
                "powershell_executable": "powershell.exe",
                "powershell_runner": runner,
            },
        ),
    )
    assert result.status == ToolResultStatus.PERMISSION_DENIED
    assert calls and calls[0][0] == "confirm"
    assert all(item[0] != "runner" for item in calls)
    print("test_powershell_cancelled_before_running: OK")


def test_powershell_confirmed_uses_runner():
    seen = {}

    def confirm(payload):
        seen["confirm_payload"] = payload
        return True

    def runner(args, cwd, env, timeout):
        seen["args"] = args
        seen["cwd"] = cwd
        seen["env"] = env
        seen["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout="hello-from-powershell\n", stderr="")

    tool = PowerShellRunTool()
    result = tool.execute(
        {"command": "Write-Output hello-from-powershell", "cwd": PROJECT_ROOT, "timeout_seconds": 7},
        ToolContext(
            mode="Agent Mode",
            extra={
                "confirm_powershell": confirm,
                "powershell_executable": "fake-powershell.exe",
                "powershell_runner": runner,
            },
        ),
    )
    assert result.status == ToolResultStatus.SUCCESS
    assert result.data["ok"] is True
    assert result.data["confirmed"] is True
    assert result.data["stdout"].strip() == "hello-from-powershell"
    assert seen["confirm_payload"]["command"] == "Write-Output hello-from-powershell"
    assert seen["args"][0] == "fake-powershell.exe"
    assert "-Command" in seen["args"]
    assert seen["cwd"] == PROJECT_ROOT
    assert seen["timeout"] == 7
    print("test_powershell_confirmed_uses_runner: OK")


if __name__ == "__main__":
    test_powershell_registered()
    test_powershell_denied_in_ask_mode()
    test_powershell_requires_command()
    test_powershell_cancelled_before_running()
    test_powershell_confirmed_uses_runner()

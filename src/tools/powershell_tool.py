"""Structured PowerShell execution tool with mandatory user confirmation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from src.tools.base import (
    PermissionResult,
    Tool,
    ToolContext,
    ToolResult,
    ToolResultStatus,
    ValidationResult,
)
from src.tools.permissions import is_ask_mode


_DEFAULT_TIMEOUT_SECONDS = 120
_MAX_TIMEOUT_SECONDS = 1800
_DEFAULT_MAX_OUTPUT_CHARS = 24000
_MAX_OUTPUT_CHARS = 120000


def _as_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _truncate(text: str, max_chars: int) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n\n[AudioMate truncated {omitted} chars]"


def _resolve_cwd(input_data: dict) -> str:
    raw = str(input_data.get("cwd") or "").strip()
    if raw:
        return os.path.abspath(os.path.expanduser(raw))
    return os.getcwd()


def _resolve_shell_key(input_data: dict) -> str:
    value = str(input_data.get("shell") or "auto").strip().lower()
    return value if value in {"auto", "powershell", "pwsh"} else "auto"


def _candidate_executables(shell_key: str) -> list[str]:
    if shell_key == "pwsh":
        return ["pwsh.exe", "pwsh"]
    if shell_key == "powershell":
        return [
            "powershell.exe",
            "powershell",
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        ]
    return [
        "powershell.exe",
        "powershell",
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "pwsh.exe",
        "pwsh",
    ]


def _resolve_executable(shell_key: str, context: ToolContext) -> str:
    extra = context.extra if isinstance(context.extra, dict) else {}
    override = str(extra.get("powershell_executable") or "").strip()
    if override:
        return override
    env_override = str(os.environ.get("AUDIOMATE_POWERSHELL_EXE") or "").strip()
    if env_override:
        return env_override
    for candidate in _candidate_executables(shell_key):
        if os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return ""


def _build_command_args(executable: str, command: str) -> list[str]:
    wrapped_command = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$OutputEncoding = [System.Text.Encoding]::UTF8; "
        + command
    )
    return [
        executable,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        wrapped_command,
    ]


def _request_confirmation(payload: dict, context: ToolContext) -> bool:
    extra = context.extra if isinstance(context.extra, dict) else {}
    callback = extra.get("confirm_powershell")
    if callable(callback):
        try:
            return bool(callback(dict(payload)))
        except Exception:
            return False

    parent = context.parent_widget
    requester = getattr(parent, "request_powershell_confirmation", None)
    if callable(requester):
        try:
            return bool(requester(dict(payload)))
        except Exception:
            return False
    return False


class PowerShellRunTool(Tool):
    """Run a PowerShell command after an explicit GUI/user confirmation."""

    @property
    def name(self) -> str:
        return "powershell.run"

    @property
    def description(self) -> str:
        return "Run a local PowerShell command after explicit user confirmation."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "PowerShell command text to run.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory. Defaults to AudioMate's process cwd.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_TIMEOUT_SECONDS,
                    "default": _DEFAULT_TIMEOUT_SECONDS,
                },
                "max_output_chars": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": _MAX_OUTPUT_CHARS,
                    "default": _DEFAULT_MAX_OUTPUT_CHARS,
                },
                "shell": {
                    "type": "string",
                    "enum": ["auto", "powershell", "pwsh"],
                    "default": "auto",
                    "description": "PowerShell host preference. auto tries Windows PowerShell first, then pwsh.",
                },
            },
            "required": ["command"],
        }

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        input_data = input if isinstance(input, dict) else {}
        command = str(input_data.get("command") or "").strip()
        if not command:
            return ValidationResult(False, "command is required.")
        if "\x00" in command:
            return ValidationResult(False, "command must not contain NUL bytes.")

        shell_key = str(input_data.get("shell") or "auto").strip().lower()
        if shell_key and shell_key not in {"auto", "powershell", "pwsh"}:
            return ValidationResult(False, "shell must be one of: auto, powershell, pwsh.")

        cwd = _resolve_cwd(input_data)
        if not os.path.isdir(cwd):
            return ValidationResult(False, f"cwd does not exist or is not a directory: {cwd}")
        return ValidationResult()

    def check_permissions(self, input: dict, context: ToolContext) -> PermissionResult:
        if is_ask_mode(context.mode):
            return PermissionResult(
                allowed=False,
                reason=(
                    "Tool 'powershell.run' launches a local shell process and is only "
                    "available in Agent Mode with explicit user confirmation."
                ),
            )
        return PermissionResult()

    def is_read_only(self, input: dict | None = None) -> bool:
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def side_effects(self) -> list[str]:
        return ["external-process", "local-file-read", "local-file-write", "network"]

    def prompt(self) -> str:
        return (
            "Run a PowerShell command. Agent Mode only. AudioMate must ask the "
            "user to confirm every invocation before the process starts."
        )

    def execute(self, input: dict, context: ToolContext) -> ToolResult:  # noqa: A002
        input_data = input if isinstance(input, dict) else {}
        validation = self.validate_input(input_data)
        if not validation.valid:
            return ToolResult(validation.error or "Tool input is invalid.", ToolResultStatus.ERROR)
        permission = self.check_permissions(input_data, context)
        if not permission.allowed:
            return ToolResult(permission.reason or "Tool permission denied.", ToolResultStatus.PERMISSION_DENIED)
        command = str(input_data.get("command") or "").strip()
        cwd = _resolve_cwd(input_data)
        timeout_seconds = _as_int(
            input_data.get("timeout_seconds"),
            _DEFAULT_TIMEOUT_SECONDS,
            minimum=1,
            maximum=_MAX_TIMEOUT_SECONDS,
        )
        max_output_chars = _as_int(
            input_data.get("max_output_chars"),
            _DEFAULT_MAX_OUTPUT_CHARS,
            minimum=1000,
            maximum=_MAX_OUTPUT_CHARS,
        )
        shell_key = _resolve_shell_key(input_data)
        executable = _resolve_executable(shell_key, context)
        if not executable:
            payload = {
                "ok": False,
                "confirmed": False,
                "error": "PowerShell executable not found. Install PowerShell or set AUDIOMATE_POWERSHELL_EXE.",
                "shell": shell_key,
                "cwd": cwd,
                "command": command,
            }
            return ToolResult(
                output=json.dumps(payload, ensure_ascii=False, indent=2),
                status=ToolResultStatus.ERROR,
                data=payload,
            )

        confirm_payload = {
            "command": command,
            "cwd": cwd,
            "timeout_seconds": timeout_seconds,
            "shell": shell_key,
            "executable": executable,
        }
        if not _request_confirmation(confirm_payload, context):
            return ToolResult(
                "PowerShell command was not run because the user declined confirmation.",
                ToolResultStatus.PERMISSION_DENIED,
                data={
                    "ok": False,
                    "confirmed": False,
                    "cancelled": True,
                    "cwd": cwd,
                    "command": command,
                    "shell": shell_key,
                    "executable": executable,
                },
            )

        args = _build_command_args(executable, command)
        env = dict(os.environ)
        env.setdefault("NO_COLOR", "1")
        env.setdefault("TERM", "dumb")
        runner = None
        extra = context.extra if isinstance(context.extra, dict) else {}
        maybe_runner = extra.get("powershell_runner")
        if callable(maybe_runner):
            runner = maybe_runner
        try:
            if runner is not None:
                completed = runner(args, cwd=cwd, env=env, timeout=timeout_seconds)
            else:
                completed = subprocess.run(
                    args,
                    cwd=cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
                    shell=False,
                )
            stdout = _truncate(getattr(completed, "stdout", "") or "", max_output_chars)
            stderr = _truncate(getattr(completed, "stderr", "") or "", max_output_chars)
            returncode = int(getattr(completed, "returncode", 1))
            payload = {
                "ok": returncode == 0,
                "confirmed": True,
                "returncode": returncode,
                "cwd": cwd,
                "command": command,
                "shell": shell_key,
                "executable": executable,
                "stdout": stdout,
                "stderr": stderr,
                "output": stdout.strip() or stderr.strip(),
            }
            return ToolResult(
                output=json.dumps(payload, ensure_ascii=False, indent=2),
                status=ToolResultStatus.SUCCESS if returncode == 0 else ToolResultStatus.ERROR,
                data=payload,
            )
        except subprocess.TimeoutExpired as exc:
            payload = {
                "ok": False,
                "confirmed": True,
                "returncode": None,
                "cwd": cwd,
                "command": command,
                "shell": shell_key,
                "executable": executable,
                "error": f"Timed out after {timeout_seconds} seconds.",
                "stdout": _truncate(exc.stdout or "", max_output_chars),
                "stderr": _truncate(exc.stderr or "", max_output_chars),
            }
            return ToolResult(
                output=json.dumps(payload, ensure_ascii=False, indent=2),
                status=ToolResultStatus.ERROR,
                data=payload,
            )
        except Exception as exc:  # noqa: BLE001
            payload = {
                "ok": False,
                "confirmed": True,
                "cwd": cwd,
                "command": command,
                "shell": shell_key,
                "executable": executable,
                "error": str(exc),
            }
            return ToolResult(
                output=json.dumps(payload, ensure_ascii=False, indent=2),
                status=ToolResultStatus.ERROR,
                data=payload,
            )

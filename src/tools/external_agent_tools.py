"""Structured tools for delegating work to external coding agents."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
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


_MAX_TIMEOUT_SECONDS = 7200
_DEFAULT_TIMEOUT_SECONDS = 900
_DEFAULT_MAX_OUTPUT_CHARS = 24000
_WINDOWS_EXECUTABLE_EXTENSIONS = (".cmd", ".exe", ".bat", ".com")


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


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


def _split_command(value: str) -> list[str]:
    value = str(value or "").strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return [item for item in parsed if item]
    except Exception:
        pass
    return shlex.split(value, posix=os.name != "nt")


def _command_from_env(env_name: str, default: list[str]) -> list[str]:
    configured = os.environ.get(env_name)
    if configured:
        parsed = _split_command(configured)
        if parsed:
            return parsed
    return list(default)


def _unique_existing_dirs(paths: list[str]) -> list[str]:
    seen = set()
    out = []
    for path in paths:
        item = os.path.abspath(os.path.expanduser(os.path.expandvars(str(path or ""))))
        key = item.lower() if os.name == "nt" else item
        if not item or key in seen or not os.path.isdir(item):
            continue
        seen.add(key)
        out.append(item)
    return out


def _node_global_bin_dirs() -> list[str]:
    """Return common Node/npm global command directories.

    GUI apps launched from Explorer/IDE often miss the per-user npm bin dir in
    PATH even though `where codex` works in an interactive shell.
    """
    paths = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(os.path.join(appdata, "npm"))
    userprofile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    if userprofile:
        paths.append(os.path.join(userprofile, "AppData", "Roaming", "npm"))
    npm_prefix = os.environ.get("NPM_CONFIG_PREFIX") or os.environ.get("npm_config_prefix")
    if npm_prefix:
        paths.extend([npm_prefix, os.path.join(npm_prefix, "bin")])
    return _unique_existing_dirs(paths)


def _prefer_windows_command_shim(path: str) -> str:
    if os.name != "nt":
        return path
    root, ext = os.path.splitext(path)
    if ext.lower() in _WINDOWS_EXECUTABLE_EXTENSIONS:
        return path
    for suffix in _WINDOWS_EXECUTABLE_EXTENSIONS:
        sibling = root + suffix
        if os.path.isfile(sibling):
            return sibling
    return path


def _executable_names(executable: str) -> list[str]:
    raw = os.path.basename(str(executable or "").strip())
    if not raw:
        return []
    root, ext = os.path.splitext(raw)
    if os.name != "nt" or ext:
        return [raw]
    return [root + suffix for suffix in _WINDOWS_EXECUTABLE_EXTENSIONS] + [raw]


def _resolve_executable(executable: str) -> str:
    raw = str(executable or "").strip()
    if not raw:
        return ""
    expanded = os.path.expanduser(os.path.expandvars(raw))

    has_dir = bool(os.path.dirname(expanded))
    if has_dir:
        candidates = [expanded]
        root, ext = os.path.splitext(expanded)
        if os.name == "nt" and not ext:
            candidates = [root + suffix for suffix in _WINDOWS_EXECUTABLE_EXTENSIONS] + candidates
        for candidate in candidates:
            if os.path.isfile(candidate):
                return _prefer_windows_command_shim(os.path.abspath(candidate))
        return ""

    resolved = shutil.which(raw)
    if resolved:
        return _prefer_windows_command_shim(resolved)

    if os.name == "nt":
        for directory in _node_global_bin_dirs():
            for name in _executable_names(raw):
                candidate = os.path.join(directory, name)
                if os.path.isfile(candidate):
                    return _prefer_windows_command_shim(candidate)
    return ""


def _format_command(command: list[str], *, prompt: str, cwd: str, extra: dict[str, str]) -> list[str]:
    has_prompt_placeholder = any("{prompt}" in part for part in command)
    values = {"prompt": prompt, "cwd": cwd, **extra}
    formatted = []
    for part in command:
        item = str(part)
        for key, value in values.items():
            item = item.replace("{" + key + "}", str(value))
        if item:
            formatted.append(item)
    if not has_prompt_placeholder:
        formatted.append(prompt)
    return formatted


def _redact_prompt(command: list[str], prompt: str) -> list[str]:
    return ["<prompt>" if part == prompt else str(part).replace(prompt, "<prompt>") for part in command]


def _resolve_cwd(input_data: dict) -> str:
    raw = str(input_data.get("cwd") or "").strip()
    if raw:
        cwd = os.path.abspath(os.path.expanduser(raw))
    else:
        cwd = os.getcwd()
    return cwd


@dataclass(frozen=True)
class _ExternalAgentSpec:
    key: str
    display_name: str
    env_name: str
    default_command: list[str]


class ExternalAgentStatusTool(Tool):
    @property
    def name(self) -> str:
        return "external_agent.status"

    @property
    def description(self) -> str:
        return "Check whether the Codex and Claude Code CLIs are available on PATH."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def is_read_only(self, input: dict | None = None) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        codex_command = _command_from_env("AUDIOMATE_CODEX_COMMAND", ["codex"])
        claude_command = _command_from_env("AUDIOMATE_CLAUDE_CODE_COMMAND", ["claude"])
        claude_path = _resolve_executable(claude_command[0] if claude_command else "claude")
        if not claude_path and "AUDIOMATE_CLAUDE_CODE_COMMAND" not in os.environ:
            claude_path = _resolve_executable("claude-code")
        payload = {
            "codex": {
                "command": os.environ.get("AUDIOMATE_CODEX_COMMAND") or "codex",
                "path": _resolve_executable(codex_command[0] if codex_command else "codex"),
                "configured_env": "AUDIOMATE_CODEX_COMMAND",
            },
            "claude_code": {
                "command": os.environ.get("AUDIOMATE_CLAUDE_CODE_COMMAND") or "claude",
                "path": claude_path,
                "configured_env": "AUDIOMATE_CLAUDE_CODE_COMMAND",
            },
        }
        return ToolResult(
            output=json.dumps(payload, ensure_ascii=False, indent=2),
            data=payload,
        )


class _ExternalAgentTool(Tool):
    def __init__(self, spec: _ExternalAgentSpec):
        self.spec = spec

    @property
    def name(self) -> str:
        return f"external_agent.{self.spec.key}"

    @property
    def description(self) -> str:
        return f"Delegate a coding task to {self.spec.display_name} CLI and return its output."

    @property
    def input_schema(self) -> dict:
        properties = {
            "prompt": {
                "type": "string",
                "description": "Concrete task to give the external coding agent.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the external agent. Defaults to AudioMate's process cwd.",
            },
            "timeout_seconds": {
                "type": "integer",
                "minimum": 10,
                "maximum": _MAX_TIMEOUT_SECONDS,
                "default": _DEFAULT_TIMEOUT_SECONDS,
            },
            "max_output_chars": {
                "type": "integer",
                "minimum": 1000,
                "maximum": 120000,
                "default": _DEFAULT_MAX_OUTPUT_CHARS,
            },
            "allow_writes": {
                "type": "boolean",
                "default": False,
                "description": "Whether the external agent is allowed to edit files or run mutating commands.",
            },
            "command": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Advanced override. Use {prompt}, {cwd}, and agent-specific placeholders.",
            },
        }
        self._extend_schema(properties)
        return {
            "type": "object",
            "properties": properties,
            "required": ["prompt"],
        }

    def _extend_schema(self, properties: dict) -> None:
        pass

    def validate_input(self, input: dict) -> ValidationResult:
        if not str((input or {}).get("prompt") or "").strip():
            return ValidationResult(False, "prompt is required.")
        command = (input or {}).get("command")
        if command is not None and (
            not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command)
        ):
            return ValidationResult(False, "command must be a non-empty list of strings when provided.")
        cwd = _resolve_cwd(input or {})
        if not os.path.isdir(cwd):
            return ValidationResult(False, f"cwd does not exist or is not a directory: {cwd}")
        return ValidationResult()

    def check_permissions(self, input: dict, context: ToolContext) -> PermissionResult:
        if is_ask_mode(context.mode):
            return PermissionResult(
                allowed=False,
                reason=f"Tool '{self.name}' launches an external coding agent and is only available in Agent Mode.",
            )
        return PermissionResult()

    def is_concurrency_safe(self) -> bool:
        return False

    def side_effects(self) -> list[str]:
        return ["external-process", "local-file-read", "local-file-write", "network"]

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        input_data = input if isinstance(input, dict) else {}
        prompt = self._build_prompt(input_data)
        cwd = _resolve_cwd(input_data)
        timeout_seconds = _as_int(
            input_data.get("timeout_seconds"),
            _DEFAULT_TIMEOUT_SECONDS,
            minimum=10,
            maximum=_MAX_TIMEOUT_SECONDS,
        )
        max_output_chars = _as_int(
            input_data.get("max_output_chars"),
            _DEFAULT_MAX_OUTPUT_CHARS,
            minimum=1000,
            maximum=120000,
        )
        command_template = self._command_template(input_data)
        command = _format_command(
            command_template,
            prompt=prompt,
            cwd=cwd,
            extra=self._format_values(input_data),
        )
        executable = command[0] if command else ""
        resolved_executable = _resolve_executable(executable)
        if not resolved_executable:
            payload = {
                "ok": False,
                "agent": self.spec.key,
                "error": (
                    f"{self.spec.display_name} CLI not found: {executable or '<empty>'}. "
                    f"Install it or set {self.spec.env_name} to a command template."
                ),
                "command": _redact_prompt(command, prompt),
                "cwd": cwd,
            }
            return ToolResult(
                output=json.dumps(payload, ensure_ascii=False, indent=2),
                status=ToolResultStatus.ERROR,
                data=payload,
            )
        command = [resolved_executable] + command[1:]

        env = dict(os.environ)
        executable_dir = os.path.dirname(resolved_executable)
        if executable_dir:
            env["PATH"] = executable_dir + os.pathsep + env.get("PATH", "")
        env.setdefault("NO_COLOR", "1")
        env.setdefault("TERM", "dumb")
        runner = None
        extra_context = context.extra if isinstance(context.extra, dict) else {}
        maybe_runner = extra_context.get("external_agent_runner")
        if callable(maybe_runner):
            runner = maybe_runner
        try:
            if runner is not None:
                completed = runner(command, cwd=cwd, env=env, timeout=timeout_seconds)
            else:
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
                    shell=False,
                )
            stdout = _truncate(completed.stdout or "", max_output_chars)
            stderr = _truncate(completed.stderr or "", max_output_chars)
            output = stdout.strip() or stderr.strip()
            payload = {
                "ok": completed.returncode == 0,
                "agent": self.spec.key,
                "returncode": completed.returncode,
                "cwd": cwd,
                "command": _redact_prompt(command, prompt),
                "stdout": stdout,
                "stderr": stderr,
                "output": output,
            }
            return ToolResult(
                output=json.dumps(payload, ensure_ascii=False, indent=2),
                status=ToolResultStatus.SUCCESS if completed.returncode == 0 else ToolResultStatus.ERROR,
                data=payload,
            )
        except subprocess.TimeoutExpired as exc:
            payload = {
                "ok": False,
                "agent": self.spec.key,
                "returncode": None,
                "cwd": cwd,
                "command": _redact_prompt(command, prompt),
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
                "agent": self.spec.key,
                "cwd": cwd,
                "command": _redact_prompt(command, prompt),
                "error": str(exc),
            }
            return ToolResult(
                output=json.dumps(payload, ensure_ascii=False, indent=2),
                status=ToolResultStatus.ERROR,
                data=payload,
            )

    def _build_prompt(self, input_data: dict) -> str:
        return str(input_data.get("prompt") or "").strip()

    def _command_template(self, input_data: dict) -> list[str]:
        command = input_data.get("command")
        if isinstance(command, list) and command:
            return [str(item) for item in command]
        return _command_from_env(self.spec.env_name, self.spec.default_command)

    def _format_values(self, input_data: dict) -> dict[str, str]:
        return {}


class CodexAgentTool(_ExternalAgentTool):
    def __init__(self):
        super().__init__(
            _ExternalAgentSpec(
                key="codex",
                display_name="Codex",
                env_name="AUDIOMATE_CODEX_COMMAND",
                default_command=["codex", "--ask-for-approval", "never", "--sandbox", "{sandbox}", "exec", "{prompt}"],
            )
        )

    def _extend_schema(self, properties: dict) -> None:
        properties.update({
            "allow_writes": {
                "type": "boolean",
                "default": False,
                "description": "When true, Codex runs with workspace-write sandbox instead of read-only.",
            },
            "sandbox": {
                "type": "string",
                "enum": ["read-only", "workspace-write"],
                "description": "Explicit Codex sandbox. Defaults to read-only unless allow_writes is true.",
            },
        })

    def _format_values(self, input_data: dict) -> dict[str, str]:
        sandbox = str(input_data.get("sandbox") or "").strip()
        if sandbox not in {"read-only", "workspace-write"}:
            sandbox = "workspace-write" if _as_bool(input_data.get("allow_writes"), False) else "read-only"
        return {"sandbox": sandbox}


class ClaudeCodeAgentTool(_ExternalAgentTool):
    def __init__(self):
        super().__init__(
            _ExternalAgentSpec(
                key="claude_code",
                display_name="Claude Code",
                env_name="AUDIOMATE_CLAUDE_CODE_COMMAND",
                default_command=["claude", "{bare}", "-p", "{prompt}"],
            )
        )

    def _extend_schema(self, properties: dict) -> None:
        properties.update({
            "bare": {
                "type": "boolean",
                "default": True,
                "description": "Run Claude Code with --bare for scripted calls. Set false to load local project/user config.",
            },
            "allowed_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional Claude Code --allowedTools list, e.g. ['Read'] or ['Read', 'Edit', 'Bash'].",
            },
            "append_system_prompt": {
                "type": "string",
                "description": "Optional Claude Code --append-system-prompt value.",
            },
            "output_format": {
                "type": "string",
                "enum": ["", "text", "json", "stream-json"],
                "description": "Optional Claude Code --output-format value.",
            },
        })

    def _build_prompt(self, input_data: dict) -> str:
        prompt = super()._build_prompt(input_data)
        if _as_bool(input_data.get("allow_writes"), False):
            return prompt
        return (
            "You are being called as an AudioMate external sub-agent. "
            "Do not modify files or run mutating commands unless the prompt explicitly says writes are allowed. "
            "Return concise findings and suggested patches in text.\n\n"
            + prompt
        )

    def _command_template(self, input_data: dict) -> list[str]:
        command = super()._command_template(input_data)
        extras = []
        allowed_tools = input_data.get("allowed_tools")
        if isinstance(allowed_tools, list) and allowed_tools:
            clean = [str(item).strip() for item in allowed_tools if str(item).strip()]
            if clean:
                extras.extend(["--allowedTools", ",".join(clean)])
        append_system_prompt = str(input_data.get("append_system_prompt") or "").strip()
        if append_system_prompt:
            extras.extend(["--append-system-prompt", append_system_prompt])
        output_format = str(input_data.get("output_format") or "").strip()
        if output_format:
            extras.extend(["--output-format", output_format])
        if extras:
            for flag in ("-p", "--print"):
                if flag in command:
                    index = command.index(flag)
                    return command[:index] + extras + command[index:]
            return command + extras
        return command

    def _format_values(self, input_data: dict) -> dict[str, str]:
        bare = "--bare" if _as_bool(input_data.get("bare"), True) else ""
        return {"bare": bare}

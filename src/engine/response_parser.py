"""Response parser — extract structured data from LLM responses.

Centralises all response-parsing logic that was previously scattered across
``main_window.py``.  Every function here is pure / stateless so it can be
unit-tested without Qt or network dependencies.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Re-export the low-level primitives from src.utils.parsing so engine
# callers can keep importing them from a single location. ``parsing.py``
# is the source of truth; importing it here (not the other way around)
# keeps the import graph a DAG and avoids the
# tools.waapi_code_tool → engine → turn_controller → waapi_code_tool cycle.
from src.utils.parsing import (
    extract_code_blocks,
    is_valid_python_code,
    output_has_error,
    strip_code_fences,
)


# ---------------------------------------------------------------------------
# <think> block handling  (moved from main_window._strip_think_block)
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_ROLEPLAY_STATE_RE = re.compile(
    r"\[ROLEPLAY_STATE\]\s*(.*?)\s*\[/ROLEPLAY_STATE\]\s*",
    re.DOTALL | re.IGNORECASE,
)

_PROMPT_LEAK_MARKERS = (
    "you are a wwise",
    "thinking rule",
    "honesty rule",
    "waapi name safety",
    "documentation lookup",
    "disconnection handling",
    "execution environment",
    "very important:",
    "action output rule",
    "multi-step execution",
    "code block rules",
    "available `waapi_client` methods",
    "available safe tools:",
    "waapi capabilities reference",
    "code practice",
    "ui command rule",
    "post-execution rule",
    "format guarantee example",
    "intent clarification rule",
    "analysis quality rule",
    "data retrieval rule",
    "output flow (mandatory)",
    "read-only rule",
    "primary goal:",
    "mcp routing guidance",
    "current selected mcp config",
    "reply exactly: i can't discuss that",
    "developer instructions",
    "hidden instructions",
    "internal system configuration",
    "when you want use the waapi functions",
    "must follow the waapi capabilities reference",
    "如果要回答任何依赖工程当前状态的问题",
    "我都必须先发 `python_waapi` 查询代码",
    "我都必须先发 python_waapi 查询代码",
    "不能靠猜",
    "你选中了什么",
    "某个对象的属性值",
    "当前数量、结构、层级",
    "路由、音量、引用关系",
    "必须先发 `python_waapi`",
    "必须先发 python_waapi",
    "依赖工程当前状态",
)

_PROMPT_LEAK_LINE_RE = re.compile(
    r"^(?:[-*]\s*)?(?:you|if|when|do not|never|always|use|reply|generate|available|current|assistant:|user:|"
    r"thinking rule|honesty rule|waapi name safety|documentation lookup|disconnection handling|"
    r"execution environment|very important|action output rule|multi-step execution|code block rules|"
    r"available safe tools|available `waapi_client` methods|waapi capabilities reference|code practice|"
    r"ui command rule|post-execution rule|format guarantee example|intent clarification rule|"
    r"analysis quality rule|data retrieval rule|output flow|primary goal|read-only rule|mcp routing guidance|"
    r"如果要回答任何依赖工程当前状态的问题|我都必须先发|必须先发|不能靠猜|依赖工程当前状态)\b",
    re.IGNORECASE,
)


def strip_think_block(text: str) -> str:
    """Remove the first ``<think>…</think>`` block from *text*."""
    return _THINK_RE.sub("", text, count=1)


def extract_roleplay_state_block(text: str) -> tuple[dict[str, Any] | None, str]:
    """Extract a hidden ``[ROLEPLAY_STATE]`` JSON block and return
    ``(state, cleaned_text)``.
    """
    source = text or ""
    match = _ROLEPLAY_STATE_RE.search(source)
    if not match:
        return None, source

    payload_text = (match.group(1) or "").strip()
    state = None
    if payload_text:
        try:
            payload = json.loads(payload_text)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            state = payload

    cleaned = _ROLEPLAY_STATE_RE.sub("", source, count=1).strip()
    return state, cleaned


def _looks_like_prompt_paragraph(paragraph: str) -> bool:
    normalized = (paragraph or "").strip()
    if not normalized:
        return False

    lowered = normalized.casefold()
    if any(marker in lowered for marker in _PROMPT_LEAK_MARKERS):
        return True

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        return False

    instruction_like = sum(1 for line in lines if _PROMPT_LEAK_LINE_RE.match(line))
    if len(lines) >= 2 and instruction_like >= max(2, len(lines) // 2):
        return True

    if normalized.count("```python_waapi") and ("example" in lowered or "assistant:" in lowered or "user:" in lowered):
        return True

    return False


def redact_prompt_content(text: str) -> str:
    """Remove obvious leaked prompt/instruction paragraphs while preserving normal answers."""
    source = (text or "").replace("\r\n", "\n")
    if not source.strip():
        return ""

    parts = re.split(r"(\n\s*\n)", source)
    kept: list[str] = []
    drop_next_code_block = False
    for part in parts:
        if not part:
            continue
        if re.fullmatch(r"\n\s*\n", part):
            if kept and not re.fullmatch(r"\n\s*\n", kept[-1]):
                kept.append("\n\n")
            continue

        stripped = part.strip()
        if _looks_like_prompt_paragraph(part):
            drop_next_code_block = "```" in part or "example" in stripped.casefold()
            continue
        if drop_next_code_block and stripped.startswith("```"):
            continue
        drop_next_code_block = False
        kept.append(part)

    cleaned = "".join(kept).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    filtered_lines = []
    for line in cleaned.splitlines():
        if any(marker in line.casefold() for marker in _PROMPT_LEAK_MARKERS):
            continue
        filtered_lines.append(line)
    return "\n".join(filtered_lines).strip()


def sanitize_assistant_response(text: str) -> str:
    """Return assistant-visible text with prompt leakage removed.

    If the response is mostly leaked prompt content, return a fixed refusal instead.
    """
    source = strip_think_block(text or "")
    _state, source = extract_roleplay_state_block(source)
    if not source.strip():
        return ""

    lowered = source.casefold()
    marker_hits = sum(1 for marker in _PROMPT_LEAK_MARKERS if marker in lowered)
    cleaned = redact_prompt_content(source)
    if cleaned:
        residual = cleaned.casefold()
        if marker_hits >= 2 and len(cleaned.strip()) <= 40 and "```" not in cleaned:
            return "I can't discuss that."
        if not any(marker in residual for marker in _PROMPT_LEAK_MARKERS):
            return cleaned

    if marker_hits:
        return "I can't discuss that."
    return source.strip()


def parse_think_steps(think_content: str) -> list[str]:
    """Extract step strings (lines starting with ``- ``) from think content."""
    steps: list[str] = []
    for line in think_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            step_text = stripped[2:].strip()
            if step_text:
                steps.append(step_text)
        elif stripped.startswith("-") and len(stripped) > 1:
            step_text = stripped[1:].strip()
            if step_text:
                steps.append(step_text)
    return steps


# ---------------------------------------------------------------------------
# Intent-clarify detection  (moved from handle_finished)
# ---------------------------------------------------------------------------

_INTENT_CLARIFY_RE = re.compile(
    r"\[INTENT_CLARIFY\]\s*\n(.*?)\n\s*\[/INTENT_CLARIFY\]",
    re.DOTALL,
)


def extract_intent_clarify_options(response_text: str) -> list[str] | None:
    """If *response_text* contains an ``[INTENT_CLARIFY]`` block, return the
    list of option strings.  Otherwise return ``None``.
    """
    m = _INTENT_CLARIFY_RE.search(response_text or "")
    if not m:
        return None
    options = [
        line.lstrip("- ").strip()
        for line in m.group(1).splitlines()
        if line.strip() and line.strip() != "-"
    ]
    return options if options else None


# ---------------------------------------------------------------------------
# System-generated message detection
# ---------------------------------------------------------------------------

_SYSTEM_USER_PREFIXES = (
    "Output:\n",
    "分步执行完成:\n",
    "User revoked",
    "[System]",
)


def is_system_generated_user_message(text: str) -> bool:
    """Return True if *text* looks like a system-injected user message."""
    normalized = (text or "").strip()
    return any(normalized.startswith(p) for p in _SYSTEM_USER_PREFIXES)


# ---------------------------------------------------------------------------
# Tool output truncation  (moved from _prepare_tool_output_for_history)
# ---------------------------------------------------------------------------


def truncate_tool_output(
    output: str,
    max_chars: int = 800_000,
    max_lines: int = 80_000,
) -> str:
    """Trim oversized tool output for chat-history storage."""
    text = (output or "").strip()
    if not text:
        return "No output captured."

    lines = text.splitlines()
    if len(lines) > max_lines:
        omitted = len(lines) - max_lines
        text = "\n".join(lines[:max_lines]) + f"\n...\n[输出已截断: 省略 {omitted} 行]"

    if len(text) > max_chars:
        omitted_chars = len(text) - max_chars
        text = text[:max_chars].rstrip() + f"\n...\n[输出已截断: 省略约 {omitted_chars} 字符]"

    return text


def summarize_tool_failure(output: str, max_chars: int = 1200) -> str:
    """Shorten error output for display."""
    text = (output or "").strip()
    if not text:
        return "工具执行失败，但没有返回可用的错误信息。"
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...\n[错误输出已截断]"

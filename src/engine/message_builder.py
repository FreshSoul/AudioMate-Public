"""Message builder — construct LLM message lists from state + context.

Extracted from ``main_window.process_turn()`` so the turn controller
and tests can build LLM messages without coupling to the GUI.
"""

from __future__ import annotations

from typing import Any, Callable

from src.engine.response_parser import truncate_tool_output


# ---------------------------------------------------------------------------
# Message list assembly
# ---------------------------------------------------------------------------


def build_llm_messages(
    system_prompt: str,
    chat_history: list[dict],
    *,
    memory_context: str | None = None,
    history_compressor: Callable[[list[dict]], list[dict]] | None = None,
    content_enricher: Callable[[dict], str] | None = None,
) -> list[dict]:
    """Build the ``messages`` list ready for the LLM API.

    Parameters
    ----------
    system_prompt:
        Full system-prompt string (already assembled with knowledge, context, etc.)
    chat_history:
        Raw chat history (may contain ``display_text``, ``attachments`` etc.)
    history_compressor:
        Optional callable (e.g. ``resilience.summarize_history``) that
        compresses older messages to fit context windows.
    content_enricher:
        Optional callable that takes a *user* message dict and returns
        enriched content (e.g. with analysis-scope context).  If ``None``,
        ``msg["content"]`` is used verbatim.
    memory_context:
        Optional rendered user/session/repo memory context to inject after
        the main system prompt and before conversation history.
    """
    compressed = history_compressor(chat_history) if history_compressor else chat_history

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if memory_context and memory_context.strip():
        messages.append({"role": "system", "content": memory_context.strip()})
    for msg in compressed:
        role = msg.get("role")
        if role not in {"user", "assistant", "system"}:
            continue
        if role == "user" and content_enricher:
            content = content_enricher(msg)
        else:
            content = msg.get("content", "")
        messages.append({"role": role, "content": _normalize_content(content)})
    return messages


def _normalize_content(content: Any) -> Any:
    """Ensure list-form content only contains valid multimodal-part dicts.

    Some upstream paths (history persistence, enrichment, legacy code) may
    leave plain strings inside an otherwise-list content. The OpenAI
    Chat Completions API rejects those with ``Invalid type for
    'messages[i].content[j]': expected an object, but got a string instead``.
    Wrap any stray scalar into a ``{"type": "text", "text": ...}`` part.
    """
    if not isinstance(content, list):
        return content
    normalized: list[dict] = []
    for part in content:
        if isinstance(part, dict):
            normalized.append(part)
        elif part is None:
            continue
        else:
            normalized.append({"type": "text", "text": str(part)})
    return normalized


# ---------------------------------------------------------------------------
# Reinforcement messages (appended after the main history)
# ---------------------------------------------------------------------------


def build_reinforcement_messages(
    *,
    mode: str,
    is_disconnected_waapi_request: bool = False,
    last_message_is_user: bool = False,
    resilience_action: str = "continue",
    resilience_message: str = "",
) -> list[dict]:
    """Return additional messages to inject after the main conversation.

    These enforce mode-specific behaviour rules that are currently hard-coded
    in ``process_turn()``.
    """
    extra: list[dict] = []
    if not last_message_is_user:
        return extra

    if mode == "Agent Mode":
        if is_disconnected_waapi_request:
            extra.append({
                "role": "user",
                "content": (
                    "CRITICAL: Wwise/WAAPI is NOT connected. Do NOT generate any "
                    "`python_waapi` code blocks. Respond in natural language, mention "
                    "the current limitation, and remind the user to click Connect "
                    "before asking for project-specific actions or data."
                ),
            })
        else:
            extra.append({
                "role": "user",
                "content": (
                    "IMPORTANT: If the user requested an action about Wwise/WAAPI, you MUST generate "
                    "a `python_waapi` code block to execute it. Do not just explain."
                ),
            })
    elif mode == "Ask Mode":
        if is_disconnected_waapi_request:
            extra.append({
                "role": "user",
                "content": (
                    "NOTE: Wwise/WAAPI is NOT connected. If the question can be "
                    "answered from general WAAPI knowledge, answer directly in natural "
                    "language and remind the user to click Connect for project-specific "
                    "help. Do NOT generate code blocks while disconnected."
                ),
            })
        else:
            extra.append({
                "role": "user",
                "content": (
                    "IMPORTANT: If answering this question requires ANY project-specific "
                    "data (object names, property values, counts, structure, etc.), you "
                    "MUST generate a `python_waapi` code block FIRST to query the data. "
                    "Do NOT guess or assume. Do NOT just explain how to query - actually "
                    "generate the code block so the system can execute it."
                ),
            })

    if resilience_action in ("loop_detected", "reflect") and resilience_message:
        extra.append({"role": "user", "content": resilience_message})

    return extra


# ---------------------------------------------------------------------------
# Tool output → history message
# ---------------------------------------------------------------------------


def format_tool_output_message(
    output: str,
    *,
    mode: str = "Agent Mode",
    has_changes: bool = False,
    max_chars: int = 800_000,
    max_lines: int = 80_000,
) -> str:
    """Prepare a user-role message wrapping code-execution output."""
    safe = truncate_tool_output(output, max_chars=max_chars, max_lines=max_lines)
    msg = f"Output:\n{safe}"
    if mode == "Agent Mode" and not has_changes:
        msg += (
            "\n\n[System Warning] 未检测到 Wwise 写操作。"
            "如果用户请求的是修改操作，请检查代码是否遗漏了实际的写调用。"
        )
    return msg

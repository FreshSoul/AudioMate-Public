"""Context manager — token-aware auto-compaction for LLM messages.

Compaction strategy:
- Estimate token usage of a message list
- Three-tier thresholds: WARNING → AUTO_COMPACT → HARD_LIMIT
- Compact older messages into a summary when approaching limits
- Maintain a *compact boundary* — messages after it stay verbatim

Works alongside the existing ``AgentResilienceManager.summarize_history``
but operates on the *assembled* message list (post-system-prompt) rather
than on raw ``chat_history``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

# Rough heuristic: 1 token ≈ 4 chars for English, ~2 chars for CJK.
# We use a blended estimate of ~3 chars/token to stay conservative.
_CHARS_PER_TOKEN = 3

# CJK character ranges — treated as ~1 token each
_CJK_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff"
    r"\U00020000-\U0002a6df\U0002a700-\U0002b73f"
    r"\U0002b740-\U0002b81f\U0002b820-\U0002ceaf"
    r"\U0002ceb0-\U0002ebef\U00030000-\U0003134f]"
)


def estimate_tokens(text: str) -> int:
    """Fast token-count estimate for a single string."""
    if not text:
        return 0
    cjk_count = len(_CJK_RE.findall(text))
    non_cjk_len = len(text) - cjk_count
    return cjk_count + max(non_cjk_len // _CHARS_PER_TOKEN, 1)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Estimate the total token count for a message list."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            # Multimodal: sum text parts only
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
        else:
            total += estimate_tokens(str(content) if content else "")
        # Role + structural overhead ≈ 4 tokens
        total += 4
    return total


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

@dataclass
class ContextLimits:
    """Token budget thresholds.

    Defaults are tuned for typical 128K-context models.
    """
    max_context_tokens: int = 128_000
    """Model's advertised context window."""

    warning_ratio: float = 0.70
    """Print a log when usage exceeds this fraction."""

    auto_compact_ratio: float = 0.85
    """Automatically compact when usage exceeds this fraction."""

    hard_limit_ratio: float = 0.95
    """Hard-truncate oldest messages when above this fraction."""

    @property
    def warning_tokens(self) -> int:
        return int(self.max_context_tokens * self.warning_ratio)

    @property
    def auto_compact_tokens(self) -> int:
        return int(self.max_context_tokens * self.auto_compact_ratio)

    @property
    def hard_limit_tokens(self) -> int:
        return int(self.max_context_tokens * self.hard_limit_ratio)


# Well-known model context sizes (partial list).
_MODEL_CONTEXT_MAP: dict[str, int] = {
    "gemini": 128_000,
    "gpt-4o": 128_000,
    "gpt-4": 128_000,
    "gpt-3.5": 16_384,
    "claude": 200_000,
    "qwen": 128_000,
    "deepseek": 128_000,
}


def limits_for_model(model_name: str) -> ContextLimits:
    """Return sensible ``ContextLimits`` based on the model name."""
    name = (model_name or "").lower()
    for prefix, ctx in _MODEL_CONTEXT_MAP.items():
        if prefix in name:
            return ContextLimits(max_context_tokens=ctx)
    return ContextLimits()  # default 128K


# ---------------------------------------------------------------------------
# Compaction result
# ---------------------------------------------------------------------------

@dataclass
class CompactResult:
    """Outcome returned by ``auto_compact_messages``."""
    messages: list[dict]
    original_tokens: int
    compacted_tokens: int
    was_compacted: bool
    compact_boundary_index: int | None = None
    """Index of the compact-summary message inside ``messages`` (0-based)."""


# ---------------------------------------------------------------------------
# Core compaction logic
# ---------------------------------------------------------------------------

# Number of *conversation* messages (excluding system) to keep verbatim.
_KEEP_RECENT_MSGS = 8


def auto_compact_messages(
    messages: list[dict],
    limits: ContextLimits | None = None,
    *,
    summariser: Callable[[list[dict]], str] | None = None,
) -> CompactResult:
    """Auto-compact *messages* if total tokens exceed the threshold.

    Parameters
    ----------
    messages:
        Full assembled message list (system + conversation).
    limits:
        Token budget.  Defaults to ``ContextLimits()`` (128K model).
    summariser:
        Optional callable ``(old_messages) -> summary_text``.  If ``None``
        a built-in heuristic summary is used.

    Returns
    -------
    CompactResult
        Always returns a new list — never mutates the input.
    """
    if limits is None:
        limits = ContextLimits()

    original_tokens = estimate_messages_tokens(messages)

    if original_tokens < limits.auto_compact_tokens:
        return CompactResult(
            messages=list(messages),
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            was_compacted=False,
        )

    # --- Separate system prompt from conversation ---
    system_msgs: list[dict] = []
    conv_msgs: list[dict] = []
    for msg in messages:
        if msg.get("role") == "system":
            system_msgs.append(msg)
        else:
            conv_msgs.append(msg)

    if len(conv_msgs) <= _KEEP_RECENT_MSGS:
        # Too few msgs to compact — return as-is
        return CompactResult(
            messages=list(messages),
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            was_compacted=False,
        )

    # Keep the most recent _KEEP_RECENT_MSGS messages verbatim
    old_part = conv_msgs[:-_KEEP_RECENT_MSGS]
    recent_part = conv_msgs[-_KEEP_RECENT_MSGS:]

    # Build summary of old messages
    if summariser:
        summary_text = summariser(old_part)
    else:
        summary_text = _default_summarise(old_part)

    # Use ``assistant`` role for the summary so we never produce two
    # consecutive ``user`` messages (which providers like Claude / OpenAI
    # reject with a 400 when the next conversation turn also starts with
    # ``user``). Prefix the content to make the origin obvious to the model.
    compact_msg: dict = {
        "role": "assistant",
        "content": summary_text,
    }

    def _assemble(recent: list[dict]) -> list[dict]:
        out = list(system_msgs) + [compact_msg]
        # If the first recent message is also ``assistant``, insert a tiny
        # bridging user turn so we keep strict alternation.
        if recent and recent[0].get("role") == "assistant":
            out.append({"role": "user", "content": "(continue)"})
        out.extend(recent)
        return out

    compacted = _assemble(recent_part)
    compacted_tokens = estimate_messages_tokens(compacted)

    # If still above hard limit, aggressively trim from the front of recent —
    # but ALWAYS preserve the latest user message (it's the question that
    # triggered this turn; dropping it leaves the LLM answering blind).
    if compacted_tokens > limits.hard_limit_tokens and len(recent_part) > 2:
        # Index of the most recent ``user`` message — everything from that
        # point on is load-bearing and must not be popped.
        last_user_idx = None
        for i in range(len(recent_part) - 1, -1, -1):
            if recent_part[i].get("role") == "user":
                last_user_idx = i
                break

        # Phase 1: pop oldest messages while we still have room before the
        # final user turn.
        while (
            compacted_tokens > limits.hard_limit_tokens
            and len(recent_part) > 2
            and last_user_idx is not None
            and last_user_idx > 0
        ):
            recent_part.pop(0)
            last_user_idx -= 1
            compacted = _assemble(recent_part)
            compacted_tokens = estimate_messages_tokens(compacted)

        # Phase 2: if still over budget, truncate the summary itself rather
        # than dropping the latest user message. Better to lose history
        # detail than to leave the model answering a question it can't see.
        if compacted_tokens > limits.hard_limit_tokens:
            summary_text_truncated = summary_text
            while (
                compacted_tokens > limits.hard_limit_tokens
                and len(summary_text_truncated) > 200
            ):
                summary_text_truncated = summary_text_truncated[: len(summary_text_truncated) // 2]
                compact_msg["content"] = summary_text_truncated + "\n[摘要因超长被截断]"
                compacted = _assemble(recent_part)
                compacted_tokens = estimate_messages_tokens(compacted)

    return CompactResult(
        messages=compacted,
        original_tokens=original_tokens,
        compacted_tokens=compacted_tokens,
        was_compacted=True,
        compact_boundary_index=len(system_msgs),  # index of the summary msg
    )


# ---------------------------------------------------------------------------
# Default summariser
# ---------------------------------------------------------------------------

def _default_summarise(old_messages: list[dict]) -> str:
    """Build a compact summary of older conversation messages."""
    user_goals: list[str] = []
    actions: list[str] = []
    results: list[str] = []

    for msg in old_messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        text = str(content) if content else ""

        if role == "user":
            # Capture first 300 chars of user messages as goals
            snippet = text[:300].strip()
            if snippet and not text.startswith("[历史摘要]") and not text.startswith("Output:"):
                user_goals.append(snippet)
        elif role == "assistant":
            # Extract code blocks as action summaries
            code_blocks = re.findall(
                r"```(?:python_waapi|python)\s*\n(.*?)```",
                text, re.DOTALL,
            )
            for cb in code_blocks[:3]:
                actions.append(cb.strip()[:150])
            # Also capture non-code assistant text (first 200 chars)
            clean = re.sub(r"```.*?```", "", text, flags=re.DOTALL).strip()
            if clean:
                results.append(clean[:200])

    parts = ["[历史摘要] 以下是之前对话内容的压缩摘要，用于保持上下文连贯。"]
    if user_goals:
        parts.append(f"用户目标: {'; '.join(user_goals[:3])}")
    if actions:
        parts.append("已执行操作:\n" + "\n".join(f"  - {a}" for a in actions[:5]))
    if results:
        parts.append("关键结果:\n" + "\n".join(f"  - {r}" for r in results[:5]))

    return "\n".join(parts)

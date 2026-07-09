"""Provider event types — structured stream consumed by LLMService.stream_events.

Legacy ``generate()`` only yields text. ``generate_events()`` yields these
typed events so callers can distinguish thinking, tool_use, usage and finish
signals without ad-hoc string parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union


@dataclass
class TextDelta:
    """A chunk of visible text from the assistant."""
    text: str


@dataclass
class ThinkingDelta:
    """A chunk of provider-native reasoning content (Claude extended thinking,
    DeepSeek-R1 reasoning_content, o-series reasoning summary, …)."""
    text: str


@dataclass
class ToolUseStart:
    """A native tool call has begun streaming. ``input`` is the partial JSON
    string accumulated so far (provider-specific incremental shape)."""
    call_id: str
    name: str


@dataclass
class ToolUseDelta:
    """Incremental update to the tool call's JSON input string."""
    call_id: str
    partial_input: str


@dataclass
class ToolUse:
    """Final, fully-assembled tool call (input parsed to dict).

    Emitted at the end of a tool_use block; ``input`` is the parsed JSON
    object. Use this when consumers can wait for the whole call.
    """
    call_id: str
    name: str
    input: dict


@dataclass
class UsageInfo:
    """Token usage and cache stats reported by the provider, if available."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class FinishReason:
    """End-of-response marker."""
    reason: str  # "stop" | "length" | "tool_use" | "error" | provider-specific


@dataclass
class ProviderError:
    """Error surface — providers translate exceptions into this event so
    consumers don't need provider-specific exception handling."""
    message: str


ProviderEvent = Union[
    TextDelta,
    ThinkingDelta,
    ToolUseStart,
    ToolUseDelta,
    ToolUse,
    UsageInfo,
    FinishReason,
    ProviderError,
]


__all__ = [
    "ProviderEvent",
    "TextDelta",
    "ThinkingDelta",
    "ToolUseStart",
    "ToolUseDelta",
    "ToolUse",
    "UsageInfo",
    "FinishReason",
    "ProviderError",
]

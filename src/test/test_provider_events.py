"""Provider-event interface tests with mock SDK responses.

No network — drives a fake OpenAI / Anthropic stream through the provider
and checks that ``generate_events`` produces the expected ``ProviderEvent``
sequence. Catches regressions in tool-call buffering, usage parsing, and
text/thinking delta routing.
"""

from __future__ import annotations

import types

import pytest

from src.llm.provider_events import (
    FinishReason,
    TextDelta,
    ThinkingDelta,
    ToolUse,
    ToolUseStart,
    UsageInfo,
)
from src.llm.providers.openai_compat import OpenAICompatProvider, _system_to_string


# ---------------------------------------------------------------------------
# Helpers — fake OpenAI SDK objects
# ---------------------------------------------------------------------------


def _ns(**kw):
    """Quick SimpleNamespace shim."""
    return types.SimpleNamespace(**kw)


def _delta(content=None, tool_calls=None, reasoning_content=None):
    return _ns(content=content, tool_calls=tool_calls or [], reasoning_content=reasoning_content)


def _chunk(delta=None, finish_reason=None):
    choice = _ns(delta=delta or _delta(), finish_reason=finish_reason)
    return _ns(choices=[choice])


def _tc(idx, *, id=None, name=None, args=None):
    fn = _ns(name=name, arguments=args)
    return _ns(index=idx, id=id, function=fn)


# ---------------------------------------------------------------------------
# OpenAICompatProvider._stream_events
# ---------------------------------------------------------------------------


def test_openai_text_stream_yields_text_deltas():
    p = OpenAICompatProvider()
    stream = iter([
        _chunk(_delta(content="Hello")),
        _chunk(_delta(content=" world")),
        _chunk(_delta(), finish_reason="stop"),
    ])
    events = list(p._stream_events(stream))
    texts = [e.text for e in events if isinstance(e, TextDelta)]
    assert texts == ["Hello", " world"]
    finishes = [e for e in events if isinstance(e, FinishReason)]
    assert finishes and finishes[-1].reason == "stop"


def test_openai_reasoning_content_yields_thinking_delta():
    """DeepSeek-R1 emits ``reasoning_content`` for chain-of-thought."""
    p = OpenAICompatProvider()
    stream = iter([
        _chunk(_delta(reasoning_content="thinking...")),
        _chunk(_delta(content="answer")),
        _chunk(_delta(), finish_reason="stop"),
    ])
    events = list(p._stream_events(stream))
    thinks = [e.text for e in events if isinstance(e, ThinkingDelta)]
    texts = [e.text for e in events if isinstance(e, TextDelta)]
    assert thinks == ["thinking..."]
    assert texts == ["answer"]


def test_openai_tool_call_buffered_across_chunks():
    """Tool args arrive as partial JSON across many chunks — they should be
    accumulated and parsed once at the end."""
    p = OpenAICompatProvider()
    stream = iter([
        _chunk(_delta(tool_calls=[_tc(0, id="call_1", name="search", args='{"q')])),
        _chunk(_delta(tool_calls=[_tc(0, args='": "we')])),
        _chunk(_delta(tool_calls=[_tc(0, args='ather"}')])),
        _chunk(_delta(), finish_reason="tool_calls"),
    ])
    events = list(p._stream_events(stream))
    starts = [e for e in events if isinstance(e, ToolUseStart)]
    finals = [e for e in events if isinstance(e, ToolUse)]
    assert len(starts) == 1
    assert starts[0].name == "search"
    assert len(finals) == 1
    assert finals[0].name == "search"
    assert finals[0].input == {"q": "weather"}


def test_openai_malformed_tool_args_falls_back_to_raw():
    """If tool args aren't valid JSON, ToolUse.input should still surface
    the raw string under ``_raw`` instead of dropping it."""
    p = OpenAICompatProvider()
    stream = iter([
        _chunk(_delta(tool_calls=[_tc(0, id="x", name="t", args="not-json")])),
        _chunk(_delta(), finish_reason="tool_calls"),
    ])
    finals = [e for e in p._stream_events(stream) if isinstance(e, ToolUse)]
    assert finals[0].input == {"_raw": "not-json"}


def test_openai_length_finish_adds_truncation_hint():
    p = OpenAICompatProvider()
    stream = iter([
        _chunk(_delta(content="partial")),
        _chunk(_delta(), finish_reason="length"),
    ])
    texts = [e.text for e in p._stream_events(stream) if isinstance(e, TextDelta)]
    assert any("截断" in t or "继续" in t for t in texts)


# ---------------------------------------------------------------------------
# _system_to_string adapter
# ---------------------------------------------------------------------------


def test_system_to_string_passthrough_string():
    assert _system_to_string("abc") == "abc"


def test_system_to_string_flattens_blocks():
    blocks = [
        {"type": "text", "text": "A"},
        {"type": "text", "text": "B"},
    ]
    assert _system_to_string(blocks) == "A\n\nB"


def test_system_to_string_handles_unknown_block_shape():
    """Non-standard blocks (e.g. with ``content`` instead of ``text``) should
    still surface their text rather than be silently dropped."""
    assert _system_to_string([{"content": "hello"}]) == "hello"


def test_system_to_string_empty_returns_empty():
    assert _system_to_string([]) == ""
    assert _system_to_string(None) == ""


# ---------------------------------------------------------------------------
# Legacy ``generate`` adapter must still yield strings.
# ---------------------------------------------------------------------------


def test_legacy_generate_yields_only_text_strings():
    """The text-only ``generate`` wrapper must filter out non-text events so
    callers that still consume the legacy iterator don't break."""
    from src.llm.provider_events import (
        TextDelta,
        ThinkingDelta,
        UsageInfo,
        FinishReason,
    )
    from src.llm.providers.base import text_events_to_strings

    events = [
        TextDelta("hi"),
        ThinkingDelta("internal"),
        TextDelta(" there"),
        UsageInfo(input_tokens=10, output_tokens=2),
        FinishReason("stop"),
    ]
    out = list(text_events_to_strings(iter(events)))
    assert out == ["hi", " there"]


# ---------------------------------------------------------------------------
# AnthropicProvider._stream_events — both high-level and raw event shapes.
#
# We don't construct a real anthropic.Anthropic client; we drive the
# helper directly with a fake stream context.
# ---------------------------------------------------------------------------


class _FakeAnthropicStream:
    """Mimics the ``with client.messages.stream(...) as s`` context."""

    def __init__(self, events, final_message=None):
        self._events = events
        self._final = final_message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._final


def _fake_client(events, final=None):
    """Build a fake Anthropic client whose ``messages.stream(...)`` returns
    the given events."""
    class _Messages:
        def stream(self, **kw):
            return _FakeAnthropicStream(events, final_message=final)

    class _Client:
        messages = _Messages()

    return _Client()


def test_anthropic_high_level_text_events():
    """Official SDK yields ``type='text'`` events with the delta on .text."""
    from src.llm.providers.anthropic import AnthropicProvider

    events = [
        _ns(type="text", text="Hello"),
        _ns(type="text", text=" world"),
    ]
    final = _ns(
        usage=_ns(input_tokens=10, output_tokens=2, cache_read_input_tokens=8, cache_creation_input_tokens=0),
        stop_reason="end_turn",
    )

    p = AnthropicProvider()
    p.client = _fake_client(events, final=final)

    out = list(p._stream_events({}))
    texts = [e.text for e in out if isinstance(e, TextDelta)]
    usages = [e for e in out if isinstance(e, UsageInfo)]
    finishes = [e for e in out if isinstance(e, FinishReason)]
    assert texts == ["Hello", " world"]
    assert usages and usages[0].cache_read_input_tokens == 8
    assert finishes and finishes[0].reason == "end_turn"


def test_anthropic_raw_event_compat_path():
    """The SDK iterator yields BOTH the raw ``content_block_delta`` and a
    synthesised ``text`` event for the SAME payload. We must consume only
    the high-level event or text will be duplicated (the visible bug:
    `<think 你` followed by empty bullets in the chat bubble)."""
    from src.llm.providers.anthropic import AnthropicProvider

    # Same payload, both event forms — simulating the SDK's build_events.
    events = [
        _ns(type="content_block_delta", index=0, delta=_ns(type="text_delta", text="hi")),
        _ns(type="text", text="hi"),
        _ns(type="content_block_delta", index=0, delta=_ns(type="text_delta", text=" again")),
        _ns(type="text", text=" again"),
    ]
    p = AnthropicProvider()
    p.client = _fake_client(events, final=_ns(usage=None, stop_reason="end_turn"))
    out = list(p._stream_events({}))
    texts = [e.text for e in out if isinstance(e, TextDelta)]
    # Must be ["hi", " again"], NOT ["hi", "hi", " again", " again"].
    assert texts == ["hi", " again"], (
        f"text was duplicated: {texts!r}. The provider must consume only the "
        "high-level ``text`` event and skip the raw ``content_block_delta``."
    )


def test_anthropic_high_level_thinking_event():
    from src.llm.providers.anthropic import AnthropicProvider

    events = [_ns(type="thinking", thinking="planning...")]
    p = AnthropicProvider()
    p.client = _fake_client(events, final=_ns(usage=None, stop_reason=None))
    out = list(p._stream_events({}))
    thinks = [e for e in out if isinstance(e, ThinkingDelta)]
    assert thinks and thinks[0].text == "planning..."


def test_anthropic_tool_use_full_lifecycle():
    """Tool block: start → input_json deltas → content_block_stop with parsed input."""
    from src.llm.providers.anthropic import AnthropicProvider

    tool_block_started = _ns(type="tool_use", id="toolu_1", name="lookup")
    tool_block_done = _ns(type="tool_use", id="toolu_1", name="lookup", input={"q": "weather"})

    events = [
        _ns(type="content_block_start", index=0, content_block=tool_block_started),
        _ns(type="input_json", partial_json='{"q":"weather"}'),
        _ns(type="content_block_stop", index=0, content_block=tool_block_done),
    ]
    p = AnthropicProvider()
    p.client = _fake_client(events, final=_ns(usage=None, stop_reason="tool_use"))
    out = list(p._stream_events({}))
    starts = [e for e in out if isinstance(e, ToolUseStart)]
    finals = [e for e in out if isinstance(e, ToolUse)]
    assert starts and starts[0].name == "lookup"
    assert finals and finals[0].input == {"q": "weather"}


def test_anthropic_usage_from_streamed_events():
    """Some proxy gateways drop ``usage`` on the final message snapshot.
    We must still surface it from message_start + message_delta."""
    from src.llm.providers.anthropic import AnthropicProvider

    msg_start = _ns(
        message=_ns(
            usage=_ns(
                input_tokens=500,
                output_tokens=0,
                cache_read_input_tokens=480,
                cache_creation_input_tokens=0,
            )
        )
    )
    events = [
        _ns(type="message_start", message=msg_start.message),
        _ns(type="text", text="ok"),
        _ns(type="message_delta", usage=_ns(output_tokens=42)),
    ]
    p = AnthropicProvider()
    # Final message has no usage — proxy strip case.
    p.client = _fake_client(events, final=_ns(usage=None, stop_reason="end_turn"))
    out = list(p._stream_events({}))
    usages = [e for e in out if isinstance(e, UsageInfo)]
    assert usages, "expected UsageInfo to be emitted from streamed events"
    u = usages[0]
    assert u.input_tokens == 500
    assert u.output_tokens == 42
    assert u.cache_read_input_tokens == 480


def test_anthropic_usage_falls_back_to_final_message():
    """When no streamed usage events fire (legacy SDK behaviour), the final
    message snapshot must still be used."""
    from src.llm.providers.anthropic import AnthropicProvider

    events = [_ns(type="text", text="hi")]
    final = _ns(
        usage=_ns(
            input_tokens=10,
            output_tokens=3,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
        stop_reason="end_turn",
    )
    p = AnthropicProvider()
    p.client = _fake_client(events, final=final)
    out = list(p._stream_events({}))
    usages = [e for e in out if isinstance(e, UsageInfo)]
    assert usages and usages[0].input_tokens == 10 and usages[0].output_tokens == 3


def test_system_blocks_round_trip_to_anthropic_kwargs():
    """End-to-end check that PromptBlocks → assemble_for_anthropic → the
    ``system`` kwarg reaches the SDK with cache_control intact."""
    from src.engine.prompt_blocks import PromptBlock, assemble_for_anthropic

    blocks = [
        PromptBlock(id="s", content="STATIC", scope="static"),
        PromptBlock(id="x", content="SESSION", scope="session"),
        PromptBlock(id="t", content="TURN", scope="turn"),
    ]
    payload = assemble_for_anthropic(blocks)
    # The shape we hand to anthropic.Anthropic().messages.stream(system=...).
    assert isinstance(payload, list)
    assert all(b.get("type") == "text" for b in payload)
    cached = [b for b in payload if "cache_control" in b]
    assert len(cached) == 2  # static + session
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in cached)

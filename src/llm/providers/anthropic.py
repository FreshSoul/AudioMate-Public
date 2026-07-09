"""Anthropic (Claude) provider.

Handles the OpenAI → Anthropic message-shape conversion (hoisted system
prompt, role-merging, multimodal blocks) so callers can keep emitting
OpenAI-style message dicts.
"""

from __future__ import annotations

import json
import re
from typing import Iterator

import anthropic

from src.llm.provider_events import (
    FinishReason,
    ProviderError,
    ProviderEvent,
    TextDelta,
    ThinkingDelta,
    ToolUse,
    ToolUseDelta,
    ToolUseStart,
    UsageInfo,
)
from src.llm.providers.base import friendly_llm_error, text_events_to_strings


_DATA_URL_RE = re.compile(r"^data:(?P<media_type>[^;,]+);base64,(?P<data>.+)$", re.DOTALL)


# Optional proxy mappings: OpenAI base -> Anthropic base.
# The Anthropic SDK appends ``/v1/messages`` to the base_url automatically.
_ANTHROPIC_BASE_URL_MAP: dict[str, str] = {}


def _content_to_text(content) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text") or ""
                if text:
                    parts.append(str(text))
            elif isinstance(part, str):
                parts.append(part)
        return "\n\n".join(parts)
    return str(content) if content else ""


def _convert_content_for_anthropic(content):
    """Convert OpenAI-style multimodal content into Anthropic content blocks."""
    if not isinstance(content, list):
        return content or ""

    blocks: list[dict] = []
    for part in content:
        if isinstance(part, str):
            if part:
                blocks.append({"type": "text", "text": part})
            continue
        if not isinstance(part, dict):
            continue

        part_type = part.get("type")
        if part_type == "text":
            text = part.get("text") or ""
            if text:
                blocks.append({"type": "text", "text": str(text)})
        elif part_type == "image" and isinstance(part.get("source"), dict):
            blocks.append(part)
        elif part_type == "image_url":
            image_url = part.get("image_url") or {}
            url = image_url.get("url") if isinstance(image_url, dict) else ""
            match = _DATA_URL_RE.match(url or "")
            if match:
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": match.group("media_type"),
                        "data": match.group("data"),
                    },
                })

    return blocks or ""


def _merge_anthropic_content(left, right):
    left_blocks = left if isinstance(left, list) else ([{"type": "text", "text": left}] if left else [])
    right_blocks = right if isinstance(right, list) else ([{"type": "text", "text": right}] if right else [])
    merged = list(left_blocks) + list(right_blocks)
    return merged or ""


def convert_messages_for_anthropic(messages: list[dict]):
    """Convert OpenAI-format messages to Anthropic format.

    Returns ``(system_prompt: str, anthropic_messages: list[dict])``.
    Anthropic requires:
      - ``system`` as a separate top-level parameter (not a message)
      - Only ``user`` and ``assistant`` roles in the messages list
      - Messages must start with a ``user`` role
      - No consecutive messages with the same role
    """
    system_parts: list[str] = []
    conv_messages: list[dict] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(_content_to_text(content))
        elif role in ("user", "assistant"):
            conv_messages.append({"role": role, "content": _convert_content_for_anthropic(content)})

    merged: list[dict] = []
    for msg in conv_messages:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] = _merge_anthropic_content(merged[-1]["content"], msg["content"])
        else:
            merged.append(dict(msg))

    if merged and merged[0]["role"] != "user":
        while merged and merged[0]["role"] != "user":
            system_parts.append(_content_to_text(merged.pop(0)["content"]))

    if not merged:
        merged = [{"role": "user", "content": "(empty)"}]

    return "\n\n".join(system_parts), merged


def _anthropic_base_url(base_url: str | None) -> str | None:
    """Derive the Anthropic-compatible base URL from the OpenAI base URL."""
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        return None  # Use Anthropic default (api.anthropic.com)

    normalized = raw.rstrip("/")
    if normalized in _ANTHROPIC_BASE_URL_MAP:
        return _ANTHROPIC_BASE_URL_MAP[normalized]
    if normalized.endswith("/v1"):
        return normalized[:-3]
    return normalized


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        self.api_key: str | None = None
        self.base_url: str | None = None
        self.client: anthropic.Anthropic | None = None

    def supports(self, model: str) -> bool:
        return bool(model) and "claude" in model.lower()

    def configure(self, *, api_key: str | None, base_url: str | None) -> None:
        self.api_key = (api_key or "").strip() or None
        self.base_url = (base_url or "").strip() or None
        if not self.api_key:
            self.client = None
            return
        kwargs: dict = {"api_key": self.api_key}
        derived = _anthropic_base_url(self.base_url)
        if derived:
            kwargs["base_url"] = derived
        self.client = anthropic.Anthropic(**kwargs)

    def generate(
        self,
        messages: list[dict],
        model: str,
        *,
        stream: bool = True,
        max_tokens: int = 88888,
    ) -> Iterator[str]:
        """Legacy text-only entry point. Delegates to ``generate_events``."""
        yield from text_events_to_strings(
            self.generate_events(messages, model, stream=stream, max_tokens=max_tokens)
        )

    def generate_events(
        self,
        messages: list[dict],
        model: str,
        *,
        stream: bool = True,
        max_tokens: int = 88888,
        system: list[dict] | str | None = None,
        tools: list[dict] | None = None,
        thinking: dict | None = None,
        extra: dict | None = None,
    ) -> Iterator[ProviderEvent]:
        if not self.client:
            yield ProviderError("Error: API Key not configured.")
            return

        # If caller supplied a structured ``system`` (e.g. blocks with
        # cache_control), use it verbatim. Otherwise derive from messages
        # so legacy callers keep working.
        if system is None:
            derived_system, conv_messages = convert_messages_for_anthropic(messages)
            system_payload: list[dict] | str | None = derived_system or None
        else:
            _, conv_messages = convert_messages_for_anthropic(messages)
            system_payload = system

        kwargs: dict = {
            "model": model,
            "messages": conv_messages,
            "max_tokens": max_tokens,
        }
        if system_payload:
            kwargs["system"] = system_payload
        if tools:
            kwargs["tools"] = tools
        if thinking:
            kwargs["thinking"] = thinking
        if extra:
            kwargs.update(extra)

        try:
            if stream:
                yield from self._stream_events(kwargs)
            else:
                yield from self._oneshot_events(kwargs)
        except Exception as exc:  # noqa: BLE001
            yield ProviderError(friendly_llm_error(exc))

    # ------------------------------------------------------------------
    # Streaming / one-shot helpers
    # ------------------------------------------------------------------

    def _stream_events(self, kwargs: dict) -> Iterator[ProviderEvent]:
        """Drive the Anthropic SDK stream and translate events.

        The SDK's ``MessageStream`` iterator yields BOTH the raw
        ``content_block_delta`` event AND a synthesised high-level event
        (``text`` / ``thinking`` / ``input_json``) for the same payload —
        see ``anthropic.lib.streaming._messages.build_events``. We must
        consume only ONE of the two or text will be duplicated, which is
        what the user saw as "<think 你" followed by empty bullets when
        markdown rendered the doubled stream.

        Strategy: consume ONLY the high-level events. We skip every
        ``content_block_delta``. ``build_events`` always synthesises a
        matching high-level event whenever the raw delta carries one of
        the four payload kinds we care about (text / thinking / input_json
        / citations), so nothing is lost.

        Usage is collected from the stream directly (``message_start`` for
        input + cache counts, ``message_delta`` for output count) since
        some proxy gateways drop the ``usage`` field on the final message
        snapshot.
        """
        tool_buf: dict[int, dict] = {}  # block_index -> {id, name, input_str}
        usage_acc = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        saw_usage = False

        with self.client.messages.stream(**kwargs) as stream_resp:
            for event in stream_resp:
                etype = getattr(event, "type", None)

                # ---- Skip raw delta — its content is already covered by
                # the synthesised high-level event the SDK yields next. ----
                if etype == "content_block_delta":
                    continue

                # ---- Usage events ----
                if etype == "message_start":
                    msg = getattr(event, "message", None)
                    u = getattr(msg, "usage", None) if msg else None
                    if u is not None:
                        saw_usage = True
                        usage_acc["input_tokens"] = getattr(u, "input_tokens", 0) or 0
                        usage_acc["cache_read_input_tokens"] = getattr(u, "cache_read_input_tokens", 0) or 0
                        usage_acc["cache_creation_input_tokens"] = getattr(u, "cache_creation_input_tokens", 0) or 0
                        usage_acc["output_tokens"] = getattr(u, "output_tokens", 0) or 0
                    continue
                if etype == "message_delta":
                    u = getattr(event, "usage", None)
                    if u is not None:
                        saw_usage = True
                        usage_acc["output_tokens"] = getattr(u, "output_tokens", usage_acc["output_tokens"]) or usage_acc["output_tokens"]
                    continue

                # ---- High-level content events ----
                if etype == "text":
                    text = getattr(event, "text", "") or ""
                    if text:
                        yield TextDelta(text)
                    continue
                if etype == "thinking":
                    text = getattr(event, "thinking", "") or ""
                    if text:
                        yield ThinkingDelta(text)
                    continue
                if etype == "input_json":
                    chunk = getattr(event, "partial_json", "") or ""
                    if tool_buf:
                        idx = max(tool_buf.keys())
                        tool_buf[idx]["input_str"] += chunk
                        yield ToolUseDelta(
                            call_id=tool_buf[idx]["id"],
                            partial_input=chunk,
                        )
                    continue

                # ---- Tool block start / stop ----
                if etype == "content_block_start":
                    block = getattr(event, "content_block", None)
                    btype = getattr(block, "type", None) if block else None
                    if btype == "tool_use":
                        idx = getattr(event, "index", 0) or 0
                        tool_buf[idx] = {
                            "id": getattr(block, "id", "") or "",
                            "name": getattr(block, "name", "") or "",
                            "input_str": "",
                        }
                        yield ToolUseStart(
                            call_id=tool_buf[idx]["id"],
                            name=tool_buf[idx]["name"],
                        )
                    continue
                if etype == "content_block_stop":
                    block = getattr(event, "content_block", None)
                    btype = getattr(block, "type", None) if block else None
                    if btype == "tool_use" or (block is None and tool_buf):
                        idx = getattr(event, "index", 0) or 0
                        if idx not in tool_buf and tool_buf:
                            idx = max(tool_buf.keys())
                        info = tool_buf.pop(idx, None)
                        parsed = getattr(block, "input", None) if block else None
                        if not isinstance(parsed, dict):
                            raw = (info or {}).get("input_str", "")
                            try:
                                parsed = json.loads(raw or "{}")
                            except Exception:
                                parsed = {"_raw": raw}
                            if not isinstance(parsed, dict):
                                parsed = {"_raw": raw}
                        if info or block:
                            yield ToolUse(
                                call_id=(getattr(block, "id", "") if block else "") or (info or {}).get("id", ""),
                                name=(getattr(block, "name", "") if block else "") or (info or {}).get("name", ""),
                                input=parsed,
                            )
                    continue

            # Prefer streamed usage; fall back to the final-message snapshot
            # for SDK paths that report only there.
            final = stream_resp.get_final_message()
            if not saw_usage and final is not None:
                yield from _usage_event(final)
            elif saw_usage:
                yield UsageInfo(**usage_acc)

            stop_reason = getattr(final, "stop_reason", None) if final else None
            if stop_reason == "max_tokens":
                yield TextDelta('\n\n[回复因长度限制被截断，请发送"继续"以获取剩余内容]')
            if stop_reason:
                yield FinishReason(stop_reason)

    def _oneshot_events(self, kwargs: dict) -> Iterator[ProviderEvent]:
        response = self.client.messages.create(**kwargs)
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text = getattr(block, "text", "") or ""
                if text:
                    yield TextDelta(text)
            elif btype == "thinking":
                text = getattr(block, "thinking", "") or ""
                if text:
                    yield ThinkingDelta(text)
            elif btype == "tool_use":
                call_input = getattr(block, "input", {}) or {}
                if not isinstance(call_input, dict):
                    call_input = {"_raw": call_input}
                yield ToolUse(
                    call_id=getattr(block, "id", "") or "",
                    name=getattr(block, "name", "") or "",
                    input=call_input,
                )
        yield from _usage_event(response)
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "max_tokens":
            yield TextDelta('\n\n[回复因长度限制被截断，请发送"继续"以获取剩余内容]')
        if stop_reason:
            yield FinishReason(stop_reason)


def _usage_event(msg) -> Iterator[UsageInfo]:
    """Extract a ``UsageInfo`` event from an Anthropic message if present."""
    usage = getattr(msg, "usage", None)
    if usage is None:
        return
    yield UsageInfo(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )

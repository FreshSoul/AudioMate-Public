"""OpenAI-compatible provider.

Catch-all for any model whose API speaks the OpenAI chat-completions shape.
"""

from __future__ import annotations

import json
from typing import Iterator

from openai import OpenAI

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


class OpenAICompatProvider:
    name = "openai"

    def __init__(self) -> None:
        self.api_key: str | None = None
        self.base_url: str | None = None
        self.client: OpenAI | None = None

    def supports(self, model: str) -> bool:
        # Fallback provider: handle whatever the Anthropic provider rejected.
        return True

    def configure(self, *, api_key: str | None, base_url: str | None) -> None:
        self.api_key = (api_key or "").strip() or None
        self.base_url = (base_url or "").strip() or None
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        else:
            self.client = None

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

        # If caller supplied a structured ``system``, inject it as a leading
        # system message (OpenAI-compat doesn't have a separate system param).
        # Accepts either a plain string or a list of {type:'text', text:...}
        # blocks (cache_control hints are ignored — most compat providers do
        # automatic prefix caching).
        if system is not None:
            sys_text = _system_to_string(system)
            if sys_text:
                # Replace any existing leading system message rather than stack
                if messages and messages[0].get("role") == "system":
                    messages = [{"role": "system", "content": sys_text}] + list(messages[1:])
                else:
                    messages = [{"role": "system", "content": sys_text}] + list(messages)

        kwargs: dict = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if extra:
            kwargs.update(extra)
        # ``thinking`` is intentionally ignored here — providers that expose
        # reasoning use different param names (reasoning_effort / reasoning).
        # Callers must pass those via ``extra`` for now.

        try:
            response = self.client.chat.completions.create(**kwargs)
            if stream:
                yield from self._stream_events(response)
            else:
                yield from self._oneshot_events(response)
        except Exception as exc:  # noqa: BLE001
            # Fallback if upstream rejected ``tools`` — retry without them.
            if tools and _is_tools_rejection(exc):
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)
                try:
                    response = self.client.chat.completions.create(**kwargs)
                    if stream:
                        yield from self._stream_events(response)
                    else:
                        yield from self._oneshot_events(response)
                    return
                except Exception as inner:  # noqa: BLE001
                    yield ProviderError(friendly_llm_error(inner))
                    return
            yield ProviderError(friendly_llm_error(exc))

    # ------------------------------------------------------------------
    # Stream / oneshot helpers
    # ------------------------------------------------------------------

    def _stream_events(self, response) -> Iterator[ProviderEvent]:
        """Translate OpenAI's chunked deltas to ``ProviderEvent`` values.

        Tool calls are streamed by ``index`` with incremental name/argument
        fragments; we buffer them and emit a final ``ToolUse`` per index when
        the stream ends.
        """
        tool_buf: dict[int, dict] = {}  # index -> {id, name, args}
        announced: set[int] = set()
        final_reason: str | None = None

        for chunk in response:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = getattr(choice, "delta", None)
            if delta is not None:
                content = getattr(delta, "content", None)
                if content:
                    yield TextDelta(content)

                # DeepSeek-R1 / Qwen-thinking-style reasoning field
                reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                if reasoning:
                    yield ThinkingDelta(str(reasoning))

                tcalls = getattr(delta, "tool_calls", None) or []
                for tc in tcalls:
                    idx = getattr(tc, "index", 0) or 0
                    fn = getattr(tc, "function", None)
                    tc_id = getattr(tc, "id", None)
                    name_chunk = getattr(fn, "name", None) if fn else None
                    args_chunk = getattr(fn, "arguments", None) if fn else None

                    buf = tool_buf.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc_id:
                        buf["id"] = tc_id
                    if name_chunk:
                        buf["name"] = (buf["name"] or "") + name_chunk
                    if args_chunk:
                        buf["args"] += args_chunk
                        if idx not in announced and buf["name"]:
                            announced.add(idx)
                            yield ToolUseStart(call_id=buf["id"], name=buf["name"])
                        if idx in announced:
                            yield ToolUseDelta(call_id=buf["id"], partial_input=args_chunk)

            reason = getattr(choice, "finish_reason", None)
            if reason:
                final_reason = reason

        for idx, buf in tool_buf.items():
            try:
                parsed = json.loads(buf["args"] or "{}")
            except Exception:
                parsed = {"_raw": buf["args"]}
            if not isinstance(parsed, dict):
                parsed = {"_raw": buf["args"]}
            yield ToolUse(call_id=buf["id"], name=buf["name"], input=parsed)

        if final_reason == "length":
            yield TextDelta('\n\n[回复因长度限制被截断，请发送"继续"以获取剩余内容]')
        if final_reason:
            yield FinishReason(final_reason)

    def _oneshot_events(self, response) -> Iterator[ProviderEvent]:
        if not response.choices:
            return
        choice = response.choices[0]
        msg = choice.message
        content = getattr(msg, "content", None) or ""
        if content:
            yield TextDelta(content)
        reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
        if reasoning:
            yield ThinkingDelta(str(reasoning))
        for tc in getattr(msg, "tool_calls", None) or []:
            fn = getattr(tc, "function", None)
            raw = getattr(fn, "arguments", "") if fn else ""
            try:
                parsed = json.loads(raw or "{}")
            except Exception:
                parsed = {"_raw": raw}
            if not isinstance(parsed, dict):
                parsed = {"_raw": raw}
            yield ToolUse(
                call_id=getattr(tc, "id", "") or "",
                name=getattr(fn, "name", "") or "" if fn else "",
                input=parsed,
            )
        usage = getattr(response, "usage", None)
        if usage is not None:
            yield UsageInfo(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            )
        reason = getattr(choice, "finish_reason", None)
        if reason == "length":
            yield TextDelta('\n\n[回复因长度限制被截断，请发送"继续"以获取剩余内容]')
        if reason:
            yield FinishReason(reason)


def _system_to_string(system) -> str:
    """Flatten a structured system payload to a single string for OpenAI compat."""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts: list[str] = []
        for block in system:
            if isinstance(block, str):
                if block:
                    parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    t = block.get("text") or ""
                    if t:
                        parts.append(str(t))
                else:
                    t = block.get("text") or block.get("content") or ""
                    if t:
                        parts.append(str(t))
        return "\n\n".join(parts)
    return ""


def _is_tools_rejection(exc: Exception) -> bool:
    """Heuristic: did the server reject the request because it doesn't support tools?"""
    msg = str(exc).lower()
    return (
        "tool" in msg
        and ("not support" in msg or "unsupported" in msg or "invalid" in msg or "unknown" in msg)
    )

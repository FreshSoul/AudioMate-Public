"""Provider protocol — the minimal contract LLMService routes through.

Only ``generate`` is part of the protocol. Embedding lives elsewhere
(``WaapiDocRetriever`` keeps its own client) and is intentionally out of
scope here.
"""

from __future__ import annotations

from typing import Iterator, Protocol

from src.llm.provider_events import ProviderEvent, TextDelta


class Provider(Protocol):
    """Minimal LLM provider contract used by :class:`LLMService`."""

    name: str

    def supports(self, model: str) -> bool:
        """Return True if this provider handles ``model``."""

    def configure(self, *, api_key: str | None, base_url: str | None) -> None:
        """Reconfigure the underlying client. Called whenever credentials change."""

    def generate(
        self,
        messages: list[dict],
        model: str,
        *,
        stream: bool = True,
        max_tokens: int = 88888,
    ) -> Iterator[str]:
        """Yield response chunks (or one chunk when stream=False).

        Legacy entry point — kept for callers that only consume text.
        New code should prefer ``generate_events``.
        """

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
        """Yield structured ``ProviderEvent`` values.

        Optional kwargs let callers opt into provider-native features:

        - ``system`` — pre-built system content (list-of-blocks for cache_control
          on Anthropic, or a single string for OpenAI-compatible providers).
          When omitted, the provider extracts the system prompt from ``messages``
          (legacy behaviour).
        - ``tools`` — native tool schemas (Anthropic ``tools`` / OpenAI
          ``tools`` shape; providers that don't support it should ignore).
        - ``thinking`` — extended-thinking config (Anthropic shape preferred).
        - ``extra`` — provider-specific passthrough kwargs.
        """


def text_events_to_strings(events: Iterator[ProviderEvent]) -> Iterator[str]:
    """Adapter: filter an event stream down to its visible text deltas.

    Used by ``Provider.generate`` wrappers to preserve the legacy
    text-only contract.
    """
    for ev in events:
        if isinstance(ev, TextDelta):
            yield ev.text


def friendly_llm_error(exc: Exception) -> str:
    """Translate a provider-side exception into a user-facing string.

    Shared between providers so error wording stays consistent.
    """
    raw = str(exc)
    lowered = raw.lower()
    if "429" in raw or "rate_limit" in lowered or "limit exceed" in lowered:
        return (
            "Error calling LLM: 当前模型服务返回 429（额度/频率限制）。"
            "图片请求会比纯文本消耗更多额度；请稍后重试，或切换到支持视觉且额度充足的模型。"
        )
    return f"Error calling LLM: {raw}"

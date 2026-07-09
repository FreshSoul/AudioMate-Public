"""LLM service — thin router over :mod:`src.llm.providers`.

The service is configured with a single ``(api_key, base_url, model)``
triple. ``get_response`` picks the first provider whose ``supports(model)``
returns True and yields its output. Both providers share the same key/url
during configuration so switching models is a metadata change, not a
re-auth.

The legacy ``client`` / ``anthropic_client`` attributes are preserved via
``__getattr__`` for any caller that still reads them directly.
"""

from __future__ import annotations

import os
from typing import Iterator

from src.llm.provider_events import ProviderEvent
from src.llm.providers import AnthropicProvider, OpenAICompatProvider, Provider
from src.llm.providers.anthropic import convert_messages_for_anthropic as _convert_messages_for_anthropic
from src.llm.providers.base import friendly_llm_error as _friendly_llm_error

__all__ = [
    "LLMService",
    "_convert_messages_for_anthropic",
    "_friendly_llm_error",
    "_is_anthropic_model",
    "model_capability",
]


def _is_anthropic_model(model: str) -> bool:
    """Return True if the model name indicates an Anthropic/Claude model."""
    return bool(model) and "claude" in model.lower()


# Model capability tiers — derived from golden-task benchmarks (see
# scripts/run_golden_tasks.py + src/test/golden_tasks.json). Used to surface
# guidance to the UI; NOT a hard gate (the execution layer enforces Ask-Mode
# and disconnected boundaries regardless of model). Match is substring-based
# and case-insensitive on the model id.
_MODEL_TIERS: dict[str, dict] = {
    "gpt-5": {
        "tier": "strong",
        "note": "Best tool-selection accuracy; handles full guidance + multi-step combos well.",
    },
    "claude": {
        "tier": "strong",
        "note": "Strong on reasoning/self-correction; native tool_use + extended thinking supported.",
    },
    "deepseek": {
        "tier": "moderate",
        "note": "Reliable single-step + self-correction, but weaker on long multi-step pipelines; output format can drift under very large tool manifests.",
    },
    "glm": {
        "tier": "moderate",
        "note": "Accurate tool picks but weakest at honoring Ask-Mode / disconnected boundaries — relies on the execution-layer guards.",
    },
    "qwen": {
        "tier": "moderate",
        "note": "General-purpose; verify behavior on version-sensitive WAAPI params.",
    },
}


def model_capability(model: str) -> dict:
    """Return ``{tier, note}`` capability metadata for a model id.

    Falls back to an ``unknown`` tier for unrecognised models. Intended for
    UI hints (e.g. a tooltip on the model selector), not for routing logic —
    boundary safety is enforced in the execution layer, not here.
    """
    name = (model or "").lower()
    for key, meta in _MODEL_TIERS.items():
        if key in name:
            return dict(meta)
    return {"tier": "unknown", "note": "No benchmark data for this model yet."}



class LLMService:
    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key: str | None = api_key
        self.base_url: str | None = base_url
        self.model: str = model or "gemini-3-pro-preview"

        if not self.api_key:
            self.api_key = os.getenv("AUDIOMATE_API_KEY")

        # Order matters: AnthropicProvider.supports is selective; the
        # OpenAI-compatible provider is the catch-all and must come last.
        self._providers: list[Provider] = [AnthropicProvider(), OpenAICompatProvider()]
        self.setup_client()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def setup_client(self) -> None:
        for provider in self._providers:
            provider.configure(api_key=self.api_key, base_url=self.base_url)

    def set_config(self, api_key, base_url, model) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").strip()
        self.model = model
        self.setup_client()

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _select_provider(self) -> Provider | None:
        for provider in self._providers:
            if provider.supports(self.model):
                return provider
        return None

    def get_response(self, messages, stream: bool = True, max_tokens: int = 88888) -> Iterator[str]:
        """Legacy text-only stream."""
        provider = self._select_provider()
        if provider is None:
            yield "Error: No provider available for this model."
            return
        yield from provider.generate(messages, self.model, stream=stream, max_tokens=max_tokens)

    def stream_events(
        self,
        messages,
        *,
        stream: bool = True,
        max_tokens: int = 88888,
        system: list[dict] | str | None = None,
        tools: list[dict] | None = None,
        thinking: dict | None = None,
        extra: dict | None = None,
    ) -> Iterator[ProviderEvent]:
        """Structured event stream — preferred for new callers.

        ``system`` may be a string or a list of ``{type:"text", text:..., cache_control:?}``
        blocks. Anthropic uses the structured form for prompt caching;
        OpenAI-compat flattens it back to a single system message.
        """
        provider = self._select_provider()
        if provider is None:
            from src.llm.provider_events import ProviderError
            yield ProviderError("Error: No provider available for this model.")
            return
        yield from provider.generate_events(
            messages,
            self.model,
            stream=stream,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            thinking=thinking,
            extra=extra,
        )

    # ------------------------------------------------------------------
    # Legacy attribute bridge — some call sites read ``llm_service.client``
    # / ``llm_service.anthropic_client`` directly. Surface them from the
    # matching provider so we don't break those readers.
    # ------------------------------------------------------------------

    def __getattr__(self, name: str):
        if name == "client":
            for provider in self.__dict__.get("_providers", []):
                if isinstance(provider, OpenAICompatProvider):
                    return provider.client
        if name == "anthropic_client":
            for provider in self.__dict__.get("_providers", []):
                if isinstance(provider, AnthropicProvider):
                    return provider.client
        raise AttributeError(name)

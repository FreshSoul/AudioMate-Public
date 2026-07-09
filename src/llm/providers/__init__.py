"""LLM provider implementations.

Each provider wraps a single backend (OpenAI-compatible, Anthropic, …) and
exposes the minimal interface defined in :mod:`src.llm.providers.base`.
``LLMService`` routes generation requests to the first provider whose
``supports(model)`` returns True.
"""

from src.llm.providers.base import Provider
from src.llm.providers.anthropic import AnthropicProvider
from src.llm.providers.openai_compat import OpenAICompatProvider

__all__ = ["Provider", "AnthropicProvider", "OpenAICompatProvider"]

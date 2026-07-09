"""Prompt blocks — layered system-prompt assembly with cache_control hints.

A ``PromptBlock`` is a chunk of system-prompt text tagged by its *scope*
(how often it changes). ``assemble_for_anthropic`` and ``assemble_as_string``
turn an ordered list of blocks into the shape each provider expects:

- Anthropic: a list of ``{type:"text", text:..., cache_control:{type:"ephemeral"}?}``
  blocks. Cache breakpoints land at scope transitions (at most 4 — the
  Anthropic limit).
- OpenAI-compat: a single concatenated string (compat providers do their
  own prefix caching at the gateway level).

Why scopes matter
-----------------
Provider prompt caches only hit when the byte-prefix is *identical*. Mixing
turn-specific data (chat history, current query, ``datetime.now()``) into
the static parts of the prompt invalidates the cache every turn. The scope
discipline keeps L1+L2 byte-stable across turns within a session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

Scope = Literal["static", "session", "turn"]
"""Block scope:

- ``static``: only changes on app start / model swap (roleplay rules,
  tool schemas, WAAPI rules.md). Cached most aggressively.
- ``session``: changes when the user touches settings (active pet,
  skill/plugin selection, KB selection, memory snapshot).
- ``turn``: rebuilt every turn (intent classification, scope hint,
  on-demand WAAPI doc snippets).
"""


@dataclass(frozen=True)
class PromptBlock:
    """One labelled chunk of system-prompt text.

    ``id`` is a stable identifier used for logging / diffing across turns
    (e.g. ``"roleplay_rules"``, ``"skill_guidance"``). ``content`` is the
    raw text to inject. ``scope`` determines cache layering.
    """

    id: str
    content: str
    scope: Scope = "turn"

    def is_empty(self) -> bool:
        return not self.content or not self.content.strip()


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

_SCOPE_ORDER: dict[Scope, int] = {"static": 0, "session": 1, "turn": 2}


def _ordered(blocks: Iterable[PromptBlock]) -> list[PromptBlock]:
    """Return blocks sorted by scope (static → session → turn), input order preserved within each scope.

    Stable sort means blocks of the same scope keep the order the caller
    chose, which is important — the cache key is byte-stable only when
    that intra-scope order is also stable.
    """
    return sorted(
        (b for b in blocks if not b.is_empty()),
        key=lambda b: _SCOPE_ORDER.get(b.scope, 99),
    )


def assemble_for_anthropic(blocks: Iterable[PromptBlock]) -> list[dict]:
    """Build Anthropic's ``system`` parameter: list of text blocks with
    cache_control hints at scope transitions.

    Anthropic allows at most 4 cache breakpoints per request. We use 2:
    one at the end of the static layer and one at the end of the session
    layer, so the static + session prefix is reused even when turn-level
    content changes.
    """
    ordered = _ordered(blocks)
    if not ordered:
        return []

    grouped: dict[Scope, list[str]] = {"static": [], "session": [], "turn": []}
    for b in ordered:
        grouped[b.scope].append(b.content.rstrip())

    out: list[dict] = []
    for scope in ("static", "session", "turn"):
        texts = grouped[scope]
        if not texts:
            continue
        block: dict = {"type": "text", "text": "\n\n".join(texts)}
        # Cache static + session; turn is intentionally not cached.
        if scope in ("static", "session"):
            block["cache_control"] = {"type": "ephemeral"}
        out.append(block)
    return out


def assemble_as_string(blocks: Iterable[PromptBlock]) -> str:
    """Build a single concatenated string (OpenAI-compat path).

    Order matches ``assemble_for_anthropic`` so the visible prompt content
    is identical across providers — only the cache hinting differs.
    """
    ordered = _ordered(blocks)
    return "\n\n".join(b.content.rstrip() for b in ordered)


def summarize_blocks(blocks: Iterable[PromptBlock]) -> list[dict]:
    """Return a compact ``[{id, scope, chars}]`` list — for logging /
    diagnostics, not for the provider."""
    return [
        {"id": b.id, "scope": b.scope, "chars": len(b.content)}
        for b in _ordered(blocks)
    ]


__all__ = [
    "PromptBlock",
    "Scope",
    "assemble_for_anthropic",
    "assemble_as_string",
    "summarize_blocks",
]

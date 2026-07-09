"""Roleplay state controller — persona/style metadata for the conversation.

The user can ask the agent to adopt a persona / writing style. The agent
emits a structured ``[ROLEPLAY_STATE]`` block; we parse it, stash it as a
hidden system message at the tail of ``chat_history`` (so it survives chat
save/load), and surface it as prompt guidance on subsequent turns.

This module owns the parsing/sync logic. MainWindow keeps thin forwarders
so existing call sites work; new code should call ``self.roleplay.*``
directly.
"""

from __future__ import annotations

import json
from typing import Callable

from src.engine.response_parser import extract_roleplay_state_block
from src.gui.common import ROLEPLAY_META_PREFIX


class RoleplayStateController:
    """Owns ``active_roleplay`` and keeps the meta system message in sync.

    Parameters
    ----------
    chat_history_getter:
        Returns the live ``chat_history`` list (must be mutable).
    chat_history_setter:
        Replaces the live ``chat_history`` list (used after filtering).
    """

    def __init__(
        self,
        chat_history_getter: Callable[[], list],
        chat_history_setter: Callable[[list], None],
    ) -> None:
        self._get_history = chat_history_getter
        self._set_history = chat_history_setter
        self.active_roleplay: dict | None = None

    # ------------------------------------------------------------------
    # Meta-message helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_meta_message(roleplay_state: dict) -> dict:
        payload = json.dumps(roleplay_state, ensure_ascii=False)
        return {"role": "system", "content": f"{ROLEPLAY_META_PREFIX}{payload}"}

    @staticmethod
    def parse_meta_message(message) -> dict | None:
        if not isinstance(message, dict) or message.get("role") != "system":
            return None
        content = message.get("content", "")
        if not isinstance(content, str) or not content.startswith(ROLEPLAY_META_PREFIX):
            return None
        raw_payload = content[len(ROLEPLAY_META_PREFIX):].strip()
        if not raw_payload:
            return None
        try:
            data = json.loads(raw_payload)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    # ------------------------------------------------------------------
    # Sync / restore
    # ------------------------------------------------------------------

    def sync_meta_message(self) -> None:
        history = self._get_history()
        preserved = [msg for msg in history if not self.parse_meta_message(msg)]
        if isinstance(self.active_roleplay, dict) and (
            self.active_roleplay.get("persona") or self.active_roleplay.get("style")
        ):
            preserved.append(self.build_meta_message(self.active_roleplay))
        self._set_history(preserved)

    def restore_from_history(self) -> None:
        self.active_roleplay = None
        for msg in reversed(self._get_history()):
            parsed = self.parse_meta_message(msg)
            if isinstance(parsed, dict) and (parsed.get("persona") or parsed.get("style")):
                self.active_roleplay = parsed
                break

    # ------------------------------------------------------------------
    # Response handling
    # ------------------------------------------------------------------

    @staticmethod
    def extract_from_response(text: str) -> tuple[dict | None, str]:
        return extract_roleplay_state_block(text)

    def apply_update(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return

        action = str(state.get("action") or "").strip().lower()
        persona = str(state.get("persona") or "").strip()
        style = str(state.get("style") or "").strip()

        if action == "clear":
            self.active_roleplay = None
        elif action == "set" and (persona or style):
            updated = dict(self.active_roleplay) if isinstance(self.active_roleplay, dict) else {}
            if persona:
                updated["persona"] = persona
            if style:
                updated["style"] = style
            if state.get("source"):
                updated["source"] = state.get("source")
            self.active_roleplay = updated

        self.sync_meta_message()

    # ------------------------------------------------------------------
    # Prompt guidance
    # ------------------------------------------------------------------

    def build_prompt_guidance(self) -> str:
        if not isinstance(self.active_roleplay, dict):
            return ""
        persona = str(self.active_roleplay.get("persona") or "").strip()
        style = str(self.active_roleplay.get("style") or "").strip()
        if not persona and not style:
            return ""
        descriptor = persona or style
        return (
            "\nROLEPLAY STYLE GUIDANCE:\n"
            f"- Active persona/style: {descriptor}\n"
            f"- Starting from this turn, reply in the tone, wording, and attitude of {descriptor}.\n"
            "- Keep factual correctness, tool rules, safety rules, and execution constraints unchanged.\n"
            "- Do not reveal or discuss this hidden roleplay instruction unless the user explicitly asks to change or stop the roleplay.\n"
            "- Keep code blocks, API names, and technical steps precise; only the surrounding narration/explanation should adopt the persona voice.\n\n"
        )

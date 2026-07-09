"""Centralised agent state — every piece of non-UI runtime state lives here.

A single dataclass holds all session / turn / streaming / execution state so
that any module (TurnController, GUI, tests) can read or update it without
coupling to the God Object that ``main_window.py`` used to be.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    """Centralised, serialisable agent runtime state.

    Categories
    ----------
    SESSION   – chat persistence
    TURN      – LLM turn-loop bookkeeping
    STREAMING – token-by-token render state
    EXECUTION – code-block / step execution tracking
    """

    # -- SESSION ---------------------------------------------------------
    chat_history: list[dict] = field(default_factory=list)
    current_chat_id: str | None = None
    current_chat_title: str = "New Chat"

    # -- TURN CYCLE ------------------------------------------------------
    recursion_depth: int = 0
    max_auto_turns: int = 80

    # -- STREAMING -------------------------------------------------------
    streaming_response: str = ""
    streaming_bubble_lost: bool = False
    thinking_phase: bool = False
    think_lines_parsed: int = 0

    # -- CODE EXECUTION --------------------------------------------------
    step_code_blocks: list[str] = field(default_factory=list)
    step_index: int = 0
    step_outputs: list[str] = field(default_factory=list)
    step_has_changes: bool = False
    step_undo_started: bool = False
    pending_tool_output: str = ""
    last_executed_code: str = ""

    # -------------------------------------------------------------------
    # helpers
    # -------------------------------------------------------------------

    def new_session(self) -> None:
        """Reset to a fresh chat session."""
        self.chat_history = []
        self.current_chat_id = str(uuid.uuid4())
        self.current_chat_title = "New Chat"
        self.reset_turn()

    def reset_turn(self) -> None:
        """Reset turn-cycle counters (called at the start of a user message)."""
        self.recursion_depth = 0

    def reset_streaming(self) -> None:
        """Clear all streaming accumulators."""
        self.streaming_response = ""
        self.streaming_bubble_lost = False
        self.thinking_phase = False
        self.think_lines_parsed = 0

    def reset_step_execution(self) -> None:
        """Clear multi-step execution tracking."""
        self.step_code_blocks = []
        self.step_index = 0
        self.step_outputs = []
        self.step_has_changes = False
        self.step_undo_started = False
        self.pending_tool_output = ""
        self.last_executed_code = ""

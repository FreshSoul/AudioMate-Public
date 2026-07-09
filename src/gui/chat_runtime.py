"""Chat runtime manager — owns per-chat background task state.

Each chat owns a :class:`ChatTaskState` carrying its worker thread, code
executor, streaming state, pending confirmations, and visible Qt widget
references. The manager keeps the live ``dict[chat_id -> ChatTaskState]``
and exposes the same five helpers MainWindow used to define inline.

The class is intentionally not a QObject — it holds Qt object references
but doesn't define any signals; MainWindow continues to own slot wiring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from src.utils.execution import CodeExecutor


@dataclass
class ChatTaskState:
    """Runtime state for a background task owned by one chat."""

    chat_id: str
    worker: object | None = None
    turn_id: str = ""
    running: bool = False
    mode: str = "Agent Mode"
    model: str = ""
    # Sub-pet attribution for the current task ("" for manual submits). Set
    # on every _submit_user_prompt; lets process_turn resolve a per-pet LLM
    # override across all auto-turn iterations of the task.
    pet_id: str = ""
    full_streaming_response: str = ""
    thinking_phase: bool = False
    think_lines_parsed: int = 0
    pending_finished: bool = False
    pending_internal_messages: list[dict] = field(default_factory=list)
    code_executor: CodeExecutor = field(default_factory=CodeExecutor)
    execution_thread: object | None = None
    pending_execution_output: str | None = None
    pending_execution_callback: object | None = None
    pending_file_write_context: tuple | None = None
    pending_file_write_widget: object | None = None
    current_streaming_bubble: object | None = None
    thinking_widget: object | None = None
    streaming_bubble_lost: bool = False
    status: str = "idle"
    status_detail: str = ""


class ChatRuntimeManager:
    """Holds the per-chat task state map.

    Parameters
    ----------
    current_chat_id_getter:
        Returns ``MainWindow.current_chat_id``.
    """

    def __init__(self, current_chat_id_getter: Callable[[], str | None]) -> None:
        self._get_current_chat_id = current_chat_id_getter
        self.states: dict[str, ChatTaskState] = {}

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def task_state_for(self, chat_id: str | None = None, *, create: bool = True) -> ChatTaskState | None:
        resolved = chat_id or self._get_current_chat_id()
        if not resolved:
            return None
        state = self.states.get(resolved)
        if state is None and create:
            state = ChatTaskState(chat_id=resolved)
            self.states[resolved] = state
        return state

    def current_task_state(self) -> ChatTaskState | None:
        return self.task_state_for(self._get_current_chat_id(), create=True)

    def is_chat_visible(self, chat_id: str | None) -> bool:
        return bool(chat_id and chat_id == self._get_current_chat_id())

    def chat_has_running_task(self, chat_id: str | None = None) -> bool:
        state = self.task_state_for(chat_id, create=False)
        worker = state.worker if state else None
        execution_thread = state.execution_thread if state else None
        return bool(
            state
            and (
                (state.running and worker and worker.isRunning())
                or (execution_thread and execution_thread.isRunning())
            )
        )

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def pop(self, chat_id: str) -> ChatTaskState | None:
        return self.states.pop(chat_id, None)

    def stop_task_for_chat(self, chat_id: str | None, *, wait_ms: int = 0) -> ChatTaskState | None:
        """Stop the worker/execution thread for ``chat_id`` and mark it cancelled.

        Returns the state so the caller can decide whether to refresh GUI
        widgets that mirror the runtime (only when ``chat_id`` is visible).
        """
        state = self.task_state_for(chat_id, create=False)
        if not state:
            return None
        worker = state.worker
        if worker and worker.isRunning():
            worker.stop()
            if wait_ms:
                worker.wait(wait_ms)
        execution_thread = state.execution_thread
        if execution_thread and execution_thread.isRunning():
            execution_thread.stop()
            if wait_ms:
                execution_thread.wait(wait_ms)
        state.running = False
        state.status = "cancelled"
        state.status_detail = "已停止"
        return state

    def stop_all_tasks(self, *, wait_ms: int = 500) -> None:
        for chat_id in list(self.states.keys()):
            self.stop_task_for_chat(chat_id, wait_ms=wait_ms)

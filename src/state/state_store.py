"""StateStore — observable wrapper around AgentState with Qt signals.

Store API:
- ``get_state()`` returns the current snapshot
- ``update(updater)`` applies a mutation and emits ``state_changed``
- Qt components connect to ``state_changed`` to react to specific slices

Thread safety: ``update()`` is **not** thread-safe by design — all state
mutations should be dispatched on the Qt main thread (use ``QMetaObject.invokeMethod``
or signal/slot from worker threads).
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from src.state.agent_state import AgentState


class StateStore(QObject):
    """Observable store that wraps a single :class:`AgentState` instance."""

    # Emitted after every ``update()`` call.
    #   key  – a short tag indicating *what* changed (e.g. "chat_history",
    #          "streaming", "step_execution").  Listeners can filter on this.
    state_changed = pyqtSignal(str)

    def __init__(self, initial: AgentState | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._state = initial or AgentState()

    # -- read ------------------------------------------------------------

    def get_state(self) -> AgentState:
        """Return the current state snapshot (direct reference, not a copy)."""
        return self._state

    # -- write -----------------------------------------------------------

    def update(self, updater: Callable[[AgentState], None], key: str = "") -> None:
        """Apply *updater* to the state, then emit ``state_changed(key)``.

        *updater* receives the current ``AgentState`` and mutates it in place.
        After *updater* returns, the ``state_changed`` signal fires.

        Example::

            store.update(lambda s: setattr(s, 'recursion_depth', s.recursion_depth + 1),
                         key="turn")
        """
        updater(self._state)
        self.state_changed.emit(key)

    def set_state(self, new_state: AgentState, key: str = "reset") -> None:
        """Replace the entire state object and emit ``state_changed``."""
        self._state = new_state
        self.state_changed.emit(key)

    # -- convenience shortcuts -------------------------------------------

    def new_session(self) -> None:
        """Shorthand for ``state.new_session()`` + signal."""
        self._state.new_session()
        self.state_changed.emit("session")

    def reset_turn(self) -> None:
        self._state.reset_turn()
        self.state_changed.emit("turn")

    def reset_streaming(self) -> None:
        self._state.reset_streaming()
        self.state_changed.emit("streaming")

    def reset_step_execution(self) -> None:
        self._state.reset_step_execution()
        self.state_changed.emit("step_execution")

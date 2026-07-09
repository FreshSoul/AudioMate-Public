"""Pet service — Qt-aware orchestration for the Buddy(宠物) feature.

Wraps the pure data helpers from ``src.pet.store`` and exposes the
runtime hooks the GUI uses:

- announce text to the floating main-pet window
- record task completions / step progress into the right pet's stats
- bind sub-pet schedules to ``SchedulerService`` and route fired tasks back
  through ``MainWindow._submit_user_prompt``
"""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from src.pet.store import (
    PET_KIND_MAIN,
    PET_KIND_SUB,
    build_pet_payload,
    change_pet_kind,
    find_pet,
    get_active_main,
    get_floating_pet,
    list_main_pets,
    list_sub_pets,
    normalize_pet_settings,
    record_pet_activity,
    set_active_main,
    set_desk_layout,
    set_floating_pet,
    set_floating_state,
)


class PetService(QObject):
    """Single source of truth for the live ``pets`` settings block.

    Signals
    -------
    main_pet_announcement(str text, str severity)
        Emitted whenever something interesting happens that the main-pet
        floating window should surface to the user.  ``severity`` is one of
        ``info / success / warn / error``.
    pet_stats_changed(str pet_id)
        Emitted after an activity entry is appended for a given pet.
    pets_changed(dict normalized_state)
        Emitted whenever the pet list / floating flags change.
    sub_pet_triggered(str pet_id, str prompt, str title)
        Emitted when a sub-pet's schedule fires.  ``MainWindow`` listens and
        forwards to ``_submit_user_prompt``.
    """

    main_pet_announcement = pyqtSignal(str, str)
    pet_stats_changed = pyqtSignal(str)
    pets_changed = pyqtSignal(dict)
    sub_pet_triggered = pyqtSignal(str, str, str)
    # Implicit-parallel dispatch lifecycle. Both signals are emitted from
    # background threads; Qt's queued-connection delivery dispatches them
    # back to the GUI thread for any connected slots.
    sub_agent_started = pyqtSignal(str, str, str)   # (run_id, pet_id, pet_name)
    sub_agent_finished = pyqtSignal(str, bool, str)  # (run_id, success, snippet)
    # Sub-agent sandbox wants to import something not in the default
    # allow-list. The third element is a ``concurrent.futures.Future`` that
    # the GUI slot completes (``set_result(True/False)``); the worker thread
    # awaits it via ``Future.result(timeout=…)``.
    import_permission_requested = pyqtSignal(str, str, object)
    _task_completion_record_requested = pyqtSignal(dict)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._state: dict = normalize_pet_settings({})
        # Maps SchedulerService task_id -> pet_id, refreshed on every state set.
        self._task_to_pet: dict[str, str] = {}
        # Optional persistence callback supplied by MainWindow:
        # ``_persist(state_dict) -> None``.  Lets the service save without
        # knowing about ``app_settings``.
        self._persist: Callable[[dict], None] | None = None
        self._task_completion_record_requested.connect(
            self._record_task_completion_from_payload
        )

    # ------------------------------------------------------------------
    # State plumbing
    # ------------------------------------------------------------------

    def set_persist_callback(self, callback: Callable[[dict], None] | None) -> None:
        self._persist = callback

    def set_state(self, state: Any) -> None:
        """Replace the live pets state with a normalised copy of ``state``."""
        self._state = normalize_pet_settings({"pets": state})
        self._rebuild_task_index()
        self.pets_changed.emit(self.state())

    def state(self) -> dict:
        """Return a fresh normalised copy of the current state."""
        return build_pet_payload(self._state)

    def _commit(self, new_state: dict) -> None:
        self._state = normalize_pet_settings({"pets": new_state})
        self._rebuild_task_index()
        if self._persist is not None:
            try:
                self._persist(self.state())
            except Exception as exc:  # pragma: no cover — defensive only
                print(f"[PetService] persist callback raised: {exc}")
        self.pets_changed.emit(self.state())

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def active_main(self) -> dict | None:
        return get_active_main(self._state)

    def floating_pet(self) -> dict | None:
        return get_floating_pet(self._state)

    def main_pets(self) -> list[dict]:
        return list_main_pets(self._state)

    def sub_pets(self) -> list[dict]:
        return list_sub_pets(self._state)

    def find(self, pet_id: str) -> dict | None:
        return find_pet(self._state, pet_id)

    def floating_enabled(self) -> bool:
        return bool(self._state.get("floating_enabled"))

    def floating_position(self) -> dict:
        return dict(self._state.get("floating_position") or {"x": -1, "y": -1})

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def set_floating_enabled(self, enabled: bool) -> None:
        new_state = set_floating_state(self._state, enabled=bool(enabled))
        self._commit(new_state)

    def set_floating_position(self, x: int, y: int) -> None:
        new_state = set_floating_state(self._state, position={"x": int(x), "y": int(y)})
        self._commit(new_state)

    def set_floating_pet(self, pet_id: str) -> None:
        new_state = set_floating_pet(self._state, pet_id)
        self._commit(new_state)

    def set_active_main(self, pet_id: str) -> None:
        new_state = set_active_main(self._state, pet_id)
        self._commit(new_state)

    def change_pet_kind(self, pet_id: str, kind: str) -> None:
        new_state = change_pet_kind(self._state, pet_id, kind)
        self._commit(new_state)

    def set_desk_layout(self, layout: list) -> None:
        new_state = set_desk_layout(self._state, layout)
        self._commit(new_state)

    def dispatch_sub_pet(self, pet_id: str, prompt_override: str = "") -> bool:
        """Fire a sub-pet immediately (manual or main-agent dispatch).

        If ``prompt_override`` is non-empty it is used as the prompt; otherwise
        the pet's saved ``task_template`` is used.  Returns True if a
        dispatch was actually emitted (i.e. a prompt was available).
        """
        pet = self.find(pet_id or "")
        if pet is None or pet.get("kind") != PET_KIND_SUB:
            return False
        prompt = (prompt_override or pet.get("task_template") or "").strip()
        if not prompt:
            return False
        title = (pet.get("name") or "副宠任务").strip()
        self.sub_pet_triggered.emit(pet_id, prompt, title)
        return True

    def find_sub_pet_by_name(self, name: str) -> dict | None:
        """Case-insensitive name lookup among sub-pets."""
        needle = (name or "").strip().lower()
        if not needle:
            return None
        for pet in self.sub_pets():
            if (pet.get("name") or "").strip().lower() == needle:
                return pet
            if (pet.get("id") or "").strip().lower() == needle:
                return pet
        return None

    def register_sub_agent_run(self, pet_id: str, pet_name: str) -> str:
        """Mark a new background sub-agent dispatch as in-flight. Returns a
        unique run_id the caller passes to finish_sub_agent_run later."""
        import uuid as _uuid
        run_id = _uuid.uuid4().hex
        try:
            self.sub_agent_started.emit(run_id, pet_id or "", pet_name or "")
        except Exception:
            pass
        return run_id

    def finish_sub_agent_run(self, run_id: str, success: bool, reply_snippet: str = "") -> None:
        if not run_id:
            return
        try:
            self.sub_agent_finished.emit(run_id, bool(success), reply_snippet or "")
        except Exception:
            pass

    def ask_import_permission(self, pet_name: str, module_name: str,
                                timeout: float = 60.0) -> bool:
        """Block the (worker-thread) caller until the GUI thread decides.

        Emits ``import_permission_requested`` with a ``Future`` the GUI slot
        completes with ``True``/``False``. Returns the user's decision;
        falls back to ``False`` on timeout or any error.

        Thread safety: ``Future`` is safe across threads. ``set_result``
        runs on the GUI thread (Qt's queued connection dispatches the slot
        there); ``result(timeout=…)`` blocks the worker thread until then.
        """
        from concurrent.futures import Future, TimeoutError as _FutureTimeout
        fut: Future = Future()
        try:
            self.import_permission_requested.emit(
                str(pet_name or "副宠"), str(module_name or ""), fut,
            )
        except Exception:
            return False
        try:
            return bool(fut.result(timeout=timeout if timeout > 0 else 60.0))
        except _FutureTimeout:
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Task lifecycle hooks
    # ------------------------------------------------------------------

    def record_task_completion(
        self,
        *,
        source: str = "",
        title: str = "",
        success: bool = True,
        cancelled: bool = False,
        detail: str = "",
        pet_id: str = "",
        tool_count: int = 0,
    ) -> None:
        """Hook into MainWindow's task-finish notification.

        Updates the matching pet's stats, mirrors a one-line summary to the
        floating window, and emits ``pet_stats_changed``.  Falls back to the
        active main pet when ``pet_id`` is unknown.
        """
        payload = {
            "source": source,
            "title": title,
            "success": bool(success),
            "cancelled": bool(cancelled),
            "detail": detail,
            "pet_id": pet_id,
            "tool_count": int(tool_count or 0),
        }
        if QThread.currentThread() != self.thread():
            self._task_completion_record_requested.emit(payload)
            return
        self._record_task_completion_now(**payload)

    def _record_task_completion_from_payload(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        self._record_task_completion_now(
            source=payload.get("source", ""),
            title=payload.get("title", ""),
            success=bool(payload.get("success", True)),
            cancelled=bool(payload.get("cancelled", False)),
            detail=payload.get("detail", ""),
            pet_id=payload.get("pet_id", ""),
            tool_count=int(payload.get("tool_count") or 0),
        )

    def _record_task_completion_now(
        self,
        *,
        source: str = "",
        title: str = "",
        success: bool = True,
        cancelled: bool = False,
        detail: str = "",
        pet_id: str = "",
        tool_count: int = 0,
    ) -> None:
        target_id = (pet_id or "").strip()
        if not target_id or self.find(target_id) is None:
            active = self.active_main()
            target_id = active["id"] if active else ""

        if cancelled:
            outcome = "cancel"
        elif success:
            outcome = "success"
        else:
            outcome = "fail"

        clean_title = (title or "").strip() or "任务"
        clean_detail = (detail or "").strip()

        if target_id:
            new_state = record_pet_activity(
                self._state,
                target_id,
                {
                    "title": clean_title,
                    "outcome": outcome,
                    "detail": clean_detail,
                    "tool_count": int(tool_count or 0),
                },
            )
            self._commit(new_state)
            self.pet_stats_changed.emit(target_id)

        announcement = self._format_completion_text(source, clean_title, outcome, clean_detail)
        severity = {"success": "success", "fail": "error", "cancel": "warn"}.get(outcome, "info")
        if announcement:
            self.main_pet_announcement.emit(announcement, severity)

    def record_step_progress(
        self,
        step_num: int,
        total: int,
        description: str,
        outcome: str = "",
    ) -> None:
        """Surface step progress to the floating window (non-persistent)."""
        text = (description or "").strip()
        if not text:
            return
        if total:
            prefix = f"步骤 {step_num}/{total}"
        else:
            prefix = f"步骤 {step_num}"
        message = f"{prefix} · {text}"
        severity = "warn" if str(outcome).lower() == "fail" else "info"
        self.main_pet_announcement.emit(message, severity)

    def announce(self, text: str, severity: str = "info") -> None:
        """Push an arbitrary message to the floating window."""
        text = (text or "").strip()
        if not text:
            return
        valid = {"info", "success", "warn", "error"}
        sev = str(severity or "info").lower()
        if sev not in valid:
            sev = "info"
        self.main_pet_announcement.emit(text, sev)

    # ------------------------------------------------------------------
    # Sub-pet ↔ scheduler binding
    # ------------------------------------------------------------------

    def pet_id_for_task(self, task_id: str) -> str:
        if not task_id:
            return ""
        return self._task_to_pet.get(task_id, "")

    def trigger_sub_pet_task(self, task: dict) -> None:
        """Called by MainWindow when a scheduler task tagged to a pet fires."""
        if not isinstance(task, dict):
            return
        task_id = task.get("id") or ""
        pet_id = self.pet_id_for_task(task_id)
        if not pet_id:
            return
        pet = self.find(pet_id)
        if pet is None:
            return
        prompt = (task.get("prompt") or pet.get("task_template") or "").strip()
        if not prompt:
            return
        title = (task.get("title") or pet.get("name") or "副宠任务").strip()
        self.announce(f"副宠[{pet.get('name', '副宠')}] 开始执行：{title}", "info")
        self.sub_pet_triggered.emit(pet_id, prompt, title)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _rebuild_task_index(self) -> None:
        self._task_to_pet.clear()
        for item in self._state.get("items", []):
            if item.get("kind") != PET_KIND_SUB:
                continue
            schedule = item.get("schedule") or {}
            task_id = (schedule.get("task_id") or "").strip()
            if task_id:
                self._task_to_pet[task_id] = item["id"]

    @staticmethod
    def _format_completion_text(source: str, title: str, outcome: str, detail: str) -> str:
        prefix_map = {
            "scheduled": "⏰ 定时任务",
            "pet": "🐾 宠物任务",
            "user": "💬 用户任务",
        }
        prefix = prefix_map.get((source or "").lower(), "任务")
        outcome_text = {
            "success": "完成",
            "fail": "失败",
            "cancel": "已取消",
        }.get(outcome, "结束")
        text = f"{prefix} · {title} {outcome_text}"
        if detail:
            text = f"{text}：{detail}"
        return text


__all__ = ["PetService", "PET_KIND_MAIN", "PET_KIND_SUB"]

from __future__ import annotations

from datetime import datetime
from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from src.utils.schedule_store import (
    build_task,
    load_scheduled_tasks,
    mark_task_ran,
    parse_datetime,
    refresh_task_schedule,
    save_scheduled_tasks,
    utc_now,
)


class SchedulerService(QObject):
    task_due = pyqtSignal(dict)
    tasks_changed = pyqtSignal(list)

    def __init__(self, parent=None, poll_interval_ms: int = 15000):
        super().__init__(parent)
        self._tasks: list[dict[str, Any]] = []
        self._timer = QTimer(self)
        self._timer.setInterval(max(1000, int(poll_interval_ms)))
        self._timer.timeout.connect(self.check_due_tasks)

    def start(self):
        self.reload()
        self._timer.start()
        self.check_due_tasks()

    def stop(self):
        self._timer.stop()

    def reload(self):
        self._tasks = load_scheduled_tasks(now=utc_now())
        self._save_and_emit()

    def tasks(self) -> list[dict[str, Any]]:
        return [dict(task) for task in self._tasks]

    def add_task(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        task = build_task(payload)
        if not task:
            return None
        self._tasks.append(task)
        self._sort_tasks()
        self._save_and_emit()
        return dict(task)

    def update_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        for index, task in enumerate(self._tasks):
            if task.get("id") != task_id:
                continue
            merged = dict(task)
            merged.update(payload)
            merged["id"] = task_id
            merged.setdefault("created_at", task.get("created_at"))
            updated = build_task(merged)
            if not updated:
                return None
            self._tasks[index] = updated
            self._sort_tasks()
            self._save_and_emit()
            return dict(updated)
        return None

    def delete_task(self, task_id: str) -> bool:
        old_count = len(self._tasks)
        self._tasks = [task for task in self._tasks if task.get("id") != task_id]
        changed = len(self._tasks) != old_count
        if changed:
            self._save_and_emit()
        return changed

    def set_task_enabled(self, task_id: str, enabled: bool) -> bool:
        for index, task in enumerate(self._tasks):
            if task.get("id") != task_id:
                continue
            updated = dict(task)
            updated["enabled"] = bool(enabled)
            updated = refresh_task_schedule(updated)
            self._tasks[index] = updated
            self._sort_tasks()
            self._save_and_emit()
            return True
        return False

    def mark_task_dispatched(self, task_id: str, when: datetime | None = None) -> dict[str, Any] | None:
        for index, task in enumerate(self._tasks):
            if task.get("id") != task_id:
                continue
            updated = mark_task_ran(task, now=when)
            self._tasks[index] = updated
            self._sort_tasks()
            self._save_and_emit()
            return dict(updated)
        return None

    def check_due_tasks(self):
        now = utc_now()
        due_tasks: list[dict[str, Any]] = []
        changed = False

        for index, task in enumerate(list(self._tasks)):
            if not task.get("enabled"):
                continue
            next_run = parse_datetime(task.get("next_run_at"))
            if next_run is None:
                refreshed = refresh_task_schedule(task, now=now)
                self._tasks[index] = refreshed
                changed = True
                next_run = parse_datetime(refreshed.get("next_run_at"))
            if next_run and next_run <= now:
                due_tasks.append(dict(self._tasks[index]))

        if changed:
            self._sort_tasks()
            self._save_and_emit()

        for task in due_tasks:
            self.task_due.emit(task)

    def _sort_tasks(self):
        self._tasks.sort(key=lambda task: task.get("next_run_at") or "9999")

    def _save_and_emit(self):
        save_scheduled_tasks(self._tasks)
        self.tasks_changed.emit(self.tasks())

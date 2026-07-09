"""Scheduled-task queue handling for ``MainWindow``.

Extracted verbatim from ``MainWindow``: scheduler CRUD pass-throughs from
the SchedulerDialog, the run-now / task-due enqueue paths (with dedupe),
the agent-busy gate, and the queue pump that turns a due task into a
``_submit_user_prompt`` call (with sub-pet attribution).

Same conventions as the other controllers: stateless, back-reference via
``w = self.window`` (queue state ``_scheduled_task_queue`` /
``_scheduled_task_ids_in_queue`` / ``_scheduled_queue_timer`` stays on the
window), attached lazily via ``_scheduler_controller_for``.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox


class SchedulerController:
    """Owns scheduled-task queueing for a single ``MainWindow``."""

    def __init__(self, window):
        self.window = window

    def _on_scheduled_tasks_changed(self, tasks):
        w = self.window
        if hasattr(w, "schedule_page"):
            w.schedule_page.set_tasks(tasks)

    def _add_scheduled_task(self, payload):
        w = self.window
        task = w.scheduler_service.add_task(payload)
        if not task:
            QMessageBox.warning(w, "保存失败", "定时任务规则无效，请检查时间设置。")

    def _update_scheduled_task(self, task_id, payload):
        w = self.window
        task = w.scheduler_service.update_task(task_id, payload)
        if not task:
            QMessageBox.warning(w, "保存失败", "定时任务规则无效，请检查时间设置。")

    def _delete_scheduled_task(self, task_id):
        w = self.window
        w.scheduler_service.delete_task(task_id)
        w._scheduled_task_queue = [task for task in w._scheduled_task_queue if task.get("id") != task_id]
        w._scheduled_task_ids_in_queue.discard(task_id)

    def _set_scheduled_task_enabled(self, task_id, enabled):
        w = self.window
        w.scheduler_service.set_task_enabled(task_id, enabled)

    def _run_scheduled_task_now(self, task):
        w = self.window
        if not isinstance(task, dict):
            return
        task_id = task.get("id")
        # Dedupe against the auto-fire path: if the scheduler also dispatched
        # the same task right around the time the user clicked "立即执行",
        # _on_scheduled_task_due may have just enqueued it.
        if task_id and task_id in w._scheduled_task_ids_in_queue:
            return
        w._scheduled_task_queue.append(dict(task))
        if task_id:
            w._scheduled_task_ids_in_queue.add(task_id)
        if not w._scheduled_queue_timer.isActive():
            w._scheduled_queue_timer.start()
        w._try_start_next_scheduled_task()

    def _on_scheduled_task_due(self, task):
        w = self.window
        task_id = task.get("id")
        if not task_id or task_id in w._scheduled_task_ids_in_queue:
            return
        w.scheduler_service.mark_task_dispatched(task_id)
        w._scheduled_task_queue.append(dict(task))
        w._scheduled_task_ids_in_queue.add(task_id)
        if not w._scheduled_queue_timer.isActive():
            w._scheduled_queue_timer.start()
        w._try_start_next_scheduled_task()

    def _is_agent_busy(self):
        w = self.window
        worker_busy = any(
            bool(state.worker and state.worker.isRunning())
            for state in w._chat_task_states.values()
        )
        execution_busy = any(
            bool(state.execution_thread and state.execution_thread.isRunning())
            for state in w._chat_task_states.values()
        )
        controls_locked = hasattr(w, "send_btn") and not w.send_btn.isEnabled()
        return worker_busy or execution_busy or controls_locked

    def _try_start_next_scheduled_task(self):
        w = self.window
        if not w._scheduled_task_queue:
            w._scheduled_queue_timer.stop()
            return
        if w._is_agent_busy():
            return
        task = w._scheduled_task_queue.pop(0)
        w._scheduled_task_ids_in_queue.discard(task.get("id"))
        title = str(task.get("title") or "定时任务").strip() or "定时任务"
        prompt = str(task.get("prompt") or "").strip()
        if not prompt:
            return
        w.page_animator.animate_to(w.chat_page, direction="right")
        w._sync_floating_panel_visibility(animated=True)
        w._sync_navigation_styles()

        # If this scheduler task is bound to a sub-pet, route through the pet
        # service so stats and announcements get the right attribution.
        pet_id = w.pet_service.pet_id_for_task(task.get("id")) if hasattr(w, "pet_service") else ""
        if pet_id:
            w._submit_user_prompt(
                prompt,
                display_prefix=f"🐾 副宠：{title}",
                task_source="pet",
                task_title=title,
                pet_id=pet_id,
            )
            return

        w._submit_user_prompt(
            prompt,
            display_prefix=f"⏰ 定时任务：{title}",
            task_source="scheduled",
            task_title=title,
        )

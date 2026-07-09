"""Pet / sub-agent integration for ``MainWindow``.

Extracted verbatim from ``MainWindow`` (the contiguous block from
``apply_pet_settings`` through ``_sync_sub_pet_schedules``). It groups the
desktop-pet ("Buddy") and parallel sub-agent concerns:

* pet settings persistence and the floating-pet window visibility,
* the parallel sub-agent status panel (the main-window twin of the floating
  pet's status frame),
* modal approval dialogs for sub-agent imports and PowerShell execution,
* the 修炼室 (training room) and skill-map / office dialogs,
* mirroring main-window interaction widgets into the floating pet panel,
* reconciling sub-pet schedules with the ``SchedulerService``.

Follows the same back-reference convention as the other GUI helpers
(``ThemeManager``, ``MarketOperations`` …): every method operates on the
owning ``MainWindow`` via ``w = self.window``. ``MainWindow`` keeps thin
delegating wrappers so all existing signal connections and external callers
(e.g. ``powershell_tool`` reaching ``request_powershell_confirmation`` via
``getattr``) keep working unchanged. This is a pure move, not a behavioural
change; the ``_parallel_agent_*`` / ``_mirrored_interactions`` state stays on
the window exactly where ``__init__`` initialises it.
"""

from __future__ import annotations

import uuid

from PyQt6.QtCore import Qt

from src.pet.store import PET_KIND_SUB, build_pet_payload, normalize_pet_settings
from src.pet.training_room import PetTrainingRoomDialog
from src.utils.app_logger import get_logger
from src.utils.storage import save_app_settings

logger = get_logger(__name__)


class PetIntegrationController:
    """Owns the pet / sub-agent behaviour for a single ``MainWindow``."""

    def __init__(self, window):
        self.window = window

    def apply_pet_settings(self, payload: dict):
        """Persist pet settings coming from SettingsDialog/PetTrainingRoom."""
        w = self.window
        if not isinstance(payload, dict):
            return
        previous_pet_task_ids = w._pet_scheduler_task_ids(
            w.app_settings.get("pets") or {}
        )
        normalized = build_pet_payload(payload)
        prev_floating = bool(w.app_settings.get("pets", {}).get("floating_enabled"))
        w.app_settings["pets"] = normalized
        save_app_settings(w.app_settings)
        if hasattr(w, "pet_service"):
            w.pet_service.set_state(normalized)
            w._sync_sub_pet_schedules(previous_pet_task_ids=previous_pet_task_ids)
        if hasattr(w, "main_pet_window"):
            new_floating = bool(normalized.get("floating_enabled"))
            if new_floating and not w.main_pet_window.isVisible():
                w.main_pet_window.show()
            elif not new_floating and w.main_pet_window.isVisible():
                w.main_pet_window.hide()
            elif new_floating != prev_floating and new_floating:
                w.main_pet_window.show()
        if hasattr(w, "settings_page"):
            w.settings_page.set_pet_settings(w.app_settings)

    def _persist_pet_settings(self, state: dict):
        """Callback used by PetService for transparent persistence."""
        w = self.window
        if not isinstance(state, dict):
            return
        w.app_settings["pets"] = build_pet_payload(state)
        save_app_settings(w.app_settings)
        if hasattr(w, "settings_page"):
            w.settings_page.set_pet_settings(w.app_settings)

    def _pet_office_chats_provider(self) -> list:
        try:
            from src.utils.storage import list_chats
            return list_chats() or []
        except Exception:
            return []

    def _pet_office_capabilities_provider(self) -> dict:
        w = self.window
        return {
            "skills": list((w.app_settings.get("skills") or {}).get("items", [])),
            "plugins": list((w.app_settings.get("plugins") or {}).get("items", [])),
        }

    def _on_office_chat_clicked(self, chat_id: str) -> None:
        w = self.window
        if not chat_id:
            return
        for i in range(w.history_list.count()):
            item = w.history_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == chat_id:
                w.load_selected_chat(item)
                break

    def _on_skill_map_requested(self) -> None:
        w = self.window
        try:
            from src.pet.skill_map_dialog import SkillMapDialog
        except Exception as exc:
            logger.debug("SkillMapDialog import failed: %s", exc)
            return
        skills = list((w.app_settings.get("skills") or {}).get("items", []))
        plugins = list((w.app_settings.get("plugins") or {}).get("items", []))
        pets = w.app_settings.get("pets") or {}
        dialog = SkillMapDialog(
            pets, skills, plugins,
            theme_mode=getattr(w, "theme_mode", "light"),
            parent=w,
        )
        dialog.exec()

    # ------------------------------------------------------------------
    # Parallel sub-agent status panel — main-window twin of the floating
    # pet's _agent_status_frame. Each in-flight dispatch shows one row;
    # the panel auto-removes itself when no rows remain.
    # ------------------------------------------------------------------

    def _ensure_parallel_agent_panel(self) -> None:
        w = self.window
        if w._parallel_agent_frame is not None:
            return
        from PyQt6.QtWidgets import QFrame, QVBoxLayout
        from PyQt6.QtCore import QTimer
        frame = QFrame()
        frame.setObjectName("parallelAgentFrame")
        # Theme-friendly inline style — falls back gracefully under dark mode.
        frame.setStyleSheet(
            "QFrame#parallelAgentFrame { background: rgba(91,143,232,28);"
            " border: 1px solid rgba(91,143,232,140); border-radius: 10px;"
            " padding: 4px; }"
            "QFrame#parallelAgentFrame QLabel { color: palette(WindowText);"
            " font-size: 12px; background: transparent; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        w._parallel_agent_frame = frame
        w._parallel_agent_layout = layout
        w.chat_layout.addWidget(frame)
        try:
            w.scroll_to_bottom()
        except Exception:
            pass
        if w._parallel_agent_heartbeat is None:
            w._parallel_agent_heartbeat = QTimer(w)
            w._parallel_agent_heartbeat.setInterval(400)
            w._parallel_agent_heartbeat.timeout.connect(w._tick_parallel_agent_heartbeat)
        w._parallel_agent_phase = 0
        w._parallel_agent_heartbeat.start()

    def _on_main_sub_agent_started(self, run_id: str, pet_id: str, pet_name: str) -> None:
        w = self.window
        from PyQt6.QtWidgets import QLabel
        w._ensure_parallel_agent_panel()
        name = pet_name or "副宠"
        label = QLabel(f"🤖 {name} 工作中…", w._parallel_agent_frame)
        w._parallel_agent_layout.addWidget(label)
        w._parallel_agent_rows[run_id] = label
        w._parallel_agent_meta[run_id] = {"name": name}
        if w._parallel_agent_heartbeat is not None and not w._parallel_agent_heartbeat.isActive():
            w._parallel_agent_phase = 0
            w._parallel_agent_heartbeat.start()
        try:
            w.scroll_to_bottom()
        except Exception:
            pass

    def _on_main_sub_agent_finished(self, run_id: str, success: bool, snippet: str) -> None:
        w = self.window
        label = w._parallel_agent_rows.get(run_id)
        meta = w._parallel_agent_meta.pop(run_id, {})
        name = meta.get("name", "副宠")
        # Stop the heartbeat as soon as nothing is in-flight, regardless of
        # whether the row UI is present — otherwise a `finished` for a
        # never-`started` run_id (or a duplicate finished) would leak the
        # timer.
        if not w._parallel_agent_meta and w._parallel_agent_heartbeat is not None:
            w._parallel_agent_heartbeat.stop()
        if label is None:
            return
        mark = "✓" if success else "✗"
        text = f"{mark} {name}"
        if snippet:
            text += f": {snippet}"
        label.setText(text)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(3000, lambda _id=run_id: w._dismiss_parallel_agent_row(_id))

    def _dismiss_parallel_agent_row(self, run_id: str) -> None:
        w = self.window
        label = w._parallel_agent_rows.pop(run_id, None)
        if label is None or w._parallel_agent_layout is None:
            return
        w._parallel_agent_layout.removeWidget(label)
        label.setParent(None)
        label.deleteLater()
        if not w._parallel_agent_rows and w._parallel_agent_frame is not None:
            w.chat_layout.removeWidget(w._parallel_agent_frame)
            w._parallel_agent_frame.setParent(None)
            w._parallel_agent_frame.deleteLater()
            w._parallel_agent_frame = None
            w._parallel_agent_layout = None

    def _tick_parallel_agent_heartbeat(self) -> None:
        w = self.window
        w._parallel_agent_phase = (w._parallel_agent_phase + 1) % 4
        dots = "." * w._parallel_agent_phase
        for run_id, label in w._parallel_agent_rows.items():
            meta = w._parallel_agent_meta.get(run_id)
            if meta is None:
                continue
            label.setText(f"🤖 {meta['name']} 工作中{dots}")

    def _on_sub_agent_import_request(self, pet_name: str, module_name: str, future) -> None:
        """GUI-thread slot for sub-agent's non-whitelisted import request.

        The worker thread emitted a request and is blocked on
        ``future.result(timeout=…)``. Show a modal confirm dialog and
        complete the future with the user's decision.
        """
        w = self.window
        from PyQt6.QtWidgets import QMessageBox
        decision = False
        try:
            answer = QMessageBox.question(
                w,
                "副宠 import 请求",
                f"副宠 「{pet_name}」 想要 import 模块 '{module_name}'。\n"
                "该模块不在默认白名单中。是否允许本次执行？\n"
                "（允许后本轮 dispatch 内不再询问该模块）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            decision = (answer == QMessageBox.StandardButton.Yes)
        except Exception:
            decision = False
        finally:
            try:
                if not future.done():
                    future.set_result(decision)
            except Exception:
                pass

    def request_powershell_confirmation(self, payload: dict, timeout: float = 120.0) -> bool:
        """Block a worker thread until the GUI confirms a PowerShell run."""
        w = self.window
        from concurrent.futures import Future, TimeoutError as _FutureTimeout
        fut: Future = Future()
        try:
            w.powershell_confirmation_requested.emit(dict(payload or {}), fut)
        except Exception:
            return False
        try:
            return bool(fut.result(timeout=timeout if timeout > 0 else 120.0))
        except _FutureTimeout:
            return False
        except Exception:
            return False

    def _on_powershell_confirmation_request(self, payload: dict, future) -> None:
        """GUI-thread slot for AudioMate PowerShell execution approval."""
        w = self.window
        from PyQt6.QtWidgets import QMessageBox
        decision = False
        payload = payload if isinstance(payload, dict) else {}
        command = str(payload.get("command") or "")
        cwd = str(payload.get("cwd") or "")
        executable = str(payload.get("executable") or "")
        timeout_seconds = payload.get("timeout_seconds", "")
        try:
            box = QMessageBox(w)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("确认 PowerShell 执行")
            box.setText("AudioMate 想要运行一条 PowerShell 命令。")
            info_lines = []
            if cwd:
                info_lines.append(f"工作目录：{cwd}")
            if executable:
                info_lines.append(f"可执行文件：{executable}")
            if timeout_seconds:
                info_lines.append(f"超时：{timeout_seconds} 秒")
            info_lines.append("")
            info_lines.append("是否允许本次执行？")
            box.setInformativeText("\n".join(info_lines))
            box.setDetailedText(command)
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            box.setEscapeButton(QMessageBox.StandardButton.No)
            decision = box.exec() == QMessageBox.StandardButton.Yes
        except Exception:
            decision = False
        finally:
            try:
                if not future.done():
                    future.set_result(decision)
            except Exception:
                pass

    def request_agent_import_confirmation(self, module_name: str, timeout: float = 120.0) -> bool:
        """Block the code-execution worker until the GUI approves an import.

        Mirrors :meth:`request_powershell_confirmation`: emit a request to the
        GUI thread carrying a ``Future`` and block on it. Returning True lets
        the sandboxed code import ``module_name``; a timeout/error denies it.
        """
        w = self.window
        from concurrent.futures import Future, TimeoutError as _FutureTimeout
        fut: Future = Future()
        try:
            w.agent_import_confirmation_requested.emit(str(module_name or ""), fut)
        except Exception:
            return False
        try:
            return bool(fut.result(timeout=timeout if timeout > 0 else 120.0))
        except _FutureTimeout:
            return False
        except Exception:
            return False

    def _on_agent_import_confirmation_request(self, module_name: str, future) -> None:
        """GUI-thread slot: confirm a non-whitelisted import for the main agent."""
        w = self.window
        from PyQt6.QtWidgets import QMessageBox
        decision = False
        try:
            answer = QMessageBox.question(
                w,
                "import 权限请求",
                f"AudioMate 想要 import 模块 '{module_name}'。\n"
                "该模块不在默认安全白名单中。是否允许本次会话使用？\n"
                "（允许后本次会话内不再询问该模块；文件写入、os.remove 等\n"
                "破坏性操作仍会单独请求确认。）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            decision = (answer == QMessageBox.StandardButton.Yes)
        except Exception:
            decision = False
        finally:
            try:
                if not future.done():
                    future.set_result(decision)
            except Exception:
                pass

    def _on_dispatch_sub_pet(self, pet_id: str) -> None:
        w = self.window
        if not pet_id:
            return
        try:
            ok = w.pet_service.dispatch_sub_pet(pet_id)
        except Exception:
            ok = False
        if not ok:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                w,
                "派遣副宠",
                "该副宠没有可派遣的任务模板。请先在修炼室填写「任务模板」。",
            )

    def open_pet_training_room(self, pet_id: str):
        """Open the 修炼室 dialog for a single pet, save changes if confirmed."""
        w = self.window
        if not pet_id:
            return
        pet = w.pet_service.find(pet_id)
        if pet is None:
            return
        skills = list((w.app_settings.get("skills") or {}).get("items", []))
        plugins = list((w.app_settings.get("plugins") or {}).get("items", []))
        image_model = ((w.app_settings.get("image_gen") or {}).get("model") or "gpt-image-2").strip()
        try:
            from src.pet.store import bound_capability_owners, list_orphan_capabilities
            bound_elsewhere = bound_capability_owners(w.app_settings.get("pets") or {})
            orphans = list_orphan_capabilities(
                w.app_settings.get("pets") or {}, skills, plugins,
            )
        except Exception:
            bound_elsewhere = {"skills": {}, "plugins": {}}
            orphans = {"skill_ids": [], "plugin_ids": []}
        active_main = w.pet_service.active_main() if hasattr(w, "pet_service") else None
        active_main_id = (active_main or {}).get("id", "")
        dialog = PetTrainingRoomDialog(
            pet,
            skills=skills,
            plugins=plugins,
            llm_service=w.llm_service,
            image_model_default=image_model,
            on_image_model_changed=w._save_image_model,
            available_models=list(getattr(w, "model_configs", {}) or {}),
            main_llm_defaults={
                "base_url": getattr(w.llm_service, "base_url", "") or "",
                "model": w.model_selector.currentText() if hasattr(w, "model_selector") else "",
            },
            bound_elsewhere=bound_elsewhere,
            orphans=orphans,
            active_main_id=active_main_id,
            theme_mode=w.theme_mode,
            parent=w,
        )
        dialog.pet_saved.connect(w._on_pet_training_room_saved)
        dialog.exec()

    def _save_image_model(self, model: str) -> None:
        w = self.window
        model = (model or "").strip()
        if not model:
            return
        current = (w.app_settings.get("image_gen") or {}).get("model", "")
        if model == current:
            return
        w.app_settings["image_gen"] = {"model": model}
        try:
            save_app_settings(w.app_settings)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Mirror main-window interaction widgets into the floating pet panel
    # ------------------------------------------------------------------

    def _mirror_to_pet(self, kind: str, main_widget, *, options=None, file_paths=None) -> str:
        """Mirror an interaction widget (intent / confirm / file_write) into
        the floating pet panel. Returns the shared widget_id used to keep
        the two sides in sync. When the user clicks on either side, the
        other side is auto-dismissed."""
        w = self.window
        widget_id = uuid.uuid4().hex
        if not hasattr(w, "_mirrored_interactions"):
            w._mirrored_interactions = {}
        w._mirrored_interactions[widget_id] = (kind, main_widget)

        pet_window = getattr(w, "main_pet_window", None)
        if pet_window is None:
            return widget_id

        try:
            if kind == "intent":
                pet_window.host_intent_widget(widget_id, list(options or []))
            elif kind == "confirm":
                pet_window.host_confirm_widget(widget_id)
            elif kind == "file_write":
                pet_window.host_file_write_widget(widget_id, list(file_paths or []))
        except Exception as exc:
            logger.debug("Failed to mirror %s widget to pet panel: %s", kind, exc)
            return widget_id

        # When the MAIN-window widget itself resolves first, hide the pet
        # mirror.  Each widget class has slightly different signals.
        try:
            if kind == "intent":
                main_widget.intent_selected.connect(
                    lambda *_a, _id=widget_id: w._dismiss_pet_mirror(_id)
                )
            else:
                main_widget.confirmed.connect(
                    lambda _id=widget_id: w._dismiss_pet_mirror(_id)
                )
                main_widget.revoked.connect(
                    lambda _id=widget_id: w._dismiss_pet_mirror(_id)
                )
        except Exception:
            pass
        return widget_id

    def _dismiss_pet_mirror(self, widget_id: str) -> None:
        w = self.window
        pet_window = getattr(w, "main_pet_window", None)
        if pet_window is not None:
            try:
                pet_window.dismiss_interaction(widget_id)
            except Exception:
                pass
        if hasattr(w, "_mirrored_interactions"):
            w._mirrored_interactions.pop(widget_id, None)

    def _on_pet_intent_mirrored(self, widget_id: str, intent: str, note: str) -> None:
        w = self.window
        entry = getattr(w, "_mirrored_interactions", {}).pop(widget_id, None)
        if not entry:
            return
        kind, main_widget = entry
        if kind != "intent" or main_widget is None:
            return
        # Drive the existing slot by firing the widget's own signal.
        try:
            main_widget.intent_selected.emit(intent, note)
        except Exception:
            pass

    def _on_pet_confirm_mirrored(self, widget_id: str, accepted: bool) -> None:
        w = self.window
        entry = getattr(w, "_mirrored_interactions", {}).pop(widget_id, None)
        if not entry:
            return
        kind, main_widget = entry
        if kind != "confirm" or main_widget is None:
            return
        try:
            (main_widget.confirmed if accepted else main_widget.revoked).emit()
        except Exception:
            pass

    def _on_pet_file_write_mirrored(self, widget_id: str, accepted: bool) -> None:
        w = self.window
        entry = getattr(w, "_mirrored_interactions", {}).pop(widget_id, None)
        if not entry:
            return
        kind, main_widget = entry
        if kind != "file_write" or main_widget is None:
            return
        try:
            (main_widget.confirmed if accepted else main_widget.revoked).emit()
        except Exception:
            pass

    def _on_pet_training_room_saved(self, pet_item: dict):
        w = self.window
        if hasattr(w, "settings_page"):
            w.settings_page.apply_pet_item(pet_item)
        else:
            normalized = build_pet_payload({"pets": w.app_settings.get("pets", {})})
            w.app_settings["pets"] = normalized
            save_app_settings(w.app_settings)

    def _on_sub_pet_triggered(self, pet_id: str, prompt: str, title: str):
        w = self.window
        if not prompt:
            return
        prompt = prompt.strip()
        if not prompt:
            return
        w._submit_user_prompt(
            prompt,
            display_prefix=f"🐾 副宠：{title}" if title else "🐾 副宠",
            task_source="pet",
            task_title=title or "副宠任务",
            pet_id=pet_id,
        )

    def _pet_scheduler_task_ids(self, pet_settings) -> set[str]:
        try:
            normalized = normalize_pet_settings({"pets": pet_settings or {}})
        except Exception:
            return set()
        task_ids: set[str] = set()
        for pet in normalized.get("items", []):
            task_id = str((pet.get("schedule") or {}).get("task_id") or "").strip()
            if task_id:
                task_ids.add(task_id)
        return task_ids

    @staticmethod
    def _is_pet_scheduler_task(task: dict) -> bool:
        if not isinstance(task, dict):
            return False
        return str(task.get("source") or "").strip() == "pet" or bool(
            str(task.get("pet_id") or "").strip()
        )

    def _persist_synced_pet_state(self, state: dict) -> None:
        w = self.window
        normalized = build_pet_payload(state)
        w.app_settings["pets"] = normalized
        save_app_settings(w.app_settings)
        w.pet_service.set_state(normalized)
        if hasattr(w, "settings_page"):
            w.settings_page.set_pet_settings(w.app_settings)

    def _sync_sub_pet_schedules(self, previous_pet_task_ids: set[str] | None = None):
        """Reconcile sub-pet schedules with the SchedulerService."""
        w = self.window
        if not hasattr(w, "scheduler_service") or not hasattr(w, "pet_service"):
            return
        state = w.pet_service.state()
        existing_tasks = {
            str(task.get("id") or ""): task
            for task in w.scheduler_service.tasks()
            if task.get("id")
        }
        wanted_task_ids: set[str] = set()
        stale_task_ids: set[str] = set(previous_pet_task_ids or set())
        stale_task_ids.update(w._pet_scheduler_task_ids(state))
        stale_task_ids.update(
            task_id for task_id, task in existing_tasks.items()
            if w._is_pet_scheduler_task(task)
        )
        updated_schedules: dict[str, dict] = {}

        for pet in [
            item for item in state.get("items", [])
            if item.get("kind") == PET_KIND_SUB
        ]:
            schedule = dict(pet.get("schedule") or {})
            existing_task_id = str(schedule.get("task_id") or "").strip()
            schedule_type = (schedule.get("schedule_type") or "none").lower()
            if not pet.get("enabled") or schedule_type in {"", "none"}:
                if existing_task_id:
                    new_schedule = dict(schedule)
                    new_schedule.pop("task_id", None)
                    updated_schedules[pet["id"]] = new_schedule
                continue
            payload = {
                "title": f"副宠：{pet.get('name', '副宠')}",
                "prompt": pet.get("task_template") or f"执行宠物 {pet.get('name', '副宠')} 的任务",
                "schedule_type": schedule_type,
                "enabled": True,
                "source": "pet",
                "pet_id": pet.get("id", ""),
            }
            if schedule_type == "interval":
                payload["interval_minutes"] = int(schedule.get("interval_minutes") or 30)
            if schedule_type in {"daily", "weekly", "once"}:
                payload["time"] = schedule.get("time") or "09:00"
            if schedule_type == "weekly":
                payload["weekdays"] = list(schedule.get("weekdays") or [])
            if schedule_type == "once":
                payload["run_at"] = schedule.get("run_at") or ""

            if existing_task_id and existing_task_id in existing_tasks:
                updated = w.scheduler_service.update_task(existing_task_id, payload)
                if updated:
                    wanted_task_ids.add(existing_task_id)
                else:
                    new_schedule = dict(schedule)
                    new_schedule.pop("task_id", None)
                    updated_schedules[pet["id"]] = new_schedule
                continue
            created = w.scheduler_service.add_task(payload)
            if created:
                task_id = str(created.get("id") or "").strip()
                if not task_id:
                    continue
                wanted_task_ids.add(task_id)
                new_schedule = dict(schedule)
                new_schedule["task_id"] = task_id
                updated_schedules[pet["id"]] = new_schedule
            elif existing_task_id:
                new_schedule = dict(schedule)
                new_schedule.pop("task_id", None)
                updated_schedules[pet["id"]] = new_schedule

        for task_id in sorted(stale_task_ids - wanted_task_ids):
            if task_id in existing_tasks:
                w.scheduler_service.delete_task(task_id)

        if updated_schedules:
            new_items = []
            for item in state.get("items", []):
                schedule = updated_schedules.get(item.get("id"))
                if schedule is None:
                    new_items.append(item)
                    continue
                updated_pet = dict(item)
                updated_pet["schedule"] = schedule
                new_items.append(updated_pet)
            w._persist_synced_pet_state({**state, "items": new_items})

"""Chat history / session lifecycle for ``MainWindow``.

Extracted verbatim from ``MainWindow``: ``start_new_chat``,
``delete_chat_history``, ``load_selected_chat`` (full bubble/timeline
restore), and ``handle_edit_confirmed`` (edit-and-branch).

Follows the same back-reference convention as the other controllers: every
method operates on the owning ``MainWindow`` via ``w = self.window`` and the
controller is STATELESS. Attached lazily via
``_chat_history_controller_for`` in ``main_window`` because tests invoke
``MainWindow.delete_chat_history`` / ``load_selected_chat`` unbound on
``MainWindow.__new__`` instances.

PATCH-POINT NOTE: tests patch ``src.gui.main_window.load_chat`` and
``src.gui.main_window.delete_chat`` at module level. Those two storage
functions are therefore resolved through the ``main_window`` module at call
time (function-level import 闁?module-level would be circular) instead of
being imported here directly.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QListWidgetItem, QMessageBox

from src.gui.common import extract_text_from_content
from src.gui.widgets import HistoryItemWidget, MessageBubble, StepProgressWidget
from src.utils.app_logger import get_logger
from src.utils.storage import create_new_chat, list_chats, save_chat

logger = get_logger(__name__)


class ChatHistoryController:
    """Owns chat history / session lifecycle for a single ``MainWindow``."""

    def __init__(self, window):
        self.window = window

    def start_new_chat(self):
        w = self.window
        w._show_chat_page(direction="right")
        w._detach_visible_runtime_widgets()
        w._reset_streaming_state()
        w.pending_branch_bubbles = []
        w.current_chat_id = create_new_chat()
        w._task_state_for(w.current_chat_id, create=True)
        w.current_chat_title = "New Chat"
        w.chat_history = []
        if hasattr(w, "external_agent_router"):
            w.external_agent_router.reset()
        try:
            memory_service = w._get_memory_service()
            if memory_service is not None:
                memory_service.ensure_scope("session", w.current_chat_id)
        except Exception as exc:
            logger.warning("Failed to create session memory: %s", exc)
        w.active_roleplay = None
        w._current_task_context = None
        w._task_completion_notified = False
        w.clear_pending_images()
        while w.chat_layout.count():
            item = w.chat_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        w._thinking_widget = None
        w.step_progress_widget = None
        w.refresh_history_list()
        w._activate_runtime_state(w.current_chat_id)
        w._update_current_chat_controls()


    def refresh_history_list(self):
        w = self.window
        w.history_list.clear()
        for chat in list_chats():
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, chat["id"])
            status_text = w._history_status_text(chat["id"])

            widget = HistoryItemWidget(
                chat["id"],
                chat["title"],
                theme_mode=w.theme_mode,
                active=chat["id"] == w.current_chat_id,
                status_text=status_text,
            )
            widget.delete_requested.connect(w.delete_chat_history)

            item.setSizeHint(widget.sizeHint())
            w.history_list.addItem(item)
            w.history_list.setItemWidget(item, widget)

    def _history_status_text(self, chat_id: str) -> str:
        w = self.window
        state = w._task_state_for(chat_id, create=False)
        if not state:
            return ""
        if state.pending_finished:
            return "Waiting for result"
        if state.pending_execution_output is not None:
            return "Waiting for execution"
        if state.pending_file_write_context:
            return "Waiting for file confirmation"
        if state.running and state.worker and state.worker.isRunning():
            return state.status_detail or "Running"
        if state.execution_thread and state.execution_thread.isRunning():
            return "Executing"
        if state.status == "cancelled":
            return "Stopped"
        return ""

    def delete_chat_history(self, chat_id):
        # Resolved via the main_window module so test patches on
        # ``src.gui.main_window.delete_chat`` keep working.
        from src.gui import main_window as _mw
        w = self.window
        state = w._task_state_for(chat_id, create=False)
        if w._chat_has_running_task(chat_id) or (state is not None and state.pending_file_write_context):
            reply = QMessageBox.question(
                w,
                "Delete Chat",
                "This chat still has a running task or pending file confirmation. Deleting it will stop the task and discard pending writes. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            w._stop_task_for_chat(chat_id, wait_ms=1000)
            if state is not None:
                state.code_executor.discard_pending_writes()
        try:
            memory_service = w._get_memory_service()
            if memory_service is not None:
                memory_service.delete_session_memory(chat_id)
        except Exception as exc:
            logger.warning("Failed to delete session memory for chat %s: %s", chat_id, exc)
        w._chat_task_states.pop(chat_id, None)
        _mw.delete_chat(chat_id)
        if w.current_chat_id == chat_id:
            w.start_new_chat()
        else:
            w.refresh_history_list()

    def load_selected_chat(self, item):
        # Resolved via the main_window module so test patches on
        # ``src.gui.main_window.load_chat`` keep working.
        from src.gui import main_window as _mw
        w = self.window
        w._show_chat_page(direction="right")
        w._detach_visible_runtime_widgets()
        w._reset_streaming_state()
        w.pending_branch_bubbles = []
        chat_id = item.data(Qt.ItemDataRole.UserRole)
        data = _mw.load_chat(chat_id)
        if data:
            w.current_chat_id = chat_id
            w._task_state_for(w.current_chat_id, create=True)
            w.current_chat_title = data.get("title", "New Chat")
            w.chat_history = data.get("messages", [])
            if hasattr(w, "external_agent_router"):
                w.external_agent_router.reset()
            try:
                memory_service = w._get_memory_service()
                if memory_service is not None:
                    memory_service.ensure_scope("session", w.current_chat_id)
            except Exception as exc:
                logger.warning("Failed to bind session memory: %s", exc)
            w._restore_roleplay_state_from_history()
            while w.chat_layout.count():
                child = w.chat_layout.takeAt(0)
                if child.widget(): child.widget().deleteLater()
            w._thinking_widget = None
            w.step_progress_widget = None
            w.scroll_area.setUpdatesEnabled(False)
            restored_bubbles = []
            has_explicit_timeline = any(
                isinstance(msg, dict) and msg.get("role") == "timeline" and msg.get("kind") == "step_timeline"
                for msg in w.chat_history
            )
            for msg in w.chat_history:
                if msg.get("role") == "timeline" and msg.get("kind") == "step_timeline":
                    w._add_timeline_widget_from_snapshot(msg.get("timeline") or {})
                    continue
                if msg["role"] in ["user", "assistant"]:
                    content = msg["content"]
                    # Skip system-generated user messages (tool output, error retries, etc.)
                    if msg["role"] == "user":
                        raw_text = extract_text_from_content(content) if isinstance(content, list) else (content or "")
                        if w._is_system_generated_user_message(raw_text):
                            continue
                    images = None
                    files = ((msg.get("attachments") or {}).get("files") or None)
                    display_text = ""

                    # Rebuild display text from structured content when needed.
                    if isinstance(content, list):
                        display_text = msg.get("display_text") or extract_text_from_content(content)
                        # Extract inline images for preview rendering.
                        images = w.base64_to_images(content)
                        if not display_text and images:
                            display_text = "[Image]"
                    else:
                        display_text = msg.get("display_text") or content
                    if msg["role"] == "assistant":
                        display_text = w._sanitize_assistant_response(display_text)
                        legacy_snapshot = None if has_explicit_timeline else w._parse_legacy_timeline_from_message(msg)
                        if legacy_snapshot:
                            w._add_timeline_widget_from_snapshot(legacy_snapshot)

                    bubble = MessageBubble(msg["role"], display_text, images=images, files=files, theme_mode=w.theme_mode)
                    if msg["role"] == "user":
                        bubble.edit_confirmed.connect(w.handle_edit_confirmed)
                    w.chat_layout.addWidget(bubble)
                    restored_bubbles.append(bubble)
            w.scroll_area.setUpdatesEnabled(True)
            QApplication.processEvents()
            for bubble in restored_bubbles:
                bubble._sync_content_visibility()
                bubble.adjust_height()
                bubble.updateGeometry()
            for i in range(w.chat_layout.count()):
                widget = w.chat_layout.itemAt(i).widget()
                if isinstance(widget, StepProgressWidget):
                    try:
                        widget._refresh_geometry()
                    except Exception:
                        widget.adjustSize()
                        widget.updateGeometry()
            w.chat_layout.invalidate()
            w.chat_layout.activate()
            w.chat_container.adjustSize()
            w.chat_container.updateGeometry()
            w._update_visible_bubbles(resync_content=True)
            QApplication.processEvents()
            # Defer one more layout pass so word-wrap heights settle once the
            # scroll area has its real width (avoids the blank-gap glitch
            # that previously only resolved by toggling the workspace).
            QTimer.singleShot(0, lambda: w._update_visible_bubbles(resync_content=True))
            w.scroll_area.verticalScrollBar().setValue(w.scroll_area.verticalScrollBar().maximum())
            w._restore_runtime_visuals_for_current_chat()
            QTimer.singleShot(0, w._dispatch_pending_finished_for_current_chat)
            QTimer.singleShot(0, w._dispatch_pending_execution_for_current_chat)

    def handle_edit_confirmed(self, new_text):
        w = self.window
        # The slot connected to ``bubble.edit_confirmed`` is the window's thin
        # wrapper, so ``w.sender()`` resolves the emitting bubble correctly.
        sender_bubble = w.sender()
        index = w.chat_layout.indexOf(sender_bubble)
        if index == -1:
            return

        visible_bubbles = []
        for i in range(w.chat_layout.count()):
            widget = w.chat_layout.itemAt(i).widget()
            if isinstance(widget, MessageBubble):
                visible_bubbles.append(widget)

        if sender_bubble not in visible_bubbles:
            return

        bubble_index = visible_bubbles.index(sender_bubble)
        message_indexes = [
            i for i, msg in enumerate(w.chat_history)
            if msg.get("role") in {"user", "assistant"}
        ]
        if bubble_index >= len(message_indexes):
            return

        history_index = message_indexes[bubble_index]
        updated_message = dict(w.chat_history[history_index])
        updated_message["content"] = w._replace_message_text_content(updated_message.get("content", ""), new_text)

        has_images = isinstance(updated_message.get("content"), list) and any(
            isinstance(part, dict) and part.get("type") == "image_url"
            for part in updated_message.get("content", [])
        )
        attachments = ((updated_message.get("attachments") or {}).get("files") or [])
        updated_message["display_text"] = w._build_user_display_text(
            new_text,
            images=[object()] if has_images else None,
            files=attachments,
        )

        w.chat_history = w.chat_history[:history_index] + [updated_message]
        while w.chat_layout.count() > index + 1:
            child = w.chat_layout.takeAt(index + 1)
            if child.widget(): child.widget().deleteLater()
        sender_bubble.set_text(updated_message["display_text"])
        sender_bubble.cancel_edit()
        save_chat(w.current_chat_id, w.current_chat_title, w.chat_history)
        w.refresh_history_list()
        w.recursion_depth = 0
        w.resilience.reset()
        w.process_turn()

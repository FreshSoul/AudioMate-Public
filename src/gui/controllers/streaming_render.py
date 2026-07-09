"""Streaming / chat-rendering behaviour for ``MainWindow``.

Extracted verbatim from ``MainWindow`` (the streaming block around
``scroll_to_bottom`` … ``_flush_streaming_render`` plus
``_reset_streaming_state``). It owns chat-bubble creation, the thinking
widget lifecycle, incremental ``<think>`` parsing, per-chat token/finish
routing (including background-chat finalisation), and streaming-state reset.

Follows the same back-reference convention as the other GUI helpers
(``ThemeManager``, ``PetIntegrationController``, ``LayoutController``,
``ModelConfigController`` …): every method operates on the owning
``MainWindow`` via ``w = self.window`` and the controller itself is
STATELESS — all streaming state (``full_streaming_response``,
``current_streaming_bubble``, ``_thinking_widget``, ``pending_branch_bubbles``
…) stays on the window exactly where ``__init__`` initialises it. Internal
cross-calls go through ``w.<method>()`` (the window's thin wrappers) so test
monkeypatching of window methods keeps intercepting the whole chain.

Deliberately NOT moved here:
- ``_set_chat_scrollbar_transient_hidden`` — a regression test pins it via an
  unbound ``MainWindow._set_chat_scrollbar_transient_hidden(fake_window, …)``
  call with a duck-typed window;
- the static text helpers (``_strip_think_block`` …) — already thin
  delegations to ``src.engine.response_parser``;
- ``_queue_internal_*`` / ``_stop_active_worker`` — message-flow / task
  lifecycle, slated for later split phases.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QTimer

from src.engine.turn_controller import TurnAction
from src.gui.chat_runtime import ChatTaskState as _ChatTaskState
from src.gui.common import extract_text_from_content
from src.gui.widgets import AgentThinkingWidget, MessageBubble, StepProgressWidget
from src.utils.app_logger import get_logger
from src.utils.storage import load_chat, save_chat

logger = get_logger(__name__)


class StreamingRenderController:
    """Owns streaming/rendering behaviour for a single ``MainWindow``."""

    def __init__(self, window):
        self.window = window

    def scroll_to_bottom(self):
        w = self.window
        scrollbar = w.scroll_area.verticalScrollBar()
        if scrollbar.value() > scrollbar.maximum() - 100:
            scrollbar.setValue(scrollbar.maximum())

    def _update_visible_bubbles(self, resync_content: bool = False):
        """Keep bubbles visible so the scroll range stays stable on long chats."""
        w = self.window
        for i in range(w.chat_layout.count()):
            item = w.chat_layout.itemAt(i)
            widget = item.widget()
            if widget is None:
                continue
            if not widget.isVisible():
                widget.setVisible(True)
            if resync_content and isinstance(widget, MessageBubble):
                widget._sync_content_visibility()
                widget.adjust_height()
                widget.updateGeometry()
            elif resync_content and isinstance(widget, StepProgressWidget):
                # Timeline cards cache word-wrap heights; force a fresh
                # layout pass so they don't leave a giant blank gap when
                # the chat container width changes (e.g. workspace toggle
                # or initial history restore).
                try:
                    widget._refresh_geometry()
                except Exception:
                    widget.adjustSize()
                    widget.updateGeometry()

    def add_message(self, role, text, images=None, files=None):
        w = self.window
        if role == "assistant" and isinstance(text, str):
            text = w._sanitize_assistant_response(text)
        bubble = MessageBubble(role, text, images=images, files=files, theme_mode=w.theme_mode)
        if role == "user":
            bubble.edit_confirmed.connect(w.handle_edit_confirmed)
        w.chat_layout.addWidget(bubble)
        # Defer height adjustment + scroll-to-bottom to next event-loop tick
        # so layout has resolved. Avoids re-entering the event loop here
        # (processEvents during streaming caused slot recursion / 状态机重入).
        def _after_layout(_b=bubble):
            try:
                _b.adjust_height()
            except RuntimeError:
                return  # widget was deleted before the tick fired
            sb = w.scroll_area.verticalScrollBar()
            sb.setValue(sb.maximum())
        QTimer.singleShot(0, _after_layout)
        return bubble

    def _add_pending_branch_bubble(self):
        w = self.window
        bubble = w.add_message("assistant", "")
        w.pending_branch_bubbles.append(bubble)
        return bubble

    def _current_thinking_task_context(self) -> str:
        w = self.window
        latest_user = w._latest_user_message(include_system_generated=False)
        if latest_user is not None:
            task_text = extract_text_from_content(latest_user.get("content", ""), default="")
            if task_text.strip():
                return task_text.strip()
        return getattr(w.resilience, "_original_goal", "") or ""

    def _ensure_thinking_widget(self, text: str = "正在分析请求", task_context: str = ""):
        w = self.window
        resolved_task_context = (task_context or w._current_thinking_task_context() or "").strip()
        if w._thinking_widget is not None:
            try:
                if getattr(w._thinking_widget, "is_finished", False):
                    w._thinking_widget = None
                else:
                    w._thinking_widget.set_task_context(resolved_task_context)
                    w._thinking_widget.set_running(text)
                    return w._thinking_widget
            except RuntimeError:
                w._thinking_widget = None

        widget = AgentThinkingWidget(theme_mode=w.theme_mode, task_context=resolved_task_context)
        widget.set_running(text)
        w.chat_layout.addWidget(widget)
        w.scroll_to_bottom()
        w._thinking_widget = widget
        return widget

    def _remove_active_thinking_widget(self):
        w = self.window
        widget = w._thinking_widget
        if widget is None:
            w._thinking_phase = False
            return
        try:
            w.chat_layout.removeWidget(widget)
            widget.deleteLater()
        except RuntimeError:
            pass
        w._thinking_widget = None
        w._thinking_phase = False

    def _compact_activity_label(self, raw_text: str, fallback: str) -> str:
        cleaned = re.sub(r"\s+", " ", (raw_text or "").strip())
        cleaned = re.sub(r"^[-*•\d.\s]+", "", cleaned)
        cleaned = cleaned.strip("*_` ")
        if not cleaned:
            return fallback
        if len(cleaned) <= 18:
            return cleaned
        return fallback

    def _clear_pending_branch_bubbles(self):
        w = self.window
        for bubble in w.pending_branch_bubbles:
            try:
                w.chat_layout.removeWidget(bubble)
                bubble.deleteLater()
            except RuntimeError:
                pass
        w.pending_branch_bubbles = []

    def _show_assistant_message(self, text: str):
        w = self.window
        safe_text = w._sanitize_assistant_response(text)
        # Detach current_streaming_bubble from pending list before clearing
        # so it doesn't get deleted while we still want to reuse it.
        target = w.current_streaming_bubble
        if target is not None:
            w.pending_branch_bubbles = [
                b for b in w.pending_branch_bubbles if b is not target
            ]
        w._clear_pending_branch_bubbles()
        if target and not w._streaming_bubble_lost:
            try:
                target.set_text(safe_text)
                return target
            except RuntimeError:
                w._streaming_bubble_lost = True
        w.current_streaming_bubble = w.add_message("assistant", safe_text)
        w._streaming_bubble_lost = False
        return w.current_streaming_bubble

    def handle_token(self, token):
        w = self.window
        w.full_streaming_response += token
        # Parse <think> block incrementally
        if w._thinking_phase:
            w._parse_think_tokens()
        if not w._streaming_render_timer.isActive():
            w._streaming_render_timer.start()

    def _handle_token_for_chat(self, chat_id: str, turn_id: str, worker, token: str):
        w = self.window
        state = w._task_state_for(chat_id, create=False)
        if state is None or state.worker is not worker or state.turn_id != turn_id:
            return
        if getattr(worker, "is_interrupted", False):
            return
        if w._is_chat_visible(chat_id):
            w._activate_runtime_state(chat_id)
            w.handle_token(token)
            w._sync_visible_runtime_to_state()
            return
        state.full_streaming_response += token
        if state.thinking_phase and "</think>" in state.full_streaming_response:
            state.thinking_phase = False
        state.status = "running"
        state.status_detail = "后台生成中"

    def _handle_finished_for_chat(self, chat_id: str, turn_id: str, worker):
        w = self.window
        state = w._task_state_for(chat_id, create=False)
        if state is None or state.worker is not worker or state.turn_id != turn_id:
            return
        if not w._is_chat_visible(chat_id):
            if w._finalize_background_text_turn(chat_id, state):
                state.worker = None
                state.pending_finished = False
                state.running = False
                state.status = "idle"
                state.status_detail = ""
            else:
                state.pending_finished = True
                state.running = False
                state.status = "waiting"
                state.status_detail = "切回对话继续处理结果"
            w.refresh_history_list()
            return
        w._activate_runtime_state(chat_id)
        w.handle_finished()
        current_state = w._task_state_for(chat_id, create=False)
        if current_state is not None and current_state.worker is worker:
            current_state.worker = None
            current_state.running = False
            current_state.status = "idle"
            current_state.status_detail = ""
            current_state.pending_finished = False
            current_state.full_streaming_response = ""
            current_state.current_streaming_bubble = None
            current_state.thinking_widget = None
        w._update_current_chat_controls()
        w.refresh_history_list()

    def _finalize_background_text_turn(self, chat_id: str, state: _ChatTaskState) -> bool:
        """Persist completed background turns that do not require UI interaction."""
        w = self.window
        if state.worker and getattr(state.worker, "is_interrupted", False):
            return True
        roleplay_state, response_without_roleplay = w._extract_roleplay_state_from_response(state.full_streaming_response)
        safe_full_response = w._sanitize_assistant_response(response_without_roleplay)
        turn_result = w.turn_controller.analyse_response(safe_full_response, mode=state.mode)
        if turn_result.action != TurnAction.PURE_TEXT:
            return False
        response_text = w._sanitize_assistant_response(turn_result.response_text)
        if not response_text.strip():
            response_text = "[Agent 未返回任何内容，可能是网络超时或模型异常，请重试。]"

        data = load_chat(chat_id) or {"title": "New Chat", "messages": []}
        messages = data.get("messages", []) if isinstance(data.get("messages"), list) else []
        if roleplay_state and w._is_chat_visible(chat_id):
            w._apply_roleplay_state_update(roleplay_state)
        messages.append({"role": "assistant", "content": response_text})
        title = data.get("title") or w._derive_title_from_messages(messages)
        save_chat(chat_id, title, messages)

        # Mirror the visible-chat finalization tail in handle_finished:
        # title summarisation + memory recording, both bound to the
        # background chat's id and its persisted message list. Without
        # these, background chats keep "New Chat" as title forever and
        # never contribute to the memory store.
        try:
            w._maybe_summarize_title_for(chat_id, messages)
        except Exception:
            logger.exception("Background title summarisation failed")
        try:
            w.memory_manager.record_turn_memory_for(chat_id, response_text, messages)
        except Exception:
            logger.exception("Background memory record failed")
        return True

    def _derive_title_from_messages(self, messages: list[dict]) -> str:
        w = self.window
        for msg in messages:
            if msg.get("role") != "user":
                continue
            display_text = w._first_line(msg.get("display_text", ""))
            if display_text:
                return display_text[:50]
            first_line = w._first_line(extract_text_from_content(msg.get("content", ""), default=""))
            if first_line:
                return first_line[:50]
            files = ((msg.get("attachments") or {}).get("files") or [])
            if files:
                return (files[0].get("name") or "附件")[:50]
        return "New Chat"

    def _dispatch_pending_finished_for_current_chat(self):
        w = self.window
        state = w._current_task_state()
        if state is None or not state.pending_finished or state.worker is None:
            w._update_current_chat_controls()
            return
        finished_worker = state.worker
        state.pending_finished = False
        w._activate_runtime_state(state.chat_id)
        w.handle_finished()
        current_state = w._task_state_for(state.chat_id, create=False)
        if current_state is not None and current_state.worker is finished_worker:
            current_state.worker = None
            current_state.running = False
            current_state.status = "idle"
            current_state.status_detail = ""
            current_state.full_streaming_response = ""
            current_state.current_streaming_bubble = None
            current_state.thinking_widget = None
        w._update_current_chat_controls()
        w.refresh_history_list()

    def _dispatch_pending_execution_for_current_chat(self):
        w = self.window
        state = w._current_task_state()
        if state is None or state.pending_execution_output is None or state.pending_execution_callback is None:
            return
        output = state.pending_execution_output
        callback = state.pending_execution_callback
        state.pending_execution_output = None
        state.pending_execution_callback = None
        state.status = "idle"
        state.status_detail = ""
        callback(output)
        w._update_current_chat_controls()
        w.refresh_history_list()

    def _parse_think_tokens(self):
        """Incrementally parse <think> lines from full_streaming_response."""
        w = self.window
        text = w.full_streaming_response
        # Detect end of think block
        close_idx = text.find("</think>")
        if close_idx != -1:
            think_content = text[:close_idx]
            w._thinking_phase = False
        else:
            think_content = text

        # Strip the <think> tag itself
        inner = think_content
        tag_pos = inner.find("<think>")
        if tag_pos != -1:
            inner = inner[tag_pos + 7:]

        # Parse completed lines
        lines = inner.split("\n")
        # All lines except the last (which may be incomplete) are complete
        complete_lines = lines[:-1] if not text.endswith("\n") and w._thinking_phase else lines

        new_steps = []
        for i, line in enumerate(complete_lines):
            if i < w._think_lines_parsed:
                continue
            stripped = line.strip()
            if stripped.startswith("- "):
                step_text = stripped[2:].strip()
                if step_text:
                    new_steps.append(step_text)
            elif stripped.startswith("-") and len(stripped) > 1:
                step_text = stripped[1:].strip()
                if step_text:
                    new_steps.append(step_text)

        if new_steps and w._thinking_widget:
            try:
                visible_steps = []
                for step_text in new_steps:
                    visible_step = w._visible_agent_activity(step_text)
                    if not visible_steps or visible_steps[-1] != visible_step:
                        visible_steps.append(visible_step)
                for step_text in visible_steps[:-1]:
                    w._thinking_widget.add_step(step_text)
                w._thinking_widget.set_running(visible_steps[-1])
            except RuntimeError:
                w._thinking_widget = None
                state = w._current_task_state()
                if state is not None:
                    state.thinking_widget = None

        w._think_lines_parsed = len(complete_lines)

        # If think block ended, finish the running state
        if not w._thinking_phase and w._thinking_widget:
            try:
                w._thinking_widget.clear_running(promote_completed=True)
                w._thinking_widget.set_running("整理回复内容")
            except RuntimeError:
                w._thinking_widget = None
                state = w._current_task_state()
                if state is not None:
                    state.thinking_widget = None

    def _visible_agent_activity(self, raw_text: str) -> str:
        w = self.window
        text = (raw_text or "").strip().lower()
        if not text:
            return "正在分析请求"

        execution_terms = (
            "执行", "运行", "修改", "应用", "写入", "调用", "批量", "处理对象", "落地",
            "execute", "run", "apply", "write", "update", "modify",
        )
        result_terms = (
            "总结", "回复", "输出", "结果", "说明", "整理",
            "summar", "result", "response", "reply", "format",
        )
        prepare_terms = (
            "检查", "确认", "定位", "理解", "分析", "规划", "准备", "检索", "读取",
            "check", "inspect", "understand", "analy", "plan", "prepare", "read", "lookup",
        )

        if any(term in text for term in execution_terms):
            return w._compact_activity_label(raw_text, "执行修改操作")
        if any(term in text for term in result_terms):
            return w._compact_activity_label(raw_text, "整理回复内容")
        if any(term in text for term in prepare_terms):
            return w._compact_activity_label(raw_text, "检查与规划")
        return w._compact_activity_label(raw_text, "处理当前请求")

    def _hide_streaming_reasoning_bubble(self):
        w = self.window
        if w.current_streaming_bubble and not w._streaming_bubble_lost:
            try:
                w.current_streaming_bubble.set_text("")
            except RuntimeError:
                w._streaming_bubble_lost = True

    def _flush_streaming_render(self):
        w = self.window
        if w.current_streaming_bubble and not w._streaming_bubble_lost:
            try:
                # Do not render raw streaming body content into the chat bubble.
                # This prevents code blocks, self-feedback, and intermediate analysis
                # text from leaking into the visible conversation before final routing.
                w.current_streaming_bubble.set_text("")
                w.scroll_area.verticalScrollBar().setValue(
                    w.scroll_area.verticalScrollBar().maximum())
            except RuntimeError:
                w._streaming_bubble_lost = True

    def _reset_streaming_state(self):
        w = self.window
        w._streaming_render_timer.stop()
        if w.current_streaming_bubble:
            try:
                if not (w.current_streaming_bubble.message_text or "").strip():
                    w.chat_layout.removeWidget(w.current_streaming_bubble)
                    w.current_streaming_bubble.deleteLater()
            except RuntimeError:
                pass
        w.current_streaming_bubble = None
        w.full_streaming_response = ""
        w._streaming_bubble_lost = False
        w._thinking_phase = False
        w._think_lines_parsed = 0
        w._set_chat_scrollbar_transient_hidden(False)
        # Note: _thinking_widget is NOT cleared here so it persists in chat for review

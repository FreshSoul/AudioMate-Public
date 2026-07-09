"""Code-execution orchestration for ``MainWindow``.

Extracted verbatim from ``MainWindow`` (two contiguous blocks:
``_start_code_execution_thread`` … ``_finish_step_code_execution`` and
``_code_requires_waapi_connection`` … ``handle_agent_confirmation``,
including ``handle_finished``). It owns:

* the background ``CodeExecutionThread`` lifecycle (per-chat busy /
  cross-chat WAAPI-write locking, deleted-chat callback dropping),
* single-block execution finalisation: file-write confirm/revoke, Wwise
  change confirmation, resilience-driven error retry,
* multi-step execution: step descriptions, the StepProgressWidget flow,
  per-step file-write confirm/revoke, rollback-and-retry, final summary,
* ``handle_finished`` — dispatch of the analysed LLM turn result
  (intent clarify / validation retry / single / multi / pure text),
* the Agent-Mode confirmation card (``handle_agent_confirmation``).

Follows the same back-reference convention as the other controllers:
every method operates on the owning ``MainWindow`` via ``w = self.window``
and the controller is STATELESS — execution state (``step_code_blocks``,
``step_index``, ``pending_tool_output``, ``_last_executed_code``,
``_step_undo_started`` …) stays on the window. Like
``StreamingRenderController``, it is attached lazily via a module-level
helper in ``main_window`` because tests invoke several of these methods
unbound on duck-typed windows / ``MainWindow.__new__`` instances. Internal
cross-calls go through ``w.<method>()`` (the window's thin wrappers) so
test monkeypatching keeps intercepting the whole chain.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QTimer

from src.engine.turn_controller import TurnAction, TurnResult
from src.engine.waapi_context import perform_waapi_preflight
from src.gui.runtime_support import CodeExecutionThread
from src.gui.widgets import (
    ConfirmationWidget,
    FileWriteConfirmWidget,
    IntentClarifyWidget,
    StepProgressWidget,
)
from src.utils.app_logger import get_logger
from src.utils.storage import save_chat

logger = get_logger(__name__)


class CodeExecutionController:
    """Owns code-execution orchestration for a single ``MainWindow``."""

    def __init__(self, window):
        self.window = window

    def _start_code_execution_thread(self, code: str, mode: str, callback):
        """Start a background code execution thread.

        Returns a tuple ``(started, reason)``:
        - ``started=True, reason=""`` on success.
        - ``started=False, reason="current_busy"`` if this chat already has a
          running execution thread.
        - ``started=False, reason="waapi_locked"`` if another chat is currently
          running an Agent Mode WAAPI write — the lock is transient and the
          caller may retry once the other chat completes.
        - ``started=False, reason="no_state"`` if no chat task state exists.
        """
        w = self.window
        state = w._current_task_state()
        if state is None:
            return False, "no_state"
        if state.execution_thread and state.execution_thread.isRunning():
            return False, "current_busy"
        if mode == "Agent Mode" and w._code_requires_waapi_connection(code):
            for chat_id, other_state in w._chat_task_states.items():
                if chat_id == w.current_chat_id:
                    continue
                other_thread = other_state.execution_thread
                if other_thread and other_thread.isRunning():
                    return False, "waapi_locked"

        thread = CodeExecutionThread(w.code_executor, code, mode, parent=w, owner=w)
        w.execution_thread = thread
        state.execution_thread = thread
        chat_id_snapshot = w.current_chat_id

        def _handle_finished(output: str):
            if w.execution_thread is thread:
                w.execution_thread = None
            task_state = w._task_state_for(chat_id_snapshot, create=False)
            # The chat that owned this execution may have been deleted while
            # the code was running. ``_task_state_for(create=False)`` returns
            # None in that case; firing the callback would run finalization
            # logic (``_handle_single_code_execution_finished`` etc.) against
            # whatever chat happens to be visible right now.
            if task_state is None:
                logger.info(
                    "Dropping execution callback for chat_id=%s (task state gone — chat deleted or task cancelled)",
                    chat_id_snapshot,
                )
                thread.deleteLater()
                return
            if task_state.execution_thread is thread:
                task_state.execution_thread = None
            if not w._is_chat_visible(chat_id_snapshot):
                task_state.pending_execution_output = output
                task_state.pending_execution_callback = callback
                task_state.status = "waiting"
                task_state.status_detail = "切回对话继续执行结果"
                w.refresh_history_list()
                thread.deleteLater()
                return
            try:
                callback(output)
            finally:
                thread.deleteLater()

        thread.finished_signal.connect(_handle_finished)
        thread.start()
        return True, ""

    def _handle_single_code_execution_finished(self, response_text, output, mode, undo_started):
        w = self.window
        if undo_started:
            w.waapi_client.end_undo_group()

        w.pending_tool_output = output

        if w._thinking_widget:
            # Keep the card running across iterations; it will be finalized at the
            # task's true end (PURE_TEXT branch in `handle_finished`).
            w._thinking_widget.add_step("已完成执行")
            w._thinking_widget.clear_running()

        has_error = "Error" in output or "Traceback" in output or "Exception" in output

        # --- Resilience: record action ---
        code_for_record = w._last_executed_code or ""
        w.resilience.record_action(w.recursion_depth, code_for_record, output, has_error)

        # --- Check for pending local file writes ---
        pending_writes = list(w.code_executor.pending_file_writes)
        has_pending_writes = bool(pending_writes) and not has_error

        if has_pending_writes:
            file_paths = [pw.path for pw in pending_writes]
            state = w._current_task_state()
            if state is not None:
                state.pending_file_write_context = (response_text, output, mode, undo_started)
            w._clear_pending_branch_bubbles()
            fw_widget = FileWriteConfirmWidget(file_paths, theme_mode=w.theme_mode)
            fw_widget.confirmed.connect(lambda: w._handle_file_write_confirmed(response_text, output, mode, undo_started))
            fw_widget.revoked.connect(lambda: w._handle_file_write_revoked(response_text, output, mode, undo_started))
            if state is not None:
                state.pending_file_write_widget = fw_widget
            w.chat_layout.addWidget(fw_widget)
            w.scroll_to_bottom()
            w._mirror_to_pet("file_write", fw_widget, file_paths=list(file_paths))
            w.send_btn.setDisabled(True)
            w.input_field.setDisabled(True)
            w._reset_streaming_state()
            return

        w._finish_single_code_execution(response_text, output, mode, undo_started, has_error)

    def _handle_file_write_confirmed(self, response_text, output, mode, undo_started):
        """User confirmed pending file writes — flush them to disk."""
        w = self.window
        state = w._current_task_state()
        if state is not None:
            state.pending_file_write_context = None
            state.pending_file_write_widget = None
        results = w.code_executor.flush_pending_writes()
        # Append file write results to output
        extra = []
        for r in results:
            if r["success"]:
                extra.append(f"[File Write] ✅ 已写入: {r['path']}")
            else:
                extra.append(f"[File Write] ❌ 写入失败: {r['path']} — {r.get('error', '')}")
        if extra:
            output = output + "\n" + "\n".join(extra)
        has_error = "Error" in output or "Traceback" in output or "Exception" in output
        w._finish_single_code_execution(response_text, output, mode, undo_started, has_error)

    def _handle_file_write_revoked(self, response_text, output, mode, undo_started):
        """User rejected pending file writes — discard them."""
        w = self.window
        state = w._current_task_state()
        if state is not None:
            state.pending_file_write_context = None
            state.pending_file_write_widget = None
        count = w.code_executor.discard_pending_writes()
        output = output + f"\n[File Write] ❌ 用户取消了 {count} 个文件的写入。"
        w._notify_current_task_finished(success=False, detail="用户取消了文件写入", cancelled=True)
        has_error = "Error" in output or "Traceback" in output or "Exception" in output
        w._finish_single_code_execution(response_text, output, mode, undo_started, has_error)

    def _finish_single_code_execution(self, response_text, output, mode, undo_started, has_error):
        """Common logic after file-write confirmation (or when no file writes are pending)."""
        w = self.window
        if mode == "Agent Mode" and w.waapi_client.has_changes and not has_error:
            # Save checkpoint on successful write
            w.resilience.save_checkpoint(w.recursion_depth, w.chat_history)
            w._clear_pending_branch_bubbles()
            confirm_widget = ConfirmationWidget(theme_mode=w.theme_mode)
            confirm_widget.confirmed.connect(lambda: w.handle_agent_confirmation(True, confirm_widget))
            confirm_widget.revoked.connect(lambda: w.handle_agent_confirmation(False, confirm_widget))
            w.chat_layout.addWidget(confirm_widget)
            w.scroll_to_bottom()
            w._mirror_to_pet("confirm", confirm_widget)
            w.send_btn.setDisabled(True)
            w.input_field.setDisabled(True)
        else:
            w.send_btn.setDisabled(False)
            w.input_field.setDisabled(False)
            if has_error:
                # --- Resilience: error retry with LLM self-correction ---
                if w.resilience.should_retry_error(output):
                    # Auto-retrieve docs for WAAPI URIs mentioned in the failed code
                    relevant_docs = ""
                    failed_code = w._last_executed_code or ""
                    if failed_code and hasattr(w, 'waapi_retriever'):
                        try:
                            uris = w.waapi_retriever.extract_uris_from_code(failed_code)
                            if uris:
                                relevant_docs = w.waapi_retriever.retrieve_authoritative_by_uris(uris)
                        except Exception:
                            pass
                    error_feedback = w.resilience.format_error_feedback(output, relevant_docs=relevant_docs)
                    w._ensure_thinking_widget("正在根据执行反馈调整方案")
                    w._queue_internal_message("assistant", w._sanitize_assistant_response(response_text))
                    w._queue_internal_message("user", error_feedback)
                    if mode == "Ask Mode":
                        w._clear_pending_branch_bubbles()
                    w._reset_streaming_state()
                    w.process_turn()
                    return
                # Retry exhausted or non-retryable — stop
                non_retryable_msg = w.resilience.get_non_retryable_message(output)
                if non_retryable_msg and w.resilience._consecutive_error_count <= 1:
                    error_message = non_retryable_msg
                else:
                    summary = w._summarize_tool_failure(output)
                    error_message = f"执行失败，已重试 {w.resilience.MAX_ERROR_RETRIES} 次仍未成功，已停止。\n\n{summary}"
                w._show_assistant_message(error_message)
                w.chat_history.append({"role": "assistant", "content": error_message})
                w.current_chat_title = w._derive_chat_title_from_history()
                save_chat(w.current_chat_id, w.current_chat_title, w.chat_history)
                w.refresh_history_list()
                w._notify_current_task_finished(success=False, detail=error_message)
            else:
                # Save checkpoint on success
                w.resilience.save_checkpoint(w.recursion_depth, w.chat_history)
                action_summary = w.resilience.build_action_summary()
                w._record_repo_action_memory(action_summary)
                w._queue_internal_tool_output(output, mode, action_summary=action_summary)
                if mode == "Agent Mode" and not w.waapi_client.has_changes:
                    w._queue_internal_message(
                        "user",
                        "[System Warning] No Wwise write operations were detected. If you intended to modify the project, you failed. Do NOT claim success unless you actually called a write function (e.g., setProperty).",
                    )

                if mode == "Ask Mode":
                    w._clear_pending_branch_bubbles()

                w.process_turn()

        w._reset_streaming_state()

    def _handle_step_code_execution_finished(self, step_num: int, output: str):
        w = self.window
        # --- Check for pending local file writes in step execution ---
        pending_writes = list(w.code_executor.pending_file_writes)
        if pending_writes and not ("Error" in output or "Traceback" in output or "Exception" in output):
            file_paths = [pw.path for pw in pending_writes]
            fw_widget = FileWriteConfirmWidget(file_paths, theme_mode=w.theme_mode)
            fw_widget.confirmed.connect(lambda: w._step_file_write_confirmed(step_num, output))
            fw_widget.revoked.connect(lambda: w._step_file_write_revoked(step_num, output))
            w.chat_layout.addWidget(fw_widget)
            w.scroll_to_bottom()
            w._mirror_to_pet("file_write", fw_widget, file_paths=list(file_paths))
            return

        w._finish_step_code_execution(step_num, output)

    def _step_file_write_confirmed(self, step_num, output):
        w = self.window
        results = w.code_executor.flush_pending_writes()
        extra = []
        for r in results:
            if r["success"]:
                extra.append(f"[File Write] ✅ 已写入: {r['path']}")
            else:
                extra.append(f"[File Write] ❌ 写入失败: {r['path']} — {r.get('error', '')}")
        if extra:
            output = output + "\n" + "\n".join(extra)
        w._finish_step_code_execution(step_num, output)

    def _step_file_write_revoked(self, step_num, output):
        w = self.window
        count = w.code_executor.discard_pending_writes()
        output = output + f"\n[File Write] ❌ 用户取消了 {count} 个文件的写入。"
        w._notify_current_task_finished(success=False, detail="用户取消了文件写入", cancelled=True)
        w._finish_step_code_execution(step_num, output)

    def _finish_step_code_execution(self, step_num: int, output: str):
        w = self.window
        w.step_outputs.append(output)

        has_error = "Error" in output or "Traceback" in output or "Exception" in output

        # --- Resilience: record action ---
        code_for_record = w.step_code_blocks[step_num] if step_num < len(w.step_code_blocks) else ""
        w.resilience.record_action(step_num, code_for_record, output, has_error)

        if has_error:
            # --- Resilience: try rollback to checkpoint and retry ---
            if w.resilience.should_retry_error(output):
                checkpoint = w.resilience.get_latest_valid_checkpoint()
                if checkpoint:
                    # Rollback to last good state
                    restored_history, _ = w.resilience.rollback_to_checkpoint(checkpoint)
                    w.chat_history = restored_history
                # Auto-retrieve docs for WAAPI URIs mentioned in the failed code
                relevant_docs = ""
                if code_for_record and hasattr(w, 'waapi_retriever'):
                    try:
                        uris = w.waapi_retriever.extract_uris_from_code(code_for_record)
                        if uris:
                            relevant_docs = w.waapi_retriever.retrieve_authoritative_by_uris(uris)
                    except Exception:
                        pass
                # Feed error back to LLM for self-correction
                error_feedback = w.resilience.format_error_feedback(output, relevant_docs=relevant_docs)
                w._queue_internal_message("user", error_feedback)
                if w.step_progress_widget is not None:
                    w.step_progress_widget.set_status_message(
                        f"重新规划 {step_num + 1}/{len(w.step_code_blocks)} · {w.step_progress_widget.step_items[step_num]['description']}"
                    )
                # End current step execution and let process_turn retry
                if getattr(w, '_step_undo_started', False):
                    w.waapi_client.end_undo_group()
                    w._step_undo_started = False
                w.send_btn.setDisabled(False)
                w.input_field.setDisabled(False)
                w._reset_streaming_state()
                w.process_turn()
                return

            w.step_progress_widget.fail_step(step_num, output)
            w.finish_step_execution(interrupted_by_error=True)
            return

        # --- Resilience: save checkpoint on success ---
        w.resilience.save_checkpoint(step_num, w.chat_history)

        w.step_progress_widget.complete_step(step_num, output)
        w.step_progress_widget.set_step_detail(step_num, w._summarize_step_output_for_board(output), visible=True)
        if w.mode_selector.currentText() == "Agent Mode" and w.waapi_client.has_changes:
            w.step_has_changes = True

        w.scroll_to_bottom()
        w.step_index += 1
        QTimer.singleShot(50, w.execute_next_step)

    # ------------------------------------------------------------------
    # WAAPI readiness / turn-result dispatch
    # ------------------------------------------------------------------

    def _code_requires_waapi_connection(self, code: str) -> bool:
        if not code:
            return False
        write_patterns = [
            r"\bset_property\s*\(",
            r"\bwaapi_client\.set_property\s*\(",
            r"\bbegin_undo_group\s*\(",
            r"\bend_undo_group\s*\(",
            r"\bundo\s*\(",
            r"ak\.wwise\.core\.object\.(?:create|set|delete|move|copy|pasteProperties)",
            r"ak\.wwise\.core\.audio\.import",
            r"ak\.wwise\.core\.soundbank\.(?:generate|convertExternalSources)",
            r"ak\.wwise\.core\.project\.save",
            r"ak\.wwise\.core\.undo\.",
            r"ak\.soundengine\.",
            r"ak\.wwise\.core\.transport\.",
            r"ak\.wwise\.core\.profiler\.",
            r"ak\.wwise\.core\.remote\.",
        ]
        return any(re.search(pattern, code, re.IGNORECASE) for pattern in write_patterns)

    def _ensure_waapi_execution_ready(self, response_text: str, code_blocks: list[str]) -> bool:
        w = self.window
        if not any(w._code_uses_waapi(code) for code in code_blocks):
            return True

        preflight = perform_waapi_preflight(w.waapi_client)
        if preflight["ok"]:
            return True

        w._show_assistant_message(preflight["message"])
        w.chat_history.append({"role": "assistant", "content": preflight["message"]})
        save_chat(w.current_chat_id, w.current_chat_title, w.chat_history)
        w._reset_streaming_state()
        return False

    def _coerce_confirmation_summary_result(self, turn_result: TurnResult) -> TurnResult:
        w = self.window
        if not getattr(w, "_confirmation_summary_only", False):
            return turn_result
        w._confirmation_summary_only = False
        if turn_result.action not in (TurnAction.SINGLE_CODE, TurnAction.MULTI_CODE):
            return turn_result
        text = (turn_result.response_text or "").strip()
        if text:
            text += "\n\n"
        text += "确认后的总结阶段未继续执行新的代码。请根据上一步输出直接总结结果。"
        return TurnResult(action=TurnAction.PURE_TEXT, response_text=text, code_blocks=[])

    def handle_finished(self):
        w = self.window
        w.send_btn.setText("✈")
        w._streaming_render_timer.stop()
        if w.worker and w.worker.is_interrupted:
            w._clear_pending_branch_bubbles()
            w._reset_streaming_state()
            return

        # Final flush to ensure all accumulated tokens are rendered
        w._flush_streaming_render()

        roleplay_state, response_without_roleplay = w._extract_roleplay_state_from_response(w.full_streaming_response)
        w._apply_roleplay_state_update(roleplay_state)
        safe_full_response = w._sanitize_assistant_response(response_without_roleplay)

        # --- Use TurnController to analyse the LLM response ---
        turn_result = w.turn_controller.analyse_response(safe_full_response, mode=w.mode_selector.currentText())
        turn_result = w._coerce_confirmation_summary_result(turn_result)
        response_text = w._sanitize_assistant_response(turn_result.response_text)

        # Finish the thinking widget's "生成回复" running state
        if w._thinking_widget:
            w._thinking_widget.clear_running()

        # --- Dispatch on TurnAction ---
        if turn_result.action == TurnAction.INTENT_CLARIFY:
            w._clear_pending_branch_bubbles()
            widget = IntentClarifyWidget(turn_result.intent_options, theme_mode=w.theme_mode)
            widget.intent_selected.connect(
                lambda intent, note, wd=widget: w._on_intent_clarified(intent, note, wd)
            )
            w.chat_layout.addWidget(widget)
            w.scroll_to_bottom()
            w._active_intent_clarify_widget = widget
            w._mirror_to_pet("intent", widget, options=list(turn_result.intent_options or []))
            w._reset_streaming_state()
            return

        # Pre-execution validation caught issues — feed warnings back to LLM
        if turn_result.action == TurnAction.ERROR_RETRY and turn_result.validation_warnings:
            warnings_text = "\n".join(f"- {wt}" for wt in turn_result.validation_warnings)
            feedback = (
                f"[System] 代码预验证发现以下问题，请修正后重新生成代码：\n{warnings_text}\n\n"
                "请根据以上提示修正代码，不要执行有问题的代码。"
            )
            w._ensure_thinking_widget("正在调整执行方案")
            w._queue_internal_message("assistant", response_text)
            w._queue_internal_message("user", feedback)
            w._reset_streaming_state()
            w.process_turn()
            return

        if turn_result.action == TurnAction.MULTI_CODE:
            w._hide_streaming_reasoning_bubble()
            w.start_step_execution(response_text, turn_result.code_blocks)
            return

        if turn_result.action == TurnAction.SINGLE_CODE:
            code = turn_result.code_blocks[0]
            if not w._ensure_waapi_execution_ready(response_text, [code]):
                return
            w._hide_streaming_reasoning_bubble()
            w._ensure_thinking_widget("正在执行代码")
            mode = w.mode_selector.currentText()

            undo_started = False
            if mode == "Agent Mode":
                w.waapi_client.reset_changes()
                undo_started = w.waapi_client.begin_undo_group()
            w._sync_executor_context()
            w.send_btn.setDisabled(True)
            w.input_field.setDisabled(True)
            w._last_executed_code = code
            started, reason = w._start_code_execution_thread(
                code,
                mode,
                lambda output, rt=response_text, md=mode, us=undo_started: w._handle_single_code_execution_finished(rt, output, md, us),
            )
            if not started:
                w.send_btn.setDisabled(False)
                w.input_field.setDisabled(False)
                if undo_started:
                    w.waapi_client.end_undo_group()
                if reason == "waapi_locked":
                    error_message = (
                        "另一个对话正在执行写入 Wwise 工程的 WAAPI 操作，已暂停本次执行。"
                        "请等待对方完成后重新发送。"
                    )
                else:
                    error_message = "当前对话已有执行任务在后台运行，请等待完成后再试。"
                w._show_assistant_message(error_message)
                w.chat_history.append({"role": "assistant", "content": error_message})
                w._reset_streaming_state()
            return

        # --- PURE_TEXT: no code blocks ---
        if w._thinking_widget:
            w._thinking_widget.finish()
        if not response_text.strip():
            error_msg = "[Agent 未返回任何内容，可能是网络超时或模型异常，请重试。]"
            w._show_assistant_message(error_msg)
            w.chat_history.append({"role": "assistant", "content": error_msg})
        else:
            w._show_assistant_message(response_text)
            w.chat_history.append({"role": "assistant", "content": response_text})
        w.current_chat_title = w._derive_chat_title_from_history()
        save_chat(w.current_chat_id, w.current_chat_title, w.chat_history)
        w._record_turn_memory(response_text if response_text.strip() else error_msg)
        w.refresh_history_list()
        w._maybe_summarize_title()
        w._notify_current_task_finished(
            success=bool(response_text.strip()),
            detail="Agent 未返回任何内容" if not response_text.strip() else "",
        )

        w._reset_streaming_state()

    # ------------------------------------------------------------------
    # Multi-step execution flow
    # ------------------------------------------------------------------

    def _extract_step_descriptions(self, response_text):
        """从LLM响应文本中提取每个步骤的描述"""
        w = self.window
        code_blocks = w._extract_executable_code_blocks(response_text)
        count = max(len(code_blocks), 0)
        descriptions = [w._describe_code_step(code_blocks[i], i) for i in range(count)]
        lines = [line.strip() for line in (response_text or "").splitlines() if line.strip()]
        for line in lines:
            cleaned = line.strip().strip("*")
            match = re.match(r"^(?:步骤|step)\s*(\d+)\s*[:：-]\s*(.+)$", cleaned, re.IGNORECASE)
            if not match:
                continue
            index = int(match.group(1)) - 1
            if not (0 <= index < count):
                continue
            title = re.sub(r"\s+", " ", match.group(2).strip("*_` "))
            if title:
                descriptions[index] = title
        return descriptions

    @staticmethod
    def _code_block_text(code_block) -> str:
        if isinstance(code_block, dict):
            return str(code_block.get("code") or "")
        return str(code_block or "")

    def _describe_code_step(self, code, index: int) -> str:
        code_text = self._code_block_text(code)
        lines = [line.strip() for line in code_text.splitlines() if line.strip()]
        ignored_prefixes = ("#", "//", "from ", "import ")
        for line in lines:
            if line.startswith(ignored_prefixes):
                continue
            normalized = re.sub(r"\s+", " ", line).strip("*_` ")
            uri_match = re.search(r"['\"](ak\.[^'\"]+)['\"]", normalized, re.IGNORECASE)
            if uri_match:
                uri = uri_match.group(1)
                lowered_uri = uri.lower()
                if any(token in lowered_uri for token in (".get", ".query", ".search")):
                    verb = "查询"
                elif any(token in lowered_uri for token in (".set", ".update", ".modify", ".rename")):
                    verb = "修改"
                elif any(token in lowered_uri for token in (".create", ".add", ".register", ".post")):
                    verb = "创建"
                elif any(token in lowered_uri for token in (".delete", ".remove", ".clear")):
                    verb = "删除"
                elif any(token in lowered_uri for token in (".load", ".open", ".read")):
                    verb = "读取"
                elif any(token in lowered_uri for token in (".save", ".write", ".export")):
                    verb = "写入"
                else:
                    verb = "执行"
                return f"{verb} {uri}"
            call_match = re.search(r"([A-Za-z_][\w\.]*)\s*\(", normalized)
            if call_match:
                call_name = call_match.group(1)
                lowered = call_name.lower()
                if any(token in lowered for token in ("get", "query", "search", "find")):
                    verb = "查询"
                elif any(token in lowered for token in ("set", "update", "modify", "change")):
                    verb = "修改"
                elif any(token in lowered for token in ("create", "add", "register", "post")):
                    verb = "创建"
                elif any(token in lowered for token in ("delete", "remove", "clear")):
                    verb = "删除"
                elif any(token in lowered for token in ("load", "open", "read")):
                    verb = "读取"
                elif any(token in lowered for token in ("save", "write", "export")):
                    verb = "写入"
                else:
                    verb = "执行"
                return f"{verb} {call_name}"
            shortened = normalized[:28].rstrip()
            if shortened:
                suffix = "..." if len(normalized) > 28 else ""
                return f"执行 {shortened}{suffix}"
        return f"执行步骤 {index + 1}"

    def start_step_execution(self, response_text, code_blocks):
        """启动分步执行流程"""
        w = self.window
        mode = w.mode_selector.currentText()
        normalized_code_blocks = [w._code_block_text(code_block) for code_block in (code_blocks or [])]
        if not w._ensure_waapi_execution_ready(response_text, normalized_code_blocks):
            return
        w._remove_active_thinking_widget()
        w.step_code_blocks = normalized_code_blocks
        w.step_index = 0
        w.step_outputs = []
        w.step_has_changes = False

        step_descs = w._extract_step_descriptions(response_text)

        if not w._is_step_progress_widget_usable():
            w.step_progress_widget = StepProgressWidget(len(normalized_code_blocks), step_descs, theme_mode=w.theme_mode)
            w.chat_layout.addWidget(w.step_progress_widget)
        else:
            w.step_progress_widget.reset_flow(len(normalized_code_blocks), step_descs)
            w.step_progress_widget.show()
        w._bind_execution_timeline_widget(w.step_progress_widget, None)
        w.step_progress_widget.set_title_text("AudioMate 执行中...")
        w.step_progress_widget.set_status_message(f"待执行 {len(normalized_code_blocks)} 项")
        w.scroll_to_bottom()

        # Begin undo group for all steps
        w._step_undo_started = False
        if mode == "Agent Mode":
            w.waapi_client.reset_changes()
            w._step_undo_started = w.waapi_client.begin_undo_group()

        # Disable input during step execution
        w.send_btn.setDisabled(True)
        w.input_field.setDisabled(True)

        QTimer.singleShot(100, w.execute_next_step)

    def execute_next_step(self):
        """执行下一个步骤"""
        w = self.window
        if w.step_index >= len(w.step_code_blocks):
            w.finish_step_execution()
            return

        step_num = w.step_index
        code = w.step_code_blocks[step_num]

        w.step_progress_widget.set_current_step(step_num)

        w._sync_executor_context()
        started, reason = w._start_code_execution_thread(
            code,
            w.mode_selector.currentText(),
            lambda output, sn=step_num: w._handle_step_code_execution_finished(sn, output),
        )
        if not started:
            if reason == "waapi_locked":
                detail = "另一个对话正在执行 WAAPI 写操作，等待对方完成后再重试。"
            else:
                detail = "当前对话已有执行任务在后台运行，请等待完成后再试。"
            w.step_progress_widget.fail_step(step_num, detail)
            w.finish_step_execution(interrupted_by_error=True)

    def finish_step_execution(self, interrupted_by_error=False):
        """完成所有步骤的执行"""
        w = self.window
        if getattr(w, '_step_undo_started', False):
            w.waapi_client.end_undo_group()
            w._step_undo_started = False

        # Re-enable input
        w.send_btn.setDisabled(False)
        w.input_field.setDisabled(False)
        w.input_field.setFocus()

        # Combine all step outputs
        combined_output = ""
        for i, output in enumerate(w.step_outputs):
            safe_output = w._prepare_tool_output_for_history(output)
            combined_output += f"[步骤 {i+1} 输出]\n{safe_output}\n"

        if interrupted_by_error:
            combined_output += f"\n[System] Execution interrupted at step {w.step_index + 1} due to an error."
            if w.step_progress_widget is not None:
                w.step_progress_widget.mark_finished(
                    f"执行中断 · 停在 {w.step_index + 1}/{len(w.step_code_blocks)}"
                )
        elif w.step_progress_widget is not None:
            w.step_progress_widget.mark_finished(f"执行完成 · 共 {len(w.step_outputs)} 项")

        w.pending_tool_output = combined_output
        mode = w.mode_selector.currentText()

        if w.step_has_changes:
            w._append_execution_timeline_history()
            save_chat(w.current_chat_id, w.current_chat_title, w.chat_history)
            w._clear_pending_branch_bubbles()
            confirm_widget = ConfirmationWidget(theme_mode=w.theme_mode)
            confirm_widget.confirmed.connect(
                lambda: w.handle_agent_confirmation(True, confirm_widget))
            confirm_widget.revoked.connect(
                lambda: w.handle_agent_confirmation(False, confirm_widget))
            w.chat_layout.addWidget(confirm_widget)
            w.scroll_to_bottom()
            w._mirror_to_pet("confirm", confirm_widget)
            w.send_btn.setDisabled(True)
            w.input_field.setDisabled(True)
        else:
            if interrupted_by_error:
                w._append_execution_timeline_history()
                summary = w._summarize_tool_failure(combined_output)
                error_message = f"分步执行失败，已重试 {w.resilience.MAX_ERROR_RETRIES} 次仍未成功，已停止。\n\n{summary}"
                w._show_assistant_message(error_message)
                w.chat_history.append({"role": "assistant", "content": error_message})
                w.current_chat_title = w._derive_chat_title_from_history()
                save_chat(w.current_chat_id, w.current_chat_title, w.chat_history)
                w.refresh_history_list()
                w._notify_current_task_finished(success=False, detail=error_message)
            else:
                # Save final checkpoint on successful multi-step completion
                w.resilience.save_checkpoint(w.step_index, w.chat_history)
                w._append_execution_timeline_history()
                save_chat(w.current_chat_id, w.current_chat_title, w.chat_history)
                action_summary = w.resilience.build_action_summary()
                w._record_repo_action_memory(action_summary)
                w._queue_internal_message("assistant", "分步执行已完成，请基于执行结果生成自然语言总结。")
                w._queue_internal_tool_output(combined_output, mode, action_summary=action_summary)

                w.process_turn()

        w._reset_streaming_state()

    def handle_agent_confirmation(self, confirmed, widget):
        w = self.window
        # Re-enable input
        w.send_btn.setDisabled(False)
        w.input_field.setDisabled(False)
        w.input_field.setFocus()

        # Remove the ConfirmationWidget from the chat layout immediately on
        # both Confirm and Revoke. Leaving it attached caused noticeable lag
        # on the post-confirm turn: every layout reflow walked through a
        # widget whose buttons were already disconnected, and the next
        # "总结中" thinking panel had to be inserted past it.
        if widget is not None:
            try:
                w.chat_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
            except RuntimeError:
                pass

        if confirmed:
            output = getattr(w, 'pending_tool_output', "No output captured.")
            action_summary = w.resilience.build_action_summary()
            w._record_repo_action_memory(action_summary)
            w._queue_internal_tool_output(
                output,
                w.mode_selector.currentText(),
                action_summary=action_summary,
                summary_only=True,
            )
            w._pending_initial_thinking_text = "总结中"
            # User requested to stop thinking after confirmation
            w.process_turn()
        else:
            try:
                w.waapi_client.undo()
            except Exception:
                pass
            save_chat(w.current_chat_id, w.current_chat_title, w.chat_history)
            w._notify_current_task_finished(success=False, detail="操作已撤销", cancelled=True)
            w.recursion_depth = 0
            w.resilience.reset()

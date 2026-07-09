"""Turn controller — orchestrate the LLM ↔ tool execution loop.

Extracted from ``main_window.py``'s deeply interleaved ``process_turn`` →
``handle_finished`` → ``_handle_single_code_execution_finished`` →
``start_step_execution`` chain.

The controller is a ``QObject`` that communicates with the GUI exclusively
through Qt signals; it never touches widgets directly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal

from src.engine.message_builder import (
    build_llm_messages,
    build_reinforcement_messages,
    format_tool_output_message,
)
from src.engine.response_parser import (
    extract_code_blocks,
    extract_intent_clarify_options,
    is_valid_python_code,
    output_has_error,
    strip_code_fences,
    strip_think_block,
    truncate_tool_output,
)
from src.utils.parsing import extract_pseudo_tool_code_blocks
from src.state.agent_state import AgentState
from src.tools.base import ToolContext, ToolResult, ToolResultStatus
from src.tools.waapi_code_tool import WaapiCodeTool, code_uses_waapi
from src.utils.execution import validate_code_patterns


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class TurnAction(Enum):
    """What the turn controller decided to do after the LLM responded."""
    PURE_TEXT = "pure_text"
    SINGLE_CODE = "single_code"
    MULTI_CODE = "multi_code"
    INTENT_CLARIFY = "intent_clarify"
    ERROR_RETRY = "error_retry"
    CONFIRM_NEEDED = "confirm_needed"
    STOPPED = "stopped"


@dataclass
class TurnResult:
    """Outcome of a single turn, emitted with ``turn_completed``."""
    action: TurnAction
    response_text: str = ""
    code_blocks: list[str] = field(default_factory=list)
    intent_options: list[str] | None = None
    output: str = ""
    has_error: bool = False
    has_changes: bool = False
    validation_warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Turn Controller
# ---------------------------------------------------------------------------


class TurnController(QObject):
    """Manages the LLM ↔ code-execution turn loop.

    Signals
    -------
    turn_completed(TurnResult)
        Emitted when a turn finishes (text reply, code output, or stop).
    confirmation_needed(TurnResult)
        Emitted when code execution produced changes that need user
        confirmation (Confirm / Revoke).
    intent_clarify_needed(list)
        Emitted when the LLM response contains ``[INTENT_CLARIFY]`` options.
    error_retrying(str)
        Emitted when the controller auto-retries after an error.
    turn_stopped(str)
        Emitted when the turn is force-stopped (recursion limit, resilience).
    """

    turn_completed = pyqtSignal(object)       # TurnResult
    confirmation_needed = pyqtSignal(object)   # TurnResult
    intent_clarify_needed = pyqtSignal(list)   # [str, ...]
    error_retrying = pyqtSignal(str)           # error feedback message
    turn_stopped = pyqtSignal(str)             # reason

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._waapi_code_tool = WaapiCodeTool()

    # -----------------------------------------------------------------
    # Response analysis (pure logic, no side effects)
    # -----------------------------------------------------------------

    def analyse_response(self, response_text: str, mode: str = "Agent Mode") -> TurnResult:
        """Parse a raw LLM response and decide the next action.

        This is a *pure* function (no state mutation) so it can be tested
        independently.
        """
        clean = strip_think_block(response_text)

        # 1. Intent clarification?
        options = extract_intent_clarify_options(clean)
        if options:
            return TurnResult(
                action=TurnAction.INTENT_CLARIFY,
                response_text=clean,
                intent_options=options,
            )

        # 2. Code blocks?
        blocks = extract_code_blocks(clean) + extract_pseudo_tool_code_blocks(clean)
        valid_blocks = [b for b in blocks if is_valid_python_code(b["code"])]
        code_list = [b["code"] for b in valid_blocks]

        if mode == "Ask Mode":
            for code in code_list:
                if self._code_contains_local_write(code):
                    return TurnResult(
                        action=TurnAction.PURE_TEXT,
                        response_text=(
                            "这个操作需要写入本地文件，在 Ask Mode 下已被阻止。"
                            "请切换到 Agent Mode 后再执行写入。"
                        ),
                    )

        # If code blocks were found but none compiled, the model likely
        # mixed natural-language text into the fences.  Fall back to
        # pure-text and strip the broken fences so display stays clean.
        if blocks and not valid_blocks:
            if self._text_contains_local_write(clean):
                return TurnResult(
                    action=TurnAction.ERROR_RETRY,
                    response_text=clean,
                    validation_warnings=["检测到文件写入代码但代码块无效；不要把代码作为普通文本展示，请重新生成可执行操作或权限提示。"],
                )
            cleaned_text = strip_code_fences(clean)
            return TurnResult(
                action=TurnAction.PURE_TEXT,
                response_text=cleaned_text or clean,
            )

        if len(code_list) > 1:
            # Pre-validate all code blocks
            all_warnings = []
            for code in code_list:
                all_warnings.extend(validate_code_patterns(code))
            if all_warnings:
                return TurnResult(
                    action=TurnAction.ERROR_RETRY,
                    response_text=clean,
                    code_blocks=code_list,
                    validation_warnings=all_warnings,
                )
            return TurnResult(
                action=TurnAction.MULTI_CODE,
                response_text=clean,
                code_blocks=code_list,
            )

        if code_list:
            # Pre-validate single code block
            warnings = validate_code_patterns(code_list[0])
            if warnings:
                return TurnResult(
                    action=TurnAction.ERROR_RETRY,
                    response_text=clean,
                    code_blocks=code_list,
                    validation_warnings=warnings,
                )
            return TurnResult(
                action=TurnAction.SINGLE_CODE,
                response_text=clean,
                code_blocks=code_list,
            )

        # 3. Pure text
        return TurnResult(
            action=TurnAction.PURE_TEXT,
            response_text=clean,
        )

    # -----------------------------------------------------------------
    # Code execution (delegates to WaapiCodeTool)
    # -----------------------------------------------------------------

    def execute_code(
        self,
        code: str,
        context: ToolContext,
        *,
        use_undo: bool = True,
    ) -> ToolResult:
        """Run a single code block through ``WaapiCodeTool``.

        Returns the ``ToolResult`` with ``data`` dict containing
        ``has_error``, ``has_changes``, ``undo_started``, ``uses_waapi``.
        """
        return self._waapi_code_tool.execute(
            {"code": code, "use_undo_group": use_undo},
            context,
        )

    # -----------------------------------------------------------------
    # Turn-result processing helpers
    # -----------------------------------------------------------------

    def process_code_result(
        self,
        result: ToolResult,
        response_text: str,
        mode: str,
        *,
        resilience: Any = None,
        recursion_depth: int = 0,
        last_code: str = "",
    ) -> TurnResult:
        """Decide what to do after executing code.

        Returns a ``TurnResult`` indicating whether to:
        - emit ``confirmation_needed`` (Agent Mode + changes + no error)
        - auto-retry (error + resilience allows)
        - stop (error + no retries left)
        - continue turn (success, no changes, need LLM follow-up)
        """
        data = result.data or {}
        has_error = data.get("has_error", result.is_error)
        has_changes = data.get("has_changes", False)
        output = result.output

        # Record action in resilience manager
        if resilience:
            resilience.record_action(recursion_depth, last_code, output, has_error)

        if has_error:
            # Check if we should retry
            if resilience and resilience.should_retry_error(output):
                return TurnResult(
                    action=TurnAction.ERROR_RETRY,
                    response_text=response_text,
                    output=output,
                    has_error=True,
                )
            else:
                return TurnResult(
                    action=TurnAction.STOPPED,
                    response_text=response_text,
                    output=output,
                    has_error=True,
                )

        if mode == "Agent Mode" and has_changes:
            return TurnResult(
                action=TurnAction.CONFIRM_NEEDED,
                response_text=response_text,
                output=output,
                has_changes=True,
            )

        # Success, no confirmation needed → LLM should see the output
        # Post-execution validation: append warnings to output if detected
        post_warnings = self._post_validate_output(output)
        if post_warnings:
            warnings_text = "\n".join(f"[Validation] {w}" for w in post_warnings)
            output = f"{output}\n\n{warnings_text}"

        return TurnResult(
            action=TurnAction.PURE_TEXT,
            response_text=response_text,
            output=output,
            has_changes=has_changes,
        )

    # -----------------------------------------------------------------
    # Post-execution output validation
    # -----------------------------------------------------------------

    @staticmethod
    def _code_contains_local_write(code: str) -> bool:
        if not code:
            return False
        patterns = (
            r"\bwrite_user_file\s*\(",
            r"\bwrite_file_tree\s*\(",
            r"call_structured_tool\s*\(\s*['\"]write_(?:user_file|file_tree)['\"]",
            r"\bopen\s*\([^\n]*[,)]\s*['\"][waxt+]",
        )
        return any(re.search(pattern, code, re.IGNORECASE) for pattern in patterns)

    @classmethod
    def _text_contains_local_write(cls, text: str) -> bool:
        blocks = extract_code_blocks(text or "")
        if any(cls._code_contains_local_write(block.get("code", "")) for block in blocks):
            return True
        return any(token in (text or "") for token in ("write_user_file", "write_file_tree", "open("))

    @staticmethod
    def _post_validate_output(output: str) -> list[str]:
        """Check execution output for signs of silent failure.

        Returns a list of warning strings (empty if output looks normal).
        """
        if not output:
            return []
        warnings = []
        stripped = output.strip()

        # Empty/no-op output
        if stripped == "Execution completed with no output.":
            warnings.append(
                "执行成功但无任何输出。如果预期有数据返回，可能遗漏了 print() 语句。"
            )

        try:
            parsed = json.loads(stripped)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            count_values = [parsed.get("count"), parsed.get("file_count"), parsed.get("analyzed_count")]
            results = parsed.get("results")
            if any(value == 0 for value in count_values) and (results == [] or results is None):
                warnings.append(
                    "工具返回 0 个结果；最终回答不得生成逐文件表格、平均响度或最响/最安静结论，只能说明没有分析到文件并给出原因。"
                )

        # Excessive None values suggest field-name mismatch
        none_count = stripped.count("None")
        line_count = max(stripped.count("\n") + 1, 1)
        if none_count > 3 and none_count / line_count > 0.3:
            warnings.append(
                "输出中包含大量 None 值，可能是属性名/字段名不匹配。"
                "建议先用 lookup_waapi_doc() 确认正确的字段名。"
            )

        return warnings

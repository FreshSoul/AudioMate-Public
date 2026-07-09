"""Agent Resilience Module — 韧性机制管理器

Provides:
- Explicit failure handling with LLM self-correction retry
- Implicit failure detection (loops, drift, context overflow)
- CheckPoint mechanism for state rollback
- Fallback strategy for runaway iterations
"""

from __future__ import annotations

import copy
import hashlib
import re
import time
from dataclasses import dataclass, field
from enum import Enum


def _extract_text_from_content(content, default=""):
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
        return "\n".join(parts) if parts else default
    if not isinstance(content, str):
        return str(content) if content else default
    return content


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

class ErrorCategory(Enum):
    """Classification of code execution errors for adaptive retry strategy."""
    SHAPE_ERROR = "shape_error"          # KeyError / AttributeError on data structure
    API_ERROR = "api_error"              # invalid_arguments / unknown property
    CONNECTION_ERROR = "connection_error" # WampConnectionError / timeout
    PERMISSION_ERROR = "permission_error" # ImportError / PermissionError
    LOGIC_ERROR = "logic_error"          # AssertionError / ValueError
    UNKNOWN = "unknown"


_ERROR_PATTERNS: list[tuple[re.Pattern, ErrorCategory]] = [
    # Connection errors — should NOT retry via LLM
    (re.compile(r"WampConnectionError|ConnectionRefusedError|ConnectionResetError|TimeoutError|"
                r"connection\s+refused|wamp.*closed|waapi.*not\s+connect", re.IGNORECASE),
     ErrorCategory.CONNECTION_ERROR),
    # Permission / import errors — should NOT retry via LLM
    (re.compile(r"ImportError|ModuleNotFoundError|PermissionError|Import '.*' is not allowed",
                re.IGNORECASE),
     ErrorCategory.PERMISSION_ERROR),
    # WAAPI API errors — retry with docs
    (re.compile(r"invalid_arguments|invalid_type|invalid_query|schema_validation_failed|schemaKeyword|"
                r"unknown\s+property|Property doesn't exist|"
                r"Invalid property|unknown\s+function|does not exist on the object|"
                r"unknown object type|Invalid object path|from path cannot be resolved|"
                r"Object .* is unknown|unknown_object|query\.unknown_object", re.IGNORECASE),
     ErrorCategory.API_ERROR),
    # Shape / data structure errors — retry with doc lookup hint
    (re.compile(r"KeyError|AttributeError.*has no attribute|TypeError.*subscriptable|"
                r"TypeError.*not iterable|IndexError", re.IGNORECASE),
     ErrorCategory.SHAPE_ERROR),
    # Logic errors — normal retry
    (re.compile(r"AssertionError|AssertionError|ValueError|ZeroDivisionError|"
                r"RecursionError|OverflowError", re.IGNORECASE),
     ErrorCategory.LOGIC_ERROR),
]


def classify_error(output: str) -> ErrorCategory:
    """Classify an error output into a category for adaptive retry strategy."""
    if not output:
        return ErrorCategory.UNKNOWN
    for pattern, category in _ERROR_PATTERNS:
        if pattern.search(output):
            return category
    return ErrorCategory.UNKNOWN


def smart_truncate(text: str, max_len: int = 2000) -> str:
    """Truncate text keeping both head and tail to preserve Traceback endings."""
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    half = max_len // 2
    omitted = len(text) - max_len
    return f"{text[:half]}\n\n...[{omitted} chars truncated]...\n\n{text[-half:]}"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ActionRecord:
    """Single execution step record."""
    step_index: int
    code: str
    output: str
    has_error: bool
    tool_signature: str = ""
    timestamp: float = field(default_factory=time.time)
    waapi_calls: list[str] = field(default_factory=list)
    changes_summary: str = ""


@dataclass
class CheckPoint:
    """Snapshot of agent state at a successful step."""
    step_index: int
    chat_history_snapshot: list = field(default_factory=list)
    intermediate_results: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Tool-call signature extraction
# ---------------------------------------------------------------------------

_CALL_PATTERN = re.compile(
    r"""(?:waapi_client|client)\s*\.\s*(?:call|get_property|set_property|get_selected_objects)\s*\("""
    r"""([^)]{0,500})""",
    re.DOTALL,
)

_TOOL_FUNC_PATTERN = re.compile(
    r"""\b(get_selected_source_files|get_project_source_files"""
    r"""|analyze_audio_file|analyze_wav_file"""
    r"""|analyze_selected_source_files_loudness|analyze_project_source_files_loudness"""
    r"""|analyze_selected_sources_full_route_loudness"""
    r"""|check_directory_loudness_compliance|batch_normalize_directory_to_target"""
    r"""|detect_audio_anomalies|detect_directory_anomalies"""
    r"""|validate_project_structure"""
    r"""|normalize_audio_loudness"""
    r"""|import_audio_files_to_selected_wwise"""
    r"""|read_user_file|write_user_file|list_local_directory|describe_local_path"""
    r"""|request_user_file_access|list_authorized_files"""
    r"""|get_selected_source_filepaths)\s*\(([^)]{0,500})""",
    re.DOTALL,
)


def _compute_tool_signature(code: str) -> str:
    """Extract a fingerprint of tool calls from code for loop detection."""
    if not code:
        return ""

    fragments = []

    for m in _CALL_PATTERN.finditer(code):
        args_text = m.group(1).strip()
        fragments.append(f"waapi_call({_normalize_args(args_text)})")

    for m in _TOOL_FUNC_PATTERN.finditer(code):
        func_name = m.group(1)
        args_text = m.group(2).strip()
        fragments.append(f"{func_name}({_normalize_args(args_text)})")

    if not fragments:
        return hashlib.md5(code.strip().encode("utf-8", errors="replace")).hexdigest()[:12]

    combined = "|".join(sorted(fragments))
    return hashlib.md5(combined.encode("utf-8", errors="replace")).hexdigest()[:12]


def _normalize_args(text: str) -> str:
    """Collapse whitespace and trim for stable comparison."""
    return re.sub(r"\s+", " ", text.strip())[:200]


# ---------------------------------------------------------------------------
# WAAPI call extraction for action logging
# ---------------------------------------------------------------------------

_WAAPI_URI_PATTERN = re.compile(
    r"""['"](\s*ak\.\w[\w.]*\w\s*)['"]""",
)
_WRITE_URI_KEYWORDS = frozenset({
    "set", "create", "delete", "move", "copy", "rename", "import", "undo", "redo",
    "setProperty", "setRandomizer", "setAttenuationCurve", "setReference",
})


def _extract_waapi_calls(code: str) -> list[str]:
    """Extract WAAPI URIs like 'ak.wwise.core.object.get' from code."""
    if not code:
        return []
    uris = []
    for m in _WAAPI_URI_PATTERN.finditer(code):
        uri = m.group(1).strip()
        if uri not in uris:
            uris.append(uri)
    return uris


def _is_write_uri(uri: str) -> bool:
    """Return True if the URI likely represents a write/mutation operation."""
    last_part = uri.rsplit(".", 1)[-1] if uri else ""
    return any(kw in last_part for kw in _WRITE_URI_KEYWORDS)


# ---------------------------------------------------------------------------
# AgentResilienceManager
# ---------------------------------------------------------------------------

class AgentResilienceManager:
    """Manages agent execution resilience across a single user request lifecycle."""

    # Stop earlier on repeated API/schema mistakes; each retry is a full LLM cycle.
    MAX_ERROR_RETRIES = 3
    REFLECT_EVERY_N_STEPS = 5
    MAX_TOTAL_ITERATIONS = 100
    LOOP_DETECT_WINDOW = 8
    HISTORY_KEEP_RECENT = 5  # number of recent turn-pairs to keep verbatim

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset all state for a new user request."""
        self.actions: list[ActionRecord] = []
        self.checkpoints: list[CheckPoint] = []
        self.total_iterations: int = 0
        self._consecutive_error_count: int = 0
        self._last_error_signature: str = ""
        self._original_goal: str = ""

    def set_original_goal(self, goal: str):
        self._original_goal = (goal or "").strip()

    # ------------------------------------------------------------------
    # 1. Explicit failure handling
    # ------------------------------------------------------------------

    def record_action(self, step_index: int, code: str, output: str, has_error: bool):
        sig = _compute_tool_signature(code)
        waapi_calls = _extract_waapi_calls(code)
        self.actions.append(ActionRecord(
            step_index=step_index,
            code=code,
            output=output,
            has_error=has_error,
            tool_signature=sig,
            waapi_calls=waapi_calls,
        ))
        self.total_iterations += 1

        if has_error:
            if sig and sig == self._last_error_signature:
                self._consecutive_error_count += 1
            else:
                self._consecutive_error_count = 1
                self._last_error_signature = sig
        else:
            self._consecutive_error_count = 0
            self._last_error_signature = ""

    def should_retry_error(self, output: str) -> bool:
        """Return True if the current error should be fed back to LLM for self-correction."""
        if self._consecutive_error_count >= self.MAX_ERROR_RETRIES:
            return False
        if self.total_iterations >= self.MAX_TOTAL_ITERATIONS:
            return False
        # Non-retryable error categories
        category = classify_error(output)
        if category in (ErrorCategory.CONNECTION_ERROR, ErrorCategory.PERMISSION_ERROR):
            return False
        return True

    def format_error_feedback(self, output: str, relevant_docs: str = "") -> str:
        """Format an error output into a feedback message for the LLM.

        Args:
            output: The error output from code execution.
            relevant_docs: Optional SDK documentation for the APIs that failed,
                           auto-retrieved to help the LLM self-correct.
        """
        trimmed = smart_truncate(output, 2000)
        category = classify_error(output)

        retry_info = f"（第 {self._consecutive_error_count}/{self.MAX_ERROR_RETRIES} 次重试）"

        doc_section = ""
        if relevant_docs:
            # Limit doc size to avoid context overflow
            doc_text = relevant_docs[:4000]
            if len(relevant_docs) > 4000:
                doc_text += "\n...[doc truncated]"
            doc_section = (
                "\n\n以下是相关 WAAPI 函数的官方文档，请据此修正你的代码：\n"
                f"{doc_text}\n"
            )

        # Category-specific guidance
        extra_guidance = ""
        if category == ErrorCategory.SHAPE_ERROR:
            extra_guidance = (
                "6. 错误类型: 数据结构问题。返回值类型与预期不符。\n"
                "   → 使用 `lookup_waapi_doc('ak.xxx')` 查阅返回值结构\n"
                "   → 使用 `.get(key, default)` 安全访问字典键\n"
                "   → 先 `print(type(result))` 检查返回值类型\n"
            )
        elif category == ErrorCategory.API_ERROR:
            extra_guidance = (
                "6. 错误类型: WAAPI 参数/URI 错误。\n"
                "   → 使用 `lookup_waapi_doc('ak.xxx')` 查阅正确的参数格式\n"
                "   → 仔细对照官方文档中的 args 和 options 结构\n"
                "   → 注意属性名的大小写和拼写\n"
            )
            lowered = (output or "").lower()
            if any(token in lowered for token in ("from path cannot be resolved", " is unknown", "unknown_object")):
                extra_guidance += (
                    "   → 这类错误通常是目标对象路径/父对象猜错了，不要继续复用同一条硬编码路径\n"
                    "   → 先重新查询真实父对象或选中对象的 ID，再把该 ID/GUID 用于后续 create/get/set\n"
                    "   → 不要假设 `\\Master-Mixer Hierarchy\\Default Work Unit\\Master Audio Bus` 一定存在；如果要用总线，先解析实际的 Main Audio Bus 或目标父对象\n"
                )
            if any(token in lowered for token in ("schema_validation_failed", "transform/0", "duckedbuses")):
                extra_guidance += (
                    "   → `ak.wwise.core.object.get` 的 `transform.select` 只能是 parent/children/descendants/ancestors/referencesTo\n"
                    "   → 不要把 `duckedBuses` 这类属性/引用名放进 `transform.select`\n"
                    "   → 先用 `ak.wwise.core.object.getPropertyAndReferenceNames` 确认真实字段名，再通过 `options['return']` 请求文档化属性/引用\n"
                )
            if any(token in lowered for token in ("schema_validation_failed", "schemaexpect", "schemakeyword", "invalid_arguments", "invalid_type", "invalid_query")):
                extra_guidance += (
                    "   → 这是 WAAPI 参数结构错误，不要只改字段名后重试；必须重新核对 args/options 的层级和数组/对象形状\n"
                    "   → `return` 只能放在第三个 options 参数里，不能放进 args；不要把 options 嵌套在 args 中\n"
                    "   → 如果错误里出现占位符或未知 ID，停止使用该 ID，先重新查询真实对象并打印返回结果\n"
                )
        elif category == ErrorCategory.LOGIC_ERROR:
            extra_guidance = (
                "6. 错误类型: 逻辑/值错误。检查数据假设是否正确。\n"
            )

        return (
            f"[System] 执行出错 {retry_info}，请分析错误原因并修正后重试。\n"
            f"错误输出:\n{trimmed}\n\n"
            f"{doc_section}"
            "要求：\n"
            "1. 仔细分析上面的错误信息\n"
            "2. 找出根本原因（如果提供了官方文档，请仔细对照参数格式）\n"
            "3. 生成修正后的代码\n"
            "4. 不要重复相同的错误模式\n"
            "5. 如果不确定正确的参数格式，使用 `lookup_waapi_doc('ak.xxx')` 查阅文档后再编写代码\n"
            f"{extra_guidance}"
        )

    # ------------------------------------------------------------------
    # 2. Implicit failure detection — loop detection
    # ------------------------------------------------------------------

    def detect_loop(self) -> bool:
        """Return True if recent actions show a repetitive loop pattern."""
        if len(self.actions) < self.LOOP_DETECT_WINDOW:
            return False

        recent = self.actions[-self.LOOP_DETECT_WINDOW:]
        sigs = [a.tool_signature for a in recent if a.tool_signature]
        if len(sigs) < self.LOOP_DETECT_WINDOW:
            return False

        # All recent signatures identical → loop
        if len(set(sigs)) == 1:
            return True

        # Check broader window: last 5 actions with >= 4 identical signatures
        if len(self.actions) >= 5:
            last5 = [a.tool_signature for a in self.actions[-5:] if a.tool_signature]
            if last5:
                from collections import Counter
                most_common_count = Counter(last5).most_common(1)[0][1]
                if most_common_count >= 4:
                    return True

        return False

    def build_loop_interrupt_message(self) -> str:
        """Build a message to inject when a loop is detected."""
        recent_sigs = [a.tool_signature for a in self.actions[-self.LOOP_DETECT_WINDOW:]]
        return (
            f"[System] 检测到执行循环：最近 {self.LOOP_DETECT_WINDOW} 步的工具调用模式相似，"
            "可能陷入死循环。请停止当前方法，换一种不同的方式来完成任务。\n"
            "如果无法用其他方式完成，请直接说明当前的困难和已获取的信息。"
        )

    # ------------------------------------------------------------------
    # 3. Direction drift — self-reflection
    # ------------------------------------------------------------------

    def should_self_reflect(self) -> bool:
        """Return True every REFLECT_EVERY_N_STEPS steps."""
        if self.total_iterations == 0:
            return False
        return self.total_iterations % self.REFLECT_EVERY_N_STEPS == 0

    def build_reflection_prompt(self) -> str:
        """Build a self-reflection prompt for the LLM to evaluate direction."""
        goal_text = self._original_goal or "(未记录原始目标)"
        completed_steps = [a for a in self.actions if not a.has_error]
        error_steps = [a for a in self.actions if a.has_error]

        summary_lines = []
        for i, a in enumerate(self.actions[-8:], start=max(1, len(self.actions) - 7)):
            status = "✗ 失败" if a.has_error else "✓ 成功"
            code_preview = a.code[:80].replace("\n", " ") if a.code else "(无代码)"
            summary_lines.append(f"  步骤{i}: [{status}] {code_preview}")

        recent_history = "\n".join(summary_lines) if summary_lines else "  (无执行记录)"

        return (
            f"[System — 自我反思检查点]\n"
            f"原始用户目标: {goal_text}\n"
            f"已执行 {len(completed_steps)} 步成功, {len(error_steps)} 步失败, 共 {self.total_iterations} 次迭代。\n"
            f"最近执行记录:\n{recent_history}\n\n"
            "请评估:\n"
            "1. 当前方向是否仍与原始用户目标一致？\n"
            "2. 如果偏离了，应该回到哪个步骤重新规划？\n"
            "3. 下一步最有效的行动是什么？\n"
            "基于评估继续执行，不要重复已经获取的数据。"
        )

    # ------------------------------------------------------------------
    # 4. Context overflow — history summarization
    # ------------------------------------------------------------------

    def summarize_history(self, chat_history: list) -> list:
        """Compress older history while keeping recent turns verbatim.

        Returns a new list suitable for _build_llm_messages. Does NOT
        modify the original chat_history.
        """
        if not chat_history:
            return []

        # Find turn boundaries (a "turn" = consecutive user+assistant messages)
        # Count assistant messages as turn markers
        assistant_indices = [i for i, m in enumerate(chat_history) if m.get("role") == "assistant"]
        turn_count = len(assistant_indices)

        if turn_count <= self.HISTORY_KEEP_RECENT:
            return list(chat_history)

        # Keep last HISTORY_KEEP_RECENT turns verbatim
        # Find the index where recent history starts
        keep_from_idx = assistant_indices[-self.HISTORY_KEEP_RECENT]
        # Walk backward to include the user message that precedes this assistant message
        while keep_from_idx > 0 and chat_history[keep_from_idx - 1].get("role") == "user":
            keep_from_idx -= 1

        old_part = chat_history[:keep_from_idx]
        recent_part = chat_history[keep_from_idx:]

        if not old_part:
            return list(chat_history)

        # Build summary of old part
        summary = self._build_history_summary(old_part)
        summary_message = {"role": "user", "content": summary}
        return [summary_message] + list(recent_part)

    def _build_history_summary(self, messages: list) -> str:
        """Create a concise summary of a message list."""
        goal = ""
        completed_actions = []
        key_results = []

        for msg in messages:
            role = msg.get("role", "")
            text = _extract_text_from_content(msg.get("content", ""))

            if role == "user" and not self._is_system_generated(text):
                if not goal:
                    goal = text[:300]
                continue

            if role == "user" and text.startswith("Output:"):
                output_preview = text[7:].strip()[:200]
                if output_preview:
                    key_results.append(output_preview)
                continue

            if role == "assistant":
                # Extract what was done
                code_blocks = re.findall(r"```(?:python_waapi|python|py)\s*\n(.*?)```", text, re.DOTALL)
                if code_blocks:
                    for cb in code_blocks[:3]:
                        action_preview = cb.strip()[:120].replace("\n", " ")
                        completed_actions.append(action_preview)
                continue

        parts = ["[历史摘要]"]
        if goal:
            parts.append(f"用户原始目标: {goal}")
        if completed_actions:
            actions_text = "; ".join(completed_actions[:5])
            parts.append(f"已执行操作: {actions_text}")
        if key_results:
            results_text = "; ".join(key_results[:3])
            parts.append(f"关键结果: {results_text}")

        return "\n".join(parts)

    @staticmethod
    def _is_system_generated(text: str) -> bool:
        normalized = (text or "").strip()
        return (
            normalized.startswith("Output:\n")
            or normalized.startswith("分步执行完成:\n")
            or normalized.startswith("User revoked")
            or normalized.startswith("[System")
        )

    # ------------------------------------------------------------------
    # 5. CheckPoint mechanism
    # ------------------------------------------------------------------

    def save_checkpoint(self, step_index: int, chat_history: list, intermediate_results: dict = None):
        """Save a checkpoint after a successful step."""
        self.checkpoints.append(CheckPoint(
            step_index=step_index,
            chat_history_snapshot=copy.deepcopy(chat_history),
            intermediate_results=dict(intermediate_results or {}),
        ))
        # Keep at most 10 checkpoints to limit memory
        if len(self.checkpoints) > 10:
            self.checkpoints = self.checkpoints[-10:]

    def get_latest_valid_checkpoint(self) -> CheckPoint | None:
        """Get the most recent checkpoint, if any."""
        return self.checkpoints[-1] if self.checkpoints else None

    def rollback_to_checkpoint(self, checkpoint: CheckPoint) -> tuple[list, dict]:
        """Return (chat_history, intermediate_results) from a checkpoint.

        Also removes all checkpoints after the one we rolled back to.
        """
        # Remove checkpoints after this one
        idx = None
        for i, cp in enumerate(self.checkpoints):
            if cp is checkpoint:
                idx = i
                break
        if idx is not None:
            self.checkpoints = self.checkpoints[:idx + 1]

        # Remove action records after the checkpoint step
        self.actions = [a for a in self.actions if a.step_index <= checkpoint.step_index]

        return (
            copy.deepcopy(checkpoint.chat_history_snapshot),
            dict(checkpoint.intermediate_results),
        )

    # ------------------------------------------------------------------
    # 6. Fallback strategy
    # ------------------------------------------------------------------

    def should_force_stop(self) -> bool:
        """Return True when total iterations reach the hard limit."""
        return self.total_iterations >= self.MAX_TOTAL_ITERATIONS

    def build_fallback_response(self) -> str:
        """Build a response using whatever data has been collected so far."""
        successful = [a for a in self.actions if not a.has_error]
        failed = [a for a in self.actions if a.has_error]

        parts = [
            f"[系统] 已达到最大执行次数（{self.MAX_TOTAL_ITERATIONS} 次），自动停止。",
            f"共执行 {len(successful)} 步成功, {len(failed)} 步失败。",
        ]

        # Collect data from successful outputs
        collected_data = []
        for a in successful:
            output = (a.output or "").strip()
            if output and output != "Execution completed with no output.":
                preview = output[:500]
                collected_data.append(preview)

        if collected_data:
            parts.append("\n以下是已获取的数据（基于成功执行的步骤）:")
            for i, data in enumerate(collected_data[-5:], 1):
                parts.append(f"\n--- 数据 {i} ---\n{data}")
        else:
            parts.append("\n未获取到有效数据。")

        if failed:
            last_error = failed[-1].output or ""
            if last_error:
                error_preview = last_error[:300]
                parts.append(f"\n最后一次错误:\n{error_preview}")

        parts.append("\n请根据以上已获取的数据进行分析并说明情况。如果数据不足，请说明缺少什么信息。")

        return "\n".join(parts)


    # ------------------------------------------------------------------
    # Convenience: combined pre-turn check
    # ------------------------------------------------------------------

    def pre_turn_check(self) -> dict:
        """Run all checks before a new process_turn iteration.

        Returns a dict with:
          - "allow": bool — whether to proceed
          - "action": str — "continue" | "force_stop" | "loop_detected" | "reflect"
          - "message": str — message to inject (if any)
        """
        if self.should_force_stop():
            return {
                "allow": False,
                "action": "force_stop",
                "message": self.build_fallback_response(),
            }

        if self.detect_loop():
            return {
                "allow": True,
                "action": "loop_detected",
                "message": self.build_loop_interrupt_message(),
            }

        if self.should_self_reflect():
            return {
                "allow": True,
                "action": "reflect",
                "message": self.build_reflection_prompt(),
            }

        return {"allow": True, "action": "continue", "message": ""}

    # ------------------------------------------------------------------
    # 7. Structured action summary for task completion reporting
    # ------------------------------------------------------------------

    def build_action_summary(self) -> str:
        """Build a structured summary of all actions taken in this session.

        Returns a concise log suitable for appending to Output messages,
        so the LLM can generate an informed completion report.
        """
        if not self.actions:
            return ""

        successful = [a for a in self.actions if not a.has_error]
        failed = [a for a in self.actions if a.has_error]

        lines = []
        for i, a in enumerate(self.actions, 1):
            status = "✓" if not a.has_error else "✗"
            uris_str = ", ".join(a.waapi_calls[:3]) if a.waapi_calls else "(no WAAPI call)"
            write_flag = ""
            if a.waapi_calls and any(_is_write_uri(u) for u in a.waapi_calls):
                write_flag = " [WRITE]"
            lines.append(f"  {status} Step {i}: {uris_str}{write_flag}")

        header = f"Executed {len(self.actions)} step(s): {len(successful)} succeeded, {len(failed)} failed"
        if failed:
            retried = len(failed) - (1 if self._consecutive_error_count > 0 else 0)
            if retried > 0:
                header += f" ({retried} retried and corrected)"

        parts = [header] + lines
        return "\n".join(parts)

    def get_non_retryable_message(self, output: str) -> str:
        """Build a user-facing message for errors that should not be retried."""
        category = classify_error(output)
        trimmed = smart_truncate(output, 1500)
        if category == ErrorCategory.CONNECTION_ERROR:
            return (
                f"执行失败：Wwise 连接错误，请检查 Wwise 是否已启动并启用了 WAAPI。\n\n"
                f"错误详情:\n{trimmed}"
            )
        if category == ErrorCategory.PERMISSION_ERROR:
            return (
                f"执行失败：权限/导入错误，该操作不被允许。\n\n"
                f"错误详情:\n{trimmed}"
            )
        return f"执行失败。\n\n错误详情:\n{trimmed}"

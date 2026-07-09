"""Phase 3 smoke tests — engine module."""
import sys, os
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

from src.engine import (
    extract_code_blocks,
    extract_intent_clarify_options,
    extract_roleplay_state_block,
    is_system_generated_user_message,
    output_has_error,
    parse_think_steps,
    redact_prompt_content,
    sanitize_assistant_response,
    strip_think_block,
    truncate_tool_output,
    summarize_tool_failure,
    build_llm_messages,
    build_reinforcement_messages,
    format_tool_output_message,
    TurnAction,
    TurnController,
    TurnResult,
)

# --- response_parser ---
assert strip_think_block("<think>\n- step1\n</think>\nHello") == "Hello"
assert strip_think_block("No think here") == "No think here"
print("strip_think_block: OK")

leaky = """
THINKING RULE (MANDATORY):
- You MUST start EVERY response with a <think> block before any other content.

这是正常回答。
"""
assert redact_prompt_content(leaky) == "这是正常回答。"
assert sanitize_assistant_response(leaky) == "这是正常回答。"
assert sanitize_assistant_response("You are a Wwise assistant.\nTHINKING RULE (MANDATORY):\n- You MUST...") == "I can't discuss that."
cn_leak = """
对，这条要求是对的。

如果要回答任何依赖工程当前状态的问题，比如：
你选中了什么
某个对象的属性值
当前数量、结构、层级
路由、音量、引用关系
我都必须先发 python_waapi 查询代码，不能靠猜。
"""
assert sanitize_assistant_response(cn_leak) == "I can't discuss that."
print("sanitize_assistant_response: OK")

state, cleaned = extract_roleplay_state_block(
    "[ROLEPLAY_STATE]\n{\"action\":\"set\",\"persona\":\"严谨架构师\",\"style\":\"冷静克制\"}\n[/ROLEPLAY_STATE]\n你好"
)
assert state == {"action": "set", "persona": "严谨架构师", "style": "冷静克制"}
assert cleaned == "你好"
assert sanitize_assistant_response("[ROLEPLAY_STATE]\n{\"action\":\"clear\"}\n[/ROLEPLAY_STATE]\n已恢复普通回复") == "已恢复普通回复"
print("extract_roleplay_state_block: OK")

steps = parse_think_steps("- step one\n- step two\n  not a step\n- step three")
assert steps == ["step one", "step two", "step three"]
print("parse_think_steps: OK")

blocks = extract_code_blocks("```python_waapi\nprint(1)\n```\ntext\n```python\nprint(2)\n```")
assert len(blocks) == 2
assert blocks[0]["language"] == "python_waapi"
assert blocks[1]["code"].strip() == "print(2)"
blocks_upper = extract_code_blocks("```PY\nprint(3)\n```")
assert len(blocks_upper) == 1
assert blocks_upper[0]["language"] == "py"
assert extract_code_blocks("") == []
print("extract_code_blocks: OK")

opts = extract_intent_clarify_options(
    "Some text\n[INTENT_CLARIFY]\n- Option A\n- Option B\n[/INTENT_CLARIFY]\nmore"
)
assert opts == ["Option A", "Option B"]
assert extract_intent_clarify_options("no block here") is None
print("extract_intent_clarify_options: OK")

assert is_system_generated_user_message("Output:\nsome data")
assert is_system_generated_user_message("[System] error")
assert not is_system_generated_user_message("Hello, can you help?")
print("is_system_generated_user_message: OK")

assert output_has_error("Error executing code: ...")
assert output_has_error("Traceback (most recent call last):")
assert output_has_error("Unhandled Exception: boom")
assert not output_has_error("Execution completed.")
assert not output_has_error("")
print("output_has_error: OK")

assert truncate_tool_output("") == "No output captured."
assert len(truncate_tool_output("x" * 1000)) == 1000
print("truncate_tool_output: OK")

assert "截断" in summarize_tool_failure("x" * 2000)
print("summarize_tool_failure: OK")

# --- message_builder ---
msgs = build_llm_messages(
    "System prompt",
    [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ],
)
assert msgs[0]["role"] == "system"
assert msgs[1]["content"] == "Hello"
assert len(msgs) == 3
print("build_llm_messages: OK")

msgs_mem = build_llm_messages(
    "System prompt",
    [{"role": "user", "content": "Hello"}],
    memory_context="MEMORY CONTEXT\n[User Memory]\n- Prefer Chinese.",
)
assert msgs_mem[0]["role"] == "system"
assert msgs_mem[1]["role"] == "system"
assert msgs_mem[1]["content"].startswith("MEMORY CONTEXT")
assert msgs_mem[2]["content"] == "Hello"
print("build_llm_messages with memory context: OK")

# with compressor
msgs2 = build_llm_messages(
    "SP",
    [{"role": "user", "content": "A"}, {"role": "user", "content": "B"}],
    history_compressor=lambda h: h[-1:],  # keep last only
)
assert len(msgs2) == 2  # system + 1 user
print("build_llm_messages with compressor: OK")

reinforcements = build_reinforcement_messages(
    mode="Agent Mode",
    is_disconnected_waapi_request=True,
    last_message_is_user=True,
)
assert len(reinforcements) == 1
assert "NOT connected" in reinforcements[0]["content"]
print("build_reinforcement_messages: OK")

msg = format_tool_output_message("result data", mode="Agent Mode", has_changes=False)
assert msg.startswith("Output:\n")
assert "未检测到" in msg
print("format_tool_output_message: OK")

# --- turn_controller ---
tc = TurnController()

# Pure text
r = tc.analyse_response("<think>\n- plan\n</think>\nJust a text answer.")
assert r.action == TurnAction.PURE_TEXT
assert "Just a text answer" in r.response_text
print("analyse_response (pure text): OK")

# Single code
r = tc.analyse_response("<think>\n- check\n</think>\n```python_waapi\nprint(1)\n```")
assert r.action == TurnAction.SINGLE_CODE
assert len(r.code_blocks) == 1
print("analyse_response (single code): OK")

# Multi code
r = tc.analyse_response("```python_waapi\nstep1\n```\ntext\n```python_waapi\nstep2\n```")
assert r.action == TurnAction.MULTI_CODE
assert len(r.code_blocks) == 2
print("analyse_response (multi code): OK")

# Intent clarify
r = tc.analyse_response("[INTENT_CLARIFY]\n- A\n- B\n[/INTENT_CLARIFY]")
assert r.action == TurnAction.INTENT_CLARIFY
assert r.intent_options == ["A", "B"]
print("analyse_response (intent clarify): OK")

# process_code_result
from src.tools.base import ToolResult, ToolResultStatus
success_result = ToolResult(output="done", status=ToolResultStatus.SUCCESS, data={"has_error": False, "has_changes": True})
tr = tc.process_code_result(success_result, "resp", "Agent Mode")
assert tr.action == TurnAction.CONFIRM_NEEDED
print("process_code_result (confirm needed): OK")

error_result = ToolResult(output="Error: bad", status=ToolResultStatus.ERROR, data={"has_error": True, "has_changes": False})
tr = tc.process_code_result(error_result, "resp", "Agent Mode")
assert tr.action == TurnAction.STOPPED  # no resilience → stopped
print("process_code_result (stopped on error): OK")

print("\n=== All Phase 3 tests passed ===")

"""
test_agent_resilience.py — Agent 韧性模块全面测试套件

覆盖范围:
  1. 显性失败：错误重试、重试计数、错误反馈格式
  2. 隐性失败 - 死循环检测：相同工具签名、近似签名、不同签名
  3. 隐性失败 - 方向偏离：自我反思触发频率、反思 prompt 内容
  4. 隐性失败 - 上下文溢出：历史压缩、摘要内容保真度
  5. CheckPoint：保存/回滚/上限/多检查点管理
  6. 兜底策略：强制停止、兜底响应内容
  7. 工具签名提取：各种代码模式的指纹稳定性
  8. pre_turn_check 统一入口
  9. 数据结构与 reset
  10. 端到端场景模拟
  11. 边界与鲁棒性
  12. 性能/压力测试

运行: python test_agent_resilience.py
"""

import sys
import os
import importlib.util
import time
import copy
import traceback

import pytest

# ---------------------------------------------------------------------------
# Import resilience module directly (bypass llm __init__ which needs openai)
# ---------------------------------------------------------------------------
_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_test_dir, "..", ".."))
_spec = importlib.util.spec_from_file_location(
    "agent_resilience",
    os.path.join(_project_root, "src", "llm", "agent_resilience.py"),
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["agent_resilience"] = _mod
_spec.loader.exec_module(_mod)

AgentResilienceManager = _mod.AgentResilienceManager
ActionRecord = _mod.ActionRecord
CheckPoint = _mod.CheckPoint
_compute_tool_signature = _mod._compute_tool_signature
_normalize_args = _mod._normalize_args
_extract_text_from_content = _mod._extract_text_from_content
ErrorCategory = _mod.ErrorCategory
classify_error = _mod.classify_error
smart_truncate = _mod.smart_truncate
_extract_waapi_calls = _mod._extract_waapi_calls
_is_write_uri = _mod._is_write_uri


# ---------------------------------------------------------------------------
# Lightweight test framework
# ---------------------------------------------------------------------------

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.current_section = ""

    def section(self, name):
        self.current_section = name
        print("\n" + "=" * 60)
        print("  " + name)
        print("=" * 60)

    def ok(self, name):
        self.passed += 1
        print("  [PASS] " + name)

    def fail(self, name, detail=""):
        self.failed += 1
        msg = "  [FAIL] " + name
        if detail:
            msg += " -- " + detail
        self.errors.append("[%s] %s: %s" % (self.current_section, name, detail))
        print(msg)

    def summary(self):
        total = self.passed + self.failed
        print("\n" + "=" * 60)
        print("  Result: %d/%d passed, %d failed" % (self.passed, total, self.failed))
        print("=" * 60)
        if self.errors:
            print("\nFailure details:")
            for e in self.errors:
                print("  - " + e)
        return self.failed == 0


def check(r, name, condition, detail=""):
    if condition:
        r.ok(name)
    else:
        r.fail(name, detail or "assertion failed")


@pytest.fixture
def r():
    result = TestResult()
    yield result
    assert result.summary()


# ---------------------------------------------------------------------------
# 1. Explicit failure handling
# ---------------------------------------------------------------------------

def test_explicit_failure(r):
    r.section("1. Explicit failure handling")

    # 1.1 First error allows retry
    m = AgentResilienceManager()
    m.record_action(1, "code", "Error: something", True)
    check(r, "First error allows retry", m.should_retry_error("Error: something"))

    # 1.2 Same error 3 times → stop
    m2 = AgentResilienceManager()
    code = 'waapi_client.call("ak.wwise.core.object.get", {"from": {"id": ["xxx"]}})'
    for i in range(3):
        m2.record_action(i + 1, code, "Error: unknown_object", True)
    check(r, "Same error stops after 3 retries",
          not m2.should_retry_error("Error: unknown_object"))
    check(r, "Consecutive error count = 3",
          m2._consecutive_error_count == 3,
          "got %d" % m2._consecutive_error_count)

    # 1.3 Different error signature resets count
    m3 = AgentResilienceManager()
    m3.record_action(1, 'waapi_client.call("get", {})', "Error: A", True)
    m3.record_action(2, 'waapi_client.call("set", {})', "Error: B", True)
    check(r, "Different error sig resets count", m3._consecutive_error_count == 1)
    check(r, "Different error still retryable", m3.should_retry_error("Error: B"))

    # 1.4 Success resets error counter and signature
    m4 = AgentResilienceManager()
    m4.record_action(1, "code_a", "Error: X", True)
    m4.record_action(2, "code_a", "Error: X", True)
    check(r, "Error count = 2 before success", m4._consecutive_error_count == 2)
    m4.record_action(3, "code_b", "success result", False)
    check(r, "Success resets error count to 0", m4._consecutive_error_count == 0)
    check(r, "Success clears error signature", m4._last_error_signature == "")

    # 1.5 No retry at iteration limit
    m5 = AgentResilienceManager()
    limit = m5.MAX_TOTAL_ITERATIONS
    for i in range(limit):
        m5.record_action(i, "code%d" % i, "ok", False)
    m5.record_action(limit, "bad_code", "Error: late error", True)
    check(r, "No retry at iteration limit", not m5.should_retry_error("Error: late error"))

    # 1.6 format_error_feedback content
    m6 = AgentResilienceManager()
    m6.record_action(1, "code", "Error: KeyError 'type'", True)
    fb = m6.format_error_feedback("Error: KeyError 'type'")
    check(r, "Feedback includes retry count", "1/3" in fb)
    check(r, "Feedback includes error content", "KeyError" in fb)
    check(r, "Feedback includes fix instruction",
          any(kw in fb for kw in ["修正", "修复", "分析"]))

    # 1.7 Long error is truncated
    long_err = "Error: " + "x" * 5000
    fb_long = m6.format_error_feedback(long_err)
    check(r, "Long error is truncated", "truncated" in fb_long)
    check(r, "Truncated feedback length reasonable",
          len(fb_long) < 4000,
          "got %d" % len(fb_long))


# ---------------------------------------------------------------------------
# 2. Loop detection
# ---------------------------------------------------------------------------

def test_loop_detection(r):
    r.section("2. Implicit failure - Loop detection")

    # 2.1 Full loop window of identical calls = loop
    m = AgentResilienceManager()
    same = 'waapi_client.call("ak.wwise.core.object.get", {"from": {"ofType": ["Sound"]}})'
    for i in range(m.LOOP_DETECT_WINDOW):
        m.record_action(i, same, "ok", False)
    check(r, "Loop window identical calls = loop", m.detect_loop())

    # 2.2 Different calls = no loop
    m2 = AgentResilienceManager()
    m2.record_action(0, 'waapi_client.call("get", {})', "ok", False)
    m2.record_action(1, 'waapi_client.call("set", {})', "ok", False)
    m2.record_action(2, 'analyze_audio_file("/path")', "ok", False)
    check(r, "Different calls = no loop", not m2.detect_loop())

    # 2.3 < 3 steps = no loop
    m3 = AgentResilienceManager()
    m3.record_action(0, same, "ok", False)
    m3.record_action(1, same, "ok", False)
    check(r, "< 3 steps = no loop", not m3.detect_loop())

    # 2.4 Empty actions = no loop
    m4 = AgentResilienceManager()
    check(r, "Empty actions = no loop", not m4.detect_loop())

    # 2.5 Wide window (4/5 identical)
    m5 = AgentResilienceManager()
    repeat_code = 'get_selected_source_files()'
    for i in range(max(0, m5.LOOP_DETECT_WINDOW - 5)):
        m5.record_action(i, 'warmup_code_%d' % i, "ok", False)
    base = max(0, m5.LOOP_DETECT_WINDOW - 5)
    m5.record_action(base, repeat_code, "ok", False)
    m5.record_action(base + 1, 'other_code = 1+1', "ok", False)
    m5.record_action(base + 2, repeat_code, "ok", False)
    m5.record_action(base + 3, repeat_code, "ok", False)
    m5.record_action(base + 4, repeat_code, "ok", False)
    check(r, "4/5 identical = loop (wide window)", m5.detect_loop())

    # 2.6 Interrupt message content
    msg = m.build_loop_interrupt_message()
    check(r, "Interrupt msg mentions loop",
          any(kw in msg for kw in ["循环", "重复"]))
    check(r, "Interrupt msg has suggestion",
          any(kw in msg for kw in ["不同的方式", "换", "其他"]))

    # 2.7 Different args same function = no loop
    m6 = AgentResilienceManager()
    m6.record_action(0, 'analyze_audio_file("/path/a.wav")', "ok", False)
    m6.record_action(1, 'analyze_audio_file("/path/b.wav")', "ok", False)
    m6.record_action(2, 'analyze_audio_file("/path/c.wav")', "ok", False)
    check(r, "Different args = no loop", not m6.detect_loop())

    # 2.8 Loop in error steps
    m7 = AgentResilienceManager()
    err_code = 'waapi_client.call("ak.wwise.core.object.get", {"from": {"id": ["bad-id"]}})'
    for i in range(m7.LOOP_DETECT_WINDOW):
        m7.record_action(i, err_code, "Error: unknown", True)
    check(r, "Loop detected in error steps too", m7.detect_loop())


# ---------------------------------------------------------------------------
# 3. Direction drift / Self-reflection
# ---------------------------------------------------------------------------

def test_self_reflection(r):
    r.section("3. Implicit failure - Self-reflection")

    # 3.1 No reflection at start
    m = AgentResilienceManager()
    check(r, "No reflection at start", not m.should_self_reflect())

    # 3.2 Reflect at step 5
    m2 = AgentResilienceManager()
    for i in range(5):
        m2.record_action(i, "code%d" % i, "ok", False)
    check(r, "Reflect at step 5", m2.should_self_reflect())

    # 3.3 No reflect at step 6
    m2.record_action(5, "code5", "ok", False)
    check(r, "No reflect at step 6", not m2.should_self_reflect())

    # 3.4 Reflect again at step 10
    for i in range(6, 10):
        m2.record_action(i, "code%d" % i, "ok", False)
    check(r, "Reflect again at step 10", m2.should_self_reflect())

    # 3.5 Reflection prompt includes original goal
    m3 = AgentResilienceManager()
    m3.set_original_goal("批量修改所有 Sound 对象的音量为 -6dB")
    for i in range(5):
        m3.record_action(i, "step_%d_code" % i, "result_ok", False)
    prompt = m3.build_reflection_prompt()
    check(r, "Reflection includes original goal",
          "批量修改所有 Sound 对象的音量" in prompt)

    # 3.6 Reflection counts successes and iterations
    check(r, "Reflection counts successes", "5 步成功" in prompt)
    check(r, "Reflection counts iterations",
          "5 次迭代" in prompt or "5" in prompt)

    # 3.7 Reflection has history and evaluation request
    check(r, "Reflection has step history",
          any(kw in prompt for kw in ["步骤", "成功", "执行"]))
    check(r, "Reflection has evaluation request",
          any(kw in prompt for kw in ["评估", "方向", "一致"]))

    # 3.8 Default when goal not set
    m4 = AgentResilienceManager()
    for i in range(5):
        m4.record_action(i, "code%d" % i, "ok", False)
    prompt2 = m4.build_reflection_prompt()
    check(r, "Default when goal not set", "未记录原始目标" in prompt2)

    # 3.9 Mixed success/failure stats
    m5 = AgentResilienceManager()
    m5.set_original_goal("测试目标")
    m5.record_action(0, "code0", "ok", False)
    m5.record_action(1, "code1", "Error: bad", True)
    m5.record_action(2, "code2", "ok", False)
    m5.record_action(3, "code3", "Error: bad2", True)
    m5.record_action(4, "code4", "ok", False)
    prompt3 = m5.build_reflection_prompt()
    check(r, "Reflection counts failures", "2 步失败" in prompt3)
    check(r, "Reflection shows pass/fail markers",
          "成功" in prompt3 and "失败" in prompt3)


# ---------------------------------------------------------------------------
# 4. Context overflow protection
# ---------------------------------------------------------------------------

def test_context_compression(r):
    r.section("4. Implicit failure - Context compression")

    m = AgentResilienceManager()

    # 4.1 Short history unchanged
    short = [
        {"role": "user", "content": "query 1"},
        {"role": "assistant", "content": "answer 1"},
        {"role": "user", "content": "query 2"},
        {"role": "assistant", "content": "answer 2"},
    ]
    result = m.summarize_history(short)
    check(r, "Short history unchanged (4 msgs)",
          len(result) == len(short),
          "got %d" % len(result))

    # 4.2 Long history compressed
    long_hist = []
    for i in range(10):
        long_hist.append({"role": "user", "content": "question %d" % i})
        long_hist.append({"role": "assistant", "content": "answer %d" % i})
    compressed = m.summarize_history(long_hist)
    check(r, "Long history compressed",
          len(compressed) < len(long_hist),
          "original=%d, compressed=%d" % (len(long_hist), len(compressed)))

    # 4.3 Summary as first message
    check(r, "First msg is summary",
          compressed[0]["content"].startswith("["))

    # 4.4 Recent assistant turns preserved
    assistant_count = sum(1 for msg in compressed if msg.get("role") == "assistant")
    check(r, "%d recent assistant msgs kept" % m.HISTORY_KEEP_RECENT,
          assistant_count == m.HISTORY_KEEP_RECENT,
          "expected %d, got %d" % (m.HISTORY_KEEP_RECENT, assistant_count))

    # 4.5 Summary captures original goal from first user message
    long_hist2 = [
        {"role": "user", "content": "帮我分析选中对象的响度"},
        {"role": "assistant", "content": "好的，正在分析"},
    ]
    for i in range(8):
        long_hist2.append({"role": "user", "content": "Output:\nresult_%d" % i})
        long_hist2.append({"role": "assistant", "content": "分析结果 %d" % i})
    comp2 = m.summarize_history(long_hist2)
    check(r, "Summary has original goal",
          "帮我分析选中对象的响度" in comp2[0]["content"])

    # 4.6 Summary captures key results
    check(r, "Summary has key outputs", "result_" in comp2[0]["content"])

    # 4.7 Empty history → empty list
    check(r, "Empty history -> empty list", m.summarize_history([]) == [])

    # 4.8 Original not modified
    original = copy.deepcopy(long_hist)
    m.summarize_history(long_hist)
    check(r, "Original history not modified", long_hist == original)

    # 4.9 Multimodal content extraction
    multimodal = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}},
        {"type": "text", "text": "describe this image"},
    ]
    text = _extract_text_from_content(multimodal)
    check(r, "Multimodal text extracted", text == "describe this image")

    # 4.10 Code blocks in assistant msg captured in summary
    long_hist3 = [
        {"role": "user", "content": "set volume to -5"},
        {"role": "assistant", "content": '```python_waapi\nwaapi_client.set_property(obj_id, "Volume", -5)\n```'},
        {"role": "user", "content": "Output:\nsuccess"},
        {"role": "assistant", "content": "done"},
    ]
    for i in range(6):
        long_hist3.append({"role": "user", "content": "q%d" % i})
        long_hist3.append({"role": "assistant", "content": "a%d" % i})
    comp3 = m.summarize_history(long_hist3)
    # The summary should mention that set_property was executed
    summary_text = comp3[0]["content"]
    check(r, "Summary has executed actions",
          "set_property" in summary_text or "已执行操作" in summary_text
          or "Volume" in summary_text)


# ---------------------------------------------------------------------------
# 5. CheckPoint mechanism
# ---------------------------------------------------------------------------

def test_checkpoint(r):
    r.section("5. CheckPoint mechanism")

    # 5.1 Save and retrieve
    m = AgentResilienceManager()
    hist = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    m.save_checkpoint(1, hist, {"obj_ids": ["id1", "id2"]})
    check(r, "Checkpoint saved", len(m.checkpoints) == 1)

    # 5.2 Latest checkpoint
    cp = m.get_latest_valid_checkpoint()
    check(r, "Latest checkpoint not None", cp is not None)
    check(r, "Checkpoint step_index correct", cp.step_index == 1)

    # 5.3 Deep copy isolation
    hist.append({"role": "user", "content": "extra"})
    check(r, "Checkpoint data isolated from source",
          len(cp.chat_history_snapshot) == 2)

    # 5.4 Rollback restores data
    restored_hist, restored_data = m.rollback_to_checkpoint(cp)
    check(r, "Rollback restores history", len(restored_hist) == 2)
    check(r, "Rollback restores intermediate results",
          restored_data.get("obj_ids") == ["id1", "id2"])

    # 5.5 Rollback returns deep copy
    restored_hist.append({"role": "user", "content": "modified"})
    cp_after = m.get_latest_valid_checkpoint()
    check(r, "Rollback result is deep copy",
          len(cp_after.chat_history_snapshot) == 2)

    # 5.6 Multiple checkpoints
    m2 = AgentResilienceManager()
    for i in range(5):
        m2.save_checkpoint(i, [{"role": "user", "content": "step %d" % i}], {"step": i})
    check(r, "Multiple checkpoints saved", len(m2.checkpoints) == 5)

    # 5.7 Rollback to middle clears later
    mid_cp = m2.checkpoints[2]
    m2.rollback_to_checkpoint(mid_cp)
    check(r, "Rollback clears later checkpoints",
          len(m2.checkpoints) == 3,
          "got %d" % len(m2.checkpoints))
    check(r, "Latest after rollback correct",
          m2.get_latest_valid_checkpoint().step_index == 2)

    # 5.8 Limit of 10 checkpoints
    m3 = AgentResilienceManager()
    for i in range(15):
        m3.save_checkpoint(i, [{"role": "user", "content": "msg %d" % i}])
    check(r, "Max 10 checkpoints", len(m3.checkpoints) == 10)
    check(r, "Oldest kept is step 5", m3.checkpoints[0].step_index == 5)
    check(r, "Newest is step 14", m3.checkpoints[-1].step_index == 14)

    # 5.9 No checkpoints → None
    m4 = AgentResilienceManager()
    check(r, "No checkpoints -> None", m4.get_latest_valid_checkpoint() is None)

    # 5.10 Rollback cleans action records
    m5 = AgentResilienceManager()
    m5.record_action(0, "code0", "ok", False)
    m5.save_checkpoint(0, [{"role": "user", "content": "step0"}])
    m5.record_action(1, "code1", "ok", False)
    m5.record_action(2, "code2", "Error", True)
    check(r, "3 actions before rollback", len(m5.actions) == 3)
    cp5 = m5.checkpoints[0]
    m5.rollback_to_checkpoint(cp5)
    check(r, "Actions cleaned to checkpoint", len(m5.actions) == 1)

    # 5.11 Timestamp present
    m6 = AgentResilienceManager()
    before = time.time()
    m6.save_checkpoint(0, [])
    after = time.time()
    cp6 = m6.get_latest_valid_checkpoint()
    check(r, "Checkpoint has valid timestamp",
          before <= cp6.timestamp <= after)


# ---------------------------------------------------------------------------
# 6. Fallback strategy
# ---------------------------------------------------------------------------

def test_fallback(r):
    r.section("6. Fallback strategy")

    # 6.1 No force stop initially
    m = AgentResilienceManager()
    check(r, "No force stop initially", not m.should_force_stop())

    # 6.2 Force stop at configured limit
    m2 = AgentResilienceManager()
    limit = m2.MAX_TOTAL_ITERATIONS
    for i in range(limit):
        m2.record_action(i, "code%d" % i, "result_%d" % i, False)
    check(r, "Force stop at configured limit", m2.should_force_stop())

    # 6.3 No force stop just before limit
    m3 = AgentResilienceManager()
    for i in range(m3.MAX_TOTAL_ITERATIONS - 1):
        m3.record_action(i, "code%d" % i, "ok", False)
    check(r, "No force stop before limit", not m3.should_force_stop())

    # 6.4 Fallback mentions limit
    fb = m2.build_fallback_response()
    check(r, "Fallback mentions limit", str(limit) in fb)

    # 6.5 Fallback counts successes
    check(r, "Fallback counts successes", "%d 步成功" % limit in fb)

    # 6.6 Fallback includes collected data
    check(r, "Fallback includes collected data", "result_" in fb)

    # 6.7 With failures: includes last error
    m4 = AgentResilienceManager()
    for i in range(18):
        m4.record_action(i, "code%d" % i, "ok", False)
    m4.record_action(18, "bad_code", "Error: something went wrong here", True)
    m4.record_action(19, "fix_code", "ok", False)
    fb4 = m4.build_fallback_response()
    check(r, "Fallback includes last error", "something went wrong" in fb4)
    check(r, "Fallback requests analysis",
          any(kw in fb4 for kw in ["分析", "说明", "情况"]))

    # 6.8 All failures
    m5 = AgentResilienceManager()
    for i in range(20):
        m5.record_action(i, "code%d" % i, "Error: fail_%d" % i, True)
    fb5 = m5.build_fallback_response()
    check(r, "All-fail fallback has errors", "fail_" in fb5)
    check(r, "All-fail counts 0 successes", "0 步成功" in fb5)

    # 6.9 No useful output
    m6 = AgentResilienceManager()
    for i in range(20):
        m6.record_action(i, "code%d" % i, "Execution completed with no output.", False)
    fb6 = m6.build_fallback_response()
    check(r, "No-output fallback states it",
          "未获取到有效数据" in fb6)


# ---------------------------------------------------------------------------
# 7. Tool signature extraction
# ---------------------------------------------------------------------------

def test_tool_signatures(r):
    r.section("7. Tool signature extraction")

    # 7.1 waapi_client.call sig
    sig1 = _compute_tool_signature(
        'waapi_client.call("ak.wwise.core.object.get", {"from": {"ofType": ["Sound"]}})')
    check(r, "waapi_client.call sig non-empty", sig1 != "")

    # 7.2 Same call → same sig
    sig2 = _compute_tool_signature(
        'waapi_client.call("ak.wwise.core.object.get", {"from": {"ofType": ["Sound"]}})')
    check(r, "Same call -> same sig", sig1 == sig2)

    # 7.3 Different URI → different sig
    sig3 = _compute_tool_signature(
        'waapi_client.call("ak.wwise.core.object.set", {"from": {"ofType": ["Sound"]}})')
    check(r, "Different URI -> different sig", sig1 != sig3)

    # 7.4 Tool function sig
    sig4 = _compute_tool_signature('analyze_audio_file("/path/to/file.wav")')
    sig5 = _compute_tool_signature('analyze_audio_file("/path/to/other.wav")')
    check(r, "Tool func sig extracted", sig4 != "")
    check(r, "Different args -> different sig", sig4 != sig5)

    # 7.5 Empty code → empty sig
    check(r, "Empty code -> empty sig", _compute_tool_signature("") == "")

    # 7.6 No-tool code uses md5 fallback
    sig6 = _compute_tool_signature("x = 1 + 2\nprint(x)")
    check(r, "No-tool code uses md5 fallback",
          sig6 != "" and len(sig6) == 12)

    # 7.7 Multi-tool code
    multi_code = (
        'result = waapi_client.call("ak.wwise.core.object.get", args)\n'
        'paths = get_selected_source_files()\n'
        'info = analyze_audio_file(paths[0])\n'
    )
    sig7 = _compute_tool_signature(multi_code)
    check(r, "Multi-tool code sig extracted", sig7 != "")

    # 7.8 Whitespace normalization
    code_a = 'waapi_client.call("get",   {"a":  1})'
    code_b = 'waapi_client.call("get", {"a": 1})'
    sig_a = _compute_tool_signature(code_a)
    sig_b = _compute_tool_signature(code_b)
    check(r, "Whitespace doesn't affect sig", sig_a == sig_b)

    # 7.9 get_property recognized
    sig_gp = _compute_tool_signature('waapi_client.get_property(obj_id, "Volume")')
    check(r, "get_property sig extracted", sig_gp != "")

    # 7.10 get_selected_objects recognized
    sig_so = _compute_tool_signature('selected = waapi_client.get_selected_objects()')
    check(r, "get_selected_objects sig extracted", sig_so != "")

    # 7.11 Long args truncated
    long_args = "a" * 500
    normalized = _normalize_args(long_args)
    check(r, "Long args truncated to 200", len(normalized) <= 200)


# ---------------------------------------------------------------------------
# 8. pre_turn_check unified entry
# ---------------------------------------------------------------------------

def test_pre_turn_check(r):
    r.section("8. pre_turn_check unified entry")

    # 8.1 Initial → continue
    m = AgentResilienceManager()
    result = m.pre_turn_check()
    check(r, "Initial -> continue", result["action"] == "continue")
    check(r, "Initial -> allow", result["allow"] is True)

    # 8.2 At limit → force_stop
    m2 = AgentResilienceManager()
    for i in range(m2.MAX_TOTAL_ITERATIONS):
        m2.record_action(i, "code%d" % i, "ok", False)
    result2 = m2.pre_turn_check()
    check(r, "At limit -> force_stop", result2["action"] == "force_stop")
    check(r, "At limit -> not allowed", result2["allow"] is False)
    check(r, "Force stop msg non-empty", len(result2["message"]) > 50)

    # 8.3 Loop → loop_detected
    m3 = AgentResilienceManager()
    same = 'get_selected_source_files()'
    for i in range(m3.LOOP_DETECT_WINDOW):
        m3.record_action(i, same, "ok", False)
    result3 = m3.pre_turn_check()
    check(r, "Loop -> loop_detected", result3["action"] == "loop_detected")
    check(r, "Loop -> still allowed", result3["allow"] is True)

    # 8.4 Step 5 → reflect
    m4 = AgentResilienceManager()
    m4.set_original_goal("test goal")
    for i in range(5):
        m4.record_action(i, "unique_%d" % i, "ok", False)
    result4 = m4.pre_turn_check()
    check(r, "Step 5 -> reflect", result4["action"] == "reflect")
    check(r, "Reflect msg has goal", "test goal" in result4["message"])

    # 8.5 Priority: force_stop > loop > reflect
    m5 = AgentResilienceManager()
    same5 = 'get_selected_source_files()'
    for i in range(m5.MAX_TOTAL_ITERATIONS):
        m5.record_action(i, same5, "ok", False)
    result5 = m5.pre_turn_check()
    check(r, "force_stop > loop > reflect", result5["action"] == "force_stop")


# ---------------------------------------------------------------------------
# 9. Data structures & reset
# ---------------------------------------------------------------------------

def test_data_structures(r):
    r.section("9. Data structures & reset")

    # 9.1 ActionRecord defaults
    ar = ActionRecord(step_index=0, code="test", output="ok", has_error=False)
    check(r, "ActionRecord default sig empty", ar.tool_signature == "")
    check(r, "ActionRecord has timestamp", ar.timestamp > 0)

    # 9.2 CheckPoint defaults
    cp = CheckPoint(step_index=0)
    check(r, "CheckPoint default history empty", cp.chat_history_snapshot == [])
    check(r, "CheckPoint default results empty", cp.intermediate_results == {})
    check(r, "CheckPoint has timestamp", cp.timestamp > 0)

    # 9.3 Reset clears everything
    m = AgentResilienceManager()
    m.record_action(0, "code", "ok", False)
    m.save_checkpoint(0, [{"role": "user", "content": "test"}])
    m.set_original_goal("goal")
    m.reset()
    check(r, "Reset clears actions", len(m.actions) == 0)
    check(r, "Reset clears checkpoints", len(m.checkpoints) == 0)
    check(r, "Reset clears iterations", m.total_iterations == 0)
    check(r, "Reset clears error count", m._consecutive_error_count == 0)
    check(r, "Reset clears error sig", m._last_error_signature == "")
    check(r, "Reset clears goal", m._original_goal == "")

    # 9.4 _is_system_generated
    isg = AgentResilienceManager._is_system_generated
    check(r, "Output: is system msg", isg("Output:\ndata"))
    check(r, "Step completion is system msg", isg("分步执行完成:\ndata"))
    check(r, "User revoked is system msg", isg("User revoked the operation."))
    check(r, "[System is system msg", isg("[System] warning"))
    check(r, "Normal text is not system msg", not isg("帮我修改音量"))


# ---------------------------------------------------------------------------
# 10. End-to-end scenario simulation
# ---------------------------------------------------------------------------

def test_e2e_scenarios(r):
    r.section("10. End-to-end scenarios")

    # Scenario A: Normal 3-step success
    m = AgentResilienceManager()
    m.set_original_goal("查询所有 Sound 对象并分析响度")
    chat = [{"role": "user", "content": "查询所有 Sound 对象并分析响度"}]
    m.record_action(0,
        'waapi_client.call("ak.wwise.core.object.get", {"from": {"ofType": ["Sound"]}})',
        '{"return": [...]}', False)
    m.save_checkpoint(0, chat)
    pre = m.pre_turn_check()
    check(r, "A-step1: continue", pre["action"] == "continue")
    m.record_action(1, 'get_selected_source_files()', '[{"path": "..."}]', False)
    m.save_checkpoint(1, chat)
    m.record_action(2, 'analyze_audio_file("/path/to/file.wav")', '{"lufs_i": -16}', False)
    m.save_checkpoint(2, chat)
    check(r, "A: 3 steps success", m.total_iterations == 3)
    check(r, "A: 3 checkpoints", len(m.checkpoints) == 3)
    check(r, "A: no loop", not m.detect_loop())

    # Scenario B: Step 2 fails, retry succeeds
    m2 = AgentResilienceManager()
    m2.set_original_goal("设置音量")
    m2.record_action(0, 'waapi_client.call("get", {})', '{"return": [{"id":"x"}]}', False)
    m2.save_checkpoint(0, [{"role": "user", "content": "设置音量"}])
    m2.record_action(1,
        'waapi_client.set_property("x", "Volme", -5)',
        'Error: unknown property Volme', True)
    check(r, "B: first error retryable",
          m2.should_retry_error("Error: unknown property Volme"))
    fb = m2.format_error_feedback("Error: unknown property Volme")
    check(r, "B: feedback has error detail", "Volme" in fb)
    m2.record_action(2, 'waapi_client.set_property("x", "Volume", -5)', "success", False)
    check(r, "B: error count reset after fix", m2._consecutive_error_count == 0)

    # Scenario C: 3x same error → stop
    m3 = AgentResilienceManager()
    bad_code = 'waapi_client.call("ak.wwise.core.object.delete", {"object": "bad-id"})'
    for i in range(3):
        m3.record_action(i, bad_code, "Error: object not found", True)
    check(r, "C: stop after 3 same errors",
          not m3.should_retry_error("Error: object not found"))
    check(r, "C: retry limit does not require loop", not m3.detect_loop())

    # Scenario D: Loop → interrupt → switch approach
    m4 = AgentResilienceManager()
    loop_code = 'get_selected_source_files()'
    for i in range(m4.LOOP_DETECT_WINDOW):
        m4.record_action(i, loop_code, "[]", False)
    pre4 = m4.pre_turn_check()
    check(r, "D: loop detected", pre4["action"] == "loop_detected")
    for offset in range(5):
        m4.record_action(m4.LOOP_DETECT_WINDOW + offset,
            'waapi_client.call("ak.wwise.core.object.get", {"from": {"ofType": ["Sound"], "index": %d}})' % offset,
            '{"return": [...]}', False)
    check(r, "D: no loop after switching approach", not m4.detect_loop())

    # Scenario E: Checkpoint rollback
    m5 = AgentResilienceManager()
    chat5 = [{"role": "user", "content": "批量处理"}]
    m5.record_action(0, "step0_code", "ok_step0", False)
    m5.save_checkpoint(0, chat5, {"items": [1, 2, 3]})
    m5.record_action(1, "step1_code", "ok_step1", False)
    m5.save_checkpoint(1, chat5, {"items": [1, 2, 3], "processed": 1})
    m5.record_action(2, "step2_bad", "Error: crash", True)
    cp5 = m5.checkpoints[-1]
    restored, data = m5.rollback_to_checkpoint(cp5)
    check(r, "E: rollback restores data", data.get("processed") == 1)
    check(r, "E: actions cleaned", len(m5.actions) <= 2)

    # Scenario F: Reach configured limit → fallback
    m6 = AgentResilienceManager()
    for i in range(m6.MAX_TOTAL_ITERATIONS - 2):
        m6.record_action(i, "code_%d" % i, "data_%d" % i, False)
    m6.record_action(m6.MAX_TOTAL_ITERATIONS - 2, "code_error", "Error: timeout", True)
    m6.record_action(m6.MAX_TOTAL_ITERATIONS - 1, "code_final", "data_final", False)
    pre6 = m6.pre_turn_check()
    check(r, "F: force stop at configured limit", pre6["action"] == "force_stop")
    check(r, "F: fallback has data", "data_" in pre6["message"])

    # Scenario G: Context compression works
    m7 = AgentResilienceManager()
    long_chat = [{"role": "user", "content": "帮我完成复杂的多步任务"}]
    for i in range(12):
        long_chat.append({"role": "assistant", "content": "```python_waapi\nstep_%d_code\n```" % i})
        long_chat.append({"role": "user", "content": "Output:\nresult_%d" % i})
    compressed = m7.summarize_history(long_chat)
    check(r, "G: 12-turn history compressed",
          len(compressed) < len(long_chat),
          "original=%d, compressed=%d" % (len(long_chat), len(compressed)))
    recent_assistant = [msg for msg in compressed if msg.get("role") == "assistant"]
    check(r, "G: recent configured turns kept",
          len(recent_assistant) == m7.HISTORY_KEEP_RECENT,
          "expected %d, got %d" % (m7.HISTORY_KEEP_RECENT, len(recent_assistant)))


# ---------------------------------------------------------------------------
# 11. Edge cases and robustness
# ---------------------------------------------------------------------------

def test_edge_cases(r):
    r.section("11. Edge cases and robustness")

    # 11.1 None inputs
    m = AgentResilienceManager()
    m.set_original_goal(None)
    check(r, "None goal handled", m._original_goal == "")
    m.record_action(0, None, None, False)
    check(r, "None code/output handled", m.total_iterations == 1)
    fb = m.format_error_feedback(None)
    check(r, "None error feedback handled", isinstance(fb, str))

    # 11.2 Empty strings
    m2 = AgentResilienceManager()
    m2.record_action(0, "", "", False)
    check(r, "Empty strings handled", m2.total_iterations == 1)
    sig = _compute_tool_signature("")
    check(r, "Empty code -> empty sig", sig == "")

    # 11.3 Unicode content
    m3 = AgentResilienceManager()
    m3.set_original_goal("修改中文名称的对象")
    m3.record_action(0,
        'waapi_client.call("get", {"name": "音效_爆炸"})',
        "结果: 成功", False)
    for i in range(1, 5):
        m3.record_action(i, "code_%d" % i, "ok", False)
    prompt = m3.build_reflection_prompt()
    check(r, "Unicode goal preserved", "中文名称" in prompt)

    # 11.4 Very long code
    long_code = 'waapi_client.call("get", {"data": "' + "x" * 10000 + '"})'
    sig_long = _compute_tool_signature(long_code)
    check(r, "Long code sig extracted",
          isinstance(sig_long, str) and len(sig_long) > 0)

    # 11.5 Many actions (100)
    m4 = AgentResilienceManager()
    for i in range(100):
        m4.record_action(i, "code_%d" % i, "output_%d" % i, i % 7 == 0)
    check(r, "100 actions handled", m4.total_iterations == 100)
    fb4 = m4.build_fallback_response()
    check(r, "100-action fallback ok", isinstance(fb4, str) and len(fb4) > 0)

    # 11.6 Rapid save/rollback cycles
    m5 = AgentResilienceManager()
    for i in range(5):
        m5.save_checkpoint(i, [{"role": "user", "content": "msg_%d" % i}])
    for _ in range(3):
        cp = m5.get_latest_valid_checkpoint()
        if cp:
            m5.rollback_to_checkpoint(cp)
    check(r, "Rapid rollback stable", len(m5.checkpoints) >= 1)

    # 11.7 User-only history
    m6 = AgentResilienceManager()
    user_only = [{"role": "user", "content": "msg_%d" % i} for i in range(10)]
    result = m6.summarize_history(user_only)
    check(r, "User-only history handled", isinstance(result, list))

    # 11.8 Assistant-only history
    assist_only = [{"role": "assistant", "content": "reply_%d" % i} for i in range(10)]
    result2 = m6.summarize_history(assist_only)
    check(r, "Assistant-only history handled", isinstance(result2, list))

    # 11.9 Mixed with system messages
    mixed = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    result3 = m6.summarize_history(mixed)
    check(r, "System msg in history handled", isinstance(result3, list))

    # 11.10 _extract_text_from_content edge cases
    check(r, "extract None -> empty", _extract_text_from_content(None) == "")
    check(r, "extract int -> str", _extract_text_from_content(42) == "42")
    check(r, "extract str -> identity", _extract_text_from_content("hello") == "hello")
    check(r, "extract empty list -> default", _extract_text_from_content([], "d") == "d")


# ---------------------------------------------------------------------------
# 12. Performance / stress tests
# ---------------------------------------------------------------------------

def test_performance(r):
    r.section("12. Performance / stress tests")

    # 12.1 Loop detection perf
    m = AgentResilienceManager()
    start = time.time()
    for i in range(500):
        m.record_action(i, 'waapi_client.call("func_%d", {})' % (i % 50), "ok", False)
    for _ in range(100):
        m.detect_loop()
    elapsed = time.time() - start
    check(r, "500 records + 100 detects < 1s (%.3fs)" % elapsed,
          elapsed < 1.0)

    # 12.2 Large history compression
    m2 = AgentResilienceManager()
    big_history = []
    for i in range(200):
        big_history.append({"role": "user", "content": "question %d %s" % (i, "x" * 100)})
        big_history.append({"role": "assistant", "content": "answer %d %s" % (i, "y" * 200)})
    start = time.time()
    compressed = m2.summarize_history(big_history)
    elapsed_compress = time.time() - start
    check(r, "200-turn compression < 0.5s (%.3fs)" % elapsed_compress,
          elapsed_compress < 0.5)
    check(r, "Large history actually compressed",
          len(compressed) < len(big_history))

    # 12.3 Checkpoint perf
    m3 = AgentResilienceManager()
    start = time.time()
    for i in range(50):
        m3.save_checkpoint(i, [{"role": "user", "content": "msg_%d %s" % (i, "z" * 500)}])
    elapsed_cp = time.time() - start
    check(r, "50 checkpoints < 0.5s (%.3fs)" % elapsed_cp,
          elapsed_cp < 0.5)
    check(r, "Checkpoint limit enforced", len(m3.checkpoints) == 10)

    # 12.4 Signature extraction perf
    codes = ['waapi_client.call("func_%d", {"arg": %d})' % (i, i) for i in range(100)]
    start = time.time()
    sigs = [_compute_tool_signature(c) for c in codes]
    elapsed_sig = time.time() - start
    check(r, "100 sig extractions < 0.1s (%.3fs)" % elapsed_sig,
          elapsed_sig < 0.1)
    check(r, "100 unique sigs",
          len(set(sigs)) == 100,
          "got %d" % len(set(sigs)))


# ---------------------------------------------------------------------------
# 13. Error classification tests
# ---------------------------------------------------------------------------

def test_error_classification(r):
    r.section("13. Error classification")

    # CONNECTION_ERROR
    check(r, "WampConnectionError -> CONNECTION",
          classify_error("WampConnectionError: connection closed") == ErrorCategory.CONNECTION_ERROR)
    check(r, "ConnectionRefusedError -> CONNECTION",
          classify_error("ConnectionRefusedError: target refused") == ErrorCategory.CONNECTION_ERROR)
    check(r, "TimeoutError -> CONNECTION",
          classify_error("TimeoutError: request timed out") == ErrorCategory.CONNECTION_ERROR)

    # PERMISSION_ERROR
    check(r, "ImportError -> PERMISSION",
          classify_error("ImportError: No module named 'numpy'") == ErrorCategory.PERMISSION_ERROR)
    check(r, "Import not allowed -> PERMISSION",
          classify_error("ImportError: Import 'subprocess' is not allowed in Agent Mode.") == ErrorCategory.PERMISSION_ERROR)

    # API_ERROR
    check(r, "invalid_arguments -> API",
          classify_error("invalid_arguments: Property doesn't exist on the object.") == ErrorCategory.API_ERROR)
    check(r, "unknown property -> API",
          classify_error("Error: unknown property 'Volume2'") == ErrorCategory.API_ERROR)
    check(r, "from path cannot be resolved -> API",
          classify_error("ApplicationError: from path cannot be resolved") == ErrorCategory.API_ERROR)
    check(r, "unknown object -> API",
          classify_error("Object \\Master-Mixer Hierarchy\\Default Work Unit\\Master Audio Bus is unknown.") == ErrorCategory.API_ERROR)

    # SHAPE_ERROR
    check(r, "KeyError -> SHAPE",
          classify_error("KeyError: 'type'") == ErrorCategory.SHAPE_ERROR)
    check(r, "AttributeError .get -> SHAPE",
          classify_error("AttributeError: 'str' object has no attribute 'get'") == ErrorCategory.SHAPE_ERROR)
    check(r, "TypeError subscriptable -> SHAPE",
          classify_error("TypeError: 'NoneType' object is not subscriptable") == ErrorCategory.SHAPE_ERROR)

    # LOGIC_ERROR
    check(r, "ValueError -> LOGIC",
          classify_error("ValueError: invalid data range") == ErrorCategory.LOGIC_ERROR)
    check(r, "ZeroDivisionError -> LOGIC",
          classify_error("ZeroDivisionError: division by zero") == ErrorCategory.LOGIC_ERROR)

    # UNKNOWN
    check(r, "Unknown error -> UNKNOWN",
          classify_error("Something went wrong") == ErrorCategory.UNKNOWN)
    check(r, "Empty output -> UNKNOWN",
          classify_error("") == ErrorCategory.UNKNOWN)

    # Non-retryable behavior
    m = AgentResilienceManager()
    m.record_action(0, "code", "WampConnectionError: closed", True)
    check(r, "CONNECTION not retryable",
          not m.should_retry_error("WampConnectionError: closed"))

    m2 = AgentResilienceManager()
    m2.record_action(0, "code", "ImportError: not allowed", True)
    check(r, "PERMISSION not retryable",
          not m2.should_retry_error("ImportError: not allowed"))

    m3 = AgentResilienceManager()
    m3.record_action(0, "code", "KeyError: 'type'", True)
    check(r, "SHAPE is retryable",
          m3.should_retry_error("KeyError: 'type'"))

    m4 = AgentResilienceManager()
    m4.record_action(0, 'waapi_client.call("ak.wwise.core.object.create", {})',
                     "Object \\Master-Mixer Hierarchy\\Default Work Unit\\Master Audio Bus is unknown.", True)
    feedback = m4.format_error_feedback(
        "Object \\Master-Mixer Hierarchy\\Default Work Unit\\Master Audio Bus is unknown."
    )
    check(r, "Path retry guidance present",
          "不要继续复用同一条硬编码路径" in feedback)


# ---------------------------------------------------------------------------
# 14. Smart truncation tests
# ---------------------------------------------------------------------------

def test_smart_truncation(r):
    r.section("14. Smart truncation")

    # Short text unchanged
    short = "Error: something"
    check(r, "Short text unchanged", smart_truncate(short) == short)

    # Long text preserves head + tail
    long_text = "HEAD " + "x" * 5000 + " TAIL"
    result = smart_truncate(long_text, 2000)
    check(r, "Head preserved", result.startswith("HEAD"))
    check(r, "Tail preserved", result.endswith("TAIL"))
    check(r, "Truncation marker present", "chars truncated" in result)
    check(r, "Result within limit", len(result) <= 2100)  # head + marker + tail

    # Empty input
    check(r, "Empty input -> empty", smart_truncate("") == "")
    check(r, "None input -> empty", smart_truncate(None) == "")


# ---------------------------------------------------------------------------
# 15. WAAPI call extraction tests
# ---------------------------------------------------------------------------

def test_waapi_extraction(r):
    r.section("15. WAAPI call extraction & action summary")

    # Basic URI extraction
    code = """result = waapi_client.call('ak.wwise.core.object.get', args)"""
    uris = _extract_waapi_calls(code)
    check(r, "Extracted URI", "ak.wwise.core.object.get" in uris)

    # Multiple URIs
    code2 = """
waapi_client.call('ak.wwise.core.object.get', args)
waapi_client.call('ak.wwise.core.object.setProperty', args2)
"""
    uris2 = _extract_waapi_calls(code2)
    check(r, "Multiple URIs extracted", len(uris2) == 2)
    check(r, "setProperty -> write URI", _is_write_uri("ak.wwise.core.object.setProperty"))
    check(r, "get -> not write URI", not _is_write_uri("ak.wwise.core.object.get"))

    # Create -> write
    check(r, "create -> write URI", _is_write_uri("ak.wwise.core.object.create"))
    check(r, "delete -> write URI", _is_write_uri("ak.wwise.core.object.delete"))

    # Empty code
    check(r, "Empty code -> no URIs", _extract_waapi_calls("") == [])

    # Action summary
    m = AgentResilienceManager()
    m.record_action(0, "waapi_client.call('ak.wwise.core.object.get', args)", "output1", False)
    m.record_action(1, "waapi_client.call('ak.wwise.core.object.setProperty', args)", "output2", False)
    m.record_action(2, "bad code", "Error: something", True)
    summary = m.build_action_summary()
    check(r, "Summary contains step count", "3 step" in summary)
    check(r, "Summary contains success count", "2 succeeded" in summary)
    check(r, "Summary contains failure count", "1 failed" in summary)
    check(r, "Summary contains WRITE flag", "[WRITE]" in summary)

    # Empty action summary
    m_empty = AgentResilienceManager()
    check(r, "Empty actions -> empty summary", m_empty.build_action_summary() == "")

    # Non-retryable message
    m4 = AgentResilienceManager()
    msg_conn = m4.get_non_retryable_message("WampConnectionError: connection refused")
    check(r, "Non-retryable connection msg", "连接错误" in msg_conn)
    msg_perm = m4.get_non_retryable_message("ImportError: not allowed")
    check(r, "Non-retryable permission msg", "权限" in msg_perm)


# ---------------------------------------------------------------------------
# 16. Category-specific error feedback tests
# ---------------------------------------------------------------------------

def test_category_feedback(r):
    r.section("16. Category-specific error feedback")

    m = AgentResilienceManager()
    m.record_action(0, "code", "KeyError: 'type'", True)

    # SHAPE_ERROR feedback
    fb = m.format_error_feedback("KeyError: 'type'")
    check(r, "SHAPE feedback has lookup hint", "lookup_waapi_doc" in fb)
    check(r, "SHAPE feedback has .get() hint", ".get(" in fb)

    # API_ERROR feedback
    m2 = AgentResilienceManager()
    m2.record_action(0, "code", "invalid_arguments: bad param", True)
    fb2 = m2.format_error_feedback("invalid_arguments: bad param")
    check(r, "API feedback has doc hint", "lookup_waapi_doc" in fb2)
    check(r, "API feedback mentions args", "args" in fb2 or "参数" in fb2)
    check(r, "API feedback mentions options placement", "options" in fb2)

    m_schema = AgentResilienceManager()
    m_schema.record_action(0, "code", "schema_validation_failed: schemaKeyword oneOf", True)
    check(r, "Schema error classified as API", classify_error("schema_validation_failed: schemaKeyword oneOf") == ErrorCategory.API_ERROR)
    check(r, "Retry budget reduced", m_schema.MAX_ERROR_RETRIES == 3)

    # LOGIC_ERROR feedback
    m3 = AgentResilienceManager()
    m3.record_action(0, "code", "ValueError: invalid", True)
    fb3 = m3.format_error_feedback("ValueError: invalid")
    check(r, "LOGIC feedback has basic instructions", "修正" in fb3 or "分析" in fb3)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    r = TestResult()
    print("\n" + "=" * 60)
    print("  Agent Resilience Module - Comprehensive Test Suite")
    print("=" * 60)

    tests = [
        test_explicit_failure,
        test_loop_detection,
        test_self_reflection,
        test_context_compression,
        test_checkpoint,
        test_fallback,
        test_tool_signatures,
        test_pre_turn_check,
        test_data_structures,
        test_e2e_scenarios,
        test_edge_cases,
        test_performance,
        test_error_classification,
        test_smart_truncation,
        test_waapi_extraction,
        test_category_feedback,
    ]

    for test_fn in tests:
        try:
            test_fn(r)
        except Exception:
            r.fail("%s CRASHED" % test_fn.__name__, traceback.format_exc())

    all_pass = r.summary()
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())

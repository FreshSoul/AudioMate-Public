"""Quick integration tests for AgentResilienceManager."""
import sys
import importlib.util

# Direct import (bypass llm __init__ which needs openai)
spec = importlib.util.spec_from_file_location("agent_resilience", "src/llm/agent_resilience.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["agent_resilience"] = mod
spec.loader.exec_module(mod)

ARM = mod.AgentResilienceManager

# Test 1: Basic lifecycle
m = ARM()
m.set_original_goal("Test goal")
assert m._original_goal == "Test goal"
assert m.total_iterations == 0
assert not m.should_force_stop()
print("Test 1 PASS: basic lifecycle")

# Test 2: Record actions and error retry
for attempt in range(1, ARM.MAX_ERROR_RETRIES):
    m.record_action(attempt, 'waapi_client.call("ak.wwise.core.object.get", {})', "Error: unknown", True)
    assert m._consecutive_error_count == attempt
    assert m.should_retry_error("Error: unknown")
m.record_action(ARM.MAX_ERROR_RETRIES, 'waapi_client.call("ak.wwise.core.object.get", {})', "Error: unknown", True)
assert m._consecutive_error_count == ARM.MAX_ERROR_RETRIES
assert not m.should_retry_error("Error: unknown")
print("Test 2 PASS: error retry limit works")

# Test 3: Error counter resets on success
m2 = ARM()
m2.record_action(1, "code1", "Error x", True)
assert m2._consecutive_error_count == 1
m2.record_action(2, "code2", "ok", False)
assert m2._consecutive_error_count == 0
print("Test 3 PASS: error counter resets on success")

# Test 4: Loop detection
m3 = ARM()
same_code = 'waapi_client.call("ak.wwise.core.object.get", {"from": {"ofType": ["Sound"]}})'
for i in range(ARM.LOOP_DETECT_WINDOW):
    m3.record_action(i + 1, same_code, "ok", False)
assert m3.detect_loop(), "Should detect loop with identical signatures"
print("Test 4 PASS: loop detection works")

# Test 5: No loop with different calls
m4 = ARM()
m4.record_action(1, 'waapi_client.call("get", {})', "ok", False)
m4.record_action(2, 'waapi_client.call("set", {})', "ok", False)
m4.record_action(3, 'waapi_client.call("create", {})', "ok", False)
assert not m4.detect_loop(), "Should not detect loop with different signatures"
print("Test 5 PASS: no false loop detection")

# Test 6: Self-reflection
m5 = ARM()
for i in range(5):
    m5.record_action(i, f"code{i}", "ok", False)
assert m5.should_self_reflect()  # total_iterations=5, 5%5==0
m5.record_action(5, "code5", "ok", False)
assert not m5.should_self_reflect()  # total_iterations=6, 6%5!=0
print("Test 6 PASS: self-reflection timing works")

# Test 7: Force stop
m6 = ARM()
for i in range(ARM.MAX_TOTAL_ITERATIONS):
    m6.record_action(i, f"code{i}", "ok", False)
assert m6.should_force_stop()
print(f"Test 7 PASS: force stop at {ARM.MAX_TOTAL_ITERATIONS}")

# Test 8: Checkpoint save/rollback
m7 = ARM()
history = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
m7.save_checkpoint(1, history, {"key": "value"})
cp = m7.get_latest_valid_checkpoint()
assert cp is not None
restored_hist, restored_data = m7.rollback_to_checkpoint(cp)
assert len(restored_hist) == 2
assert restored_data.get("key") == "value"
print("Test 8 PASS: checkpoint save/rollback works")

# Test 9: History summarization
m8 = ARM()
long_history = []
for i in range(12):
    long_history.append({"role": "user", "content": f"question {i}"})
    long_history.append({"role": "assistant", "content": f"answer {i}"})
compressed = m8.summarize_history(long_history)
assert len(compressed) < len(long_history), f"Expected compression: {len(compressed)} < {len(long_history)}"
assert compressed[0]["content"].startswith("["), f"First msg should be summary: {compressed[0]['content'][:50]}"
print(f"Test 9 PASS: history compressed from {len(long_history)} to {len(compressed)} messages")

# Test 10: Pre-turn check
m9 = ARM()
result = m9.pre_turn_check()
assert result["allow"] is True
assert result["action"] == "continue"
print("Test 10 PASS: pre_turn_check works")

# Test 11: Error feedback format
m10 = ARM()
m10.record_action(1, "code", "Error: something broke", True)
feedback = m10.format_error_feedback("Error: something broke")
assert f"1/{ARM.MAX_ERROR_RETRIES}" in feedback
assert "something broke" in feedback
print("Test 11 PASS: error feedback formatting works")

# Test 12: Fallback response
m11 = ARM()
m11.record_action(1, "code1", "data: [1,2,3]", False)
m11.record_action(2, "code2", "Error: failed", True)
for i in range(ARM.MAX_TOTAL_ITERATIONS - 2):
    m11.record_action(i + 3, f"code{i+3}", "ok", False)
fb = m11.build_fallback_response()
assert str(ARM.MAX_TOTAL_ITERATIONS) in fb
print("Test 12 PASS: fallback response works")

# Test 13: Tool signature extraction
sig1 = mod._compute_tool_signature('analyze_audio_file("/path/to/file.wav")')
sig2 = mod._compute_tool_signature('analyze_audio_file("/path/to/file.wav")')
sig3 = mod._compute_tool_signature('analyze_audio_file("/path/to/other.wav")')
assert sig1 == sig2, "Same calls should have same signature"
assert sig1 != sig3, "Different args should have different signatures"
print("Test 13 PASS: tool signature extraction works")

# Test 14: Pre-turn check with force stop
m12 = ARM()
for i in range(ARM.MAX_TOTAL_ITERATIONS):
    m12.record_action(i, f"code{i}", "ok", False)
result = m12.pre_turn_check()
assert result["allow"] is False
assert result["action"] == "force_stop"
assert str(ARM.MAX_TOTAL_ITERATIONS) in result["message"]
print("Test 14 PASS: pre_turn_check force stop works")

# Test 15: Pre-turn check with loop detection
m13 = ARM()
same_code2 = 'get_selected_source_files()'
for i in range(ARM.LOOP_DETECT_WINDOW):
    m13.record_action(i + 1, same_code2, "ok", False)
result = m13.pre_turn_check()
assert result["allow"] is True
assert result["action"] == "loop_detected"
print("Test 15 PASS: pre_turn_check loop detection works")

# Test 16: Pre-turn check with reflection
m14 = ARM()
for i in range(5):
    m14.record_action(i, f"unique_code_{i}", "ok", False)
result = m14.pre_turn_check()
assert result["action"] == "reflect"
assert "原始用户目标" in result["message"]
print("Test 16 PASS: pre_turn_check self-reflection works")

# Test 17: Checkpoint limit (max 10)
m15 = ARM()
for i in range(15):
    m15.save_checkpoint(i, [{"role": "user", "content": f"msg {i}"}])
assert len(m15.checkpoints) == 10
assert m15.checkpoints[0].step_index == 5  # oldest should be step 5
print("Test 17 PASS: checkpoint limit enforced")

# Test 18: Reflection prompt content
m16 = ARM()
m16.set_original_goal("修改所有 Sound 对象的音量")
m16.record_action(1, "waapi_client.call('get', {})", "items found", False)
m16.record_action(2, "waapi_client.call('set', {})", "Error: failed", True)
prompt = m16.build_reflection_prompt()
assert "修改所有 Sound 对象的音量" in prompt
assert "1 步成功" in prompt
assert "1 步失败" in prompt
print("Test 18 PASS: reflection prompt content correct")

# Test 19: History summarization preserves short history
m17 = ARM()
short_history = [
    {"role": "user", "content": "q1"},
    {"role": "assistant", "content": "a1"},
]
result = m17.summarize_history(short_history)
assert len(result) == len(short_history), "Short history should not be compressed"
print("Test 19 PASS: short history preserved")

# Test 20: Reset clears everything
m18 = ARM()
m18.record_action(1, "code", "ok", False)
m18.save_checkpoint(1, [{"role": "user", "content": "test"}])
m18.set_original_goal("goal")
m18.reset()
assert m18.total_iterations == 0
assert len(m18.actions) == 0
assert len(m18.checkpoints) == 0
assert m18._original_goal == ""
print("Test 20 PASS: reset clears all state")

print()
print("ALL 20 TESTS PASSED")

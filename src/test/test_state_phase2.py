"""Quick smoke-test for Phase 2 state management."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

from src.state import AgentState, StateStore

# --- AgentState basics ---
s = AgentState()
assert s.chat_history == []
assert s.current_chat_id is None
assert s.recursion_depth == 0
assert s.max_auto_turns == 80
assert s.streaming_response == ""
assert s.step_code_blocks == []
print("AgentState defaults: OK")

s.new_session()
assert s.current_chat_id is not None
assert s.chat_history == []
assert s.current_chat_title == "New Chat"
print("new_session: OK")

s.recursion_depth = 5
s.reset_turn()
assert s.recursion_depth == 0
print("reset_turn: OK")

s.streaming_response = "hello"
s.thinking_phase = True
s.reset_streaming()
assert s.streaming_response == ""
assert s.thinking_phase is False
print("reset_streaming: OK")

s.step_code_blocks = ["a", "b"]
s.step_index = 1
s.reset_step_execution()
assert s.step_code_blocks == []
assert s.step_index == 0
print("reset_step_execution: OK")

# --- StateStore ---
store = StateStore()
received = []
store.state_changed.connect(lambda key: received.append(key))

store.update(lambda st: setattr(st, 'recursion_depth', 3), key="turn")
assert store.get_state().recursion_depth == 3
assert received[-1] == "turn"

store.new_session()
assert store.get_state().chat_history == []
assert received[-1] == "session"

store.reset_streaming()
assert received[-1] == "streaming"

new_state = AgentState()
new_state.current_chat_title = "Test"
store.set_state(new_state, key="reset")
assert store.get_state().current_chat_title == "Test"
assert received[-1] == "reset"
print("StateStore signals: OK")

print("\n=== All Phase 2 tests passed ===")

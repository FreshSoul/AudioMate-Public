"""Integration-ish tests for the TurnController state machine.

The full ``MainWindow.process_turn`` is too widget-coupled to instantiate in
a headless test (it runs an entire LLM → code-execution → result-rendering
loop wired to Qt widgets and signals). Instead these tests exercise the
parts of the turn loop that ``TurnController`` actually owns today:

- ``analyse_response`` — pure decision function that maps an LLM reply
  string to a ``TurnAction``. Covers PURE_TEXT, SINGLE_CODE, MULTI_CODE,
  INTENT_CLARIFY, ERROR_RETRY (via validation warnings), STOPPED.
- ``process_code_result`` — decides what to do after code has executed.
  Covers CONFIRM_NEEDED (Agent Mode + changes), ERROR_RETRY (error +
  resilience allows retry), STOPPED (error + no retries), and the
  pass-through PURE_TEXT path.

Together these cover the four code paths the user wants verified
(PURE_TEXT / SINGLE_CODE / ERROR_RETRY / CONFIRM_NEEDED) at the layer
that can actually be reached without standing up a QMainWindow.
"""

from __future__ import annotations

import pytest

from src.engine.turn_controller import TurnAction, TurnController
from src.tools.base import ToolResult, ToolResultStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def controller(qapp):
    # qapp ensures a QApplication exists so QObject construction succeeds.
    return TurnController()


class _FakeResilience:
    """Minimal stand-in for AgentResilienceManager."""

    def __init__(self, *, allow_retry: bool = True):
        self._allow_retry = allow_retry
        self.actions: list[tuple[int, str, str, bool]] = []

    def record_action(self, depth: int, code: str, output: str, has_error: bool) -> None:
        self.actions.append((depth, code, output, has_error))

    def should_retry_error(self, output: str) -> bool:
        return self._allow_retry


# ---------------------------------------------------------------------------
# analyse_response — PURE_TEXT
# ---------------------------------------------------------------------------


def test_analyse_response_pure_text_no_code(controller):
    result = controller.analyse_response("Here is a plain explanation.")
    assert result.action is TurnAction.PURE_TEXT
    assert result.response_text == "Here is a plain explanation."
    assert result.code_blocks == []


def test_analyse_response_strips_think_block(controller):
    raw = "<think>\n- planning\n</think>\nVisible reply."
    result = controller.analyse_response(raw)
    assert result.action is TurnAction.PURE_TEXT
    assert "<think>" not in result.response_text
    assert "Visible reply." in result.response_text


def test_analyse_response_code_fences_but_no_compilable_code_falls_back_to_text(controller):
    raw = "```python\nthis is not python code at all !!!\n```"
    result = controller.analyse_response(raw)
    assert result.action is TurnAction.PURE_TEXT


# ---------------------------------------------------------------------------
# analyse_response — SINGLE_CODE
# ---------------------------------------------------------------------------


def test_analyse_response_single_code_block(controller):
    raw = "Setting volume.\n```python\nprint('hi')\n```"
    result = controller.analyse_response(raw)
    assert result.action is TurnAction.SINGLE_CODE
    assert len(result.code_blocks) == 1
    assert "print('hi')" in result.code_blocks[0]


def test_analyse_response_multi_code(controller):
    raw = (
        "Step 1.\n```python\nprint('a')\n```\n"
        "Step 2.\n```python\nprint('b')\n```"
    )
    result = controller.analyse_response(raw)
    assert result.action is TurnAction.MULTI_CODE
    assert len(result.code_blocks) == 2


def test_analyse_response_converts_tool_call_helper(controller):
    raw = (
        '<tool_call>{"name":"read_user_file",'
        '"arguments":{"path":"E:/design_notes/sfx_spec.md"}}</tool_call>'
    )
    result = controller.analyse_response(raw)
    assert result.action is TurnAction.SINGLE_CODE
    assert "read_user_file('E:/design_notes/sfx_spec.md')" in result.code_blocks[0]
    assert "print(result)" in result.code_blocks[0]


def test_analyse_response_converts_structured_waapi_tool_call(controller):
    raw = (
        '<tool_call>{"name":"waapi.get_objects",'
        '"input":{"from":{"ofType":["StateGroup"]},"return":["id","name"]}}</tool_call>'
    )
    result = controller.analyse_response(raw)
    assert result.action is TurnAction.SINGLE_CODE
    assert "call_structured_tool('waapi.get_objects'" in result.code_blocks[0]
    assert "'StateGroup'" in result.code_blocks[0]


def test_analyse_response_ignores_fabricated_tool_response(controller):
    raw = '<tool_response>{"return":[{"name":"Fake"}]}</tool_response>'
    result = controller.analyse_response(raw)
    assert result.action is TurnAction.PURE_TEXT
    assert result.code_blocks == []


# ---------------------------------------------------------------------------
# analyse_response — ERROR_RETRY (validation warning before execution)
# ---------------------------------------------------------------------------


def test_analyse_response_error_retry_on_invalid_waapi_uri(controller):
    # validate_code_patterns flags known-bad URIs *when they appear as a
    # string literal in the code* (see src/utils/execution.py
    # _KNOWN_BAD_URIS + _URI_IN_CODE regex). The canonical bad URI
    # ak.wwise.core.object.getCurve must be rewritten to getAttenuationCurve.
    raw = (
        "Doing the thing.\n```python\n"
        "waapi_client.call('ak.wwise.core.object.getCurve', {})\n"
        "```"
    )
    result = controller.analyse_response(raw)
    assert result.action is TurnAction.ERROR_RETRY
    assert result.validation_warnings
    assert any("getAttenuationCurve" in w for w in result.validation_warnings)


# ---------------------------------------------------------------------------
# analyse_response — INTENT_CLARIFY
# ---------------------------------------------------------------------------


def test_analyse_response_intent_clarify(controller):
    raw = "[INTENT_CLARIFY]\n- option A\n- option B\n[/INTENT_CLARIFY]"
    result = controller.analyse_response(raw)
    assert result.action is TurnAction.INTENT_CLARIFY
    assert result.intent_options
    assert len(result.intent_options) >= 2


# ---------------------------------------------------------------------------
# analyse_response — Ask Mode write-block
# ---------------------------------------------------------------------------


def test_analyse_response_ask_mode_blocks_local_writes(controller):
    raw = (
        "Writing config.\n```python\n"
        "write_user_file('out.txt', 'data')\n"
        "```"
    )
    result = controller.analyse_response(raw, mode="Ask Mode")
    assert result.action is TurnAction.PURE_TEXT
    assert "Ask Mode" in result.response_text


# ---------------------------------------------------------------------------
# process_code_result — CONFIRM_NEEDED
# ---------------------------------------------------------------------------


def test_process_code_result_confirm_needed_on_changes_in_agent_mode(controller):
    tool_result = ToolResult(
        output="Property set",
        data={"has_error": False, "has_changes": True},
    )
    resilience = _FakeResilience()
    result = controller.process_code_result(
        tool_result,
        response_text="ok",
        mode="Agent Mode",
        resilience=resilience,
    )
    assert result.action is TurnAction.CONFIRM_NEEDED
    assert result.has_changes is True


def test_process_code_result_no_confirm_in_ask_mode_even_with_changes(controller):
    tool_result = ToolResult(
        output="Property set",
        data={"has_error": False, "has_changes": True},
    )
    result = controller.process_code_result(
        tool_result,
        response_text="ok",
        mode="Ask Mode",
        resilience=_FakeResilience(),
    )
    # Ask Mode never raises CONFIRM_NEEDED — the change request was
    # already pre-filtered upstream, so post-exec just continues.
    assert result.action is TurnAction.PURE_TEXT


# ---------------------------------------------------------------------------
# process_code_result — ERROR_RETRY and STOPPED
# ---------------------------------------------------------------------------


def test_process_code_result_error_retry_when_resilience_allows(controller):
    tool_result = ToolResult(
        output="Traceback: ValueError: oops",
        status=ToolResultStatus.ERROR,
        data={"has_error": True, "has_changes": False},
    )
    result = controller.process_code_result(
        tool_result,
        response_text="trying",
        mode="Agent Mode",
        resilience=_FakeResilience(allow_retry=True),
    )
    assert result.action is TurnAction.ERROR_RETRY
    assert result.has_error is True


def test_process_code_result_stopped_when_resilience_refuses(controller):
    tool_result = ToolResult(
        output="Traceback: ValueError: oops",
        status=ToolResultStatus.ERROR,
        data={"has_error": True, "has_changes": False},
    )
    result = controller.process_code_result(
        tool_result,
        response_text="trying",
        mode="Agent Mode",
        resilience=_FakeResilience(allow_retry=False),
    )
    assert result.action is TurnAction.STOPPED
    assert result.has_error is True


def test_process_code_result_records_action_in_resilience(controller):
    resilience = _FakeResilience()
    tool_result = ToolResult(output="done", data={"has_error": False, "has_changes": False})
    controller.process_code_result(
        tool_result,
        response_text="reply",
        mode="Agent Mode",
        resilience=resilience,
        recursion_depth=3,
        last_code="print('x')",
    )
    assert resilience.actions == [(3, "print('x')", "done", False)]

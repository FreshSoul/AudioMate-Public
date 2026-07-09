"""Self-tests for the golden-task scorer + the prompt-block assembler.

No LLM calls — exercises the scoring logic with synthetic responses so CI
can catch scorer regressions, and verifies the prompt-block layering
emits the expected shapes.
"""

from __future__ import annotations

import pytest

from src.engine.prompt_blocks import (
    PromptBlock,
    assemble_as_string,
    assemble_for_anthropic,
    summarize_blocks,
)
from src.test.golden_tasks_runner import (
    load_golden_tasks,
    score_task,
    summarize,
)
from scripts.run_golden_tasks import _tool_calls_for_scoring


# ---------------------------------------------------------------------------
# Prompt blocks
# ---------------------------------------------------------------------------


def test_prompt_blocks_skip_empty():
    blocks = [
        PromptBlock(id="a", content="hello", scope="static"),
        PromptBlock(id="b", content="", scope="session"),
        PromptBlock(id="c", content="   ", scope="turn"),
        PromptBlock(id="d", content="world", scope="turn"),
    ]
    text = assemble_as_string(blocks)
    assert "hello" in text
    assert "world" in text
    assert text.count("\n\n") == 1  # only two non-empty blocks separated


def test_prompt_blocks_scope_ordering():
    """Blocks must come out in static → session → turn order regardless of input order."""
    blocks = [
        PromptBlock(id="t", content="TURN", scope="turn"),
        PromptBlock(id="s", content="STATIC", scope="static"),
        PromptBlock(id="x", content="SESSION", scope="session"),
    ]
    text = assemble_as_string(blocks)
    assert text.index("STATIC") < text.index("SESSION") < text.index("TURN")


def test_prompt_blocks_anthropic_cache_breakpoints():
    """Anthropic output should place cache_control on static and session
    layers, but never on the turn layer."""
    blocks = [
        PromptBlock(id="s", content="STATIC", scope="static"),
        PromptBlock(id="x", content="SESSION", scope="session"),
        PromptBlock(id="t", content="TURN", scope="turn"),
    ]
    out = assemble_for_anthropic(blocks)
    assert len(out) == 3
    assert out[0]["text"] == "STATIC"
    assert out[0].get("cache_control") == {"type": "ephemeral"}
    assert out[1]["text"] == "SESSION"
    assert out[1].get("cache_control") == {"type": "ephemeral"}
    assert out[2]["text"] == "TURN"
    assert "cache_control" not in out[2]


def test_prompt_blocks_anthropic_skips_missing_layer():
    """If a scope is empty, no block is emitted for it (so the cache prefix
    stays byte-stable across turns that vary in which scopes are present)."""
    blocks = [
        PromptBlock(id="s", content="STATIC", scope="static"),
        PromptBlock(id="t", content="TURN", scope="turn"),
    ]
    out = assemble_for_anthropic(blocks)
    assert len(out) == 2
    assert out[0]["text"] == "STATIC"
    assert out[1]["text"] == "TURN"


def test_summarize_blocks():
    blocks = [
        PromptBlock(id="a", content="hi", scope="static"),
        PromptBlock(id="b", content="", scope="turn"),
    ]
    summary = summarize_blocks(blocks)
    assert summary == [{"id": "a", "scope": "static", "chars": 2}]


# ---------------------------------------------------------------------------
# Golden tasks — file integrity + scorer correctness
# ---------------------------------------------------------------------------


def test_golden_tasks_file_loadable():
    tasks = load_golden_tasks()
    assert tasks, "golden_tasks.json should contain at least one task"
    seen_ids: set[str] = set()
    for t in tasks:
        assert "id" in t
        assert t["id"] not in seen_ids, f"duplicate task id: {t['id']}"
        seen_ids.add(t["id"])
        assert "user_query" in t and t["user_query"]
        assert isinstance(t.get("expected_signals", []), list)
        assert isinstance(t.get("forbidden_signals", []), list)


def test_score_pure_chat_no_tool():
    task = {
        "id": "chat",
        "user_query": "hi",
        "expected_tool": None,
        "expected_signals": [],
        "forbidden_signals": ["ak.wwise"],
    }
    s = score_task(task, "你好，今天过得怎么样？", tool_calls=None)
    assert s.passed
    assert s.tool_match == 1.0


def test_score_chat_but_emitted_code_fails():
    """A chat task with no expected tool but the response contains tool
    calls should fail tool_match (the model called a tool when it shouldn't)."""
    task = {"id": "chat", "expected_tool": None, "expected_signals": [], "forbidden_signals": []}
    s = score_task(task, "你好", tool_calls=[{"name": "waapi_python_exec", "input": {"code": ""}}])
    assert not s.passed
    assert s.tool_match == 0.0


def test_score_signal_recall_with_tool_code():
    """The scorer should look inside tool call inputs for expected signals,
    not only the visible text."""
    task = {
        "id": "create",
        "expected_tool": "waapi_python_exec",
        "expected_signals": ["ak.wwise.core.object.create"],
        "forbidden_signals": [],
    }
    s = score_task(
        task,
        "好的，我会创建这个对象。",
        tool_calls=[{"name": "waapi_python_exec", "input": {"code": "waapi_client.call('ak.wwise.core.object.create', ...)"}}],
    )
    assert s.passed
    assert s.signal_recall == 1.0


def test_score_forbidden_signal_caught():
    task = {
        "id": "stategroup",
        "expected_tool": "waapi_python_exec",
        "expected_signals": ["ak.wwise.core.object.setStateGroups"],
        "forbidden_signals": ["ak.wwise.core.object.addStateGroup"],
    }
    s = score_task(
        task,
        "",
        tool_calls=[{"name": "waapi_python_exec", "input": {"code": "ak.wwise.core.object.addStateGroup(...)"}}],
    )
    assert not s.passed
    assert s.forbidden_avoidance == 0.0
    assert "ak.wwise.core.object.addStateGroup" in s.found_forbidden


def test_score_signal_missing_reported():
    task = {
        "id": "needs_signal",
        "expected_tool": None,
        "expected_signals": ["MUST_APPEAR"],
        "forbidden_signals": [],
    }
    s = score_task(task, "this response is unrelated", tool_calls=None)
    assert "MUST_APPEAR" in s.missing_signals
    assert s.signal_recall == 0.0


def test_forbidden_in_comment_not_penalised():
    """A forbidden API named only in a comment (e.g. '# avoid X, use helper')
    must NOT count as a violation — only an actual use in live code does."""
    task = {
        "id": "comment_mention",
        "expected_tool": "waapi_python_exec",
        "expected_signals": ["import_audio_files_to_selected_wwise"],
        "forbidden_signals": ["ak.wwise.core.audio.import"],
    }
    code = (
        "# 使用提供的 helper，避免手写 ak.wwise.core.audio.import\n"
        "import_audio_files_to_selected_wwise(paths)\n"
    )
    s = score_task(task, "", tool_calls=[{"name": "waapi_python_exec", "input": {"code": code}}])
    assert s.found_forbidden == []
    assert s.forbidden_avoidance == 1.0
    assert s.passed


def test_forbidden_in_live_code_still_caught():
    """A real call to the forbidden API (not in a comment) must still fail."""
    task = {
        "id": "real_use",
        "expected_tool": "waapi_python_exec",
        "expected_signals": [],
        "forbidden_signals": ["ak.wwise.core.audio.import"],
    }
    code = "waapi_client.call('ak.wwise.core.audio.import', payload)\n"
    s = score_task(task, "", tool_calls=[{"name": "waapi_python_exec", "input": {"code": code}}])
    assert "ak.wwise.core.audio.import" in s.found_forbidden
    assert not s.passed


def test_runner_scores_pseudo_tool_call_as_executable_code():
    response = (
        '<tool_call>{"name":"read_user_file",'
        '"arguments":{"path":"E:/design_notes/sfx_spec.md"}}</tool_call>'
        '<tool_response>{"fake":"ignored"}</tool_response>'
    )
    calls = _tool_calls_for_scoring(response, [])
    assert len(calls) == 1
    assert calls[0]["name"] == "waapi_python_exec"
    assert "read_user_file('E:/design_notes/sfx_spec.md')" in calls[0]["input"]["code"]



def test_summarize_pass_rate():
    scores = [
        score_task({"id": "a", "expected_tool": None, "expected_signals": [], "forbidden_signals": []}, "hi"),
        score_task({"id": "b", "expected_tool": None, "expected_signals": ["MUST_APPEAR"], "forbidden_signals": []}, "unrelated"),
    ]
    stats = summarize(scores)
    assert stats["count"] == 2
    assert stats["passed"] == 1
    assert stats["pass_rate"] == 0.5

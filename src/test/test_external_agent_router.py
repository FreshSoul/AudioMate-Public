"""Tests for deterministic external-agent (Codex / Claude Code) delegation routing."""

from __future__ import annotations

from src.engine.external_agent_router import (
    ExternalAgentRouter,
    agent_pet_id,
    detect_delegation,
)


def test_forward_when_agent_named_with_task():
    d = detect_delegation("和codex对话继续完善我的网站")
    assert d.forward is True
    assert d.agent_key == "codex"
    assert d.agent_pet_id == "codex-agent"


def test_forward_let_codex_continue():
    d = detect_delegation("让codex继续完善网站")
    assert d.forward is True
    assert d.agent_key == "codex"


def test_claude_code_alias():
    d = detect_delegation("交给 claude code 修一下这个 bug")
    assert d.forward is True
    assert d.agent_key == "claude_code"
    assert d.agent_pet_id == "claude-code-agent"


def test_agent_named_midsentence_no_task_opens_relay_without_forwarding():
    # Agent named mid-sentence with no task marker → relay opens, no forward.
    d = detect_delegation("我之前用的是 codex")
    assert d.forward is False
    assert d.agent_key == "codex"  # relay remembered, not yet forwarded


def test_agent_at_start_always_forwards():
    # Addressing the agent directly ("codex ...") forwards by design — the
    # common case is "codex 帮我做X"; the rare "codex 是什么" just gets a
    # self-intro from Codex, which is acceptable.
    d = detect_delegation("codex 帮我加个登录页")
    assert d.forward is True
    assert d.agent_key == "codex"


def test_followup_forwards_in_active_relay():
    # No agent named, but relay already active → follow-up forwards.
    d = detect_delegation("继续完善登录页", active_agent_key="codex")
    assert d.forward is True
    assert d.agent_key == "codex"


def test_no_agent_no_relay_does_not_forward():
    d = detect_delegation("帮我在 Wwise 里建一个 Actor-Mixer")
    assert d.forward is False
    assert d.agent_key == ""


def test_stop_term_clears_relay():
    d = detect_delegation("你来做，别用codex了", active_agent_key="codex")
    assert d.clear is True
    assert d.forward is False


def test_router_remembers_agent_across_turns():
    r = ExternalAgentRouter()
    first = r.handle("和codex继续完善网站")
    assert first.forward is True
    assert r.active_agent_key == "codex"
    # Bare follow-up now routes to codex without re-naming it.
    second = r.handle("再加一个深色模式")
    assert second.forward is True
    assert second.agent_key == "codex"


def test_router_clear_then_normal_turn():
    r = ExternalAgentRouter()
    r.handle("和codex完善网站")
    stop = r.handle("停止转发，你直接来")
    assert stop.clear is True
    assert r.active_agent_key == ""
    # After clearing, a bare follow-up must NOT forward.
    after = r.handle("继续完善")
    assert after.forward is False


def test_agent_pet_id_lookup():
    assert agent_pet_id("codex") == "codex-agent"
    assert agent_pet_id("claude_code") == "claude-code-agent"
    assert agent_pet_id("nope") == ""

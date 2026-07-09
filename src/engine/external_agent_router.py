"""Deterministic routing for "talk to Codex / Claude Code" requests.

AudioMate's main chat normally runs every user message through the LLM turn,
whose system prompt insists "if it's an action, emit a python_waapi code
block". That rule fights the user's real intent when they say things like
"和 Codex 对话继续完善我的网站" — the model writes website/WAAPI code itself
instead of handing the task to the Codex sub-agent.

This module makes the hand-off deterministic. Before ``process_turn`` runs we
detect delegation intent here (no LLM involved) and dispatch straight to the
external coding sub-agent. It also remembers the active agent for the chat, so
follow-ups like "继续" keep routing to the same agent until the user stops.

The detection is intentionally conservative: an agent name (codex / claude
code) must appear, OR the chat must already be in relay mode with the agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# pet_id of the built-in external-agent sub-pets (see src/pet/store.py).
_AGENT_PET_IDS = {
    "codex": "codex-agent",
    "claude_code": "claude-code-agent",
}

_AGENT_LABELS = {
    "codex": "Codex",
    "claude_code": "ClaudeCode",
}

# Aliases that name each agent in a user message.
_AGENT_ALIASES = {
    "codex": ("codex", "code x"),
    "claude_code": ("claudecode", "claude code", "claude-code", "claude_code"),
}

# User wants to leave relay mode / do it inside AudioMate itself.
_STOP_TERMS = (
    "停止", "退出", "结束", "关闭转发", "取消转发", "不用转发", "别转发",
    "不要转发", "你来", "你直接", "audiomate 来", "别用 codex", "不用 codex",
    "别用codex", "不用codex", "stop relay", "stop forwarding",
)

# Markers that a message carries an actual task to forward (vs idle chatter).
_TASK_TERMS = (
    "继续", "完善", "生成", "写", "做", "修改", "修复", "添加", "加",
    "创建", "实现", "检查", "分析", "优化", "重构", "对话", "聊", "问",
    "交给", "发给", "让", "帮我", "review", "fix", "implement", "create",
    "add", "continue", "improve", "build", "refactor", "talk", "chat",
)


@dataclass(frozen=True)
class DelegationDecision:
    """Outcome of inspecting one user message for delegation intent."""

    forward: bool = False          # dispatch to the external agent now
    clear: bool = False            # leave relay mode
    agent_key: str = ""            # "codex" | "claude_code"
    agent_pet_id: str = ""         # pet_id to dispatch
    agent_label: str = ""          # display name


def _lower(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).casefold()


def _detect_agent(lowered: str) -> str:
    for key, aliases in _AGENT_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                return key
    return ""


def agent_pet_id(agent_key: str) -> str:
    return _AGENT_PET_IDS.get(str(agent_key or "").strip(), "")


def agent_label(agent_key: str) -> str:
    return _AGENT_LABELS.get(str(agent_key or "").strip(), "")


def detect_delegation(user_text: str, active_agent_key: str = "") -> DelegationDecision:
    """Return how *user_text* should affect external-agent relay.

    Rules (deterministic, no LLM):
    - Name an agent + carry a task marker -> forward now, enter relay mode.
    - Already in relay mode + a stop term -> clear relay.
    - Already in relay mode + any non-trivial message -> forward (follow-up).
    """
    lowered = _lower(user_text)
    active = str(active_agent_key or "").strip()
    if not lowered:
        return DelegationDecision()

    mentioned = _detect_agent(lowered)

    # Stop terms only matter when a relay is active or an agent is named.
    if (mentioned or active) and any(term in lowered for term in _STOP_TERMS):
        key = mentioned or active
        return DelegationDecision(forward=False, clear=True, agent_key=key,
                                  agent_pet_id=agent_pet_id(key), agent_label=agent_label(key))

    if mentioned:
        has_task = any(term in lowered for term in _TASK_TERMS)
        # Naming the agent at the start (e.g. "codex, 帮我…") always forwards.
        starts_with_agent = any(lowered.startswith(a) for a in _AGENT_ALIASES[mentioned])
        if has_task or starts_with_agent:
            return DelegationDecision(forward=True, agent_key=mentioned,
                                      agent_pet_id=agent_pet_id(mentioned),
                                      agent_label=agent_label(mentioned))
        # Agent named but no task marker — open relay without forwarding yet.
        return DelegationDecision(forward=False, agent_key=mentioned,
                                  agent_pet_id=agent_pet_id(mentioned),
                                  agent_label=agent_label(mentioned))

    if active:
        # Relay already active; forward any substantive follow-up.
        return DelegationDecision(forward=True, agent_key=active,
                                  agent_pet_id=agent_pet_id(active),
                                  agent_label=agent_label(active))

    return DelegationDecision()


class ExternalAgentRouter:
    """Per-chat relay state: remembers which external agent is active."""

    def __init__(self) -> None:
        self.active_agent_key: str = ""

    def reset(self) -> None:
        self.active_agent_key = ""

    def handle(self, user_text: str) -> DelegationDecision:
        decision = detect_delegation(user_text, self.active_agent_key)
        if decision.clear:
            self.active_agent_key = ""
        elif decision.agent_key:
            # Both "forward now" and "relay-only" remember the agent so
            # follow-up turns keep routing to it.
            self.active_agent_key = decision.agent_key
        return decision


__all__ = [
    "DelegationDecision",
    "ExternalAgentRouter",
    "agent_label",
    "agent_pet_id",
    "detect_delegation",
]

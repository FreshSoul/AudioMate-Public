"""Golden-task evaluator — pure scoring functions for LLM responses.

The runner itself does NOT call any LLM. It takes a model's response text
plus the parsed tool calls (from ``response_parser`` or native tool_use)
and scores it against the expectations in ``golden_tasks.json``.

This split means CI can validate the scoring logic without API keys, and
a separate (gitignored) script can drive real LLM calls and feed results
in. See ``scripts/run_golden_tasks.py`` (to add) for the runner.

Each task scores 0-1 on:
- ``tool_match``: expected_tool matched (or both None for chat-only)
- ``signal_recall``: fraction of expected_signals present in the response
- ``forbidden_avoidance``: 1.0 if no forbidden_signals present, else 0.0
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

GOLDEN_PATH = Path(__file__).with_name("golden_tasks.json")


def load_golden_tasks(path: Path | None = None) -> list[dict]:
    """Load the golden-task list. Empty list if the file is missing."""
    p = path or GOLDEN_PATH
    if not p.is_file():
        return []
    with open(p, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"golden_tasks.json must be a JSON array, got {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class TaskScore:
    """Per-task result. ``passed`` is the conjunction of the three sub-scores."""

    task_id: str
    tool_match: float = 0.0
    signal_recall: float = 0.0
    forbidden_avoidance: float = 1.0
    missing_signals: list[str] = field(default_factory=list)
    found_forbidden: list[str] = field(default_factory=list)
    response_preview: str = ""

    @property
    def passed(self) -> bool:
        return (
            self.tool_match >= 1.0
            and self.signal_recall >= 1.0
            and self.forbidden_avoidance >= 1.0
        )


def _normalize(text: str) -> str:
    return (text or "").lower()


def _contains_any_signal(haystack_lc: str, signal: str) -> bool:
    """Match a signal case-insensitively. Whitespace-tolerant on tokens.

    A pipe (``|``) inside a signal means "any of the alternatives counts as
    a match" — e.g. ``"set_property|ak.wwise.core.object.set"`` succeeds
    when EITHER substring appears. Use this for tasks where multiple
    legitimate API choices exist; everything that should be required must
    stay in its own list entry.
    """
    s = (signal or "").strip()
    if not s:
        return False
    if "|" in s:
        return any(_contains_any_signal(haystack_lc, alt) for alt in s.split("|"))
    return s.lower() in haystack_lc


def _strip_comments(text: str) -> str:
    """Remove Python/markdown comment content so forbidden-API matching only
    sees live code, not explanatory mentions.

    Drops everything after a ``#`` on each line. Coarse (a ``#`` inside a
    string literal also truncates the line) but safe for our purpose:
    forbidden APIs named only in a comment like ``# avoid X, use the helper``
    must not count as a violation. False negatives (missing a real use that
    happens to sit after a ``#`` on the same line) are vanishingly rare in
    generated WAAPI code.
    """
    out_lines = []
    for line in (text or "").splitlines():
        hash_idx = line.find("#")
        out_lines.append(line if hash_idx < 0 else line[:hash_idx])
    return "\n".join(out_lines)


def score_task(
    task: dict,
    response_text: str,
    tool_calls: Iterable[dict] | None = None,
) -> TaskScore:
    """Score a single task against an LLM response.

    Parameters
    ----------
    task:
        One entry from golden_tasks.json.
    response_text:
        Visible assistant text (post-think-strip, post-roleplay-strip).
    tool_calls:
        List of ``{name, input}`` dicts representing parsed tool calls. For
        the markdown-code-block path, pass ``[{"name": "waapi_python_exec",
        "input": {"code": "..."}}]``. For chat-only turns, pass ``None`` or
        ``[]``.
    """
    tool_calls = list(tool_calls or [])
    expected_tool = task.get("expected_tool")

    # Tool match
    if expected_tool is None:
        tool_match = 1.0 if not tool_calls else 0.0
    else:
        tool_match = 1.0 if any(tc.get("name") == expected_tool for tc in tool_calls) else 0.0

    # Build the haystack: response text + any tool input code/args.
    haystack_parts = [response_text or ""]
    for tc in tool_calls:
        inp = tc.get("input") or {}
        if isinstance(inp, dict):
            for v in inp.values():
                if isinstance(v, str):
                    haystack_parts.append(v)
                else:
                    haystack_parts.append(json.dumps(v, ensure_ascii=False))
    haystack_full = "\n".join(haystack_parts)
    haystack_lc = _normalize(haystack_full)

    # Signal recall — matched against the FULL text (mentioning the right API
    # in a comment still shows the model knows it).
    expected_signals = task.get("expected_signals") or []
    missing: list[str] = []
    for sig in expected_signals:
        if not _contains_any_signal(haystack_lc, sig):
            missing.append(sig)
    if expected_signals:
        signal_recall = 1.0 - (len(missing) / len(expected_signals))
    else:
        signal_recall = 1.0

    # Forbidden — matched against CODE ONLY (comments stripped). A model that
    # writes "# avoid ak.wwise.core.audio.import, use the helper" must NOT be
    # penalised for naming the forbidden API in a comment; only an actual use
    # in live code counts as a violation.
    haystack_code_lc = _normalize(_strip_comments(haystack_full))
    found_forbidden: list[str] = []
    for sig in task.get("forbidden_signals") or []:
        if _contains_any_signal(haystack_code_lc, sig):
            found_forbidden.append(sig)
    forbidden_avoidance = 0.0 if found_forbidden else 1.0

    preview = (response_text or "").strip().replace("\n", " ")[:200]

    return TaskScore(
        task_id=str(task.get("id") or ""),
        tool_match=tool_match,
        signal_recall=signal_recall,
        forbidden_avoidance=forbidden_avoidance,
        missing_signals=missing,
        found_forbidden=found_forbidden,
        response_preview=preview,
    )


# ---------------------------------------------------------------------------
# Aggregate stats
# ---------------------------------------------------------------------------


def summarize(scores: list[TaskScore]) -> dict:
    """Return aggregate stats over a list of per-task scores."""
    if not scores:
        return {"count": 0, "pass_rate": 0.0}
    passed = sum(1 for s in scores if s.passed)
    return {
        "count": len(scores),
        "passed": passed,
        "pass_rate": round(passed / len(scores), 3),
        "avg_tool_match": round(sum(s.tool_match for s in scores) / len(scores), 3),
        "avg_signal_recall": round(sum(s.signal_recall for s in scores) / len(scores), 3),
        "avg_forbidden_avoidance": round(sum(s.forbidden_avoidance for s in scores) / len(scores), 3),
    }


__all__ = ["TaskScore", "load_golden_tasks", "score_task", "summarize"]

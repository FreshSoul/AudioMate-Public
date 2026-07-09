"""Turn log — structured JSONL of LLM turns, for offline accuracy analysis.

Each line records one LLM call: model, prompt-block summary, token usage
(input / output / cache_read / cache_creation), latency, and any tool
calls. Writes are append-only and tolerant of failures (logging never
breaks user-facing flow).

Lives at ``LOGS_DIR / turns.jsonl``. Rotated by date to keep individual
files small enough to grep through.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from src.utils.app_paths import LOGS_DIR, ensure_data_dirs


_WRITE_LOCK = threading.Lock()


def _log_path() -> Path:
    """Return today's turn-log file path. One file per UTC date."""
    ensure_data_dirs()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return LOGS_DIR / f"turns-{today}.jsonl"


def _coerce(obj: Any) -> Any:
    """Best-effort JSON-friendly coercion."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {str(k): _coerce(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_coerce(v) for v in obj]
    return str(obj)


def write_entry(entry: dict) -> None:
    """Append one record to the turn-log. Failures are swallowed.

    The caller owns the entry shape; we just ensure JSON-safety and add a
    timestamp if missing.
    """
    entry.setdefault("ts", datetime.utcnow().isoformat(timespec="seconds") + "Z")
    payload = _coerce(entry)
    try:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return  # don't bring down the worker over a serialization bug
    try:
        with _WRITE_LOCK:
            with open(_log_path(), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        return


def record_usage(
    *,
    model: str,
    elapsed_ms: int,
    usage,
    system_blocks: Iterable | None = None,
) -> None:
    """Convenience entry for the WorkerThread's per-call stats.

    Captures just enough to compute cache-hit rate, token spend, and
    latency distributions later. Block ids/scopes are recorded so we can
    correlate cache misses to which scope mutated.
    """
    blocks_summary: list[dict] = []
    if system_blocks:
        for b in system_blocks:
            blocks_summary.append({
                "id": getattr(b, "id", ""),
                "scope": getattr(b, "scope", ""),
                "chars": len(getattr(b, "content", "") or ""),
            })

    entry = {
        "kind": "llm_turn",
        "model": model,
        "elapsed_ms": elapsed_ms,
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
        "blocks": blocks_summary,
    }
    write_entry(entry)


def record_tool_call(
    *,
    name: str,
    success: bool,
    elapsed_ms: int,
    error: str | None = None,
    args_chars: int = 0,
) -> None:
    """Convenience entry for tool-execution stats. Lets us compute per-tool
    success rates and latency offline."""
    entry = {
        "kind": "tool_call",
        "name": name,
        "success": bool(success),
        "elapsed_ms": elapsed_ms,
        "args_chars": args_chars,
    }
    if error:
        entry["error"] = str(error)[:500]
    write_entry(entry)


__all__ = ["write_entry", "record_usage", "record_tool_call"]

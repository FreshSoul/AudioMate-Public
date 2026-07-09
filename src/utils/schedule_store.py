from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from src.utils.storage import BASE_DIR


SCHEDULED_TASKS_FILE = os.path.join(BASE_DIR, "scheduled_tasks.json")
SCHEDULE_TYPES = {"once", "daily", "weekly", "interval"}
WEEKDAY_VALUES = set(range(7))


def utc_now() -> datetime:
    return datetime.now().replace(microsecond=0)


def format_datetime(value: datetime | None) -> str:
    if not value:
        return ""
    return value.replace(microsecond=0).isoformat()


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def parse_time_text(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def format_time_text(hour: int, minute: int) -> str:
    return f"{int(hour):02d}:{int(minute):02d}"


def _normalize_weekdays(value: Any) -> list[int]:
    if isinstance(value, int):
        candidates = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        candidates = []

    weekdays: list[int] = []
    for item in candidates:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if day in WEEKDAY_VALUES and day not in weekdays:
            weekdays.append(day)
    weekdays.sort()
    return weekdays


def compute_next_run(task: dict[str, Any], now: datetime | None = None) -> datetime | None:
    now = (now or utc_now()).replace(microsecond=0)
    schedule_type = task.get("schedule_type")

    if schedule_type == "once":
        run_at = parse_datetime(task.get("run_at"))
        if not run_at or run_at <= now:
            return None
        return run_at.replace(microsecond=0)

    if schedule_type == "daily":
        time_value = parse_time_text(task.get("time"))
        if not time_value:
            return None
        hour, minute = time_value
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if schedule_type == "weekly":
        time_value = parse_time_text(task.get("time"))
        weekdays = _normalize_weekdays(task.get("weekdays"))
        if not time_value or not weekdays:
            return None
        hour, minute = time_value
        candidates = []
        for day in weekdays:
            days_ahead = (day - now.weekday()) % 7
            candidate = (now + timedelta(days=days_ahead)).replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )
            if candidate <= now:
                candidate += timedelta(days=7)
            candidates.append(candidate)
        return min(candidates) if candidates else None

    if schedule_type == "interval":
        try:
            interval_minutes = int(task.get("interval_minutes"))
        except (TypeError, ValueError):
            return None
        if interval_minutes < 1:
            return None
        interval = timedelta(minutes=interval_minutes)
        anchor = parse_datetime(task.get("last_run_at")) or parse_datetime(task.get("created_at")) or now
        candidate = anchor.replace(microsecond=0) + interval
        while candidate <= now:
            candidate += interval
        return candidate

    return None


def normalize_task(raw: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    now = (now or utc_now()).replace(microsecond=0)
    schedule_type = str(raw.get("schedule_type") or "once").strip().lower()
    if schedule_type not in SCHEDULE_TYPES:
        return None

    created_at = parse_datetime(raw.get("created_at")) or now
    updated_at = parse_datetime(raw.get("updated_at")) or created_at
    task = {
        "id": str(raw.get("id") or uuid.uuid4()),
        "title": str(raw.get("title") or "定时任务").strip() or "定时任务",
        "prompt": str(raw.get("prompt") or "").strip(),
        "schedule_type": schedule_type,
        "enabled": bool(raw.get("enabled", True)),
        "created_at": format_datetime(created_at),
        "updated_at": format_datetime(updated_at),
        "last_run_at": format_datetime(parse_datetime(raw.get("last_run_at"))),
        "next_run_at": "",
    }
    source = str(raw.get("source") or "").strip()
    if source:
        task["source"] = source
    pet_id = str(raw.get("pet_id") or "").strip()
    if pet_id:
        task["pet_id"] = pet_id

    if schedule_type == "once":
        run_at = parse_datetime(raw.get("run_at"))
        if not run_at:
            return None
        task["run_at"] = format_datetime(run_at)
    elif schedule_type in {"daily", "weekly"}:
        time_value = parse_time_text(raw.get("time"))
        if not time_value:
            return None
        task["time"] = format_time_text(*time_value)
        if schedule_type == "weekly":
            weekdays = _normalize_weekdays(raw.get("weekdays"))
            if not weekdays:
                return None
            task["weekdays"] = weekdays
    elif schedule_type == "interval":
        try:
            interval_minutes = int(raw.get("interval_minutes"))
        except (TypeError, ValueError):
            return None
        if interval_minutes < 1:
            return None
        task["interval_minutes"] = interval_minutes

    if not task["prompt"]:
        task["enabled"] = False

    next_run = compute_next_run(task, now=now) if task["enabled"] else None
    if next_run is None and schedule_type == "once":
        task["enabled"] = False
    task["next_run_at"] = format_datetime(next_run)
    return task


def load_scheduled_tasks(now: datetime | None = None) -> list[dict[str, Any]]:
    if not os.path.exists(SCHEDULED_TASKS_FILE):
        return []
    try:
        with open(SCHEDULED_TASKS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as exc:
        print(f"[ScheduleStore] Failed to load {SCHEDULED_TASKS_FILE}: {exc}")
        return []

    source = data.get("tasks") if isinstance(data, dict) else data
    if not isinstance(source, list):
        return []

    tasks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in source:
        normalized = normalize_task(item, now=now)
        if not normalized or normalized["id"] in seen_ids:
            continue
        tasks.append(normalized)
        seen_ids.add(normalized["id"])
    tasks.sort(key=lambda item: item.get("next_run_at") or "9999")
    return tasks


def save_scheduled_tasks(tasks: list[dict[str, Any]]) -> bool:
    try:
        payload = {"tasks": tasks}
        with open(SCHEDULED_TASKS_FILE, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        print(f"[ScheduleStore] Failed to save {SCHEDULED_TASKS_FILE}: {exc}")
        return False


def build_task(payload: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    data = deepcopy(payload)
    current = (now or utc_now()).replace(microsecond=0)
    data.setdefault("id", str(uuid.uuid4()))
    data.setdefault("created_at", format_datetime(current))
    data["updated_at"] = format_datetime(current)
    return normalize_task(data, now=current)


def refresh_task_schedule(task: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    refreshed = dict(task)
    current = (now or utc_now()).replace(microsecond=0)
    if refreshed.get("schedule_type") == "once" and parse_datetime(refreshed.get("run_at")) and parse_datetime(refreshed.get("run_at")) <= current:
        refreshed["enabled"] = False
    next_run = compute_next_run(refreshed, now=current) if refreshed.get("enabled") else None
    if next_run is None and refreshed.get("schedule_type") == "once":
        refreshed["enabled"] = False
    refreshed["next_run_at"] = format_datetime(next_run)
    refreshed["updated_at"] = format_datetime(current)
    return refreshed


def mark_task_ran(task: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    current = (now or utc_now()).replace(microsecond=0)
    updated = dict(task)
    updated["last_run_at"] = format_datetime(current)
    if updated.get("schedule_type") == "once":
        updated["enabled"] = False
        updated["next_run_at"] = ""
    else:
        updated["next_run_at"] = format_datetime(compute_next_run(updated, now=current))
    updated["updated_at"] = format_datetime(current)
    return updated

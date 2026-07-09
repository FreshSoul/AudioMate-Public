from __future__ import annotations

from typing import Any


DEFAULT_NOTIFICATION_SETTINGS = {
    "enabled": True,
    "task_completed": True,
    "scheduled_completed": True,
    "failure": True,
}


def normalize_notification_settings(settings: dict[str, Any] | None) -> dict[str, bool]:
    source = settings if isinstance(settings, dict) else {}
    normalized = dict(DEFAULT_NOTIFICATION_SETTINGS)
    for key in normalized:
        if key in source:
            normalized[key] = bool(source.get(key))
    return normalized

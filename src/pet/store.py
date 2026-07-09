"""Pet store — persistence helpers for the Buddy(宠物) feature.

Mirrors the patterns in ``src/utils/plugin_store.py`` and
``src/utils/skill_store.py``.  Keeps all data normalisation and mutation
logic outside the GUI so it is easy to unit-test.

Data shape stored under ``app_settings["pets"]``::

    {
        "active_main_id": str,
        "floating_pet_id": str,
        "floating_enabled": bool,
        "floating_position": {"x": int, "y": int},
        "items": [
            {
                "id": str,
                "kind": "main" | "sub",
                "name": str,
                "avatar_path": str,
                "description": str,
                "enabled": bool,
                "persona_prompt": str,
                "external_agent": "" | "codex" | "claude_code",
                "llm": {                  # sub pets only; empty = inherit main
                    "base_url": str,
                    "api_key": str,
                    "model": str,
                },
                "capabilities": {"skill_ids": [...], "plugin_ids": [...]},
                "schedule": {...},        # sub pets only
                "task_template": str,     # sub pets only
                "stats": {
                    "tasks_total": int,
                    "tasks_succeeded": int,
                    "tasks_failed": int,
                    "tools_used": int,
                    "last_active_at": str,
                },
                "activity_log": [
                    {"ts": str, "title": str, "outcome": str, "detail": str},
                    ...  # capped at ACTIVITY_LOG_CAP entries
                ],
                "imported_at": str,
                "updated_at": str,
            }
        ]
    }
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any


PET_KIND_MAIN = "main"
PET_KIND_SUB = "sub"
VALID_PET_KINDS = (PET_KIND_MAIN, PET_KIND_SUB)
VALID_OUTCOMES = ("success", "fail", "cancel", "info")

ACTIVITY_LOG_CAP = 50

DEFAULT_FLOATING_POSITION = {"x": -1, "y": -1}  # -1 means "use a sensible default"
DEFAULT_MAIN_PET_ID = "audiomate-main"
DEFAULT_CODEX_PET_ID = "codex-agent"
DEFAULT_CLAUDE_CODE_PET_ID = "claude-code-agent"
FIXED_DEFAULT_PET_IDS = frozenset({
    DEFAULT_MAIN_PET_ID,
    DEFAULT_CODEX_PET_ID,
    DEFAULT_CLAUDE_CODE_PET_ID,
})
VALID_EXTERNAL_AGENTS = ("", "codex", "claude_code")


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _slugify(text: str, fallback: str = "pet") -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return cleaned or fallback


def _build_pet_id(name: str, kind: str) -> str:
    seed = f"{kind}-{name}".strip("-")
    if seed:
        slug = _slugify(seed, fallback="")
        # If the slug collapsed to just the kind prefix (e.g. because the
        # name was non-ASCII like 中文), every newly added pet of that kind
        # would get the same id and clobber its predecessors. Append a uuid
        # suffix in that case so each pet stays unique.
        if slug and slug != kind:
            return slug
    return str(uuid.uuid4())


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for raw in value:
        text = _clean_text(raw)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _normalize_capabilities(value: Any) -> dict:
    source = value if isinstance(value, dict) else {}
    return {
        "skill_ids": _normalize_string_list(source.get("skill_ids")),
        "plugin_ids": _normalize_string_list(source.get("plugin_ids")),
    }


def _normalize_schedule(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    schedule = dict(value)
    return schedule


def _normalize_external_agent(value: Any) -> str:
    text = _clean_text(value).lower().replace("-", "_").replace(" ", "_")
    if text in {"claude", "claudecode", "claude_code"}:
        return "claude_code"
    if text == "codex":
        return "codex"
    return ""


def _normalize_pet_llm(value: Any) -> dict:
    """Per-sub-pet LLM override. Empty fields inherit the main config."""
    source = value if isinstance(value, dict) else {}
    return {
        "base_url": _clean_text(source.get("base_url")),
        "api_key": _clean_text(source.get("api_key")),
        "model": _clean_text(source.get("model")),
    }


def resolve_pet_llm_config(
    pet: Any,
    *,
    fallback_api_key: str = "",
    fallback_base_url: str = "",
    fallback_model: str = "",
) -> dict:
    """Resolve the effective LLM config for a pet task.

    Returns ``{"api_key", "base_url", "model", "is_override"}``. Empty pet
    fields inherit the fallbacks (the main window's live config).
    ``is_override`` is True only when the pet is a sub-pet with at least one
    non-empty llm field — callers use it to keep the exact legacy code path
    (shared service, no new instance) when False. External-agent pets
    (Codex / ClaudeCode) never override: they dispatch to local CLIs.
    """
    source = pet if isinstance(pet, dict) else {}
    llm = source.get("llm") if isinstance(source.get("llm"), dict) else {}
    base_url = _clean_text(llm.get("base_url"))
    api_key = _clean_text(llm.get("api_key"))
    model = _clean_text(llm.get("model"))
    is_sub = _clean_text(source.get("kind")).lower() == PET_KIND_SUB
    is_external = bool(_clean_text(source.get("external_agent")))
    is_override = is_sub and not is_external and bool(base_url or api_key or model)
    return {
        "api_key": api_key or fallback_api_key,
        "base_url": base_url or fallback_base_url,
        "model": model or fallback_model,
        "is_override": is_override,
    }


def is_fixed_default_pet(pet_id: str) -> bool:
    """Return True for built-in BUDDY system seats that cannot be removed."""
    return _clean_text(pet_id) in FIXED_DEFAULT_PET_IDS


def _normalize_stats(value: Any) -> dict:
    source = value if isinstance(value, dict) else {}
    return {
        "tasks_total": max(_coerce_int(source.get("tasks_total")), 0),
        "tasks_succeeded": max(_coerce_int(source.get("tasks_succeeded")), 0),
        "tasks_failed": max(_coerce_int(source.get("tasks_failed")), 0),
        "tools_used": max(_coerce_int(source.get("tools_used")), 0),
        "last_active_at": _clean_text(source.get("last_active_at")),
    }


def _normalize_activity_entry(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    title = _clean_text(value.get("title"))
    if not title:
        return None
    outcome = _clean_text(value.get("outcome")).lower()
    if outcome not in VALID_OUTCOMES:
        outcome = "info"
    return {
        "ts": _clean_text(value.get("ts")) or _now_text(),
        "title": title,
        "outcome": outcome,
        "detail": _clean_text(value.get("detail")),
    }


def _normalize_activity_log(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    entries: list[dict] = []
    for raw in value:
        normalized = _normalize_activity_entry(raw)
        if normalized is not None:
            entries.append(normalized)
    if len(entries) > ACTIVITY_LOG_CAP:
        entries = entries[-ACTIVITY_LOG_CAP:]
    return entries


def _normalize_position(value: Any) -> dict:
    if not isinstance(value, dict):
        return dict(DEFAULT_FLOATING_POSITION)
    return {
        "x": _coerce_int(value.get("x"), DEFAULT_FLOATING_POSITION["x"]),
        "y": _coerce_int(value.get("y"), DEFAULT_FLOATING_POSITION["y"]),
    }


def _normalize_pet_item(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None

    kind = _clean_text(item.get("kind")).lower()
    if kind not in VALID_PET_KINDS:
        return None

    name = _clean_text(item.get("name"))
    if not name:
        name = "主宠" if kind == PET_KIND_MAIN else "副宠"

    pet_id = _clean_text(item.get("id")) or _build_pet_id(name, kind)
    pet_id = _slugify(pet_id, fallback=str(uuid.uuid4()))

    imported_at = _clean_text(item.get("imported_at")) or _now_text()
    updated_at = _clean_text(item.get("updated_at")) or imported_at

    avatar_path = _clean_text(item.get("avatar_path"))
    raw_sprites = item.get("sprites")
    if not isinstance(raw_sprites, dict):
        raw_sprites = {}
    sprite_idle = _clean_text(raw_sprites.get("idle")) or avatar_path
    sprite_working = _clean_text(raw_sprites.get("working"))
    sprite_moving = _clean_text(raw_sprites.get("moving"))
    if not avatar_path:
        avatar_path = sprite_idle

    external_agent = _normalize_external_agent(item.get("external_agent")) if kind == PET_KIND_SUB else ""

    normalized = {
        "id": pet_id,
        "kind": kind,
        "name": name,
        "avatar_path": avatar_path,
        "sprites": {
            "idle": sprite_idle,
            "working": sprite_working,
            "moving": sprite_moving,
        },
        "description": _clean_text(item.get("description") or item.get("summary")),
        "enabled": bool(item.get("enabled", True)),
        "persona_prompt": _clean_text(item.get("persona_prompt")),
        "external_agent": external_agent,
        # External-agent pets (Codex / ClaudeCode) dispatch to local CLIs and
        # never use the LLM — strip any llm override for them.
        "llm": _normalize_pet_llm(item.get("llm")) if kind == PET_KIND_SUB and not external_agent else {},
        "capabilities": _normalize_capabilities(item.get("capabilities")),
        "schedule": _normalize_schedule(item.get("schedule")) if kind == PET_KIND_SUB else {},
        "task_template": _clean_text(item.get("task_template")) if kind == PET_KIND_SUB else "",
        "stats": _normalize_stats(item.get("stats")),
        "activity_log": _normalize_activity_log(item.get("activity_log")),
        "imported_at": imported_at,
        "updated_at": updated_at,
    }
    return normalized


def normalize_pet_settings(app_settings: Any = None) -> dict:
    """Return a fully-normalised ``pets`` settings block.

    Accepts either a full ``app_settings`` dict or just the inner ``pets``
    dict.  Always returns the canonical shape with ``items`` sorted by
    ``updated_at`` (newest first), with main pets bubbled to the top.
    """
    source = app_settings if isinstance(app_settings, dict) else {}
    if "pets" in source and isinstance(source["pets"], (dict, list)):
        raw_pets = source["pets"]
    elif (
        "items" in source
        or "active_main_id" in source
        or "floating_pet_id" in source
        or "floating_enabled" in source
    ):
        raw_pets = source
    else:
        raw_pets = {}

    if isinstance(raw_pets, dict):
        raw_items = raw_pets.get("items") if isinstance(raw_pets.get("items"), list) else []
        active_main_id = _clean_text(raw_pets.get("active_main_id"))
        floating_pet_id = _clean_text(raw_pets.get("floating_pet_id"))
        floating_enabled = bool(raw_pets.get("floating_enabled", False))
        floating_position = _normalize_position(raw_pets.get("floating_position"))
        raw_desk_layout = raw_pets.get("desk_layout") if isinstance(raw_pets.get("desk_layout"), list) else []
    elif isinstance(raw_pets, list):
        raw_items = raw_pets
        active_main_id = ""
        floating_pet_id = ""
        floating_enabled = False
        floating_position = dict(DEFAULT_FLOATING_POSITION)
        raw_desk_layout = []
    else:
        raw_items = []
        active_main_id = ""
        floating_pet_id = ""
        floating_enabled = False
        floating_position = dict(DEFAULT_FLOATING_POSITION)
        raw_desk_layout = []

    items: list[dict] = []
    seen_ids: set[str] = set()
    for raw in raw_items:
        normalized = _normalize_pet_item(raw)
        if normalized is None:
            continue
        if normalized["id"] in seen_ids:
            continue
        seen_ids.add(normalized["id"])
        items.append(normalized)

    # Resolve / fix up active_main_id
    main_ids = [item["id"] for item in items if item.get("kind") == PET_KIND_MAIN]
    if active_main_id not in main_ids:
        active_main_id = main_ids[0] if main_ids else ""

    # Invariant: at most one main pet. If legacy / corrupted data has
    # multiple, keep ``active_main_id`` (or the first) as the sole main and
    # silently demote the rest to sub. This guarantees the singleton
    # contract even when other code paths skip the explicit demotion step.
    if len(main_ids) > 1:
        keeper = active_main_id or main_ids[0]
        demoted_any = False
        for item in items:
            if item.get("kind") == PET_KIND_MAIN and item.get("id") != keeper:
                item["kind"] = PET_KIND_SUB
                # Sub pets carry a schedule and task_template field; seed
                # them empty when demoting so they fit the sub shape.
                item.setdefault("schedule", {})
                item.setdefault("task_template", "")
                demoted_any = True
        if demoted_any:
            active_main_id = keeper

    items.sort(
        key=lambda entry: (
            0 if entry.get("kind") == PET_KIND_MAIN else 1,
            -_timestamp_sort_key(entry.get("updated_at")),
        ),
    )

    # Normalize the optional desk_layout: a list of pet_id strings keeping
    # only currently existing pets, deduplicated, length-capped to 9 slots.
    valid_ids = {item["id"] for item in items}
    if floating_pet_id not in valid_ids:
        floating_pet_id = active_main_id if active_main_id in valid_ids else (items[0]["id"] if items else "")
    desk_layout: list[str] = []
    seen_layout: set[str] = set()
    for raw in (raw_desk_layout or []):
        pid = _clean_text(raw)
        if pid and pid in valid_ids and pid not in seen_layout:
            desk_layout.append(pid)
            seen_layout.add(pid)
        if len(desk_layout) >= 9:
            break

    return {
        "active_main_id": active_main_id,
        "floating_pet_id": floating_pet_id,
        "floating_enabled": floating_enabled,
        "floating_position": floating_position,
        "items": items,
        "desk_layout": desk_layout,
    }


def build_default_pet_settings() -> dict:
    """Default BUDDY office layout for first-run settings.

    Keep this separate from ``normalize_pet_settings({})`` so users can delete
    or replace the defaults; an explicitly-saved empty ``pets.items`` list must
    stay empty instead of being re-seeded on every launch.
    """
    stamp = "2026-01-01 00:00:00"
    return normalize_pet_settings({
        "items": [
            {
                "id": DEFAULT_MAIN_PET_ID,
                "kind": PET_KIND_MAIN,
                "name": "AudioMate",
                "description": "主工位，总控当前对话、Wwise、工具和子 Agent 调度。",
                "persona_prompt": "你是 AudioMate 主 Agent，负责理解用户目标、拆分任务，并把代码库重任务委派给合适的子 Agent。",
                "enabled": True,
                "imported_at": stamp,
                "updated_at": stamp,
            },
            {
                "id": DEFAULT_CODEX_PET_ID,
                "kind": PET_KIND_SUB,
                "name": "Codex",
                "description": "Codex CLI 子 Agent，适合代码审查、实现和仓库级修改建议。",
                "persona_prompt": (
                    "你是 Codex 外部编码子 Agent。优先处理代码库审查、补丁设计、实现计划和测试建议；"
                    "除非用户明确允许写入，否则不要修改文件。"
                ),
                "external_agent": "codex",
                "task_template": "检查当前 AudioMate 项目代码，报告高风险问题和建议；默认不要修改文件。",
                "enabled": True,
                "imported_at": stamp,
                "updated_at": stamp,
            },
            {
                "id": DEFAULT_CLAUDE_CODE_PET_ID,
                "kind": PET_KIND_SUB,
                "name": "ClaudeCode",
                "description": "Claude Code CLI 子 Agent，适合长上下文代码阅读、方案复核和第二意见。",
                "persona_prompt": (
                    "你是 Claude Code 外部编码子 Agent。擅长长上下文阅读、架构复核、风险评估和给主 Agent 第二意见；"
                    "除非用户明确允许写入，否则不要修改文件。"
                ),
                "external_agent": "claude_code",
                "task_template": "阅读当前 AudioMate 项目代码，给出架构风险和修复建议；默认不要修改文件。",
                "enabled": True,
                "imported_at": stamp,
                "updated_at": stamp,
            },
        ],
        "active_main_id": DEFAULT_MAIN_PET_ID,
        "floating_pet_id": DEFAULT_MAIN_PET_ID,
        "floating_enabled": False,
        "floating_position": dict(DEFAULT_FLOATING_POSITION),
        "desk_layout": [DEFAULT_CODEX_PET_ID, DEFAULT_CLAUDE_CODE_PET_ID],
    })


def seed_default_buddy_pets(pet_settings: Any) -> dict:
    """Merge fixed AudioMate/Codex/ClaudeCode desks into any BUDDY state.

    These are system seats: they are always present, keep their fixed roles,
    and serve as placeholders when the corresponding external CLI is missing.
    """
    raw_floating_pet_id = ""
    if isinstance(pet_settings, dict):
        raw_floating_pet_id = _clean_text(pet_settings.get("floating_pet_id"))
    normalized = normalize_pet_settings({"pets": pet_settings})
    defaults = build_default_pet_settings()
    default_by_id = {item["id"]: item for item in defaults.get("items", [])}
    source_items = [dict(item) for item in normalized.get("items", [])]
    items_by_id = {item.get("id"): dict(item) for item in source_items if item.get("id")}

    def merge_fixed(default_id: str, *, kind: str, external_agent: str = "") -> dict:
        default = dict(default_by_id[default_id])
        current = dict(items_by_id.get(default_id) or {})
        merged = {**default, **current}
        merged["id"] = default_id
        merged["kind"] = kind
        merged["name"] = default["name"]
        merged["description"] = default["description"]
        merged["persona_prompt"] = current.get("persona_prompt") or default.get("persona_prompt", "")
        merged["external_agent"] = external_agent if kind == PET_KIND_SUB else ""
        if kind == PET_KIND_SUB:
            merged["task_template"] = current.get("task_template") or default.get("task_template", "")
        else:
            merged["schedule"] = {}
            merged["task_template"] = ""
        return merged

    fixed_items = {
        DEFAULT_MAIN_PET_ID: merge_fixed(DEFAULT_MAIN_PET_ID, kind=PET_KIND_MAIN),
        DEFAULT_CODEX_PET_ID: merge_fixed(DEFAULT_CODEX_PET_ID, kind=PET_KIND_SUB, external_agent="codex"),
        DEFAULT_CLAUDE_CODE_PET_ID: merge_fixed(
            DEFAULT_CLAUDE_CODE_PET_ID,
            kind=PET_KIND_SUB,
            external_agent="claude_code",
        ),
    }

    user_items = []
    for item in source_items:
        pet_id = item.get("id")
        if pet_id in FIXED_DEFAULT_PET_IDS:
            continue
        user_item = dict(item)
        if user_item.get("kind") == PET_KIND_MAIN:
            user_item["kind"] = PET_KIND_SUB
            user_item.setdefault("schedule", {})
            user_item.setdefault("task_template", "")
        # Legacy placeholder main from earlier builds becomes redundant once
        # the fixed AudioMate seat exists.
        if _clean_text(user_item.get("name")) in {"主宠", "新主宠"}:
            continue
        user_items.append(user_item)

    existing_layout = list(normalized.get("desk_layout") or [])
    layout = []
    for pet_id in [DEFAULT_CODEX_PET_ID, DEFAULT_CLAUDE_CODE_PET_ID, *existing_layout]:
        if pet_id and pet_id != DEFAULT_MAIN_PET_ID and pet_id not in layout:
            layout.append(pet_id)

    return normalize_pet_settings({
        "items": [
            fixed_items[DEFAULT_MAIN_PET_ID],
            fixed_items[DEFAULT_CODEX_PET_ID],
            fixed_items[DEFAULT_CLAUDE_CODE_PET_ID],
            *user_items,
        ],
        "active_main_id": DEFAULT_MAIN_PET_ID,
        "floating_pet_id": raw_floating_pet_id or normalized.get("floating_pet_id") or DEFAULT_MAIN_PET_ID,
        "floating_enabled": normalized.get("floating_enabled"),
        "floating_position": normalized.get("floating_position"),
        "desk_layout": layout,
    })


def _timestamp_sort_key(value: Any) -> int:
    text = _clean_text(value)
    if not text:
        return 0
    try:
        return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").timestamp())
    except ValueError:
        try:
            return int(datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp())
        except ValueError:
            return 0


def build_pet_payload(pet_settings: Any) -> dict:
    """Return a settings dict suitable for persisting back to disk."""
    return normalize_pet_settings({"pets": pet_settings})


def upsert_pet_item(pet_settings: Any, pet_item: dict) -> dict:
    """Insert or replace a pet entry, returning a normalised settings dict.

    Refuses to insert a *new* main pet if one already exists — main is a
    singleton; promotion must go through ``change_pet_kind`` instead. (An
    existing main with the same id is still allowed; that is just an
    update.)
    """
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    normalized_item = _normalize_pet_item(pet_item)
    if normalized_item is None:
        return normalized_settings

    items = list(normalized_settings["items"])
    is_new_id = all(existing.get("id") != normalized_item["id"] for existing in items)
    if (
        is_new_id
        and normalized_item.get("kind") == PET_KIND_MAIN
        and any(existing.get("kind") == PET_KIND_MAIN for existing in items)
    ):
        # Reject silently; the UI guards against this so reaching this path
        # implies a programmer bug or a race. Returning the unchanged state
        # avoids creating a second main behind the user's back.
        return normalized_settings

    replaced = False
    for index, existing in enumerate(items):
        if existing.get("id") == normalized_item["id"]:
            normalized_item["imported_at"] = existing.get("imported_at") or normalized_item["imported_at"]
            # Preserve runtime stats / activity if caller did not supply them.
            if not pet_item.get("stats"):
                normalized_item["stats"] = existing.get("stats", normalized_item["stats"])
            if "activity_log" not in pet_item:
                normalized_item["activity_log"] = existing.get("activity_log", [])
            normalized_item["updated_at"] = _now_text()
            items[index] = normalized_item
            replaced = True
            break

    if not replaced:
        normalized_item["updated_at"] = _now_text()
        items.insert(0, normalized_item)

    rebuilt = normalize_pet_settings(
        {
            "pets": {
                "items": items,
                "active_main_id": normalized_settings.get("active_main_id"),
                "floating_pet_id": normalized_settings.get("floating_pet_id"),
                "floating_enabled": normalized_settings.get("floating_enabled"),
                "floating_position": normalized_settings.get("floating_position"),
                "desk_layout": normalized_settings.get("desk_layout") or [],
            }
        }
    )

    # If the new entry is the first main pet, mark it active.
    if normalized_item["kind"] == PET_KIND_MAIN and not rebuilt["active_main_id"]:
        rebuilt["active_main_id"] = normalized_item["id"]
    elif normalized_item["kind"] == PET_KIND_MAIN and not replaced and not normalized_settings.get("active_main_id"):
        rebuilt["active_main_id"] = normalized_item["id"]
    return rebuilt


def remove_pet_item(pet_settings: Any, pet_id: str) -> dict:
    """Remove a pet by ``id`` and return the normalised settings."""
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    target = _clean_text(pet_id)
    if is_fixed_default_pet(target):
        return seed_default_buddy_pets(normalized_settings)
    items = [item for item in normalized_settings["items"] if item.get("id") != target]
    active_main_id = normalized_settings.get("active_main_id")
    if active_main_id == target:
        active_main_id = ""
    return normalize_pet_settings(
        {
            "pets": {
                "items": items,
                "active_main_id": active_main_id,
                "floating_pet_id": (
                    active_main_id
                    if normalized_settings.get("floating_pet_id") == target
                    else normalized_settings.get("floating_pet_id")
                ),
                "floating_enabled": normalized_settings.get("floating_enabled"),
                "floating_position": normalized_settings.get("floating_position"),
                "desk_layout": [pid for pid in (normalized_settings.get("desk_layout") or []) if pid != target],
            }
        }
    )


def update_pet_item(pet_settings: Any, pet_id: str, **updates: Any) -> dict:
    """Patch a pet entry with arbitrary fields, returning normalised settings."""
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    target = _clean_text(pet_id)
    if not target:
        return normalized_settings

    items: list[dict] = []
    for item in normalized_settings["items"]:
        if item.get("id") == target:
            merged = dict(item)
            for key, value in updates.items():
                if key == "id":
                    continue
                merged[key] = value
            merged["updated_at"] = _now_text()
            normalized = _normalize_pet_item(merged)
            if normalized is not None:
                items.append(normalized)
        else:
            items.append(item)
    return normalize_pet_settings(
        {
            "pets": {
                "items": items,
                "active_main_id": normalized_settings.get("active_main_id"),
                "floating_pet_id": normalized_settings.get("floating_pet_id"),
                "floating_enabled": normalized_settings.get("floating_enabled"),
                "floating_position": normalized_settings.get("floating_position"),
                "desk_layout": normalized_settings.get("desk_layout") or [],
            }
        }
    )


def change_pet_kind(pet_settings: Any, pet_id: str, kind: str) -> dict:
    """Promote a sub-pet to main, or demote a main-pet to sub.

    Enforces the singleton-main invariant: promoting any pet to main first
    demotes every other current main to sub. Demoting the active main
    simply clears the active pointer (or transfers it if some race left
    another main behind).
    """
    new_kind = (kind or "").strip().lower()
    if new_kind not in VALID_PET_KINDS:
        return normalize_pet_settings({"pets": pet_settings})
    target = _clean_text(pet_id)
    if not target:
        return normalize_pet_settings({"pets": pet_settings})
    if is_fixed_default_pet(target):
        return seed_default_buddy_pets(pet_settings)

    normalized_current = normalize_pet_settings({"pets": pet_settings})
    has_fixed_main = any(
        item.get("id") == DEFAULT_MAIN_PET_ID and item.get("kind") == PET_KIND_MAIN
        for item in normalized_current.get("items", [])
    )
    if new_kind == PET_KIND_MAIN and has_fixed_main:
        return seed_default_buddy_pets(normalized_current)

    if new_kind == PET_KIND_MAIN:
        # Atomic swap: demote every other main → sub, then promote target.
        normalized = normalized_current
        items: list[dict] = []
        for item in normalized.get("items", []):
            entry = dict(item)
            if entry.get("id") != target and entry.get("kind") == PET_KIND_MAIN:
                entry["kind"] = PET_KIND_SUB
                entry.setdefault("schedule", {})
                entry.setdefault("task_template", "")
            elif entry.get("id") == target:
                entry["kind"] = PET_KIND_MAIN
            items.append(entry)
        rebuilt = normalize_pet_settings(
            {
                "pets": {
                    "items": items,
                    "active_main_id": target,
                    "floating_pet_id": normalized.get("floating_pet_id"),
                    "floating_enabled": normalized.get("floating_enabled"),
                    "floating_position": normalized.get("floating_position"),
                    "desk_layout": normalized.get("desk_layout") or [],
                }
            }
        )
        # Force the active pointer even if normalize tried to keep a stale one.
        rebuilt["active_main_id"] = target
        return rebuilt

    # new_kind == sub: standard demotion.
    normalized = update_pet_item(normalized_current, pet_id, kind=new_kind)
    main_ids = [item["id"] for item in normalized["items"] if item.get("kind") == PET_KIND_MAIN]
    if normalized.get("active_main_id") == target:
        fallback = main_ids[0] if main_ids else ""
        normalized = set_active_main(normalized, fallback)
    return normalized


def set_desk_layout(pet_settings: Any, layout: list) -> dict:
    """Persist a custom desk ordering (list of pet_id strings)."""
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    return normalize_pet_settings(
        {
            "pets": {
                "items": normalized_settings["items"],
                "active_main_id": normalized_settings.get("active_main_id"),
                "floating_pet_id": normalized_settings.get("floating_pet_id"),
                "floating_enabled": normalized_settings.get("floating_enabled"),
                "floating_position": normalized_settings.get("floating_position"),
                "desk_layout": list(layout or []),
            }
        }
    )


def set_active_main(pet_settings: Any, pet_id: str) -> dict:
    """Mark a main-pet ``pet_id`` as active.  Falls back if the id is invalid."""
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    target = _clean_text(pet_id)
    main_ids = [item["id"] for item in normalized_settings["items"] if item.get("kind") == PET_KIND_MAIN]
    if target in main_ids:
        normalized_settings["active_main_id"] = target
    elif main_ids:
        normalized_settings["active_main_id"] = main_ids[0]
    else:
        normalized_settings["active_main_id"] = ""
    return normalized_settings


def set_floating_state(
    pet_settings: Any,
    *,
    enabled: bool | None = None,
    position: dict | None = None,
) -> dict:
    """Update floating-window enable flag and/or remembered position."""
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    if enabled is not None:
        normalized_settings["floating_enabled"] = bool(enabled)
    if position is not None:
        normalized_settings["floating_position"] = _normalize_position(position)
    return normalized_settings


def set_floating_pet(pet_settings: Any, pet_id: str) -> dict:
    """Choose which configured pet appears in the desktop floating window."""
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    target = _clean_text(pet_id)
    valid_ids = {item.get("id") for item in normalized_settings.get("items", [])}
    if target in valid_ids:
        normalized_settings["floating_pet_id"] = target
    return normalize_pet_settings({"pets": normalized_settings})


def record_pet_activity(pet_settings: Any, pet_id: str, entry: dict) -> dict:
    """Append an activity entry and bump the matching stats counters.

    ``entry`` should at minimum contain ``title``.  ``outcome`` should be one
    of ``success / fail / cancel / info`` — any other value collapses to
    ``info``.  ``tool_count`` (optional int) accumulates into
    ``stats.tools_used``.
    """
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    target = _clean_text(pet_id)
    if not target:
        return normalized_settings

    normalized_entry = _normalize_activity_entry(entry)
    if normalized_entry is None:
        return normalized_settings

    tool_count = max(_coerce_int((entry or {}).get("tool_count")), 0)
    outcome = normalized_entry["outcome"]

    items: list[dict] = []
    for item in normalized_settings["items"]:
        if item.get("id") != target:
            items.append(item)
            continue

        new_log = list(item.get("activity_log", []))
        new_log.append(normalized_entry)
        if len(new_log) > ACTIVITY_LOG_CAP:
            new_log = new_log[-ACTIVITY_LOG_CAP:]

        stats = dict(item.get("stats") or {})
        stats["tasks_total"] = _coerce_int(stats.get("tasks_total")) + 1
        if outcome == "success":
            stats["tasks_succeeded"] = _coerce_int(stats.get("tasks_succeeded")) + 1
        elif outcome == "fail":
            stats["tasks_failed"] = _coerce_int(stats.get("tasks_failed")) + 1
        if tool_count:
            stats["tools_used"] = _coerce_int(stats.get("tools_used")) + tool_count
        stats["last_active_at"] = normalized_entry["ts"]

        merged = dict(item)
        merged["activity_log"] = new_log
        merged["stats"] = _normalize_stats(stats)
        merged["updated_at"] = _now_text()
        items.append(merged)

    return normalize_pet_settings(
        {
            "pets": {
                "items": items,
                "active_main_id": normalized_settings.get("active_main_id"),
                "floating_pet_id": normalized_settings.get("floating_pet_id"),
                "floating_enabled": normalized_settings.get("floating_enabled"),
                "floating_position": normalized_settings.get("floating_position"),
                "desk_layout": normalized_settings.get("desk_layout") or [],
            }
        }
    )


def find_pet(pet_settings: Any, pet_id: str) -> dict | None:
    """Return the pet entry with ``pet_id`` or ``None``."""
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    target = _clean_text(pet_id)
    for item in normalized_settings["items"]:
        if item.get("id") == target:
            return item
    return None


def list_sub_pets(pet_settings: Any) -> list[dict]:
    """Return only the sub-pets, in display order."""
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    return [item for item in normalized_settings["items"] if item.get("kind") == PET_KIND_SUB]


def list_main_pets(pet_settings: Any) -> list[dict]:
    """Return only the main-pets, in display order."""
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    return [item for item in normalized_settings["items"] if item.get("kind") == PET_KIND_MAIN]


def get_active_main(pet_settings: Any) -> dict | None:
    """Return the currently-active main pet, or ``None`` if none configured."""
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    active_id = normalized_settings.get("active_main_id")
    if not active_id:
        for item in normalized_settings["items"]:
            if item.get("kind") == PET_KIND_MAIN:
                return item
        return None
    return find_pet(normalized_settings, active_id)


def get_floating_pet(pet_settings: Any) -> dict | None:
    """Return the pet currently selected for the desktop floating window."""
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    floating_id = normalized_settings.get("floating_pet_id") or ""
    if floating_id:
        pet = find_pet(normalized_settings, floating_id)
        if pet is not None:
            return pet
    return get_active_main(normalized_settings)


def _collect_id_set(items: Any) -> set[str]:
    """Helper: pick the ``id`` field out of an iterable of dicts (or strings)."""
    out: set[str] = set()
    if not items:
        return out
    for item in items:
        if isinstance(item, dict):
            ident = _clean_text(item.get("id"))
        else:
            ident = _clean_text(item)
        if ident:
            out.add(ident)
    return out


def bound_capability_owners(pet_settings: Any) -> dict:
    """Map every explicitly-bound skill/plugin id to its owner pet info.

    Returns ``{"skills": {skill_id: {pet_id, pet_name}}, "plugins": {...}}``.
    Useful for the training-room UI to grey out items already claimed by
    another pet.
    """
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    skills_map: dict[str, dict] = {}
    plugins_map: dict[str, dict] = {}
    for pet in normalized_settings.get("items", []):
        owner = {"pet_id": pet.get("id", ""), "pet_name": pet.get("name", "")}
        caps = pet.get("capabilities") or {}
        for sid in caps.get("skill_ids") or []:
            sid = _clean_text(sid)
            if sid and sid not in skills_map:
                skills_map[sid] = owner
        for pid in caps.get("plugin_ids") or []:
            pid = _clean_text(pid)
            if pid and pid not in plugins_map:
                plugins_map[pid] = owner
    return {"skills": skills_map, "plugins": plugins_map}


def list_orphan_capabilities(pet_settings: Any, all_skills: Any, all_plugins: Any) -> dict:
    """Return skill/plugin ids that no pet has explicitly bound."""
    all_skill_ids = _collect_id_set(all_skills)
    all_plugin_ids = _collect_id_set(all_plugins)
    bound = bound_capability_owners(pet_settings)
    orphan_skills = sorted(all_skill_ids - set(bound["skills"].keys()))
    orphan_plugins = sorted(all_plugin_ids - set(bound["plugins"].keys()))
    return {"skill_ids": orphan_skills, "plugin_ids": orphan_plugins}


def resolve_pet_capabilities(
    pet_settings: Any,
    pet_id: str,
    all_skills: Any,
    all_plugins: Any,
) -> dict:
    """Compute the skill/plugin id sets a pet actually owns at runtime.

    Rules:
    - Skills/plugins explicitly bound to ``pet_id`` always belong to it.
    - Orphan capabilities (bound to no pet) implicitly belong to the active
      main pet only.
    - Capabilities bound to another pet never appear in this pet's set.
    """
    normalized_settings = normalize_pet_settings({"pets": pet_settings})
    target_id = _clean_text(pet_id)
    pet = find_pet(normalized_settings, target_id) if target_id else None
    caps = (pet or {}).get("capabilities") or {}
    own_skills = set(_clean_text(s) for s in (caps.get("skill_ids") or []) if _clean_text(s))
    own_plugins = set(_clean_text(p) for p in (caps.get("plugin_ids") or []) if _clean_text(p))

    active_main_id = normalized_settings.get("active_main_id") or ""
    is_active_main = bool(target_id) and target_id == active_main_id
    if is_active_main:
        orphans = list_orphan_capabilities(normalized_settings, all_skills, all_plugins)
        own_skills |= set(orphans["skill_ids"])
        own_plugins |= set(orphans["plugin_ids"])

    return {
        "skill_ids": sorted(own_skills),
        "plugin_ids": sorted(own_plugins),
    }

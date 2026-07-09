import json
import os
import re
import uuid
from datetime import datetime


PLUGIN_MANIFEST_FILENAME = "plugin.json"
AVAILABLE_PLUGIN_STATUSES = {"discovered", "loaded", "initialized", "registered", "ready", ""}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _clean_text(value) -> str:
    return str(value or "").strip()


def _normalize_dir(path_value) -> str:
    raw_path = _clean_text(path_value)
    if not raw_path:
        return ""
    return os.path.abspath(raw_path)


def _slugify(text: str, fallback: str = "plugin") -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return cleaned or fallback


def _build_plugin_id(name: str, source_dir: str) -> str:
    seed = f"{name}|{source_dir}".strip("|")
    if seed:
        return _slugify(seed, fallback=str(uuid.uuid4()))
    return str(uuid.uuid4())


def _read_manifest(directory: str) -> dict | None:
    manifest_path = os.path.join(directory, PLUGIN_MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        return None
    with open(manifest_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else None


def _normalize_tools(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    tools = []
    seen = set()
    for raw_tool in value:
        if isinstance(raw_tool, str):
            tool = {"name": raw_tool, "description": ""}
        elif isinstance(raw_tool, dict):
            tool = dict(raw_tool)
        else:
            continue
        name = _slugify(tool.get("name"), fallback="")
        if not name or name in seen:
            continue
        seen.add(name)
        tools.append({
            "name": name,
            "description": _clean_text(tool.get("description") or tool.get("summary")),
            "function": _clean_text(tool.get("function") or name),
            "read_only": bool(tool.get("read_only", False)),
        })
    return tools


def _safe_entry_path(source_dir: str, entry: str) -> str:
    entry_text = _clean_text(entry) or "plugin.py"
    entry_path = os.path.abspath(os.path.join(source_dir, entry_text))
    source_root = os.path.abspath(source_dir)
    if os.path.commonpath([source_root, entry_path]) != source_root:
        raise ValueError("Plugin entry 不能指向插件目录之外")
    if not entry_path.lower().endswith(".py"):
        raise ValueError("Plugin entry 必须是 .py 文件")
    return entry_path


def _normalize_plugin_item(item) -> dict | None:
    if not isinstance(item, dict):
        return None

    source_dir = _normalize_dir(item.get("source_dir") or item.get("path"))
    name = _clean_text(item.get("name") or item.get("title"))
    if not name:
        name = os.path.basename(source_dir) if source_dir else ""
    if not name:
        return None

    entry = _clean_text(item.get("entry")) or "plugin.py"
    entry_path = ""
    status = _clean_text(item.get("status"))
    error = _clean_text(item.get("error"))
    if source_dir and os.path.isdir(source_dir):
        try:
            entry_path = _safe_entry_path(source_dir, entry)
            if not os.path.isfile(entry_path):
                status = status or "missing"
        except ValueError as exc:
            status = "failed"
            error = str(exc)
    else:
        status = status or "missing"

    if not status:
        status = "discovered"

    plugin_id = _clean_text(item.get("id")) or _build_plugin_id(name, source_dir)
    imported_at = _clean_text(item.get("imported_at")) or _now_text()
    updated_at = _clean_text(item.get("updated_at")) or imported_at

    return {
        "id": _slugify(plugin_id, fallback=str(uuid.uuid4())),
        "name": name,
        "description": _clean_text(item.get("description") or item.get("summary")),
        "version": _clean_text(item.get("version")) or "1.0.0",
        "source_dir": source_dir,
        "entry": os.path.relpath(entry_path, source_dir) if entry_path and source_dir else entry,
        "source": item.get("source") if isinstance(item.get("source"), dict) else {},
        "enabled": bool(item.get("enabled", True)),
        "imported_at": imported_at,
        "updated_at": updated_at,
        "status": status,
        "error": error,
        "tools": _normalize_tools(item.get("tools")),
    }


def normalize_plugin_settings(app_settings=None) -> dict:
    source = app_settings if isinstance(app_settings, dict) else {}
    raw_plugins = source.get("plugins")
    if isinstance(raw_plugins, dict):
        raw_items = raw_plugins.get("items") if isinstance(raw_plugins.get("items"), list) else []
    elif isinstance(raw_plugins, list):
        raw_items = raw_plugins
    else:
        raw_items = []

    items = []
    seen_ids = set()
    seen_dirs = set()
    for raw_item in raw_items:
        normalized = _normalize_plugin_item(raw_item)
        if normalized is None:
            continue
        plugin_id = normalized["id"]
        source_dir = normalized["source_dir"]
        if plugin_id in seen_ids:
            continue
        if source_dir and source_dir in seen_dirs:
            continue
        seen_ids.add(plugin_id)
        if source_dir:
            seen_dirs.add(source_dir)
        items.append(normalized)

    items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return {"items": items}


def build_plugin_payload(plugin_settings) -> dict:
    return normalize_plugin_settings({"plugins": plugin_settings})


def upsert_plugin_item(plugin_settings, plugin_item: dict) -> dict:
    normalized_settings = normalize_plugin_settings({"plugins": plugin_settings})
    normalized_item = _normalize_plugin_item(plugin_item)
    if normalized_item is None:
        return normalized_settings

    items = normalized_settings["items"]
    replaced = False
    for index, existing in enumerate(items):
        same_id = existing.get("id") == normalized_item.get("id")
        same_dir = existing.get("source_dir") and existing.get("source_dir") == normalized_item.get("source_dir")
        if same_id or same_dir:
            normalized_item["imported_at"] = existing.get("imported_at") or normalized_item.get("imported_at")
            normalized_item["updated_at"] = _now_text()
            items[index] = normalized_item
            replaced = True
            break

    if not replaced:
        normalized_item["updated_at"] = _now_text()
        items.insert(0, normalized_item)
    return normalize_plugin_settings({"plugins": {"items": items}})


def remove_plugin_item(plugin_settings, plugin_id: str) -> dict:
    normalized_settings = normalize_plugin_settings({"plugins": plugin_settings})
    return {"items": [item for item in normalized_settings["items"] if item.get("id") != plugin_id]}


def update_plugin_item(plugin_settings, plugin_id: str, **updates) -> dict:
    normalized_settings = normalize_plugin_settings({"plugins": plugin_settings})
    items = []
    for item in normalized_settings["items"]:
        if item.get("id") == plugin_id:
            merged = dict(item)
            merged.update(updates)
            merged["updated_at"] = _now_text()
            normalized = _normalize_plugin_item(merged)
            if normalized is not None:
                items.append(normalized)
        else:
            items.append(item)
    return normalize_plugin_settings({"plugins": {"items": items}})


def import_plugin_directory(directory: str) -> dict:
    source_dir = _normalize_dir(directory)
    if not source_dir:
        raise ValueError("请选择 Plugin 目录")
    if not os.path.isdir(source_dir):
        raise ValueError("所选路径不是有效目录")

    manifest = _read_manifest(source_dir)
    if not manifest:
        raise ValueError("目录内缺少 plugin.json")

    name = _clean_text(manifest.get("name")) or os.path.basename(source_dir)
    entry = _clean_text(manifest.get("entry")) or "plugin.py"
    entry_path = _safe_entry_path(source_dir, entry)
    if not os.path.isfile(entry_path):
        raise ValueError(f"Plugin entry 不存在: {entry}")

    imported_at = _now_text()
    return {
        "id": _clean_text(manifest.get("id")) or _build_plugin_id(name, source_dir),
        "name": name,
        "description": _clean_text(manifest.get("description") or manifest.get("summary")),
        "version": _clean_text(manifest.get("version")) or "1.0.0",
        "source_dir": source_dir,
        "entry": entry,
        "source": manifest.get("source") if isinstance(manifest.get("source"), dict) else {},
        "enabled": True,
        "imported_at": imported_at,
        "updated_at": imported_at,
        "status": "discovered",
        "error": "",
        "tools": _normalize_tools(manifest.get("tools")),
    }

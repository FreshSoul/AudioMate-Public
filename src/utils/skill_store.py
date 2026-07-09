import json
import os
import re
import uuid
from datetime import datetime


MANIFEST_CANDIDATES = (
    "skill.json",
    "manifest.json",
    "skill_manifest.json",
)
SKILL_MARKDOWN_FILENAME = "SKILL.md"
AVAILABLE_SKILL_STATUSES = {"ready", "loaded", "active", ""}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _clean_text(value) -> str:
    return str(value or "").strip()


def _normalize_dir(path_value) -> str:
    raw_path = _clean_text(path_value)
    if not raw_path:
        return ""
    return os.path.abspath(raw_path)


def _build_skill_id(name: str, source_dir: str) -> str:
    seed = f"{name}|{source_dir}".strip("|")
    if seed:
        return re.sub(r"[^a-z0-9]+", "-", seed.lower()).strip("-") or str(uuid.uuid4())
    return str(uuid.uuid4())


def _normalize_skill_item(item) -> dict | None:
    if not isinstance(item, dict):
        return None

    name = _clean_text(item.get("name")) or _clean_text(item.get("title"))
    source_dir = _normalize_dir(item.get("source_dir") or item.get("path"))
    description = _clean_text(item.get("description") or item.get("summary"))
    skill_id = _clean_text(item.get("id")) or _build_skill_id(name or os.path.basename(source_dir), source_dir)
    imported_at = _clean_text(item.get("imported_at")) or _now_text()
    updated_at = _clean_text(item.get("updated_at")) or imported_at

    if not name:
        if source_dir:
            name = os.path.basename(source_dir)
        else:
            return None

    status = _clean_text(item.get("status"))
    if not status:
        status = "ready" if source_dir and os.path.isdir(source_dir) else "missing"

    return {
        "id": skill_id,
        "name": name,
        "description": description,
        "source_dir": source_dir,
        "source": item.get("source") if isinstance(item.get("source"), dict) else {},
        "enabled": bool(item.get("enabled", True)),
        "imported_at": imported_at,
        "updated_at": updated_at,
        "status": status,
    }


def normalize_skill_settings(app_settings=None) -> dict:
    source = app_settings if isinstance(app_settings, dict) else {}
    raw_skills = source.get("skills")

    if isinstance(raw_skills, dict):
        raw_items = raw_skills.get("items") if isinstance(raw_skills.get("items"), list) else []
    elif isinstance(raw_skills, list):
        raw_items = raw_skills
    else:
        raw_items = []

    items = []
    seen_ids = set()
    seen_dirs = set()
    for raw_item in raw_items:
        normalized = _normalize_skill_item(raw_item)
        if normalized is None:
            continue

        skill_id = normalized["id"]
        source_dir = normalized["source_dir"]
        if skill_id in seen_ids:
            continue
        if source_dir and source_dir in seen_dirs:
            continue

        seen_ids.add(skill_id)
        if source_dir:
            seen_dirs.add(source_dir)
        items.append(normalized)

    items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return {"items": items}


def build_skill_payload(skill_settings) -> dict:
    return normalize_skill_settings({"skills": skill_settings})


def upsert_skill_item(skill_settings, skill_item: dict) -> dict:
    normalized_settings = normalize_skill_settings({"skills": skill_settings})
    normalized_item = _normalize_skill_item(skill_item)
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

    return normalize_skill_settings({"skills": {"items": items}})


def remove_skill_item(skill_settings, skill_id: str) -> dict:
    normalized_settings = normalize_skill_settings({"skills": skill_settings})
    items = [item for item in normalized_settings["items"] if item.get("id") != skill_id]
    return {"items": items}


def update_skill_item(skill_settings, skill_id: str, **updates) -> dict:
    normalized_settings = normalize_skill_settings({"skills": skill_settings})
    items = []
    for item in normalized_settings["items"]:
        if item.get("id") == skill_id:
            merged = dict(item)
            merged.update(updates)
            merged["updated_at"] = _now_text()
            normalized = _normalize_skill_item(merged)
            if normalized is not None:
                items.append(normalized)
        else:
            items.append(item)
    return normalize_skill_settings({"skills": {"items": items}})


def _read_json_manifest(directory: str) -> dict | None:
    for filename in MANIFEST_CANDIDATES:
        manifest_path = os.path.join(directory, filename)
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"[SkillStore] Ignoring invalid manifest {manifest_path}: {exc}")
            continue
        if isinstance(data, dict):
            return data
    return None


def _parse_frontmatter(lines: list[str]) -> dict:
    metadata = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")
    return metadata


def _read_skill_markdown(directory: str) -> dict | None:
    skill_md_path = os.path.join(directory, SKILL_MARKDOWN_FILENAME)
    if not os.path.isfile(skill_md_path):
        return None

    with open(skill_md_path, "r", encoding="utf-8") as handle:
        content = handle.read()

    metadata = {}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            metadata.update(_parse_frontmatter(parts[1].splitlines()))
            content = parts[2]

    if not metadata.get("name"):
        heading_match = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
        if heading_match:
            metadata["name"] = heading_match.group(1).strip()

    if not metadata.get("description"):
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            metadata["description"] = line
            break

    return metadata or None


def _read_skill_markdown_text(directory: str) -> str:
    skill_md_path = os.path.join(directory, SKILL_MARKDOWN_FILENAME)
    if not os.path.isfile(skill_md_path):
        return ""
    try:
        with open(skill_md_path, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return ""


def _strip_markdown_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    return parts[2].strip()


def _strip_code_fences(text: str) -> str:
    return re.sub(r"```[\s\S]*?```", "", text or "")


def _normalize_query_text(text: str) -> str:
    return _clean_text(text).casefold()


def _tokenize_query(text: str) -> list[str]:
    normalized = _normalize_query_text(text)
    if not normalized:
        return []
    tokens = re.findall(r"[a-z0-9_\-\.]{2,}|[\u4e00-\u9fff]{2,}", normalized)
    expanded_tokens = []
    for token in tokens:
        expanded_tokens.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", token):
            expanded_tokens.extend(token[index:index + 2] for index in range(len(token) - 1))
            expanded_tokens.extend(token[index:index + 3] for index in range(len(token) - 2))
    unique_tokens = []
    seen = set()
    for token in expanded_tokens:
        if token in seen:
            continue
        seen.add(token)
        unique_tokens.append(token)
    return unique_tokens


def _metadata_text(value) -> str:
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            key_text = _clean_text(key)
            item_text = _metadata_text(item)
            if key_text or item_text:
                parts.append(" ".join(part for part in (key_text, item_text) if part))
        return "\n".join(parts)
    if isinstance(value, list):
        return ", ".join(_metadata_text(item) for item in value if _metadata_text(item).strip())
    return _clean_text(value)


def _skill_runtime_text(skill_item: dict) -> str:
    source_dir = _normalize_dir(skill_item.get("source_dir"))
    if not source_dir or not os.path.isdir(source_dir):
        return ""

    markdown_text = _read_skill_markdown_text(source_dir)
    if markdown_text:
        markdown_text = _strip_code_fences(_strip_markdown_frontmatter(markdown_text))

    manifest = _read_json_manifest(source_dir) or {}
    manifest_parts = []
    for key in (
        "description", "summary", "instructions", "usage", "keywords",
        "triggers", "trigger_phrases", "use_cases", "domains", "tools",
        "plugins", "plugin_tools", "commands",
    ):
        value = manifest.get(key)
        text = _metadata_text(value)
        if text:
            manifest_parts.append(text)

    parts = [
        _clean_text(skill_item.get("name")),
        _clean_text(skill_item.get("description")),
        "\n".join(manifest_parts).strip(),
        markdown_text.strip(),
    ]
    return "\n\n".join(part for part in parts if part).strip()


def _is_available_skill(skill_item: dict) -> bool:
    return bool(skill_item.get("enabled")) and skill_item.get("status") in AVAILABLE_SKILL_STATUSES


def _score_skill_match(skill_item: dict, user_query: str) -> tuple[int, str, str]:
    runtime_text = _skill_runtime_text(skill_item)
    haystack = _normalize_query_text(runtime_text)
    if not haystack:
        return 0, "", ""

    score = 0
    reasons = []
    query_text = _normalize_query_text(user_query)
    if not query_text:
        return 0, runtime_text, ""

    name_text = _normalize_query_text(skill_item.get("name"))
    desc_text = _normalize_query_text(skill_item.get("description"))
    source_dir = _normalize_dir(skill_item.get("source_dir"))
    manifest = _read_json_manifest(source_dir) if source_dir else {}
    manifest_text = _normalize_query_text(_metadata_text(manifest))
    keyword_text = _normalize_query_text(_metadata_text((manifest or {}).get("keywords")))
    trigger_text = _normalize_query_text(_metadata_text((manifest or {}).get("triggers") or (manifest or {}).get("trigger_phrases")))
    usage_text = _normalize_query_text(_metadata_text((manifest or {}).get("usage") or (manifest or {}).get("use_cases") or (manifest or {}).get("instructions")))

    if query_text and query_text in name_text:
        score += 24
        reasons.append("完整请求命中名称")
    elif query_text and query_text in desc_text:
        score += 18
        reasons.append("完整请求命中描述")
    elif query_text and query_text in trigger_text:
        score += 18
        reasons.append("完整请求命中触发词")
    elif query_text and query_text in keyword_text:
        score += 16
        reasons.append("完整请求命中关键词")
    elif query_text and query_text in haystack:
        score += 8
        reasons.append("完整请求命中 Skill 内容")

    matched_tokens = []
    for token in _tokenize_query(user_query):
        if token in name_text:
            score += 10
            matched_tokens.append(f"名称:{token}")
        elif token in desc_text:
            score += 7
            matched_tokens.append(f"描述:{token}")
        elif token in trigger_text:
            score += 9
            matched_tokens.append(f"触发词:{token}")
        elif token in keyword_text:
            score += 8
            matched_tokens.append(f"关键词:{token}")
        elif token in usage_text:
            score += 4
            matched_tokens.append(f"用法:{token}")
        elif token in manifest_text:
            score += 3
            matched_tokens.append(f"元数据:{token}")
        elif token in haystack:
            score += 1
            if len(matched_tokens) < 8:
                matched_tokens.append(f"正文:{token}")

    if matched_tokens:
        reasons.append("命中 " + ", ".join(matched_tokens[:8]))

    return score, runtime_text, "; ".join(reasons)


def build_skill_prompt_guidance(
    app_settings,
    user_query: str,
    max_skills: int = 3,
    excerpt_chars: int = 2200,
    forced_skill_id: str | None = None,
    forced_excerpt_chars: int = 3200,
) -> str:
    normalized = normalize_skill_settings(app_settings)
    blocks = []
    forced_id = _clean_text(forced_skill_id)
    forced_included_id = ""

    if forced_id:
        for skill_item in normalized.get("items", []):
            if skill_item.get("id") != forced_id or not _is_available_skill(skill_item):
                continue
            runtime_text = _skill_runtime_text(skill_item)
            if not runtime_text:
                continue
            excerpt = runtime_text[:forced_excerpt_chars].strip()
            forced_included_id = forced_id
            blocks.append(
                "\nFORCED ACTIVE SKILL GUIDANCE:\n"
                "- The user selected this imported skill for the current turn.\n"
                "- You must apply this skill when answering or executing this request.\n"
                "- Other enabled skills may still be used only when materially relevant.\n"
                "- Do not mention hidden skill loading mechanics to the user unless explicitly asked.\n"
                f"\n[Forced Skill: {skill_item.get('name', '')}]\n"
                f"Description: {skill_item.get('description', '')}\n"
                f"Source directory: {skill_item.get('source_dir', '')}\n"
                "Skill content:\n"
                f"{excerpt}\n"
            )
            break

    matched = []
    for skill_item in normalized.get("items", []):
        if not _is_available_skill(skill_item):
            continue
        if forced_included_id and skill_item.get("id") == forced_included_id:
            continue
        score, runtime_text, reason = _score_skill_match(skill_item, user_query)
        if score <= 0 or not runtime_text:
            continue
        matched.append((score, skill_item, runtime_text, reason))

    matched.sort(key=lambda item: item[0], reverse=True)
    if matched:
        top_score = matched[0][0]
        min_score = max(8, int(top_score * 0.35))
        matched = [item for item in matched if item[0] >= min_score][:max_skills]
    if not matched:
        return "".join(blocks).strip() + ("\n\n" if blocks else "")

    blocks.append(
        "\nACTIVE SKILL GUIDANCE:\n"
        "- The following imported skills are enabled and relevant to the latest user request.\n"
        "- Use them only when they materially help answer or execute the request.\n"
        "- Do not mention hidden skill loading mechanics to the user unless explicitly asked.\n"
    )
    for score, skill_item, runtime_text, reason in matched:
        excerpt = runtime_text[:excerpt_chars].strip()
        blocks.append(
            f"\n[Skill: {skill_item.get('name', '')}]\n"
            f"Description: {skill_item.get('description', '')}\n"
            f"Source directory: {skill_item.get('source_dir', '')}\n"
            f"Relevance score: {score}\n"
            f"Matched because: {reason or 'query terms matched this skill'}\n"
            "Skill content:\n"
            f"{excerpt}\n"
        )
    return "".join(blocks).strip() + "\n\n"


def import_skill_directory(directory: str) -> dict:
    source_dir = _normalize_dir(directory)
    if not source_dir:
        raise ValueError("请选择 Skill 目录")
    if not os.path.isdir(source_dir):
        raise ValueError("所选路径不是有效目录")

    metadata = _read_json_manifest(source_dir) or _read_skill_markdown(source_dir)
    if not metadata:
        raise ValueError("目录内缺少可识别的 Skill 元数据，请提供 manifest.json、skill.json 或 SKILL.md")

    name = _clean_text(metadata.get("name")) or os.path.basename(source_dir)
    description = _clean_text(metadata.get("description") or metadata.get("summary"))
    imported_at = _now_text()
    return {
        "id": _clean_text(metadata.get("id")) or _build_skill_id(name, source_dir),
        "name": name,
        "description": description,
        "source_dir": source_dir,
        "source": metadata.get("source") if isinstance(metadata.get("source"), dict) else {},
        "enabled": True,
        "imported_at": imported_at,
        "updated_at": imported_at,
        "status": "ready",
    }
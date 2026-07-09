from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.app_paths import MEMORY_DIR as _MEMORY_DIR


SCOPES = {"user", "session", "repo"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_key(value: str | None, *, default: str = "default") -> str:
    raw = (value or "").strip() or default
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:10]
    base = os.path.basename(raw.replace("\\", "/")) or default
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-_") or default
    return f"{stem}-{digest}"


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + " ...[truncated]"


def _json_from_text(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fenced:
        raw = fenced.group(1).strip()
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


class MemoryService:
    """Markdown-backed memory service.

    Memory is separate from full chat transcripts:
    - session: one Markdown file per chat
    - repo: one Markdown file per Wwise project
    - user: one Markdown file for long-term user preferences

    A small compatibility layer exposes record-like methods so existing UI code
    can render one Markdown file as one manageable memory item.
    """

    def __init__(self, base_dir: str | os.PathLike[str] | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else Path(_MEMORY_DIR)
        self.user_dir = self.base_dir / "user"
        self.session_dir = self.base_dir / "session"
        self.repo_dir = self.base_dir / "repo"
        self.legacy_projects_dir = self.base_dir / "projects"
        self._ensure_dirs()
        self.ensure_scope("user", "default")

    def _ensure_dirs(self) -> None:
        for directory in (self.user_dir, self.session_dir, self.repo_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def normalize_key(self, scope: str, key: str | None = None) -> str:
        if scope == "user":
            return "default"
        if scope == "session":
            return (key or "default").strip() or "default"
        if scope == "repo":
            return _safe_key(key, default="default-repo")
        raise ValueError(f"Unsupported memory scope: {scope}")

    def markdown_path(self, scope: str, key: str | None = None) -> Path:
        normalized = self.normalize_key(scope, key)
        if scope == "user":
            return self.user_dir / "memories.md"
        if scope == "session":
            return self.session_dir / f"{normalized}.md"
        if scope == "repo":
            return self.repo_dir / f"{normalized}.md"
        raise ValueError(f"Unsupported memory scope: {scope}")

    def session_path(self, chat_id: str | None) -> Path:
        return self.markdown_path("session", chat_id)

    def repo_path(self, project_key: str | None) -> Path:
        return self.markdown_path("repo", project_key)

    def user_path(self) -> Path:
        return self.markdown_path("user", "default")

    def _legacy_json_path(self, scope: str, key: str | None = None) -> Path:
        normalized = self.normalize_key(scope, key)
        if scope == "user":
            return self.user_dir / "memories.json"
        directory = self.session_dir if scope == "session" else self.repo_dir
        return directory / f"{normalized}.json"

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _write_text_atomic(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text.rstrip() + "\n")
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _empty_markdown(self, scope: str, key: str | None = None) -> str:
        now = _now()
        if scope == "session":
            return (
                "# 当前对话记忆\n\n"
                f"- Chat ID: `{self.normalize_key('session', key)}`\n"
                f"- 更新时间: {now}\n\n"
                "## 当前目标\n- 暂无\n\n"
                "## 关键结论\n- 暂无\n\n"
                "## 已完成事项\n- 暂无\n\n"
                "## 待跟进事项\n- 暂无\n\n"
                "## 约束与偏好\n- 暂无\n"
            )
        if scope == "repo":
            return (
                "# 工程记忆\n\n"
                f"- 工程标识: `{key or 'default-wwise-project'}`\n"
                f"- 更新时间: {now}\n\n"
                "## 工程结构\n- 暂无\n\n"
                "## 工程内容\n- 暂无\n\n"
                "## 最佳实践\n- 暂无\n\n"
                "## 已知风险与注意事项\n- 暂无\n"
            )
        return (
            "# 长期用户记忆\n\n"
            f"- 更新时间: {now}\n\n"
            "## 个人偏好\n- 暂无\n\n"
            "## 工作习惯\n- 暂无\n\n"
            "## 输出格式偏好\n- 暂无\n\n"
            "## 工具与流程偏好\n- 暂无\n"
        )

    def _records_from_legacy_json(self, scope: str, key: str | None) -> list[dict[str, Any]]:
        paths = [self._legacy_json_path(scope, key)]
        if scope == "session" and key:
            paths.extend(sorted(self.session_dir.glob(f"{key}-*.json")))
        records: list[dict[str, Any]] = []
        seen = set()
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            data = self._read_json(path)
            raw_records = data.get("records") if isinstance(data, dict) and isinstance(data.get("records"), list) else []
            records.extend(record for record in raw_records if isinstance(record, dict))
        return records

    def _markdown_from_legacy_json(self, scope: str, key: str | None) -> str:
        records = self._records_from_legacy_json(scope, key)
        if not records:
            return ""
        now = _now()
        if scope == "session":
            bullets = [str(record.get("content") or "").strip() for record in records[-6:] if record.get("content")]
            goal_lines = "\n".join(f"- {_truncate(item, 300)}" for item in bullets) or "- 暂无"
            return (
                "# 当前对话记忆\n\n"
                f"- Chat ID: `{self.normalize_key('session', key)}`\n"
                f"- 更新时间: {now}\n\n"
                "## 当前目标\n"
                f"{goal_lines}\n\n"
                "## 关键结论\n- 从旧 JSON 记忆迁移。\n\n"
                "## 已完成事项\n- 暂无\n\n"
                "## 待跟进事项\n- 暂无\n\n"
                "## 约束与偏好\n- 暂无\n"
            )
        if scope == "repo":
            facts = []
            for record in records:
                category = str(record.get("category") or "")
                content = str(record.get("content") or "").strip()
                if content and category != "action_result":
                    facts.append(content)
            fact_lines = "\n".join(f"- {_truncate(item, 300)}" for item in facts[-12:]) or "- 暂无"
            return (
                "# 工程记忆\n\n"
                f"- 工程标识: `{key or 'default-wwise-project'}`\n"
                f"- 更新时间: {now}\n\n"
                "## 工程结构\n- 暂无\n\n"
                "## 工程内容\n"
                f"{fact_lines}\n\n"
                "## 最佳实践\n- 暂无\n\n"
                "## 已知风险与注意事项\n- 暂无\n"
            )
        prefs = [str(record.get("content") or "").strip() for record in records if record.get("content")]
        pref_lines = "\n".join(f"- {_truncate(item, 300)}" for item in prefs[-50:]) or "- 暂无"
        return (
            "# 长期用户记忆\n\n"
            f"- 更新时间: {now}\n\n"
            "## 个人偏好\n"
            f"{pref_lines}\n\n"
            "## 工作习惯\n- 暂无\n\n"
            "## 输出格式偏好\n- 暂无\n\n"
            "## 工具与流程偏好\n- 暂无\n"
        )

    def _load_or_migrate_markdown(self, scope: str, key: str | None = None) -> str:
        path = self.markdown_path(scope, key)
        text = self._read_text(path)
        if text.strip():
            return text
        migrated = self._markdown_from_legacy_json(scope, key)
        if migrated.strip():
            self._write_text_atomic(path, migrated)
            return migrated
        return ""

    def ensure_scope(self, scope: str, key: str | None = None) -> dict[str, Any]:
        if scope not in SCOPES:
            raise ValueError(f"Unsupported memory scope: {scope}")
        path = self.markdown_path(scope, key)
        if not path.exists():
            existing = self._load_or_migrate_markdown(scope, key)
            if not existing.strip():
                self._write_text_atomic(path, self._empty_markdown(scope, key))
        return self.load_scope(scope, key)

    def load_scope(self, scope: str, key: str | None = None) -> dict[str, Any]:
        if scope not in SCOPES:
            raise ValueError(f"Unsupported memory scope: {scope}")
        markdown = self._load_or_migrate_markdown(scope, key)
        records = self._records_for_markdown(scope, key, markdown)
        return {
            "schema_version": 2,
            "format": "markdown",
            "scope": scope,
            "key": self.normalize_key(scope, key),
            "path": str(self.markdown_path(scope, key)),
            "records": records,
        }

    def load_session_markdown(self, chat_id: str | None) -> str:
        return self._load_or_migrate_markdown("session", chat_id)

    def save_session_markdown(self, chat_id: str | None, markdown: str) -> None:
        self._write_text_atomic(self.session_path(chat_id), markdown or self._empty_markdown("session", chat_id))

    def load_repo_markdown(self, project_key: str | None) -> str:
        return self._load_or_migrate_markdown("repo", project_key)

    def save_repo_markdown(self, project_key: str | None, markdown: str) -> None:
        self._write_text_atomic(self.repo_path(project_key), markdown or self._empty_markdown("repo", project_key))

    def load_user_markdown(self) -> str:
        return self._load_or_migrate_markdown("user", "default")

    def save_user_markdown(self, markdown: str) -> None:
        self._write_text_atomic(self.user_path(), markdown or self._empty_markdown("user", "default"))

    def _records_for_markdown(self, scope: str, key: str | None, markdown: str) -> list[dict[str, Any]]:
        if not markdown.strip():
            return []
        path = self.markdown_path(scope, key)
        try:
            updated_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if path.exists() else ""
        except OSError:
            updated_at = ""
        category = {"session": "markdown_session", "repo": "markdown_project", "user": "markdown_user"}[scope]
        display_type = self._display_type(scope, key)
        display_content = self._display_content(scope, markdown)
        return [{
            "id": f"{scope}:markdown",
            "scope": scope,
            "category": category,
            "content": markdown,
            "display_type": display_type,
            "display_content": display_content,
            "updated_at": updated_at,
            "path": str(path),
        }]

    def _display_type(self, scope: str, key: str | None) -> str:
        if scope == "session":
            return self.normalize_key("session", key)
        if scope == "repo":
            return key or "default-wwise-project"
        return "长期用户记忆"

    def _section_text(self, markdown: str, heading: str) -> str:
        lines = markdown.splitlines()
        target = f"## {heading}"
        try:
            start = lines.index(target) + 1
        except ValueError:
            return ""
        end = len(lines)
        for index in range(start, len(lines)):
            if lines[index].startswith("## "):
                end = index
                break
        body = []
        for line in lines[start:end]:
            cleaned = line.strip()
            if not cleaned or cleaned == "- 暂无":
                continue
            body.append(cleaned[2:].strip() if cleaned.startswith("- ") else cleaned)
        return " ".join(body).strip()

    def _display_content(self, scope: str, markdown: str) -> str:
        if scope == "session":
            return self._section_text(markdown, "摘要") or self._section_text(markdown, "关键结论") or self._section_text(markdown, "当前目标") or "暂无摘要"
        if scope == "repo":
            parts = [
                self._section_text(markdown, "工程内容"),
                self._section_text(markdown, "最佳实践"),
                self._section_text(markdown, "工程结构"),
            ]
            return " ".join(part for part in parts if part).strip() or "暂无工程记忆"
        parts = [
            self._section_text(markdown, "个人偏好"),
            self._section_text(markdown, "工作习惯"),
            self._section_text(markdown, "输出格式偏好"),
            self._section_text(markdown, "工具与流程偏好"),
        ]
        return " ".join(part for part in parts if part).strip() or "暂无长期记忆"

    def list_records(self, scope: str, key: str | None = None) -> list[dict[str, Any]]:
        return list(self.load_scope(scope, key).get("records") or [])

    def append_record(
        self,
        scope: str,
        key: str | None,
        content: str,
        *,
        category: str = "fact",
        source_chat_id: str | None = None,
        source_turn_id: str | None = None,
        tags: Any = None,
        confidence: float = 1.0,
        max_records: int | None = None,
    ) -> dict[str, Any] | None:
        text = (content or "").strip()
        if not text:
            return None
        if scope == "user":
            markdown = self._append_user_memory(text)
            self.save_user_markdown(markdown)
            return self.list_records("user", "default")[0]
        if scope == "session":
            existing = self.load_session_markdown(key) or self._empty_markdown("session", key)
            markdown = self._replace_section(existing, "关键结论", [text])
            self.save_session_markdown(key, markdown)
            return self.list_records("session", key)[0]
        if scope == "repo":
            existing = self.load_repo_markdown(key) or self._empty_markdown("repo", key)
            markdown = self._replace_section(existing, "工程内容", [text])
            self.save_repo_markdown(key, markdown)
            return self.list_records("repo", key)[0]
        raise ValueError(f"Unsupported memory scope: {scope}")

    def delete_record(self, scope: str, key: str | None, record_id: str) -> bool:
        if record_id != f"{scope}:markdown":
            return False
        self.clear_scope(scope, key)
        return True

    def clear_scope(self, scope: str, key: str | None = None) -> None:
        path = self.markdown_path(scope, key)
        if path.exists():
            path.unlink()

    def delete_session_memory(self, chat_id: str | None) -> None:
        if not chat_id:
            return
        path = self.session_path(chat_id)
        if path.exists():
            path.unlink()
        json_path = self._legacy_json_path("session", chat_id)
        if json_path.exists():
            json_path.unlink()
        for legacy in self.session_dir.glob(f"{chat_id}-*.json"):
            try:
                legacy.unlink()
            except OSError:
                pass

    def search_relevant(self, scope: str, key: str | None, query: str = "", *, limit: int = 8) -> list[dict[str, Any]]:
        records = self.list_records(scope, key)
        if not query:
            return records[:limit]
        terms = [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]+", query) if len(term) > 1]
        if not terms:
            return records[:limit]
        matched = []
        for record in records:
            content = str(record.get("content") or "").lower()
            if any(term in content for term in terms):
                matched.append(record)
        return (matched or records)[:limit]

    def build_context_for_llm(
        self,
        *,
        chat_id: str | None,
        project_key: str | None,
        query: str = "",
        settings: dict[str, Any] | None = None,
    ) -> str:
        memory_settings = settings if isinstance(settings, dict) else {}
        if memory_settings.get("enabled") is False:
            return ""
        max_chars = int(memory_settings.get("max_memory_context_chars") or 12000)
        sections: list[str] = []
        specs = [
            ("User Memory", "user", "default", bool(memory_settings.get("auto_inject_user", True))),
            ("Session Memory", "session", chat_id, bool(memory_settings.get("auto_inject_session", True))),
            ("Repo Memory", "repo", project_key, bool(memory_settings.get("auto_inject_repo", True))),
        ]
        for title, scope, key, enabled in specs:
            if not enabled or (scope != "user" and not key):
                continue
            markdown = self._load_or_migrate_markdown(scope, key)
            if markdown.strip():
                sections.append(f"[{title}]\n{_truncate(markdown, 3000)}")
        if not sections:
            return ""
        return _truncate(
            "MEMORY CONTEXT\nUse these Markdown memories as helpful context. They may be stale; prefer live WAAPI data for current project state.\n\n"
            + "\n\n".join(sections),
            max_chars,
        )

    def build_memory_refresh_messages(
        self,
        *,
        chat_id: str | None,
        project_key: str | None,
        recent_messages: list[dict[str, Any]],
        action_summaries: list[str] | None = None,
    ) -> list[dict[str, str]]:
        existing_session = self.load_session_markdown(chat_id) or self._empty_markdown("session", chat_id)
        existing_repo = self.load_repo_markdown(project_key) or self._empty_markdown("repo", project_key)
        compact_messages = []
        for message in recent_messages[-10:]:
            role = str(message.get("role") or "")
            content = message.get("content")
            if isinstance(content, list):
                text = " ".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
            else:
                text = str(content or "")
            text = _truncate(text, 1600)
            if role and text:
                compact_messages.append(f"{role}: {text}")
        action_text = "\n\n".join(_truncate(item, 1600) for item in (action_summaries or []) if str(item).strip())
        prompt = (
            "你是 WwiseAgent 的记忆管理员。请在一次对话已经完成后，判断是否需要刷新当前对话记忆和工程记忆。\n"
            "只保留重要、有复用价值的信息；不要记录普通寒暄、临时措辞、无关细节或完整聊天记录。\n\n"
            "记忆规则：\n"
            "1. 当前对话记忆：类型是对话编号，内容是本对话摘要。每个对话只保留一个摘要。\n"
            "2. 工程记忆：类型是当前工程标识，内容是有关工程结构、对象、路径、WAAPI 查询发现、工程约定、最佳实践或风险的记忆。\n"
            "3. 如果没有值得保存的新信息，对应 should_update 必须为 false。\n"
            "4. 输出必须是一个 JSON 对象，不要输出 Markdown 代码块或解释。\n\n"
            "JSON 格式：\n"
            "{\n"
            "  \"session\": {\"should_update\": true, \"summary\": \"对话摘要，1-5 条要点\"},\n"
            "  \"repo\": {\"should_update\": true, \"memory\": \"工程相关记忆，1-8 条要点\"}\n"
            "}\n\n"
            f"对话编号: {self.normalize_key('session', chat_id)}\n"
            f"工程标识: {project_key or 'default-wwise-project'}\n\n"
            "现有当前对话记忆：\n"
            f"{_truncate(existing_session, 2400)}\n\n"
            "现有工程记忆：\n"
            f"{_truncate(existing_repo, 2400)}\n\n"
            "最近对话：\n"
            f"{_truncate(chr(10).join(compact_messages), 5000)}\n\n"
            "执行摘要：\n"
            f"{_truncate(action_text or '无', 3000)}"
        )
        return [
            {"role": "system", "content": "你只输出严格 JSON，用于刷新 WwiseAgent 的 Markdown 记忆文件。"},
            {"role": "user", "content": prompt},
        ]

    def apply_memory_refresh_response(
        self,
        *,
        chat_id: str | None,
        project_key: str | None,
        response_text: str,
    ) -> dict[str, bool]:
        data = _json_from_text(response_text)
        if not data:
            return {"session": False, "repo": False}
        updated = {"session": False, "repo": False}
        session = data.get("session") if isinstance(data.get("session"), dict) else {}
        if chat_id and session.get("should_update") is True:
            summary = str(session.get("summary") or "").strip()
            if summary:
                self.save_session_markdown(chat_id, self._session_markdown_from_summary(chat_id, summary))
                updated["session"] = True
        repo = data.get("repo") if isinstance(data.get("repo"), dict) else {}
        if project_key and repo.get("should_update") is True:
            memory = str(repo.get("memory") or "").strip()
            if memory:
                existing = self.load_repo_markdown(project_key) or self._empty_markdown("repo", project_key)
                markdown = self._replace_section(existing, "工程内容", self._memory_lines(memory))
                self.save_repo_markdown(project_key, markdown)
                updated["repo"] = True
        return updated

    def _memory_lines(self, text: str) -> list[str]:
        lines = []
        for line in str(text or "").splitlines():
            cleaned = line.strip().lstrip("-*• ").strip()
            if cleaned:
                lines.append(cleaned)
        return lines or [str(text or "").strip()]

    def _session_markdown_from_summary(self, chat_id: str | None, summary: str) -> str:
        return (
            "# 当前对话记忆\n\n"
            f"- Chat ID: `{self.normalize_key('session', chat_id)}`\n"
            f"- 更新时间: {_now()}\n\n"
            "## 摘要\n"
            + "\n".join(f"- {line}" for line in self._memory_lines(summary))
            + "\n"
        )

    def record_turn_summary(
        self,
        chat_id: str | None,
        user_text: str,
        assistant_text: str,
        *,
        max_records: int = 80,
    ) -> dict[str, Any] | None:
        if not chat_id:
            return None
        markdown = (
            "# 当前对话记忆\n\n"
            f"- Chat ID: `{self.normalize_key('session', chat_id)}`\n"
            f"- 更新时间: {_now()}\n\n"
            "## 当前目标\n"
            f"- {_truncate(user_text, 500) or '暂无'}\n\n"
            "## 关键结论\n"
            f"- {_truncate(assistant_text, 1000) or '暂无'}\n\n"
            "## 已完成事项\n- 最近一轮对话已完成。\n\n"
            "## 待跟进事项\n- 暂无\n\n"
            "## 约束与偏好\n- 完整聊天记录保存在 chats/*.json；此文件只保存精选对话记忆。\n"
        )
        self.save_session_markdown(chat_id, markdown)
        return self.list_records("session", chat_id)[0]

    def record_action_summary(
        self,
        project_key: str | None,
        chat_id: str | None,
        action_summary: str,
        *,
        max_records: int = 200,
    ) -> dict[str, Any] | None:
        if not project_key or not action_summary.strip():
            return None
        existing = self.load_repo_markdown(project_key) or self._empty_markdown("repo", project_key)
        markdown = self._replace_section(existing, "工程内容", [
            "最近一次成功查询/执行结果已作为工程事实候选：",
            _truncate(action_summary, 900),
        ])
        self.save_repo_markdown(project_key, markdown)
        return self.list_records("repo", project_key)[0]

    def _set_updated_at(self, markdown: str) -> str:
        lines = markdown.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("- 更新时间:"):
                lines[index] = f"- 更新时间: {_now()}"
                return "\n".join(lines)
        return markdown.rstrip() + f"\n- 更新时间: {_now()}\n"

    def _replace_section(self, markdown: str, heading: str, bullets: list[str]) -> str:
        lines = markdown.splitlines()
        target = f"## {heading}"
        try:
            start = lines.index(target)
        except ValueError:
            return self._set_updated_at(markdown.rstrip() + f"\n\n{target}\n" + "\n".join(f"- {b}" for b in bullets if b.strip()) + "\n")
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if lines[index].startswith("## "):
                end = index
                break
        replacement = [target]
        replacement.extend(f"- {bullet.strip()}" for bullet in bullets if bullet.strip())
        if len(replacement) == 1:
            replacement.append("- 暂无")
        updated = lines[:start] + replacement + [""] + lines[end:]
        return self._set_updated_at("\n".join(updated).strip())

    def _append_user_memory(self, content: str) -> str:
        existing = self.load_user_markdown() or self._empty_markdown("user", "default")
        lines = existing.splitlines()
        target = "## 个人偏好"
        try:
            start = lines.index(target)
        except ValueError:
            return self._set_updated_at(existing.rstrip() + f"\n\n{target}\n- {content}\n")
        insert_at = start + 1
        while insert_at < len(lines) and lines[insert_at].strip() in {"", "- 暂无"}:
            del lines[insert_at]
        lines.insert(insert_at, f"- {content}")
        return self._set_updated_at("\n".join(lines))

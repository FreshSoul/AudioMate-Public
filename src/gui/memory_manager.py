"""Memory settings and refresh helpers for the AudioMate main window."""

from __future__ import annotations

from src.gui.runtime_support import MemoryRefreshThread
from src.utils.app_logger import get_logger
from src.utils.storage import normalize_memory_settings, save_app_settings


logger = get_logger(__name__)


class MemoryManager:
    """Coordinate memory UI records, prompt context, and async refresh work."""

    def __init__(self, owner):
        self.owner = owner
        self._pending_action_summaries = []

    def apply_memory_settings(self, payload: dict):
        owner = self.owner
        owner.app_settings["memory"] = normalize_memory_settings(payload)
        save_app_settings(owner.app_settings)
        if hasattr(owner, "settings_page"):
            owner.settings_page.set_memory_settings(owner.app_settings)

    def memory_key_for_scope(self, scope: str):
        owner = self.owner
        if scope == "user":
            return "default"
        if scope == "session":
            return owner.current_chat_id
        if scope == "repo":
            return self.current_memory_project_key()
        return None

    def current_memory_records(self) -> dict:
        memory_service = self.get_memory_service()
        if memory_service is None:
            return {"session": [], "repo": [], "user": []}
        records = {}
        for scope in ("session", "repo", "user"):
            key = self.memory_key_for_scope(scope)
            if scope != "user" and not key:
                records[scope] = []
                continue
            try:
                records[scope] = memory_service.list_records(scope, key)
            except Exception as exc:
                logger.warning("Failed to list %s memory records: %s", scope, exc)
                records[scope] = []
        return records

    def refresh_settings_memory_page(self):
        owner = self.owner
        if not hasattr(owner, "settings_page"):
            return
        owner.settings_page.set_memory_settings(owner.app_settings)
        owner.settings_page.set_memory_records(self.current_memory_records())

    def delete_memory_record(self, scope: str, record_id: str):
        memory_service = self.get_memory_service()
        if memory_service is None:
            return
        key = self.memory_key_for_scope(scope)
        try:
            memory_service.delete_record(scope, key, record_id)
        except Exception as exc:
            logger.warning("Failed to delete %s memory record: %s", scope, exc)
        self.refresh_settings_memory_page()

    def clear_memory_scope(self, scope: str):
        memory_service = self.get_memory_service()
        if memory_service is None:
            return
        key = self.memory_key_for_scope(scope)
        try:
            memory_service.clear_scope(scope, key)
        except Exception as exc:
            logger.warning("Failed to clear %s memory scope: %s", scope, exc)
        self.refresh_settings_memory_page()

    def add_user_memory(self, content: str):
        owner = self.owner
        memory_service = self.get_memory_service()
        if memory_service is None:
            return
        text = (content or "").strip()
        if not text:
            return
        try:
            memory_service.append_record(
                "user",
                "default",
                text,
                category="preference",
                source_chat_id=owner.current_chat_id,
                tags=["manual", "user"],
                confidence=1.0,
                max_records=200,
            )
        except Exception as exc:
            logger.warning("Failed to add user memory: %s", exc)
        self.refresh_settings_memory_page()

    def memory_settings(self) -> dict:
        try:
            app_settings = self.owner.__dict__.get("app_settings", {})
        except Exception:
            app_settings = {}
        settings = app_settings.get("memory") if isinstance(app_settings, dict) else None
        return settings if isinstance(settings, dict) else {}

    def get_memory_service(self):
        try:
            return self.owner.__dict__.get("memory_service")
        except Exception:
            return None

    def current_memory_project_key(self) -> str:
        owner = self.owner
        try:
            if getattr(owner.waapi_client, "connected", False):
                project_path = owner.waapi_client.get_project_path()
                if project_path:
                    return project_path
        except Exception:
            pass
        return "default-wwise-project"

    def build_memory_context_for_llm(self) -> str:
        owner = self.owner
        memory_service = self.get_memory_service()
        if memory_service is None:
            return ""
        try:
            return memory_service.build_context_for_llm(
                chat_id=owner.current_chat_id,
                project_key=self.current_memory_project_key(),
                query=owner._latest_user_text(),
                settings=self.memory_settings(),
            )
        except Exception as exc:
            logger.warning("Failed to build memory context: %s", exc)
            return ""

    def record_turn_memory(self, assistant_text: str):
        owner = self.owner
        return self._record_turn_memory_inner(
            assistant_text,
            chat_id=owner.current_chat_id,
            history=list(owner.chat_history),
        )

    def record_turn_memory_for(self, chat_id: str, assistant_text: str, history: list):
        """Same as :meth:`record_turn_memory` but bound to a specific chat_id +
        message list — used for background-chat completion paths where the
        finished turn doesn't belong to the visible chat.
        """
        return self._record_turn_memory_inner(
            assistant_text,
            chat_id=chat_id,
            history=list(history) if history else [],
        )

    def _record_turn_memory_inner(self, assistant_text: str, *, chat_id, history):
        owner = self.owner
        memory_service = self.get_memory_service()
        if memory_service is None:
            return
        normalized_text = (assistant_text or "").strip()
        if normalized_text.startswith(("执行失败", "分步执行失败")) or "[Error]" in normalized_text:
            logger.info("Skipping memory refresh for failed/error turn")
            return
        settings = self.memory_settings()
        if settings.get("enabled") is False:
            return
        save_session = settings.get("auto_save_session") is not False
        save_repo = settings.get("auto_save_repo") is not False
        current_worker = owner.__dict__.get("memory_refresh_worker")
        if current_worker is not None and current_worker.isRunning():
            logger.info("Skipping memory refresh because a previous refresh is still running")
            return
        action_summaries = list(self._pending_action_summaries)
        self._pending_action_summaries.clear()
        if not save_session and not save_repo:
            return
        target_chat_id = chat_id if save_session else None
        project_key = self.current_memory_project_key() if save_repo else None
        try:
            recent_messages = list(history[-10:])
            if assistant_text.strip() and (not recent_messages or recent_messages[-1].get("role") != "assistant"):
                recent_messages.append({"role": "assistant", "content": assistant_text})
            messages = memory_service.build_memory_refresh_messages(
                chat_id=target_chat_id,
                project_key=project_key,
                recent_messages=recent_messages,
                action_summaries=action_summaries,
            )
            worker = MemoryRefreshThread(owner.llm_service, messages, owner)
            owner.memory_refresh_worker = worker
            worker.finished_signal.connect(
                lambda response, svc=memory_service, cid=target_chat_id, pkey=project_key, w=worker: self.handle_memory_refresh_finished(
                    response, svc, cid, pkey, w
                )
            )
            worker.start()
        except Exception as exc:
            logger.warning("Failed to record session memory: %s", exc)

    def handle_memory_refresh_finished(self, response: str, memory_service, chat_id: str | None, project_key: str | None, worker):
        owner = self.owner
        try:
            if response.strip().lower().startswith(("error:", "error calling llm", "error calling memory refresh llm")):
                logger.warning("Memory refresh LLM failed: %s", response.strip())
                return
            memory_service.apply_memory_refresh_response(
                chat_id=chat_id,
                project_key=project_key,
                response_text=response,
            )
            self.refresh_settings_memory_page()
        except Exception as exc:
            logger.warning("Failed to apply memory refresh: %s", exc)
        finally:
            if owner.__dict__.get("memory_refresh_worker") is worker:
                owner.memory_refresh_worker = None
            try:
                worker.deleteLater()
            except RuntimeError:
                pass

    def record_repo_action_memory(self, action_summary: str):
        settings = self.memory_settings()
        if settings.get("enabled") is False or settings.get("auto_save_repo") is False:
            return
        if not action_summary.strip():
            return
        self._pending_action_summaries.append(action_summary)
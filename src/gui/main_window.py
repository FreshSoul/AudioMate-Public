import sys
import os
import re
import json
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlparse, unquote
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel,
                             QScrollArea, QFrame, QListWidget, QGraphicsOpacityEffect, QGraphicsDropShadowEffect,
                             QListWidgetItem, QComboBox, QMessageBox, QStackedWidget, QSizePolicy)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QIcon, QTextCursor

from src.waapi.client import WwiseClient
from src.llm.service import LLMService
from src.llm.retrieval import WaapiDocRetriever
from src.llm.embedding_defaults import (
    DEFAULT_REMOTE_BASE_URL,
    build_remote_api_config,
    get_default_embedding_config,
)
from src.utils.execution import CodeExecutor
from src.utils.agent_tools import AgentToolbox
from src.llm.agent_resilience import AgentResilienceManager
from src.gui.notification_service import NotificationService
from src.utils.notification_settings import normalize_notification_settings
from src.services.auth_session import AuthSession
from src.services.mcp_runtime import MCPRuntimeService
from src.services.plugin_runtime import PluginRuntimeService
from src.services.scheduler import SchedulerService
from src.utils.knowledge_store import list_knowledge_bases, search_knowledge_snippets
from src.services.web_access import WebAccessService
from src.services.memory_service import MemoryService
from src.engine.response_parser import (
    extract_code_blocks as _engine_extract_code_blocks,
    strip_think_block as _engine_strip_think_block,
    redact_prompt_content as _engine_redact_prompt_content,
    sanitize_assistant_response as _engine_sanitize_assistant_response,
    is_system_generated_user_message as _engine_is_system_generated,
    truncate_tool_output as _engine_truncate_tool_output,
    summarize_tool_failure as _engine_summarize_tool_failure,
    output_has_error as _engine_output_has_error,
    extract_intent_clarify_options as _engine_extract_intent_options,
)
from src.engine.message_builder import (
    build_llm_messages as _engine_build_llm_messages,
    build_reinforcement_messages as _engine_build_reinforcement_messages,
    format_tool_output_message as _engine_format_tool_output_message,
)
from src.engine.external_agent_router import ExternalAgentRouter
from src.tools.waapi_code_tool import code_uses_waapi as _engine_code_uses_waapi
from src.state import AgentState, StateStore
from src.tools import create_default_registry
from src.engine.turn_controller import TurnController, TurnAction, TurnResult
from src.engine.roleplay import RoleplayStateController
from src.engine.prompt_assembler import PromptGuidanceAssembler
from src.utils.storage import (
    save_chat,
    load_chat,
    create_new_chat,
    delete_chat,
    load_app_settings,
    save_app_settings,
)
from src.utils.app_logger import get_logger
from src.utils.skill_store import (
    build_skill_payload,
    build_skill_prompt_guidance,
    normalize_skill_settings,
)
from src.utils.plugin_store import (
    build_plugin_payload,
)
from src.pet.store import (
    normalize_pet_settings,
)
from src.pet.service import PetService
from src.pet.window import MainPetWindow


INTERNAL_MESSAGE_PREFIX = "[INTERNAL_EXECUTION]"


def _streaming_render_controller_for(window):
    """Lazily attach a ``StreamingRenderController`` to *window*.

    Module-level (not a bound method) so it also works for the duck-typed
    fake windows tests pass to unbound ``MainWindow.<method>`` calls, and
    for instances created via ``MainWindow.__new__`` that skip ``__init__``.
    The controller is stateless, so on-demand creation is safe.
    """
    ctrl = window.__dict__.get("_streaming_render_controller")
    if ctrl is None:
        ctrl = StreamingRenderController(window)
        window.__dict__["_streaming_render_controller"] = ctrl
    return ctrl


def _code_execution_controller_for(window):
    """Lazily attach a ``CodeExecutionController`` to *window*.

    Same convention as ``_streaming_render_controller_for``: module-level so
    duck-typed fake windows and ``MainWindow.__new__`` instances work.
    """
    ctrl = window.__dict__.get("_code_execution_controller")
    if ctrl is None:
        ctrl = CodeExecutionController(window)
        window.__dict__["_code_execution_controller"] = ctrl
    return ctrl


def _turn_pipeline_controller_for(window):
    """Lazily attach a ``TurnPipelineController`` to *window*.

    Same convention as ``_streaming_render_controller_for``: module-level so
    duck-typed fake windows and ``MainWindow.__new__`` instances work.
    """
    ctrl = window.__dict__.get("_turn_pipeline_controller")
    if ctrl is None:
        ctrl = TurnPipelineController(window)
        window.__dict__["_turn_pipeline_controller"] = ctrl
    return ctrl


def _chat_history_controller_for(window):
    """Lazily attach a ``ChatHistoryController`` (same convention as above)."""
    ctrl = window.__dict__.get("_chat_history_controller")
    if ctrl is None:
        ctrl = ChatHistoryController(window)
        window.__dict__["_chat_history_controller"] = ctrl
    return ctrl


def _dialog_controller_for(window):
    """Lazily attach a ``DialogController`` (same convention as above)."""
    ctrl = window.__dict__.get("_dialog_controller")
    if ctrl is None:
        ctrl = DialogController(window)
        window.__dict__["_dialog_controller"] = ctrl
    return ctrl


def _scheduler_controller_for(window):
    """Lazily attach a ``SchedulerController`` (same convention as above)."""
    ctrl = window.__dict__.get("_scheduler_controller")
    if ctrl is None:
        ctrl = SchedulerController(window)
        window.__dict__["_scheduler_controller"] = ctrl
    return ctrl

logger = get_logger(__name__)


from src.gui.chat_runtime import ChatRuntimeManager, ChatTaskState as _ChatTaskState

# --- Extracted modules ---------------------------------------------------
from src.gui.common import (
    extract_text_from_content,
    IMAGE_FILE_EXTENSIONS,
    DEFAULT_REMOTE_MODELS,
    _is_supported_image_path,
    _split_attachment_files_for_display,
    _resolve_local_image_path,
    _extract_local_image_paths_from_text,
    _system_file_icon,
)
from src.gui.theme import STYLESHEET, _apply_context_menu_theme
from src.gui.ui.main_window_ui import MainWindowUi
from src.gui.controllers.pet_integration import PetIntegrationController
from src.gui.controllers.layout_controller import LayoutController
from src.gui.controllers.model_config import ModelConfigController
from src.gui.controllers.streaming_render import StreamingRenderController
from src.gui.controllers.code_execution import CodeExecutionController
from src.gui.controllers.turn_pipeline import TurnPipelineController
from src.gui.controllers.chat_history import ChatHistoryController
from src.gui.controllers.dialog_controller import DialogController
from src.gui.controllers.scheduler_controller import SchedulerController
from src.gui.theme_manager import ThemeManager
from src.gui.market_operations import MarketOperations
from src.gui.memory_manager import MemoryManager
from src.gui.attachment_manager import AttachmentManager
from src.gui.runtime_support import (
    WorkerThread,
    _WwiseConnector,
    build_executor_context,
)
from src.gui.widgets import (
    ThemedTextEdit,
    StackedPageAnimator,
    FileWriteConfirmWidget,
    StepProgressWidget,
    ImageInputTextEdit,
    ImageViewerDialog,
    FeedbackQRDialog,
    ClickableImageLabel,
    MessageBubble,
    HistoryItemWidget,
    MessageFileWidget,
)

class _TitleSummaryThread(QThread):
    """Background LLM call to summarize a chat into a short topic title."""

    finished_with_title = pyqtSignal(str, str)  # (chat_id, title)

    _SYSTEM_PROMPT = (
        "你是一个会话标题总结助手。请用不超过 20 个中文字符（或 30 个英文字符）"
        "为下面这段对话生成一个简短的主题标题。"
        "只输出标题本身，不要加引号、标点、前缀或解释。"
    )

    def __init__(self, llm_service, chat_id: str, user_text: str, assistant_text: str, parent=None):
        super().__init__(parent)
        self._llm_service = llm_service
        self._chat_id = chat_id
        self._user_text = (user_text or "")[:2000]
        self._assistant_text = (assistant_text or "")[:2000]

    def run(self) -> None:
        title = ""
        try:
            messages = [
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"用户：{self._user_text}\n\n"
                        f"助手：{self._assistant_text}\n\n"
                        "请输出标题："
                    ),
                },
            ]
            chunks = []
            for piece in self._llm_service.get_response(messages, stream=False, max_tokens=64):
                if isinstance(piece, str):
                    chunks.append(piece)
            raw = "".join(chunks).strip()
            if raw.lower().startswith("error"):
                raw = ""
            # Strip wrapping quotes / punctuation a model might add anyway.
            raw = raw.strip().strip("\"'“”‘’《》「」 \n\r\t")
            # Single line, capped length.
            raw = raw.splitlines()[0] if raw else ""
            title = raw[:30]
        except Exception:
            title = ""
        self.finished_with_title.emit(self._chat_id, title)


class MainWindow(QMainWindow):
    analysis_progress_signal = pyqtSignal(int, int, str)
    analysis_finished_signal = pyqtSignal()
    powershell_confirmation_requested = pyqtSignal(dict, object)
    agent_import_confirmation_requested = pyqtSignal(str, object)

    def __init__(self):
        super().__init__()
        logger.info("MainWindow initialization started")
        self.max_auto_turns = 80
        self.resilience = AgentResilienceManager()
        self.app_settings = load_app_settings()
        self.theme_mode = self.app_settings.get("theme", "light")
        if self.theme_mode not in ("light", "dark"):
            self.theme_mode = "light"
        self.theme_manager = ThemeManager(self)
        self.market_operations = MarketOperations(self)
        self.attachment_manager = AttachmentManager(self)
        self.layout_controller = LayoutController(self)
        self.model_config = ModelConfigController(self)
        self.sidebar_expanded_width = 280
        self.sidebar_collapsed = bool(self.app_settings.get("sidebar_collapsed", False))
        self.sidebar_animation = None
        self.sidebar_fade_animation = None
        self.floating_panel_fade_animation = None

        self.setWindowTitle("AudioMate")
        # 设置窗口图标（左上角 + 任务栏），兼容 PyInstaller 打包
        if getattr(sys, '_MEIPASS', None):
            icon_path = os.path.join(sys._MEIPASS, 'AudioMate.jpg')
        else:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'AudioMate.jpg')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1150, 850)
        self.setStyleSheet(STYLESHEET)
        self.notification_service = NotificationService(self, self.app_settings.get("notifications"))

        # Pet / sub-agent behaviour lives in a dedicated controller; the
        # MainWindow keeps thin delegating wrappers (see below). Must exist
        # before pet_service wiring, which routes through those wrappers.
        self.pet_integration = PetIntegrationController(self)

        # Buddy(宠物) — desktop pet service must come before any service that
        # might emit announcements through it.
        self.app_settings["pets"] = normalize_pet_settings(self.app_settings)
        self.pet_service = PetService(self)
        self.pet_service.set_state(self.app_settings["pets"])
        self.pet_service.set_persist_callback(self._persist_pet_settings)
        # Deterministic "talk to Codex / Claude Code" routing — keeps the main
        # chat from writing code itself when the user asks to delegate.
        self.external_agent_router = ExternalAgentRouter()
        self.pet_service.sub_pet_triggered.connect(self._on_sub_pet_triggered)
        self.pet_service.sub_agent_started.connect(self._on_main_sub_agent_started)
        self.pet_service.sub_agent_finished.connect(self._on_main_sub_agent_finished)
        self.pet_service.import_permission_requested.connect(self._on_sub_agent_import_request)
        self.powershell_confirmation_requested.connect(self._on_powershell_confirmation_request)
        self.agent_import_confirmation_requested.connect(self._on_agent_import_confirmation_request)
        self._parallel_agent_frame = None
        self._parallel_agent_layout = None
        self._parallel_agent_rows: dict[str, "QLabel"] = {}
        self._parallel_agent_meta: dict[str, dict] = {}
        self._parallel_agent_heartbeat = None
        self._parallel_agent_phase = 0

        # Services 保持不变
        self.waapi_client = WwiseClient()
        self.llm_service = LLMService()
        self.auth_session = AuthSession()
        self.mcp_runtime = MCPRuntimeService(self.app_settings)
        self.web_access = WebAccessService()
        self.memory_service = MemoryService()
        self.memory_manager = MemoryManager(self)
        self.agent_tools = AgentToolbox(self, self.waapi_client)
        self.agent_tools.set_analysis_progress_callbacks(
            progress_callback=self._emit_analysis_progress,
            finished_callback=self._emit_analysis_finished,
        )

        saved_api_key = (self.auth_session.get_api_key() or "").strip()
        saved_base_url = (getattr(self.auth_session, "get_base_url", lambda: "")() or "").strip()
        
        # WAAPI doc retriever (semantic search)
        self.embedding_config = get_default_embedding_config()
        self.waapi_retriever = WaapiDocRetriever(
            api_key=self.embedding_config.get("api_key"),
            base_url=self.embedding_config.get("base_url"),
            embedding_model=self.embedding_config.get("embedding_model"),
        )
        
        # --- 模型预设配置 (Model Presets) ---
        _default_api = build_remote_api_config(
            api_key=saved_api_key,
            base_url=saved_base_url or DEFAULT_REMOTE_BASE_URL,
        )
        self.model_configs = {
            model_name: dict(_default_api) for model_name in DEFAULT_REMOTE_MODELS
        }
        
        # --- Centralized State & Tool Registry (Phase 4) ---
        self.tool_registry = create_default_registry()
        self.plugin_runtime = PluginRuntimeService(self.tool_registry, self._build_plugin_base_context)
        self.app_settings["plugins"] = self.plugin_runtime.configure(self.app_settings)
        self.state_store = StateStore()

        # Add controlled execution tools.
        self.code_executor = CodeExecutor(context_globals=self._build_executor_context())
        self.turn_controller = TurnController(parent=self)
        self._current_task_context = None
        self._task_completion_notified = False
        
        self.current_chat_id = None
        self.current_chat_title = "New Chat"
        self.chat_history = []
        self.active_roleplay = None
        self.roleplay = RoleplayStateController(
            chat_history_getter=lambda: self.chat_history,
            chat_history_setter=self._replace_chat_history,
        )
        self.prompt_assembler = PromptGuidanceAssembler(self)
        self.pending_branch_bubbles = []
        self.current_streaming_bubble = None
        self.full_streaming_response = ""
        self._streaming_bubble_lost = False
        self._streaming_render_timer = QTimer(self)
        self._streaming_render_timer.setSingleShot(True)
        self._streaming_render_timer.setInterval(100)
        self._streaming_render_timer.timeout.connect(self._flush_streaming_render)
        self._thinking_widget = None
        self.step_progress_widget = None
        self._thinking_phase = False
        self._think_lines_parsed = 0
        self._pending_initial_thinking_text = ""
        self._pending_internal_messages = []
        self.recursion_depth = 0
        self.worker = None
        self.memory_refresh_worker = None
        self.execution_thread = None
        self.chat_runtime = ChatRuntimeManager(current_chat_id_getter=lambda: self.current_chat_id)
        self._chat_task_states = self.chat_runtime.states
        self.scheduler_service = SchedulerService(self)
        self.scheduler_service.task_due.connect(self._on_scheduled_task_due)
        self.scheduler_service.tasks_changed.connect(self._on_scheduled_tasks_changed)
        self._scheduled_task_queue = []
        self._scheduled_task_ids_in_queue = set()
        self._scheduled_queue_timer = QTimer(self)
        self._scheduled_queue_timer.setInterval(1000)
        self._scheduled_queue_timer.timeout.connect(self._try_start_next_scheduled_task)
        self._model_fetcher = None  # 后台模型列表获取线程
        self._retriever_thread = None
        self._retriever_init_signature = None
        self._retriever_init_status = ""
        self._last_model_signature = None
        self._active_intent_clarify_widget = None
        self.analysis_progress_signal.connect(self._on_analysis_progress)
        self.analysis_finished_signal.connect(self._on_analysis_finished)

        # 主界面布局 —— 静态控件树的构建已抽到 MainWindowUi.build()。
        # 该构建器把所有控件按原属性名挂回 self，并连接到本窗口的槽，
        # 因此后续所有 self.<widget> 引用与信号连接均保持不变。
        MainWindowUi(self).build()

        # 初始化业务
        # 不自动连接 Wwise，等待用户手动点击 Connect 按钮
        self.status_label.setText("○ Wwise Disconnected")
        self.refresh_history_list()
        self.start_new_chat()
        self.apply_theme(self.theme_mode)
        self.set_sidebar_collapsed(self.sidebar_collapsed, animated=False)
        
        # 强制应用默认模型的配置 
        default_model = DEFAULT_REMOTE_MODELS[0]
        if self.model_selector.findText(default_model) != -1:
             self.model_selector.setCurrentText(default_model)
             # 手动触发一次配置更新，确保 Keys 被注入到 Service
             self.change_model(default_model)

        # 启动时获取可用模型列表
        self._trigger_model_refresh()
        # 启动时加载已有知识库到选择器
        self._refresh_kb_selector()
        self._refresh_skill_selector()
        self.scheduler_service.start()

        # Buddy(宠物) — instantiate the floating window and wire its signals.
        self.main_pet_window = MainPetWindow(self.pet_service, parent=None)
        self.main_pet_window.user_message_submitted.connect(self._on_pet_user_message)
        self.main_pet_window.open_training_room_requested.connect(self.open_pet_training_room)
        self.main_pet_window.intent_mirrored.connect(self._on_pet_intent_mirrored)
        self.main_pet_window.confirm_mirrored.connect(self._on_pet_confirm_mirrored)
        self.main_pet_window.file_write_mirrored.connect(self._on_pet_file_write_mirrored)
        self.main_pet_window.open_settings_requested.connect(self._open_buddy_settings)
        if bool(self.app_settings.get("pets", {}).get("floating_enabled")):
            self.main_pet_window.show()
        self._sync_sub_pet_schedules()
        logger.info(
            "MainWindow initialization completed: theme=%s sidebar_collapsed=%s model=%s",
            self.theme_mode,
            self.sidebar_collapsed,
            self.model_selector.currentText() if hasattr(self, "model_selector") else "",
        )
        

    def _theme_styles(self):
        return self.theme_manager.theme_styles()

    def apply_theme(self, theme_mode):
        return self.theme_manager.apply_theme(theme_mode)

    def _history_list_style(self):
        return self.theme_manager.history_list_style()

    def _sidebar_nav_button_style(self, active=False, centered=False):
        return self.theme_manager.sidebar_nav_button_style(active=active, centered=centered)

    def _floating_button_style(self, active=False, accent=False):
        return self.theme_manager.floating_button_style(active=active, accent=accent)

    def _sync_navigation_styles(self):
        return self.theme_manager.sync_navigation_styles()

    def _show_chat_page(self, direction="right"):
        try:
            page_stack = self.__dict__.get("page_stack")
            chat_page = self.__dict__.get("chat_page")
            page_animator = self.__dict__.get("page_animator")
        except Exception:
            return
        if page_stack is None or chat_page is None:
            return
        if page_stack.currentWidget() == chat_page:
            return
        if page_animator is not None:
            page_animator.animate_to(chat_page, direction=direction)
        else:
            page_stack.setCurrentWidget(chat_page)
        self._sync_floating_panel_visibility(animated=True)
        self._sync_navigation_styles()

    def _asset_path(self, filename):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", filename)

    def _refresh_feedback_icon(self):
        return self.theme_manager.refresh_feedback_icon()

    def _refresh_donate_icon(self):
        return self.theme_manager.refresh_donate_icon()

    def save_theme_preference(self):
        return self.theme_manager.save_theme_preference()

    def apply_mcp_settings(self, payload: dict):
        if not isinstance(payload, dict):
            return

        configs = payload.get("configs") if isinstance(payload.get("configs"), dict) else {}
        raw_order = payload.get("order") if isinstance(payload.get("order"), list) else []
        order = []
        seen = set()
        for item in raw_order:
            name = str(item or "").strip()
            if name in configs and name not in seen:
                order.append(name)
                seen.add(name)
        for name in configs:
            if name not in seen:
                order.append(name)
                seen.add(name)
        selected = next((name for name in order if bool(configs.get(name, {}).get("enabled"))), "")

        self.app_settings["mcp_configs"] = configs
        self.app_settings["mcp_config_order"] = order
        self.app_settings["mcp_selected_config"] = selected
        save_app_settings(self.app_settings)
        self.mcp_runtime.configure(self.app_settings)
        self._sync_executor_context()

    # ------------------------------------------------------------------
    # Buddy (pets) integration — implemented in PetIntegrationController.
    # These thin wrappers preserve the existing method names so all signal
    # connections and external callers (e.g. powershell_tool reaching
    # request_powershell_confirmation via getattr) keep working unchanged.
    # ------------------------------------------------------------------

    def apply_pet_settings(self, payload: dict):
        return self.pet_integration.apply_pet_settings(payload)

    def _persist_pet_settings(self, state: dict):
        return self.pet_integration._persist_pet_settings(state)

    def _pet_office_chats_provider(self) -> list:
        return self.pet_integration._pet_office_chats_provider()

    def _pet_office_capabilities_provider(self) -> dict:
        return self.pet_integration._pet_office_capabilities_provider()

    def _on_office_chat_clicked(self, chat_id: str) -> None:
        return self.pet_integration._on_office_chat_clicked(chat_id)

    def _on_skill_map_requested(self) -> None:
        return self.pet_integration._on_skill_map_requested()

    def _ensure_parallel_agent_panel(self) -> None:
        return self.pet_integration._ensure_parallel_agent_panel()

    def _on_main_sub_agent_started(self, run_id: str, pet_id: str, pet_name: str) -> None:
        return self.pet_integration._on_main_sub_agent_started(run_id, pet_id, pet_name)

    def _on_main_sub_agent_finished(self, run_id: str, success: bool, snippet: str) -> None:
        return self.pet_integration._on_main_sub_agent_finished(run_id, success, snippet)

    def _dismiss_parallel_agent_row(self, run_id: str) -> None:
        return self.pet_integration._dismiss_parallel_agent_row(run_id)

    def _tick_parallel_agent_heartbeat(self) -> None:
        return self.pet_integration._tick_parallel_agent_heartbeat()

    def _on_sub_agent_import_request(self, pet_name: str, module_name: str, future) -> None:
        return self.pet_integration._on_sub_agent_import_request(pet_name, module_name, future)

    def request_powershell_confirmation(self, payload: dict, timeout: float = 120.0) -> bool:
        return self.pet_integration.request_powershell_confirmation(payload, timeout=timeout)

    def _on_powershell_confirmation_request(self, payload: dict, future) -> None:
        return self.pet_integration._on_powershell_confirmation_request(payload, future)

    def request_agent_import_confirmation(self, module_name: str, timeout: float = 120.0) -> bool:
        return self.pet_integration.request_agent_import_confirmation(module_name, timeout=timeout)

    def _on_agent_import_confirmation_request(self, module_name: str, future) -> None:
        return self.pet_integration._on_agent_import_confirmation_request(module_name, future)

    def _on_dispatch_sub_pet(self, pet_id: str) -> None:
        return self.pet_integration._on_dispatch_sub_pet(pet_id)

    def open_pet_training_room(self, pet_id: str):
        return self.pet_integration.open_pet_training_room(pet_id)

    def _save_image_model(self, model: str) -> None:
        return self.pet_integration._save_image_model(model)

    def _mirror_to_pet(self, kind: str, main_widget, *, options=None, file_paths=None) -> str:
        return self.pet_integration._mirror_to_pet(
            kind, main_widget, options=options, file_paths=file_paths
        )

    def _dismiss_pet_mirror(self, widget_id: str) -> None:
        return self.pet_integration._dismiss_pet_mirror(widget_id)

    def _on_pet_intent_mirrored(self, widget_id: str, intent: str, note: str) -> None:
        return self.pet_integration._on_pet_intent_mirrored(widget_id, intent, note)

    def _on_pet_confirm_mirrored(self, widget_id: str, accepted: bool) -> None:
        return self.pet_integration._on_pet_confirm_mirrored(widget_id, accepted)

    def _on_pet_file_write_mirrored(self, widget_id: str, accepted: bool) -> None:
        return self.pet_integration._on_pet_file_write_mirrored(widget_id, accepted)

    def _on_pet_training_room_saved(self, pet_item: dict):
        return self.pet_integration._on_pet_training_room_saved(pet_item)

    def _on_sub_pet_triggered(self, pet_id: str, prompt: str, title: str):
        return self.pet_integration._on_sub_pet_triggered(pet_id, prompt, title)

    def _pet_scheduler_task_ids(self, pet_settings) -> set[str]:
        return self.pet_integration._pet_scheduler_task_ids(pet_settings)

    def _is_pet_scheduler_task(self, task: dict) -> bool:
        return self.pet_integration._is_pet_scheduler_task(task)

    def _persist_synced_pet_state(self, state: dict) -> None:
        return self.pet_integration._persist_synced_pet_state(state)

    def _sync_sub_pet_schedules(self, previous_pet_task_ids: set[str] | None = None):
        return self.pet_integration._sync_sub_pet_schedules(
            previous_pet_task_ids=previous_pet_task_ids
        )

    def apply_skill_settings(self, payload: dict):
        if not isinstance(payload, dict):
            return

        self.app_settings["skills"] = build_skill_payload(payload)
        save_app_settings(self.app_settings)
        if hasattr(self, "settings_page"):
            self.settings_page.set_skill_settings(self.app_settings)
        if hasattr(self, "skill_selector"):
            self._refresh_skill_selector()

    def apply_plugin_settings(self, payload: dict):
        if not isinstance(payload, dict):
            return
        self.app_settings["plugins"] = build_plugin_payload(payload)
        if hasattr(self, "plugin_runtime"):
            self.app_settings["plugins"] = self.plugin_runtime.configure(self.app_settings)
        save_app_settings(self.app_settings)
        if hasattr(self, "settings_page"):
            self.settings_page.set_plugin_settings(self.app_settings)
        if hasattr(self, "code_executor"):
            self._sync_executor_context()

    def import_plugin_from_dialog(self):
        return self.market_operations.import_plugin_from_dialog()

    def import_plugin_from_path(self, directory: str):
        return self.market_operations.import_plugin_from_path(directory)

    def import_bundled_plugin(self, relative_path: str):
        return self.market_operations.import_bundled_plugin(relative_path)

    def open_reaper_setup(self):
        return self.market_operations.open_reaper_setup()

    def import_skill_from_dialog(self):
        return self.market_operations.import_skill_from_dialog()

    def refresh_market_catalog(self):
        return self.market_operations.refresh_market_catalog()

    def apply_notification_settings(self, payload: dict):
        self.app_settings["notifications"] = normalize_notification_settings(payload)
        save_app_settings(self.app_settings)
        if hasattr(self, "notification_service"):
            self.notification_service.update_settings(self.app_settings.get("notifications"))
        if hasattr(self, "settings_page"):
            self.settings_page.set_notification_settings(self.app_settings)

    def apply_memory_settings(self, payload: dict):
        return self.memory_manager.apply_memory_settings(payload)

    def _memory_key_for_scope(self, scope: str):
        return self.memory_manager.memory_key_for_scope(scope)

    def _current_memory_records(self) -> dict:
        return self.memory_manager.current_memory_records()

    def _refresh_settings_memory_page(self):
        return self.memory_manager.refresh_settings_memory_page()

    def delete_memory_record(self, scope: str, record_id: str):
        return self.memory_manager.delete_memory_record(scope, record_id)

    def clear_memory_scope(self, scope: str):
        return self.memory_manager.clear_memory_scope(scope)

    def add_user_memory(self, content: str):
        return self.memory_manager.add_user_memory(content)

    def _begin_task_notification_context(self, source: str, title: str, prompt: str, pet_id: str = ""):
        source = source if source in {"manual", "scheduled", "pet"} else "manual"
        title = (title or "").strip()
        prompt_preview = self._first_line(prompt or "")[:80]
        if not title:
            title = "定时任务" if source == "scheduled" else (prompt_preview or "当前任务")
        self._current_task_context = {
            "source": source,
            "title": title[:80],
            "prompt_preview": prompt_preview,
            "pet_id": (pet_id or "").strip(),
        }
        self._task_completion_notified = False

    def _notify_current_task_finished(self, *, success: bool = True, detail: str = "", cancelled: bool = False):
        self._set_pet_state("idle")
        if self._task_completion_notified:
            return
        settings = normalize_notification_settings(self.app_settings.get("notifications"))
        if not settings.get("enabled", True):
            return

        context = self._current_task_context or {}
        source = context.get("source", "manual")

        task_title = str(context.get("title") or "当前任务").strip() or "当前任务"
        prompt_preview = str(context.get("prompt_preview") or "").strip()
        if cancelled:
            title = "AudioMate 任务已撤销"
            message = f"{task_title} 已撤销。"
        elif success:
            title = "AudioMate 定时任务完成" if source == "scheduled" else "AudioMate 任务完成"
            message = f"{task_title} 已完成。"
        else:
            title = "AudioMate 任务未完成"
            message = f"{task_title} 执行失败或中断。"

        if detail:
            first_detail = self._first_line(detail)
            if first_detail:
                message = f"{message}\n{first_detail[:120]}"
        elif prompt_preview and prompt_preview != task_title:
            message = f"{message}\n{prompt_preview}"

        if hasattr(self, "notification_service"):
            self.notification_service.update_settings(settings)
            if cancelled:
                self.notification_service.notify_task_cancelled(title, message)
            elif success:
                self.notification_service.notify_task_completed(title, message)
            else:
                self.notification_service.notify_task_failed(title, message)
        self._task_completion_notified = True

        # Mirror to the pet service so Buddy can update stats & announce.
        if hasattr(self, "pet_service"):
            try:
                self.pet_service.record_task_completion(
                    source=source,
                    title=task_title,
                    success=success and not cancelled,
                    cancelled=cancelled,
                    detail=detail,
                    pet_id=str(context.get("pet_id") or ""),
                )
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("PetService.record_task_completion failed: %s", exc)

    def get_active_mcp_config(self):
        return self.mcp_runtime.describe_active_config()

    def list_mcp_tools(self, force_refresh: bool = False):
        return self.mcp_runtime.list_tools(force_refresh=force_refresh)

    def call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict | None = None,
        timeout_seconds: int = 60,
        config_name: str | None = None,
    ):
        return self.mcp_runtime.call_tool(
            tool_name,
            arguments=arguments,
            timeout_seconds=timeout_seconds,
            config_name=config_name,
        )

    def fetch_webpage(self, url: str, max_chars: int = 12000, timeout: int = 15):
        return self.web_access.fetch_webpage(url, max_chars=max_chars, timeout=timeout)

    def _extract_feishu_document_id(self, url_or_id: str) -> str:
        candidate = str(url_or_id or "").strip()
        if not candidate:
            return ""
        if "://" not in candidate:
            return candidate

        parsed = urlparse(candidate)
        path = unquote(parsed.path or "")
        segments = [segment for segment in path.split("/") if segment]
        for marker in ("wiki", "docx", "docs", "sheet", "base"):
            if marker in segments:
                marker_index = segments.index(marker)
                if marker_index + 1 < len(segments):
                    return segments[marker_index + 1]
        for segment in reversed(segments):
            if re.fullmatch(r"[A-Za-z0-9]{10,}", segment):
                return segment
        return candidate

    def read_feishu_doc(self, url_or_id: str, timeout_seconds: int = 60):
        document_id = self._extract_feishu_document_id(url_or_id)
        if not document_id:
            raise ValueError("A Feishu document URL or document_id is required")

        result = dict(self.call_mcp_tool("get_doc_content", {"document_id": document_id}, timeout_seconds=timeout_seconds))
        result["document_id"] = document_id
        text = result.get("text")
        if isinstance(text, str) and text.strip().startswith("{"):
            try:
                payload = json.loads(text)
            except Exception:
                return result
            result["payload"] = payload
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, str) and data.strip():
                result["text"] = data.strip()
        return result

    def on_theme_selector_changed(self, theme_text):
        selected = "dark" if theme_text == "Dark" else "light"
        self.apply_theme(selected)
        self.save_theme_preference()

    # ------------------------------------------------------------------
    # Sidebar / floating-panel layout — implemented in LayoutController.
    # Thin delegating wrappers preserve the existing method names so all
    # signal connections and call sites keep working unchanged.
    # ------------------------------------------------------------------

    def toggle_sidebar(self):
        return self.layout_controller.toggle_sidebar()

    def set_sidebar_collapsed(self, collapsed, animated=True):
        return self.layout_controller.set_sidebar_collapsed(collapsed, animated=animated)

    def _sync_floating_panel_visibility(self, animated=False):
        return self.layout_controller._sync_floating_panel_visibility(animated=animated)

    def _apply_sidebar_width(self, value):
        return self.layout_controller._apply_sidebar_width(value)

    def update_floating_panel_position(self):
        return self.layout_controller.update_floating_panel_position()

    def update_top_bar_margins(self):
        return self.layout_controller.update_top_bar_margins()

    def update_input_wrapper_margins(self):
        return self.layout_controller.update_input_wrapper_margins()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_controller.on_resize(event)

    # --- 逻辑功能区 ---

    def _on_mode_changed(self, new_mode):
        """Handle mode switch: reset UI state to prevent freeze."""
        # Mode changes apply to the next turn. Existing background turns keep
        # their captured mode so switching UI mode does not cancel other chats.
        self._update_current_chat_controls()
        self.recursion_depth = 0
        self.resilience.reset()
        self._sync_executor_context()
        logger.info("Mode switched: %s", new_mode)

    def _task_state_for(self, chat_id: str | None = None, *, create: bool = True) -> _ChatTaskState | None:
        runtime = self.__dict__.get("chat_runtime")
        if runtime is not None:
            return runtime.task_state_for(chat_id, create=create)
        # Fallback: tests use ``MainWindow.__new__`` and inject a raw
        # ``_chat_task_states`` dict without constructing ``ChatRuntimeManager``.
        resolved = chat_id or self.__dict__.get("current_chat_id")
        if not resolved:
            return None
        states = self.__dict__.get("_chat_task_states") or {}
        state = states.get(resolved)
        if state is None and create:
            state = _ChatTaskState(chat_id=resolved)
            states[resolved] = state
            self.__dict__["_chat_task_states"] = states
        return state

    def _current_task_state(self) -> _ChatTaskState | None:
        runtime = self.__dict__.get("chat_runtime")
        if runtime is not None:
            return runtime.current_task_state()
        return self._task_state_for(self.__dict__.get("current_chat_id"), create=True)

    def _is_chat_visible(self, chat_id: str | None) -> bool:
        runtime = self.__dict__.get("chat_runtime")
        if runtime is not None:
            return runtime.is_chat_visible(chat_id)
        return bool(chat_id and chat_id == self.__dict__.get("current_chat_id"))

    def _sync_visible_runtime_to_state(self):
        state = self._current_task_state()
        if state is None:
            return
        state.full_streaming_response = self.full_streaming_response
        state.thinking_phase = self._thinking_phase
        state.think_lines_parsed = self._think_lines_parsed
        state.current_streaming_bubble = self.current_streaming_bubble
        state.thinking_widget = self._thinking_widget
        state.streaming_bubble_lost = self._streaming_bubble_lost

    def _activate_runtime_state(self, chat_id: str | None):
        state = self._task_state_for(chat_id, create=True)
        if state is None:
            self.worker = None
            self.full_streaming_response = ""
            self.current_streaming_bubble = None
            self._streaming_bubble_lost = False
            self._thinking_phase = False
            self._think_lines_parsed = 0
            return
        self.worker = state.worker
        self.code_executor = state.code_executor
        self.full_streaming_response = state.full_streaming_response
        self.current_streaming_bubble = state.current_streaming_bubble
        self._streaming_bubble_lost = state.streaming_bubble_lost
        self._thinking_phase = state.thinking_phase
        self._think_lines_parsed = state.think_lines_parsed
        self._thinking_widget = state.thinking_widget

    def _detach_visible_runtime_widgets(self):
        state = self._current_task_state()
        if state is None:
            return
        state.full_streaming_response = self.full_streaming_response
        state.thinking_phase = self._thinking_phase
        state.think_lines_parsed = self._think_lines_parsed
        state.streaming_bubble_lost = self._streaming_bubble_lost
        # Widgets belong to the currently rebuilt layout; do not keep stale Qt
        # object references after the chat layout is cleared.
        state.current_streaming_bubble = None
        state.thinking_widget = None
        state.pending_file_write_widget = None
        self.current_streaming_bubble = None
        self._thinking_widget = None

    def _chat_has_running_task(self, chat_id: str | None = None) -> bool:
        runtime = self.__dict__.get("chat_runtime")
        if runtime is None:
            return False
        return runtime.chat_has_running_task(chat_id)

    def _stop_task_for_chat(self, chat_id: str | None, *, wait_ms: int = 0):
        runtime = self.__dict__.get("chat_runtime")
        if runtime is None:
            return
        state = runtime.stop_task_for_chat(chat_id, wait_ms=wait_ms)
        if state is None:
            return
        if chat_id == self.__dict__.get("current_chat_id"):
            self.worker = state.worker
            self._reset_streaming_state()
            self._update_current_chat_controls()

    def _stop_all_tasks(self):
        for chat_id in list(self._chat_task_states.keys()):
            self._stop_task_for_chat(chat_id, wait_ms=500)
        if self.memory_refresh_worker:
            self.memory_refresh_worker.stop()

    def _update_current_chat_controls(self):
        state = self._current_task_state()
        if state is not None and state.pending_file_write_context:
            self.send_btn.setDisabled(True)
            self.input_field.setDisabled(True)
            self.send_btn.setText("✈")
            return
        running = self._chat_has_running_task(self.current_chat_id)
        self.send_btn.setDisabled(False)
        self.input_field.setDisabled(False)
        self.send_btn.setText("■" if running else "✈")

    def _restore_runtime_visuals_for_current_chat(self):
        state = self._current_task_state()
        if state is None:
            self._update_current_chat_controls()
            return
        self._activate_runtime_state(state.chat_id)
        if state.running and state.worker is not None:
            text = state.status_detail or "后台任务运行中"
            self._thinking_widget = None
            widget = self._ensure_thinking_widget(text, task_context=self._current_thinking_task_context())
            state.thinking_widget = widget
            self._thinking_widget = widget
            if state.full_streaming_response and not state.current_streaming_bubble:
                self.current_streaming_bubble = self.add_message("assistant", "")
                state.current_streaming_bubble = self.current_streaming_bubble
            self.scroll_to_bottom()
        elif state.pending_finished:
            self._thinking_widget = None
            widget = self._ensure_thinking_widget("整理后台结果", task_context=self._current_thinking_task_context())
            state.thinking_widget = widget
            self._thinking_widget = widget
        if state.pending_file_write_context and state.code_executor.pending_file_writes:
            response_text, output, mode, undo_started = state.pending_file_write_context
            file_paths = [w.path for w in state.code_executor.pending_file_writes]
            fw_widget = FileWriteConfirmWidget(file_paths, theme_mode=self.theme_mode)
            fw_widget.confirmed.connect(lambda rt=response_text, out=output, md=mode, us=undo_started: self._handle_file_write_confirmed(rt, out, md, us))
            fw_widget.revoked.connect(lambda rt=response_text, out=output, md=mode, us=undo_started: self._handle_file_write_revoked(rt, out, md, us))
            state.pending_file_write_widget = fw_widget
            self.chat_layout.addWidget(fw_widget)
            self.scroll_to_bottom()
            self._mirror_to_pet("file_write", fw_widget, file_paths=list(file_paths))
            self.send_btn.setDisabled(True)
            self.input_field.setDisabled(True)
        self._update_current_chat_controls()

    # ------------------------------------------------------------------
    # Model / API configuration — implemented in ModelConfigController.
    # Thin delegating wrappers preserve the existing method names so all
    # signal connections and call sites keep working unchanged.
    # ------------------------------------------------------------------

    def change_model(self, model_name):
        return self.model_config.change_model(model_name)

    def _init_retriever_async(self):
        return self.model_config._init_retriever_async()

    def _on_retriever_init_finished(self, status: str):
        return self.model_config._on_retriever_init_finished(status)

    def _get_remote_runtime_config(self):
        return self.model_config._get_remote_runtime_config()

    def _sync_remote_provider_config(self, api_key: str, base_url: str = ""):
        return self.model_config._sync_remote_provider_config(api_key, base_url=base_url)

    def _apply_remote_models(self, models: list):
        return self.model_config._apply_remote_models(models)

    def apply_user_api_key(self, api_key: str, base_url: str = ""):
        return self.model_config.apply_user_api_key(api_key, base_url=base_url)

    def _trigger_model_refresh(self):
        return self.model_config._trigger_model_refresh()

    def _on_models_fetched(self, models: list):
        return self.model_config._on_models_fetched(models)

    def adjust_input_height(self):
        doc_height = self.input_field.document().size().height()
        # 调整自适应高度的下限和上限，配合更矮的输入框
        new_height = min(max(40, int(doc_height + 2)), 78)
        self.input_field.setFixedHeight(new_height)

    def _start_voice_input(self):
        """Start Windows native voice typing and let it insert text into the chat input."""
        if not sys.platform.startswith("win"):
            QMessageBox.information(self, "语音输入", "当前语音输入使用 Windows 系统语音输入，仅支持 Windows。")
            return
        if not self.input_field.isEnabled():
            QMessageBox.information(self, "语音输入", "当前正在处理任务，暂时不能语音输入。")
            return

        self.activateWindow()
        self.raise_()
        self.input_field.setFocus(Qt.FocusReason.MouseFocusReason)
        self.input_field.moveCursor(QTextCursor.MoveOperation.End)
        QApplication.processEvents()
        QTimer.singleShot(80, self._trigger_windows_voice_typing)

    def _trigger_windows_voice_typing(self):
        """Trigger the Windows Voice Typing panel using the Win+H shortcut."""
        try:
            import ctypes

            user32 = ctypes.windll.user32
            vk_lwin = 0x5B
            vk_h = 0x48
            keyeventf_keyup = 0x0002

            user32.keybd_event(vk_lwin, 0, 0, 0)
            user32.keybd_event(vk_h, 0, 0, 0)
            user32.keybd_event(vk_h, 0, keyeventf_keyup, 0)
            user32.keybd_event(vk_lwin, 0, keyeventf_keyup, 0)
        except Exception as exc:
            QMessageBox.warning(self, "语音输入", f"无法启动 Windows 语音输入：{exc}")

    def add_pending_image(self, image):
        return self.attachment_manager.add_pending_image(image)

    def add_pending_paths(self, paths):
        return self.attachment_manager.add_pending_paths(paths)
    
    def remove_pending_image(self, index):
        return self.attachment_manager.remove_pending_image(index)

    def remove_pending_file(self, index):
        return self.attachment_manager.remove_pending_file(index)
    
    def update_image_preview(self):
        return self.attachment_manager.update_image_preview()
    
    def clear_pending_images(self):
        return self.attachment_manager.clear_pending_images()

    def _format_pending_files_text(self, items):
        return self.attachment_manager.format_pending_files_text(items)

    def _build_user_display_text(self, user_text, images=None, files=None):
        return self.attachment_manager.build_user_display_text(user_text, images=images, files=files)
    
    def images_to_base64(self, images):
        return self.attachment_manager.images_to_base64(images)
    
    def base64_to_images(self, content_list):
        return self.attachment_manager.base64_to_images(content_list)

    def _extract_executable_code_blocks(self, response_text):
        return _engine_extract_code_blocks(response_text)

    def _strip_executable_code_blocks(self, response_text, blocks):
        clean_text = response_text or ""
        for block in blocks or []:
            clean_text = clean_text.replace(block.get("fence", ""), "")
        return clean_text.strip()

    def toggle_wwise_connection(self):
        if not self.waapi_client.connected:
            logger.info("Wwise connection requested")
            # 在后台线程中连接，防止阻塞 UI
            self.connect_btn.setDisabled(True)
            self.status_label.setText("⏳ 正在连接 Wwise...")
            self._wwise_connector = _WwiseConnector(self.waapi_client, parent=self)
            self._wwise_connector.result.connect(self._on_wwise_connect_result)
            self._wwise_connector.start()
        else:
            logger.info("Wwise disconnection requested")
            self.waapi_client.disconnect()
            self.status_label.setText("○ Wwise Disconnected")
            self.connect_btn.setText("Connect")
            self._update_connection_status_style()

    def _on_wwise_connect_result(self, success):
        logger.info("Wwise connection result received: success=%s", success)
        self.connect_btn.setDisabled(False)
        if success:
            self.status_label.setText("● Wwise Connected")
            self.connect_btn.setText("Disconnect")
        else:
            self.status_label.setText("○ 请打开Wwise或开启WAAPI")
        self._update_connection_status_style()

    def _emit_analysis_progress(self, current: int, total: int, label: str = ""):
        self.analysis_progress_signal.emit(int(current), int(total), (label or "").strip())

    def _emit_analysis_finished(self):
        self.analysis_finished_signal.emit()

    def _restore_status_label(self):
        if self.waapi_client.connected:
            self.status_label.setText("● Wwise Connected")
        else:
            self.status_label.setText("○ Wwise Disconnected")
        self._update_connection_status_style()

    def _on_analysis_progress(self, current: int, total: int, label: str):
        total = max(int(total or 0), 0)
        current = max(int(current or 0), 0)
        suffix = f": {label}" if label else ""
        if total > 0:
            self.status_label.setText(f"⏳ 分析中 {current}/{total}{suffix}")
        else:
            self.status_label.setText(f"⏳ 分析中{suffix}")
        self.status_label.setStyleSheet("color: #1A73E8; font-weight: bold;")

    def _on_analysis_finished(self):
        self._restore_status_label()

    # ------------------------------------------------------------------
    # Streaming / chat rendering — implemented in StreamingRenderController.
    # Thin delegating wrappers preserve the existing method names so all
    # signal connections, tests and call sites keep working unchanged.
    # (_set_chat_scrollbar_transient_hidden stays below: a regression test
    # invokes it unbound with a duck-typed window.)
    # ------------------------------------------------------------------

    @property
    def streaming_render(self):
        return _streaming_render_controller_for(self)

    def scroll_to_bottom(self):
        return _streaming_render_controller_for(self).scroll_to_bottom()

    def _set_chat_scrollbar_transient_hidden(self, hidden: bool):
        # User requested: keep the chat scrollbar in its normal as-needed mode
        # during thinking/execution. The previous implementation toggled the
        # scrollbar policy AND called hide()/show() on the QScrollBar widgets,
        # which on Windows produced a tall light-grey native scrollbar artifact
        # on the right while the panel re-laid-out. We now keep the scrollbar
        # consistently in AsNeeded mode and simply ensure it stays enabled.
        if self.scroll_area.verticalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAsNeeded:
            self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        bar = self.scroll_area.verticalScrollBar()
        if bar is not None and not bar.isEnabled():
            bar.setEnabled(True)

    def _update_visible_bubbles(self, resync_content: bool = False):
        return _streaming_render_controller_for(self)._update_visible_bubbles(resync_content=resync_content)

    def add_message(self, role, text, images=None, files=None):
        return _streaming_render_controller_for(self).add_message(role, text, images=images, files=files)

    def _add_pending_branch_bubble(self):
        return _streaming_render_controller_for(self)._add_pending_branch_bubble()

    def _current_thinking_task_context(self) -> str:
        return _streaming_render_controller_for(self)._current_thinking_task_context()

    def _ensure_thinking_widget(self, text: str = "正在分析请求", task_context: str = ""):
        return _streaming_render_controller_for(self)._ensure_thinking_widget(text, task_context=task_context)

    def _remove_active_thinking_widget(self):
        return _streaming_render_controller_for(self)._remove_active_thinking_widget()

    def _compact_activity_label(self, raw_text: str, fallback: str) -> str:
        return _streaming_render_controller_for(self)._compact_activity_label(raw_text, fallback)

    def _clear_pending_branch_bubbles(self):
        return _streaming_render_controller_for(self)._clear_pending_branch_bubbles()

    def _show_assistant_message(self, text: str):
        return _streaming_render_controller_for(self)._show_assistant_message(text)

    def handle_token(self, token):
        return _streaming_render_controller_for(self).handle_token(token)

    def _handle_token_for_chat(self, chat_id: str, turn_id: str, worker, token: str):
        return _streaming_render_controller_for(self)._handle_token_for_chat(chat_id, turn_id, worker, token)

    def _handle_finished_for_chat(self, chat_id: str, turn_id: str, worker):
        return _streaming_render_controller_for(self)._handle_finished_for_chat(chat_id, turn_id, worker)

    def _finalize_background_text_turn(self, chat_id: str, state: _ChatTaskState) -> bool:
        return _streaming_render_controller_for(self)._finalize_background_text_turn(chat_id, state)

    def _derive_title_from_messages(self, messages: list[dict]) -> str:
        return _streaming_render_controller_for(self)._derive_title_from_messages(messages)

    def _dispatch_pending_finished_for_current_chat(self):
        return _streaming_render_controller_for(self)._dispatch_pending_finished_for_current_chat()

    def _dispatch_pending_execution_for_current_chat(self):
        return _streaming_render_controller_for(self)._dispatch_pending_execution_for_current_chat()

    def _parse_think_tokens(self):
        return _streaming_render_controller_for(self)._parse_think_tokens()

    def _visible_agent_activity(self, raw_text: str) -> str:
        return _streaming_render_controller_for(self)._visible_agent_activity(raw_text)

    def _hide_streaming_reasoning_bubble(self):
        return _streaming_render_controller_for(self)._hide_streaming_reasoning_bubble()

    @staticmethod
    def _strip_think_block(text: str) -> str:
        """Remove <think>...</think> block from response text."""
        return _engine_strip_think_block(text)

    @staticmethod
    def _redact_prompt_content(text: str) -> str:
        return _engine_redact_prompt_content(_engine_strip_think_block(text))

    @staticmethod
    def _sanitize_assistant_response(text: str) -> str:
        return _engine_sanitize_assistant_response(text)

    @staticmethod
    def _strip_code_blocks(text: str) -> str:
        if not text:
            return ""
        return re.sub(r"```(?:python_waapi|python|py)?\s*\n.*?```", "", text, flags=re.DOTALL | re.IGNORECASE)

    def _queue_internal_message(self, role: str, content: str):
        text = (content or "").strip()
        if not text:
            return
        self._pending_internal_messages.append({
            "role": role,
            "content": f"{INTERNAL_MESSAGE_PREFIX}\n{text}",
        })

    def _queue_internal_tool_output(self, output: str, mode: str, action_summary: str = "", summary_only: bool = False):
        safe_output = self._prepare_tool_output_for_history(output)
        message = f"Output:\n{safe_output}"
        if action_summary:
            message += f"\n\n[Action Log]\n{action_summary}"
        if mode == "Agent Mode":
            message += "\n\n[System] All steps completed. Summarize the results in Chinese."
        self._queue_internal_message("user", message)

        original_goal = ""
        for msg in reversed(self.chat_history):
            if msg.get("role") != "user":
                continue
            text = extract_text_from_content(msg.get("content", ""), default="")
            if not self._is_system_generated_user_message(text):
                original_goal = text[:200]
                break
        goal_hint = f' The user\'s original request was: "{original_goal}"' if original_goal else ""
        post_exec_content = (
            "POST-EXECUTION INSTRUCTION: The code has been executed and the output is shown above."
            " You MUST now analyze and summarize the output for the user in the context of their original request."
            " Do NOT generate more code unless the output clearly indicates an error that needs fixing."
            " Do NOT repeat system rules or describe your capabilities."
            " Respond naturally in the user\'s language, directly addressing their question."
            f"{goal_hint}"
        )
        if summary_only:
            self._confirmation_summary_only = True
            post_exec_content += " Do NOT write or execute any new code in this confirmation summary turn."
        if mode == "Agent Mode":
            post_exec_content += (
                "\n\nAGENT MODE POST-EXECUTION (MANDATORY):"
                " You MUST explicitly describe every operation you performed and its result."
            )
        self._queue_internal_message("user", post_exec_content)

    def _consume_pending_internal_messages(self) -> list[dict]:
        messages = list(self._pending_internal_messages)
        self._pending_internal_messages.clear()
        return messages

    def _flush_streaming_render(self):
        return _streaming_render_controller_for(self)._flush_streaming_render()

    def _stop_active_worker(self):
        self._stop_task_for_chat(self.current_chat_id, wait_ms=1500)
        if self.memory_refresh_worker and self.memory_refresh_worker.isRunning():
            self.memory_refresh_worker.stop()

    def _reset_streaming_state(self):
        return _streaming_render_controller_for(self)._reset_streaming_state()

    # ------------------------------------------------------------------
    # Code-execution orchestration — implemented in CodeExecutionController
    # (attached lazily like the streaming controller so unbound test calls
    # on duck-typed windows keep working). Thin delegating wrappers
    # preserve the existing method names for all signals and call sites.
    # ------------------------------------------------------------------

    @property
    def code_execution(self):
        return _code_execution_controller_for(self)

    def _start_code_execution_thread(self, code: str, mode: str, callback):
        return _code_execution_controller_for(self)._start_code_execution_thread(code, mode, callback)

    def _handle_single_code_execution_finished(self, response_text, output, mode, undo_started):
        return _code_execution_controller_for(self)._handle_single_code_execution_finished(
            response_text, output, mode, undo_started
        )

    def _handle_file_write_confirmed(self, response_text, output, mode, undo_started):
        return _code_execution_controller_for(self)._handle_file_write_confirmed(
            response_text, output, mode, undo_started
        )

    def _handle_file_write_revoked(self, response_text, output, mode, undo_started):
        return _code_execution_controller_for(self)._handle_file_write_revoked(
            response_text, output, mode, undo_started
        )

    def _finish_single_code_execution(self, response_text, output, mode, undo_started, has_error):
        return _code_execution_controller_for(self)._finish_single_code_execution(
            response_text, output, mode, undo_started, has_error
        )

    def _handle_step_code_execution_finished(self, step_num: int, output: str):
        return _code_execution_controller_for(self)._handle_step_code_execution_finished(step_num, output)

    def _step_file_write_confirmed(self, step_num, output):
        return _code_execution_controller_for(self)._step_file_write_confirmed(step_num, output)

    def _step_file_write_revoked(self, step_num, output):
        return _code_execution_controller_for(self)._step_file_write_revoked(step_num, output)

    def _finish_step_code_execution(self, step_num: int, output: str):
        return _code_execution_controller_for(self)._finish_step_code_execution(step_num, output)

    def _first_line(self, text: str) -> str:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        return lines[0] if lines else ""

    def _derive_chat_title_from_history(self) -> str:
        for msg in self.chat_history:
            if msg.get("role") != "user":
                continue

            display_text = self._first_line(msg.get("display_text", ""))
            if display_text:
                return display_text[:50]

            first_line = self._first_line(extract_text_from_content(msg.get("content", ""), default=""))
            if first_line:
                return first_line[:50]

            files = ((msg.get("attachments") or {}).get("files") or [])
            if files:
                return (files[0].get("name") or "附件")[:50]

        return "New Chat"

    def _set_pet_state(self, state: str) -> None:
        try:
            if getattr(self, "main_pet_window", None) is not None:
                self.main_pet_window.set_pet_state(state)
        except Exception:
            pass

    def _maybe_summarize_title(self) -> None:
        """Trigger background LLM title summarization after the first assistant reply."""
        chat_id = self.current_chat_id
        if not chat_id:
            return
        self._maybe_summarize_title_for(chat_id, self.chat_history)

    def _maybe_summarize_title_for(self, chat_id: str, messages: list) -> None:
        """Same as :meth:`_maybe_summarize_title` but for an arbitrary chat —
        used by background-chat finalization where the finished chat is not
        the one currently visible.
        """
        if not chat_id:
            return
        if not getattr(self, "_title_threads", None):
            self._title_threads = {}
        if chat_id in self._title_threads:
            return
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        if len(assistant_msgs) != 1:
            return
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if not user_msgs:
            return
        user_text = extract_text_from_content(user_msgs[0].get("content", ""), default="").strip()
        if not user_text:
            user_text = (user_msgs[0].get("display_text") or "").strip()
        assistant_text = extract_text_from_content(assistant_msgs[0].get("content", ""), default="").strip()
        if not user_text and not assistant_text:
            return

        thread = _TitleSummaryThread(self.llm_service, chat_id, user_text, assistant_text, self)
        thread.finished_with_title.connect(self._on_title_summary_ready)
        thread.finished.connect(lambda c=chat_id: self._title_threads.pop(c, None))
        self._title_threads[chat_id] = thread
        thread.start()

    def _on_title_summary_ready(self, chat_id: str, title: str) -> None:
        title = (title or "").strip()
        if not title:
            return
        try:
            from src.utils.storage import load_chat
            data = load_chat(chat_id) or {}
            messages = data.get("messages") or (
                self.chat_history if chat_id == self.current_chat_id else []
            )
            if not messages:
                return
            save_chat(chat_id, title, messages)
        except Exception as exc:
            logger.debug("Title save failed for chat %s: %s", chat_id, exc)
            return
        if chat_id == self.current_chat_id:
            self.current_chat_title = title
        try:
            self.refresh_history_list()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Turn pipeline (send → submit → process_turn) — TurnPipelineController
    # (attached lazily like the other controllers so tests that monkeypatch
    # window.process_turn on duck-typed windows keep working). Thin
    # delegating wrappers preserve the existing method names.
    # ------------------------------------------------------------------

    @property
    def turn_pipeline(self):
        return _turn_pipeline_controller_for(self)

    def send_message(self):
        return _turn_pipeline_controller_for(self).send_message()

    def _submit_user_prompt(
        self,
        user_text: str,
        images=None,
        files=None,
        display_prefix: str = "",
        task_source: str = "manual",
        task_title: str = "",
        pet_id: str = "",
    ):
        return _turn_pipeline_controller_for(self)._submit_user_prompt(
            user_text,
            images=images,
            files=files,
            display_prefix=display_prefix,
            task_source=task_source,
            task_title=task_title,
            pet_id=pet_id,
        )

    def _maybe_delegate_to_external_agent(self, user_text: str) -> bool:
        return _turn_pipeline_controller_for(self)._maybe_delegate_to_external_agent(user_text)

    def _build_external_agent_prompt(self, user_text: str, max_turns: int = 8, max_chars: int = 1500) -> str:
        return _turn_pipeline_controller_for(self)._build_external_agent_prompt(
            user_text, max_turns=max_turns, max_chars=max_chars
        )

    def _on_intent_clarified(self, chosen_intent: str, note_text: str, widget):
        return _turn_pipeline_controller_for(self)._on_intent_clarified(chosen_intent, note_text, widget)

    def process_turn(self):
        return _turn_pipeline_controller_for(self).process_turn()

    def _latest_user_text(self):
        for msg in reversed(self.chat_history):
            if msg.get("role") == "user":
                return extract_text_from_content(msg.get("content", ""), default="")
        return ""

    def _latest_user_message(self, include_system_generated: bool = False):
        for msg in reversed(self.chat_history):
            if msg.get("role") != "user":
                continue
            text = extract_text_from_content(msg.get("content", ""), default="")
            if not include_system_generated and self._is_system_generated_user_message(text):
                continue
            return msg
        return None

    def _build_executor_context(self):
        return build_executor_context(self)

    def _build_plugin_base_context(self):
        return {
            "app_settings": self.app_settings,
            "waapi_client": self.waapi_client,
            "agent_tools": self.agent_tools,
            "parent_widget": self,
        }

    def _sync_executor_context(self):
        state = self._current_task_state()
        if state is not None:
            self.code_executor = state.code_executor
        self.code_executor.update_context(self._build_executor_context())

    def _normalize_analysis_scopes(self, scopes) -> list[str]:
        valid_scopes = ["local_audio", "project", "project_source_audio"]
        normalized = []
        if isinstance(scopes, str):
            candidate = scopes.strip()
            if candidate in valid_scopes:
                normalized.append(candidate)
        elif isinstance(scopes, (list, tuple, set)):
            for item in scopes:
                if not isinstance(item, str):
                    continue
                candidate = item.strip()
                if candidate in valid_scopes and candidate not in normalized:
                    normalized.append(candidate)
        return normalized

    def _message_analysis_scopes(self, message) -> list[str]:
        if not isinstance(message, dict):
            return []
        scopes = self._normalize_analysis_scopes(message.get("analysis_scopes"))
        if scopes:
            return scopes
        return self._normalize_analysis_scopes(message.get("analysis_scope"))

    def _analysis_scope_label(self, scope: str) -> str:
        labels = {
            "local_audio": "本地音频文件",
            "project": "Wwise 工程",
            "project_source_audio": "所选对象源文件",
        }
        return labels.get((scope or "").strip(), (scope or "").strip())

    def _build_effective_user_query(self, user_message) -> str:
        if not isinstance(user_message, dict):
            return ""

        base_text = extract_text_from_content(user_message.get("content", ""), default="")
        scope_note = (user_message.get("analysis_scope_note") or "").strip()
        if scope_note:
            return f"{base_text}\n{scope_note}".strip()
        return (base_text or "").strip()

    def _replace_chat_history(self, new_history: list) -> None:
        """Helper used by collaborators to swap the live chat_history list."""
        self.chat_history = list(new_history)

    def _build_roleplay_meta_message(self, roleplay_state: dict) -> dict:
        return self.roleplay.build_meta_message(roleplay_state)

    def _parse_roleplay_meta_message(self, message) -> dict | None:
        return self.roleplay.parse_meta_message(message)

    def _sync_roleplay_meta_message(self):
        self.roleplay.sync_meta_message()

    def _restore_roleplay_state_from_history(self):
        self.roleplay.restore_from_history()
        self.active_roleplay = self.roleplay.active_roleplay

    def _extract_roleplay_state_from_response(self, text: str) -> tuple[dict | None, str]:
        return self.roleplay.extract_from_response(text)

    def _apply_roleplay_state_update(self, state: dict | None):
        self.roleplay.apply_update(state)
        self.active_roleplay = self.roleplay.active_roleplay

    def _build_roleplay_prompt_guidance(self) -> str:
        return self.roleplay.build_prompt_guidance()

    def _content_with_analysis_context(self, message):
        if not isinstance(message, dict):
            return ""

        scopes = self._message_analysis_scopes(message)
        scope_note = (message.get("analysis_scope_note") or "").strip()
        content = message.get("content", "")
        local_context = self._recent_local_attachment_context(message)
        if not scopes and not scope_note and not local_context:
            return content

        context_lines = []
        if scopes:
            context_lines.append(f"[分析范围: {'、'.join(self._analysis_scope_label(scope) for scope in scopes)}]")
        if scope_note:
            context_lines.append(f"[补充说明: {scope_note}]")
        if local_context:
            context_lines.extend(local_context)
        context_text = "\n".join(context_lines)

        if isinstance(content, list):
            new_content = []
            injected = False
            for part in content:
                if isinstance(part, dict):
                    part_copy = dict(part)
                    if part_copy.get("type") == "text" and not injected:
                        original_text = (part_copy.get("text") or "").strip()
                        part_copy["text"] = f"{original_text}\n\n{context_text}" if original_text else context_text
                        injected = True
                    new_content.append(part_copy)
                else:
                    new_content.append(part)
            if not injected:
                new_content.append({"type": "text", "text": context_text})
            return new_content

        original_text = extract_text_from_content(content, default="")
        return f"{original_text}\n\n{context_text}".strip() if original_text else context_text

    def _recent_local_attachment_context(self, message, max_items: int = 5):
        if not isinstance(message, dict):
            return []
        current_files = ((message.get("attachments") or {}).get("files") or [])
        if current_files:
            return []

        recent = []
        for msg in reversed(self.chat_history):
            if msg is message:
                continue
            if msg.get("role") != "user":
                continue
            files = ((msg.get("attachments") or {}).get("files") or [])
            for item in files:
                path = (item.get("path") or "").strip() if isinstance(item, dict) else ""
                if not path:
                    continue
                normalized = os.path.abspath(path)
                if any(existing.get("path") == normalized for existing in recent):
                    continue
                recent.append({
                    "path": normalized,
                    "name": item.get("name") or os.path.basename(normalized) or normalized,
                    "is_dir": bool(item.get("is_dir")),
                    "exists": os.path.exists(normalized),
                })
                if len(recent) >= max_items:
                    break
            if recent:
                break
        if not recent:
            return []

        lines = ["[最近本地路径上下文: 当前消息未重新附加文件；如用户说“这些/他们/上面文件”，优先沿用以下最近附件。]"]
        for item in recent:
            kind = "文件夹" if item.get("is_dir") else "文件"
            status = "存在" if item.get("exists") else "不存在或不可访问"
            lines.append(f"- {kind}: {item['path']} ({status})")
        return lines

    def _replace_message_text_content(self, content, new_text: str):
        if isinstance(content, list):
            updated_content = []
            text_replaced = False
            for part in content:
                if isinstance(part, dict):
                    part_copy = dict(part)
                    if part_copy.get("type") == "text" and not text_replaced:
                        part_copy["text"] = new_text
                        text_replaced = True
                    updated_content.append(part_copy)
                else:
                    updated_content.append(part)
            if not text_replaced:
                updated_content.append({"type": "text", "text": new_text})
            return updated_content
        return new_text

    def _build_llm_messages(self, system_prompt: str):
        filtered_history = [msg for msg in self.chat_history if not self._parse_roleplay_meta_message(msg)]
        memory_context = self._build_memory_context_for_llm()
        return _engine_build_llm_messages(
            system_prompt,
            filtered_history,
            memory_context=memory_context,
            history_compressor=self.resilience.summarize_history,
            content_enricher=self._content_with_analysis_context,
        )

    def _memory_settings(self) -> dict:
        return self.memory_manager.memory_settings()

    def _get_memory_service(self):
        return self.memory_manager.get_memory_service()

    def _current_memory_project_key(self) -> str:
        return self.memory_manager.current_memory_project_key()

    def _build_memory_context_for_llm(self) -> str:
        return self.memory_manager.build_memory_context_for_llm()

    def _record_turn_memory(self, assistant_text: str):
        return self.memory_manager.record_turn_memory(assistant_text)

    def _handle_memory_refresh_finished(self, response: str, memory_service, chat_id: str | None, project_key: str | None, worker):
        return self.memory_manager.handle_memory_refresh_finished(response, memory_service, chat_id, project_key, worker)

    def _record_repo_action_memory(self, action_summary: str):
        return self.memory_manager.record_repo_action_memory(action_summary)

    def _current_pet_capability_ids(self) -> tuple[set, set]:
        """Return (allowed_skill_ids, allowed_plugin_ids) for the active task pet.

        Falls back to the active main pet when no task pet is set.  Orphan
        capabilities (bound to no pet) implicitly belong to the active main.
        Returns (None, None) — meaning "no filter, expose everything" — when
        no sub-pet has *actually* claimed any skill/plugin. This prevents
        the partition logic from silently hiding tools from the main agent
        in the common case where the user has no per-pet bindings at all.
        """
        try:
            from src.pet.store import resolve_pet_capabilities, bound_capability_owners
        except Exception:
            return None, None
        pet_id = ""
        if self._current_task_context:
            pet_id = (self._current_task_context.get("pet_id") or "").strip()
        active = self.pet_service.active_main() if hasattr(self, "pet_service") else None
        active_id = (active or {}).get("id", "")
        if not pet_id:
            pet_id = active_id
        if not pet_id:
            return None, None

        # If the current run is the active main AND no other pet has claimed
        # anything, skip filtering entirely — everything is implicitly the
        # main's by default.
        pets_state = self.app_settings.get("pets") or {}
        owners = bound_capability_owners(pets_state)
        others_claim_skill = any(
            (info or {}).get("pet_id") and info["pet_id"] != active_id
            for info in (owners.get("skills") or {}).values()
        )
        others_claim_plugin = any(
            (info or {}).get("pet_id") and info["pet_id"] != active_id
            for info in (owners.get("plugins") or {}).values()
        )
        if pet_id == active_id and not others_claim_skill and not others_claim_plugin:
            return None, None

        skills_all = (self.app_settings.get("skills") or {}).get("items", [])
        plugins_all = (self.app_settings.get("plugins") or {}).get("items", [])
        resolved = resolve_pet_capabilities(
            pets_state,
            pet_id,
            skills_all,
            plugins_all,
        )
        return set(resolved.get("skill_ids") or []), set(resolved.get("plugin_ids") or [])

    def _build_skill_prompt_guidance(self, user_query: str) -> str:
        return self.prompt_assembler.build_skill_guidance(user_query)

    def _build_plugin_prompt_guidance(self) -> str:
        return self.prompt_assembler.build_plugin_guidance()

    def _build_sub_agent_roster_guidance(self) -> str:
        return self.prompt_assembler.build_sub_agent_roster_guidance()

    def _build_user_knowledge_guidance(self, user_query: str) -> str:
        return self.prompt_assembler.build_user_knowledge_guidance(user_query)

    def _is_system_generated_user_message(self, text: str) -> bool:
        return _engine_is_system_generated(text)

    def _summarize_tool_failure(self, output: str, max_chars: int = 1200) -> str:
        return _engine_summarize_tool_failure(output, max_chars=max_chars)

    def _prepare_tool_output_for_history(self, output: str, max_chars: int = 800000, max_lines: int = 80000) -> str:
        """Trim oversized tool output before appending it to chat history."""
        return _engine_truncate_tool_output(output, max_chars=max_chars, max_lines=max_lines)

    def _summarize_step_output_for_board(self, output: str) -> str:
        text = (output or "").strip()
        if not text:
            return "已执行"

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        skipped_prefixes = (
            "Traceback",
            "Output:",
            "[System]",
            "[Validation]",
            "File ",
            "Error executing code",
        )
        for line in lines:
            if line.startswith("===") and line.endswith("==="):
                continue
            if line.startswith(skipped_prefixes):
                continue
            if line.startswith("# "):
                continue
            normalized = re.sub(r"\s+", " ", line)
            if len(normalized) > 72:
                normalized = f"{normalized[:72].rstrip()}..."
            return normalized
        return "已执行"

    def _build_execution_timeline_snapshot(self):
        if self.step_progress_widget is None:
            return None
        snapshot = self.step_progress_widget.snapshot()
        snapshot["kind"] = "step_timeline"
        return snapshot

    def _bind_execution_timeline_widget(self, widget, snapshot_ref=None):
        if widget is None:
            return
        widget._history_snapshot_ref = snapshot_ref
        if getattr(widget, "_collapse_persist_connected", False):
            return
        widget.collapse_changed.connect(lambda _collapsed, current=widget: self._persist_execution_timeline_widget(current))
        widget._collapse_persist_connected = True

    def _persist_execution_timeline_widget(self, widget):
        snapshot_ref = getattr(widget, "_history_snapshot_ref", None)
        if not isinstance(snapshot_ref, dict):
            return
        snapshot_ref.clear()
        snapshot_ref.update(widget.snapshot())
        if self.current_chat_id:
            save_chat(self.current_chat_id, self.current_chat_title, self.chat_history)

    def _append_execution_timeline_history(self):
        snapshot = self._build_execution_timeline_snapshot()
        if not snapshot:
            return
        self.chat_history.append({
            "role": "timeline",
            "kind": "step_timeline",
            "timeline": snapshot,
        })
        self._bind_execution_timeline_widget(self.step_progress_widget, snapshot)

    def _parse_legacy_timeline_from_message(self, message):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return None
        text = str(message.get("content") or "")
        matches = list(re.finditer(r"\[步骤\s*(\d+)\s*输出\]\n", text))
        if not matches:
            return None

        steps = []
        total = len(matches)
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < total else len(text)
            chunk = text[start:end].strip()
            detail = self._summarize_step_output_for_board(chunk)
            header_match = re.search(r"===\s*(.*?)\s*文档\s*===", chunk)
            if header_match:
                description = f"查询 {header_match.group(1).strip()}"
            else:
                description = f"执行步骤 {index + 1}"
            steps.append({
                "description": description,
                "state": "done" if index < total - 1 else ("failed" if "分步执行失败" in text else "done"),
                "detail": detail,
                "detail_visible": True,
            })

        status = "执行历史"
        if "分步执行失败" in text:
            status = f"执行中断 · 停在 {total}/{total}"
        elif steps:
            status = f"执行完成 · 共 {len(steps)} 项"

        return {
            "kind": "step_timeline",
            "title": "执行流程",
            "status": status,
            "steps": steps,
        }

    def _add_timeline_widget_from_snapshot(self, snapshot):
        if not snapshot:
            return None
        widget = StepProgressWidget(0, [], theme_mode=self.theme_mode)
        widget.apply_snapshot(snapshot)
        self._bind_execution_timeline_widget(widget, snapshot)
        self.chat_layout.addWidget(widget)
        return widget

    def _is_step_progress_widget_usable(self) -> bool:
        widget = self.step_progress_widget
        if widget is None:
            return False
        try:
            _ = widget.title_label.text()
            _ = widget.meta_label.text()
            return True
        except RuntimeError:
            self.step_progress_widget = None
            return False

    def _detect_analysis_scope(self, user_message) -> list[str]:
        return self.prompt_assembler.detect_analysis_scope(user_message)


    def _is_sensitive_meta_request(self, user_query: str) -> bool:
        return self.prompt_assembler.is_sensitive_meta_request(user_query)

    def _classify_request_intent(self, user_query: str, scope_override=None) -> str:
        return self.prompt_assembler.classify_request_intent(user_query, scope_override=scope_override)


    # ------------------------------------------------------------------
    # Turn-result dispatch & multi-step flow — CodeExecutionController.
    # _code_uses_waapi stays as a thin engine delegation below.
    # ------------------------------------------------------------------

    def _code_requires_waapi_connection(self, code: str) -> bool:
        return _code_execution_controller_for(self)._code_requires_waapi_connection(code)

    def _code_uses_waapi(self, code: str) -> bool:
        return _engine_code_uses_waapi(code)

    def _ensure_waapi_execution_ready(self, response_text: str, code_blocks: list[str]) -> bool:
        return _code_execution_controller_for(self)._ensure_waapi_execution_ready(response_text, code_blocks)

    def _coerce_confirmation_summary_result(self, turn_result: TurnResult) -> TurnResult:
        return _code_execution_controller_for(self)._coerce_confirmation_summary_result(turn_result)

    def handle_finished(self):
        return _code_execution_controller_for(self).handle_finished()

    def _extract_step_descriptions(self, response_text):
        return _code_execution_controller_for(self)._extract_step_descriptions(response_text)

    def _code_block_text(self, code_block) -> str:
        return CodeExecutionController._code_block_text(code_block)

    def _describe_code_step(self, code, index: int) -> str:
        return _code_execution_controller_for(self)._describe_code_step(code, index)

    def start_step_execution(self, response_text, code_blocks):
        return _code_execution_controller_for(self).start_step_execution(response_text, code_blocks)

    def execute_next_step(self):
        return _code_execution_controller_for(self).execute_next_step()

    def finish_step_execution(self, interrupted_by_error=False):
        return _code_execution_controller_for(self).finish_step_execution(
            interrupted_by_error=interrupted_by_error
        )

    def handle_agent_confirmation(self, confirmed, widget):
        return _code_execution_controller_for(self).handle_agent_confirmation(confirmed, widget)

    # ------------------------------------------------------------------
    # Chat history / session lifecycle — ChatHistoryController
    # (lazy attach; tests call delete_chat_history / load_selected_chat
    # unbound on MainWindow.__new__ instances).
    # ------------------------------------------------------------------

    @property
    def chat_history_controller(self):
        return _chat_history_controller_for(self)

    def start_new_chat(self):
        return _chat_history_controller_for(self).start_new_chat()

    def refresh_history_list(self):
        return _chat_history_controller_for(self).refresh_history_list()

    def _history_status_text(self, chat_id: str) -> str:
        return _chat_history_controller_for(self)._history_status_text(chat_id)

    def delete_chat_history(self, chat_id):
        return _chat_history_controller_for(self).delete_chat_history(chat_id)

    def load_selected_chat(self, item):
        return _chat_history_controller_for(self).load_selected_chat(item)

    def handle_edit_confirmed(self, new_text):
        return _chat_history_controller_for(self).handle_edit_confirmed(new_text)

    def _apply_theme_to_dynamic_widgets(self):
        return self.theme_manager.apply_theme_to_dynamic_widgets()

    def _update_connection_status_style(self):
        return self.theme_manager.update_connection_status_style()

    # ------------------------------------------------------------------
    # Sub-page navigation & QR dialogs — DialogController.
    # ------------------------------------------------------------------

    @property
    def dialog_controller(self):
        return _dialog_controller_for(self)

    def open_settings(self):
        return _dialog_controller_for(self).open_settings()

    def _open_buddy_settings(self):
        return _dialog_controller_for(self)._open_buddy_settings()

    def open_market(self):
        return _dialog_controller_for(self).open_market()

    def close_market(self):
        return _dialog_controller_for(self).close_market()

    def close_settings(self):
        return _dialog_controller_for(self).close_settings()

    def open_feedback(self):
        return _dialog_controller_for(self).open_feedback()

    def open_donate(self):
        return _dialog_controller_for(self).open_donate()

    def open_knowledge(self):
        return _dialog_controller_for(self).open_knowledge()

    def close_knowledge(self):
        return _dialog_controller_for(self).close_knowledge()

    def open_schedule(self):
        return _dialog_controller_for(self).open_schedule()

    def close_schedule(self):
        return _dialog_controller_for(self).close_schedule()

    # ------------------------------------------------------------------
    # Scheduled-task queue — SchedulerController.
    # ------------------------------------------------------------------

    @property
    def scheduler_controller(self):
        return _scheduler_controller_for(self)

    def _on_scheduled_tasks_changed(self, tasks):
        return _scheduler_controller_for(self)._on_scheduled_tasks_changed(tasks)

    def _add_scheduled_task(self, payload):
        return _scheduler_controller_for(self)._add_scheduled_task(payload)

    def _update_scheduled_task(self, task_id, payload):
        return _scheduler_controller_for(self)._update_scheduled_task(task_id, payload)

    def _delete_scheduled_task(self, task_id):
        return _scheduler_controller_for(self)._delete_scheduled_task(task_id)

    def _set_scheduled_task_enabled(self, task_id, enabled):
        return _scheduler_controller_for(self)._set_scheduled_task_enabled(task_id, enabled)

    def _run_scheduled_task_now(self, task):
        return _scheduler_controller_for(self)._run_scheduled_task_now(task)

    def _on_scheduled_task_due(self, task):
        return _scheduler_controller_for(self)._on_scheduled_task_due(task)

    def _is_agent_busy(self):
        return _scheduler_controller_for(self)._is_agent_busy()

    def _try_start_next_scheduled_task(self):
        return _scheduler_controller_for(self)._try_start_next_scheduled_task()

    def _on_pet_user_message(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        if hasattr(self, "page_animator") and hasattr(self, "chat_page"):
            self.page_animator.animate_to(self.chat_page, direction="right")
            self._sync_floating_panel_visibility(animated=True)
            self._sync_navigation_styles()
        self._submit_user_prompt(
            text,
            display_prefix="💬 来自 Buddy",
            task_source="pet",
            task_title="主宠对话",
        )

    def _refresh_kb_selector(self):
        """刷新输入框中的知识库下拉列表"""
        current = self.kb_selector.currentText()
        self.kb_selector.blockSignals(True)
        self.kb_selector.clear()
        self.kb_selector.addItem("📚 知识库")
        for kb in list_knowledge_bases():
            self.kb_selector.addItem(kb["name"], kb["id"])
        # 尝试恢复之前的选择
        idx = self.kb_selector.findText(current)
        if idx >= 0:
            self.kb_selector.setCurrentIndex(idx)
        self.kb_selector.blockSignals(False)

    def _refresh_skill_selector(self):
        """刷新输入框中的 Skill 下拉列表。"""
        if not hasattr(self, "skill_selector"):
            return
        current_id = self.skill_selector.currentData() if self.skill_selector.currentIndex() > 0 else None
        self.skill_selector.blockSignals(True)
        self.skill_selector.clear()
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons", "skill_selector_icon.svg")
        icon = QIcon(icon_path)
        self.skill_selector.addItem(icon, "Auto Skill ", None)

        for skill in normalize_skill_settings(self.app_settings).get("items", []):
            if not skill.get("enabled"):
                continue
            if skill.get("status") not in {"ready", "loaded", "active", ""}:
                continue
            self.skill_selector.addItem(icon, skill.get("name") or "Skill", skill.get("id"))

        if current_id:
            idx = self.skill_selector.findData(current_id)
            if idx >= 0:
                self.skill_selector.setCurrentIndex(idx)
        self.skill_selector.blockSignals(False)

    def closeEvent(self, event):
        # ---- Stop all timers BEFORE tearing widgets down so deferred
        # timeouts don't fire against deleted layouts. ----
        for timer_attr in (
            "_scheduled_queue_timer",
            "_streaming_render_timer",
            "_visibility_timer",
        ):
            t = getattr(self, timer_attr, None)
            if t is not None:
                try:
                    t.stop()
                except RuntimeError:
                    pass

        # ---- Ask all worker threads to interrupt, then wait for them.
        # Calling wait() with a bounded timeout prevents the app from
        # hanging if a thread is wedged in blocking IO. ----
        threads_to_join: list = []

        def _collect(obj):
            if obj is None:
                return
            try:
                if hasattr(obj, "stop"):
                    obj.stop()
            except Exception:
                pass
            try:
                if hasattr(obj, "requestInterruption"):
                    obj.requestInterruption()
            except Exception:
                pass
            try:
                if hasattr(obj, "quit"):
                    obj.quit()
            except Exception:
                pass
            threads_to_join.append(obj)

        # Per-chat task workers (covers WorkerThread + CodeExecutionThread)
        try:
            self._stop_all_tasks()
        except Exception:
            pass

        _collect(getattr(self, "memory_refresh_worker", None))
        _collect(getattr(self, "_retriever_thread", None))
        _collect(getattr(self, "_model_fetcher", None))
        _collect(getattr(self, "_wwise_connector", None))

        for t in list((getattr(self, "_title_threads", None) or {}).values()):
            _collect(t)
        for t in list(getattr(self, "_market_catalog_threads", None) or []):
            _collect(t)

        # Bounded wait — total ceiling ~1.5s so close stays responsive.
        for t in threads_to_join:
            try:
                if hasattr(t, "isRunning") and t.isRunning() and hasattr(t, "wait"):
                    t.wait(300)
            except RuntimeError:
                pass

        if hasattr(self, "scheduler_service"):
            try:
                self.scheduler_service.stop()
            except Exception:
                pass
        if hasattr(self, "plugin_runtime"):
            try:
                self.plugin_runtime.shutdown()
            except Exception:
                pass
        if hasattr(self, "main_pet_window") and self.main_pet_window is not None:
            self.main_pet_window.hide()
            self.main_pet_window.deleteLater()
        try:
            self.waapi_client.disconnect()
        except Exception:
            pass
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

"""Service container — all non-widget services MainWindow owns.

Construction order matters and is enforced by :meth:`ServiceContainer.create`:

1. ``resilience``, ``app_settings``, ``theme_manager`` — no inter-service deps
2. ``notification_service`` — reads app_settings
3. ``pet_service`` — must exist before anything that emits announcements
4. ``waapi_client`` → ``llm_service`` → ``auth_session`` → ``mcp_runtime``
   → ``web_access`` → ``memory_service`` → ``memory_manager``
5. ``agent_tools(parent_window, waapi_client)`` — depends on waapi_client
6. ``waapi_retriever`` — uses ``embedding_config``
7. ``tool_registry`` → ``plugin_runtime(tool_registry, plugin_base_context_factory)``
8. ``state_store``, ``code_executor(executor_context_factory)``, ``turn_controller``
9. ``scheduler_service``

MainWindow still wires Qt signals itself — the container only constructs
the objects and exposes them as attributes. Adding ``__getattr__`` on
MainWindow that delegates to ``self.services`` lets old call sites
(``self.llm_service`` etc.) keep working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

from src.gui.attachment_manager import AttachmentManager
from src.gui.common import DEFAULT_REMOTE_MODELS
from src.gui.market_operations import MarketOperations
from src.gui.memory_manager import MemoryManager
from src.gui.notification_service import NotificationService
from src.gui.theme_manager import ThemeManager
from src.engine.turn_controller import TurnController
from src.llm.embedding_defaults import (
    DEFAULT_REMOTE_BASE_URL,
    build_remote_api_config,
    get_default_embedding_config,
)
from src.llm.retrieval import WaapiDocRetriever
from src.llm.service import LLMService
from src.llm.agent_resilience import AgentResilienceManager
from src.pet.service import PetService
from src.pet.store import normalize_pet_settings
from src.services.auth_session import AuthSession
from src.services.mcp_runtime import MCPRuntimeService
from src.services.memory_service import MemoryService
from src.services.plugin_runtime import PluginRuntimeService
from src.services.scheduler import SchedulerService
from src.services.web_access import WebAccessService
from src.state.state_store import StateStore
from src.tools import create_default_registry
from src.utils.agent_tools import AgentToolbox
from src.utils.execution import CodeExecutor
from src.utils.storage import load_app_settings
from src.waapi.client import WwiseClient

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget


@dataclass
class ServiceContainer:
    """Holds every non-widget service the GUI depends on.

    Build via :meth:`create`; do not instantiate fields manually unless in
    tests that need to stub a subset.
    """

    # --- Settings & cross-cutting -------------------------------------
    app_settings: dict
    resilience: AgentResilienceManager
    theme_manager: ThemeManager
    market_operations: MarketOperations
    attachment_manager: AttachmentManager
    notification_service: NotificationService

    # --- Pet ----------------------------------------------------------
    pet_service: PetService

    # --- Core backends ------------------------------------------------
    waapi_client: WwiseClient
    llm_service: LLMService
    auth_session: AuthSession
    mcp_runtime: MCPRuntimeService
    web_access: WebAccessService
    memory_service: MemoryService
    memory_manager: MemoryManager
    agent_tools: AgentToolbox

    # --- Retrieval ----------------------------------------------------
    embedding_config: dict
    waapi_retriever: WaapiDocRetriever
    model_configs: dict

    # --- Engine / execution ------------------------------------------
    tool_registry: object
    plugin_runtime: PluginRuntimeService
    state_store: StateStore
    code_executor: CodeExecutor
    turn_controller: TurnController

    # --- Scheduling ---------------------------------------------------
    scheduler_service: SchedulerService

    # --- Theme mode (light/dark) — kept here so collaborators read it
    #     from the container instead of MainWindow.
    theme_mode: str = "light"

    @classmethod
    def create(
        cls,
        *,
        parent_window: "QWidget",
        persist_pet_callback: Callable[[dict], None],
        plugin_base_context_factory: Callable[[], dict],
        executor_context_factory: Callable[[], dict],
        analysis_progress_cb: Callable[[int, int, str], None] | None = None,
        analysis_finished_cb: Callable[[], None] | None = None,
    ) -> "ServiceContainer":
        resilience = AgentResilienceManager()
        app_settings = load_app_settings()
        theme_mode = app_settings.get("theme", "light")
        if theme_mode not in ("light", "dark"):
            theme_mode = "light"

        theme_manager = ThemeManager(parent_window)
        market_operations = MarketOperations(parent_window)
        attachment_manager = AttachmentManager(parent_window)
        notification_service = NotificationService(parent_window, app_settings.get("notifications"))

        # Pet first — anything that announces depends on it.
        app_settings["pets"] = normalize_pet_settings(app_settings)
        pet_service = PetService(parent_window)
        pet_service.set_state(app_settings["pets"])
        pet_service.set_persist_callback(persist_pet_callback)

        waapi_client = WwiseClient()
        llm_service = LLMService()
        auth_session = AuthSession()
        mcp_runtime = MCPRuntimeService(app_settings)
        web_access = WebAccessService()
        memory_service = MemoryService()
        memory_manager = MemoryManager(parent_window)
        agent_tools = AgentToolbox(parent_window, waapi_client)
        if analysis_progress_cb or analysis_finished_cb:
            agent_tools.set_analysis_progress_callbacks(
                progress_callback=analysis_progress_cb,
                finished_callback=analysis_finished_cb,
            )

        saved_api_key = (auth_session.get_api_key() or "").strip()
        saved_base_url = (getattr(auth_session, "get_base_url", lambda: "")() or "").strip()

        embedding_config = get_default_embedding_config()
        waapi_retriever = WaapiDocRetriever(
            api_key=embedding_config.get("api_key"),
            base_url=embedding_config.get("base_url"),
            embedding_model=embedding_config.get("embedding_model"),
        )

        _default_api = build_remote_api_config(
            api_key=saved_api_key,
            base_url=saved_base_url or DEFAULT_REMOTE_BASE_URL,
        )
        model_configs = {name: dict(_default_api) for name in DEFAULT_REMOTE_MODELS}

        tool_registry = create_default_registry()
        plugin_runtime = PluginRuntimeService(tool_registry, plugin_base_context_factory)
        app_settings["plugins"] = plugin_runtime.configure(app_settings)
        state_store = StateStore()

        code_executor = CodeExecutor(context_globals=executor_context_factory())
        turn_controller = TurnController(parent=parent_window)

        scheduler_service = SchedulerService(parent_window)

        return cls(
            app_settings=app_settings,
            resilience=resilience,
            theme_manager=theme_manager,
            market_operations=market_operations,
            attachment_manager=attachment_manager,
            notification_service=notification_service,
            pet_service=pet_service,
            waapi_client=waapi_client,
            llm_service=llm_service,
            auth_session=auth_session,
            mcp_runtime=mcp_runtime,
            web_access=web_access,
            memory_service=memory_service,
            memory_manager=memory_manager,
            agent_tools=agent_tools,
            embedding_config=embedding_config,
            waapi_retriever=waapi_retriever,
            model_configs=model_configs,
            tool_registry=tool_registry,
            plugin_runtime=plugin_runtime,
            state_store=state_store,
            code_executor=code_executor,
            turn_controller=turn_controller,
            scheduler_service=scheduler_service,
            theme_mode=theme_mode,
        )

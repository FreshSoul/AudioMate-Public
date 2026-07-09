"""Model / API-key configuration behaviour for ``MainWindow``.

Extracted verbatim from ``MainWindow`` (the contiguous block from
``change_model`` through ``_on_models_fetched``). It owns model switching,
remote provider (API key / base URL) propagation across model presets, the
WAAPI doc-retriever's async embedding initialisation, and the background
refresh of the available remote model list.

Follows the same back-reference convention as the other GUI helpers
(``ThemeManager``, ``PetIntegrationController``, ``LayoutController`` …):
every method operates on the owning ``MainWindow`` via ``w = self.window``.
``MainWindow`` keeps thin delegating wrappers so all signal connections and
call sites keep working unchanged. Runtime state (``model_configs``,
``_last_model_signature``, ``_retriever_thread``, ``_model_fetcher`` …)
stays on the window exactly where ``__init__`` initialises it; worker
QThreads remain referenced from the window so their lifetime is unchanged.
"""

from __future__ import annotations

from urllib.parse import urlparse

from PyQt6.QtCore import QThread, pyqtSignal

from src.gui.common import DEFAULT_REMOTE_MODELS
from src.gui.runtime_support import _ModelFetcher
from src.llm.embedding_defaults import DEFAULT_REMOTE_BASE_URL, build_remote_api_config
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


class ModelConfigController:
    """Owns model/API configuration for a single ``MainWindow``."""

    def __init__(self, window):
        self.window = window

    def change_model(self, model_name):
        """切换 LLM 模型及对应配置"""
        w = self.window
        remote_config = w._get_remote_runtime_config()
        api_key = remote_config.get("api_key", "")
        base_url = remote_config.get("base_url", DEFAULT_REMOTE_BASE_URL)

        # 尝试从预设加载配置
        if hasattr(w, 'model_configs') and model_name in w.model_configs:
            preset = w.model_configs[model_name]

            if "api_key" in preset:
                api_key = (preset.get("api_key") or "").strip()

            if "base_url" in preset:
                preset_base_url = (preset.get("base_url") or "").strip()
                if preset_base_url:
                    base_url = preset_base_url

        signature = (model_name, (api_key or "").strip(), (base_url or "").strip())
        if signature == w._last_model_signature:
            return

        w.llm_service.set_config(api_key, base_url, model_name)
        w._last_model_signature = signature
        parsed_base_url = urlparse(base_url or "")
        logger.info("Model switched: model=%s base_url_host=%s", model_name, parsed_base_url.netloc or parsed_base_url.path)
        w.input_field.setPlaceholderText("Ask AudioMate...")

        # Initialize retriever with dedicated embedding configuration.
        w.waapi_retriever.configure(
            api_key=w.embedding_config.get("api_key"),
            base_url=w.embedding_config.get("base_url"),
            embedding_model=w.embedding_config.get("embedding_model"),
        )
        w._init_retriever_async()

    def _init_retriever_async(self):
        """Initialize WAAPI doc retriever embeddings in a background thread."""
        w = self.window
        init_signature = w.waapi_retriever._current_init_signature()
        if w._retriever_init_signature == init_signature and w._retriever_init_status:
            return
        if hasattr(w, '_retriever_thread') and w._retriever_thread and w._retriever_thread.isRunning():
            return  # Already initializing

        class RetrieverInitThread(QThread):
            finished_signal = pyqtSignal(str)
            def __init__(self, retriever):
                super().__init__()
                self.retriever = retriever
            def run(self):
                try:
                    status = self.retriever.initialize()
                except MemoryError:
                    status = "MemoryError during retriever init; using TF-IDF fallback"
                except Exception as e:
                    status = f"Retriever init failed: {e}"
                self.finished_signal.emit(status)

        w._retriever_thread = RetrieverInitThread(w.waapi_retriever)
        w._retriever_thread.finished_signal.connect(w._on_retriever_init_finished)
        w._retriever_thread.start()

    def _on_retriever_init_finished(self, status: str):
        w = self.window
        w._retriever_init_signature = w.waapi_retriever._current_init_signature()
        w._retriever_init_status = status or ""
        logger.info("WAAPI doc retriever init finished: %s", status)

    def _get_remote_runtime_config(self):
        w = self.window
        fallback_key = (w.auth_session.get_api_key() or "").strip()
        fallback_base_url = (
            getattr(w.auth_session, "get_base_url", lambda: "")() or DEFAULT_REMOTE_BASE_URL
        ).strip()
        for preset in w.model_configs.values():
            base_url = (preset.get("base_url") or "").strip()
            if "localhost" in base_url.lower():
                continue
            api_key = (preset.get("api_key") or fallback_key).strip()
            return build_remote_api_config(api_key=api_key, base_url=base_url or DEFAULT_REMOTE_BASE_URL)
        return build_remote_api_config(api_key=fallback_key, base_url=fallback_base_url)

    def _sync_remote_provider_config(self, api_key: str, base_url: str = ""):
        w = self.window
        remote_api = build_remote_api_config(api_key=api_key, base_url=base_url or DEFAULT_REMOTE_BASE_URL)
        for preset in w.model_configs.values():
            base_url = (preset.get("base_url") or "").strip().lower()
            if "localhost" in base_url:
                continue
            preset["api_key"] = remote_api["api_key"]
            preset["base_url"] = remote_api["base_url"]

    def _apply_remote_models(self, models: list):
        w = self.window
        remote_api = w._get_remote_runtime_config()
        current_text = w.model_selector.currentText()

        local_presets = {}
        for name, preset in list(w.model_configs.items()):
            bu = (preset.get("base_url") or "").strip().lower()
            if "localhost" in bu:
                local_presets[name] = preset

        merged_remote_models = []
        for model_id in list(DEFAULT_REMOTE_MODELS) + list(models or []):
            normalized = (model_id or "").strip()
            if not normalized or normalized in merged_remote_models:
                continue
            merged_remote_models.append(normalized)

        new_configs = {}
        for model_id in merged_remote_models:
            new_configs[model_id] = dict(remote_api)
        new_configs.update(local_presets)
        w.model_configs = new_configs

        w.model_selector.blockSignals(True)
        w.model_selector.clear()
        w.model_selector.addItems(merged_remote_models + list(local_presets.keys()))
        if current_text and w.model_selector.findText(current_text) != -1:
            w.model_selector.setCurrentText(current_text)
        elif w.model_selector.findText(DEFAULT_REMOTE_MODELS[0]) != -1:
            w.model_selector.setCurrentText(DEFAULT_REMOTE_MODELS[0])
        elif w.model_selector.count() > 0:
            w.model_selector.setCurrentIndex(0)
        w.model_selector.blockSignals(False)

    def apply_user_api_key(self, api_key: str, base_url: str = ""):
        w = self.window
        normalized_key = (api_key or "").strip()
        normalized_base_url = (base_url or "").strip()
        logger.info("User API configuration updated: has_key=%s base_url_set=%s", bool(normalized_key), bool(normalized_base_url))
        w._sync_remote_provider_config(normalized_key, normalized_base_url)

        current_model = w.model_selector.currentText()
        if current_model:
            w.change_model(current_model)

        # 密钥变更后刷新可用模型列表
        w._trigger_model_refresh()

    # ── 获取可用模型列表 ──────────────────────────────
    def _trigger_model_refresh(self):
        """后台获取当前密钥可用的模型并更新选择器"""
        w = self.window
        remote_api = w._get_remote_runtime_config()
        api_key = (remote_api.get("api_key") or "").strip()
        base_url = (remote_api.get("base_url") or "").strip()
        if not api_key or not base_url:
            logger.info("Skipping remote model refresh: missing_key_or_base_url")
            return
        # 避免重复请求
        if w._model_fetcher is not None and w._model_fetcher.isRunning():
            logger.info("Skipping remote model refresh: already_running")
            return
        logger.info("Starting remote model refresh")
        w._model_fetcher = _ModelFetcher(api_key, base_url, parent=w)
        w._model_fetcher.finished.connect(w._on_models_fetched)
        w._model_fetcher.start()

    def _on_models_fetched(self, models: list):
        """后台线程返回模型列表后更新 UI"""
        w = self.window
        if not models:
            models = list(DEFAULT_REMOTE_MODELS)

        w._apply_remote_models(models)

        # 触发一次 change_model 确保 LLM service 使用当前选中的模型配置
        selected = w.model_selector.currentText()
        if selected:
            w.change_model(selected)

        logger.info("Remote model list applied: count=%s", len(models))

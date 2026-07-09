"""Page-navigation (settings/market/knowledge/schedule) for ``MainWindow``.

Extracted verbatim from ``MainWindow``: the open/close pairs for the
stacked sub-pages (settings, market, knowledge, schedule), the feedback /
donate QR dialogs, and the pet-window entry point into settings. Each
``open_*`` collapses the sidebar (remembering the prior state) and animates
the page stack; each ``close_*`` restores it.

Same conventions as the other controllers: stateless, back-reference via
``w = self.window`` (``_sidebar_was_collapsed`` stays on the window),
attached lazily via ``_dialog_controller_for``.
"""

from __future__ import annotations

from src.gui.widgets import FeedbackQRDialog
from src.utils.app_logger import get_logger

logger = get_logger(__name__)


class DialogController:
    """Owns sub-page navigation and QR dialogs for a single ``MainWindow``."""

    def __init__(self, window):
        self.window = window

    def open_settings(self):
        w = self.window
        if hasattr(w, "settings_page"):
            w.settings_page.set_mcp_settings(w.app_settings)
            w.settings_page.set_plugin_settings(w.app_settings)
            w.settings_page.set_notification_settings(w.app_settings)
            w._refresh_settings_memory_page()
            w.settings_page._refresh_login_state()
            w.settings_page._refresh_api_key_state()
            w.page_animator.animate_to(w.settings_page, direction="left")
            w._sync_floating_panel_visibility(animated=True)
            w._sync_navigation_styles()

    def _open_buddy_settings(self):
        w = self.window
        w.open_settings()
        if hasattr(w, "settings_page"):
            try:
                w.settings_page.select_settings_section("pets")
            except Exception:
                pass

    def open_market(self):
        w = self.window
        if hasattr(w, "market_page"):
            w._sidebar_was_collapsed = w.sidebar_collapsed
            if not w.sidebar_collapsed:
                w.set_sidebar_collapsed(True, animated=True)
            w.page_animator.animate_to(w.market_page, direction="left")
            w._sync_floating_panel_visibility(animated=True)
            w._sync_navigation_styles()
            w.refresh_market_catalog()

    def close_market(self):
        w = self.window
        if hasattr(w, "page_stack") and hasattr(w, "chat_page"):
            w.page_animator.animate_to(w.chat_page, direction="right")
            was = getattr(w, '_sidebar_was_collapsed', True)
            if not was:
                w.set_sidebar_collapsed(False, animated=True)
            w._sync_floating_panel_visibility(animated=True)
            w._sync_navigation_styles()

    def close_settings(self):
        w = self.window
        if hasattr(w, "page_stack") and hasattr(w, "chat_page"):
            w.page_animator.animate_to(w.chat_page, direction="right")
            w._sync_floating_panel_visibility(animated=True)
            w._sync_navigation_styles()

    def open_feedback(self):
        w = self.window
        logger.info("Feedback dialog opened")
        qr_path = w._asset_path("feedback_qr.png")
        dialog = FeedbackQRDialog(qr_path, theme_mode=w.theme_mode, parent=w)
        dialog.exec()

    def open_donate(self):
        w = self.window
        qr_path = w._asset_path("donate_qr.png")
        dialog = FeedbackQRDialog(
            qr_path,
            theme_mode=w.theme_mode,
            parent=w,
            title_text="赞赏支持",
            window_title="赞赏支持",
            show_logs_button=False,
        )
        dialog.exec()

    def open_knowledge(self):
        w = self.window
        if hasattr(w, "knowledge_page"):
            # 记住进入前的侧边栏状态，然后隐藏侧边栏
            w._sidebar_was_collapsed = w.sidebar_collapsed
            if not w.sidebar_collapsed:
                w.set_sidebar_collapsed(True, animated=True)
            w.knowledge_page.refresh()
            w.page_animator.animate_to(w.knowledge_page, direction="left")
            w._sync_floating_panel_visibility(animated=True)
            w._sync_navigation_styles()

    def close_knowledge(self):
        w = self.window
        if hasattr(w, "page_stack") and hasattr(w, "chat_page"):
            w.page_animator.animate_to(w.chat_page, direction="right")
            # 恢复进入前的侧边栏状态
            was = getattr(w, '_sidebar_was_collapsed', True)
            if not was:
                w.set_sidebar_collapsed(False, animated=True)
            w._sync_floating_panel_visibility(animated=True)
            w._sync_navigation_styles()
            w._refresh_kb_selector()

    def open_schedule(self):
        w = self.window
        if hasattr(w, "schedule_page"):
            w._sidebar_was_collapsed = w.sidebar_collapsed
            if not w.sidebar_collapsed:
                w.set_sidebar_collapsed(True, animated=True)
            w.schedule_page.set_tasks(w.scheduler_service.tasks())
            w.page_animator.animate_to(w.schedule_page, direction="left")
            w._sync_floating_panel_visibility(animated=True)
            w._sync_navigation_styles()

    def close_schedule(self):
        w = self.window
        if hasattr(w, "page_stack") and hasattr(w, "chat_page"):
            w.page_animator.animate_to(w.chat_page, direction="right")
            was = getattr(w, '_sidebar_was_collapsed', True)
            if not was:
                w.set_sidebar_collapsed(False, animated=True)
            w._sync_floating_panel_visibility(animated=True)
            w._sync_navigation_styles()

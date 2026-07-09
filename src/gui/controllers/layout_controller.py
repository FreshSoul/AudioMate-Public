"""Sidebar / floating-panel layout behaviour for ``MainWindow``.

Extracted verbatim from ``MainWindow`` (the contiguous block from
``toggle_sidebar`` through the body of ``resizeEvent``). It owns the
collapsible sidebar animation, the floating quick-action panel's
visibility/positioning, and the responsive top-bar / input-wrapper margins.

Follows the same back-reference convention as the other GUI helpers
(``ThemeManager``, ``PetIntegrationController`` …): every method operates on
the owning ``MainWindow`` via ``w = self.window``. ``MainWindow`` keeps thin
delegating wrappers so all signal connections and call sites keep working
unchanged. Layout/animation state (``sidebar_collapsed``,
``sidebar_animation``, ``floating_panel_fade_animation`` …) stays on the
window exactly where ``__init__`` initialises it; Qt animations remain
parented to the window so their lifetime is unchanged.

``resizeEvent`` is a Qt override and therefore stays on ``MainWindow`` (it
must call ``super().resizeEvent``); only its body delegates here via
``on_resize``.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation

from src.utils.storage import save_app_settings


class LayoutController:
    """Owns sidebar / floating-panel layout for a single ``MainWindow``."""

    def __init__(self, window):
        self.window = window

    def toggle_sidebar(self):
        w = self.window
        self.set_sidebar_collapsed(not w.sidebar_collapsed, animated=True)

    def set_sidebar_collapsed(self, collapsed, animated=True):
        w = self.window
        w.sidebar_collapsed = bool(collapsed)
        target_width = 0 if w.sidebar_collapsed else w.sidebar_expanded_width

        if w.sidebar_animation:
            w.sidebar_animation.stop()
            w.sidebar_animation = None

        if w.sidebar_fade_animation:
            w.sidebar_fade_animation.stop()
            w.sidebar_fade_animation = None

        if animated:
            width_animation = QPropertyAnimation(w.sidebar, b"maximumWidth", w)
            width_animation.setDuration(220)
            width_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            width_animation.setStartValue(w.sidebar.width())
            width_animation.setEndValue(target_width)
            width_animation.valueChanged.connect(w._apply_sidebar_width)

            fade_animation = QPropertyAnimation(w.sidebar_opacity, b"opacity", w)
            fade_animation.setDuration(200)
            fade_animation.setStartValue(w.sidebar_opacity.opacity())
            fade_animation.setEndValue(0.62 if w.sidebar_collapsed else 1.0)
            fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

            group = QParallelAnimationGroup(w)
            group.addAnimation(width_animation)
            group.addAnimation(fade_animation)
            w.sidebar_animation = group
            w.sidebar_fade_animation = fade_animation
            group.start()
        else:
            w._apply_sidebar_width(target_width)
            w.sidebar_opacity.setOpacity(0.62 if w.sidebar_collapsed else 1.0)

        w.sidebar_collapse_btn.setText("⌄" if not w.sidebar_collapsed else "⌃")
        w.float_toggle_btn.setText("☰")
        w._sync_floating_panel_visibility(animated=animated)
        w.update_top_bar_margins()
        w.update_input_wrapper_margins()
        w._sync_navigation_styles()
        w.app_settings["sidebar_collapsed"] = w.sidebar_collapsed
        save_app_settings(w.app_settings)

    def _sync_floating_panel_visibility(self, animated=False):
        w = self.window
        if not hasattr(w, "floating_panel"):
            return
        on_sub_page = (
            hasattr(w, "page_stack")
            and (
                (hasattr(w, "settings_page") and w.page_stack.currentWidget() == w.settings_page)
                or (hasattr(w, "knowledge_page") and w.page_stack.currentWidget() == w.knowledge_page)
                or (hasattr(w, "schedule_page") and w.page_stack.currentWidget() == w.schedule_page)
                or (hasattr(w, "market_page") and w.page_stack.currentWidget() == w.market_page)
            )
        )
        should_show = w.sidebar_collapsed and not on_sub_page
        if w.floating_panel_fade_animation:
            w.floating_panel_fade_animation.stop()
            w.floating_panel_fade_animation = None

        if not animated:
            w.floating_panel.setVisible(should_show)
            w.floating_opacity.setOpacity(1.0 if should_show else 0.0)
            return

        if should_show:
            w.floating_panel.setVisible(True)
            animation = QPropertyAnimation(w.floating_opacity, b"opacity", w)
            animation.setDuration(220)
            animation.setStartValue(w.floating_opacity.opacity())
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.start()
            w.floating_panel_fade_animation = animation
        else:
            animation = QPropertyAnimation(w.floating_opacity, b"opacity", w)
            animation.setDuration(180)
            animation.setStartValue(w.floating_opacity.opacity())
            animation.setEndValue(0.0)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            animation.finished.connect(lambda: w.floating_panel.setVisible(False))
            animation.start()
            w.floating_panel_fade_animation = animation

    def _apply_sidebar_width(self, value):
        w = self.window
        width_value = int(value)
        w.sidebar.setMinimumWidth(width_value)
        w.sidebar.setMaximumWidth(width_value)
        w.sidebar.setFixedWidth(width_value)

    def update_floating_panel_position(self):
        w = self.window
        if not hasattr(w, "floating_panel"):
            return
        w.floating_panel.move(16, 76)

    def update_top_bar_margins(self):
        w = self.window
        if not hasattr(w, "top_bar"):
            return
        left_margin = 96 if w.sidebar_collapsed else 30
        w.top_bar.setContentsMargins(left_margin, 10, 30, 10)

    def update_input_wrapper_margins(self):
        w = self.window
        if not hasattr(w, "input_wrapper"):
            return
        left_margin = 108 if w.sidebar_collapsed else 36
        right_margin = 40 if w.sidebar_collapsed else 36
        w.input_wrapper.setContentsMargins(left_margin, 18, right_margin, 20)

    def on_resize(self, event):
        """Body of ``MainWindow.resizeEvent`` (the override itself stays on the
        window so it can call ``super().resizeEvent``)."""
        w = self.window
        w.update_floating_panel_position()
        w.update_input_wrapper_margins()

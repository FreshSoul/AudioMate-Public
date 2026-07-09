"""Theme application helpers for the AudioMate main window."""

from __future__ import annotations

import os

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtCore import QSize

from src.gui.theme import DARK_STYLESHEET, STYLESHEET
from src.gui.widgets import (
    AgentThinkingWidget,
    ConfirmationWidget,
    FilePreviewWidget,
    FileWriteConfirmWidget,
    HistoryItemWidget,
    ImagePreviewWidget,
    IntentClarifyWidget,
    MessageBubble,
    StepProgressWidget,
)
from src.utils.storage import save_app_settings


class ThemeManager:
    """Apply theme styles to MainWindow-owned widgets.

    This keeps the first refactor intentionally conservative: MainWindow still
    owns widgets and public slots, while theme-specific styling lives here.
    """

    def __init__(self, owner):
        self.owner = owner

    @property
    def theme_mode(self) -> str:
        return "dark" if getattr(self.owner, "theme_mode", "light") == "dark" else "light"

    def theme_styles(self) -> dict:
        if self.theme_mode == "dark":
            return {
                "root": DARK_STYLESHEET,
                "sidebar": "background-color: #1E2228; border-right: 1px solid #343942;",
                "new_chat_btn": (
                    "QPushButton {"
                    "background-color: #4C63F6; color: #FFFFFF;"
                    "border: none; border-radius: 16px;"
                    "padding: 14px; font-weight: 600; font-size: 14px;"
                    "}"
                    "QPushButton:hover { background-color: #5A71FF; }"
                ),
                "settings_btn": "text-align: left; padding: 12px; color: #D0D3D8; background: transparent; border-radius: 12px;",
                "knowledge_btn": "text-align: left; padding: 12px; color: #D0D3D8; background: transparent; border-radius: 12px;",
                "sidebar_title": "QLabel#sidebarTitle { color: #B6BEC9; font-size: 13px; font-weight: 500; border: none; background: transparent; padding: 0px; margin: 0px; }",
                "sidebar_toggle_btn": (
                    "QPushButton {"
                    "background-color: #2B313A; color: #D7DDEA; border: 1px solid #39414D; border-radius: 17px; font-size: 14px; font-weight: 700;"
                    "}"
                    "QPushButton:hover { background-color: #343B47; }"
                ),
                "status_label": "color: #AEB4BE; font-size: 13px;",
                "connect_btn": "background: #31353B; border-radius: 12px; font-size: 12px; padding: 5px; color: #E6E6E6;",
                "feedback_btn": (
                    "QPushButton#feedbackButton {"
                    "background: #31353B; color: #78A8FF; border: none; border-radius: 12px;"
                    "padding: 4px;"
                    "}"
                    "QPushButton#feedbackButton:hover { background: #3A414E; color: #9FC1FF; }"
                    "QPushButton#feedbackButton:pressed { background: #29303B; }"
                ),
                "donate_btn": (
                    "QPushButton#donateButton {"
                    "background: #31353B; color: #78A8FF; border: none; border-radius: 12px;"
                    "padding: 4px;"
                    "}"
                    "QPushButton#donateButton:hover { background: #3A414E; color: #9FC1FF; }"
                    "QPushButton#donateButton:pressed { background: #29303B; }"
                ),
                "mode_label": "color: #C9CDD4; font-size: 13px;",
                "theme_label": "color: #C9CDD4; font-size: 13px;",
                "mode_selector": (
                    "QComboBox {"
                    "background: #31353B; border-radius: 12px; padding: 5px 10px; font-size: 13px; border: none; color: #E6E6E6;"
                    "}"
                    "QComboBox::drop-down { border: none; }"
                    "QComboBox::down-arrow { image: none; border: none; }"
                    "QComboBox QAbstractItemView {"
                    "background-color: #2B2F35;"
                    "border: 1px solid #4A4F57;"
                    "border-radius: 8px;"
                    "padding: 4px;"
                    "outline: none;"
                    "color: #E6E6E6;"
                    "}"
                    "QComboBox::item {"
                    "padding: 8px 12px;"
                    "border-radius: 4px;"
                    "color: #E6E6E6;"
                    "}"
                    "QComboBox::item:selected {"
                    "background-color: #2F4E7A;"
                    "color: #DCEBFF;"
                    "}"
                ),
                "theme_selector": (
                    "QComboBox {"
                    "background: #31353B; border-radius: 12px; padding: 5px 10px; font-size: 13px; border: none; color: #E6E6E6;"
                    "}"
                    "QComboBox::drop-down { border: none; }"
                    "QComboBox::down-arrow { image: none; border: none; }"
                    "QComboBox QAbstractItemView {"
                    "background-color: #2B2F35;"
                    "border: 1px solid #4A4F57;"
                    "border-radius: 8px;"
                    "padding: 4px;"
                    "outline: none;"
                    "color: #E6E6E6;"
                    "}"
                    "QComboBox::item {"
                    "padding: 8px 12px;"
                    "border-radius: 4px;"
                    "color: #E6E6E6;"
                    "}"
                    "QComboBox::item:selected {"
                    "background-color: #2F4E7A;"
                    "color: #DCEBFF;"
                    "}"
                ),
                "chat_container": "background-color: #1E1F22; border-radius: 26px;",
                "top_bar_card": (
                    "QFrame#topBarCard {"
                    "background: transparent;"
                    "border: none;"
                    "border-radius: 0px;"
                    "}"
                ),
                "input_pill": (
                    "QFrame#chatInputPill { background-color: #232733; border: 1px solid rgba(119, 126, 165, 0.14); border-radius: 34px; }"
                    "QFrame#chatInputPill:focus-within { background-color: #252A37; border: 1px solid #8D86FF; }"
                ),
                "input_wrapper": "QWidget#chatInputWrapper { background: transparent; }",
                "input_disclaimer": "QLabel#inputDisclaimerLabel { color: #858DA0; font-size: 12px; background: transparent; }",
                "model_selector": (
                    "QComboBox {"
                    "background: transparent;"
                    "color: #F2F4FF; font-weight: 700; font-size: 15px;"
                    "border: none; padding-left: 0px;"
                    "}"
                    "QComboBox::drop-down { border: none; width: 22px; }"
                    "QComboBox::down-arrow { image: none; }"
                    "QComboBox:hover { color: #BBB6FF; }"
                    "QComboBox QAbstractItemView {"
                    "background-color: #2B2F35;"
                    "border: 1px solid #4A4F57;"
                    "border-radius: 8px;"
                    "padding: 4px;"
                    "outline: none;"
                    "color: #E6E6E6;"
                    "}"
                    "QComboBox::item {"
                    "padding: 8px 12px;"
                    "border-radius: 4px;"
                    "color: #E6E6E6;"
                    "}"
                    "QComboBox::item:selected {"
                    "background-color: #2F4E7A;"
                    "color: #DCEBFF;"
                    "}"
                ),
                "line": "background: #4A4F57; margin: 0 8px;",
                "kb_selector": (
                    "QComboBox {"
                    "background: transparent;"
                    "color: #C7CEE7; font-size: 14px; font-weight: 500;"
                    "border: none; padding-left: 0px;"
                    "}"
                    "QComboBox::drop-down { border: none; width: 0px; }"
                    "QComboBox::down-arrow { image: none; }"
                    "QComboBox:hover { color: #BBB6FF; }"
                    "QComboBox QAbstractItemView {"
                    "background-color: #2B2F35;"
                    "border: 1px solid #4A4F57;"
                    "border-radius: 8px;"
                    "padding: 4px;"
                    "outline: none;"
                    "color: #E6E6E6;"
                    "}"
                    "QComboBox::item {"
                    "padding: 8px 12px;"
                    "border-radius: 4px;"
                    "color: #E6E6E6;"
                    "}"
                    "QComboBox::item:selected {"
                    "background-color: #2F4E7A;"
                    "color: #DCEBFF;"
                    "}"
                ),
                "kb_line": "background: #4A4F57; margin: 0 8px;",
                "input_field": "background: transparent; border: none; font-size: 18px; padding: 0; color: #F1F4FF;",
                "voice_btn": (
                    "QPushButton {"
                    "background: transparent; color: #C7CEE7; border: none; border-radius: 20px; font-size: 18px; font-weight: 500;"
                    "}"
                    "QPushButton:hover { background: rgba(141, 134, 255, 0.10); color: #FFFFFF; }"
                    "QPushButton:disabled { color: #72798A; }"
                ),
                "send_btn": (
                    "QPushButton {"
                    "background-color: #7D73FF; color: #FFFFFF; border: none;"
                    "border-radius: 26px; font-size: 20px; font-weight: 700;"
                    "}"
                    "QPushButton:hover { background-color: #6F63FF; }"
                    "QPushButton:disabled { background-color: #373C49; color: #858DA0; }"
                ),
                "floating_panel": (
                    "QFrame#floatingPanel {"
                    "background: rgba(30, 34, 40, 0.94);"
                    "border: 1px solid rgba(132, 146, 176, 0.16);"
                    "border-radius: 24px;"
                    "}"
                ),
                "floating_btn": (
                    "QPushButton {"
                    "background: transparent; color: #D0D3D8; border: none; border-radius: 10px; font-size: 14px;"
                    "}"
                    "QPushButton:hover { background-color: #2B2F35; color: #FFFFFF; }"
                ),
            }
        return {
            "root": STYLESHEET,
            "sidebar": "background-color: #F8FAFD; border-right: 1px solid #E7EBF4;",
            "new_chat_btn": (
                "QPushButton {"
                "background-color: #4C63F6; color: #FFFFFF;"
                "border: none; border-radius: 16px;"
                "padding: 14px; font-weight: 600; font-size: 14px;"
                "}"
                "QPushButton:hover { background-color: #5A71FF; }"
            ),
            "settings_btn": "text-align: left; padding: 12px; color: #444746; background: transparent; border-radius: 12px;",
            "knowledge_btn": "text-align: left; padding: 12px; color: #444746; background: transparent; border-radius: 12px;",
            "sidebar_title": "QLabel#sidebarTitle { color: #4A556A; font-size: 13px; font-weight: 500; border: none; background: transparent; padding: 0px; margin: 0px; }",
            "sidebar_toggle_btn": (
                "QPushButton {"
                "background-color: #F4F6FF; color: #53627A; border: 1px solid #E1E7F5; border-radius: 17px; font-size: 14px; font-weight: 700;"
                "}"
                "QPushButton:hover { background-color: #EEF2FF; }"
            ),
            "status_label": "color: #747775; font-size: 13px;",
            "connect_btn": "background: #F0F4F9; border-radius: 12px; font-size: 12px; padding: 5px;",
            "feedback_btn": (
                "QPushButton#feedbackButton {"
                "background: #F0F4F9; color: #4E83D9; border: none; border-radius: 12px;"
                "padding: 4px;"
                "}"
                "QPushButton#feedbackButton:hover { background: #E3ECFF; color: #2F6FD6; }"
                "QPushButton#feedbackButton:pressed { background: #D8E6FF; }"
            ),
            "donate_btn": (
                "QPushButton#donateButton {"
                "background: #F0F4F9; color: #4E83D9; border: none; border-radius: 12px;"
                "padding: 4px;"
                "}"
                "QPushButton#donateButton:hover { background: #E3ECFF; color: #2F6FD6; }"
                "QPushButton#donateButton:pressed { background: #D8E6FF; }"
            ),
            "mode_label": "color: #444746; font-size: 13px;",
            "theme_label": "color: #444746; font-size: 13px;",
            "mode_selector": (
                "QComboBox {"
                "background: #F0F4F9; border-radius: 12px; padding: 5px 10px; font-size: 13px; border: none; color: #1F1F1F;"
                "}"
                "QComboBox::drop-down { border: none; }"
                "QComboBox::down-arrow { image: none; border: none; }"
                "QComboBox QAbstractItemView {"
                "background-color: #FFFFFF;"
                "border: 1px solid #DADCE0;"
                "border-radius: 8px;"
                "padding: 4px;"
                "outline: none;"
                "color: #1F1F1F;"
                "selection-background-color: #D2E3FC;"
                "selection-color: #174EA6;"
                "}"
                "QComboBox::item {"
                "padding: 8px 12px;"
                "border-radius: 4px;"
                "color: #1F1F1F;"
                "background-color: #FFFFFF;"
                "}"
                "QComboBox::item:selected {"
                "background-color: #D2E3FC;"
                "color: #174EA6;"
                "}"
            ),
            "theme_selector": (
                "QComboBox {"
                "background: #F0F4F9; border-radius: 12px; padding: 5px 10px; font-size: 13px; border: none; color: #1F1F1F;"
                "}"
                "QComboBox::drop-down { border: none; }"
                "QComboBox::down-arrow { image: none; border: none; }"
                "QComboBox QAbstractItemView {"
                "background-color: #FFFFFF;"
                "border: 1px solid #DADCE0;"
                "border-radius: 8px;"
                "padding: 4px;"
                "outline: none;"
                "color: #1F1F1F;"
                "selection-background-color: #D2E3FC;"
                "selection-color: #174EA6;"
                "}"
                "QComboBox::item {"
                "padding: 8px 12px;"
                "border-radius: 4px;"
                "color: #1F1F1F;"
                "background-color: #FFFFFF;"
                "}"
                "QComboBox::item:selected {"
                "background-color: #D2E3FC;"
                "color: #174EA6;"
                "}"
            ),
            "chat_container": "background-color: #FFFFFF; border-radius: 26px;",
            "top_bar_card": "QFrame#topBarCard { background: #FFFFFF; border: none; border-radius: 24px; }",
            "input_pill": (
                "QFrame#chatInputPill { background-color: #FFFFFF; border: 1px solid rgba(162, 170, 211, 0.16); border-radius: 34px; }"
                "QFrame#chatInputPill:focus-within { background-color: #FFFFFF; border: 1px solid #A49BFF; }"
            ),
            "input_wrapper": "QWidget#chatInputWrapper { background: transparent; }",
            "input_disclaimer": "QLabel#inputDisclaimerLabel { color: #8A93A8; font-size: 12px; background: transparent; }",
            "model_selector": (
                "QComboBox {"
                "background: transparent;"
                "color: #35405E; font-weight: 700; font-size: 15px;"
                "border: none; padding-left: 0px;"
                "}"
                "QComboBox::drop-down { border: none; width: 22px; }"
                "QComboBox::down-arrow { image: none; }"
                "QComboBox:hover { color: #7066FF; }"
                "QComboBox QAbstractItemView {"
                "background-color: #FFFFFF;"
                "border: 1px solid #DADCE0;"
                "border-radius: 8px;"
                "padding: 4px;"
                "outline: none;"
                "}"
                "QComboBox::item {"
                "padding: 8px 12px;"
                "border-radius: 4px;"
                "color: #333333;"
                "}"
                "QComboBox::item:selected {"
                "background-color: #E8F0FE;"
                "color: #1967D2;"
                "}"
            ),
            "line": "background: #DADCE0; margin: 0 8px;",
            "kb_selector": (
                "QComboBox {"
                "background: transparent;"
                "color: #5F6985; font-size: 14px; font-weight: 500;"
                "border: none; padding-left: 0px;"
                "}"
                "QComboBox::drop-down { border: none; width: 0px; }"
                "QComboBox::down-arrow { image: none; }"
                "QComboBox:hover { color: #7066FF; }"
                "QComboBox QAbstractItemView {"
                "background-color: #FFFFFF;"
                "border: 1px solid #DADCE0;"
                "border-radius: 8px;"
                "padding: 4px;"
                "outline: none;"
                "}"
                "QComboBox::item {"
                "padding: 8px 12px;"
                "border-radius: 4px;"
                "color: #333333;"
                "}"
                "QComboBox::item:selected {"
                "background-color: #E8F0FE;"
                "color: #1967D2;"
                "}"
            ),
            "kb_line": "background: #DADCE0; margin: 0 8px;",
            "input_field": "background: transparent; border: none; font-size: 18px; padding: 0; color: #6A7395;",
            "voice_btn": (
                "QPushButton {"
                "background: transparent; color: #70799A; border: none; border-radius: 20px; font-size: 18px; font-weight: 500;"
                "}"
                "QPushButton:hover { background: #F1F0FF; color: #6257F2; }"
                "QPushButton:disabled { color: #B4BAC7; }"
            ),
            "send_btn": (
                "QPushButton {"
                "background-color: #7D73FF; color: #FFFFFF; border: none;"
                "border-radius: 26px; font-size: 20px; font-weight: 700;"
                "}"
                "QPushButton:hover { background-color: #6F63FF; }"
                "QPushButton:disabled { background-color: #DBDFF0; color: #9FA7BC; }"
            ),
            "floating_panel": "QFrame { background: transparent; border: none; }",
            "floating_btn": (
                "QPushButton {"
                "background: transparent; color: #5f6368; border: none; border-radius: 10px; font-size: 14px;"
                "}"
                "QPushButton:hover { background-color: #EEF2F7; color: #1F1F1F; }"
            ),
        }

    def apply_theme(self, theme_mode):
        owner = self.owner
        owner.theme_mode = "dark" if theme_mode == "dark" else "light"
        styles = self.theme_styles()
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(styles["root"])
        owner.setStyleSheet(styles["root"])

        owner.sidebar.setStyleSheet(styles["sidebar"])
        owner.new_chat_btn.setStyleSheet(styles["new_chat_btn"])
        owner.sidebar_title.setStyleSheet(styles["sidebar_title"])
        owner.sidebar_collapse_btn.setStyleSheet(styles["sidebar_toggle_btn"])
        owner.status_label.setStyleSheet(styles["status_label"])
        owner.connect_btn.setStyleSheet(styles["connect_btn"])
        owner.feedback_btn.setStyleSheet(styles["feedback_btn"])
        self.refresh_feedback_icon()
        if hasattr(owner, "donate_btn"):
            owner.donate_btn.setStyleSheet(styles["donate_btn"])
            self.refresh_donate_icon()
        owner.mode_label.setStyleSheet(styles["mode_label"])
        owner.theme_label.setStyleSheet(styles["theme_label"])
        owner.mode_selector.setStyleSheet(styles["mode_selector"])
        owner.theme_selector.setStyleSheet(styles["theme_selector"])
        owner.top_bar_card.setStyleSheet(styles["top_bar_card"])
        owner.chat_container.setStyleSheet(styles["chat_container"])
        owner.input_wrapper.setStyleSheet(styles["input_wrapper"])
        owner.input_disclaimer_label.setStyleSheet(styles["input_disclaimer"])
        owner.input_pill.setStyleSheet(styles["input_pill"])
        if hasattr(owner, "input_pill_shadow"):
            shadow_color = QColor(10, 22, 70, 55) if owner.theme_mode == "light" else QColor(0, 0, 0, 90)
            owner.input_pill_shadow.setColor(shadow_color)
        owner.model_selector.setStyleSheet(styles["model_selector"])
        owner.line.setStyleSheet(styles["line"])
        owner.kb_selector.setStyleSheet(styles["kb_selector"])
        if hasattr(owner, "skill_selector"):
            owner.skill_selector.setStyleSheet(styles["kb_selector"])
        owner.kb_line.setStyleSheet(styles["kb_line"])
        owner.input_field.setStyleSheet(styles["input_field"])
        owner.input_field.set_theme_mode(owner.theme_mode)
        owner.voice_btn.setStyleSheet(styles["voice_btn"])
        owner.send_btn.setStyleSheet(styles["send_btn"])
        owner.floating_panel.setStyleSheet(styles["floating_panel"])
        owner.history_list.setStyleSheet(self.history_list_style())
        if hasattr(owner, "settings_page"):
            owner.settings_page.apply_theme(owner.theme_mode)
        if hasattr(owner, "knowledge_page"):
            owner.knowledge_page.apply_theme(owner.theme_mode)
        if hasattr(owner, "market_page"):
            owner.market_page.apply_theme(owner.theme_mode)
        if hasattr(owner, "schedule_page"):
            owner.schedule_page.apply_theme(owner.theme_mode)

        owner.theme_selector.blockSignals(True)
        owner.theme_selector.setCurrentText("Dark" if owner.theme_mode == "dark" else "Light")
        owner.theme_selector.blockSignals(False)
        self.sync_navigation_styles()
        self.apply_theme_to_dynamic_widgets()
        self.update_connection_status_style()

    def history_list_style(self) -> str:
        if self.theme_mode == "dark":
            return (
                "QListWidget {"
                "background: #1E2228; border: 1px solid #343942; outline: none;"
                "border-radius: 22px; padding: 10px 8px;"
                "}"
                "QListWidget::item { margin: 4px 0px; border: none; background: transparent; }"
                "QListWidget::item:selected { background: transparent; }"
                "QListWidget::item:hover { background: transparent; }"
            )
        return (
            "QListWidget {"
            "background: #F5F7FB; border: 1px solid #E4EAF5; outline: none;"
            "border-radius: 22px; padding: 10px 8px;"
            "}"
            "QListWidget::item { margin: 4px 0px; border: none; background: transparent; }"
            "QListWidget::item:selected { background: transparent; }"
            "QListWidget::item:hover { background: transparent; }"
        )

    def sidebar_nav_button_style(self, active=False, centered=False) -> str:
        is_dark = self.theme_mode == "dark"
        if active:
            bg = "#293B68" if is_dark else "#E8F0FE"
            border = "#526DFF" if is_dark else "#CAD8FF"
            fg = "#F3F6FF" if is_dark else "#3157E0"
        else:
            bg = "transparent"
            border = "transparent"
            fg = "#C9D1E3" if is_dark else "#444746"
        hover_bg = "#262C35" if is_dark else "#F2F5FB"
        hover_border = "#3A4351" if is_dark else "#E3E9F5"
        text_align = "center" if centered else "left"
        return (
            "QPushButton {"
            f"text-align: {text_align}; padding: 13px 14px; color: {fg}; background: {bg};"
            f"border-radius: 16px; border: 1px solid {border}; font-size: 14px; font-weight: 600;"
            "}"
            f"QPushButton:hover {{ background: {hover_bg}; border: 1px solid {hover_border}; }}"
        )

    def floating_button_style(self, active=False, accent=False) -> str:
        is_dark = self.theme_mode == "dark"
        if active or accent:
            bg = "#5867F8" if is_dark else "#4C63F6"
            fg = "#FFFFFF"
            border = bg
            hover_bg = "#6B79FF" if is_dark else "#5A71FF"
        else:
            bg = "#252B35" if is_dark else "#F4F6FF"
            fg = "#D7DEEF" if is_dark else "#495164"
            border = "#3A4351" if is_dark else "#E3E9F8"
            hover_bg = "#303746" if is_dark else "#EDF1FF"
        return (
            "QPushButton {"
            f"background: {bg}; color: {fg}; border: 1px solid {border}; border-radius: 16px;"
            "font-size: 18px; font-weight: 700;"
            "}"
            f"QPushButton:hover {{ background: {hover_bg}; border: 1px solid {border}; }}"
            "QPushButton:pressed { padding-top: 1px; padding-left: 1px; }"
        )

    def sync_navigation_styles(self):
        owner = self.owner
        current = owner.page_stack.currentWidget() if hasattr(owner, "page_stack") else None
        owner.schedule_btn.setStyleSheet(self.sidebar_nav_button_style(active=current == owner.schedule_page, centered=True))
        owner.knowledge_btn.setStyleSheet(self.sidebar_nav_button_style(active=current == owner.knowledge_page))
        owner.settings_btn.setStyleSheet(self.sidebar_nav_button_style(active=current == owner.settings_page))
        owner.float_toggle_btn.setStyleSheet(self.floating_button_style())
        owner.float_new_chat_btn.setStyleSheet(self.floating_button_style())
        owner.float_schedule_btn.setStyleSheet(self.floating_button_style(active=current == owner.schedule_page))
        owner.float_knowledge_btn.setStyleSheet(self.floating_button_style(active=current == owner.knowledge_page))
        owner.float_market_btn.setStyleSheet(self.floating_button_style(active=current == owner.market_page))
        owner.float_settings_btn.setStyleSheet(self.floating_button_style(active=current == owner.settings_page))

    def refresh_feedback_icon(self):
        owner = self.owner
        if not hasattr(owner, "feedback_btn"):
            return
        icon_path = owner._asset_path("feedback_icon.svg")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            if icon.isNull():
                owner.feedback_btn.setIcon(QIcon())
                owner.feedback_btn.setText("Edit")
                return
            owner.feedback_btn.setText("")
            owner.feedback_btn.setIcon(icon)
            owner.feedback_btn.setIconSize(QSize(22, 22))
        else:
            owner.feedback_btn.setIcon(QIcon())
            owner.feedback_btn.setText("Edit")

    def refresh_donate_icon(self):
        owner = self.owner
        if not hasattr(owner, "donate_btn"):
            return
        for filename in ("donate_icon.svg", "donate_icon.png"):
            icon_path = owner._asset_path(filename)
            if not os.path.exists(icon_path):
                continue
            icon = QIcon(icon_path)
            if icon.isNull():
                continue
            owner.donate_btn.setText("")
            owner.donate_btn.setIcon(icon)
            owner.donate_btn.setIconSize(QSize(22, 22))
            return
        owner.donate_btn.setIcon(QIcon())
        owner.donate_btn.setText("Donate")

    def save_theme_preference(self):
        self.owner.app_settings["theme"] = self.owner.theme_mode
        save_app_settings(self.owner.app_settings)

    def apply_theme_to_dynamic_widgets(self):
        owner = self.owner
        for index in range(owner.chat_layout.count()):
            item = owner.chat_layout.itemAt(index)
            if not item:
                continue
            widget = item.widget()
            if isinstance(widget, MessageBubble):
                widget.apply_theme(owner.theme_mode)
            elif isinstance(widget, ConfirmationWidget):
                widget.apply_theme(owner.theme_mode)
            elif isinstance(widget, FileWriteConfirmWidget):
                widget.apply_theme(owner.theme_mode)
            elif isinstance(widget, StepProgressWidget):
                widget.apply_theme(owner.theme_mode)
            elif isinstance(widget, IntentClarifyWidget):
                widget.apply_theme(owner.theme_mode)
            elif isinstance(widget, AgentThinkingWidget):
                widget.apply_theme(owner.theme_mode)

        for index in range(owner.image_preview_layout.count() - 1):
            item = owner.image_preview_layout.itemAt(index)
            if not item:
                continue
            widget = item.widget()
            if isinstance(widget, ImagePreviewWidget):
                widget.apply_theme(owner.theme_mode)
            elif isinstance(widget, FilePreviewWidget):
                widget.apply_theme(owner.theme_mode)

        for index in range(owner.history_list.count()):
            list_item = owner.history_list.item(index)
            widget = owner.history_list.itemWidget(list_item)
            if isinstance(widget, HistoryItemWidget):
                widget.apply_theme(owner.theme_mode)

    def update_connection_status_style(self):
        owner = self.owner
        if owner.waapi_client.connected:
            owner.status_label.setStyleSheet("color: #1E8E3E; font-weight: bold;")
            return

        disconnected_color = "#AEB4BE" if owner.theme_mode == "dark" else "#747775"
        owner.status_label.setStyleSheet(f"color: {disconnected_color}; font-weight: normal;")

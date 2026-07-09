"""Stylesheets and theme helpers for the AudioMate GUI."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette


STYLESHEET = """
QMainWindow {
    background-color: #FFFFFF;
}
QWidget {
    color: #1F1F1F;
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 14px;
}
/* 侧边栏 */
QListWidget {
    background-color: #F8F9FA;
    border: none;
    outline: none;
}
QListWidget::item {
    padding: 0px;
    border-radius: 12px;
    margin: 2px 8px;
    color: #444746;
}
QListWidget::item:selected {
    background-color: #E8F0FE;
    color: #1967D2;
}
QListWidget::item:hover {
    background-color: #E0E4E9;
}
/* 滚动条 */
QScrollArea {
    border: none;
    background-color: #FFFFFF;
}
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 8px;
}
QScrollBar::handle:vertical {
    background: #DADCE0;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #BDC1C6;
}
QMenu {
    background-color: #FFFFFF;
    color: #1F1F1F;
    border: 1px solid #DADCE0;
    border-radius: 8px;
    padding: 4px 0px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
    margin: 2px 4px;
    color: #1F1F1F;
    background-color: #FFFFFF;
}
QMenu::item:selected {
    background-color: #E8F0FE;
    color: #1967D2;
}
QMenu::item:disabled {
    color: #9AA0A6;
    background-color: #FFFFFF;
}
QMenu::separator {
    height: 1px;
    background: #E0E0E0;
    margin: 4px 8px;
}
"""

DARK_STYLESHEET = """
QMainWindow {
    background-color: #1E1F22;
}
QWidget {
    color: #E6E6E6;
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 14px;
}
QListWidget {
    background-color: #23262B;
    border: none;
    outline: none;
}
QListWidget::item {
    padding: 0px;
    border-radius: 12px;
    margin: 2px 8px;
    color: #D0D3D8;
}
QListWidget::item:selected {
    background-color: #2F4E7A;
    color: #DCEBFF;
}
QListWidget::item:hover {
    background-color: #31353B;
}
QScrollArea {
    border: none;
    background-color: #1E1F22;
}
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 8px;
}
QScrollBar::handle:vertical {
    background: #4A4F57;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #616772;
}
QMenu {
    background-color: #23262B;
    color: #E6E6E6;
    border: 1px solid #4A4F57;
    border-radius: 8px;
    padding: 4px 0px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
    margin: 2px 4px;
    color: #E6E6E6;
    background-color: #23262B;
}
QMenu::item:selected {
    background-color: #2F4E7A;
    color: #DCEBFF;
}
QMenu::item:disabled {
    color: #7C828C;
    background-color: #23262B;
}
QMenu::separator {
    height: 1px;
    background: #4A4F57;
    margin: 4px 8px;
}
"""


def _apply_context_menu_theme(menu, theme_mode: str):
    is_dark = theme_mode == "dark"
    background = "#23262B" if is_dark else "#FFFFFF"
    text = "#E6E6E6" if is_dark else "#1F1F1F"
    border = "#4A4F57" if is_dark else "#DADCE0"
    hover_bg = "#2F4E7A" if is_dark else "#E8F0FE"
    hover_text = "#DCEBFF" if is_dark else "#1967D2"
    disabled = "#7C828C" if is_dark else "#9AA0A6"
    separator = "#4A4F57" if is_dark else "#E0E0E0"

    menu.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    palette = menu.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(background))
    palette.setColor(QPalette.ColorRole.Base, QColor(background))
    palette.setColor(QPalette.ColorRole.Button, QColor(background))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
    palette.setColor(QPalette.ColorRole.Text, QColor(text))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(hover_bg))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(hover_text))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(disabled))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(disabled))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(disabled))
    menu.setPalette(palette)
    menu.setStyleSheet(
        f"QMenu {{ background-color: {background}; color: {text}; border: 1px solid {border}; border-radius: 8px; padding: 4px 0px; }}"
        f"QMenu::item {{ padding: 6px 24px; border-radius: 4px; margin: 2px 4px; color: {text}; background-color: {background}; }}"
        f"QMenu::item:selected {{ background-color: {hover_bg}; color: {hover_text}; }}"
        f"QMenu::item:disabled {{ color: {disabled}; background-color: {background}; }}"
        f"QMenu::separator {{ height: 1px; background: {separator}; margin: 4px 8px; }}"
    )

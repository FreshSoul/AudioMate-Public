import webbrowser
import json
import os
import re
from PyQt6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QWidget,
    QFormLayout,
    QMessageBox,
    QDialog,
    QComboBox,
    QTextEdit,
    QFileDialog,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, QUrl, QTimer, QThread, pyqtSignal as Signal, Qt, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QColor, QDesktopServices, QPainter, QPen, QPainterPath
from src.llm.embedding_defaults import DEFAULT_REMOTE_BASE_URL, normalize_openai_base_url
from src.gui.common import configure_back_button, back_button_style
from src.gui.theme import _apply_context_menu_theme
from src.utils.storage import normalize_memory_settings
from src.utils.notification_settings import normalize_notification_settings
from src.utils.skill_store import (
    normalize_skill_settings,
    build_skill_payload,
    import_skill_directory,
    upsert_skill_item,
    remove_skill_item,
    update_skill_item,
)
from src.utils.plugin_store import (
    normalize_plugin_settings,
    build_plugin_payload,
    import_plugin_directory,
    upsert_plugin_item,
    remove_plugin_item,
    update_plugin_item,
)
from src.pet.store import (
    normalize_pet_settings,
    build_pet_payload,
    upsert_pet_item,
    remove_pet_item,
    set_desk_layout,
    set_floating_pet,
    is_fixed_default_pet,
    PET_KIND_SUB,
)
from src.pet.office import PetOfficeWidget




class AnimatedSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked=False, theme_mode="light", parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self._theme_mode = "dark" if theme_mode == "dark" else "light"
        self._thumb_position = 20.0 if self._checked else 2.0
        self._animation = QPropertyAnimation(self, b"thumbPosition", self)
        self._animation.setDuration(170)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)

    def isChecked(self):
        return self._checked

    def setThemeMode(self, theme_mode: str):
        self._theme_mode = "dark" if theme_mode == "dark" else "light"
        self.update()

    def _target_position(self, checked: bool) -> float:
        return 20.0 if checked else 2.0

    def getThumbPosition(self):
        return self._thumb_position

    def setThumbPosition(self, value):
        self._thumb_position = float(value)
        self.update()

    thumbPosition = pyqtProperty(float, fget=getThumbPosition, fset=setThumbPosition)

    def setChecked(self, checked: bool, animate: bool = True):
        checked = bool(checked)
        changed = checked != self._checked
        self._checked = checked
        target = self._target_position(checked)
        if animate:
            self._animation.stop()
            self._animation.setStartValue(self._thumb_position)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._thumb_position = target
            self.update()
        if changed:
            self.toggled.emit(self._checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked, animate=True)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track_rect = self.rect().adjusted(0, 0, 0, 0)

        if self._checked:
            track_color = QColor("#2EB85C") if self._theme_mode == "light" else QColor("#36B864")
            border_color = QColor(track_color)
        else:
            track_color = QColor("#C3CAD6") if self._theme_mode == "light" else QColor("#6A7282")
            border_color = QColor(track_color)

        painter.setPen(QPen(border_color, 1))
        painter.setBrush(track_color)
        painter.drawRoundedRect(track_rect.adjusted(0, 1, 0, -1), 11, 11)

        thumb_rect = track_rect.adjusted(0, 0, 0, 0)
        thumb_rect.setLeft(int(self._thumb_position))
        thumb_rect.setTop(2)
        thumb_rect.setWidth(18)
        thumb_rect.setHeight(18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(thumb_rect)


class SkillActionIconButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, kind: str, theme_mode="light", parent=None):
        super().__init__(parent)
        self.kind = kind if kind in {"edit", "delete"} else "edit"
        self._theme_mode = "dark" if theme_mode == "dark" else "light"
        self._hovered = False
        self._pressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(38, 38)

    def setThemeMode(self, theme_mode: str):
        self._theme_mode = "dark" if theme_mode == "dark" else "light"
        self.update()

    def enterEvent(self, _event):
        self._hovered = True
        self.update()

    def leaveEvent(self, _event):
        self._hovered = False
        self._pressed = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pressed and self.rect().contains(event.pos()):
            self.clicked.emit()
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def _colors(self):
        if self.kind == "edit":
            if self._theme_mode == "dark":
                return {
                    "border": QColor("#575CFF"),
                    "icon": QColor("#7B80FF"),
                    "bg": QColor(87, 92, 255, 28 if not self._hovered else 42),
                }
            return {
                "border": QColor("#DCDCFD"),
                "icon": QColor("#5D63F2"),
                "bg": QColor("#F4F3FF") if self._hovered else QColor("#FFFFFF"),
            }

        if self._theme_mode == "dark":
            return {
                "border": QColor("#6A3F46"),
                "icon": QColor("#FF6B72"),
                "bg": QColor(255, 107, 114, 20 if not self._hovered else 34),
            }
        return {
            "border": QColor("#FFDCDC"),
            "icon": QColor("#F2515C"),
            "bg": QColor("#FFF5F5") if self._hovered else QColor("#FFFFFF"),
        }

    def _draw_edit_icon(self, painter: QPainter, icon_color: QColor):
        pen = QPen(icon_color, 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.drawRoundedRect(11, 12, 14, 14, 3, 3)
        painter.drawLine(24, 10, 28, 6)
        painter.drawLine(26, 8, 29, 11)
        painter.drawLine(18, 20, 28, 10)
        painter.drawLine(16, 23, 19, 22)

    def _draw_delete_icon(self, painter: QPainter, icon_color: QColor):
        pen = QPen(icon_color, 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        path = QPainterPath()
        path.moveTo(13, 13)
        path.lineTo(27, 13)
        painter.drawPath(path)
        painter.drawRoundedRect(15, 13, 10, 14, 2.5, 2.5)
        painter.drawLine(18, 9, 22, 9)
        painter.drawLine(17, 9, 16, 13)
        painter.drawLine(23, 9, 24, 13)
        painter.drawLine(18, 17, 18, 23)
        painter.drawLine(20, 17, 20, 23)
        painter.drawLine(22, 17, 22, 23)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = self._colors()
        rect = self.rect().adjusted(1, 1, -1, -1)

        painter.setPen(QPen(colors["border"], 1.4))
        painter.setBrush(colors["bg"])
        painter.drawRoundedRect(rect, 13, 13)

        if self.kind == "edit":
            self._draw_edit_icon(painter, colors["icon"])
        else:
            self._draw_delete_icon(painter, colors["icon"])


class MCPOrderIconButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, direction: str, theme_mode="light", parent=None):
        super().__init__(parent)
        self.direction = direction if direction in {"up", "down"} else "up"
        self._theme_mode = "dark" if theme_mode == "dark" else "light"
        self._hovered = False
        self._pressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(32, 32)

    def setThemeMode(self, theme_mode: str):
        self._theme_mode = "dark" if theme_mode == "dark" else "light"
        self.update()

    def enterEvent(self, _event):
        self._hovered = True
        self.update()

    def leaveEvent(self, _event):
        self._hovered = False
        self._pressed = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pressed and self.rect().contains(event.pos()):
            self.clicked.emit()
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def _colors(self):
        if self._theme_mode == "dark":
            return {
                "border": QColor("#3A4250"),
                "icon": QColor("#AEB7C8"),
                "bg": QColor("#252B35") if self._hovered else QColor("#20242B"),
            }
        return {
            "border": QColor("#DCE4F2"),
            "icon": QColor("#53627A"),
            "bg": QColor("#F6F8FC") if self._hovered else QColor("#FFFFFF"),
        }

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = self._colors()
        rect = self.rect().adjusted(1, 1, -1, -1)

        painter.setPen(QPen(colors["border"], 1.2))
        painter.setBrush(colors["bg"])
        painter.drawRoundedRect(rect, 10, 10)

        pen = QPen(colors["icon"], 2.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        if self.direction == "up":
            path.moveTo(10, 19)
            path.lineTo(16, 13)
            path.lineTo(22, 19)
        else:
            path.moveTo(10, 13)
            path.lineTo(16, 19)
            path.lineTo(22, 13)
        painter.drawPath(path)


class SettingsDialog(QWidget):
    back_requested = pyqtSignal()
    api_key_updated = pyqtSignal(str, str)
    mcp_settings_updated = pyqtSignal(dict)
    plugin_settings_updated = pyqtSignal(dict)
    skill_settings_updated = pyqtSignal(dict)
    notification_settings_updated = pyqtSignal(dict)
    memory_settings_updated = pyqtSignal(dict)
    memory_record_delete_requested = pyqtSignal(str, str)
    memory_scope_clear_requested = pyqtSignal(str)
    user_memory_add_requested = pyqtSignal(str)
    pet_settings_updated = pyqtSignal(dict)
    pet_training_room_requested = pyqtSignal(str)
    pet_chat_clicked = pyqtSignal(str)
    pet_dispatch_requested = pyqtSignal(str)
    pet_skill_map_requested = pyqtSignal()

    def __init__(self, auth_session, app_settings=None, parent=None):
        super().__init__(parent)
        self.auth_session = auth_session
        self.theme_mode = "light"
        self._app_settings = app_settings if isinstance(app_settings, dict) else {}
        self._mcp_settings = self._normalize_mcp_settings(app_settings)
        self._plugin_settings = normalize_plugin_settings(app_settings)
        self._skill_settings = normalize_skill_settings(app_settings)
        self._notification_settings = normalize_notification_settings(
            app_settings.get("notifications") if isinstance(app_settings, dict) else None
        )
        self._memory_settings = normalize_memory_settings(
            app_settings.get("memory") if isinstance(app_settings, dict) else None
        )
        self._memory_records = {"session": [], "repo": [], "user": []}
        self._skill_show_all = False
        self._pet_settings = normalize_pet_settings(app_settings)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(26, 18, 26, 18)
        page_layout.setSpacing(14)

        header_layout = QHBoxLayout()
        self.back_btn = QPushButton("<")
        configure_back_button(self.back_btn)
        self.back_btn.clicked.connect(self.back_requested.emit)
        self.title_label = QLabel("Settings")
        self.title_label.setStyleSheet("font-size: 24px; font-weight: 600;")
        header_layout.addWidget(self.back_btn)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        page_layout.addLayout(header_layout)

        self.settings_sections = [
            {"key": "general", "title": "General", "builder": self._build_general_section},
            {"key": "memory", "title": "Memory", "builder": self._build_memory_section},
            {"key": "plugins", "title": "Plugins", "builder": self._build_plugin_section},
            {"key": "skills", "title": "Skills", "builder": self._build_skill_section},
            {"key": "pets", "title": "Buddy", "builder": self._build_pets_section},
            {"key": "mcp", "title": "MCP", "builder": self._build_mcp_section},
            {"key": "about", "title": "About / Updates", "builder": self._build_about_section},
        ]

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 2, 0, 0)
        content_layout.setSpacing(18)
        page_layout.addLayout(content_layout, 1)

        self.settings_nav = self._build_settings_sidebar(self.settings_sections)
        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("settingsContentStack")
        self.content_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        for section in self.settings_sections:
            self.content_stack.addWidget(self._create_settings_page(section["builder"]()))

        content_layout.addWidget(self.settings_nav, 0)
        content_layout.addWidget(self.content_stack, 1)
        self.settings_nav.setCurrentRow(0)

        self._refresh_login_state()
        self._refresh_api_key_state()
        self._refresh_plugin_state()
        self._refresh_skill_state()
        self._refresh_mcp_state()
        self._refresh_pet_state()

    def _build_settings_sidebar(self, sections):
        nav = QListWidget()
        nav.setObjectName("settingsSidebar")
        nav.setFixedWidth(176)
        nav.setFrameShape(QFrame.Shape.NoFrame)
        nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        nav.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        nav.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        for section in sections:
            item = QListWidgetItem(section["title"])
            item.setData(Qt.ItemDataRole.UserRole, section["key"])
            nav.addItem(item)

        nav.currentRowChanged.connect(self._on_settings_nav_changed)
        return nav

    def _create_settings_page(self, section_widget):
        scroll = QScrollArea()
        scroll.setObjectName("settingsPageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("settingsPageContent")
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 8, 0, 26)
        layout.setSpacing(18)
        section_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(section_widget)
        layout.addStretch(1)
        return scroll

    def _on_settings_nav_changed(self, row: int):
        if 0 <= row < self.content_stack.count():
            self.content_stack.setCurrentIndex(row)

    def select_settings_section(self, key: str):
        for row, section in enumerate(self.settings_sections):
            if section.get("key") == key:
                self.settings_nav.setCurrentRow(row)
                return True
        return False

    def _build_general_section(self):
        page = QWidget()
        page.setObjectName("settingsGeneralPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addWidget(self._build_key_section())
        layout.addWidget(self._build_notification_section())
        return page

    def _build_notification_section(self):
        card = QFrame()
        card.setObjectName("settingsCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(16)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(8)
        title_label = QLabel("任务提醒")
        title_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        desc_label = QLabel("任务完成或失败时，将 AudioMate 带到前台。")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 13px;")
        text_layout.addWidget(title_label)
        text_layout.addWidget(desc_label)

        self.notification_toggles = {}
        toggle = AnimatedSwitch(bool(self._notification_settings.get("enabled")), self.theme_mode)
        toggle.toggled.connect(lambda checked: self.on_toggle_notification("enabled", checked))
        self.notification_toggles["enabled"] = toggle

        layout.addLayout(text_layout, 1)
        layout.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        return card

    def _create_notification_toggle_row(self, key: str, title: str, desc: str):
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(12)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 12px;")
        text_wrap.addWidget(title_label)
        text_wrap.addWidget(desc_label)

        toggle = AnimatedSwitch(bool(self._notification_settings.get(key)), self.theme_mode)
        toggle.toggled.connect(lambda checked, setting_key=key: self.on_toggle_notification(setting_key, checked))
        self.notification_toggles[key] = toggle

        row.addLayout(text_wrap, 1)
        row.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _build_memory_section(self):
        card, layout = self._create_section(
            "Memory",
            "Manage current chat, project, and long-term user memories. Memories keep useful context, not full chat logs.",
        )
        self.memory_toggles = {}
        self.memory_tables = {}
        self.memory_empty_labels = {}
        self.memory_clear_buttons = {}

        layout.addLayout(self._create_memory_toggle_row(
            "enabled",
            "Allow the agent to read selected memories and save useful information after tasks.",
            "Allow the agent to read selected memories and save useful information after tasks.",
        ))

        toggle_grid = QHBoxLayout()
        toggle_grid.setContentsMargins(0, 4, 0, 4)
        toggle_grid.setSpacing(12)
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(4)
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(4)
        left_col.addLayout(self._create_memory_toggle_row("auto_inject_session", "Use chat memory", "Let the model remember important goals and results from the current chat."))
        left_col.addLayout(self._create_memory_toggle_row("auto_inject_repo", "Use project memory", "Let the model use remembered Wwise project paths, objects, and conventions."))
        left_col.addLayout(self._create_memory_toggle_row("auto_inject_user", "Use user memory", "Let the model use long-term preferences and workflow notes."))
        right_col.addLayout(self._create_memory_toggle_row("auto_save_session", "Save chat memory", "Save useful task context after a conversation."))
        right_col.addLayout(self._create_memory_toggle_row("auto_save_repo", "Save project memory", "Save project facts, WAAPI findings, and workflow conventions."))
        right_col.addLayout(self._create_memory_toggle_row("auto_save_user", "Save user memory", "Save stable preferences across projects."))
        toggle_grid.addLayout(left_col, 1)
        toggle_grid.addLayout(right_col, 1)
        layout.addLayout(toggle_grid)

        layout.addWidget(self._create_memory_scope_block(
            "session",
            "Chat Memory",
            "Important task goals, execution results, and conversation summaries from the current chat.",
        ))
        layout.addWidget(self._create_memory_scope_block(
            "repo",
            "Project Memory",
            "Objects, paths, WAAPI findings, and conventions for the current Wwise project.",
        ))
        layout.addWidget(self._create_memory_scope_block(
            "user",
            "User Memory",
            "Long-term personal preferences shared across projects.",
        ))

        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 4, 0, 0)
        add_row.setSpacing(10)
        self.user_memory_input = QLineEdit()
        self.user_memory_input.setPlaceholderText("Add a long-term memory, for example: prefer Chinese replies and preserve key commands.")
        self.user_memory_add_btn = QPushButton("Add Memory")
        self.user_memory_add_btn.setObjectName("primaryBtn")
        self.user_memory_add_btn.clicked.connect(self.on_add_user_memory)
        add_row.addWidget(self.user_memory_input, 1)
        add_row.addWidget(self.user_memory_add_btn)
        layout.addLayout(add_row)

        self._refresh_memory_state()
        return card

    def _create_memory_toggle_row(self, key: str, title: str, desc: str):
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(10)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(1)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 11px;")
        text_wrap.addWidget(title_label)
        text_wrap.addWidget(desc_label)

        toggle = AnimatedSwitch(bool(self._memory_settings.get(key)), self.theme_mode)
        toggle.toggled.connect(lambda checked, setting_key=key: self.on_toggle_memory_setting(setting_key, checked))
        self.memory_toggles[key] = toggle

        row.addLayout(text_wrap, 1)
        row.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _create_memory_scope_block(self, scope: str, title: str, desc: str):
        block = QFrame()
        block.setObjectName("memoryScopeBlock")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 8, 0, 2)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 12px;")
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("dangerBtn")
        clear_btn.clicked.connect(lambda _checked=False, memory_scope=scope: self.on_clear_memory_scope(memory_scope))
        self.memory_clear_buttons[scope] = clear_btn
        header.addWidget(title_label)
        header.addStretch()
        header.addWidget(clear_btn)
        layout.addLayout(header)
        layout.addWidget(desc_label)

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Type", "Content", "Updated", "Action"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos, memory_scope=scope: self.on_memory_table_context_menu(memory_scope, pos))
        table.setMinimumHeight(126)
        table.setMaximumHeight(190)
        header_view = table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 104)
        table.setColumnWidth(2, 152)
        table.setColumnWidth(3, 76)
        self.memory_tables[scope] = table
        layout.addWidget(table)

        empty_label = QLabel("No memories yet.")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label.setStyleSheet("font-size: 12px; padding: 6px 0;")
        self.memory_empty_labels[scope] = empty_label
        layout.addWidget(empty_label)
        return block

    def _memory_record_preview(self, record: dict) -> str:
        content = str(record.get("display_content") or record.get("content") or "").strip().replace("\n", " ")
        if len(content) > 160:
            return content[:157].rstrip() + "..."
        return content

    def _refresh_memory_state(self):
        if not hasattr(self, "memory_tables"):
            return
        for scope, table in self.memory_tables.items():
            records = [record for record in self._memory_records.get(scope, []) if isinstance(record, dict)]
            records.sort(key=lambda record: str(record.get("updated_at") or record.get("created_at") or ""), reverse=True)
            table._memory_row_records = records
            table.setRowCount(len(records))
            text_color = Qt.GlobalColor.white if self.theme_mode == "dark" else Qt.GlobalColor.black
            for row, record in enumerate(records):
                category_item = QTableWidgetItem(str(record.get("display_type") or record.get("category") or "memory"))
                content_item = QTableWidgetItem(self._memory_record_preview(record))
                updated_item = QTableWidgetItem(str(record.get("updated_at") or record.get("created_at") or ""))
                for item in (category_item, content_item, updated_item):
                    item.setForeground(text_color)
                content_item.setToolTip(str(record.get("content") or record.get("display_content") or ""))
                updated_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 0, category_item)
                table.setItem(row, 1, content_item)
                table.setItem(row, 2, updated_item)
                delete_btn = SkillActionIconButton("delete", self.theme_mode)
                delete_btn.setToolTip("Delete this memory")
                record_id = str(record.get("id") or "")
                delete_btn.clicked.connect(lambda rid=record_id, memory_scope=scope: self.on_delete_memory_record(memory_scope, rid))
                table.setCellWidget(row, 3, delete_btn)
                table.setRowHeight(row, 48)
            table.setVisible(bool(records))
            if scope in self.memory_empty_labels:
                self.memory_empty_labels[scope].setVisible(not records)
            if scope in self.memory_clear_buttons:
                self.memory_clear_buttons[scope].setEnabled(bool(records))

    def _memory_record_folder(self, record: dict) -> str:
        raw_path = str(record.get("path") or "").strip()
        if not raw_path:
            return ""
        folder = raw_path if os.path.isdir(raw_path) else os.path.dirname(raw_path)
        return folder if folder and os.path.isdir(folder) else ""

    def on_memory_table_context_menu(self, scope: str, pos):
        table = self.memory_tables.get(scope) if hasattr(self, "memory_tables") else None
        if table is None:
            return
        row = table.rowAt(pos.y())
        records = getattr(table, "_memory_row_records", [])
        if row < 0 or row >= len(records):
            return
        folder = self._memory_record_folder(records[row])
        if not folder:
            return
        menu = QMenu(table)
        _apply_context_menu_theme(menu, self.theme_mode)
        open_action = menu.addAction("Open memory folder")
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen == open_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _settings_table_style(self, header_padding="12px 10px") -> str:
        if self.theme_mode == "dark":
            table_bg = "#171A20"
            viewport_bg = "#171A20"
            header_bg = "#20242B"
            text = "#E6E6E6"
            header_text = "#AEB7C8"
            border = "#303641"
            row_border = "#262B34"
            selected_bg = "#24395D"
            selected_text = "#F4F8FF"
        else:
            table_bg = "#FFFFFF"
            viewport_bg = "#FFFFFF"
            header_bg = "#FFFFFF"
            text = "#24324A"
            header_text = "#61708C"
            border = "#E7EBF4"
            row_border = "#EFF3FA"
            selected_bg = "#E8F0FE"
            selected_text = "#174EA6"
        return (
            f"QTableWidget {{ background: {table_bg}; color: {text}; border: 1px solid {border}; "
            "border-radius: 16px; gridline-color: transparent; }"
            f"QHeaderView::section {{ background: {header_bg}; color: {header_text}; border: none; "
            f"padding: {header_padding}; font-size: 12px; font-weight: 600; }}"
            f"QTableWidget::item {{ background: {viewport_bg}; color: {text}; "
            f"border-bottom: 1px solid {row_border}; padding: 0 8px; }}"
            f"QTableWidget::item:selected {{ background: {selected_bg}; color: {selected_text}; }}"
        )

    def set_memory_settings(self, app_settings):
        self._memory_settings = normalize_memory_settings(
            app_settings.get("memory") if isinstance(app_settings, dict) else app_settings
        )
        if hasattr(self, "memory_toggles"):
            for key, toggle in self.memory_toggles.items():
                toggle.blockSignals(True)
                toggle.setChecked(bool(self._memory_settings.get(key)), animate=False)
                toggle.blockSignals(False)

    def set_memory_records(self, records: dict):
        source = records if isinstance(records, dict) else {}
        self._memory_records = {
            "session": list(source.get("session") or []),
            "repo": list(source.get("repo") or []),
            "user": list(source.get("user") or []),
        }
        self._refresh_memory_state()

    def on_toggle_memory_setting(self, key: str, enabled: bool):
        self._memory_settings = normalize_memory_settings(self._memory_settings)
        self._memory_settings[key] = bool(enabled)
        self.memory_settings_updated.emit(dict(self._memory_settings))

    def on_delete_memory_record(self, scope: str, record_id: str):
        if not record_id:
            return
        self.memory_record_delete_requested.emit(scope, record_id)

    def on_clear_memory_scope(self, scope: str):
        answer = QMessageBox.question(
            self,
            "Clear Memory",
            "Clear this memory scope? This will not delete the full chat history.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.memory_scope_clear_requested.emit(scope)

    def on_add_user_memory(self):
        text = self.user_memory_input.text().strip()
        if not text:
            return
        self.user_memory_add_requested.emit(text)
        self.user_memory_input.clear()

    def _create_section(self, title: str, desc: str):
        card = QFrame()
        card.setObjectName("settingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 13px;")

        card_layout.addWidget(title_label)
        if desc:
            card_layout.addWidget(desc_label)
        return card, card_layout

    def _build_about_section(self):
        from src.__version__ import __version__ as _ver
        card, layout = self._create_section(
            "About / Updates",
            f"Current version: v{_ver}. Configure AUDIOMATE_UPDATE_REPOSITORY=owner/repo to enable GitHub release checks.",
        )
        row = QHBoxLayout()
        check_btn = QPushButton("Check for Updates")
        check_btn.clicked.connect(self._on_check_update)
        row.addWidget(check_btn)
        repository = os.environ.get("AUDIOMATE_UPDATE_REPOSITORY", "").strip()
        if "/" in repository:
            open_page_btn = QPushButton("Open Releases")
            open_page_btn.clicked.connect(lambda: webbrowser.open(f"https://github.com/{repository}/releases"))
            row.addWidget(open_page_btn)
        row.addStretch(1)
        layout.addLayout(row)
        return card

    def _on_check_update(self):
        try:
            from src.gui.update_dialog import show_update_dialog
            show_update_dialog(self)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Updates", f"Unable to check for updates: {e}")


    def _build_key_section(self):
        card, layout = self._create_section("Model Provider", "Configure an OpenAI-compatible Base URL and API Key.")
        self.key_section_card = card

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText(DEFAULT_REMOTE_BASE_URL)
        form.addRow("Base URL", self.base_url_input)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("sk-...")
        form.addRow("API Key", self.api_key_input)
        layout.addLayout(form)

        key_actions = QHBoxLayout()
        key_actions.setContentsMargins(0, 4, 0, 0)
        self.save_key_btn = QPushButton("Save Provider Settings")
        self.save_key_btn.setObjectName("primaryBtn")
        key_actions.addWidget(self.save_key_btn)
        key_actions.addStretch()
        layout.addLayout(key_actions)
        self.save_key_btn.clicked.connect(self.on_save_key)
        return card

    def _build_plugin_section(self):
        card = QFrame()
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        self.plugin_section_title = QLabel("Plugins")
        self.plugin_section_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.plugin_count_badge = QLabel("0")
        self.plugin_count_badge.setObjectName("pluginCountBadge")
        self.plugin_count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plugin_count_badge.setFixedSize(24, 24)
        self.plugin_add_btn = QPushButton("Import Plugin")
        self.plugin_add_btn.setObjectName("primaryBtn")

        header_row.addWidget(self.plugin_section_title)
        header_row.addWidget(self.plugin_count_badge)
        header_row.addStretch()
        header_row.addWidget(self.plugin_add_btn)
        layout.addLayout(header_row)

        self.plugin_desc_label = QLabel("Plugins load local Python code and register callable tools. Imported plugins are enabled by default and can be disabled or removed later.")
        self.plugin_desc_label.setWordWrap(True)
        self.plugin_desc_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(self.plugin_desc_label)

        self.plugin_table = QTableWidget(0, 6)
        self.plugin_table.setHorizontalHeaderLabels(["Name", "Description", "Status", "Tools", "Updated", "Actions"])
        self.plugin_table.verticalHeader().setVisible(False)
        self.plugin_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.plugin_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.plugin_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.plugin_table.setShowGrid(False)
        self.plugin_table.setAlternatingRowColors(False)
        self.plugin_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.plugin_table.setMinimumHeight(240)
        self.plugin_table.setMaximumHeight(330)
        header = self.plugin_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.plugin_table.setColumnWidth(2, 92)
        self.plugin_table.setColumnWidth(3, 72)
        self.plugin_table.setColumnWidth(4, 132)
        self.plugin_table.setColumnWidth(5, 132)
        layout.addWidget(self.plugin_table)

        self.plugin_empty_label = QLabel("No plugins imported yet. Use the button above to choose a local folder that contains plugin.json.")
        self.plugin_empty_label.setWordWrap(True)
        self.plugin_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.plugin_empty_label)

        self.plugin_add_btn.clicked.connect(self.on_import_plugin)
        return card

    def _build_skill_section(self):
        card = QFrame()
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        self.skill_section_title = QLabel("Skills")
        self.skill_section_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.skill_count_badge = QLabel("0")
        self.skill_count_badge.setObjectName("skillCountBadge")
        self.skill_count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.skill_count_badge.setFixedSize(24, 24)
        self.skill_add_btn = QPushButton("Import Skill")
        self.skill_add_btn.setObjectName("primaryBtn")

        header_row.addWidget(self.skill_section_title)
        header_row.addWidget(self.skill_count_badge)
        header_row.addStretch()
        header_row.addWidget(self.skill_add_btn)
        layout.addLayout(header_row)

        self.skill_desc_label = QLabel("Skills define reusable agent behavior. Imported Skills can be used in conversations when relevant.")
        self.skill_desc_label.setWordWrap(True)
        self.skill_desc_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(self.skill_desc_label)

        self.skill_table = QTableWidget(0, 5)
        self.skill_table.setHorizontalHeaderLabels(["Name", "Description", "Status", "Updated", "Actions"])
        self.skill_table.verticalHeader().setVisible(False)
        self.skill_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.skill_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.skill_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.skill_table.setShowGrid(False)
        self.skill_table.setAlternatingRowColors(False)
        self.skill_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.skill_table.setMinimumHeight(270)
        self.skill_table.setMaximumHeight(330)
        header = self.skill_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.skill_table.setColumnWidth(2, 86)
        self.skill_table.setColumnWidth(3, 138)
        self.skill_table.setColumnWidth(4, 96)
        layout.addWidget(self.skill_table)

        self.skill_empty_label = QLabel("No skills imported yet. Use the Extension Center or Settings to import a local Skill directory.")
        self.skill_empty_label.setWordWrap(True)
        self.skill_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.skill_empty_label)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        self.skill_expand_btn = QPushButton("Show All")
        self.skill_expand_btn.setObjectName("linkBtn")
        footer_row.addStretch()
        footer_row.addWidget(self.skill_expand_btn)
        footer_row.addStretch()
        layout.addLayout(footer_row)

        self.skill_add_btn.clicked.connect(self.on_import_skill)
        self.skill_expand_btn.clicked.connect(self.on_toggle_skill_expand)
        return card

    def _build_mcp_section(self):
        card, layout = self._create_section("MCP Configuration", "Configure MCP servers, enable or disable them, and set priority order.")

        self.mcp_table = QTableWidget(0, 5)
        self.mcp_table.setHorizontalHeaderLabels(["Order", "Name", "Summary", "Status", "Actions"])
        self.mcp_table.verticalHeader().setVisible(False)
        self.mcp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.mcp_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.mcp_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.mcp_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mcp_table.setShowGrid(False)
        self.mcp_table.setAlternatingRowColors(False)
        self.mcp_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.mcp_table.setMinimumHeight(220)
        self.mcp_table.setMaximumHeight(300)
        mcp_header = self.mcp_table.horizontalHeader()
        mcp_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        mcp_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        mcp_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        mcp_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        mcp_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.mcp_table.setColumnWidth(0, 68)
        self.mcp_table.setColumnWidth(3, 92)
        self.mcp_table.setColumnWidth(4, 92)
        self.mcp_table.cellClicked.connect(self.on_mcp_row_selected)
        layout.addWidget(self.mcp_table)

        self.mcp_empty_label = QLabel("No MCP configurations saved yet. Enter a name and JSON, then save.")
        self.mcp_empty_label.setWordWrap(True)
        self.mcp_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mcp_empty_label.setStyleSheet("font-size: 13px; padding: 8px 0;")
        layout.addWidget(self.mcp_empty_label)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.mcp_name_input = QLineEdit()
        self.mcp_name_input.setPlaceholderText("Example: local-tools")
        form.addRow("Config name", self.mcp_name_input)
        layout.addLayout(form)

        self.mcp_status_label = QLabel("")
        self.mcp_status_label.setWordWrap(True)
        self.mcp_status_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.mcp_status_label)

        self.mcp_config_input = QTextEdit()
        self.mcp_config_input.setMinimumHeight(180)
        self.mcp_config_input.setPlaceholderText(self._default_mcp_config_text())
        layout.addWidget(self.mcp_config_input)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 6, 0, 0)
        actions.setSpacing(10)
        self.mcp_new_btn = QPushButton("New Configuration")
        self.mcp_save_btn = QPushButton("Save Configuration")
        self.mcp_delete_btn = QPushButton("Delete Configuration")
        self.mcp_new_btn.setObjectName("secondaryBtn")
        self.mcp_save_btn.setObjectName("primaryBtn")
        self.mcp_delete_btn.setObjectName("dangerBtn")
        actions.addWidget(self.mcp_new_btn)
        actions.addWidget(self.mcp_save_btn)
        actions.addWidget(self.mcp_delete_btn)
        actions.addStretch()
        layout.addLayout(actions)

        self.mcp_new_btn.clicked.connect(self.on_new_mcp_config)
        self.mcp_save_btn.clicked.connect(self.on_save_mcp_config)
        self.mcp_delete_btn.clicked.connect(self.on_delete_mcp_config)
        return card

    def _normalize_mcp_settings(self, app_settings=None):
        source = app_settings if isinstance(app_settings, dict) else {}
        raw_configs = source.get("mcp_configs") if isinstance(source.get("mcp_configs"), dict) else {}
        configs = {}
        for name, config in raw_configs.items():
            normalized_name = str(name or "").strip()
            if not normalized_name or not isinstance(config, dict):
                continue
            normalized_config = dict(config)
            if "enabled" not in normalized_config:
                normalized_config["enabled"] = False
            else:
                normalized_config["enabled"] = bool(normalized_config.get("enabled"))
            configs[normalized_name] = normalized_config

        raw_order = source.get("mcp_config_order") if isinstance(source.get("mcp_config_order"), list) else []
        order = []
        seen = set()
        for item in raw_order:
            normalized_name = str(item or "").strip()
            if normalized_name in configs and normalized_name not in seen:
                order.append(normalized_name)
                seen.add(normalized_name)
        for name in configs:
            if name not in seen:
                order.append(name)
                seen.add(name)

        selected = str(source.get("mcp_selected_config") or "").strip()
        if selected not in configs:
            selected = order[0] if order else ""

        return {
            "selected": selected,
            "configs": configs,
            "order": order,
        }

    def set_mcp_settings(self, app_settings):
        self._mcp_settings = self._normalize_mcp_settings(app_settings)
        if hasattr(self, "mcp_table"):
            self._refresh_mcp_state()

    def set_skill_settings(self, app_settings):
        self._skill_settings = normalize_skill_settings(app_settings)
        if hasattr(self, "skill_table"):
            self._refresh_skill_state()

    def set_plugin_settings(self, app_settings):
        self._plugin_settings = normalize_plugin_settings(app_settings)
        if hasattr(self, "plugin_table"):
            self._refresh_plugin_state()

    def set_notification_settings(self, app_settings):
        self._notification_settings = normalize_notification_settings(
            app_settings.get("notifications") if isinstance(app_settings, dict) else app_settings
        )
        if hasattr(self, "notification_toggles"):
            for key, toggle in self.notification_toggles.items():
                toggle.setChecked(bool(self._notification_settings.get(key)), animate=False)

    def on_toggle_notification(self, key: str, enabled: bool):
        self._notification_settings = normalize_notification_settings(self._notification_settings)
        self._notification_settings[key] = bool(enabled)
        self.notification_settings_updated.emit(dict(self._notification_settings))

    def _visible_skill_items(self):
        items = list(self._skill_settings.get("items", []))
        if self._skill_show_all or len(items) <= 4:
            return items
        return items[:4]

    def _emit_plugin_settings(self):
        self.plugin_settings_updated.emit(build_plugin_payload(self._plugin_settings))

    def _create_plugin_toggle(self, plugin_item: dict):
        enabled = bool(plugin_item.get("enabled"))
        toggle = AnimatedSwitch(enabled, self.theme_mode)
        toggle.setToolTip("Enable or disable this Plugin")
        plugin_id = plugin_item.get("id", "")
        toggle.toggled.connect(lambda checked, pid=plugin_id: self.on_toggle_plugin_enabled(pid, checked))
        return toggle

    def _create_plugin_actions(self, plugin_item: dict):
        action_wrap = QWidget()
        action_layout = QHBoxLayout(action_wrap)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        reload_btn = SkillActionIconButton("edit", self.theme_mode)
        reload_btn.setToolTip("Reload this Plugin")
        delete_btn = SkillActionIconButton("delete", self.theme_mode)
        delete_btn.setToolTip("Delete this Plugin")

        plugin_id = plugin_item.get("id", "")
        reload_btn.clicked.connect(lambda pid=plugin_id: self.on_reload_plugin(pid))
        delete_btn.clicked.connect(lambda pid=plugin_id: self.on_delete_plugin(pid))

        action_layout.addWidget(reload_btn)
        action_layout.addWidget(delete_btn)
        action_layout.addStretch()
        return action_wrap

    def _refresh_plugin_state(self):
        if not hasattr(self, "plugin_table"):
            return

        items = list(self._plugin_settings.get("items", []))
        self.plugin_count_badge.setText(str(len(items)))
        self.plugin_table.setRowCount(len(items))
        text_color = Qt.GlobalColor.white if self.theme_mode == "dark" else Qt.GlobalColor.black

        for row, plugin_item in enumerate(items):
            tools = plugin_item.get("tools") if isinstance(plugin_item.get("tools"), list) else []
            status = plugin_item.get("status", "") or "discovered"
            if plugin_item.get("error"):
                status_item_text = f"{status}"
            else:
                status_item_text = status

            name_item = QTableWidgetItem(plugin_item.get("name", ""))
            desc_item = QTableWidgetItem(plugin_item.get("description", ""))
            status_item = QTableWidgetItem(status_item_text)
            tools_item = QTableWidgetItem(str(len(tools)))
            updated_item = QTableWidgetItem(plugin_item.get("updated_at", ""))
            for item in (name_item, desc_item, status_item, tools_item, updated_item):
                item.setForeground(text_color)
            name_item.setToolTip(plugin_item.get("source_dir", ""))
            desc_item.setToolTip(plugin_item.get("description", ""))
            status_item.setToolTip(plugin_item.get("error", ""))
            tools_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            updated_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.plugin_table.setItem(row, 0, name_item)
            self.plugin_table.setItem(row, 1, desc_item)
            self.plugin_table.setItem(row, 2, status_item)
            self.plugin_table.setItem(row, 3, tools_item)
            self.plugin_table.setItem(row, 4, updated_item)
            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(8)
            actions_layout.addWidget(self._create_plugin_toggle(plugin_item))
            actions_layout.addWidget(self._create_plugin_actions(plugin_item))
            self.plugin_table.setCellWidget(row, 5, actions)
            self.plugin_table.setRowHeight(row, 52)

        self.plugin_empty_label.setVisible(not items)
        self.plugin_table.setVisible(bool(items))

    def on_import_plugin(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Plugin Folder")
        if not directory:
            return
        try:
            plugin_item = import_plugin_directory(directory)
        except Exception as exc:
            QMessageBox.warning(self, "Import Plugin", str(exc))
            return
        self._plugin_settings = upsert_plugin_item(self._plugin_settings, plugin_item)
        self._refresh_plugin_state()
        self._emit_plugin_settings()
        QMessageBox.information(self, "Import Plugin", f"Imported Plugin: {plugin_item.get('name', '')}")

    def on_toggle_plugin_enabled(self, plugin_id: str, enabled: bool):
        status = "discovered" if enabled else "discovered"
        self._plugin_settings = update_plugin_item(self._plugin_settings, plugin_id, enabled=bool(enabled), status=status, error="")
        self._refresh_plugin_state()
        self._emit_plugin_settings()

    def on_reload_plugin(self, plugin_id: str):
        self._plugin_settings = update_plugin_item(self._plugin_settings, plugin_id, status="discovered", error="")
        self._refresh_plugin_state()
        self._emit_plugin_settings()

    def on_delete_plugin(self, plugin_id: str):
        target = next((item for item in self._plugin_settings.get("items", []) if item.get("id") == plugin_id), None)
        if not target:
            return
        answer = QMessageBox.question(
            self,
            "Delete Plugin",
            f"Delete plugin {target.get('name', '')}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._plugin_settings = remove_plugin_item(self._plugin_settings, plugin_id)
        self._refresh_plugin_state()
        self._emit_plugin_settings()

    def _emit_skill_settings(self):
        self.skill_settings_updated.emit(build_skill_payload(self._skill_settings))

    def _create_skill_toggle(self, skill_item: dict):
        enabled = bool(skill_item.get("enabled"))
        toggle = AnimatedSwitch(enabled, self.theme_mode)
        toggle.setToolTip("Enable or disable this Skill")
        skill_id = skill_item.get("id", "")
        toggle.toggled.connect(lambda checked, sid=skill_id: self.on_toggle_skill_enabled(sid, checked))
        return toggle

    def _create_skill_actions(self, skill_item: dict):
        action_wrap = QWidget()
        action_layout = QHBoxLayout(action_wrap)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        edit_btn = SkillActionIconButton("edit", self.theme_mode)
        edit_btn.setToolTip("Edit this Skill")
        delete_btn = SkillActionIconButton("delete", self.theme_mode)
        delete_btn.setToolTip("Delete this Skill")

        skill_id = skill_item.get("id", "")
        edit_btn.clicked.connect(lambda sid=skill_id: self.on_edit_skill(sid))
        delete_btn.clicked.connect(lambda sid=skill_id: self.on_delete_skill(sid))

        action_layout.addWidget(edit_btn)
        action_layout.addWidget(delete_btn)
        action_layout.addStretch()
        return action_wrap

    def _refresh_skill_state(self):
        if not hasattr(self, "skill_table"):
            return

        items = list(self._skill_settings.get("items", []))
        visible_items = self._visible_skill_items()
        self.skill_count_badge.setText(str(len(items)))
        self.skill_table.setRowCount(len(visible_items))

        for row, skill_item in enumerate(visible_items):
            name_item = QTableWidgetItem(skill_item.get("name", ""))
            name_item.setToolTip(skill_item.get("source_dir", ""))
            desc_item = QTableWidgetItem(skill_item.get("description", ""))
            desc_item.setToolTip(skill_item.get("source_dir", ""))
            updated_item = QTableWidgetItem(skill_item.get("updated_at", ""))
            updated_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name_item.setForeground(Qt.GlobalColor.white if self.theme_mode == "dark" else Qt.GlobalColor.black)
            desc_item.setForeground(Qt.GlobalColor.white if self.theme_mode == "dark" else Qt.GlobalColor.black)
            updated_item.setForeground(Qt.GlobalColor.white if self.theme_mode == "dark" else Qt.GlobalColor.black)
            name_item.setData(Qt.ItemDataRole.UserRole, skill_item.get("id", ""))
            name_item.setText(skill_item.get("name", ""))
            desc_item.setText(skill_item.get("description", ""))

            self.skill_table.setItem(row, 0, name_item)
            self.skill_table.setItem(row, 1, desc_item)
            self.skill_table.setCellWidget(row, 2, self._create_skill_toggle(skill_item))
            self.skill_table.setItem(row, 3, updated_item)
            self.skill_table.setCellWidget(row, 4, self._create_skill_actions(skill_item))
            self.skill_table.setRowHeight(row, 52)

        self.skill_empty_label.setVisible(not items)
        self.skill_table.setVisible(bool(items))

        has_more = len(items) > 4
        self.skill_expand_btn.setVisible(has_more)
        self.skill_expand_btn.setText("Show Less" if self._skill_show_all and has_more else "Show All")

    def on_toggle_skill_expand(self):
        self._skill_show_all = not self._skill_show_all
        self._refresh_skill_state()

    def on_import_skill(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Skill Folder")
        if not directory:
            return

        try:
            skill_item = import_skill_directory(directory)
        except Exception as exc:
            QMessageBox.warning(self, "Import Skill", str(exc))
            return

        self._skill_settings = upsert_skill_item(self._skill_settings, skill_item)
        self._refresh_skill_state()
        self._emit_skill_settings()
        QMessageBox.information(self, "Import Skill", f"Imported Skill: {skill_item.get('name', '')}")

    def on_toggle_skill_enabled(self, skill_id: str, enabled: bool):
        self._skill_settings = update_skill_item(self._skill_settings, skill_id, enabled=bool(enabled))
        self._refresh_skill_state()
        self._emit_skill_settings()

    def on_edit_skill(self, skill_id: str):
        target = next((item for item in self._skill_settings.get("items", []) if item.get("id") == skill_id), None)
        if not target:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Skill")
        dialog.resize(520, 320)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(18, 18, 18, 18)
        dialog_layout.setSpacing(12)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        name_input = QLineEdit(target.get("name", ""))
        desc_input = QTextEdit()
        desc_input.setMinimumHeight(120)
        desc_input.setPlainText(target.get("description", ""))
        form.addRow("Name", name_input)
        form.addRow("Description", desc_input)
        dialog_layout.addLayout(form)

        source_label = QLabel(target.get("source_dir", ""))
        source_label.setWordWrap(True)
        source_label.setStyleSheet("font-size: 12px;")
        dialog_layout.addWidget(source_label)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel_btn = QPushButton("Cancel")
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryBtn")
        actions.addWidget(cancel_btn)
        actions.addWidget(save_btn)
        dialog_layout.addLayout(actions)

        cancel_btn.clicked.connect(dialog.reject)
        save_btn.clicked.connect(dialog.accept)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        name = name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Edit Skill", "Select a Skill first.")
            return

        description = desc_input.toPlainText().strip()
        self._skill_settings = update_skill_item(self._skill_settings, skill_id, name=name, description=description)
        self._refresh_skill_state()
        self._emit_skill_settings()

    def on_delete_skill(self, skill_id: str):
        target = next((item for item in self._skill_settings.get("items", []) if item.get("id") == skill_id), None)
        if not target:
            return

        answer = QMessageBox.question(
            self,
            "Delete Skill",
            f"Delete Skill {target.get('name', '')}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._skill_settings = remove_skill_item(self._skill_settings, skill_id)
        self._refresh_skill_state()
        self._emit_skill_settings()

    # ------------------------------------------------------------------
    # Pets (Buddy) section
    # ------------------------------------------------------------------

    def _build_pets_section(self):
        card = QFrame()
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.pet_office = PetOfficeWidget(card, theme_mode=getattr(self, "theme_mode", "light"))
        self.pet_office.pet_clicked.connect(
            lambda pid: self.pet_training_room_requested.emit(pid or "")
        )
        self.pet_office.pet_add_requested.connect(self._on_add_pet)
        self.pet_office.pet_delete_requested.connect(self._on_delete_pet)
        self.pet_office.pet_dispatch_requested.connect(
            lambda pid: self.pet_dispatch_requested.emit(pid or "")
        )
        self.pet_office.desk_layout_changed.connect(self._on_desk_layout_changed)
        self.pet_office.pet_enable_toggled.connect(self._on_toggle_pet_enabled)
        self.pet_office.floating_toggle_requested.connect(self._on_pet_floating_toggled)
        self.pet_office.floating_pet_changed.connect(self._on_pet_floating_pet_changed)
        self.pet_office.chat_clicked.connect(
            lambda cid: self.pet_chat_clicked.emit(cid or "")
        )
        self.pet_office.skill_map_requested.connect(self.pet_skill_map_requested.emit)
        layout.addWidget(self.pet_office)
        return card

    def set_pet_office_chats_provider(self, provider):
        if hasattr(self, "pet_office"):
            self.pet_office.set_chats_provider(provider)

    def set_pet_office_capabilities_provider(self, provider):
        if hasattr(self, "pet_office"):
            self.pet_office.set_capabilities_provider(provider)

    def set_pet_settings(self, app_settings):
        self._pet_settings = normalize_pet_settings(app_settings)
        if hasattr(self, "pet_office"):
            self._refresh_pet_state()

    def _refresh_pet_state(self):
        if not hasattr(self, "pet_office"):
            return
        self.pet_office.set_pet_settings(self._pet_settings)
        self.pet_office.refresh_chats()

    def _on_pet_floating_toggled(self, checked: bool):
        self._pet_settings = dict(self._pet_settings)
        self._pet_settings["floating_enabled"] = bool(checked)
        self._emit_pet_settings()

    def _on_pet_floating_pet_changed(self, pet_id: str):
        if not pet_id:
            return
        self._pet_settings = set_floating_pet(self._pet_settings, pet_id)
        self._refresh_pet_state()
        self._emit_pet_settings()

    def _on_add_pet(self, kind: str):
        import uuid as _uuid
        kind = PET_KIND_SUB
        new_id = _uuid.uuid4().hex
        new_pet = {
            "id": new_id,
            "kind": kind,
            "name": "New Buddy",
            "enabled": True,
            "stats": {},
            "activity_log": [],
        }
        self._pet_settings = upsert_pet_item(self._pet_settings, new_pet)
        target = next(
            (item for item in self._pet_settings.get("items", []) if item.get("id") == new_id),
            None,
        )
        self._refresh_pet_state()
        self._emit_pet_settings()
        if target is not None:
            self.pet_training_room_requested.emit(target.get("id", ""))

    def _on_delete_pet(self, pet_id: str):
        if not pet_id:
            return
        target = next((item for item in self._pet_settings.get("items", []) if item.get("id") == pet_id), None)
        name = target.get("name") if target else "Buddy"
        if is_fixed_default_pet(pet_id):
            QMessageBox.information(
                self,
                "Delete Buddy",
                f"{name} is a built-in AudioMate buddy and cannot be deleted.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Delete Buddy",
            f"Delete buddy {name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._pet_settings = remove_pet_item(self._pet_settings, pet_id)
        self._refresh_pet_state()
        self._emit_pet_settings()

    def _on_desk_layout_changed(self, layout: list):
        self._pet_settings = set_desk_layout(self._pet_settings, list(layout or []))
        self._refresh_pet_state()
        self._emit_pet_settings()

    def _on_toggle_pet_enabled(self, pet_id: str, enabled: bool):
        if not pet_id:
            return
        target = next((dict(item) for item in self._pet_settings.get("items", []) if item.get("id") == pet_id), None)
        if target is None:
            return
        target["enabled"] = bool(enabled)
        self._pet_settings = upsert_pet_item(self._pet_settings, target)
        self._refresh_pet_state()
        self._emit_pet_settings()

    def apply_pet_item(self, pet_item: dict):
        """External entry point used after the training-room dialog saves."""
        if not isinstance(pet_item, dict):
            return
        self._pet_settings = upsert_pet_item(self._pet_settings, pet_item)
        self._refresh_pet_state()
        self._emit_pet_settings()

    def _emit_pet_settings(self):
        self.pet_settings_updated.emit(build_pet_payload(self._pet_settings))

    def _default_mcp_config_text(self):
        return json.dumps(
            {
                "transport": "streamable_http",
                "url": "http://127.0.0.1:8000/mcp",
                "headers": {},
            },
            ensure_ascii=False,
            indent=2,
        )

    def _mcp_payload(self):
        return {
            "selected": self._mcp_settings.get("selected", ""),
            "configs": self._mcp_settings.get("configs", {}),
            "order": self._mcp_settings.get("order", []),
        }

    def _mcp_config_summary(self, config: dict) -> str:
        prepared = dict(config or {})
        if prepared.get("mcpServers") and isinstance(prepared["mcpServers"], dict):
            first_key = next(iter(prepared["mcpServers"]), "")
            if first_key:
                prepared = dict(prepared["mcpServers"][first_key])
        transport = str(prepared.get("transport") or prepared.get("type") or ("stdio" if prepared.get("command") else "")).strip()
        if prepared.get("url"):
            return f"{transport or 'http'} - {prepared.get('url')}"
        if prepared.get("command"):
            args = prepared.get("args") if isinstance(prepared.get("args"), list) else []
            command = " ".join([str(prepared.get("command")), *[str(item) for item in args]]).strip()
            return f"{transport or 'stdio'} - {command}"
        return transport or "Unknown transport"

    def _enabled_mcp_names(self):
        configs = self._mcp_settings.get("configs", {})
        return [name for name in self._mcp_settings.get("order", []) if bool(configs.get(name, {}).get("enabled"))]

    def _create_mcp_toggle(self, name: str, config: dict):
        wrap = QWidget()
        wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        wrap.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()
        toggle = AnimatedSwitch(bool(config.get("enabled")), self.theme_mode)
        toggle.setToolTip("Enable or disable this MCP configuration")
        toggle.toggled.connect(lambda checked, cfg_name=name: self.on_toggle_mcp_config_enabled(cfg_name, checked))
        layout.addWidget(toggle, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        return wrap

    def _create_mcp_order_actions(self, name: str):
        action_wrap = QWidget()
        action_wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        action_wrap.setStyleSheet("background: transparent;")
        action_layout = QHBoxLayout(action_wrap)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(4)

        up_btn = MCPOrderIconButton("up", self.theme_mode)
        down_btn = MCPOrderIconButton("down", self.theme_mode)
        up_btn.setToolTip("Raise this MCP configuration priority")
        down_btn.setToolTip("Lower this MCP configuration priority")
        up_btn.clicked.connect(lambda cfg_name=name: self.on_move_mcp_config(cfg_name, -1))
        down_btn.clicked.connect(lambda cfg_name=name: self.on_move_mcp_config(cfg_name, 1))

        action_layout.addStretch()
        action_layout.addWidget(up_btn)
        action_layout.addWidget(down_btn)
        action_layout.addStretch()
        return action_wrap

    def _refresh_mcp_state(self):
        configs = self._mcp_settings.get("configs", {})
        order = [name for name in self._mcp_settings.get("order", []) if name in configs]
        for name in configs:
            if name not in order:
                order.append(name)
        self._mcp_settings["order"] = order

        self.mcp_table.blockSignals(True)
        self.mcp_table.setRowCount(len(order))
        text_color = Qt.GlobalColor.white if self.theme_mode == "dark" else Qt.GlobalColor.black
        for row, name in enumerate(order):
            config = configs.get(name, {})
            order_item = QTableWidgetItem(str(row + 1))
            name_item = QTableWidgetItem(name)
            summary_item = QTableWidgetItem(self._mcp_config_summary(config))
            order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            order_item.setForeground(text_color)
            name_item.setForeground(text_color)
            summary_item.setForeground(text_color)
            name_item.setData(Qt.ItemDataRole.UserRole, name)
            summary_item.setToolTip(self._mcp_config_summary(config))

            self.mcp_table.setItem(row, 0, order_item)
            self.mcp_table.setItem(row, 1, name_item)
            self.mcp_table.setItem(row, 2, summary_item)
            self.mcp_table.setCellWidget(row, 3, self._create_mcp_toggle(name, config))
            self.mcp_table.setCellWidget(row, 4, self._create_mcp_order_actions(name))
            self.mcp_table.setRowHeight(row, 52)

        self.mcp_table.blockSignals(False)
        self.mcp_empty_label.setVisible(not order)
        self.mcp_table.setVisible(bool(order))

        selected = self._mcp_settings.get("selected", "")
        if selected not in configs:
            selected = order[0] if order else ""
            self._mcp_settings["selected"] = selected

        if selected:
            selected_row = order.index(selected) if selected in order else -1
            if selected_row >= 0:
                self.mcp_table.selectRow(selected_row)
            config = configs.get(selected) or {}
        else:
            config = {}

        self.mcp_name_input.setText(selected)
        if config:
            self.mcp_config_input.setPlainText(json.dumps(config, ensure_ascii=False, indent=2))
        else:
            self.mcp_config_input.setPlainText(self._default_mcp_config_text())

        enabled_names = self._enabled_mcp_names()
        if enabled_names:
            self.mcp_status_label.setText("Enabled MCP configurations: " + ", ".join(enabled_names))
        else:
            self.mcp_status_label.setText("No MCP configuration selected")

    def on_mcp_row_selected(self, row, _column):
        item = self.mcp_table.item(row, 1)
        selected = str(item.data(Qt.ItemDataRole.UserRole) if item else "").strip()
        if not selected:
            return
        self._mcp_settings["selected"] = selected
        config = self._mcp_settings.get("configs", {}).get(selected) or {}
        self.mcp_name_input.setText(selected)
        self.mcp_config_input.setPlainText(json.dumps(config, ensure_ascii=False, indent=2))

    def on_new_mcp_config(self):
        self._mcp_settings["selected"] = ""
        self.mcp_table.clearSelection()
        self.mcp_name_input.clear()
        self.mcp_config_input.setPlainText(self._default_mcp_config_text())
        self.mcp_status_label.setText("Ready to save MCP configuration")

    def on_toggle_mcp_config_enabled(self, name: str, enabled: bool):
        configs = self._mcp_settings.setdefault("configs", {})
        if name not in configs:
            return
        configs[name]["enabled"] = bool(enabled)
        self._refresh_mcp_state()
        self.mcp_settings_updated.emit(self._mcp_payload())

    def on_move_mcp_config(self, name: str, direction: int):
        order = [item for item in self._mcp_settings.get("order", []) if item in self._mcp_settings.get("configs", {})]
        if name not in order:
            return
        old_index = order.index(name)
        new_index = old_index + int(direction)
        if new_index < 0 or new_index >= len(order):
            return
        order[old_index], order[new_index] = order[new_index], order[old_index]
        self._mcp_settings["order"] = order
        self._mcp_settings["selected"] = name
        self._refresh_mcp_state()
        self.mcp_settings_updated.emit(self._mcp_payload())

    def on_save_mcp_config(self):
        name = self.mcp_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "MCP Configuration", "Enter a configuration name first.")
            return

        raw_text = self.mcp_config_input.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "MCP Configuration", "Enter MCP configuration JSON first.")
            return

        try:
            config = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "MCP Configuration", f"JSON parse failed: {exc}")
            return

        if not isinstance(config, dict):
            QMessageBox.warning(self, "MCP Configuration", "The MCP JSON root must be an object.")
            return

        previous_name = self._mcp_settings.get("selected", "")
        if "enabled" not in config:
            config["enabled"] = True
        else:
            config["enabled"] = bool(config.get("enabled"))

        configs = self._mcp_settings.setdefault("configs", {})
        order = [item for item in self._mcp_settings.get("order", []) if item in configs]
        if previous_name and previous_name != name and previous_name in configs:
            old_index = order.index(previous_name) if previous_name in order else len(order)
            del configs[previous_name]
            order = [item for item in order if item != previous_name]
            order.insert(min(old_index, len(order)), name)
        elif name not in order:
            order.append(name)

        configs[name] = config
        self._mcp_settings["order"] = order
        self._mcp_settings["selected"] = name
        self._refresh_mcp_state()
        self.mcp_settings_updated.emit(self._mcp_payload())
        QMessageBox.information(self, "MCP Configuration", f"Saved MCP configuration: {name}")

    def on_delete_mcp_config(self):
        name = str(self._mcp_settings.get("selected") or self.mcp_name_input.text() or "").strip()
        configs = self._mcp_settings.setdefault("configs", {})
        if not name or name not in configs:
            QMessageBox.warning(self, "MCP Configuration", "Select an MCP configuration first.")
            return

        del configs[name]
        self._mcp_settings["order"] = [item for item in self._mcp_settings.get("order", []) if item != name and item in configs]
        if self._mcp_settings.get("selected") == name:
            self._mcp_settings["selected"] = self._mcp_settings["order"][0] if self._mcp_settings["order"] else ""
        self._refresh_mcp_state()
        self.mcp_settings_updated.emit(self._mcp_payload())
        QMessageBox.information(self, "MCP Configuration", f"Deleted MCP configuration: {name}")

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        if self.theme_mode == "dark":
            self.setStyleSheet(
                "QWidget { background-color: #1B1E24; color: #E6E6E6; }"
                "QScrollArea { background: #1B1E24; border: none; }"
                "QListWidget#settingsSidebar { background: transparent; border: none; outline: none; padding: 4px; }"
                "QListWidget#settingsSidebar::item { color: #AEB7C8; border: none; border-radius: 12px; padding: 11px 14px; margin: 3px 0px; }"
                "QListWidget#settingsSidebar::item:selected { background: #293157; color: #FFFFFF; font-weight: 600; }"
                "QListWidget#settingsSidebar::item:hover { background: #242A35; color: #F1F4FF; }"
                "QFrame#settingsCard { background-color: #20242B; border: 1px solid #323843; border-radius: 20px; }"
                "QFrame#settingsCard QLabel { background: transparent; }"
                "QPushButton { background: #2C313B; border: 1px solid #353C47; border-radius: 14px; padding: 9px 14px; color: #E6E6E6; }"
                "QPushButton:hover { background: #353B47; }"
                "QPushButton#signinBtn, QPushButton#primaryBtn { background: #4F63F6; border-color: #4F63F6; color: #FFFFFF; }"
                "QPushButton#signinBtn:hover, QPushButton#primaryBtn:hover { background: #6073FF; }"
                "QPushButton#accountBtn { background: #ECECEC; color: #111827; border-color: #ECECEC; }"
                "QPushButton#logoutBtn, QPushButton#dangerBtn { background: #3A2427; border-color: #3A2427; color: #FFC0C0; }"
                "QPushButton#logoutBtn:hover, QPushButton#dangerBtn:hover { background: #4A2B31; }"
                "QPushButton:disabled { background: #252A33; border-color: #323843; color: #737D90; }"
                "QPushButton#secondaryBtn { background: #262C35; }"
                "QPushButton#secondaryBtn:hover { background: #2E3540; }"
                "QPushButton#linkBtn { background: transparent; border: none; color: #9AA4FF; padding: 0; }"
                "QPushButton#linkBtn:hover { background: transparent; color: #C2C9FF; }"
                "QLabel { color: #D0D3D8; background: transparent; }"
                "QLineEdit, QTextEdit, QComboBox { background: #171A20; border: 1px solid #313743; border-radius: 14px; padding: 10px 12px; color: #E6E6E6; }"
                "QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #4F63F6; }"
                "QComboBox QAbstractItemView { background: #20242B; color: #E6E6E6; border: 1px solid #323843; border-radius: 12px; padding: 6px; }"
                "QMenu { background-color: #23262B; color: #E6E6E6; border: 1px solid #4A4F57; border-radius: 8px; padding: 4px 0px; }"
                "QMenu::item { padding: 6px 24px; border-radius: 4px; margin: 2px 4px; color: #E6E6E6; background-color: #23262B; }"
                "QMenu::item:selected { background-color: #2F4E7A; color: #DCEBFF; }"
                f"{back_button_style('dark')}"
            )
            if hasattr(self, "skill_count_badge"):
                self.skill_count_badge.setStyleSheet("background: #2B313A; color: #A8B3D8; border-radius: 12px; font-size: 12px; font-weight: 700;")
                self.skill_table.setStyleSheet(self._settings_table_style(header_padding="12px 10px"))
                self.skill_empty_label.setStyleSheet("font-size: 13px; color: #8F98AB; padding: 10px 0 2px 0;")
            if hasattr(self, "plugin_count_badge"):
                self.plugin_count_badge.setStyleSheet("background: #2B313A; color: #A8B3D8; border-radius: 12px; font-size: 12px; font-weight: 700;")
                self.plugin_table.setStyleSheet(self._settings_table_style(header_padding="12px 10px"))
                self.plugin_empty_label.setStyleSheet("font-size: 13px; color: #8F98AB; padding: 10px 0 2px 0;")
            if hasattr(self, "mcp_table"):
                self.mcp_table.setStyleSheet(self._settings_table_style(header_padding="12px 10px"))
                self.mcp_empty_label.setStyleSheet("font-size: 13px; color: #8F98AB; padding: 8px 0;")
            if hasattr(self, "notification_toggles"):
                for toggle in self.notification_toggles.values():
                    toggle.setThemeMode(self.theme_mode)
            if hasattr(self, "memory_toggles"):
                for toggle in self.memory_toggles.values():
                    toggle.setThemeMode(self.theme_mode)
            if hasattr(self, "memory_tables"):
                for table in self.memory_tables.values():
                    table.setStyleSheet(self._settings_table_style(header_padding="10px 8px"))
                for label in self.memory_empty_labels.values():
                    label.setStyleSheet("font-size: 12px; color: #8F98AB; padding: 6px 0;")
        else:
            self.setStyleSheet(
                "QWidget { background-color: #FCFCFE; color: #1F1F1F; }"
                "QScrollArea { background: #FCFCFE; border: none; }"
                "QListWidget#settingsSidebar { background: transparent; border: none; outline: none; padding: 4px; }"
                "QListWidget#settingsSidebar::item { color: #44516A; border: none; border-radius: 12px; padding: 11px 14px; margin: 3px 0px; }"
                "QListWidget#settingsSidebar::item:selected { background: #EEF0FF; color: #4C63F6; font-weight: 600; }"
                "QListWidget#settingsSidebar::item:hover { background: #F3F5FA; color: #24324A; }"
                "QFrame#settingsCard { background-color: #FFFFFF; border: 1px solid #E7EBF4; border-radius: 20px; }"
                "QFrame#settingsCard QLabel { background: transparent; }"
                "QPushButton { background: #F3F5FA; border: 1px solid #E5EAF5; border-radius: 14px; padding: 9px 14px; color: #24324A; }"
                "QPushButton:hover { background: #EDF1F8; }"
                "QPushButton#signinBtn, QPushButton#primaryBtn { background: #4C63F6; border-color: #4C63F6; color: #FFFFFF; }"
                "QPushButton#signinBtn:hover, QPushButton#primaryBtn:hover { background: #5B71FF; }"
                "QPushButton#accountBtn { background: #ECECEC; color: #111827; border-color: #ECECEC; }"
                "QPushButton#logoutBtn, QPushButton#dangerBtn { background: #FFF2F2; border-color: #FFDCDD; color: #C54A4A; }"
                "QPushButton#logoutBtn:hover, QPushButton#dangerBtn:hover { background: #FFE7E7; }"
                "QPushButton:disabled { background: #F2F5FA; border-color: #E4E9F3; color: #98A2B3; }"
                "QPushButton#secondaryBtn { background: #FFFFFF; }"
                "QPushButton#secondaryBtn:hover { background: #F7F9FC; }"
                "QPushButton#linkBtn { background: transparent; border: none; color: #6C63F4; padding: 0; }"
                "QPushButton#linkBtn:hover { background: transparent; color: #7F77FF; }"
                "QLabel { color: #374151; background: transparent; }"
                "QLineEdit, QTextEdit, QComboBox { background: #FFFFFF; border: 1px solid #E5EAF5; border-radius: 14px; padding: 10px 12px; color: #24324A; }"
                "QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #4C63F6; }"
                "QComboBox QAbstractItemView { background: #FFFFFF; color: #24324A; border: 1px solid #E7EBF4; border-radius: 12px; padding: 6px; }"
                "QMenu { background-color: #FFFFFF; color: #1F1F1F; border: 1px solid #DADCE0; border-radius: 8px; padding: 4px 0px; }"
                "QMenu::item { padding: 6px 24px; border-radius: 4px; margin: 2px 4px; color: #1F1F1F; background-color: #FFFFFF; }"
                "QMenu::item:selected { background-color: #E8F0FE; color: #1967D2; }"
                f"{back_button_style('light')}"
            )
            if hasattr(self, "skill_count_badge"):
                self.skill_count_badge.setStyleSheet("background: #EEF0FF; color: #6A63F2; border-radius: 12px; font-size: 12px; font-weight: 700;")
                self.skill_table.setStyleSheet(self._settings_table_style(header_padding="12px 10px"))
                self.skill_empty_label.setStyleSheet("font-size: 13px; color: #8A94A8; padding: 10px 0 2px 0;")
            if hasattr(self, "plugin_count_badge"):
                self.plugin_count_badge.setStyleSheet("background: #EEF0FF; color: #6A63F2; border-radius: 12px; font-size: 12px; font-weight: 700;")
                self.plugin_table.setStyleSheet(self._settings_table_style(header_padding="12px 10px"))
                self.plugin_empty_label.setStyleSheet("font-size: 13px; color: #8A94A8; padding: 10px 0 2px 0;")
            if hasattr(self, "mcp_table"):
                self.mcp_table.setStyleSheet(self._settings_table_style(header_padding="12px 10px"))
                self.mcp_empty_label.setStyleSheet("font-size: 13px; color: #8A94A8; padding: 8px 0;")
            if hasattr(self, "notification_toggles"):
                for toggle in self.notification_toggles.values():
                    toggle.setThemeMode(self.theme_mode)
            if hasattr(self, "memory_toggles"):
                for toggle in self.memory_toggles.values():
                    toggle.setThemeMode(self.theme_mode)
            if hasattr(self, "memory_tables"):
                for table in self.memory_tables.values():
                    table.setStyleSheet(self._settings_table_style(header_padding="10px 8px"))
                for label in self.memory_empty_labels.values():
                    label.setStyleSheet("font-size: 12px; color: #8A94A8; padding: 6px 0;")

        if hasattr(self, "pet_office"):
            self.pet_office.apply_theme(self.theme_mode)

        if hasattr(self, "skill_table"):
            self._refresh_skill_state()
        if hasattr(self, "plugin_table"):
            self._refresh_plugin_state()
        if hasattr(self, "mcp_table"):
            self._refresh_mcp_state()
        if hasattr(self, "memory_tables"):
            self._refresh_memory_state()

    def _refresh_login_state(self):
        if hasattr(self, "api_key_input"):
            self.api_key_input.setEnabled(True)
        if hasattr(self, "save_key_btn"):
            self.save_key_btn.setEnabled(True)

    def _refresh_api_key_state(self):
        if hasattr(self.auth_session, "get_base_url"):
            base_url = normalize_openai_base_url((self.auth_session.get_base_url() or "").strip())
            self.base_url_input.setText(base_url or DEFAULT_REMOTE_BASE_URL)
        if hasattr(self.auth_session, "get_api_key"):
            self.api_key_input.setText((self.auth_session.get_api_key() or "").strip())

    def on_save_key(self):
        api_key = self.api_key_input.text().strip()
        base_url = normalize_openai_base_url(self.base_url_input.text().strip()) or DEFAULT_REMOTE_BASE_URL
        backend = "keyring"
        try:
            if hasattr(self.auth_session, "set_api_key"):
                backend = self.auth_session.set_api_key(api_key) or backend
            if hasattr(self.auth_session, "set_base_url"):
                self.auth_session.set_base_url(base_url)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Model Provider",
                f"Failed to save credentials. Nothing was written.\n{exc}\n\nCheck disk permissions and try again.",
            )
            return
        self.base_url_input.setText(base_url)
        self.api_key_updated.emit(api_key, base_url)
        if backend == "plaintext":
            QMessageBox.warning(
                self,
                "Model Provider",
                "API Key and Base URL were saved and synchronized.\n\n"
                "Warning: OS keyring is unavailable, so credentials were saved in plaintext at "
                "~/.audiomate_secrets.json (restricted to the current user where supported).\n"
                "Do not expose this file on shared machines.",
            )
        else:
            QMessageBox.information(self, "Model Provider", "API Key and Base URL saved and synchronized")

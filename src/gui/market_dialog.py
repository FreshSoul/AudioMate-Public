from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.common import back_button_style, configure_back_button


class MarketDialog(QWidget):
    """Local extension center for skills and plugins."""

    back_requested = pyqtSignal()
    import_plugin_requested = pyqtSignal()
    import_bundled_plugin_requested = pyqtSignal(str)
    reaper_setup_requested = pyqtSignal()
    import_skill_requested = pyqtSignal()
    refresh_catalog_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_mode = "light"
        self._plugins = []
        self._skills = []
        self._item_widgets = []
        self._active_tab = "plugin"
        self._status_message = ""
        self._status_kind = "idle"
        self._last_column_count = 0
        self._last_body_margin = 0
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("headerBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 12, 24, 12)
        self.back_btn = QPushButton("<")
        configure_back_button(self.back_btn)
        self.back_btn.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(self.back_btn)
        header_layout.addStretch()
        root.addWidget(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.scroll_area)

        body = QWidget()
        body.setMinimumWidth(0)
        self.scroll_area.setWidget(body)
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(78, 8, 78, 48)
        self.body_layout.setSpacing(16)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(8)
        self.plugin_tab_btn = QPushButton("Plugins")
        self.plugin_tab_btn.setObjectName("marketTab")
        self.plugin_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.plugin_tab_btn.clicked.connect(lambda: self._set_active_tab("plugin"))
        self.skill_tab_btn = QPushButton("Skills")
        self.skill_tab_btn.setObjectName("marketTab")
        self.skill_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skill_tab_btn.clicked.connect(lambda: self._set_active_tab("skill"))
        tab_row.addStretch(1)
        tab_row.addWidget(self.plugin_tab_btn)
        tab_row.addWidget(self.skill_tab_btn)
        tab_row.addStretch(1)
        self.body_layout.addLayout(tab_row)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search plugins")
        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(200)
        self._search_debounce_timer.timeout.connect(self._rebuild_items)
        self.search_input.textChanged.connect(lambda _text: self._search_debounce_timer.start())
        search_row.addWidget(self.search_input, 1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("marketRefreshBtn")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_catalog_requested.emit)
        search_row.addWidget(self.refresh_btn)
        self.body_layout.addLayout(search_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("marketStatus")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        self.body_layout.addWidget(self.status_label)

        self.list_layout = QVBoxLayout()
        self.list_layout.setContentsMargins(0, 6, 0, 0)
        self.list_layout.setSpacing(14)
        self.body_layout.addLayout(self.list_layout)
        self.body_layout.addStretch(1)
        self._sync_responsive_layout(rebuild=False)
        self._sync_tab_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_responsive_layout(rebuild=True)

    def refresh(self):
        self._rebuild_items()

    def set_catalog(self, _hub_url: str = "", skills=None, plugins=None, **_ignored):
        self._skills = list(skills or [])
        self._plugins = list(plugins or [])
        self._rebuild_items()

    def set_loading(self, message: str = "Loading extensions..."):
        self.set_status(message, "info")

    def set_status(self, message: str = "", kind: str = "info"):
        self._status_kind = kind if kind in {"idle", "info", "warning", "error"} else "info"
        self._status_message = str(message or "")
        self._sync_status_label()

    def _sync_status_label(self):
        text = self._status_message
        self.status_label.setText(text)
        self.status_label.setProperty("kind", self._status_kind)
        self.status_label.setVisible(bool(text))
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _set_active_tab(self, tab: str):
        self._active_tab = "skill" if tab == "skill" else "plugin"
        self.search_input.setPlaceholderText("Search skills" if self._active_tab == "skill" else "Search plugins")
        self._sync_tab_buttons()
        self._rebuild_items()

    def _sync_tab_buttons(self):
        for button, tab in ((self.plugin_tab_btn, "plugin"), (self.skill_tab_btn, "skill")):
            button.setProperty("active", tab == self._active_tab)
            button.style().unpolish(button)
            button.style().polish(button)

    def _visible_items(self):
        needle = self.search_input.text().strip().casefold()
        source_items = self._skills if self._active_tab == "skill" else self._plugins
        items = []
        for item in source_items:
            haystack = " ".join(str(item.get(key, "")) for key in ("title", "description", "category", "kind")).casefold()
            if not needle or needle in haystack:
                items.append(item)
        return items

    def _column_count(self) -> int:
        width = self.scroll_area.viewport().width()
        return 1 if width < 900 else 2

    def _body_margin(self) -> int:
        width = self.scroll_area.viewport().width()
        if width < 720:
            return 18
        if width < 900:
            return 32
        return 78

    def _sync_responsive_layout(self, rebuild: bool):
        columns = self._column_count()
        margin = self._body_margin()
        changed = columns != self._last_column_count or margin != self._last_body_margin
        self.body_layout.setContentsMargins(margin, 8, margin, 48)
        self._last_column_count = columns
        self._last_body_margin = margin
        if changed and rebuild:
            self._rebuild_items()

    def _rebuild_items(self):
        self._clear_layout(self.list_layout)
        self._item_widgets = []
        items = self._visible_items()
        if not items:
            label = "No matching skills" if self._active_tab == "skill" else "No matching plugins"
            self._add_empty_state(label)
            return

        columns = self._column_count()
        grid = QWidget()
        grid.setMinimumWidth(0)
        grid.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        grid_layout = QGridLayout(grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(16)
        grid_layout.setVerticalSpacing(8)
        for column in range(columns):
            grid_layout.setColumnStretch(column, 1)
        for index, item in enumerate(items):
            card = self._create_item_card(item)
            grid_layout.addWidget(card, index // columns, index % columns)
            self._item_widgets.append((card, item))
        self.list_layout.addWidget(grid)

    def _add_empty_state(self, text: str):
        label = QLabel(text)
        label.setObjectName("marketEmpty")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumHeight(180)
        self.list_layout.addWidget(label)

    def _create_item_card(self, item: dict):
        card = QFrame()
        card.setObjectName("marketItem")
        card.setMinimumHeight(64)
        card.setMinimumWidth(0)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(12)

        icon = QLabel(self._icon_for(item.get("kind")))
        icon.setObjectName("itemIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(34, 34)
        layout.addWidget(icon)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(2)
        title = QLabel(item.get("title", ""))
        title.setObjectName("itemTitle")
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        desc = QLabel(item.get("description", ""))
        desc.setObjectName("itemDesc")
        desc.setMinimumWidth(0)
        desc.setWordWrap(True)
        desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        category = QLabel(item.get("category", ""))
        category.setObjectName("itemMeta")
        category.setMinimumWidth(0)
        category.setWordWrap(True)
        category.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text_wrap.addWidget(title)
        text_wrap.addWidget(desc)
        if item.get("category"):
            text_wrap.addWidget(category)
        layout.addLayout(text_wrap, 1)

        button = QPushButton("+")
        button.setObjectName("itemAddBtn")
        button.setFixedSize(30, 30)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, market_item=item: self._handle_add(market_item))
        layout.addWidget(button)
        if self._is_reaper_control_item(item):
            setup_btn = QPushButton("Setup")
            setup_btn.setObjectName("itemSetupBtn")
            setup_btn.setFixedSize(56, 30)
            setup_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            setup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            setup_btn.setToolTip("Configure REAPER Python and the reapy bridge")
            setup_btn.clicked.connect(lambda _checked=False: self.reaper_setup_requested.emit())
            layout.addWidget(setup_btn)
        return card

    def _is_reaper_control_item(self, item: dict) -> bool:
        plugin_id = str(item.get("id") or item.get("plugin_id") or "").casefold()
        title = str(item.get("title") or "").casefold()
        path = str(item.get("path") or "").casefold()
        return plugin_id == "reaper-control" or "reaper control" in title or "reaper-control" in path

    def _handle_add(self, item: dict):
        kind = item.get("kind")
        if kind == "plugin":
            self.import_plugin_requested.emit()
        elif kind == "bundled_plugin":
            self.import_bundled_plugin_requested.emit(str(item.get("path") or ""))
        elif kind == "skill":
            self.import_skill_requested.emit()

    def _icon_for(self, kind: str) -> str:
        if kind == "plugin":
            return "P"
        if kind == "bundled_plugin":
            return "B"
        return "S"

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        if self.theme_mode == "dark":
            self.setStyleSheet(
                "QWidget { background: #1B1E24; color: #E6E6E6; }"
                "QLabel { background: transparent; color: #E6E6E6; }"
                "QFrame#marketItem { background: #20242B; border: 1px solid #323843; border-radius: 14px; }"
                "QLabel#itemIcon { background: #2B313A; border-radius: 10px; color: #9AA4FF; font-size: 18px; font-weight: 700; }"
                "QLabel#itemTitle { color: #F2F4FA; font-size: 13px; font-weight: 700; }"
                "QLabel#itemDesc { color: #8F98AB; font-size: 12px; }"
                "QLabel#itemMeta { color: #6F7A91; font-size: 11px; }"
                "QLineEdit { background: #171A20; border: 1px solid #313743; border-radius: 12px; padding: 9px 12px; color: #E6E6E6; }"
                "QLabel#marketStatus { color: #AEB7C8; background: #20242B; border: 1px solid #323843; border-radius: 10px; padding: 10px 12px; }"
                "QLabel#marketEmpty { color: #8F98AB; font-size: 13px; padding: 28px; }"
                "QPushButton { background: #2C313B; border: 1px solid #353C47; border-radius: 12px; color: #E6E6E6; padding: 8px 12px; }"
                "QPushButton:hover { background: #353B47; }"
                "QPushButton#itemAddBtn { border-radius: 15px; font-size: 18px; padding: 0; }"
                "QPushButton#itemSetupBtn { border-radius: 10px; font-size: 12px; padding: 0; }"
                "QPushButton#marketTab { background: transparent; border: 0; border-radius: 10px; color: #AEB7C8; padding: 8px 14px; font-weight: 600; }"
                "QPushButton#marketTab[active=\"true\"] { background: #2C313B; color: #F4F6FF; }"
                f"{back_button_style('dark')}"
            )
        else:
            self.setStyleSheet(
                "QWidget { background: #FCFCFE; color: #1F1F1F; }"
                "QLabel { background: transparent; color: #24324A; }"
                "QFrame#marketItem { background: #FFFFFF; border: 1px solid #EEF2F7; border-radius: 14px; }"
                "QFrame#marketItem:hover { background: #F8FAFD; }"
                "QLabel#itemIcon { background: #F3F5FA; border-radius: 10px; color: #4C63F6; font-size: 18px; font-weight: 700; }"
                "QLabel#itemTitle { color: #1F2937; font-size: 13px; font-weight: 700; }"
                "QLabel#itemDesc { color: #6B7280; font-size: 12px; }"
                "QLabel#itemMeta { color: #8A94A8; font-size: 11px; }"
                "QLineEdit { background: #FFFFFF; border: 1px solid #E5EAF5; border-radius: 12px; padding: 9px 12px; color: #24324A; }"
                "QLabel#marketStatus { color: #5F6B7A; background: #F8FAFD; border: 1px solid #E5EAF5; border-radius: 10px; padding: 10px 12px; }"
                "QLabel#marketEmpty { color: #7A8497; font-size: 13px; padding: 28px; }"
                "QPushButton { background: #F3F5FA; border: 1px solid #E5EAF5; border-radius: 12px; color: #24324A; padding: 8px 12px; }"
                "QPushButton:hover { background: #EDF1F8; }"
                "QPushButton#itemAddBtn { border-radius: 15px; font-size: 18px; padding: 0; }"
                "QPushButton#itemSetupBtn { border-radius: 10px; font-size: 12px; padding: 0; }"
                "QPushButton#marketTab { background: transparent; border: 0; border-radius: 10px; color: #7A8497; padding: 8px 14px; font-weight: 600; }"
                "QPushButton#marketTab[active=\"true\"] { background: #F0F1F4; color: #172033; }"
                f"{back_button_style('light')}"
            )
        self._sync_tab_buttons()

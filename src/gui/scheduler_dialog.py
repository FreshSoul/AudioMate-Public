from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from PyQt6.QtCore import QDate, QDateTime, QPointF, QRectF, QTime, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from src.gui.common import back_button_style, configure_back_button
from src.utils.schedule_store import parse_datetime


_WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_SCHEDULE_LABELS = {
    "once": "一次性",
    "daily": "每天",
    "weekly": "每周",
    "interval": "自定义",
}
class ScheduleIconButton(QPushButton):
    def __init__(self, icon_kind: str, parent=None, size: int = 28, filled: bool = False):
        super().__init__(parent)
        self.icon_kind = icon_kind
        self.filled = filled
        self.theme_mode = "light"
        self.setText("")
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_theme(self, theme_mode: str):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        self.update()

    def _colors(self):
        is_dark = self.theme_mode == "dark"
        if self.icon_kind == "power":
            if self.isEnabled():
                return {
                    "bg": QColor("#22C55E") if not self.underMouse() else QColor("#34D399"),
                    "border": QColor("#22C55E"),
                    "icon": QColor("#FFFFFF"),
                }
            return {"bg": QColor("#F1F5F9"), "border": QColor("#F1F5F9"), "icon": QColor("#94A3B8")}

        bg = QColor("#EEF2FF") if not is_dark else QColor("#2A3040")
        if self.underMouse():
            bg = QColor("#E0E7FF") if not is_dark else QColor("#343B50")
        if self.isDown():
            bg = QColor("#E0E7FF") if not is_dark else QColor("#30364A")
        if not self.isEnabled():
            return {
                "bg": QColor("#F1F5F9") if not is_dark else QColor("#303642"),
                "border": QColor("#E2E8F0") if not is_dark else QColor("#3A4351"),
                "icon": QColor("#CBD5E1") if not is_dark else QColor("#718096"),
            }
        return {
            "bg": bg,
            "border": QColor("#E0E7FF") if not is_dark else QColor("#3A4351"),
            "icon": QColor("#6366F1") if not is_dark else QColor("#8B82FF"),
        }

    def paintEvent(self, _event):
        colors = self._colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = min(rect.width(), rect.height()) / (2 if self.icon_kind in {"run", "edit", "more"} else 4)
        if self.icon_kind == "power":
            radius = 7
        painter.setPen(QPen(colors["border"], 1))
        painter.setBrush(colors["bg"])
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(QPen(colors["icon"], 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        self._draw_icon(painter, rect, colors["icon"])

    def _draw_icon(self, painter: QPainter, rect: QRectF, icon_color: QColor):
        cx = rect.center().x()
        cy = rect.center().y()
        if self.icon_kind == "back":
            painter.drawLine(QPointF(cx + 5, cy - 7), QPointF(cx - 4, cy))
            painter.drawLine(QPointF(cx - 4, cy), QPointF(cx + 5, cy + 7))
            painter.drawLine(QPointF(cx - 3, cy), QPointF(cx + 8, cy))
        elif self.icon_kind == "down":
            painter.drawLine(QPointF(cx - 5, cy - 2), QPointF(cx, cy + 4))
            painter.drawLine(QPointF(cx, cy + 4), QPointF(cx + 5, cy - 2))
        elif self.icon_kind == "power":
            painter.drawLine(QPointF(cx, cy - 7), QPointF(cx, cy - 1))
            path = QPainterPath()
            path.moveTo(cx - 6, cy - 4)
            path.cubicTo(cx - 9, cy + 1, cx - 6, cy + 8, cx, cy + 8)
            path.cubicTo(cx + 6, cy + 8, cx + 9, cy + 1, cx + 6, cy - 4)
            painter.drawPath(path)
        elif self.icon_kind == "run":
            painter.setBrush(icon_color)
            painter.setPen(Qt.PenStyle.NoPen)
            path = QPainterPath()
            path.moveTo(cx - 3, cy - 6)
            path.lineTo(cx + 6, cy)
            path.lineTo(cx - 3, cy + 6)
            path.closeSubpath()
            painter.drawPath(path)
        elif self.icon_kind == "edit":
            painter.drawLine(QPointF(cx - 5, cy + 5), QPointF(cx + 5, cy - 5))
            painter.drawLine(QPointF(cx + 3, cy - 7), QPointF(cx + 7, cy - 3))
            painter.drawLine(QPointF(cx - 7, cy + 7), QPointF(cx - 3, cy + 6))
        elif self.icon_kind == "more":
            painter.setBrush(icon_color)
            painter.setPen(Qt.PenStyle.NoPen)
            for offset in (-5, 0, 5):
                painter.drawEllipse(QPointF(cx + offset, cy), 1.6, 1.6)


def _arrow_color(widget: QWidget, theme_mode: str) -> QColor:
    if not widget.isEnabled():
        return QColor("#9AA6BD")
    return QColor("#8B82FF" if theme_mode == "dark" else "#5964F2")


def _paint_spin_arrows(widget: QWidget, painter: QPainter, theme_mode: str):
    color = _arrow_color(widget, theme_mode)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    center_x = widget.width() - 14
    top_y = widget.height() / 2 - 7
    bottom_y = widget.height() / 2 + 7
    painter.drawLine(QPointF(center_x - 4, top_y + 3), QPointF(center_x, top_y - 1))
    painter.drawLine(QPointF(center_x, top_y - 1), QPointF(center_x + 4, top_y + 3))
    painter.drawLine(QPointF(center_x - 4, bottom_y - 3), QPointF(center_x, bottom_y + 1))
    painter.drawLine(QPointF(center_x, bottom_y + 1), QPointF(center_x + 4, bottom_y - 3))


def _paint_down_arrow(widget: QWidget, painter: QPainter, theme_mode: str):
    color = _arrow_color(widget, theme_mode)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(color, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    center_x = widget.width() - 17
    center_y = widget.height() / 2
    painter.drawLine(QPointF(center_x - 5, center_y - 2), QPointF(center_x, center_y + 4))
    painter.drawLine(QPointF(center_x, center_y + 4), QPointF(center_x + 5, center_y - 2))


class ScheduleSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_mode = "light"

    def set_theme(self, theme_mode: str):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        _paint_spin_arrows(self, painter, self.theme_mode)


class ScheduleTimeEdit(QTimeEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_mode = "light"

    def set_theme(self, theme_mode: str):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        _paint_spin_arrows(self, painter, self.theme_mode)


class ScheduleDateTimeEdit(QDateTimeEdit):
    def __init__(self, parent=None, dropdown_icon: bool = False):
        super().__init__(parent)
        self.theme_mode = "light"
        self.dropdown_icon = dropdown_icon

    def set_theme(self, theme_mode: str):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        if self.dropdown_icon:
            _paint_down_arrow(self, painter, self.theme_mode)
        else:
            _paint_spin_arrows(self, painter, self.theme_mode)


class ScheduleComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_mode = "light"

    def set_theme(self, theme_mode: str):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        icon_color = QColor("#8B82FF" if self.theme_mode == "dark" else "#6366F1")
        if not self.isEnabled():
            icon_color = QColor("#94A3B8")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(icon_color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx = self.width() - 18
        cy = self.height() / 2
        painter.drawLine(QPointF(cx - 5, cy - 2), QPointF(cx, cy + 4))
        painter.drawLine(QPointF(cx, cy + 4), QPointF(cx + 5, cy - 2))


class SchedulerDialog(QWidget):
    back_requested = pyqtSignal()
    task_add_requested = pyqtSignal(dict)
    task_update_requested = pyqtSignal(str, dict)
    task_delete_requested = pyqtSignal(str)
    task_enabled_changed = pyqtSignal(str, bool)
    task_run_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_mode = "light"
        self._tasks: list[dict[str, Any]] = []
        self._editing_task_id: str | None = None
        self._status_filter = "all"
        self._search_text = ""
        self._active_tab = "tasks"
        self._selected_schedule_type = "once"
        # The "下次执行时间" column is rendered as a static QTableWidgetItem; without
        # a periodic refresh, displayed times go stale (and look like missed runs)
        # the moment the scheduled time passes. Refresh once a minute while the
        # dialog is visible so the user always sees a current value.
        self._next_run_refresh_timer = QTimer(self)
        self._next_run_refresh_timer.setInterval(60_000)
        self._next_run_refresh_timer.timeout.connect(self._refresh_next_run_column)
        self._setup_ui()
        self.apply_theme(self.theme_mode)

    def showEvent(self, event):  # noqa: N802 — Qt override
        super().showEvent(event)
        self._next_run_refresh_timer.start()

    def hideEvent(self, event):  # noqa: N802 — Qt override
        self._next_run_refresh_timer.stop()
        super().hideEvent(event)

    def _refresh_next_run_column(self):
        """Update column 3 (next-run time) in place without rebuilding the table."""
        if not hasattr(self, "task_table"):
            return
        for row, task in enumerate(self._tasks):
            item = self.task_table.item(row, 3)
            if item is not None:
                item.setText(self._format_next_run(task.get("next_run_at")))

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("scheduleHeader")
        header.setFixedHeight(76)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 14, 22, 14)
        header_layout.setSpacing(12)

        self.back_btn = configure_back_button(QPushButton())
        self.back_btn.clicked.connect(self.back_requested.emit)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        self.title_label = QLabel("⏰ 定时任务")
        self.title_label.setObjectName("scheduleTitle")
        self.title_label.setFont(QFont("", 20, QFont.Weight.DemiBold))
        self.subtitle_label = QLabel("按时进行AudioMate任务")
        self.subtitle_label.setObjectName("scheduleSubtitle")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)

        header_layout.addWidget(self.back_btn)
        header_layout.addLayout(title_col)
        header_layout.addStretch()
        root.addWidget(header)

        self.separator = QFrame()
        self.separator.setObjectName("scheduleSeparator")
        self.separator.setFrameShape(QFrame.Shape.HLine)
        self.separator.setFixedHeight(1)
        root.addWidget(self.separator)

        body = QWidget()
        body.setObjectName("scheduleBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(18, 18, 18, 18)
        body_layout.setSpacing(16)

        main_panel = QFrame()
        main_panel.setObjectName("mainPanel")
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(14)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(8)
        self.tasks_tab_btn = self._make_tab_button("定时任务", "tasks")
        self.logs_tab_btn = self._make_tab_button("执行日志", "logs")
        tab_row.addWidget(self.tasks_tab_btn)
        tab_row.addWidget(self.logs_tab_btn)
        tab_row.addStretch()
        self.new_task_btn = QPushButton("＋ 新建任务")
        self.new_task_btn.setObjectName("primaryBtn")
        self.new_task_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_task_btn.clicked.connect(self._clear_form)
        tab_row.addWidget(self.new_task_btn)
        main_layout.addLayout(tab_row)

        self.page_stack = QStackedWidget()
        self.tasks_page = QWidget()
        tasks_layout = QVBoxLayout(self.tasks_page)
        tasks_layout.setContentsMargins(0, 0, 0, 0)
        tasks_layout.setSpacing(12)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_buttons: dict[str, QPushButton] = {}
        for key, label in (("all", "全部"), ("enabled", "启用中"), ("paused", "暂停"), ("disabled", "已禁用")):
            button = QPushButton(label)
            button.setObjectName("filterChip")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=key: self._set_status_filter(value))
            self.filter_buttons[key] = button
            filter_row.addWidget(button)
        filter_row.addStretch()
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("搜索任务名称或提示词...")
        self.search_input.setFixedWidth(230)
        self.search_input.textChanged.connect(self._on_search_changed)
        filter_row.addWidget(self.search_input)
        tasks_layout.addLayout(filter_row)

        self.task_table = QTableWidget(0, 6)
        self.task_table.setObjectName("taskTable")
        self.task_table.setHorizontalHeaderLabels(["", "任务名称", "执行规则", "下次执行时间", "状态", "操作"])
        header_view = self.task_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.task_table.setColumnWidth(0, 58)
        self.task_table.setColumnWidth(2, 116)
        self.task_table.setColumnWidth(3, 164)
        self.task_table.setColumnWidth(4, 92)
        self.task_table.setColumnWidth(5, 138)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.setShowGrid(False)
        self.task_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_table.horizontalHeader().setFixedHeight(42)
        tasks_layout.addWidget(self.task_table, 1)

        self.empty_label = QLabel("暂无定时任务\n\n创建一个任务，让 Agent 在指定时间自动开始工作。")
        self.empty_label.setObjectName("emptyLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tasks_layout.addWidget(self.empty_label, 1)

        self.logs_page = QWidget()
        logs_layout = QVBoxLayout(self.logs_page)
        logs_layout.setContentsMargins(0, 0, 0, 0)
        self.logs_empty_label = QLabel("暂无执行日志\n\n任务触发记录会在后续版本展示在这里。")
        self.logs_empty_label.setObjectName("emptyLabel")
        self.logs_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logs_layout.addWidget(self.logs_empty_label, 1)

        self.page_stack.addWidget(self.tasks_page)
        self.page_stack.addWidget(self.logs_page)
        main_layout.addWidget(self.page_stack, 1)

        self.form_card = QFrame()
        self.form_card.setObjectName("formCard")
        self.form_card.setFixedWidth(330)
        form_layout = QVBoxLayout(self.form_card)
        form_layout.setContentsMargins(18, 18, 18, 18)
        form_layout.setSpacing(12)

        self.form_title = QLabel("新建任务")
        self.form_title.setObjectName("formTitle")
        self.form_title.setFont(QFont("", 16, QFont.Weight.DemiBold))
        form_layout.addWidget(self.form_title)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("任务名称")
        form_layout.addWidget(self._field_block("名称", self.title_input))

        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("输入到点后要发送给 Agent 的提示")
        self.prompt_input.setFixedHeight(108)
        form_layout.addWidget(self._field_block("提示词", self.prompt_input))

        rule_block = QWidget()
        rule_layout = QGridLayout(rule_block)
        rule_layout.setContentsMargins(0, 0, 0, 0)
        rule_layout.setHorizontalSpacing(6)
        rule_layout.setVerticalSpacing(6)
        self.schedule_type_buttons: dict[str, QPushButton] = {}
        for index, schedule_type in enumerate(("once", "daily", "weekly", "interval")):
            button = QPushButton(_SCHEDULE_LABELS[schedule_type])
            button.setObjectName("segmentBtn")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=schedule_type: self._set_schedule_type(value))
            self.schedule_type_buttons[schedule_type] = button
            rule_layout.addWidget(button, index // 2, index % 2)
        form_layout.addWidget(self._field_block("执行规则", rule_block))

        self.once_edit = ScheduleDateTimeEdit()
        self.once_edit.setCalendarPopup(True)
        self.once_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.once_edit.setMinimumDateTime(QDateTime.currentDateTime())
        form_layout.addWidget(self._field_block("执行时间", self.once_edit, "once"))

        self.time_edit = ScheduleTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        form_layout.addWidget(self._field_block("固定时间", self.time_edit, "time"))

        weekdays_widget = QWidget()
        weekdays_layout = QGridLayout(weekdays_widget)
        weekdays_layout.setContentsMargins(0, 0, 0, 0)
        weekdays_layout.setHorizontalSpacing(6)
        weekdays_layout.setVerticalSpacing(6)
        self.weekday_checks: list[QCheckBox] = []
        for index, label in enumerate(_WEEKDAY_LABELS):
            check = QCheckBox(label)
            check.setObjectName("weekdayCheck")
            self.weekday_checks.append(check)
            weekdays_layout.addWidget(check, index // 4, index % 4)
        form_layout.addWidget(self._field_block("重复日期", weekdays_widget, "weekly"))

        self.interval_spin = ScheduleSpinBox()
        self.interval_spin.setRange(1, 10080)
        self.interval_spin.setSuffix(" 分钟")
        self.interval_spin.setValue(60)
        form_layout.addWidget(self._field_block("执行间隔", self.interval_spin, "interval"))

        self.start_date_edit = ScheduleDateTimeEdit(dropdown_icon=True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setEnabled(False)
        form_layout.addWidget(self._field_block("开始日期", self.start_date_edit))

        self.timezone_combo = ScheduleComboBox()
        self.timezone_combo.addItems(["(UTC+08:00) 北京，上海，香港", "本地时区"])
        self.timezone_combo.setEnabled(False)
        form_layout.addWidget(self._field_block("时区", self.timezone_combo))

        self.enabled_check = QCheckBox("启用任务")
        self.enabled_check.setObjectName("enabledCheck")
        self.enabled_check.setChecked(True)
        form_layout.addWidget(self.enabled_check)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("primaryBtn")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._save_form)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("secondaryBtn")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._clear_form)
        button_row.addWidget(self.save_btn)
        button_row.addWidget(self.cancel_btn)
        form_layout.addLayout(button_row)
        form_layout.addStretch()

        body_layout.addWidget(main_panel, 1)
        body_layout.addWidget(self.form_card)
        root.addWidget(body, 1)

        self._rule_blocks = {
            "once": self.findChild(QWidget, "ruleBlock_once"),
            "time": self.findChild(QWidget, "ruleBlock_time"),
            "weekly": self.findChild(QWidget, "ruleBlock_weekly"),
            "interval": self.findChild(QWidget, "ruleBlock_interval"),
        }
        self._set_active_tab("tasks")
        self._clear_form()

    def _field_block(self, label_text: str, widget: QWidget, rule_key: str | None = None) -> QWidget:
        block = QWidget()
        if rule_key:
            block.setObjectName(f"ruleBlock_{rule_key}")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        layout.addWidget(widget)
        return block

    def _make_tab_button(self, text: str, tab_key: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("tabBtn")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, key=tab_key: self._set_active_tab(key))
        return button

    def set_tasks(self, tasks: list[dict[str, Any]]):
        self._tasks = [dict(task) for task in tasks]
        self._refresh_table()

    def refresh(self):
        self._refresh_table()

    def _set_active_tab(self, tab_key: str):
        self._active_tab = tab_key if tab_key in {"tasks", "logs"} else "tasks"
        self.tasks_tab_btn.setChecked(self._active_tab == "tasks")
        self.logs_tab_btn.setChecked(self._active_tab == "logs")
        self.page_stack.setCurrentWidget(self.tasks_page if self._active_tab == "tasks" else self.logs_page)

    def _set_status_filter(self, value: str):
        self._status_filter = value if value in {"all", "enabled", "paused", "disabled"} else "all"
        self._refresh_table()

    def _on_search_changed(self, text: str):
        self._search_text = (text or "").strip().lower()
        self._refresh_table()

    def _task_status(self, task: dict[str, Any]) -> str:
        if task.get("enabled"):
            return "enabled"
        return "disabled"

    def _filtered_tasks(self) -> list[dict[str, Any]]:
        result = []
        for task in self._tasks:
            status = self._task_status(task)
            if self._status_filter == "enabled" and status != "enabled":
                continue
            if self._status_filter == "disabled" and status != "disabled":
                continue
            if self._status_filter == "paused" and status != "paused":
                continue
            if self._search_text:
                haystack = f"{task.get('title', '')} {task.get('prompt', '')}".lower()
                if self._search_text not in haystack:
                    continue
            result.append(task)
        return result

    def _refresh_filter_counts(self):
        total = len(self._tasks)
        enabled = sum(1 for task in self._tasks if self._task_status(task) == "enabled")
        disabled = sum(1 for task in self._tasks if self._task_status(task) == "disabled")
        counts = {"all": total, "enabled": enabled, "paused": 0, "disabled": disabled}
        labels = {"all": "全部", "enabled": "启用中", "paused": "暂停", "disabled": "已禁用"}
        for key, button in self.filter_buttons.items():
            button.setText(f"{labels[key]}  {counts[key]}")
            button.setChecked(key == self._status_filter)

    def _refresh_table(self):
        self._refresh_filter_counts()
        tasks = self._filtered_tasks()
        self.task_table.setRowCount(len(tasks))
        self.task_table.setVisible(bool(tasks))
        self.empty_label.setVisible(not tasks)

        for row, task in enumerate(tasks):
            self.task_table.setRowHeight(row, 58)
            self.task_table.setCellWidget(row, 0, self._icon_cell(task))

            title_item = QTableWidgetItem(str(task.get("title") or "定时任务"))
            title_item.setToolTip(str(task.get("prompt") or ""))
            self.task_table.setItem(row, 1, title_item)
            self.task_table.setItem(row, 2, QTableWidgetItem(self._rule_summary(task)))
            self.task_table.setItem(row, 3, QTableWidgetItem(self._format_next_run(task.get("next_run_at"))))
            self.task_table.setCellWidget(row, 4, self._status_badge(task))
            self.task_table.setCellWidget(row, 5, self._action_cell(task))

    def _icon_cell(self, task: dict[str, Any]) -> QWidget:
        holder = QWidget()
        holder.setObjectName("transparentCell")
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        icon = ScheduleIconButton("power", size=30)
        icon.setEnabled(bool(task.get("enabled")))
        icon.setToolTip("启用" if task.get("enabled") else "已禁用")
        icon.set_theme(self.theme_mode)
        icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)
        return holder

    def _status_badge(self, task: dict[str, Any]) -> QWidget:
        status = self._task_status(task)
        label = QLabel("启用中" if status == "enabled" else "已禁用")
        label.setObjectName("statusBadgeEnabled" if status == "enabled" else "statusBadgeDisabled")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFixedSize(58, 26)
        holder = QWidget()
        holder.setObjectName("transparentCell")
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignCenter)
        return holder

    def _action_cell(self, task: dict[str, Any]) -> QWidget:
        holder = QWidget()
        holder.setObjectName("transparentCell")
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        run_btn = ScheduleIconButton("run", size=28)
        run_btn.setToolTip("立即执行")
        run_btn.clicked.connect(lambda _checked=False, item=dict(task): self.task_run_requested.emit(item))
        edit_btn = ScheduleIconButton("edit", size=28)
        edit_btn.setToolTip("编辑任务")
        edit_btn.clicked.connect(lambda _checked=False, item=dict(task): self._edit_task(item))
        more_btn = ScheduleIconButton("more", size=28)
        more_btn.setToolTip("更多操作")
        more_btn.clicked.connect(lambda _checked=False, button=more_btn, item=dict(task): self._show_more_menu(button, item))
        for button in (run_btn, edit_btn, more_btn):
            button.set_theme(self.theme_mode)
            layout.addWidget(button)
        layout.addStretch()
        return holder

    def _show_more_menu(self, button: QPushButton, task: dict[str, Any]):
        menu = QMenu(self)
        toggle_text = "禁用任务" if task.get("enabled") else "启用任务"
        toggle_action = menu.addAction(toggle_text)
        delete_action = menu.addAction("删除任务")
        selected = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if selected == toggle_action:
            self.task_enabled_changed.emit(task.get("id"), not bool(task.get("enabled")))
        elif selected == delete_action:
            self._delete_task(task)

    def _format_next_run(self, value: Any) -> str:
        next_run = parse_datetime(value)
        if not next_run:
            return "未计划"
        return next_run.strftime("%Y-%m-%d %H:%M")

    def _rule_summary(self, task: dict[str, Any]) -> str:
        schedule_type = task.get("schedule_type") or "once"
        if schedule_type in {"daily", "weekly"}:
            return f"{_SCHEDULE_LABELS.get(schedule_type, '规则')} {task.get('time') or '--:--'}"
        if schedule_type == "interval":
            return f"每 {task.get('interval_minutes') or 0} 分钟"
        return _SCHEDULE_LABELS.get(schedule_type, "一次性")

    def _set_schedule_type(self, schedule_type: str):
        self._selected_schedule_type = schedule_type if schedule_type in _SCHEDULE_LABELS else "once"
        for key, button in self.schedule_type_buttons.items():
            button.setChecked(key == self._selected_schedule_type)
        self._sync_rule_fields()

    def _sync_rule_fields(self):
        schedule_type = self._selected_schedule_type
        self._rule_blocks["once"].setVisible(schedule_type == "once")
        self._rule_blocks["time"].setVisible(schedule_type in {"daily", "weekly"})
        self._rule_blocks["weekly"].setVisible(schedule_type == "weekly")
        self._rule_blocks["interval"].setVisible(schedule_type == "interval")

    def _clear_form(self):
        self._editing_task_id = None
        self.form_title.setText("新建任务")
        self.title_input.clear()
        self.prompt_input.clear()
        self._set_schedule_type("once")
        self.once_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self.start_date_edit.setDateTime(QDateTime.currentDateTime())
        self.time_edit.setTime(QTime.currentTime().addSecs(3600))
        for check in self.weekday_checks:
            check.setChecked(False)
        today = QDate.currentDate().dayOfWeek() - 1
        if 0 <= today < len(self.weekday_checks):
            self.weekday_checks[today].setChecked(True)
        self.interval_spin.setValue(60)
        self.enabled_check.setChecked(True)
        self._set_active_tab("tasks")

    def _edit_task(self, task: dict[str, Any]):
        self._editing_task_id = task.get("id")
        self.form_title.setText("编辑任务")
        self.title_input.setText(str(task.get("title") or ""))
        self.prompt_input.setPlainText(str(task.get("prompt") or ""))
        schedule_type = task.get("schedule_type") or "once"
        self._set_schedule_type(schedule_type)
        if schedule_type == "once":
            run_at = parse_datetime(task.get("run_at")) or (datetime.now() + timedelta(hours=1))
            self.once_edit.setDateTime(QDateTime(QDate(run_at.year, run_at.month, run_at.day), QTime(run_at.hour, run_at.minute)))
        if schedule_type in {"daily", "weekly"}:
            hour, minute = self._parse_time_parts(task.get("time"))
            self.time_edit.setTime(QTime(hour, minute))
        weekdays = set(task.get("weekdays") or [])
        for index, check in enumerate(self.weekday_checks):
            check.setChecked(index in weekdays)
        if schedule_type == "interval":
            self.interval_spin.setValue(int(task.get("interval_minutes") or 60))
        self.enabled_check.setChecked(bool(task.get("enabled")))
        self._set_active_tab("tasks")

    def _parse_time_parts(self, value: Any) -> tuple[int, int]:
        if isinstance(value, str) and ":" in value:
            parts = value.split(":")
            try:
                return int(parts[0]), int(parts[1])
            except (TypeError, ValueError):
                pass
        now = datetime.now() + timedelta(hours=1)
        return now.hour, now.minute

    def _delete_task(self, task: dict[str, Any]):
        title = str(task.get("title") or "定时任务")
        reply = QMessageBox.question(self, "删除任务", f"确定删除“{title}”吗？")
        if reply == QMessageBox.StandardButton.Yes:
            self.task_delete_requested.emit(task.get("id"))
            if self._editing_task_id == task.get("id"):
                self._clear_form()

    def _save_form(self):
        title = self.title_input.text().strip() or "定时任务"
        prompt = self.prompt_input.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "提示词为空", "请输入到点后要发送给 Agent 的提示词。")
            return

        schedule_type = self._selected_schedule_type
        payload: dict[str, Any] = {
            "title": title,
            "prompt": prompt,
            "schedule_type": schedule_type,
            "enabled": self.enabled_check.isChecked(),
        }

        if schedule_type == "once":
            run_at = self.once_edit.dateTime().toPyDateTime().replace(second=0, microsecond=0)
            payload["run_at"] = run_at.isoformat()
        elif schedule_type == "daily":
            payload["time"] = self.time_edit.time().toString("HH:mm")
        elif schedule_type == "weekly":
            payload["time"] = self.time_edit.time().toString("HH:mm")
            weekdays = [index for index, check in enumerate(self.weekday_checks) if check.isChecked()]
            if not weekdays:
                QMessageBox.warning(self, "未选择星期", "请至少选择一个星期。")
                return
            payload["weekdays"] = weekdays
        elif schedule_type == "interval":
            payload["interval_minutes"] = self.interval_spin.value()

        if self._editing_task_id:
            self.task_update_requested.emit(self._editing_task_id, payload)
        else:
            self.task_add_requested.emit(payload)
        self._clear_form()

    def _theme_tokens(self) -> dict[str, str]:
        if self.theme_mode == "dark":
            return {
                "bg": "#1E1F22",
                "panel": "#232833",
                "panel_alt": "#282E3A",
                "field": "#1B202A",
                "text": "#EEF2FF",
                "muted": "#9AA6BD",
                "border": "#343C4B",
                "header": "#20242E",
                "primary": "#7D73FF",
                "primary_hover": "#8B82FF",
                "primary_soft": "#303060",
                "green": "#45D483",
                "green_bg": "#173827",
                "gray_bg": "#303642",
            }
        return {
            "bg": "#F8FAFF",
            "panel": "#FFFFFF",
            "panel_alt": "#F5F7FF",
            "field": "#FFFFFF",
            "text": "#202537",
            "muted": "#6B7280",
            "border": "#E3E8F6",
            "header": "#F6F8FF",
            "primary": "#6366F1",
            "primary_hover": "#5155E8",
            "primary_soft": "#EEF0FF",
            "green": "#13A66B",
            "green_bg": "#EAFBF2",
            "gray_bg": "#F1F5F9",
        }

    def apply_theme(self, theme_mode: str):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        t = self._theme_tokens()
        self.timezone_combo.set_theme(self.theme_mode)
        self.once_edit.set_theme(self.theme_mode)
        self.time_edit.set_theme(self.theme_mode)
        self.interval_spin.set_theme(self.theme_mode)
        self.start_date_edit.set_theme(self.theme_mode)
        self.setStyleSheet(
            back_button_style(self.theme_mode) +
            f"QWidget {{ background: {t['bg']}; color: {t['text']}; font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; }}"
            "QWidget#transparentCell { background: transparent; }"
            f"QWidget#scheduleHeader {{ background: {t['panel']}; }}"
            f"QWidget#scheduleBody {{ background: {t['bg']}; }}"
            f"QFrame#scheduleSeparator {{ background: {t['border']}; border: none; }}"
            f"QFrame#mainPanel, QFrame#formCard {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 14px; }}"
            f"QLabel#scheduleTitle, QLabel#formTitle {{ color: {t['text']}; background: transparent; }}"
            f"QLabel#scheduleSubtitle, QLabel#fieldLabel {{ color: {t['muted']}; background: transparent; font-size: 12px; font-weight: 600; }}"
            f"QLabel#emptyLabel {{ color: {t['muted']}; background: transparent; font-size: 14px; padding: 60px 0; }}"
            f"QLineEdit, QTextEdit, QComboBox, QDateTimeEdit, QTimeEdit, QSpinBox {{ background: {t['field']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 9px; padding: 8px; padding-right: 30px; }}"
            "QComboBox::drop-down { border: none; width: 30px; }"
            "QComboBox::down-arrow { image: none; border: none; width: 0px; height: 0px; }"
            "QDateTimeEdit::drop-down { border: none; width: 28px; }"
            "QDateTimeEdit::down-arrow { image: none; border: none; width: 0px; height: 0px; }"
            "QDateTimeEdit::up-button, QTimeEdit::up-button, QSpinBox::up-button { border: none; background: transparent; width: 26px; subcontrol-origin: border; subcontrol-position: top right; }"
            "QDateTimeEdit::down-button, QTimeEdit::down-button, QSpinBox::down-button { border: none; background: transparent; width: 26px; subcontrol-origin: border; subcontrol-position: bottom right; }"
            "QDateTimeEdit::up-arrow, QDateTimeEdit::down-arrow, QTimeEdit::up-arrow, QTimeEdit::down-arrow, QSpinBox::up-arrow, QSpinBox::down-arrow { image: none; border: none; width: 0px; height: 0px; }"
            f"QLineEdit#searchInput {{ background: {t['panel']}; border-radius: 16px; padding: 8px 12px; }}"
            f"QComboBox:disabled, QDateTimeEdit:disabled {{ color: {t['muted']}; background: {t['panel_alt']}; }}"
            f"QPushButton#primaryBtn {{ background: {t['primary']}; color: #FFFFFF; border: none; border-radius: 9px; padding: 9px 14px; font-weight: 700; }}"
            f"QPushButton#primaryBtn:hover {{ background: {t['primary_hover']}; }}"
            f"QPushButton#secondaryBtn {{ background: {t['panel']}; color: {t['muted']}; border: 1px solid {t['border']}; border-radius: 9px; padding: 9px 14px; font-weight: 600; }}"
            f"QPushButton#tabBtn {{ background: transparent; color: {t['muted']}; border: none; border-radius: 0; padding: 8px 12px; font-weight: 700; }}"
            f"QPushButton#tabBtn:checked {{ color: {t['primary']}; border-bottom: 2px solid {t['primary']}; }}"
            f"QPushButton#filterChip {{ background: {t['panel']}; color: {t['muted']}; border: 1px solid {t['border']}; border-radius: 12px; padding: 7px 12px; font-weight: 700; }}"
            f"QPushButton#filterChip:checked {{ background: {t['primary_soft']}; color: {t['primary']}; border: 1px solid {t['primary']}; }}"
            f"QPushButton#segmentBtn {{ background: {t['panel']}; color: {t['muted']}; border: 1px solid {t['border']}; border-radius: 9px; padding: 8px; font-weight: 700; }}"
            f"QPushButton#segmentBtn:checked {{ background: {t['primary_soft']}; color: {t['primary']}; border: 1px solid {t['primary']}; }}"
            f"QTableWidget#taskTable {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 12px; gridline-color: transparent; }}"
            f"QHeaderView::section {{ background: {t['header']}; color: {t['muted']}; border: none; padding: 8px; font-weight: 700; }}"
            f"QTableWidget::item {{ border-bottom: 1px solid {t['border']}; padding: 6px; }}"
            f"QLabel#statusBadgeEnabled {{ background: {t['green_bg']}; color: {t['green']}; border-radius: 10px; font-size: 12px; font-weight: 800; }}"
            f"QLabel#statusBadgeDisabled {{ background: {t['gray_bg']}; color: {t['muted']}; border-radius: 10px; font-size: 12px; font-weight: 800; }}"
            f"QCheckBox {{ color: {t['text']}; background: transparent; spacing: 6px; }}"
            f"QMenu {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 4px; }}"
            f"QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}"
            f"QMenu::item:selected {{ background: {t['primary_soft']}; color: {t['primary']}; }}"
        )

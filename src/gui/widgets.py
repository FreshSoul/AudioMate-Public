"""Reusable UI widget classes for the AudioMate GUI."""

import os
import re

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QTextBrowser, QPushButton,
    QLabel, QFrame, QDialog, QLineEdit, QGraphicsOpacityEffect, QSizePolicy,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer, QObject, QPoint, QRect, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QUrl, QDateTime
from PyQt6.QtGui import QImage, QPixmap, QIcon, QColor, QPalette, QFont, QFontMetrics, QPainter, QDesktopServices

from .common import (
    extract_text_from_content,
    _split_attachment_files_for_display,
    _extract_local_image_paths_from_text,
    _system_file_icon,
    _attachment_secondary_text,
)
from .theme import _apply_context_menu_theme
from src.utils.app_logger import LogDirectoryOpenError, get_logs_dir, open_logs_dir


_FENCED_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(https?://[^)\s]+\)", re.IGNORECASE)
_HTTP_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}]+", re.IGNORECASE)


def _strip_trailing_url_punctuation(value: str) -> tuple[str, str]:
    trailing = ""
    while value and value[-1] in ".,!?;:)]}":
        trailing = value[-1] + trailing
        value = value[:-1]
    return value, trailing


def _protect_markdown_links(text: str) -> tuple[str, dict[str, str]]:
    placeholders = {}

    def _replace(match):
        token = f"__WWISE_LINK_{len(placeholders)}__"
        placeholders[token] = match.group(0)
        return token

    protected = _MARKDOWN_LINK_RE.sub(_replace, text)
    return protected, placeholders


def _protect_inline_code(text: str) -> tuple[str, dict[str, str]]:
    placeholders = {}

    def _replace(match):
        token = f"__WWISE_CODE_{len(placeholders)}__"
        placeholders[token] = match.group(0)
        return token

    protected = _INLINE_CODE_RE.sub(_replace, text)
    return protected, placeholders


def _restore_markdown_links(text: str, placeholders: dict[str, str]) -> str:
    restored = text
    for token, value in placeholders.items():
        restored = restored.replace(token, value)
    return restored


def _linkify_http_urls(text: str) -> str:
    if not text:
        return ""

    def _process_plain_segment(segment: str) -> str:
        protected, link_placeholders = _protect_markdown_links(segment)
        protected, code_placeholders = _protect_inline_code(protected)

        def _replace_url(match):
            candidate = match.group(0)
            url, trailing = _strip_trailing_url_punctuation(candidate)
            if not url:
                return candidate
            return f"[{url}]({url}){trailing}"

        processed = _HTTP_URL_RE.sub(_replace_url, protected)
        processed = _restore_markdown_links(processed, code_placeholders)
        return _restore_markdown_links(processed, link_placeholders)

    parts = []
    last_index = 0
    for fenced_match in _FENCED_CODE_BLOCK_RE.finditer(text):
        if fenced_match.start() > last_index:
            plain_segment = text[last_index:fenced_match.start()]
            parts.append(_process_plain_segment(plain_segment))
        parts.append(fenced_match.group(0))
        last_index = fenced_match.end()

    if last_index < len(text):
        parts.append(_process_plain_segment(text[last_index:]))

    return "".join(parts)


_CODE_FENCE_LANG_RE = re.compile(r"^([ \t]*`{3,})[^\n`]*$", re.MULTILINE)


def _strip_code_fence_language(text: str) -> str:
    """Drop the language tag from code-fence lines (```text -> ```).

    Qt's ``QTextEdit.setMarkdown`` has a parser defect: a fenced code block
    whose opening fence carries a language tag (e.g. ``` ```text ```) and
    whose body contains CJK characters renders with the CJK silently dropped
    — users saw large Chinese documents collapse to a few stray symbols.
    Stripping the (purely cosmetic, un-highlighted) language tag avoids the
    defect while keeping the monospace code block intact.

    Only the tag is removed; the fence itself and all body content are
    preserved. Inline code and fence indentation are untouched.
    """
    if not text or "`" not in text:
        return text
    return _CODE_FENCE_LANG_RE.sub(lambda m: m.group(1), text)


def _elide_text_ascii(font_metrics: QFontMetrics, text: str, width: int) -> str:
    if width <= 0:
        return ""
    if font_metrics.horizontalAdvance(text) <= width:
        return text

    ellipsis = "..."
    available_width = max(0, width - font_metrics.horizontalAdvance(ellipsis))
    if available_width <= 0:
        return ellipsis

    trimmed = text
    while trimmed and font_metrics.horizontalAdvance(trimmed) > available_width:
        trimmed = trimmed[:-1]
    return f"{trimmed}{ellipsis}"


def _attachment_display_name(item: dict) -> str:
    path = (item or {}).get("path") or ""
    if path:
        normalized = path.replace("/", os.sep).replace("\\", os.sep)
        base = os.path.basename(normalized)
        if base:
            return base

    raw_name = (item or {}).get("name") or ""
    normalized_name = raw_name.replace("/", os.sep).replace("\\", os.sep)
    return os.path.basename(normalized_name) or raw_name or "附件"


def _normalize_timeline_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    normalized = re.sub(r"^[-*•\d.\s]+", "", normalized)
    normalized = normalized.strip("*_` ")
    return normalized or "正在处理中"


def _truncate_timeline_title(text: str, limit: int = 22) -> str:
    normalized = _normalize_timeline_text(text)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _summarize_timeline_error(error: str, limit: int = 88) -> str:
    lines = [line.strip() for line in (error or "").splitlines() if line.strip()]
    if not lines:
        return "执行失败"

    preferred = None
    for line in reversed(lines):
        lowered = line.lower()
        if "traceback" in lowered or lowered.startswith("file "):
            continue
        if any(token in lowered for token in ("error", "exception", "失败", "错误", "invalid", "denied")):
            preferred = line
            break
    if preferred is None:
        preferred = lines[0]

    preferred = re.sub(r"\s+", " ", preferred)
    if len(preferred) <= limit:
        return preferred
    return f"{preferred[:limit].rstrip()}..."


def _current_timeline_timestamp() -> str:
    return QDateTime.currentDateTime().toString("HH:mm:ss")


def _execution_panel_palette(theme_mode: str) -> dict[str, str]:
    is_dark = theme_mode == "dark"
    if is_dark:
        return {
            "panel_bg": "#161B22",
            "panel_border": "#273142",
            "panel_title": "#F3F7FF",
            "panel_meta": "#98A2B3",
            "panel_muted": "#7C8798",
            "header_icon_bg": "#314E9C",
            "header_icon_text": "#F8FBFF",
            "chevron": "#9FB4DA",
            "rail_idle": "#344054",
            "rail_active": "#5B7CFA",
            "rail_done": "#5B7CFA",
            "rail_failed": "#F97066",
            "badge_pending_bg": "#161B22",
            "badge_pending_border": "#475467",
            "badge_pending_text": "#98A2B3",
            "badge_active_bg": "#5B7CFA",
            "badge_active_border": "#7A95FF",
            "badge_active_text": "#FFFFFF",
            "badge_failed_bg": "#3C1D24",
            "badge_failed_border": "#F97066",
            "badge_failed_text": "#FFD7D3",
            "card_bg": "#1C2330",
            "card_border": "#2B3648",
            "card_running_bg": "#1E2B45",
            "card_running_border": "#5B7CFA",
            "card_failed_bg": "#311F25",
            "card_failed_border": "#D94A44",
            "title": "#F3F7FF",
            "title_active": "#DCE7FF",
            "title_failed": "#FFD7D3",
            "detail": "#B6C2D4",
            "detail_active": "#C6D5FF",
            "detail_failed": "#FFB3AC",
            "status_pending": "#667085",
            "status_running": "#7A95FF",
            "status_done": "#32D583",
            "status_failed": "#F97066",
            "time_pending": "#667085",
            "time_active": "#BFD0FF",
            "time_done": "#B6C2D4",
            "time_failed": "#FFB3AC",
            "substeps_bg": "#202B3C",
            "substeps_border": "#314259",
            "substep_title": "#E7EEF9",
            "substep_detail": "#98A2B3",
            "substep_pending": "#667085",
            "substep_running": "#7A95FF",
            "substep_done": "#5B7CFA",
            "substep_failed": "#F97066",
            "footer_success_bg": "#182A22",
            "footer_success_border": "#22563A",
            "footer_success_icon": "#32D583",
            "footer_success_text": "#E8FFF2",
            "footer_error_bg": "#2E1D22",
            "footer_error_border": "#6E2E36",
            "footer_error_icon": "#F97066",
            "footer_error_text": "#FFE3E0",
        }
    return {
        "panel_bg": "#FFFFFF",
        "panel_border": "#EBEEF5",
        "panel_title": "#101828",
        "panel_meta": "#667085",
        "panel_muted": "#98A2B3",
        "header_icon_bg": "#EEF4FF",
        "header_icon_text": "#4F6BFF",
        "chevron": "#98A2B3",
        "rail_idle": "#D7DDEA",
        "rail_active": "#4F6BFF",
        "rail_done": "#4F6BFF",
        "rail_failed": "#F04438",
        "badge_pending_bg": "#FFFFFF",
        "badge_pending_border": "#D7DDEA",
        "badge_pending_text": "#98A2B3",
        "badge_active_bg": "#4F6BFF",
        "badge_active_border": "#4F6BFF",
        "badge_active_text": "#FFFFFF",
        "badge_failed_bg": "#FFF1F0",
        "badge_failed_border": "#F97066",
        "badge_failed_text": "#D92D20",
        "card_bg": "#FFFFFF",
        "card_border": "#EEF1F5",
        "card_running_bg": "#F6F8FF",
        "card_running_border": "#DCE6FF",
        "card_failed_bg": "#FFF7F6",
        "card_failed_border": "#FFD9D5",
        "title": "#0F172A",
        "title_active": "#1D4ED8",
        "title_failed": "#B42318",
        "detail": "#667085",
        "detail_active": "#4F6BFF",
        "detail_failed": "#B42318",
        "status_pending": "#C7CDD6",
        "status_running": "#4F6BFF",
        "status_done": "#22C55E",
        "status_failed": "#F04438",
        "time_pending": "#C7CDD6",
        "time_active": "#667085",
        "time_done": "#667085",
        "time_failed": "#B42318",
        "substeps_bg": "#F8FAFF",
        "substeps_border": "#E7ECFF",
        "substep_title": "#344054",
        "substep_detail": "#98A2B3",
        "substep_pending": "#C7CDD6",
        "substep_running": "#4F6BFF",
        "substep_done": "#7B6EFF",
        "substep_failed": "#F04438",
        "footer_success_bg": "#F4FBF6",
        "footer_success_border": "#D8F3DF",
        "footer_success_icon": "#22C55E",
        "footer_success_text": "#0F172A",
        "footer_error_bg": "#FFF5F4",
        "footer_error_border": "#FFD6D2",
        "footer_error_icon": "#F04438",
        "footer_error_text": "#8E1C12",
    }


def _coerce_substep_item(item) -> dict[str, str]:
    if isinstance(item, dict):
        title = str(item.get("title") or item.get("text") or item.get("description") or "处理中")
        detail = str(item.get("detail") or "")
        state = str(item.get("state") or "pending")
    else:
        title = str(item or "处理中")
        detail = ""
        state = "pending"
    if state not in {"pending", "running", "done", "failed"}:
        state = "pending"
    return {
        "title": _normalize_timeline_text(title),
        "detail": (detail or "").strip(),
        "state": state,
    }


def _summarize_task_context(task_context: str, limit: int = 26) -> str:
    normalized = _normalize_timeline_text(task_context)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _resolve_thinking_activity_title(activity_text: str, task_context: str = "") -> str:
    activity = _normalize_timeline_text(activity_text)
    if activity in {"总结中", "正在总结", "生成总结", "整理总结"}:
        return "总结中"
    task_summary = _summarize_task_context(task_context, limit=20)
    if not task_summary:
        return activity

    lowered = activity.lower()
    if any(token in lowered for token in ("分析", "检查", "规划", "请求", "处理当前")):
        return f"分析任务需求 · {task_summary}"
    if any(token in lowered for token in ("调整", "修正", "重试", "反馈")):
        return f"调整执行方案 · {task_summary}"
    if any(token in lowered for token in ("执行", "代码", "调用", "落地")):
        return f"准备执行操作 · {task_summary}"
    if any(token in lowered for token in ("整理", "回复", "结果", "总结", "输出")):
        return f"整理最终结果 · {task_summary}"
    return activity


def _default_substeps_for_activity(text: str, task_context: str = "") -> list[dict[str, str]]:
    activity = _normalize_timeline_text(text)
    normalized_task = _normalize_timeline_text(task_context) if task_context else ""
    lowered = f"{normalized_task} {activity}".lower()
    task_summary = _summarize_task_context(task_context, limit=30)

    analysis_terms = (
        "分析", "检查", "看看", "说明", "解释", "判断", "识别", "确认", "review", "inspect", "analy", "explain",
    )
    import_terms = (
        "导入", "import", "导进", "导入到", "导入至",
    )
    attachment_terms = (
        "已附加本地路径", "[文件]", ".wav", ".mp3", ".wem", ".ogg", ".flac", ".aif", ".aiff",
    )
    create_terms = (
        "创建", "新建", "搭建", "结构", "work unit", "event", "container", "folder", "bus", "rtpc", "switch", "state",
    )
    update_terms = (
        "修改", "更新", "设置", "调整", "重命名", "rename", "property", "属性",
    )
    summary_terms = (
        "总结", "回复", "输出", "报告", "整理", "summary", "result", "reply", "response",
    )

    explicit_analysis = any(token in normalized_task.lower() for token in analysis_terms)
    explicit_import = any(token in normalized_task.lower() for token in import_terms)
    explicit_create = any(token in normalized_task.lower() for token in create_terms)
    explicit_update = any(token in normalized_task.lower() for token in update_terms)
    explicit_summary = any(token in normalized_task.lower() for token in summary_terms)
    has_attachment_hint = any(token in lowered for token in attachment_terms)

    if explicit_analysis and not explicit_import and not explicit_create and not explicit_update:
        if has_attachment_hint:
            items = [
                {"title": "确认分析目标与附加素材", "detail": "", "state": "pending"},
                {"title": "检查文件路径与上下文线索", "detail": "", "state": "pending"},
                {"title": "整理观察结论与下一步建议", "detail": "", "state": "pending"},
            ]
        else:
            items = [
                {"title": "确认分析范围", "detail": "", "state": "pending"},
                {"title": "读取问题上下文与关键对象", "detail": "", "state": "pending"},
                {"title": "整理关键结果与异常", "detail": "", "state": "pending"},
            ]
    elif explicit_import or any(token in lowered for token in ("音频", "wav", "素材", "source file", "audio file")):
        items = [
            {"title": "确认导入目标与素材来源", "detail": "", "state": "pending"},
            {"title": "检查路径映射与导入规则", "detail": "", "state": "pending"},
            {"title": "准备导入参数并验证结果", "detail": "", "state": "pending"},
        ]
    elif explicit_create:
        items = [
            {"title": "确认要创建的对象结构", "detail": "", "state": "pending"},
            {"title": "定位父节点与命名规则", "detail": "", "state": "pending"},
            {"title": "检查依赖与去重约束", "detail": "", "state": "pending"},
        ]
    elif explicit_update:
        items = [
            {"title": "定位待修改对象", "detail": "", "state": "pending"},
            {"title": "读取当前值与影响范围", "detail": "", "state": "pending"},
            {"title": "准备变更并校验回执", "detail": "", "state": "pending"},
        ]
    elif explicit_summary:
        items = [
            {"title": "提炼关键信息", "detail": "", "state": "pending"},
            {"title": "组织结构化结论", "detail": "", "state": "pending"},
            {"title": "生成最终回复", "detail": "", "state": "pending"},
        ]
    elif any(token in lowered for token in ("路径", "对象", "读取", "检索", "定位", "查询", "分析", "扫描", "列出", "结构", "层级", "project")):
        items = [
            {"title": "确认分析范围", "detail": "", "state": "pending"},
            {"title": "读取项目对象与层级", "detail": "", "state": "pending"},
            {"title": "整理关键结果与异常", "detail": "", "state": "pending"},
        ]
    elif any(token in lowered for token in ("总结", "回复", "输出", "报告", "整理", "explain", "summary", "result")):
        items = [
            {"title": "提炼关键信息", "detail": "", "state": "pending"},
            {"title": "组织结构化结论", "detail": "", "state": "pending"},
            {"title": "生成最终回复", "detail": "", "state": "pending"},
        ]
    else:
        items = [
            {"title": "理解当前任务目标", "detail": "", "state": "pending"},
            {"title": "整理执行上下文", "detail": "", "state": "pending"},
            {"title": "形成下一步方案", "detail": "", "state": "pending"},
        ]

    if task_summary and items:
        items[0]["detail"] = f"围绕任务: {task_summary}"
    return items


def _resolve_substeps_for_state(substeps, state: str, active_index: int = 0) -> list[dict[str, str]]:
    normalized = [_coerce_substep_item(item) for item in (substeps or [])]
    if not normalized:
        return []

    if state == "done":
        for item in normalized:
            item["state"] = "done"
            if not item["detail"]:
                item["detail"] = "已完成"
        return normalized

    if state == "failed":
        resolved_index = min(max(active_index, 0), len(normalized) - 1)
        for index, item in enumerate(normalized):
            if index < resolved_index:
                item["state"] = "done"
                if not item["detail"]:
                    item["detail"] = "已完成"
            elif index == resolved_index:
                item["state"] = "failed"
                if not item["detail"]:
                    item["detail"] = "执行受阻"
            else:
                item["state"] = "pending"
                if not item["detail"]:
                    item["detail"] = "等候中"
        return normalized

    resolved_index = min(max(active_index, 0), len(normalized) - 1)
    for index, item in enumerate(normalized):
        if index < resolved_index:
            item["state"] = "done"
            if not item["detail"]:
                item["detail"] = "已完成"
        elif index == resolved_index:
            item["state"] = "running"
            if not item["detail"]:
                item["detail"] = "进行中..."
        else:
            item["state"] = "pending"
            if not item["detail"]:
                item["detail"] = "等候中"
    return normalized


class _TimelineNodeWidget(QFrame):
    def __init__(self, index_text: str, title: str, theme_mode="light", parent=None):
        super().__init__(parent)
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        self.index_text = index_text
        self.state = "pending"
        self.timestamp_text = "--:--:--"
        self.substeps = []
        self.substeps_visible = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        rail_container = QWidget()
        rail_container.setFixedWidth(34)
        rail_container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        rail_layout = QVBoxLayout(rail_container)
        rail_layout.setContentsMargins(16, 0, 16, 0)
        rail_layout.setSpacing(0)

        self.line_top = QFrame()
        self.line_top.setFixedWidth(2)
        self.line_top.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        rail_layout.addWidget(self.line_top)

        self.badge = QLabel(index_text)
        self.badge.setFixedSize(26, 26)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rail_layout.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignCenter)

        self.line_bottom = QFrame()
        self.line_bottom.setFixedWidth(2)
        self.line_bottom.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        rail_layout.addWidget(self.line_bottom)

        layout.addWidget(rail_container)

        self.card = QFrame()
        self.card.setObjectName("timelineCard")
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(14)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        self.title_label = QLabel(_normalize_timeline_text(title))
        self.title_label.setWordWrap(True)
        text_layout.addWidget(self.title_label)

        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        self.detail_label.hide()
        text_layout.addWidget(self.detail_label)

        header_layout.addLayout(text_layout, 1)

        self.meta_container = QWidget()
        meta_layout = QHBoxLayout(self.meta_container)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(8)

        self.status_label = QLabel("•")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFixedWidth(16)
        meta_layout.addWidget(self.status_label)

        self.time_label = QLabel(self.timestamp_text)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        meta_layout.addWidget(self.time_label)

        header_layout.addWidget(self.meta_container, alignment=Qt.AlignmentFlag.AlignTop)
        card_layout.addLayout(header_layout)

        self.substeps_frame = QFrame()
        self.substeps_frame.setObjectName("timelineSubsteps")
        self.substeps_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.substeps_layout = QVBoxLayout(self.substeps_frame)
        self.substeps_layout.setContentsMargins(14, 12, 14, 12)
        self.substeps_layout.setSpacing(8)
        self.substeps_frame.hide()
        card_layout.addWidget(self.substeps_frame)

        layout.addWidget(self.card, 1)
        self.apply_theme(self.theme_mode)

    def set_index_text(self, text: str):
        self.index_text = text
        self.badge.setText(text)

    def set_title(self, text: str):
        self.title_label.setText(_normalize_timeline_text(text))
        self.title_label.setToolTip(_normalize_timeline_text(text))

    def set_detail(self, text: str = "", visible: bool = False):
        detail = (text or "").strip()
        self.detail_label.setText(detail)
        self.detail_label.setVisible(bool(visible and detail))

    def set_timestamp(self, text: str = ""):
        normalized = (text or "").strip() or "--:--:--"
        self.timestamp_text = normalized
        self.time_label.setText(normalized)

    def set_substeps(self, substeps=None, *, visible: bool = False):
        self.substeps = [_coerce_substep_item(item) for item in (substeps or [])]
        while self.substeps_layout.count():
            item = self.substeps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.substeps_visible = bool(visible and self.substeps)
        if not self.substeps_visible:
            self.substeps_frame.hide()
            self.substeps_frame.updateGeometry()
            self.card.adjustSize()
            self.adjustSize()
            self.updateGeometry()
            return

        palette = _execution_panel_palette(self.theme_mode)
        total = len(self.substeps)
        for index, substep in enumerate(self.substeps):
            # NOTE: Every child widget below is created with an explicit parent
            # so it never becomes a top-level window. Previously, calling
            # setVisible(True) on parentless QFrames (top_line / bottom_line)
            # before adding them to a layout caused them to flash as stray
            # top-level windows during every substep refresh — appearing as a
            # thin "scrollbar-like" popup floating over the chat.
            row = QWidget(self.substeps_frame)
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)

            rail = QWidget(row)
            rail.setFixedWidth(12)
            rail_layout = QVBoxLayout(rail)
            rail_layout.setContentsMargins(5, 0, 5, 0)
            rail_layout.setSpacing(0)

            top_line = QFrame(rail)
            top_line.setFixedWidth(2)
            top_line.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            top_line.setVisible(index > 0)
            rail_layout.addWidget(top_line)

            dot = QFrame(rail)
            dot.setFixedSize(8, 8)
            rail_layout.addWidget(dot, alignment=Qt.AlignmentFlag.AlignCenter)

            bottom_line = QFrame(rail)
            bottom_line.setFixedWidth(2)
            bottom_line.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            bottom_line.setVisible(index < total - 1)
            rail_layout.addWidget(bottom_line)

            row_layout.addWidget(rail)

            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(2)

            title_label = QLabel(substep["title"], row)
            title_label.setWordWrap(True)
            text_col.addWidget(title_label)

            detail = (substep.get("detail") or "").strip()
            if detail:
                detail_label = QLabel(detail, row)
                detail_label.setWordWrap(True)
                text_col.addWidget(detail_label)
            else:
                detail_label = None

            row_layout.addLayout(text_col, 1)
            self.substeps_layout.addWidget(row)

            state = substep["state"]
            line_color = palette["substep_running"] if state == "running" else palette["rail_idle"]
            dot_color = {
                "pending": palette["substep_pending"],
                "running": palette["substep_running"],
                "done": palette["substep_done"],
                "failed": palette["substep_failed"],
            }[state]
            title_color = palette["substep_title"] if state != "failed" else palette["title_failed"]
            detail_color = palette["substep_detail"] if state != "failed" else palette["detail_failed"]

            top_line.setStyleSheet(f"background-color: {line_color}; border-radius: 1px;")
            bottom_line.setStyleSheet(f"background-color: {line_color}; border-radius: 1px;")
            dot.setStyleSheet(f"background-color: {dot_color}; border-radius: 4px;")
            title_label.setStyleSheet(
                f"color: {title_color}; font-size: 12px; font-weight: 500; background: transparent; border: none;"
            )
            if detail_label is not None:
                detail_label.setStyleSheet(
                    f"color: {detail_color}; font-size: 11px; background: transparent; border: none;"
                )

        self.substeps_frame.show()
        self.substeps_frame.adjustSize()
        self.card.adjustSize()
        self.adjustSize()
        self.updateGeometry()

    def set_line_visibility(self, *, top: bool, bottom: bool):
        self.line_top.setVisible(top)
        self.line_bottom.setVisible(bottom)

    def set_state(self, state: str):
        self.state = state
        self.badge.setText(self.index_text)
        self.apply_theme(self.theme_mode)

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        palette = _execution_panel_palette(self.theme_mode)

        if self.state == "running":
            badge_bg = palette["badge_active_bg"]
            badge_border = palette["badge_active_border"]
            badge_text = palette["badge_active_text"]
            card_bg = palette["card_running_bg"]
            card_border = palette["card_running_border"]
            title_color = palette["title_active"]
            detail_color = palette["detail_active"]
            line_color = palette["rail_active"]
            status_color = palette["status_running"]
            status_text = "◌"
            time_color = palette["time_active"]
        elif self.state == "done":
            badge_bg = palette["badge_active_bg"]
            badge_border = palette["badge_active_border"]
            badge_text = palette["badge_active_text"]
            card_bg = palette["card_bg"]
            card_border = palette["card_border"]
            title_color = palette["title"]
            detail_color = palette["detail"]
            line_color = palette["rail_done"]
            status_color = palette["status_done"]
            status_text = "✓"
            time_color = palette["time_done"]
        elif self.state == "failed":
            badge_bg = palette["badge_failed_bg"]
            badge_border = palette["badge_failed_border"]
            badge_text = palette["badge_failed_text"]
            card_bg = palette["card_failed_bg"]
            card_border = palette["card_failed_border"]
            title_color = palette["title_failed"]
            detail_color = palette["detail_failed"]
            line_color = palette["rail_failed"]
            status_color = palette["status_failed"]
            status_text = "!"
            time_color = palette["time_failed"]
        else:
            badge_bg = palette["badge_pending_bg"]
            badge_border = palette["badge_pending_border"]
            badge_text = palette["badge_pending_text"]
            card_bg = palette["card_bg"]
            card_border = palette["card_border"]
            title_color = palette["title"]
            detail_color = palette["detail"]
            line_color = palette["rail_idle"]
            status_color = palette["status_pending"]
            status_text = "•"
            time_color = palette["time_pending"]

        self.setStyleSheet("QFrame { background: transparent; border: none; }")
        line_style = f"background-color: {line_color}; border-radius: 1px;"
        self.line_top.setStyleSheet(line_style)
        self.line_bottom.setStyleSheet(line_style)
        self.badge.setStyleSheet(
            f"background-color: {badge_bg};"
            f"border: 1px solid {badge_border};"
            f"color: {badge_text};"
            "border-radius: 13px; font-size: 12px; font-weight: 700;"
        )
        self.card.setStyleSheet(
            f"QFrame#timelineCard {{ background-color: {card_bg}; border: 1px solid {card_border}; border-radius: 18px; }}"
        )
        self.title_label.setStyleSheet(
            f"color: {title_color}; font-size: 14px; font-weight: 600; background: transparent; border: none;"
        )
        self.detail_label.setStyleSheet(
            f"color: {detail_color}; font-size: 12px; background: transparent; border: none;"
        )
        self.status_label.setText(status_text)
        self.status_label.setStyleSheet(
            f"color: {status_color}; font-size: 14px; font-weight: 700; background: transparent; border: none;"
        )
        self.time_label.setStyleSheet(
            f"color: {time_color}; font-size: 12px; background: transparent; border: none;"
        )
        self.substeps_frame.setStyleSheet(
            f"QFrame#timelineSubsteps {{ background-color: {palette['substeps_bg']}; border: 1px solid {palette['substeps_border']}; border-radius: 14px; }}"
        )
        self.set_substeps(self.substeps, visible=self.substeps_visible)


class StackedPageAnimator(QObject):
    def __init__(self, stack, parent=None):
        super().__init__(parent or stack)
        self.stack = stack
        self._group = None
        self._active_widget = None

    def animate_to(self, target_widget, direction="left"):
        if self.stack is None or target_widget is None:
            return
        current_widget = self.stack.currentWidget()
        if current_widget is target_widget:
            return

        if self._group is not None:
            self._group.stop()
            self._clear_effect(self._active_widget)
            self._group = None
            self._active_widget = None

        self.stack.setCurrentWidget(target_widget)
        target_widget.raise_()

        effect = QGraphicsOpacityEffect(target_widget)
        effect.setOpacity(0.0)
        target_widget.setGraphicsEffect(effect)

        fade_animation = QPropertyAnimation(effect, b"opacity", self)
        fade_animation.setDuration(220)
        fade_animation.setStartValue(0.0)
        fade_animation.setEndValue(1.0)
        fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(fade_animation)
        group.finished.connect(lambda widget=target_widget: self._finish(widget))
        self._group = group
        self._active_widget = target_widget
        group.start()

    def _finish(self, widget):
        if widget is not None:
            self._clear_effect(widget)
        self._group = None
        self._active_widget = None

    def _clear_effect(self, widget):
        if widget is None:
            return
        effect = widget.graphicsEffect()
        if effect is not None:
            try:
                widget.setGraphicsEffect(None)
            except RuntimeError:
                return


# ---------------------------------------------------------------------------
#  ThemedTextEdit
# ---------------------------------------------------------------------------

class ThemedTextEdit(QTextEdit):
    def __init__(self, parent=None, theme_mode="light"):
        super().__init__(parent)
        self.theme_mode = "dark" if theme_mode == "dark" else "light"

    def set_theme_mode(self, theme_mode: str):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        _apply_context_menu_theme(menu, self.theme_mode)
        menu.exec(event.globalPos())
        menu.deleteLater()


class MessageTextBrowser(QTextBrowser):
    def __init__(self, parent=None, theme_mode="light"):
        super().__init__(parent)
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)
        self.anchorClicked.connect(self._open_external_link)

    def set_theme_mode(self, theme_mode: str):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        _apply_context_menu_theme(menu, self.theme_mode)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def _open_external_link(self, url: QUrl):
        if url.scheme().lower() not in {"http", "https"}:
            return
        QDesktopServices.openUrl(url)


# ---------------------------------------------------------------------------
#  ConfirmationWidget
# ---------------------------------------------------------------------------

class ConfirmationWidget(QFrame):
    confirmed = pyqtSignal()
    revoked = pyqtSignal()

    def __init__(self, theme_mode="light", parent=None):
        super().__init__(parent)
        self.theme_mode = theme_mode

        layout = QVBoxLayout(self)
        
        info_layout = QHBoxLayout()
        self.label = QLabel("Operation executed. Please confirm or revoke.")
        info_layout.addWidget(self.label)
        layout.addLayout(info_layout)
        
        btn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("Confirm (Keep)")
        self.confirm_btn.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 4px; padding: 6px 12px;")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self.on_confirm)
        
        self.revoke_btn = QPushButton("Revoke (Undo)")
        self.revoke_btn.setStyleSheet("background-color: #F44336; color: white; border-radius: 4px; padding: 6px 12px;")
        self.revoke_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.revoke_btn.clicked.connect(self.on_revoke)
        
        btn_layout.addWidget(self.confirm_btn)
        btn_layout.addWidget(self.revoke_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.apply_theme(self.theme_mode)

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        if self.theme_mode == "dark":
            self.setStyleSheet(
                "QFrame { background-color: #2B2F35; border-radius: 12px; border: 1px solid #4A4F57; margin: 10px 60px; }"
                "QLabel { color: #FFD8A8; font-weight: bold; font-size: 14px; }"
            )
            self.confirm_btn.setStyleSheet("background-color: #2E7D32; color: white; border-radius: 4px; padding: 6px 12px;")
            self.revoke_btn.setStyleSheet("background-color: #B71C1C; color: white; border-radius: 4px; padding: 6px 12px;")
        else:
            self.setStyleSheet(
                "QFrame { background-color: #FFF3E0; border-radius: 12px; border: 1px solid #FFE0B2; margin: 10px 60px; }"
                "QLabel { color: #E65100; font-weight: bold; font-size: 14px; }"
            )
            self.confirm_btn.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 4px; padding: 6px 12px;")
            self.revoke_btn.setStyleSheet("background-color: #F44336; color: white; border-radius: 4px; padding: 6px 12px;")

    def on_confirm(self):
        if getattr(self, "_handled", False):
            return
        self._handled = True
        self.confirm_btn.setEnabled(False)
        self.revoke_btn.setEnabled(False)
        self.label.setText("Operation Confirmed.")
        self.confirm_btn.hide()
        self.revoke_btn.hide()
        self.confirmed.emit()

    def on_revoke(self):
        if getattr(self, "_handled", False):
            return
        self._handled = True
        self.confirm_btn.setEnabled(False)
        self.revoke_btn.setEnabled(False)
        self.label.setText("Operation Revoked.")
        self.confirm_btn.hide()
        self.revoke_btn.hide()
        self.revoked.emit()


# ---------------------------------------------------------------------------
#  FileWriteConfirmWidget
# ---------------------------------------------------------------------------

class FileWriteConfirmWidget(QFrame):
    """Confirmation widget shown before flushing deferred local file writes."""
    confirmed = pyqtSignal()
    revoked = pyqtSignal()

    def __init__(self, file_paths: list, theme_mode="light", parent=None):
        super().__init__(parent)
        self.theme_mode = theme_mode
        self.file_labels = []
        layout = QVBoxLayout(self)

        self.label = QLabel("📝 以下文件将被写入，请确认：")
        layout.addWidget(self.label)

        for path in file_paths:
            file_label = QLabel(f"  • {path}")
            file_label.setWordWrap(True)
            self.file_labels.append(file_label)
            layout.addWidget(file_label)

        btn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("✅ 确认写入")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self._on_confirm)

        self.revoke_btn = QPushButton("❌ 取消")
        self.revoke_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.revoke_btn.clicked.connect(self._on_revoke)

        btn_layout.addWidget(self.confirm_btn)
        btn_layout.addWidget(self.revoke_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.apply_theme(self.theme_mode)

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        if self.theme_mode == "dark":
            self.setStyleSheet(
                "QFrame { background-color: #2B2F35; border-radius: 12px; border: 1px solid #4A4F57; margin: 10px 60px; }"
                "QLabel { color: #FFD8A8; font-weight: bold; font-size: 14px; }"
            )
            self.confirm_btn.setStyleSheet("background-color: #2E7D32; color: white; border-radius: 4px; padding: 6px 12px;")
            self.revoke_btn.setStyleSheet("background-color: #B71C1C; color: white; border-radius: 4px; padding: 6px 12px;")
        else:
            self.setStyleSheet(
                "QFrame { background-color: #FFF3E0; border-radius: 12px; border: 1px solid #FFE0B2; margin: 10px 60px; }"
                "QLabel { color: #E65100; font-weight: bold; font-size: 14px; }"
            )
            self.confirm_btn.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 4px; padding: 6px 12px;")
            self.revoke_btn.setStyleSheet("background-color: #F44336; color: white; border-radius: 4px; padding: 6px 12px;")

        for file_label in self.file_labels:
            file_label.setStyleSheet("font-size: 13px; padding-left: 8px; background: transparent; border: none; font-weight: normal;")

    def _on_confirm(self):
        if getattr(self, "_handled", False):
            return
        self._handled = True
        self.confirm_btn.setEnabled(False)
        self.revoke_btn.setEnabled(False)
        self.label.setText("✅ 文件已写入。")
        self.confirm_btn.hide()
        self.revoke_btn.hide()
        self.confirmed.emit()

    def _on_revoke(self):
        if getattr(self, "_handled", False):
            return
        self._handled = True
        self.confirm_btn.setEnabled(False)
        self.revoke_btn.setEnabled(False)
        self.label.setText("❌ 文件写入已取消。")
        self.confirm_btn.hide()
        self.revoke_btn.hide()
        self.revoked.emit()


# ---------------------------------------------------------------------------
#  IntentClarifyWidget
# ---------------------------------------------------------------------------

class IntentClarifyWidget(QFrame):
    """当 LLM 无法确定用户意图时，展示候选意图供用户选择。"""
    intent_selected = pyqtSignal(str, str)  # (chosen_intent, optional_context)

    def __init__(self, options: list[str], theme_mode="light", parent=None):
        super().__init__(parent)
        self.theme_mode = theme_mode
        self.option_buttons: list[QPushButton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        hint = QLabel("请选择最符合的意图：")
        hint.setStyleSheet("font-weight: 600; font-size: 14px; background: transparent; border: none;")
        layout.addWidget(hint)
        self._hint_label = hint

        btn_layout = QVBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(6)
        for text in options:
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.toggled.connect(lambda checked, b=btn: self._on_option_toggled(checked, b))
            btn_layout.addWidget(btn)
            self.option_buttons.append(btn)
        layout.addLayout(btn_layout)

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("可选：补充上下文，或直接输入你的意图")
        self.note_input.textChanged.connect(self._update_confirm_state)
        layout.addWidget(self.note_input)

        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)
        self.confirm_btn = QPushButton("确认")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._confirm)
        action_layout.addWidget(self.confirm_btn)
        action_layout.addStretch()
        layout.addLayout(action_layout)

        self.apply_theme(self.theme_mode)

    # --- behaviour ---
    def _on_option_toggled(self, checked, btn):
        if checked:
            for b in self.option_buttons:
                if b is not btn:
                    b.setChecked(False)
        self._update_confirm_state()

    def _update_confirm_state(self, *_args):
        has_selection = any(b.isChecked() for b in self.option_buttons)
        has_text = bool(self.note_input.text().strip())
        self.confirm_btn.setEnabled(has_selection or has_text)

    def _confirm(self):
        if getattr(self, "_handled", False):
            return
        chosen = next((b.text() for b in self.option_buttons if b.isChecked()), None)
        note = self.note_input.text().strip()
        if chosen:
            # User selected an option button; note is supplementary context
            pass
        elif note:
            # No option selected but user typed free-form intent
            chosen = note
            note = ""
        else:
            return
        self._handled = True
        for b in self.option_buttons:
            b.setDisabled(True)
        self.note_input.setDisabled(True)
        self.confirm_btn.setDisabled(True)
        self.intent_selected.emit(chosen, note)

    # --- theming ---
    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        if self.theme_mode == "dark":
            self.setStyleSheet(
                "QFrame { background-color: #2B2F35; border-radius: 12px; border: 1px solid #4A4F57; margin: 10px 60px; }"
            )
            self._hint_label.setStyleSheet("color: #DCEBFF; font-weight: 600; font-size: 14px; background: transparent; border: none;")
            input_style = (
                "QLineEdit { background-color: #31353B; color: #E6E6E6; border-radius: 10px; padding: 8px 12px; border: 1px solid #4A4F57; }"
                "QLineEdit:focus { border-color: #6B7280; }"
                "QLineEdit:disabled { background-color: #262A2F; color: #7C828C; border-color: #353A42; }"
            )
            option_style = (
                "QPushButton { background-color: #31353B; color: #E6E6E6; border-radius: 10px; padding: 8px 14px; border: 1px solid #4A4F57; text-align: left; }"
                "QPushButton:hover { background-color: #3A3F46; border-color: #6B7280; }"
                "QPushButton:checked { background-color: #2F4E7A; border-color: #6EA8FF; color: #DCEBFF; }"
                "QPushButton:disabled { background-color: #262A2F; color: #7C828C; border-color: #353A42; }"
            )
            confirm_style = (
                "QPushButton { background-color: #2F6FED; color: #FFFFFF; border-radius: 10px; padding: 8px 14px; border: none; font-weight: 600; }"
                "QPushButton:hover { background-color: #3B7EFF; }"
                "QPushButton:disabled { background-color: #39404A; color: #8B949E; }"
            )
        else:
            self.setStyleSheet(
                "QFrame { background-color: #F8F9FA; border-radius: 12px; border: 1px solid #DADCE0; margin: 10px 60px; }"
            )
            self._hint_label.setStyleSheet("color: #1F1F1F; font-weight: 600; font-size: 14px; background: transparent; border: none;")
            input_style = (
                "QLineEdit { background-color: #FFFFFF; color: #1F1F1F; border-radius: 10px; padding: 8px 12px; border: 1px solid #DADCE0; }"
                "QLineEdit:focus { border-color: #AECBFA; }"
                "QLineEdit:disabled { background-color: #F1F3F4; color: #9AA0A6; border-color: #E0E0E0; }"
            )
            option_style = (
                "QPushButton { background-color: #FFFFFF; color: #1F1F1F; border-radius: 10px; padding: 8px 14px; border: 1px solid #DADCE0; text-align: left; }"
                "QPushButton:hover { background-color: #E8F0FE; border-color: #AECBFA; }"
                "QPushButton:checked { background-color: #E8F0FE; border-color: #1A73E8; color: #1967D2; }"
                "QPushButton:disabled { background-color: #F1F3F4; color: #9AA0A6; border-color: #E0E0E0; }"
            )
            confirm_style = (
                "QPushButton { background-color: #1A73E8; color: #FFFFFF; border-radius: 10px; padding: 8px 14px; border: none; font-weight: 600; }"
                "QPushButton:hover { background-color: #1765CC; }"
                "QPushButton:disabled { background-color: #DADCE0; color: #9AA0A6; }"
            )

        self.note_input.setStyleSheet(input_style)
        self.confirm_btn.setStyleSheet(confirm_style)
        for b in self.option_buttons:
            b.setStyleSheet(option_style)


# ---------------------------------------------------------------------------
#  StepProgressWidget
# ---------------------------------------------------------------------------

class StepProgressWidget(QFrame):
    """显示分步执行进度的小部件"""

    collapse_changed = pyqtSignal(bool)

    def __init__(self, total_steps, step_descriptions=None, theme_mode="light", parent=None):
        super().__init__(parent)
        self.setObjectName("executionBoard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        self.total_steps = 0
        self.step_descriptions = []
        self.step_items = []
        self._is_collapsed = False
        self._footer_visible = False

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 18, 20, 18)
        main_layout.setSpacing(12)
        self.main_layout = main_layout

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        self.header_icon = QLabel("✦")
        self.header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_icon.setFixedSize(24, 24)
        # Anchor icon to the top so it stays on the title line regardless of
        # how tall the two-line header text (title + meta) ends up rendering.
        header_row.addWidget(self.header_icon, alignment=Qt.AlignmentFlag.AlignTop)

        header_text_layout = QVBoxLayout()
        header_text_layout.setContentsMargins(0, 0, 0, 0)
        header_text_layout.setSpacing(2)

        self.title_label = QLabel("执行流程")
        self.meta_label = QLabel("")
        header_text_layout.addWidget(self.title_label)
        header_text_layout.addWidget(self.meta_label)
        header_row.addLayout(header_text_layout, 1)

        self.chevron_button = QPushButton("⌃")
        self.chevron_button.setFixedSize(24, 24)
        self.chevron_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chevron_button.setFlat(True)
        self.chevron_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chevron_button.clicked.connect(self._toggle_collapsed)
        header_row.addWidget(self.chevron_button, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        main_layout.addLayout(header_row)

        self.steps_container = QWidget()
        self.steps_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.steps_layout = QVBoxLayout(self.steps_container)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.setSpacing(10)
        main_layout.addWidget(self.steps_container)

        self.footer_frame = QFrame()
        self.footer_frame.setObjectName("timelineFooter")
        self.footer_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        footer_layout = QHBoxLayout(self.footer_frame)
        footer_layout.setContentsMargins(14, 12, 14, 12)
        footer_layout.setSpacing(10)
        self.footer_icon_label = QLabel("✓")
        self.footer_icon_label.setFixedWidth(18)
        footer_layout.addWidget(self.footer_icon_label)
        self.footer_label = QLabel("")
        footer_layout.addWidget(self.footer_label, 1)
        self.footer_time_label = QLabel("")
        footer_layout.addWidget(self.footer_time_label)
        self.footer_frame.hide()
        main_layout.addWidget(self.footer_frame)

        self.reset_flow(total_steps, step_descriptions)
        self.apply_theme(self.theme_mode)

    def _default_status_message(self):
        return f"待执行 {self.total_steps} 项"

    def _default_title(self):
        return "执行流程"

    def _hide_footer(self):
        self._footer_visible = False
        self.footer_label.clear()
        self.footer_time_label.clear()
        self.footer_frame.hide()
        self._refresh_geometry()

    def _refresh_geometry(self):
        self.steps_container.adjustSize()
        if self.footer_frame.isVisible():
            self.footer_frame.adjustSize()
        self.adjustSize()
        self.updateGeometry()

    @property
    def is_collapsed(self) -> bool:
        return self._is_collapsed

    def _sync_collapsed_state(self):
        self.chevron_button.setText("⌄" if self._is_collapsed else "⌃")
        self.steps_container.setVisible(not self._is_collapsed)
        self.footer_frame.setVisible(self._footer_visible and not self._is_collapsed)
        self._refresh_geometry()

    def set_collapsed(self, collapsed: bool, *, emit_signal: bool = True):
        collapsed = bool(collapsed)
        if self._is_collapsed == collapsed:
            self._sync_collapsed_state()
            return
        self._is_collapsed = collapsed
        self._sync_collapsed_state()
        if emit_signal:
            self.collapse_changed.emit(self._is_collapsed)

    def _toggle_collapsed(self):
        self.set_collapsed(not self._is_collapsed)

    def _clear_steps(self):
        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.step_items = []

    def reset_flow(self, total_steps, step_descriptions=None, status_text=None):
        self.total_steps = max(int(total_steps or 0), 0)
        provided = list(step_descriptions or [])
        self.title_label.setText(self._default_title())
        self.step_descriptions = [
            provided[i] if i < len(provided) and str(provided[i]).strip() else f"执行操作 {i+1}"
            for i in range(self.total_steps)
        ]

        self._hide_footer()
        self._clear_steps()
        for i in range(self.total_steps):
            desc = self.step_descriptions[i]
            node = _TimelineNodeWidget(str(i + 1), desc, theme_mode=self.theme_mode)
            node.set_state("pending")
            node.set_timestamp("--:--:--")
            node.set_line_visibility(top=i > 0, bottom=i < self.total_steps - 1)
            self.step_items.append({
                'node': node,
                'description': desc,
                'state': 'pending',
                'detail': '',
                'detail_visible': False,
                'timestamp': '--:--:--',
                'substeps': [],
                'substeps_visible': False,
                'active_substep_index': 0,
            })
            self.steps_layout.addWidget(node)

        self.set_status_message(status_text or self._default_status_message())
        # Avoid calling self.show() here: when this widget has no parent yet
        # (e.g. during construction or history snapshot restore before being
        # added to a layout), show() promotes it to a top-level window which
        # appears as a stray "Python" popup. Visibility is handled by the
        # parent layout once the widget is added, or explicitly by callers
        # that reuse an existing widget.
        if self.parent() is not None:
            self.show()
        self.apply_theme(self.theme_mode)

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        palette = _execution_panel_palette(self.theme_mode)

        self.setStyleSheet(
            f"QFrame#executionBoard {{ background-color: {palette['panel_bg']}; border-radius: 22px; border: 1px solid {palette['panel_border']}; margin: 10px 60px; }}"
            f"QFrame#timelineFooter {{ background-color: {palette['footer_success_bg']}; border: 1px solid {palette['footer_success_border']}; border-radius: 16px; }}"
        )
        self.header_icon.setStyleSheet(
            f"background-color: {palette['header_icon_bg']}; color: {palette['header_icon_text']}; border-radius: 12px; font-size: 12px; font-weight: 700;"
        )
        self.title_label.setStyleSheet(
            f"font-weight: 700; font-size: 16px; color: {palette['panel_title']}; border: none; background: transparent;")
        self.meta_label.setStyleSheet(
            f"font-size: 12px; color: {palette['panel_meta']}; border: none; background: transparent;")
        self.chevron_button.setStyleSheet(
            "QPushButton {"
            f"font-size: 14px; color: {palette['chevron']}; border: none; background: transparent;"
            "}"
            "QPushButton:hover {"
            f"color: {palette['panel_title']};"
            "}"
        )
        self.footer_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {palette['footer_success_text']}; border: none; background: transparent;"
        )
        self.footer_time_label.setStyleSheet(
            f"font-size: 12px; color: {palette['panel_meta']}; border: none; background: transparent;"
        )

        for item in self.step_items:
            item['node'].apply_theme(self.theme_mode)
            self._apply_step_state_style(item, item['state'])
        self._refresh_geometry()

    def _apply_step_state_style(self, item, state):
        node = item['node']
        node.set_title(item['description'])
        node.set_state(state)
        node.set_detail(item.get('detail', ''), item.get('detail_visible', False))
        node.set_timestamp(item.get('timestamp', '--:--:--'))
        node.set_substeps(item.get('substeps') or [], visible=item.get('substeps_visible', False))
        node.adjustSize()
        node.updateGeometry()
        self._refresh_geometry()

    def set_title_text(self, text):
        self.title_label.setText((text or self._default_title()).strip())

    def set_status_message(self, text):
        self.meta_label.setText((text or self._default_status_message()).strip())

    def _final_title_for_status(self, text: str) -> str:
        status = (text or "").strip()
        if "失败" in status:
            return "AudioMate 执行失败"
        if "中断" in status or "受阻" in status:
            return "AudioMate 执行中断"
        return "AudioMate 执行完成"

    def mark_finished(self, text="全部步骤已完成"):
        self.set_status_message(text)
        interrupted = "中断" in text or "受阻" in text or "失败" in text
        self.set_title_text(self._final_title_for_status(text))
        self._footer_visible = True
        palette = _execution_panel_palette(self.theme_mode)
        if interrupted:
            self.footer_frame.setStyleSheet(
                f"QFrame#timelineFooter {{ background-color: {palette['footer_error_bg']}; border: 1px solid {palette['footer_error_border']}; border-radius: 16px; }}"
            )
            self.footer_icon_label.setText("!")
            self.footer_icon_label.setStyleSheet(
                f"font-size: 14px; font-weight: 700; color: {palette['footer_error_icon']}; border: none; background: transparent;"
            )
            self.footer_label.setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {palette['footer_error_text']}; border: none; background: transparent;"
            )
        else:
            self.footer_frame.setStyleSheet(
                f"QFrame#timelineFooter {{ background-color: {palette['footer_success_bg']}; border: 1px solid {palette['footer_success_border']}; border-radius: 16px; }}"
            )
            self.footer_icon_label.setText("✓")
            self.footer_icon_label.setStyleSheet(
                f"font-size: 14px; font-weight: 700; color: {palette['footer_success_icon']}; border: none; background: transparent;"
            )
            self.footer_label.setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {palette['footer_success_text']}; border: none; background: transparent;"
            )
        self.footer_label.setText(text)
        self.footer_time_label.setText(_current_timeline_timestamp())
        self._sync_collapsed_state()

    def set_step_detail(self, index, detail="", visible=True):
        if 0 <= index < self.total_steps:
            self.step_items[index]['detail'] = (detail or '').strip()
            self.step_items[index]['detail_visible'] = bool(visible and self.step_items[index]['detail'])
            self._apply_step_state_style(self.step_items[index], self.step_items[index]['state'])

    def set_step_substeps(self, index, substeps=None, *, active_index: int = 0, visible: bool = True):
        if 0 <= index < self.total_steps:
            resolved = _resolve_substeps_for_state(
                substeps or _default_substeps_for_activity(self.step_items[index]['description']),
                self.step_items[index]['state'],
                active_index,
            )
            self.step_items[index]['substeps'] = resolved
            self.step_items[index]['substeps_visible'] = bool(visible and resolved)
            self.step_items[index]['active_substep_index'] = active_index
            self._apply_step_state_style(self.step_items[index], self.step_items[index]['state'])

    def snapshot(self):
        return {
            'title': self.title_label.text(),
            'collapsed': self._is_collapsed,
            'status': self.meta_label.text(),
            'footer': {
                'visible': self._footer_visible,
                'text': self.footer_label.text(),
                'time': self.footer_time_label.text(),
                'kind': 'error' if self.footer_icon_label.text() == '!' else 'success',
            },
            'steps': [
                {
                    'description': item['description'],
                    'state': item['state'],
                    'detail': item.get('detail', ''),
                    'detail_visible': item.get('detail_visible', False),
                    'timestamp': item.get('timestamp', '--:--:--'),
                    'substeps': item.get('substeps', []),
                    'substeps_visible': item.get('substeps_visible', False),
                    'active_substep_index': item.get('active_substep_index', 0),
                }
                for item in self.step_items
            ],
        }

    def apply_snapshot(self, snapshot):
        snapshot = snapshot or {}
        steps = list(snapshot.get('steps') or [])
        descriptions = [str(step.get('description') or f"执行操作 {index + 1}") for index, step in enumerate(steps)]
        self.reset_flow(len(steps), descriptions, status_text=snapshot.get('status') or self._default_status_message())
        self.set_title_text(snapshot.get('title') or self._default_title())
        for index, step in enumerate(steps):
            state = str(step.get('state') or 'pending')
            detail = str(step.get('detail') or '')
            visible = bool(step.get('detail_visible', False))
            timestamp = str(step.get('timestamp') or '--:--:--')
            substeps = step.get('substeps') or []
            substeps_visible = bool(step.get('substeps_visible', False))
            active_substep_index = int(step.get('active_substep_index', 0) or 0)
            self.step_items[index]['state'] = state
            self.step_items[index]['detail'] = detail
            self.step_items[index]['detail_visible'] = visible and bool(detail)
            self.step_items[index]['timestamp'] = timestamp
            self.step_items[index]['substeps'] = [_coerce_substep_item(item) for item in substeps]
            self.step_items[index]['substeps_visible'] = substeps_visible and bool(substeps)
            self.step_items[index]['active_substep_index'] = active_substep_index
            self._apply_step_state_style(self.step_items[index], state)
        footer = snapshot.get('footer') or {}
        if footer.get('visible'):
            self.mark_finished(str(footer.get('text') or self.meta_label.text() or '执行完成'))
            self.footer_time_label.setText(str(footer.get('time') or _current_timeline_timestamp()))
            if footer.get('kind') == 'error':
                self.footer_icon_label.setText('!')
        else:
            self._hide_footer()
        self.set_collapsed(bool(snapshot.get('collapsed', False)), emit_signal=False)

    def set_current_step(self, index):
        """标记当前正在执行的步骤"""
        if 0 <= index < self.total_steps:
            for item in self.step_items:
                if item['state'] == 'running':
                    item['state'] = 'pending'
                    item['timestamp'] = '--:--:--'
                    item['substeps_visible'] = False
                    self._apply_step_state_style(item, 'pending')
            self.step_items[index]['state'] = 'running'
            self.step_items[index]['timestamp'] = _current_timeline_timestamp()
            default_substeps = self.step_items[index]['substeps'] or _default_substeps_for_activity(self.step_items[index]['description'])
            self.step_items[index]['substeps'] = _resolve_substeps_for_state(default_substeps, 'running', 0)
            self.step_items[index]['substeps_visible'] = True
            self.step_items[index]['active_substep_index'] = 0
            self._apply_step_state_style(self.step_items[index], 'running')
            self.set_status_message(f"执行中 {index + 1}/{self.total_steps} · {self.step_items[index]['description']}")

    def complete_step(self, index, output=""):
        """标记步骤完成并显示输出"""
        if 0 <= index < self.total_steps:
            self.step_items[index]['state'] = 'done'
            self.step_items[index]['timestamp'] = _current_timeline_timestamp()
            if self.step_items[index]['substeps']:
                self.step_items[index]['substeps'] = _resolve_substeps_for_state(
                    self.step_items[index]['substeps'],
                    'done',
                    self.step_items[index].get('active_substep_index', 0),
                )
            self.step_items[index]['substeps_visible'] = False
            self._apply_step_state_style(self.step_items[index], 'done')
            self.set_status_message(f"已完成 {index + 1}/{self.total_steps} · {self.step_items[index]['description']}")

    def fail_step(self, index, error=""):
        """标记步骤失败"""
        if 0 <= index < self.total_steps:
            self.step_items[index]['state'] = 'failed'
            self.step_items[index]['timestamp'] = _current_timeline_timestamp()
            default_substeps = self.step_items[index]['substeps'] or _default_substeps_for_activity(self.step_items[index]['description'])
            active_index = min(max(self.step_items[index].get('active_substep_index', 0), 0), max(len(default_substeps) - 1, 0))
            self.step_items[index]['substeps'] = _resolve_substeps_for_state(default_substeps, 'failed', active_index)
            self.step_items[index]['substeps_visible'] = bool(self.step_items[index]['substeps'])
            self._apply_step_state_style(self.step_items[index], 'failed')
            self.set_status_message(f"执行受阻 {index + 1}/{self.total_steps} · {self.step_items[index]['description']}")
            if error and error.strip():
                self.set_step_detail(index, f"⚠ {_summarize_timeline_error(error)}", visible=True)


# ---------------------------------------------------------------------------
#  ImagePreviewWidget
# ---------------------------------------------------------------------------

class ImagePreviewWidget(QFrame):
    """显示待发送图片的预览小部件"""
    remove_clicked = pyqtSignal(int)  # 发送要移除的图片索引
    
    def __init__(self, pixmap, index, theme_mode="light", parent=None):
        super().__init__(parent)
        self.index = index
        self.theme_mode = theme_mode
        self.setFixedSize(80, 80)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        
        # 图片预览
        self.image_label = ClickableImageLabel(pixmap)
        scaled = pixmap.scaled(68, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label)
        
        # 删除按钮
        self.remove_btn = QPushButton("×")
        self.remove_btn.setFixedSize(18, 18)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background-color: #E53935;
                color: white;
                border-radius: 9px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #C62828;
            }
        """)
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.index))
        
        # 将删除按钮放在右上角
        self.remove_btn.setParent(self)
        self.remove_btn.move(58, 2)
        self.remove_btn.raise_()
        self.apply_theme(self.theme_mode)

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        frame_bg = "#2B2F35" if self.theme_mode == "dark" else "#F0F4F9"
        frame_border = "#4A4F57" if self.theme_mode == "dark" else "#DADCE0"
        self.setStyleSheet(
            "QFrame {"
            f"background-color: {frame_bg};"
            "border-radius: 8px;"
            f"border: 1px solid {frame_border};"
            "}"
        )


# ---------------------------------------------------------------------------
#  FilePreviewWidget
# ---------------------------------------------------------------------------

class FilePreviewWidget(QFrame):
    """显示待发送文件或文件夹的预览小部件"""
    remove_clicked = pyqtSignal(int)

    def __init__(self, item, index, theme_mode="light", parent=None):
        super().__init__(parent)
        self.index = index
        self.theme_mode = theme_mode
        self.item = dict(item or {})
        self.setObjectName("filePreviewChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(232, 58)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 34, 10)
        layout.setSpacing(12)

        name = item.get("name") or item.get("path") or "附件"
        path = item.get("path") or ""
        secondary = _attachment_secondary_text(path, is_dir=bool(item.get("is_dir")))

        self.icon_label = QLabel()
        self.icon_label.setObjectName("filePreviewIcon")
        self.icon_label.setPixmap(_system_file_icon(path, is_dir=bool(item.get("is_dir"))).pixmap(28, 34))
        self.icon_label.setFixedSize(28, 34)
        self.setToolTip(path or name)
        layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.title_label = QLabel(name)
        self.title_label.setObjectName("filePreviewTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.meta_label = QLabel(secondary)
        self.meta_label.setObjectName("filePreviewMeta")
        self.meta_label.setWordWrap(False)
        self.meta_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.meta_label)
        layout.addLayout(text_layout, 1)

        self.remove_btn = QPushButton("×")
        self.remove_btn.setFixedSize(18, 18)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #98A2B3;
                border: none;
                border-radius: 9px;
                font-size: 18px;
                font-weight: 400;
            }
            QPushButton:hover {
                background: rgba(152, 162, 179, 0.10);
                color: #667085;
            }
        """)
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.index))
        self.remove_btn.setParent(self)
        self.remove_btn.move(204, 10)
        self.remove_btn.raise_()
        self.apply_theme(self.theme_mode)

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        frame_bg = "#232733" if self.theme_mode == "dark" else "#FFFFFF"
        frame_border = "#3C4352" if self.theme_mode == "dark" else "#E5E7EB"
        title_color = "#F3F4F6" if self.theme_mode == "dark" else "#101828"
        meta_color = "#98A2B3" if self.theme_mode == "dark" else "#667085"
        self.setStyleSheet(
            "QFrame#filePreviewChip {"
            f"background-color: {frame_bg};"
            "border-radius: 14px;"
            f"border: 1px solid {frame_border};"
            "}"
            "QLabel#filePreviewIcon { background-color: #F4F7FB; border-radius: 8px; padding: 2px; }"
            f"QLabel#filePreviewTitle {{ font-size: 12px; font-weight: 600; color: {title_color}; background: transparent; border: none; }}"
            f"QLabel#filePreviewMeta {{ font-size: 11px; font-weight: 500; color: {meta_color}; background: transparent; border: none; }}"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        text_width = max(64, self.width() - 92)
        metrics = QFontMetrics(self.title_label.font())
        self.title_label.setText(_elide_text_ascii(metrics, self.item.get("name") or self.item.get("path") or "附件", text_width))
        self.title_label.setFixedWidth(text_width)
        self.meta_label.setFixedWidth(text_width)
        self.remove_btn.move(self.width() - 28, 10)


# ---------------------------------------------------------------------------
#  ImageInputTextEdit
# ---------------------------------------------------------------------------

class ImageInputTextEdit(ThemedTextEdit):
    """支持图片粘贴和拖拽的文本输入框"""
    image_added = pyqtSignal(QImage)
    paths_added = pyqtSignal(list)
    returnPressed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
    
    def canInsertFromMimeData(self, source):
        if source.hasImage() or source.hasUrls():
            return True
        return super().canInsertFromMimeData(source)
    
    def insertFromMimeData(self, source):
        # 处理粘贴的图片
        if source.hasImage():
            image = QImage(source.imageData())
            if not image.isNull():
                self.image_added.emit(image)
                if not source.hasUrls():
                    return
        
        # 处理拖拽的文件
        if source.hasUrls():
            local_paths = []
            handled_image = False
            for url in source.urls():
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    if self._is_image_file(file_path):
                        image = QImage(file_path)
                        if not image.isNull():
                            self.image_added.emit(image)
                            handled_image = True
                            continue
                    local_paths.append(file_path)
            if local_paths:
                self.paths_added.emit(local_paths)
                return
            if handled_image:
                return
        
        # 默认处理文本
        super().insertFromMimeData(source)
    
    def _is_image_file(self, file_path):
        supported = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']
        return any(file_path.lower().endswith(ext) for ext in supported)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            event.accept()
            self.returnPressed.emit()
            return
        super().keyPressEvent(event)
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasImage() or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasImage() or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)
    
    def dropEvent(self, event):
        mime = event.mimeData()
        
        if mime.hasImage():
            image = QImage(mime.imageData())
            if not image.isNull():
                self.image_added.emit(image)
                event.acceptProposedAction()
                return
        
        if mime.hasUrls():
            local_paths = []
            handled_image = False
            for url in mime.urls():
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    if self._is_image_file(file_path):
                        image = QImage(file_path)
                        if not image.isNull():
                            self.image_added.emit(image)
                            handled_image = True
                            continue
                    local_paths.append(file_path)
            if local_paths:
                self.paths_added.emit(local_paths)
                event.acceptProposedAction()
                return
            if handled_image:
                event.acceptProposedAction()
                return
        
        super().dropEvent(event)


# ---------------------------------------------------------------------------
#  FeedbackQRDialog
# ---------------------------------------------------------------------------

class FeedbackQRDialog(QDialog):
    def __init__(
        self,
        qr_path,
        theme_mode="light",
        parent=None,
        title_text="扫码反馈",
        window_title="反馈",
        show_logs_button=True,
    ):
        super().__init__(parent)
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        self.show_logs_button = show_logs_button
        self.setWindowTitle(window_title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(title_text)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self.title_label = title

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setFixedSize(260, 260)
        layout.addWidget(self.qr_label)

        hint = QLabel("点击空白处或按 Esc 关闭")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        self.hint_label = hint

        self.open_logs_btn = QPushButton("打开日志目录")
        self.open_logs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_logs_btn.clicked.connect(self._open_logs_dir)
        if show_logs_button:
            layout.addWidget(self.open_logs_btn)
        else:
            self.open_logs_btn.hide()

        self._load_qr(qr_path)
        self.apply_theme(self.theme_mode)

    def _open_logs_dir(self):
        try:
            open_logs_dir()
        except LogDirectoryOpenError:
            QMessageBox.warning(
                self,
                "无法打开日志目录",
                f"系统未能自动打开日志目录，请手动查看：\n{get_logs_dir()}",
            )

    def _load_qr(self, qr_path):
        if qr_path and os.path.exists(qr_path):
            pixmap = QPixmap(qr_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    240,
                    240,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.qr_label.setPixmap(scaled)
                return
        self.qr_label.setText("二维码未配置")

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        if self.theme_mode == "dark":
            dialog_bg = "#1F2430"
            panel_bg = "#252B36"
            border = "#3D4655"
            title_color = "#F1F4FF"
            hint_color = "#AEB8CA"
            button_bg = "#303746"
            button_fg = "#F1F4FF"
            button_hover = "#3B4352"
        else:
            dialog_bg = "#F3F6FC"
            panel_bg = "#FFFFFF"
            border = "#DDE5F2"
            title_color = "#1F2A44"
            hint_color = "#667085"
            button_bg = "#EEF2FF"
            button_fg = "#3157E0"
            button_hover = "#E1E8FF"
        self.setStyleSheet(
            "QDialog {"
            f"background: {dialog_bg};"
            f"border: 1px solid {border};"
            "border-radius: 18px;"
            "}"
            "QLabel { background: transparent; border: none; }"
        )
        self.title_label.setStyleSheet(f"color: {title_color}; font-size: 16px; font-weight: 700;")
        self.hint_label.setStyleSheet(f"color: {hint_color}; font-size: 12px; font-weight: 500;")
        self.open_logs_btn.setStyleSheet(
            "QPushButton {"
            f"background: {button_bg}; color: {button_fg}; border: 1px solid {border};"
            "border-radius: 12px; padding: 9px 16px; font-size: 13px; font-weight: 600;"
            "}"
            f"QPushButton:hover {{ background: {button_hover}; }}"
        )
        self.qr_label.setStyleSheet(
            "QLabel {"
            f"background: {panel_bg};"
            f"border: 1px solid {border};"
            "border-radius: 12px;"
            f"color: {hint_color};"
            "font-size: 14px; font-weight: 600;"
            "}"
        )

    def mousePressEvent(self, event):
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if self.childAt(position) is None:
            self.close()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
#  ImageViewerDialog
# ---------------------------------------------------------------------------

class ImageViewerDialog(QDialog):
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Preview")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.showMaximized()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 获取屏幕尺寸并计算合适的缩放比例
        screen = QApplication.primaryScreen()
        if screen:
             screen_geometry = screen.availableGeometry()
             screen_size = screen_geometry.size()
             max_w = screen_size.width() * 0.95
             max_h = screen_size.height() * 0.95
             scaled_pixmap = pixmap.scaled(QSize(int(max_w), int(max_h)), 
                                         Qt.AspectRatioMode.KeepAspectRatio, 
                                         Qt.TransformationMode.SmoothTransformation)
             self.image_label.setPixmap(scaled_pixmap)
        else:
             self.image_label.setPixmap(pixmap)

        self.layout.addWidget(self.image_label)
        
        self.setStyleSheet("QDialog { background-color: rgba(0, 0, 0, 0.9); }")
        
    def mousePressEvent(self, event):
        self.close()
        
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
#  ClickableImageLabel
# ---------------------------------------------------------------------------

class ClickableImageLabel(QLabel):
    def __init__(self, original_pixmap, parent=None):
        super().__init__(parent)
        self.original_pixmap = original_pixmap
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Double-click to expand")
        
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            viewer = ImageViewerDialog(self.original_pixmap, self.window())
            viewer.exec()


# ---------------------------------------------------------------------------
#  AgentThinkingWidget
# ---------------------------------------------------------------------------

class AgentThinkingWidget(QFrame):
    """Timeline-style progress indicator for agent reasoning."""

    collapse_changed = pyqtSignal(bool)

    def __init__(self, theme_mode="light", task_context="", parent=None):
        super().__init__(parent)
        self.setObjectName("thinkingBoard")
        # Vertical policy must be Maximum (不超过 sizeHint)，否则第一次对话
        # 时聊天区只有少量消息，面板会被 QScrollArea 多余的垂直空间
        # 拉伸，造成 header / steps / footer 三区出现大片空白。
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        self._task_context = (task_context or "").strip()
        self._steps = []
        self._running_node = None
        self._running_text = ""
        self._running_display_text = ""
        self._finished = False
        self._is_collapsed = False
        self._footer_visible = False
        self._running_substeps_signature = ()
        self._typing_frame_index = 0
        self._typing_frames = [0, 1, 2, 1]
        self._typing_active_color = "#1A73E8"
        self._typing_idle_color = "#DADCE0"
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(240)
        self._typing_timer.timeout.connect(self._advance_typing_indicator)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 18, 20, 18)
        main_layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        self._header_icon = QLabel("💭")
        self._header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_icon.setFixedSize(24, 24)
        # Anchor icon to the top so it visually pairs with the title line and
        # does not float between the title and status text (which previously
        # produced a stacked "title / icon / status" misalignment, especially
        # noticeable with emoji icons whose glyph height is bigger than 24px).
        header_row.addWidget(self._header_icon, alignment=Qt.AlignmentFlag.AlignTop)

        header_text_layout = QVBoxLayout()
        header_text_layout.setContentsMargins(0, 0, 0, 0)
        header_text_layout.setSpacing(2)

        self._header = QLabel("AudioMate 思考中...")
        self._header_status = QLabel("准备中")
        header_text_layout.addWidget(self._header)
        header_text_layout.addWidget(self._header_status)
        header_row.addLayout(header_text_layout, 1)

        self._chevron_button = QPushButton("⌃")
        self._chevron_button.setFixedSize(24, 24)
        self._chevron_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron_button.setFlat(True)
        self._chevron_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chevron_button.clicked.connect(self._toggle_collapsed)
        header_row.addWidget(self._chevron_button, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        main_layout.addLayout(header_row)

        self._steps_container = QWidget()
        self._steps_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._steps_layout = QVBoxLayout(self._steps_container)
        self._steps_layout.setContentsMargins(0, 0, 0, 0)
        self._steps_layout.setSpacing(10)
        main_layout.addWidget(self._steps_container)

        self._footer_frame = QFrame()
        self._footer_frame.setObjectName("thinkingFooter")
        self._footer_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        footer_layout = QHBoxLayout(self._footer_frame)
        footer_layout.setContentsMargins(14, 12, 14, 12)
        footer_layout.setSpacing(10)
        self._footer_icon = QLabel("✓")
        footer_layout.addWidget(self._footer_icon)
        self._footer_label = QLabel("思考完成")
        footer_layout.addWidget(self._footer_label, 1)
        self._footer_time = QLabel("")
        footer_layout.addWidget(self._footer_time)
        self._footer_frame.hide()
        main_layout.addWidget(self._footer_frame)

        self._apply_theme()
        self._update_header()

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def is_collapsed(self) -> bool:
        return self._is_collapsed

    def _refresh_geometry(self):
        self._steps_container.adjustSize()
        if self._footer_frame.isVisible():
            self._footer_frame.adjustSize()
        self.adjustSize()
        self.updateGeometry()

    def _sync_collapsed_state(self):
        self._chevron_button.setText("⌄" if self._is_collapsed else "⌃")
        self._steps_container.setVisible(not self._is_collapsed)
        self._footer_frame.setVisible(self._footer_visible and not self._is_collapsed)
        self._refresh_geometry()

    def set_collapsed(self, collapsed: bool, *, emit_signal: bool = True):
        collapsed = bool(collapsed)
        if self._is_collapsed == collapsed:
            self._sync_collapsed_state()
            return
        self._is_collapsed = collapsed
        self._sync_collapsed_state()
        if emit_signal:
            self.collapse_changed.emit(self._is_collapsed)

    def _toggle_collapsed(self):
        self.set_collapsed(not self._is_collapsed)

    def _clear_steps(self):
        for item in self._steps:
            node = item.get("node")
            if node is not None:
                self._steps_layout.removeWidget(node)
                node.deleteLater()
        self._steps = []

    def _hide_footer(self):
        self._footer_visible = False
        self._footer_time.clear()
        self._footer_frame.hide()
        self._refresh_geometry()

    def set_task_context(self, task_context: str):
        self._task_context = (task_context or "").strip()
        if self._running_node is None:
            return
        if self._apply_running_payload(force=True):
            self._refresh_geometry()

    def _apply_running_payload(self, force: bool = False) -> bool:
        if self._running_node is None:
            return False
        display_text = _resolve_thinking_activity_title(self._running_text or self._running_display_text, self._task_context)
        resolved_substeps = _resolve_substeps_for_state(
            _default_substeps_for_activity(self._running_text or display_text, self._task_context),
            'running',
            0,
        )
        signature = tuple(
            (item.get('title', ''), item.get('detail', ''), item.get('state', 'pending'))
            for item in resolved_substeps
        )
        changed = False
        if force or self._running_display_text != display_text:
            self._running_display_text = display_text
            self._running_node.set_title(display_text)
            changed = True
        if force or self._running_substeps_signature != signature:
            self._running_substeps_signature = signature
            self._running_node.set_substeps(resolved_substeps, visible=True)
            changed = True
        return changed

    # --- public API ---

    def add_step(self, text: str):
        node = _TimelineNodeWidget(str(len(self._steps) + 1), text, theme_mode=self.theme_mode)
        node.set_state("done")
        node.set_timestamp(_current_timeline_timestamp())
        self._steps.append({"node": node, "text": text})
        self._steps_layout.addWidget(node)
        self._refresh_timeline_lines()
        self._update_header()
        self._refresh_geometry()

    def set_running(self, text: str):
        """Set or update the current in-progress node."""
        self._finished = False
        self._running_text = text
        self._running_display_text = _resolve_thinking_activity_title(text, self._task_context)
        # 若底层 QWidget 已被 Qt 销毁（C++ 对象失效），需要重建节点；否则
        # 任何对其属性/子控件的访问都会抛 RuntimeError。
        if self._running_node is not None:
            try:
                # 任意一次轻量级访问即可触发已销毁对象的 RuntimeError
                self._running_node.isVisible()
            except RuntimeError:
                self._running_node = None
        if self._running_node is None:
            self._running_node = _TimelineNodeWidget(str(len(self._steps) + 1), self._running_display_text, theme_mode=self.theme_mode)
            self._running_node.set_state("running")
            self._steps_layout.addWidget(self._running_node)
        else:
            self._running_node.set_index_text(str(len(self._steps) + 1))
            self._running_node.set_title(self._running_display_text)
            self._running_node.set_state("running")
        self._footer_visible = False
        self._footer_frame.hide()
        self._running_node.set_timestamp(_current_timeline_timestamp())
        content_changed = self._apply_running_payload(force=self._running_node is None)
        self._render_typing_indicator()
        self._steps_container.show()
        self._refresh_timeline_lines()
        self._typing_timer.stop()
        self._update_header()
        if content_changed:
            self._refresh_geometry()

    def clear_running(self, promote_completed: bool = False):
        self._typing_timer.stop()
        running_text = self._running_text
        display_text = self._running_display_text
        if self._running_node is not None:
            self._steps_layout.removeWidget(self._running_node)
            self._running_node.deleteLater()
            self._running_node = None
        self._running_text = ""
        self._running_display_text = ""
        self._running_substeps_signature = ()
        if promote_completed and running_text:
            self.add_step(display_text or running_text)
        self._refresh_timeline_lines()
        self._update_header()
        self._refresh_geometry()

    def finish(self):
        """Mark the timeline as finished while keeping it visible in chat."""
        if self._finished:
            return
        self._finished = True
        self.clear_running(promote_completed=False)
        self._footer_label.setText("思考完成")
        self._footer_time.setText(_current_timeline_timestamp())
        self._footer_visible = True
        self._update_header()
        self._sync_collapsed_state()

    def snapshot(self):
        return {
            'task_context': self._task_context,
            'collapsed': self._is_collapsed,
            'finished': self._finished,
            'footer': {
                'visible': self._footer_visible,
                'text': self._footer_label.text(),
                'time': self._footer_time.text(),
            },
            'steps': [
                {
                    'text': item.get('text') or item['node'].title_label.text(),
                    'timestamp': item['node'].timestamp_text,
                }
                for item in self._steps
            ],
            'running': {
                'text': self._running_text,
                'timestamp': self._running_node.timestamp_text if self._running_node is not None else '',
            } if self._running_node is not None else None,
        }

    def apply_snapshot(self, snapshot):
        snapshot = snapshot or {}
        self._typing_timer.stop()
        self._task_context = str(snapshot.get('task_context') or '')
        self._finished = False
        self._hide_footer()
        self._clear_steps()
        if self._running_node is not None:
            self._steps_layout.removeWidget(self._running_node)
            self._running_node.deleteLater()
            self._running_node = None
        self._running_text = ''
        self._running_display_text = ''

        for index, step in enumerate(snapshot.get('steps') or []):
            text = str(step.get('text') or f'步骤 {index + 1}')
            node = _TimelineNodeWidget(str(index + 1), text, theme_mode=self.theme_mode)
            node.set_state('done')
            node.set_timestamp(str(step.get('timestamp') or _current_timeline_timestamp()))
            self._steps.append({'node': node, 'text': text})
            self._steps_layout.addWidget(node)

        running = snapshot.get('running') or {}
        running_text = str(running.get('text') or '')
        if running_text and not bool(snapshot.get('finished', False)):
            self.set_running(running_text)
            if self._running_node is not None:
                self._running_node.set_timestamp(str(running.get('timestamp') or _current_timeline_timestamp()))

        self._finished = bool(snapshot.get('finished', False))
        footer = snapshot.get('footer') or {}
        if footer.get('visible'):
            self._footer_visible = True
            self._footer_label.setText(str(footer.get('text') or '思考完成'))
            self._footer_time.setText(str(footer.get('time') or _current_timeline_timestamp()))
        else:
            self._hide_footer()
        self._refresh_timeline_lines()
        self._update_header()
        self.set_collapsed(bool(snapshot.get('collapsed', False)), emit_signal=False)

    # --- internal rendering ---

    def _render_typing_indicator(self):
        if not self._running_node:
            return
        self._running_node.set_detail("处理中...", True)

    def _advance_typing_indicator(self):
        return

    def _update_header(self):
        self._header.setText("AudioMate 思考完成" if self._finished else "AudioMate 思考中...")
        if self._finished:
            status = "已完成"
        elif self._running_node is not None:
            status = "进行中"
        elif self._steps:
            status = "已记录"
        else:
            status = "准备中"
        self._header_status.setText(status)

    def _refresh_timeline_lines(self):
        nodes = [item["node"] for item in self._steps]
        if self._running_node is not None:
            nodes.append(self._running_node)
        for index, node in enumerate(nodes):
            node.set_line_visibility(top=index > 0, bottom=index < len(nodes) - 1)

    def _apply_theme(self):
        palette = _execution_panel_palette(self.theme_mode)
        self._typing_active_color = palette['status_running']
        self._typing_idle_color = palette['panel_muted']
        self.setStyleSheet(
            f"QFrame {{ background: transparent; }}"
            f"QFrame#thinkingBoard {{ background-color: {palette['panel_bg']}; border-radius: 22px; border: 1px solid {palette['panel_border']}; margin: 10px 60px; }}"
            f"QFrame#thinkingFooter {{ background-color: {palette['footer_success_bg']}; border: 1px solid {palette['footer_success_border']}; border-radius: 16px; }}"
        )
        self._header_icon.setStyleSheet(
            f"background-color: {palette['header_icon_bg']}; color: {palette['header_icon_text']}; border-radius: 12px; font-size: 12px; font-weight: 700;"
        )
        self._header.setStyleSheet(
            f"color: {palette['panel_title']}; font-size: 16px; font-weight: 700; background: transparent; border: none;"
        )
        self._header_status.setStyleSheet(
            f"color: {palette['panel_meta']}; font-size: 12px; background: transparent; border: none;"
        )
        self._chevron_button.setStyleSheet(
            "QPushButton {"
            f"font-size: 14px; color: {palette['chevron']}; background: transparent; border: none;"
            "}"
            "QPushButton:hover {"
            f"color: {palette['panel_title']};"
            "}"
        )
        self._footer_icon.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {palette['footer_success_icon']}; border: none; background: transparent;"
        )
        self._footer_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {palette['footer_success_text']}; border: none; background: transparent;"
        )
        self._footer_time.setStyleSheet(
            f"font-size: 12px; color: {palette['panel_meta']}; border: none; background: transparent;"
        )
        for item in self._steps:
            item["node"].apply_theme(self.theme_mode)
        if self._running_node:
            self._running_node.apply_theme(self.theme_mode)
            self._render_typing_indicator()
        self._update_header()
        self._sync_collapsed_state()

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        self._apply_theme()
        self._refresh_timeline_lines()


# ---------------------------------------------------------------------------
#  MessageBubble
# ---------------------------------------------------------------------------

class MessageBubble(QFrame):
    edit_confirmed = pyqtSignal(str)

    def __init__(self, role, text="", images=None, files=None, theme_mode="light", parent=None):
        super().__init__(parent)
        self.role = role
        self.theme_mode = theme_mode
        self.images = images or []  # List of QImage objects
        self.files = files or []
        self._typing_frame_index = 0
        self._typing_frames = [0, 1, 2, 1]
        self._typing_active_color = "#1A73E8"
        self._typing_idle_color = "#DADCE0"
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(240)
        self._typing_timer.timeout.connect(self._advance_typing_indicator)
        self.message_text = extract_text_from_content(text)
        attachment_images, attachment_files = _split_attachment_files_for_display(self.files)
        text_images = []
        for image_path in _extract_local_image_paths_from_text(self.message_text):
            image = QImage(image_path)
            if not image.isNull():
                text_images.append(image)

        self.display_images = [*self.images, *attachment_images, *text_images]
        self.display_files = attachment_files
        self.has_attachments = bool(self.display_images or self.display_files)
        self.images_height = 0  # 图片区域高度
        self.files_height = 0
        self.image_labels = []
        self.image_pixmaps = []
        self.file_widgets = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(38, 8, 38, 8)
        layout.setSpacing(14)
        
        self.content_container = QWidget()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)

        # 图片显示区域 (在文本之前)
        if self.display_images:
            self.images_container = QWidget()
            images_layout = QHBoxLayout(self.images_container)
            images_layout.setContentsMargins(0, 0, 0, 8)
            images_layout.setSpacing(8)
            self.images_layout = images_layout
            
            for img in self.display_images:
                pixmap = QPixmap.fromImage(img)
                img_label = ClickableImageLabel(pixmap)
                img_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                img_label.setStyleSheet("border-radius: 8px;")
                images_layout.addWidget(img_label)
                self.image_labels.append(img_label)
                self.image_pixmaps.append(pixmap)
            
            images_layout.addStretch()
            self.content_layout.addWidget(self.images_container)

        if self.display_files:
            self.files_container = QWidget()
            files_layout = QVBoxLayout(self.files_container)
            files_layout.setContentsMargins(0, 0, 0, 8)
            files_layout.setSpacing(6)
            for item in self.display_files:
                file_widget = MessageFileWidget(item)
                files_layout.addWidget(file_widget)
                self.file_widgets.append(file_widget)
            self.content_layout.addWidget(self.files_container)

        # 消息文本
        self.typing_indicator = QLabel()
        self.typing_indicator.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
        self.typing_indicator.hide()
        self.content_layout.addWidget(self.typing_indicator)

        self.content = MessageTextBrowser(theme_mode=self.theme_mode)
        self.content.setFrameStyle(QFrame.Shape.NoFrame)
        self.content.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content.setStyleSheet("background: transparent; font-size: 16px; line-height: 1.5;")
        
        self._render_message_text()
        self.content.document().contentsChanged.connect(self.adjust_height)
        self.content_layout.addWidget(self.content)

        if role == "user":
            # 用户：浅灰色气泡，靠右
            layout.addStretch()
            layout.addWidget(self.content_container, 4)
        else:
            # Assistant: 无背景
            self.avatar = QLabel("")
            self.avatar.setFixedSize(32, 32)
            self.avatar.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            self.avatar.setStyleSheet("font-size: 26px; font-weight: bold; margin-top: 2px;")
            
            layout.addWidget(self.avatar, alignment=Qt.AlignmentFlag.AlignTop)
            layout.addWidget(self.content_container, 9)
            layout.addStretch()

        # 编辑模式 UI
        self.edit_widget = QWidget()
        self.edit_widget.hide()
        edit_layout = QVBoxLayout(self.edit_widget)
        self.edit_input = ThemedTextEdit(theme_mode=self.theme_mode)
        self.edit_input.setStyleSheet("border-radius: 12px; padding: 10px;")
        self.edit_input.setFixedHeight(120)
        edit_layout.addWidget(self.edit_input)
        
        ebtn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("Update")
        self.confirm_btn.setStyleSheet("background-color: #1a73e8; color: white; border-radius: 18px; padding: 6px 16px;")
        self.confirm_btn.clicked.connect(self.confirm_edit)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet("background-color: transparent; border-radius: 18px;")
        self.cancel_btn.clicked.connect(self.cancel_edit)
        ebtn_layout.addWidget(self.confirm_btn)
        ebtn_layout.addWidget(self.cancel_btn)
        ebtn_layout.addStretch()
        edit_layout.addLayout(ebtn_layout)
        self.content_layout.addWidget(self.edit_widget)

        # 悬浮编辑按钮 (仅限用户消息)
        if role == "user":
            self.float_edit_btn = QPushButton("✎")
            self.float_edit_btn.setFixedSize(28, 28)
            self.float_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.float_edit_btn.setStyleSheet("QPushButton { border-radius: 14px; font-size: 14px; }")
            self.float_edit_btn.hide()
            self.float_edit_btn.clicked.connect(self.enter_edit_mode)
            layout.insertWidget(0, self.float_edit_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.apply_theme(self.theme_mode)
        self._set_typing_visible(self.role == "assistant" and not self.message_text.strip())
        self._sync_content_visibility()
        QTimer.singleShot(0, self.adjust_height)

    def _sync_content_visibility(self):
        if not hasattr(self, "content"):
            return
        should_show_content = bool((self.message_text or "").strip())
        if self.role == "assistant" and self.typing_indicator.isVisible():
            should_show_content = False
        self.content.setVisible(should_show_content)

    def _available_container_width(self):
        layout = self.layout()
        if layout is None:
            return 360

        margins = layout.contentsMargins()
        bubble_width = self.width() if self.width() > 0 else 760
        available = bubble_width - margins.left() - margins.right()
        if self.role != "user":
            available -= 32 + layout.spacing() + 12
        return max(220, available)

    def _attachment_content_width(self):
        inner_padding = 44
        return max(180, self._available_container_width() - inner_padding)

    def _update_image_sizes(self):
        if not hasattr(self, "images_container") or not self.image_labels:
            self.images_height = 0
            return

        available_width = self._attachment_content_width()
        spacing = self.images_layout.spacing()
        image_count = max(1, len(self.image_labels))
        max_width = min(360, max(112, (available_width - spacing * (image_count - 1)) // image_count))
        max_height = 260 if image_count == 1 else 180
        max_img_height = 0

        self.images_container.setMaximumWidth(available_width)
        for img_label, pixmap in zip(self.image_labels, self.image_pixmaps):
            scaled = pixmap.scaled(
                max_width,
                max_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            img_label.setPixmap(scaled)
            img_label.setFixedSize(scaled.size())
            max_img_height = max(max_img_height, scaled.height())

        self.images_height = max_img_height + 16 if max_img_height else 0

    def _update_file_widths(self):
        if not hasattr(self, "files_container") or not self.file_widgets:
            self.files_height = 0
            return

        available_width = self._attachment_content_width()
        card_width = min(420, available_width)
        self.files_container.setMaximumWidth(available_width)
        for file_widget in self.file_widgets:
            file_widget.setFixedWidth(card_width)
            file_widget.recompute_layout(card_width)
            file_widget.updateGeometry()
        self.files_container.updateGeometry()
        self.files_container.adjustSize()
        self.files_height = self._measure_files_height()

    def _update_attachment_layout(self):
        self.content_container.setMaximumWidth(self._available_container_width())
        self._update_image_sizes()
        self._update_file_widths()

    def _measure_files_height(self):
        if not hasattr(self, "files_container"):
            return 0
        self.files_container.updateGeometry()
        self.files_container.adjustSize()
        return max(
            self.files_container.sizeHint().height(),
            self.files_container.minimumSizeHint().height(),
        )

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"

        text_color = "#E6E6E6" if self.theme_mode == "dark" else "#1F1F1F"
        user_bg = "#2B2F35" if self.theme_mode == "dark" else "#F0F4F9"
        avatar_color = "#8AB4F8" if self.theme_mode == "dark" else "#4285F4"
        self._typing_active_color = "#8AB4F8" if self.theme_mode == "dark" else "#202124"
        self._typing_idle_color = "#5F6368" if self.theme_mode == "dark" else "#DADCE0"
        edit_bg = "#2B2F35" if self.theme_mode == "dark" else "white"
        edit_border = "#4A4F57" if self.theme_mode == "dark" else "#DADCE0"
        cancel_color = "#C9CDD4" if self.theme_mode == "dark" else "#5f6368"
        float_text = "#D0D3D8" if self.theme_mode == "dark" else "#444746"
        float_bg = "#31353B" if self.theme_mode == "dark" else "#E0E4E9"
        float_hover_bg = "#3A3F46" if self.theme_mode == "dark" else "#D2E3FC"

        self.content.setStyleSheet(
            f"background: transparent; color: {text_color}; font-size: 16px; line-height: 1.5;")
        self.typing_indicator.setStyleSheet(
            f"background: transparent; border: none; padding: 0; margin: 0; color: {self._typing_active_color}; font-size: 16px;")
        self._render_typing_indicator()

        if self.role == "user":
            self.content_container.setStyleSheet(
                f"background-color: {user_bg}; border-radius: 22px; padding: 14px 20px;")
            if hasattr(self, "float_edit_btn"):
                self.float_edit_btn.setStyleSheet(
                    "QPushButton {"
                    f"background: {float_bg}; color: {float_text}; border-radius: 14px; font-size: 14px;"
                    "}"
                    f"QPushButton:hover {{ background: {float_hover_bg}; }}"
                )
        elif hasattr(self, "avatar"):
            self.avatar.setStyleSheet(
                f"color: {avatar_color}; font-size: 26px; font-weight: bold; margin-top: 2px;")

        if hasattr(self, "files_container"):
            files_layout = self.files_container.layout()
            for index in range(files_layout.count()):
                file_widget = files_layout.itemAt(index).widget()
                if isinstance(file_widget, MessageFileWidget):
                    file_widget.apply_theme(self.theme_mode)

        self.edit_input.setStyleSheet(
            f"background: {edit_bg}; border: 1px solid {edit_border}; border-radius: 12px; padding: 10px; color: {text_color};")
        self.content.set_theme_mode(self.theme_mode)
        self.edit_input.set_theme_mode(self.theme_mode)
        self.cancel_btn.setStyleSheet(
            f"background-color: transparent; color: {cancel_color}; border-radius: 18px;")

    def enterEvent(self, event):
        if self.role == "user" and self.edit_widget.isHidden() and hasattr(self, "float_edit_btn"):
            self.float_edit_btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if hasattr(self, 'float_edit_btn'):
            self.float_edit_btn.hide()
        super().leaveEvent(event)

    def adjust_height(self):
        self._update_attachment_layout()
        self.files_height = self._measure_files_height()
        if self.edit_widget.isVisible():
            self.setFixedHeight(200 + self.images_height + self.files_height)
        else:
            if self.typing_indicator.isVisible():
                indicator_height = max(24, self.typing_indicator.sizeHint().height())
                total_height = int(indicator_height + 36 + self.images_height + self.files_height)
                self.setFixedHeight(total_height)
                return
            doc_height = 0
            if self.content.isVisible():
                width = self.content.viewport().width()
                if width > 0:
                    self.content.document().setTextWidth(width)
                doc_height = self.content.document().size().height()
                self.content.setFixedHeight(int(doc_height + 18))
            else:
                self.content.setFixedHeight(0)
            total_height = int(doc_height + 52 + self.images_height + self.files_height)
            self.setFixedHeight(total_height)

    def _render_message_text(self):
        if not self.message_text:
            self.content.clear()
            return
        # User-typed messages render as plain text — Markdown delimiters in
        # user input (e.g. ``Play_Music_*Win*`` event names, hash-prefixed
        # tags, backticks) must not be reinterpreted as formatting.
        if self.role == "user":
            self.content.setPlainText(self.message_text)
        else:
            self.content.setMarkdown(
                _strip_code_fence_language(_linkify_http_urls(self.message_text))
            )

    def set_text(self, text):
        self.message_text = extract_text_from_content(text)
        self._set_typing_visible(self.role == "assistant" and not self.message_text.strip())
        self._render_message_text()
        self._sync_content_visibility()
        self.adjust_height()

    def _render_typing_indicator(self):
        if not hasattr(self, "typing_indicator"):
            return
        active_index = self._typing_frames[self._typing_frame_index % len(self._typing_frames)]
        dots = []
        for index in range(3):
            color = self._typing_active_color if index <= active_index else self._typing_idle_color
            dots.append(f"<span style='color:{color}; font-size:18px;'>●</span>")
        self.typing_indicator.setText("&nbsp;".join(dots))

    def _advance_typing_indicator(self):
        self._typing_frame_index = (self._typing_frame_index + 1) % len(self._typing_frames)
        self._render_typing_indicator()

    def _set_typing_visible(self, visible: bool):
        if self.role != "assistant":
            return
        should_show = bool(visible)
        self.typing_indicator.setVisible(should_show)
        self._sync_content_visibility()
        if should_show:
            self._typing_frame_index = 0
            self._render_typing_indicator()
            if not self._typing_timer.isActive():
                self._typing_timer.start()
        else:
            self._typing_timer.stop()

    def enter_edit_mode(self):
        self.content.hide()
        if hasattr(self, "float_edit_btn"):
            self.float_edit_btn.hide()
        self.edit_input.setPlainText(self.message_text)
        self.edit_widget.show()
        self.adjust_height()

    def cancel_edit(self):
        self.edit_widget.hide()
        self._sync_content_visibility()
        self.adjust_height()

    def confirm_edit(self):
        self.edit_confirmed.emit(self.edit_input.toPlainText())

    def resizeEvent(self, event):
        self.adjust_height()
        super().resizeEvent(event)


# ---------------------------------------------------------------------------
#  HistoryItemWidget
# ---------------------------------------------------------------------------

class HistoryItemWidget(QWidget):
    delete_requested = pyqtSignal(str)

    def __init__(self, chat_id, title, theme_mode="light", active=False, status_text="", parent=None):
        super().__init__(parent)
        self.chat_id = chat_id
        self.theme_mode = theme_mode
        self.active = bool(active)
        self.status_text = status_text or ""
        self.hovered = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.card = QFrame()
        self.card.setObjectName("historyCard")
        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(16, 12, 10, 12)
        card_layout.setSpacing(10)
        
        title = extract_text_from_content(title, default="New Chat")
        
        self.label = QLabel(title)
        self.label.setWordWrap(True)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.status_label = QLabel(self.status_text)
        self.status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.status_label.setVisible(bool(self.status_text))
        
        self.delete_btn = QPushButton("×")
        self.delete_btn.setFixedSize(22, 22)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.hide()
        self.delete_btn.clicked.connect(self.on_delete)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(self.label)
        text_layout.addWidget(self.status_label)
        card_layout.addLayout(text_layout, 1)
        card_layout.addWidget(self.delete_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.card)
        
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        self.apply_theme(self.theme_mode)

    def sizeHint(self):
        return QSize(224, 72)

    def set_active(self, active: bool):
        self.active = bool(active)
        self.apply_theme(self.theme_mode)

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        is_dark = self.theme_mode == "dark"
        if self.active:
            card_bg = "#2F4E7A" if is_dark else "#E8F0FE"
            border = "#4D78B0" if is_dark else "#B6CCFF"
            title_color = "#F3F7FF" if is_dark else "#1F4FD6"
        elif self.hovered:
            card_bg = "#2A2E35" if is_dark else "#F5F7FF"
            border = "#4A4F57" if is_dark else "#D9E2FF"
            title_color = "#E6EAF2" if is_dark else "#2D3340"
        else:
            card_bg = "#23262B" if is_dark else "#FFFFFF"
            border = "#343942" if is_dark else "#E6EBF5"
            title_color = "#D0D3D8" if is_dark else "#444746"

        delete_bg = "#3A2227" if is_dark else "#FFF1F1"
        delete_fg = "#FFB2B2" if is_dark else "#D14343"
        delete_hover = "#4A292F" if is_dark else "#FFDCDC"
        self.card.setStyleSheet(
            f"QFrame#historyCard {{ background: {card_bg}; border: 1px solid {border}; border-radius: 16px; }}"
        )
        self.label.setStyleSheet(
            f"background: transparent; border: none; color: {title_color}; font-size: 13px; line-height: 1.35; font-weight: 500;"
        )
        status_color = "#9BB8FF" if is_dark else "#4263EB"
        self.status_label.setStyleSheet(
            f"background: transparent; border: none; color: {status_color}; font-size: 11px; font-weight: 600;"
        )
        self.delete_btn.setStyleSheet(
            "QPushButton {"
            f"background-color: {delete_bg}; color: {delete_fg}; border-radius: 11px;"
            "font-weight: 700; border: none; font-size: 14px; padding-bottom: 2px;"
            "}"
            f"QPushButton:hover {{ background-color: {delete_hover}; }}"
        )

    def enterEvent(self, event):
        self.hovered = True
        self.apply_theme(self.theme_mode)
        self.delete_btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.apply_theme(self.theme_mode)
        self.delete_btn.hide()
        super().leaveEvent(event)

    def on_delete(self):
        self.delete_requested.emit(self.chat_id)


# ---------------------------------------------------------------------------
#  MessageFileWidget
# ---------------------------------------------------------------------------

class MessageFileWidget(QFrame):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.theme_mode = "light"
        self.item = dict(item or {})
        self.setObjectName("messageFileChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(58)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.title_color = QColor("#101828")
        self.meta_color = QColor("#667085")
        self._title_font = QFont()
        self._meta_font = QFont()
        self._title_rect = QRect()
        self._meta_rect = QRect()
        self._meta_text = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("messageFileIcon")
        icon = _system_file_icon(item.get("path", ""), is_dir=bool(item.get("is_dir")))
        self.icon_label.setPixmap(icon.pixmap(28, 34))
        self.icon_label.setFixedSize(28, 34)
        layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.display_name = _attachment_display_name(self.item)
        full_path = item.get("path") or item.get("name") or self.display_name
        secondary = _attachment_secondary_text(item.get("path", ""), is_dir=bool(item.get("is_dir")))
        self.name_label = QLabel(self.display_name)
        self.name_label.setWordWrap(True)
        self.name_label.setToolTip(full_path)
        self.name_label.hide()
        self.meta_label = QLabel(secondary)
        self.meta_label.setWordWrap(False)
        self.meta_label.hide()
        layout.addStretch(1)
        self.apply_theme(self.theme_mode)
        self.recompute_layout(232)

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        frame_bg = "rgba(35, 39, 51, 0.94)" if self.theme_mode == "dark" else "#FFFFFF"
        frame_border = "#3C4352" if self.theme_mode == "dark" else "#E5E7EB"
        title_color = "#F3F4F6" if self.theme_mode == "dark" else "#101828"
        meta_color = "#98A2B3" if self.theme_mode == "dark" else "#667085"
        self.title_color = QColor(title_color)
        self.meta_color = QColor(meta_color)
        self._title_font = QFont(self.font())
        self._title_font.setPixelSize(12)
        self._title_font.setWeight(QFont.Weight.DemiBold)
        self._meta_font = QFont(self.font())
        self._meta_font.setPixelSize(11)
        self._meta_font.setWeight(QFont.Weight.Medium)
        self.setStyleSheet(
            "QFrame#messageFileChip {"
            f"background-color: {frame_bg};"
            "border-radius: 14px;"
            f"border: 1px solid {frame_border};"
            "}"
            "QLabel#messageFileIcon { background-color: #F4F7FB; border-radius: 8px; padding: 2px; }"
        )

    def recompute_layout(self, width: int | None = None):
        current_width = width if width is not None else self.width()
        text_width = max(96, current_width - 70)
        self.display_name = _attachment_display_name(self.item)
        self.name_label.setText(self.display_name)
        self._meta_text = _attachment_secondary_text(self.item.get("path", ""), is_dir=bool(self.item.get("is_dir")))
        self.meta_label.setText(self._meta_text)
        self._title_rect = QRect(76, 12, text_width, 32)
        self._meta_rect = QRect(76, 44, text_width, 18)
        self.layout().activate()
        self.setFixedHeight(max(58, self.layout().sizeHint().height()))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        title_metrics = QFontMetrics(self._title_font)
        title_text = title_metrics.elidedText(self.display_name, Qt.TextElideMode.ElideRight, self._title_rect.width() * 2)
        painter.setFont(self._title_font)
        painter.setPen(self.title_color)
        painter.drawText(self._title_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), title_text)

        meta_metrics = QFontMetrics(self._meta_font)
        meta_text = meta_metrics.elidedText(self._meta_text, Qt.TextElideMode.ElideRight, self._meta_rect.width())
        painter.setFont(self._meta_font)
        painter.setPen(self.meta_color)
        painter.drawText(self._meta_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), meta_text)
        painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.recompute_layout(self.width())

    def sizeHint(self):
        hint = self.layout().sizeHint()
        return QSize(max(232, hint.width()), max(58, hint.height()))

    def minimumSizeHint(self):
        return QSize(232, 58)

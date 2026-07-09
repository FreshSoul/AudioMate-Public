"""Common helper functions and constants shared across GUI modules."""

import functools
import os
import re
from urllib.parse import urlparse, unquote

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QImage, QIcon, QPainter, QPixmap, QColor, QFont, QPainterPath


def extract_text_from_content(content, default=""):
    """从消息内容中提取纯文本（支持多模态列表格式和普通字符串）"""
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
        return "\n".join(parts) if parts else default
    if not isinstance(content, str):
        return str(content) if content else default
    return content


IMAGE_FILE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
DEFAULT_REMOTE_MODELS = ["gpt-5.5","gpt-5.4","claude-fable-5","claude-opus-4-8", "claude-opus-4-7",  "claude-opus-4-6"]
ROLEPLAY_META_PREFIX = "[ROLEPLAY_STATE]"


def configure_back_button(button, tooltip: str = "返回"):
    """Apply shared behavior and geometry to page-level back buttons."""
    button.setText("‹")
    button.setObjectName("backBtn")
    button.setFixedSize(38, 38)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolTip(tooltip)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


def back_button_style(theme_mode: str) -> str:
    """Shared stylesheet for all page-level back buttons."""
    is_dark = theme_mode == "dark"
    bg = "#242A35" if is_dark else "#F4F6FF"
    hover_bg = "#303746" if is_dark else "#EDF1FF"
    pressed_bg = "#1F2530" if is_dark else "#E5EBFF"
    border = "#3A4351" if is_dark else "#DDE5F8"
    hover_border = "#526DFF" if is_dark else "#C9D6FF"
    fg = "#EEF3FF" if is_dark else "#4B5C78"
    disabled_fg = "#6E7788" if is_dark else "#A3ACBA"
    return (
        "QPushButton#backBtn {"
        f"background: {bg}; color: {fg}; border: 1px solid {border};"
        "border-radius: 19px; padding: 0px; margin: 0px;"
        "font-size: 24px; font-weight: 700;"
        "text-align: center; min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px;"
        "}"
        f"QPushButton#backBtn:hover {{ background: {hover_bg}; border: 1px solid {hover_border}; }}"
        f"QPushButton#backBtn:pressed {{ background: {pressed_bg}; padding-left: 1px; padding-top: 1px; }}"
        f"QPushButton#backBtn:disabled {{ color: {disabled_fg}; border-color: {border}; }}"
    )


def _is_supported_image_path(file_path: str) -> bool:
    if not file_path or not isinstance(file_path, str):
        return False
    return file_path.lower().endswith(IMAGE_FILE_EXTENSIONS)


def _split_attachment_files_for_display(files):
    display_images = []
    display_files = []

    for item in files or []:
        path = (item or {}).get("path") or ""
        if item.get("is_dir") or not _is_supported_image_path(path) or not os.path.isfile(path):
            display_files.append(item)
            continue

        image = QImage(path)
        if image.isNull():
            display_files.append(item)
            continue

        display_images.append(image)

    return display_images, display_files


def _resolve_local_image_path(path_text: str) -> str:
    candidate = (path_text or "").strip().strip('"\'<>')
    if not candidate:
        return ""

    if candidate.lower().startswith("file://"):
        parsed = urlparse(candidate)
        candidate = unquote(parsed.path or "")
        if re.match(r"^/[A-Za-z]:/", candidate):
            candidate = candidate[1:]

    candidate = candidate.replace("/", os.sep)
    if not _is_supported_image_path(candidate):
        return ""

    abs_path = os.path.abspath(candidate)
    if not os.path.isfile(abs_path):
        return ""
    return abs_path


def _extract_local_image_paths_from_text(text: str) -> list[str]:
    content = (text or "")
    if not content:
        return []

    candidates: list[str] = []

    markdown_matches = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", content, flags=re.IGNORECASE)
    candidates.extend(markdown_matches)

    html_matches = re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"']", content, flags=re.IGNORECASE)
    candidates.extend(html_matches)

    windows_path_matches = re.findall(
        r"([A-Za-z]:[\\/][^\n\r\t\"'<>|?*]+\.(?:png|jpg|jpeg|gif|bmp|webp))",
        content,
        flags=re.IGNORECASE,
    )
    candidates.extend(windows_path_matches)

    unix_path_matches = re.findall(
        r"((?:/[^\n\r\t\"'<>|?*]+)+\.(?:png|jpg|jpeg|gif|bmp|webp))",
        content,
        flags=re.IGNORECASE,
    )
    candidates.extend(unix_path_matches)

    resolved_paths = []
    seen = set()
    for raw in candidates:
        resolved = _resolve_local_image_path(raw)
        if resolved and resolved not in seen:
            seen.add(resolved)
            resolved_paths.append(resolved)
    return resolved_paths


@functools.lru_cache(maxsize=128)
def _icon_for_suffix(suffix: str) -> QIcon:
    clean_suffix = (suffix or "").strip()
    if not clean_suffix:
        return _build_file_type_icon("", is_dir=False)
    return _build_file_type_icon(clean_suffix, is_dir=False)


def _file_type_style(path: str, is_dir: bool = False) -> tuple[str, str, str, str]:
    if is_dir:
        return "#E8A11A", "DIR", "#FFF4D6", "#D8A93A"

    suffix = os.path.splitext((path or "").lower())[1]
    if suffix == ".pdf":
        return "#F04438", "PDF", "#FFF0EE", "#FECACA"
    if suffix in {".doc", ".docx"}:
        return "#3B82F6", "W", "#EEF4FF", "#BFDBFE"
    if suffix in {".xls", ".xlsx", ".csv"}:
        return "#22C55E", "X", "#EDFCF2", "#BBF7D0"
    if suffix in {".ppt", ".pptx"}:
        return "#FB923C", "P", "#FFF2E8", "#FED7AA"
    if suffix in {".wav", ".mp3", ".ogg", ".flac", ".aif", ".aiff", ".wem"}:
        return "#8B5CF6", "A", "#F4EEFF", "#DDD6FE"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tga"}:
        return "#8B5CF6", "IMG", "#F4EEFF", "#DDD6FE"
    if suffix in {".txt", ".md", ".log", ".json", ".xml", ".html"}:
        return "#94A3B8", "T", "#F1F5F9", "#CBD5E1"
    if suffix in {".zip", ".rar", ".7z"}:
        return "#4F8EF7", "ZIP", "#EEF4FF", "#BFDBFE"
    if suffix in {".py", ".js", ".ts", ".cs", ".cpp", ".h"}:
        return "#2F80ED", "CODE", "#EEF4FF", "#BFDBFE"
    return "#94A3B8", "?", "#F1F5F9", "#CBD5E1"


def _format_attachment_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _attachment_secondary_text(path: str, is_dir: bool = False) -> str:
    normalized_path = (path or "").strip()
    if is_dir:
        return "文件夹"
    try:
        if normalized_path and os.path.isfile(normalized_path):
            return _format_attachment_size(os.path.getsize(normalized_path))
    except OSError:
        pass

    suffix = os.path.splitext(normalized_path)[1].lstrip(".").upper()
    return f"{suffix} 文件" if suffix else "本地文件"


def _build_file_type_icon(path: str, is_dir: bool = False) -> QIcon:
    width = 28
    height = 34
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    accent, label, _background, border = _file_type_style(path, is_dir=is_dir)

    if is_dir:
        tab_rect = QRectF(4, 7, 10, 5)
        body_rect = QRectF(3, 10, 22, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent))
        painter.drawRoundedRect(tab_rect, 2, 2)
        painter.drawRoundedRect(body_rect, 4, 4)
        painter.setPen(QColor("#FFFFFF"))
        font = QFont()
        font.setPixelSize(7)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(body_rect, int(Qt.AlignmentFlag.AlignCenter), label)
    else:
        page = QPainterPath()
        page.moveTo(2, 2)
        page.lineTo(18, 2)
        page.lineTo(25, 9)
        page.lineTo(25, 31)
        page.lineTo(2, 31)
        page.closeSubpath()
        painter.fillPath(page, QColor("#F5F7FB"))
        painter.setPen(QColor("#B8C2D1"))
        painter.drawPath(page)

        fold = QPainterPath()
        fold.moveTo(18, 2)
        fold.lineTo(18, 9)
        fold.lineTo(25, 9)
        fold.closeSubpath()
        painter.fillPath(fold, QColor("#D7DEEA"))

        painter.setPen(QColor("#E2E8F0"))
        painter.drawLine(5, 8, 16, 8)
        painter.drawLine(5, 12, 21, 12)

        badge_rect = QRectF(4, 17, 19, 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent))
        painter.drawRoundedRect(badge_rect, 3, 3)
        painter.setPen(QColor("#FFFFFF"))
        font = QFont()
        font.setPixelSize(7 if len(label) <= 3 else 6)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(badge_rect, int(Qt.AlignmentFlag.AlignCenter), label[:3])

    painter.end()
    return QIcon(pixmap)


def _system_file_icon(path: str, is_dir: bool = False) -> QIcon:
    normalized_path = (path or "").strip().strip('"')
    if is_dir:
        return _build_file_type_icon(normalized_path, is_dir=True)
    suffix = os.path.splitext(normalized_path)[1]
    if suffix:
        return _icon_for_suffix(suffix)
    return _build_file_type_icon(normalized_path, is_dir=False)

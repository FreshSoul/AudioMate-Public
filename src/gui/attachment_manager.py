"""Attachment preview and multimodal image helpers for MainWindow."""

from __future__ import annotations

import base64
import os

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QPixmap

from src.gui.widgets import FilePreviewWidget, ImagePreviewWidget
from src.utils.app_logger import get_logger


logger = get_logger(__name__)

VISION_IMAGE_MAX_SIDE = 1568
VISION_IMAGE_JPEG_QUALITY = 82


class AttachmentManager:
    """Manage pending image/file attachments and their preview widgets."""

    def __init__(self, owner):
        self.owner = owner
        self.pending_images = []
        self.pending_files = []
        owner.pending_images = self.pending_images
        owner.pending_files = self.pending_files

    def add_pending_image(self, image):
        self.pending_images.append(image)
        self.update_image_preview()

    def add_pending_paths(self, paths):
        existing = {item.get("path") for item in self.pending_files}
        normalized_paths = []
        for path in paths or []:
            if not path:
                continue
            normalized = os.path.abspath(path)
            if normalized in existing:
                continue
            existing.add(normalized)
            normalized_paths.append(normalized)
            self.pending_files.append({
                "path": normalized,
                "name": os.path.basename(normalized) or normalized,
                "is_dir": os.path.isdir(normalized),
            })
        if normalized_paths:
            self.owner.agent_tools.remember_paths(normalized_paths, source="drag-drop")
            self.update_image_preview()

    def remove_pending_image(self, index):
        if 0 <= index < len(self.pending_images):
            self.pending_images.pop(index)
            self.update_image_preview()

    def remove_pending_file(self, index):
        if 0 <= index < len(self.pending_files):
            self.pending_files.pop(index)
            self.update_image_preview()

    def update_image_preview(self):
        owner = self.owner
        while owner.image_preview_layout.count() > 1:
            item = owner.image_preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        insert_index = 0
        max_preview_height = 0
        if self.pending_images:
            for index, image in enumerate(self.pending_images):
                pixmap = QPixmap.fromImage(image)
                preview = ImagePreviewWidget(pixmap, index, theme_mode=owner.theme_mode)
                preview.remove_clicked.connect(owner.remove_pending_image)
                owner.image_preview_layout.insertWidget(insert_index, preview)
                insert_index += 1
                max_preview_height = max(
                    max_preview_height,
                    preview.height(),
                    preview.sizeHint().height(),
                    preview.minimumSizeHint().height(),
                )

        if self.pending_files:
            for index, item in enumerate(self.pending_files):
                preview = FilePreviewWidget(item, index, theme_mode=owner.theme_mode)
                preview.remove_clicked.connect(owner.remove_pending_file)
                owner.image_preview_layout.insertWidget(insert_index, preview)
                insert_index += 1
                max_preview_height = max(
                    max_preview_height,
                    preview.height(),
                    preview.sizeHint().height(),
                    preview.minimumSizeHint().height(),
                )

        if self.pending_images or self.pending_files:
            _, top_margin, _, bottom_margin = owner.image_preview_layout.getContentsMargins()
            owner.image_preview_container.setFixedHeight(max_preview_height + top_margin + bottom_margin)
            owner.image_preview_content.adjustSize()
            owner.image_preview_container.show()
        else:
            owner.image_preview_container.setFixedHeight(0)
            owner.image_preview_container.hide()

    def clear_pending_images(self):
        self.pending_images.clear()
        self.pending_files.clear()
        self.update_image_preview()

    def format_pending_files_text(self, items):
        if not items:
            return ""
        lines = []
        for item in items:
            icon = "[文件夹]" if item.get("is_dir") else "[文件]"
            lines.append(f"{icon} {item.get('path', '')}")
        return "\n".join(lines)

    def build_user_display_text(self, user_text, images=None, files=None):
        parts = []
        if user_text:
            parts.append(user_text)
        if files:
            parts.append(self.format_pending_files_text(files))
        if images and not user_text and not files:
            parts.append("[图片]")
        elif images:
            parts.append(f"[图片 {len(images)} 张]")
        return "\n".join(part for part in parts if part).strip()

    def images_to_base64(self, images):
        result = []
        for image in images:
            prepared = QImage(image)
            if prepared.isNull():
                continue

            if max(prepared.width(), prepared.height()) > VISION_IMAGE_MAX_SIDE:
                prepared = prepared.scaled(
                    VISION_IMAGE_MAX_SIDE,
                    VISION_IMAGE_MAX_SIDE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

            prepared = prepared.convertToFormat(QImage.Format.Format_RGB888)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            media_type = "image/jpeg"
            prepared.save(buffer, "JPEG", VISION_IMAGE_JPEG_QUALITY)
            encoded = base64.b64encode(buffer.data().data()).decode("utf-8")
            result.append({"type": "image", "data": encoded, "media_type": media_type})
        return result

    def base64_to_images(self, content_list):
        images = []
        for item in content_list:
            if item.get("type") != "image_url":
                continue
            image_url = item.get("image_url", {})
            url = image_url.get("url", "")
            if not url.startswith("data:"):
                continue
            try:
                _header, encoded = url.split(",", 1)
                image_bytes = base64.b64decode(encoded)
                image = QImage()
                image.loadFromData(image_bytes)
                if not image.isNull():
                    images.append(image)
            except Exception as exc:
                logger.warning("Failed to decode image from stored content: %s", exc)
        return images
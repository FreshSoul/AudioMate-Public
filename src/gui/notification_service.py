from __future__ import annotations

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication, QWidget

from src.utils.notification_settings import normalize_notification_settings


class NotificationService(QObject):
    def __init__(self, parent: QWidget | None = None, settings: dict | None = None):
        super().__init__(parent)
        self.parent_widget = parent
        self.settings = normalize_notification_settings(settings)

    def update_settings(self, settings: dict | None):
        self.settings = normalize_notification_settings(settings)

    def is_available(self) -> bool:
        return self.parent_widget is not None

    def notify_task_completed(self, title: str, message: str):
        self._show()

    def notify_task_failed(self, title: str, message: str):
        self._show()

    def notify_task_cancelled(self, title: str, message: str):
        self._show()

    def _show(self):
        if not self.settings.get("enabled", True):
            return
        if self.parent_widget is not None:
            QApplication.alert(self.parent_widget, 0)

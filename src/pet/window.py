"""Floating desktop pet window.

A frameless, always-on-top, draggable window that displays an avatar plus
a collapsible chat bubble.  Subscribed to ``PetService`` signals so it can
relay live task progress to the user.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QMovie,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from src.pet.service import PetService


_SEVERITY_COLORS = {
    "info": "#3B82F6",
    "success": "#16A34A",
    "warn": "#F59E0B",
    "error": "#DC2626",
}


class _RoundedAvatar(QLabel):
    """Round avatar widget; supports per-state GIF animations and static fallback."""

    PET_STATE_IDLE = "idle"
    PET_STATE_WORKING = "working"
    PET_STATE_MOVING = "moving"

    def __init__(self, diameter: int = 96, parent: QWidget | None = None):
        super().__init__(parent)
        self._diameter = diameter
        self._initial = "B"
        self._pixmap: QPixmap | None = None
        self._movies: dict[str, QMovie] = {}
        self._sprite_paths: dict[str, str] = {"idle": "", "working": "", "moving": ""}
        self._state: str = self.PET_STATE_IDLE
        self._active_movie: QMovie | None = None
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_avatar(self, path: str, fallback_initial: str = "B") -> None:
        self._initial = (fallback_initial or "B")[:1].upper() or "B"
        self._teardown_movies()
        self._sprite_paths = {"idle": path or "", "working": "", "moving": ""}
        self._load_static(path)

    def set_sprites(self, sprite_paths: dict, fallback_initial: str = "B") -> None:
        """Configure per-state sprite paths.

        ``sprite_paths`` maps ``idle/working/moving`` to local file paths
        (PNG/JPG/GIF/SVG).  Missing or invalid states fall back to ``idle``.
        """
        self._initial = (fallback_initial or "B")[:1].upper() or "B"
        self._teardown_movies()
        cleaned = {
            state: (sprite_paths or {}).get(state, "") or ""
            for state in ("idle", "working", "moving")
        }
        self._sprite_paths = cleaned
        self._apply_state(self._state)

    def set_state(self, state: str) -> None:
        if state not in ("idle", "working", "moving"):
            return
        if state == self._state:
            return
        self._state = state
        self._apply_state(state)

    # ------------------------------------------------------------------

    def _teardown_movies(self) -> None:
        if self._active_movie is not None:
            try:
                self._active_movie.frameChanged.disconnect(self._on_movie_frame)
            except (RuntimeError, TypeError):
                pass
            self._active_movie.stop()
        for movie in self._movies.values():
            movie.stop()
            movie.deleteLater()
        self._movies.clear()
        self._active_movie = None

    def _apply_state(self, state: str) -> None:
        path = self._sprite_paths.get(state) or self._sprite_paths.get("idle") or ""
        if self._active_movie is not None:
            try:
                self._active_movie.frameChanged.disconnect(self._on_movie_frame)
            except (RuntimeError, TypeError):
                pass
            self._active_movie.stop()
            self._active_movie = None

        if path and os.path.isfile(path) and path.lower().endswith(".gif"):
            movie = self._movies.get(state)
            if movie is None:
                movie = QMovie(path)
                movie.setCacheMode(QMovie.CacheMode.CacheAll)
                # Use natural frame size; paintEvent scales preserving aspect.
                self._movies[state] = movie
            self._active_movie = movie
            movie.frameChanged.connect(self._on_movie_frame)
            self._pixmap = None
            movie.start()
            self.update()
            return

        self._load_static(path)

    def _load_static(self, path: str) -> None:
        if path and os.path.isfile(path):
            pix = QPixmap(path)
            if not pix.isNull():
                # Keep the full subject — paintEvent scales preserving aspect.
                self._pixmap = pix
                self.update()
                return
        self._pixmap = None
        self.update()

    def _on_movie_frame(self, _frame_index: int) -> None:
        if self._active_movie is None:
            return
        self._pixmap = self._active_movie.currentPixmap()
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = self.rect()

        if self._pixmap is not None:
            # Draw the sprite at its natural aspect ratio, centred — no
            # circular clip and no white ring. Non-square characters keep
            # their full silhouette and only the alpha channel survives.
            pix = self._pixmap
            scaled = pix.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = rect.x() + (rect.width() - scaled.width()) // 2
            y = rect.y() + (rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            # Fallback: minimal circle with the initial.
            rect_f = QRectF(rect).adjusted(2, 2, -2, -2)
            path = QPainterPath()
            path.addEllipse(rect_f)
            painter.setClipPath(path)
            painter.fillRect(rect, QColor("#5B8FE8"))
            font = QFont(self.font())
            font.setPointSizeF(self._diameter / 2.6)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._initial)
            painter.setClipping(False)
        painter.end()


class _AnnouncementBubble(QFrame):
    """Tiny floating label that fades in & out when the pet has news."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("petBubble")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            "QFrame#petBubble { background-color: rgba(255,255,255,235);"
            " border: 1px solid rgba(91,143,232,140); border-radius: 12px; }"
            "QLabel { color: #1F2937; font-size: 12px; padding: 0px; background: transparent; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self._label = QLabel("", self)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(240)
        layout.addWidget(self._label)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_in = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_in.setDuration(200)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade_out = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_out.setDuration(400)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self.hide)

        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self._fade_out.start)

        self.hide()

    def show_message(self, text: str, severity: str = "info", duration_ms: int = 3500) -> None:
        if not text:
            return
        color = _SEVERITY_COLORS.get(severity, _SEVERITY_COLORS["info"])
        self._label.setStyleSheet(f"color: {color}; font-size: 12px; padding: 0px; background: transparent;")
        self._label.setText(text)
        self.adjustSize()
        self.show()
        self._fade_in.stop()
        self._fade_out.stop()
        self._opacity_effect.setOpacity(0.0)
        self._fade_in.start()
        self._auto_hide.stop()
        self._auto_hide.start(max(1500, int(duration_ms)))


class MainPetWindow(QWidget):
    """The floating desktop window that represents the selected desktop pet."""

    user_message_submitted = pyqtSignal(str)
    open_training_room_requested = pyqtSignal(str)  # pet_id
    open_settings_requested = pyqtSignal()
    hide_requested = pyqtSignal()
    intent_mirrored = pyqtSignal(str, str, str)   # widget_id, intent, note
    confirm_mirrored = pyqtSignal(str, bool)      # widget_id, accepted
    file_write_mirrored = pyqtSignal(str, bool)   # widget_id, accepted

    AVATAR_DIAMETER = 110

    def __init__(
        self,
        pet_service: "PetService",
        parent: QWidget | None = None,
    ):
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._pet_service = pet_service
        self._drag_offset: QPoint | None = None
        self._chat_visible = False
        self._recent_messages: list[str] = []
        self._current_pet_id: str = ""

        self._build_ui()
        self._connect_signals()
        self._refresh_from_service()
        self._restore_position()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._bubble = _AnnouncementBubble(self)
        self._bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        outer.addWidget(self._bubble, 0, Qt.AlignmentFlag.AlignHCenter)

        self._avatar = _RoundedAvatar(self.AVATAR_DIAMETER, self)
        self._avatar.installEventFilter(self)
        outer.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignHCenter)

        # Name label is hidden by default — desktop shows only the sprite
        # subject. Hovering over the avatar (or right-click) surfaces the
        # name briefly for identification.
        self._name_label = QLabel("Buddy", self)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._name_label.setStyleSheet(
            "color: #FFFFFF; font-weight: 700; font-size: 13px;"
            " background: transparent; padding: 2px 8px;"
        )
        name_shadow = QGraphicsDropShadowEffect(self._name_label)
        name_shadow.setBlurRadius(6)
        name_shadow.setColor(QColor(0, 0, 0, 220))
        name_shadow.setOffset(0, 1)
        self._name_label.setGraphicsEffect(name_shadow)
        self._name_label.hide()
        outer.addWidget(self._name_label, 0, Qt.AlignmentFlag.AlignHCenter)

        # Hover-to-reveal timers for the name label.
        self._name_show_timer = QTimer(self)
        self._name_show_timer.setSingleShot(True)
        self._name_show_timer.setInterval(800)
        self._name_show_timer.timeout.connect(self._on_show_name)
        self._name_hide_timer = QTimer(self)
        self._name_hide_timer.setSingleShot(True)
        self._name_hide_timer.setInterval(2000)
        self._name_hide_timer.timeout.connect(self._name_label.hide)

        self._chat_panel = QFrame(self)
        self._chat_panel.setObjectName("petChatPanel")
        self._chat_panel.setStyleSheet(
            "QFrame#petChatPanel { background-color: rgba(255,255,255,240);"
            " border: 1px solid rgba(91,143,232,180); border-radius: 14px; }"
            "QTextEdit { border: none; background: transparent; color: #1F2937;"
            " font-size: 12px; }"
            "QLineEdit { border: 1px solid #D1D5DB; border-radius: 8px;"
            " padding: 6px 10px; background: #FFFFFF; color: #111827; }"
            "QPushButton { background: #5B8FE8; color: #FFFFFF; border: none;"
            " border-radius: 8px; padding: 6px 14px; font-weight: 600; }"
            "QPushButton:hover { background: #4A7BD0; }"
            "QPushButton:disabled { background: #B0BEC5; }"
        )
        self._chat_panel.setMinimumWidth(320)
        self._chat_panel.setMaximumWidth(520)
        self._chat_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)

        chat_layout = QVBoxLayout(self._chat_panel)
        chat_layout.setContentsMargins(12, 12, 12, 12)
        chat_layout.setSpacing(8)

        # Mount point for mirrored interaction widgets (intent / confirm /
        # file-write). Tracks mounted widgets by id so a click on either
        # side (main window or floating pet) can dismiss the partner.
        self._interaction_host = QVBoxLayout()
        self._interaction_host.setContentsMargins(0, 0, 0, 0)
        self._interaction_host.setSpacing(6)
        self._interaction_widgets: dict[str, QWidget] = {}
        chat_layout.addLayout(self._interaction_host)

        # Parallel sub-agent status rows — one row per in-flight dispatch.
        self._agent_status_frame = QFrame(self._chat_panel)
        self._agent_status_frame.setObjectName("petAgentStatusFrame")
        self._agent_status_frame.setStyleSheet(
            "QFrame#petAgentStatusFrame { background: rgba(31,41,55,160);"
            " border: 1px solid rgba(91,143,232,160); border-radius: 10px; }"
            "QLabel { color: #F3F4F6; font-size: 12px; background: transparent; }"
        )
        self._agent_status_layout = QVBoxLayout(self._agent_status_frame)
        self._agent_status_layout.setContentsMargins(10, 6, 10, 6)
        self._agent_status_layout.setSpacing(2)
        self._agent_status_rows: dict[str, QLabel] = {}
        self._agent_status_heartbeat = QTimer(self)
        self._agent_status_heartbeat.setInterval(400)
        self._agent_status_heartbeat.timeout.connect(self._tick_agent_status_heartbeat)
        self._agent_status_phase = 0
        self._agent_status_pending_meta: dict[str, dict] = {}
        self._agent_status_frame.hide()
        chat_layout.addWidget(self._agent_status_frame)

        self._history_view = QTextEdit(self._chat_panel)
        self._history_view.setReadOnly(True)
        self._history_view.setFixedHeight(110)
        self._history_view.setPlaceholderText("还没有汇报~ 让 Buddy 帮你跑个任务吧。")
        chat_layout.addWidget(self._history_view)

        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self._input_edit = QLineEdit(self._chat_panel)
        self._input_edit.setPlaceholderText("和 Buddy 聊点什么…")
        self._input_edit.returnPressed.connect(self._on_send_clicked)
        input_row.addWidget(self._input_edit, 1)
        self._send_btn = QPushButton("发送", self._chat_panel)
        self._send_btn.clicked.connect(self._on_send_clicked)
        input_row.addWidget(self._send_btn, 0)
        chat_layout.addLayout(input_row)

        outer.addWidget(self._chat_panel, 0, Qt.AlignmentFlag.AlignHCenter)
        self._chat_panel.hide()

        self._sync_size()

    def _connect_signals(self) -> None:
        self._pet_service.main_pet_announcement.connect(self._on_announcement)
        self._pet_service.pets_changed.connect(self._on_pets_changed)
        # Parallel sub-agent live status.
        try:
            self._pet_service.sub_agent_started.connect(self._on_sub_agent_started)
            self._pet_service.sub_agent_finished.connect(self._on_sub_agent_finished)
        except Exception:
            pass

    # ---- parallel sub-agent status ----

    def _on_sub_agent_started(self, run_id: str, pet_id: str, pet_name: str) -> None:
        label = QLabel(f"🤖 {pet_name or '副宠'} 工作中…", self._agent_status_frame)
        self._agent_status_layout.addWidget(label)
        self._agent_status_rows[run_id] = label
        self._agent_status_pending_meta[run_id] = {"name": pet_name or "副宠"}
        self._agent_status_frame.show()
        self._ensure_chat_panel_visible()
        if not self._agent_status_heartbeat.isActive():
            self._agent_status_phase = 0
            self._agent_status_heartbeat.start()

    def _on_sub_agent_finished(self, run_id: str, success: bool, snippet: str) -> None:
        label = self._agent_status_rows.get(run_id)
        meta = self._agent_status_pending_meta.pop(run_id, {})
        name = meta.get("name", "副宠")
        # Stop the heartbeat as soon as nothing is in-flight, regardless of
        # whether the UI row is present — guards against `finished` for an
        # unknown run_id leaking the timer.
        if not self._agent_status_pending_meta:
            self._agent_status_heartbeat.stop()
        if label is None:
            return
        mark = "✓" if success else "✗"
        text = f"{mark} {name}"
        if snippet:
            text += f": {snippet}"
        label.setText(text)
        # Schedule fade-out 3s later. Use a single-shot QTimer per row so
        # multiple finishes don't stomp on each other.
        QTimer.singleShot(3000, lambda _id=run_id: self._dismiss_agent_status_row(_id))

    def _dismiss_agent_status_row(self, run_id: str) -> None:
        label = self._agent_status_rows.pop(run_id, None)
        if label is None:
            return
        self._agent_status_layout.removeWidget(label)
        label.setParent(None)
        label.deleteLater()
        if not self._agent_status_rows:
            self._agent_status_frame.hide()
        self._sync_size()

    def _tick_agent_status_heartbeat(self) -> None:
        self._agent_status_phase = (self._agent_status_phase + 1) % 4
        dots = "." * self._agent_status_phase
        for run_id, label in self._agent_status_rows.items():
            if run_id in self._agent_status_pending_meta:
                name = self._agent_status_pending_meta[run_id].get("name", "副宠")
                label.setText(f"🤖 {name} 工作中{dots}")

    def _refresh_from_service(self) -> None:
        pet_getter = getattr(self._pet_service, "floating_pet", None)
        pet = pet_getter() if callable(pet_getter) else self._pet_service.active_main()
        if pet is None:
            self._current_pet_id = ""
            self._name_label.setText("Buddy")
            self._avatar.set_avatar("", "B")
            return
        self._current_pet_id = pet.get("id", "")
        name = (pet.get("name") or "Buddy").strip() or "Buddy"
        self._name_label.setText(name)
        sprites = pet.get("sprites") or {}
        if sprites.get("idle") or sprites.get("working") or sprites.get("moving"):
            self._avatar.set_sprites(sprites, name[:1])
        else:
            self._avatar.set_avatar(pet.get("avatar_path", ""), name[:1])

    def set_pet_state(self, state: str) -> None:
        """Switch the floating avatar to ``idle``/``working``/``moving``."""
        try:
            self._avatar.set_state(state)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Position persistence
    # ------------------------------------------------------------------

    def _restore_position(self) -> None:
        position = self._pet_service.floating_position()
        x = int(position.get("x", -1))
        y = int(position.get("y", -1))
        if x >= 0 and y >= 0:
            self.move(x, y)
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            self.move(40, 40)
            return
        geom = screen.availableGeometry()
        self._sync_size()
        target_x = geom.right() - self.width() - 32
        target_y = geom.bottom() - self.height() - 60
        self.move(max(geom.left(), target_x), max(geom.top(), target_y))

    def _sync_size(self) -> None:
        self.adjustSize()
        # Floor a minimum so the avatar+name don't clip on first show.
        self.setMinimumWidth(180)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self._avatar:
            event_type = event.type()
            from PyQt6.QtCore import QEvent  # local import keeps top tidy

            if event_type == QEvent.Type.Enter:
                self._name_hide_timer.stop()
                self._name_show_timer.start()
            elif event_type == QEvent.Type.Leave:
                self._name_show_timer.stop()
                if self._name_label.isVisible():
                    self._name_hide_timer.start(500)

            if event_type == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return True
            if event_type == QEvent.Type.MouseMove and self._drag_offset is not None:
                new_pos = event.globalPosition().toPoint() - self._drag_offset
                self.move(new_pos)
                self._avatar.set_state("moving")
                event.accept()
                return True
            if event_type == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self._drag_offset is not None:
                    delta = event.globalPosition().toPoint() - (self._drag_offset + self.frameGeometry().topLeft())
                    self._drag_offset = None
                    pos = self.pos()
                    self._pet_service.set_floating_position(pos.x(), pos.y())
                    self._avatar.set_state("idle")
                    if abs(delta.x()) < 4 and abs(delta.y()) < 4:
                        self._toggle_chat()
                    event.accept()
                    return True
            if event_type == QEvent.Type.ContextMenu:
                self._show_context_menu(event.globalPos())
                event.accept()
                return True
        return super().eventFilter(obj, event)

    def _on_show_name(self) -> None:
        if not self._name_label.text():
            return
        self._name_label.show()
        # Auto-hide after a short while in case the user moves elsewhere
        # without crossing the avatar's Leave boundary cleanly.
        self._name_hide_timer.start(2500)

    def closeEvent(self, event):
        # Hidden rather than destroyed; MainWindow controls lifecycle.
        event.ignore()
        self.hide()
        self.hide_requested.emit()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_announcement(self, text: str, severity: str) -> None:
        if not text:
            return
        self._bubble.show_message(text, severity)
        self._recent_messages.append(text)
        if len(self._recent_messages) > 6:
            self._recent_messages = self._recent_messages[-6:]
        self._refresh_history()

    def _on_pets_changed(self, _state: dict) -> None:
        self._refresh_from_service()

    def _toggle_chat(self) -> None:
        self._chat_visible = not self._chat_visible
        self._chat_panel.setVisible(self._chat_visible)
        self._sync_size()
        if self._chat_visible:
            self._input_edit.setFocus()

    def _refresh_history(self) -> None:
        if not self._recent_messages:
            self._history_view.clear()
            return
        text = "\n".join(f"· {msg}" for msg in self._recent_messages[-3:])
        self._history_view.setPlainText(text)

    def _on_send_clicked(self) -> None:
        text = self._input_edit.text().strip()
        if not text:
            return
        self._input_edit.clear()
        self.user_message_submitted.emit(text)

    # ------------------------------------------------------------------
    # Mirrored interaction widgets (intent clarify / confirm / file write)
    # ------------------------------------------------------------------

    def _ensure_chat_panel_visible(self) -> None:
        if not self._chat_visible:
            self._chat_visible = True
            self._chat_panel.setVisible(True)
            self._sync_size()

    def host_intent_widget(self, widget_id: str, options: list) -> None:
        """Mount an IntentClarifyWidget into the floating chat panel."""
        if not widget_id:
            return
        # Avoid duplicates if MainWindow asks twice for the same id.
        self.dismiss_interaction(widget_id)
        # Local import keeps this file's top-level import list slim and
        # avoids a circular import risk via widgets → main_window helpers.
        from src.gui.widgets import IntentClarifyWidget
        wid = IntentClarifyWidget(list(options or []), theme_mode="light", parent=self._chat_panel)
        wid.intent_selected.connect(
            lambda intent, note, _id=widget_id: self._emit_intent_choice(_id, intent, note)
        )
        self._mount_interaction(widget_id, wid)

    def host_confirm_widget(self, widget_id: str) -> None:
        if not widget_id:
            return
        self.dismiss_interaction(widget_id)
        from src.gui.widgets import ConfirmationWidget
        wid = ConfirmationWidget(theme_mode="light", parent=self._chat_panel)
        wid.confirmed.connect(lambda _id=widget_id: self._emit_confirm_choice(_id, True))
        wid.revoked.connect(lambda _id=widget_id: self._emit_confirm_choice(_id, False))
        self._mount_interaction(widget_id, wid)

    def host_file_write_widget(self, widget_id: str, file_paths: list) -> None:
        if not widget_id:
            return
        self.dismiss_interaction(widget_id)
        from src.gui.widgets import FileWriteConfirmWidget
        wid = FileWriteConfirmWidget(list(file_paths or []), theme_mode="light", parent=self._chat_panel)
        wid.confirmed.connect(lambda _id=widget_id: self._emit_file_write_choice(_id, True))
        wid.revoked.connect(lambda _id=widget_id: self._emit_file_write_choice(_id, False))
        self._mount_interaction(widget_id, wid)

    def dismiss_interaction(self, widget_id: str) -> None:
        widget = self._interaction_widgets.pop(widget_id, None)
        if widget is None:
            return
        self._interaction_host.removeWidget(widget)
        widget.setParent(None)
        widget.deleteLater()
        self._sync_size()

    def _mount_interaction(self, widget_id: str, widget: QWidget) -> None:
        self._interaction_widgets[widget_id] = widget
        self._interaction_host.addWidget(widget)
        self._ensure_chat_panel_visible()

    def _emit_intent_choice(self, widget_id: str, intent: str, note: str) -> None:
        self.dismiss_interaction(widget_id)
        self.intent_mirrored.emit(widget_id, intent or "", note or "")

    def _emit_confirm_choice(self, widget_id: str, accepted: bool) -> None:
        self.dismiss_interaction(widget_id)
        self.confirm_mirrored.emit(widget_id, bool(accepted))

    def _emit_file_write_choice(self, widget_id: str, accepted: bool) -> None:
        self.dismiss_interaction(widget_id)
        self.file_write_mirrored.emit(widget_id, bool(accepted))

    def _show_context_menu(self, global_pos) -> None:
        menu = QMenu(self)
        if self._current_pet_id:
            open_room = QAction("打开修炼室", menu)
            pet_id = self._current_pet_id
            open_room.triggered.connect(lambda: self.open_training_room_requested.emit(pet_id))
            menu.addAction(open_room)
        toggle_chat = QAction("收起对话" if self._chat_visible else "展开对话", menu)
        toggle_chat.triggered.connect(self._toggle_chat)
        menu.addAction(toggle_chat)
        open_settings = QAction("Buddy 设置…", menu)
        open_settings.triggered.connect(self.open_settings_requested.emit)
        menu.addAction(open_settings)
        menu.addSeparator()
        hide_action = QAction("隐藏悬浮窗", menu)
        hide_action.triggered.connect(self._on_hide_clicked)
        menu.addAction(hide_action)
        menu.exec(global_pos)

    def _on_hide_clicked(self) -> None:
        self.hide()
        self.hide_requested.emit()


__all__ = ["MainPetWindow"]

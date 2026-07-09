"""AudioMate Office — the visual BUDDY view inside the Settings page.

A 2D top-down "office" with desks: the active main pet in the centre,
sub-pets arranged around it, a side panel showing today's token usage
and the list of recent conversations.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
from PyQt6.QtGui import QDrag, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QComboBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.pet.store import PET_KIND_MAIN, PET_KIND_SUB, is_fixed_default_pet


_GRID_SLOTS = 9  # 3x3 grid


_DESK_MIME = "application/x-audiomate-pet-id"


class _PetDeskWidget(QFrame):
    """A single desk: shows a pet's avatar + name, or an empty placeholder.

    Supports drag-and-drop reorder: drag a desk that has a pet, drop on any
    other desk to swap. Empty desks accept drops as well.
    """

    clicked = pyqtSignal(str)            # pet_id (for occupied desks)
    empty_clicked = pyqtSignal(int)       # slot_index (for empty desks)
    context_requested = pyqtSignal(str, "QPoint")  # pet_id, global pos
    drop_received = pyqtSignal(str, int)  # source pet_id, target slot_index

    def __init__(self, slot_index: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._slot_index = int(slot_index)
        self.setObjectName("petDeskCard")
        self.setProperty("deskState", "empty")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumSize(140, 140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pet: dict | None = None
        self._is_main = False
        self.setAcceptDrops(True)
        self._drag_start_pos = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._avatar = QLabel(self)
        self._avatar.setFixedSize(96, 96)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setObjectName("petDeskAvatar")
        layout.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignHCenter)

        self._name_label = QLabel("", self)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._name_label.setObjectName("petDeskName")
        layout.addWidget(self._name_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self._role_label = QLabel("", self)
        self._role_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._role_label.setObjectName("petDeskRole")
        layout.addWidget(self._role_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_state("empty")

    def slot_index(self) -> int:
        return self._slot_index

    def pet_id(self) -> str:
        return (self._pet or {}).get("id", "") if self._pet else ""

    def _set_state(self, state: str) -> None:
        self.setProperty("deskState", state)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_empty(self) -> None:
        self._pet = None
        self._is_main = False
        self._avatar.setPixmap(QPixmap())
        self._avatar.setText("＋")
        self._avatar.setProperty("avatarState", "add")
        self._refresh_avatar_style()
        self._name_label.setText("空工位")
        self._role_label.setText("点击添加宠物")
        self._set_state("empty")

    def set_pet(self, pet: dict, is_main: bool, is_desktop: bool = False) -> None:
        self._pet = dict(pet or {})
        self._is_main = bool(is_main)
        name = pet.get("name") or ("AudioMate" if is_main else "副宠")
        self._name_label.setText(name)
        role = "AudioMate (主)" if is_main else "副宠 (Agent)"
        if is_desktop:
            role += " · 桌面显示"
        self._role_label.setText(role)

        sprites = pet.get("sprites") or {}
        path = sprites.get("idle") or pet.get("avatar_path", "") or ""
        has_image = False
        if path and os.path.isfile(path) and not path.lower().endswith(".gif"):
            pix = QPixmap(path)
            if not pix.isNull():
                pix = pix.scaled(
                    96, 96,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._avatar.setPixmap(pix)
                self._avatar.setText("")
                has_image = True
        if not has_image:
            self._avatar.setPixmap(QPixmap())
            self._avatar.setText(name[:1] if name else "?")
        self._avatar.setProperty("avatarState", "image" if has_image else "initial")
        self._refresh_avatar_style()
        self._set_state("main" if is_main else "occupied")

    def _refresh_avatar_style(self) -> None:
        self._avatar.style().unpolish(self._avatar)
        self._avatar.style().polish(self._avatar)

    # ---- mouse / drag-drop ----

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            if self._pet is None:
                # Click on empty slot — defer to release
                pass
        elif event.button() == Qt.MouseButton.RightButton:
            if self._pet is not None:
                self.context_requested.emit(self.pet_id(), event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start_pos is not None:
            self._drag_start_pos = None
            if self._pet is None:
                self.empty_clicked.emit(self._slot_index)
            else:
                # Treat as a click if there was no drag.
                self.clicked.emit(self.pet_id())
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._pet is None or self._drag_start_pos is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        distance = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
        if distance < 12:
            return
        # Start drag — clear the click state so release doesn't fire clicked.
        self._drag_start_pos = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_DESK_MIME, self.pet_id().encode("utf-8"))
        drag.setMimeData(mime)
        pix = self._avatar.pixmap()
        if pix and not pix.isNull():
            drag.setPixmap(pix.scaled(64, 64,
                                      Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_DESK_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_DESK_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        data = event.mimeData().data(_DESK_MIME)
        if not data:
            return
        source_pet_id = bytes(data).decode("utf-8", errors="ignore")
        if source_pet_id:
            self.drop_received.emit(source_pet_id, self._slot_index)
        event.acceptProposedAction()


class PetOfficeWidget(QWidget):
    """AudioMate Office page — drop-in replacement for the BUDDY settings list."""

    pet_clicked = pyqtSignal(str)              # pet_id → open training room
    pet_add_requested = pyqtSignal(str)        # kind ("main" | "sub")
    pet_delete_requested = pyqtSignal(str)
    pet_enable_toggled = pyqtSignal(str, bool)
    pet_dispatch_requested = pyqtSignal(str)   # pet_id (sub) → run its task
    desk_layout_changed = pyqtSignal(list)     # new desk_layout list of pet_ids
    floating_toggle_requested = pyqtSignal(bool)
    floating_pet_changed = pyqtSignal(str)      # pet_id shown by desktop floating window
    chat_clicked = pyqtSignal(str)             # chat_id
    skill_map_requested = pyqtSignal()          # user clicked "查看技能地图"

    def __init__(self, parent: QWidget | None = None, *, theme_mode: str = "light"):
        super().__init__(parent)
        self._pet_settings: dict = {
            "items": [],
            "active_main_id": "",
            "floating_pet_id": "",
            "floating_enabled": False,
        }
        self._chats_provider: Callable[[], list[dict]] | None = None
        self._capabilities_provider: Callable[[], dict] | None = None
        self._theme_mode = theme_mode if theme_mode in ("light", "dark") else "light"
        self._build_ui()
        self.apply_theme(self._theme_mode)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # ----- Centre: office grid -----
        center = QVBoxLayout()
        center.setSpacing(8)

        self._title_label = QLabel("AudioMate办公室", self)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._title_label.setObjectName("petOfficeTitle")
        center.addWidget(self._title_label)

        grid_frame = QFrame(self)
        grid_frame.setObjectName("petOfficeGrid")
        grid = QGridLayout(grid_frame)
        grid.setContentsMargins(20, 20, 20, 20)
        grid.setSpacing(14)
        self._desks: list[_PetDeskWidget] = []
        for idx in range(_GRID_SLOTS):
            desk = _PetDeskWidget(idx, grid_frame)
            desk.clicked.connect(self._on_desk_clicked)
            desk.empty_clicked.connect(self._on_empty_clicked)
            desk.context_requested.connect(self._on_desk_context)
            desk.drop_received.connect(self._on_desk_drop)
            row, col = divmod(idx, 3)
            grid.addWidget(desk, row, col)
            self._desks.append(desk)
        center.addWidget(grid_frame, 1)

        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.addWidget(QLabel("显示桌面悬浮窗", self))
        toggle_row.addStretch(1)
        toggle_row.addWidget(QLabel("桌面宠物", self))
        self._floating_pet_combo = QComboBox(self)
        self._floating_pet_combo.setObjectName("petFloatingCombo")
        self._floating_pet_combo.setMinimumWidth(150)
        self._floating_pet_combo.currentIndexChanged.connect(self._on_floating_pet_combo_changed)
        toggle_row.addWidget(self._floating_pet_combo)
        self._floating_btn = QPushButton("启用悬浮窗", self)
        self._floating_btn.setObjectName("secondaryBtn")
        self._floating_btn.setCheckable(True)
        self._floating_btn.toggled.connect(self._on_floating_toggled)
        toggle_row.addWidget(self._floating_btn)
        center.addLayout(toggle_row)

        root.addLayout(center, 2)

        # ----- Right: binding map + chats -----
        side = QVBoxLayout()
        side.setSpacing(10)

        bindings_frame = QFrame(self)
        bindings_frame.setObjectName("petOfficeCard")
        bindings_layout = QVBoxLayout(bindings_frame)
        bindings_layout.setContentsMargins(14, 12, 14, 12)
        bindings_layout.setSpacing(4)
        # Title row: label + 「技能地图」按钮 — 点击弹出可视化节点视图。
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        bindings_title = QLabel("全局绑定地图", bindings_frame)
        bindings_title.setObjectName("petOfficeCardTitle")
        title_row.addWidget(bindings_title)
        title_row.addStretch(1)
        skill_map_btn = QPushButton("查看技能地图", bindings_frame)
        skill_map_btn.setObjectName("secondaryBtn")
        skill_map_btn.clicked.connect(self.skill_map_requested.emit)
        title_row.addWidget(skill_map_btn)
        bindings_layout.addLayout(title_row)
        side.addWidget(bindings_frame)

        chats_frame = QFrame(self)
        chats_frame.setObjectName("petOfficeCard")
        chats_layout = QVBoxLayout(chats_frame)
        chats_layout.setContentsMargins(14, 12, 14, 12)
        chats_layout.setSpacing(6)
        chats_title = QLabel("对话明细", chats_frame)
        chats_title.setObjectName("petOfficeCardTitle")
        chats_layout.addWidget(chats_title)
        self._chats_list = QListWidget(chats_frame)
        self._chats_list.setObjectName("petOfficeChats")
        self._chats_list.itemActivated.connect(self._on_chat_activated)
        self._chats_list.itemClicked.connect(self._on_chat_activated)
        chats_layout.addWidget(self._chats_list, 1)
        side.addWidget(chats_frame, 1)

        side_container = QWidget(self)
        side_container.setMinimumWidth(280)
        side_container.setLayout(side)
        root.addWidget(side_container, 1)

    # ------------------------------------------------------------------
    # External setters
    # ------------------------------------------------------------------

    def set_chats_provider(self, provider: Callable[[], list[dict]] | None) -> None:
        self._chats_provider = provider
        self.refresh_chats()

    def set_capabilities_provider(self, provider: Callable[[], dict] | None) -> None:
        """Provider returns ``{"skills": [...], "plugins": [...]}`` lists of
        items (each dict with id/name) so the binding map can resolve names."""
        self._capabilities_provider = provider
        self.refresh_bindings_map()

    def set_pet_settings(self, settings: dict) -> None:
        self._pet_settings = dict(settings or {})
        self._refresh_grid()
        self._floating_pet_combo.blockSignals(True)
        self._floating_pet_combo.clear()
        items = list(self._pet_settings.get("items") or [])
        active_id = self._pet_settings.get("active_main_id") or ""
        floating_pet_id = self._pet_settings.get("floating_pet_id") or active_id
        current_index = -1
        for index, pet in enumerate(items):
            pet_id = pet.get("id") or ""
            if not pet_id:
                continue
            label = pet.get("name") or pet_id
            if pet.get("kind") == PET_KIND_MAIN:
                label = f"{label}（主）"
            self._floating_pet_combo.addItem(label, pet_id)
            if pet_id == floating_pet_id:
                current_index = self._floating_pet_combo.count() - 1
        if current_index >= 0:
            self._floating_pet_combo.setCurrentIndex(current_index)
        self._floating_pet_combo.blockSignals(False)
        self._floating_btn.blockSignals(True)
        self._floating_btn.setChecked(bool(self._pet_settings.get("floating_enabled")))
        self._floating_btn.setText(
            "悬浮窗：开" if self._floating_btn.isChecked() else "悬浮窗：关"
        )
        self._floating_btn.blockSignals(False)
        self.refresh_bindings_map()

    def refresh_chats(self) -> None:
        self._chats_list.clear()
        chats = []
        if self._chats_provider is not None:
            try:
                chats = list(self._chats_provider() or [])
            except Exception:
                chats = []
        if not chats:
            placeholder = QListWidgetItem("还没有对话")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._chats_list.addItem(placeholder)
            return
        for chat in chats[:20]:
            title = (chat.get("title") or "未命名").strip() or "未命名"
            updated = chat.get("updated_at") or ""
            item = QListWidgetItem(f"{title}\n{updated[:19]}")
            item.setData(Qt.ItemDataRole.UserRole, chat.get("id", ""))
            self._chats_list.addItem(item)

    def refresh_bindings_map(self) -> None:
        """No-op kept for backwards compatibility.

        The text-mode binding overview was removed in favour of the visual
        "查看技能地图" dialog; callers (set_pet_settings, MainWindow refresh)
        still invoke this method, so we accept and ignore the call.
        """
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_grid(self) -> None:
        items = list(self._pet_settings.get("items") or [])
        active_id = self._pet_settings.get("active_main_id") or ""
        floating_pet_id = self._pet_settings.get("floating_pet_id") or active_id
        items_by_id = {p.get("id"): p for p in items if p.get("id")}

        main_pets = [p for p in items if p.get("kind") == PET_KIND_MAIN]
        active_main = next((p for p in main_pets if p.get("id") == active_id), None)
        if active_main is None and main_pets:
            active_main = main_pets[0]

        if active_main is not None:
            self._title_label.setText(f"{active_main.get('name') or 'AudioMate'} 办公室")
        else:
            self._title_label.setText("AudioMate办公室")

        # Slot 1 (top-middle) is reserved for the active main pet.
        main_slot = 1
        slot_to_pet: dict[int, dict] = {}

        # Determine the order of "other" pets (everything that is not the active main).
        layout_order = [pid for pid in (self._pet_settings.get("desk_layout") or [])
                        if pid in items_by_id]
        # Build the set of "other" pet ids (excluding active main).
        other_ids = [p.get("id") for p in items if p.get("id")
                     and (active_main is None or p.get("id") != active_main.get("id"))]
        # Take layout entries first (preserving user order), then any new pets at the end.
        ordered_other_ids: list[str] = []
        seen: set[str] = set()
        for pid in layout_order:
            if pid in other_ids and pid not in seen:
                ordered_other_ids.append(pid)
                seen.add(pid)
        for pid in other_ids:
            if pid not in seen:
                ordered_other_ids.append(pid)
                seen.add(pid)

        # Fill slots: main_slot reserved; iterate other slots in row-major order.
        other_iter = iter(ordered_other_ids)
        for slot in range(len(self._desks)):
            if slot == main_slot:
                continue
            try:
                next_id = next(other_iter)
            except StopIteration:
                break
            slot_to_pet[slot] = items_by_id[next_id]
        if active_main is not None:
            slot_to_pet[main_slot] = active_main

        for slot, desk in enumerate(self._desks):
            pet = slot_to_pet.get(slot)
            if pet is None:
                desk.set_empty()
            else:
                desk.set_pet(pet, is_main=(slot == main_slot and active_main is not None
                                            and pet.get("id") == active_main.get("id")),
                             is_desktop=(pet.get("id") == floating_pet_id))

    def _on_desk_clicked(self, pet_id: str) -> None:
        if pet_id:
            self.pet_clicked.emit(pet_id)

    def _on_empty_clicked(self, slot_index: int) -> None:
        kind = self._ask_pet_kind()
        if kind:
            self.pet_add_requested.emit(kind)

    def _ask_pet_kind(self) -> str:
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setWindowTitle("添加宠物")
        box.setText("AudioMate 主工位固定。请选择要添加的副宠类型：")
        sub_btn = box.addButton("副宠（子 Agent）", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is sub_btn:
            return PET_KIND_SUB
        return ""

    def _on_desk_drop(self, source_pet_id: str, target_slot: int) -> None:
        if not source_pet_id:
            return
        # Build the current ordered list (of pet ids in displayed slot order,
        # skipping the reserved main slot), then move source to target_slot's
        # position within that ordered list.
        items_by_id = {p.get("id"): p for p in (self._pet_settings.get("items") or []) if p.get("id")}
        if source_pet_id not in items_by_id:
            return
        # If the source is the active main, treat the drop as "demote + reorder":
        # demotion happens via separate menu action; here we just decline the drop.
        active_id = self._pet_settings.get("active_main_id") or ""
        if source_pet_id == active_id:
            return

        # Current visible order of "other" pets (in slot order, skipping main_slot=1).
        main_slot = 1
        current_order: list[str] = []
        for slot in range(len(self._desks)):
            if slot == main_slot:
                continue
            pid = self._desks[slot].pet_id()
            if pid:
                current_order.append(pid)

        if source_pet_id in current_order:
            current_order.remove(source_pet_id)

        # Compute target position in this "other" list from the target slot index.
        other_slots = [s for s in range(len(self._desks)) if s != main_slot]
        try:
            target_pos = other_slots.index(target_slot)
        except ValueError:
            target_pos = len(current_order)
        # Cap to end of list.
        target_pos = max(0, min(target_pos, len(current_order)))
        current_order.insert(target_pos, source_pet_id)
        self.desk_layout_changed.emit(current_order)

    def _on_desk_context(self, pet_id: str, global_pos) -> None:
        if not pet_id:
            return
        pet = next((p for p in self._pet_settings.get("items") or [] if p.get("id") == pet_id), None)
        if pet is None:
            return
        is_main = pet.get("kind") == PET_KIND_MAIN
        is_fixed = is_fixed_default_pet(pet_id)
        active_id = self._pet_settings.get("active_main_id") or ""
        floating_pet_id = self._pet_settings.get("floating_pet_id") or active_id
        menu = QMenu(self)
        open_act = menu.addAction("打开修炼室")
        dispatch_act = None
        if not is_main and (pet.get("task_template") or "").strip():
            dispatch_act = menu.addAction("派遣此副宠执行任务")
        desktop_act = None
        if pet_id == floating_pet_id:
            current_desktop_act = menu.addAction("已在桌面显示")
            current_desktop_act.setEnabled(False)
        else:
            desktop_act = menu.addAction("显示在桌面")
        toggle_act = menu.addAction("停用" if pet.get("enabled", True) else "启用")
        menu.addSeparator()
        delete_act = None
        if not is_fixed:
            delete_act = menu.addAction("删除")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen == open_act:
            self.pet_clicked.emit(pet_id)
        elif dispatch_act is not None and chosen == dispatch_act:
            self.pet_dispatch_requested.emit(pet_id)
        elif desktop_act is not None and chosen == desktop_act:
            self.floating_pet_changed.emit(pet_id)
        elif chosen == toggle_act:
            self.pet_enable_toggled.emit(pet_id, not bool(pet.get("enabled", True)))
        elif delete_act is not None and chosen == delete_act:
            self.pet_delete_requested.emit(pet_id)

    def _on_floating_toggled(self, checked: bool) -> None:
        self._floating_btn.setText("悬浮窗：开" if checked else "悬浮窗：关")
        self.floating_toggle_requested.emit(bool(checked))

    def _on_floating_pet_combo_changed(self, _index: int) -> None:
        pet_id = self._floating_pet_combo.currentData()
        if pet_id:
            self.floating_pet_changed.emit(str(pet_id))

    def _on_chat_activated(self, item: QListWidgetItem) -> None:
        chat_id = item.data(Qt.ItemDataRole.UserRole) if item else ""
        if chat_id:
            self.chat_clicked.emit(str(chat_id))

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def apply_theme(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode if theme_mode in ("light", "dark") else "light"
        self.setStyleSheet(_office_stylesheet(self._theme_mode))


def _office_stylesheet(theme_mode: str) -> str:
    if theme_mode == "dark":
        return (
            "PetOfficeWidget { background: #1F2937; color: #F3F4F6; }"
            "QLabel { color: #F3F4F6; }"
            "QLabel#petOfficeTitle { font-size: 18px; font-weight: 600; color: #F9FAFB; }"
            "QFrame#petOfficeGrid { background: #111827; border: 1px solid #374151;"
            " border-radius: 14px; }"
            "QFrame#petOfficeCard { background: #111827; border: 1px solid #374151;"
            " border-radius: 10px; }"
            "QLabel#petOfficeCardTitle { font-weight: 600; color: #F9FAFB; }"
            "QListWidget#petOfficeChats { border: none; background: transparent;"
            " color: #F3F4F6; }"
            "QListWidget#petOfficeChats::item { padding: 8px 4px;"
            " border-bottom: 1px solid #374151; }"
            "QListWidget#petOfficeChats::item:selected { background: #1E3A8A; }"
            "QFrame#petDeskCard { background: #1F2937; border: 1px dashed #374151;"
            " border-radius: 12px; }"
            "QFrame#petDeskCard[deskState=\"occupied\"] { background: #111827;"
            " border: 1px solid #374151; }"
            "QFrame#petDeskCard[deskState=\"main\"] { background: #1E3A8A;"
            " border: 2px solid #3B82F6; }"
            "QFrame#petDeskCard[deskState=\"add\"] { background: #1F2937;"
            " border: 1px dashed #3B82F6; }"
            "QLabel#petDeskAvatar { background: transparent; color: #9CA3AF;"
            " font-size: 11px; }"
            "QLabel#petDeskAvatar[avatarState=\"initial\"] { background: #5B8FE8;"
            " color: white; font-size: 28px; font-weight: 600; border-radius: 48px; }"
            "QLabel#petDeskAvatar[avatarState=\"add\"] { background: transparent;"
            " color: #60A5FA; font-size: 32px; font-weight: 600; }"
            "QLabel#petDeskName { color: #F3F4F6; font-size: 12px; }"
            "QLabel#petDeskRole { color: #9CA3AF; font-size: 10px; }"
            "QPushButton { background: #374151; color: #F3F4F6;"
            " border: 1px solid #4B5563; border-radius: 6px; padding: 5px 14px; }"
            "QPushButton:hover { background: #4B5563; }"
            "QPushButton#secondaryBtn { background: transparent; color: #93C5FD;"
            " border: 1px solid #1E40AF; }"
            "QPushButton#secondaryBtn:hover { background: #1E3A8A; }"
            "QPushButton#secondaryBtn:checked { background: #2563EB; color: white;"
            " border: 1px solid #2563EB; }"
        )
    return (
        "PetOfficeWidget { background: #FFFFFF; color: #111827; }"
        "QLabel { color: #111827; }"
        "QLabel#petOfficeTitle { font-size: 18px; font-weight: 600; color: #111827; }"
        "QFrame#petOfficeGrid { background: #FFFFFF; border: 1px solid #E5E7EB;"
        " border-radius: 14px; }"
        "QFrame#petOfficeCard { background: #FFFFFF; border: 1px solid #E5E7EB;"
        " border-radius: 10px; }"
        "QLabel#petOfficeCardTitle { font-weight: 600; color: #111827; }"
        "QListWidget#petOfficeChats { border: none; background: transparent;"
        " color: #111827; }"
        "QListWidget#petOfficeChats::item { padding: 8px 4px;"
        " border-bottom: 1px solid #F3F4F6; }"
        "QListWidget#petOfficeChats::item:selected { background: #DBEAFE; }"
        "QFrame#petDeskCard { background: #FAFAFA; border: 1px dashed #D1D5DB;"
        " border-radius: 12px; }"
        "QFrame#petDeskCard[deskState=\"occupied\"] { background: #F3F4F6;"
        " border: 1px solid #D1D5DB; }"
        "QFrame#petDeskCard[deskState=\"main\"] { background: #DBEAFE;"
        " border: 2px solid #2563EB; }"
        "QFrame#petDeskCard[deskState=\"add\"] { background: #FAFAFA;"
        " border: 1px dashed #93C5FD; }"
        "QLabel#petDeskAvatar { background: transparent; color: #9CA3AF;"
        " font-size: 11px; }"
        "QLabel#petDeskAvatar[avatarState=\"initial\"] { background: #5B8FE8;"
        " color: white; font-size: 28px; font-weight: 600; border-radius: 48px; }"
        "QLabel#petDeskAvatar[avatarState=\"add\"] { background: transparent;"
        " color: #2563EB; font-size: 32px; font-weight: 600; }"
        "QLabel#petDeskName { color: #111827; font-size: 12px; }"
        "QLabel#petDeskRole { color: #6B7280; font-size: 10px; }"
        "QPushButton { background: #F3F4F6; color: #111827;"
        " border: 1px solid #D1D5DB; border-radius: 6px; padding: 5px 14px; }"
        "QPushButton:hover { background: #E5E7EB; }"
        "QPushButton#secondaryBtn { background: transparent; color: #2563EB;"
        " border: 1px solid #DBEAFE; }"
        "QPushButton#secondaryBtn:hover { background: #EFF6FF; }"
        "QPushButton#secondaryBtn:checked { background: #2563EB; color: white;"
        " border: 1px solid #2563EB; }"
    )


__all__ = ["PetOfficeWidget"]

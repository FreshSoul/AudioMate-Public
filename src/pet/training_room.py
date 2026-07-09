"""Pet 修炼室 dialog — persona, capabilities, sprites for a single pet.

Single tab "能力" (Capabilities): persona prompt, skill/plugin selection,
plus sub-pet schedule + task template. Sprite uploads and the AI "describe
to generate" flow live in the left column.
"""

from __future__ import annotations

import os
import urllib.request
import uuid
from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import QTime
from PyQt6.QtGui import QMovie, QPixmap

from src.pet.store import PET_KIND_MAIN, PET_KIND_SUB


_SCHEDULE_TYPE_LABELS = {
    "none": "不调度",
    "interval": "按间隔",
    "daily": "每日",
    "weekly": "每周",
    "once": "单次",
}

_WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

_SPRITE_STATES: list[tuple[str, str]] = [
    ("idle", "待机"),
    ("working", "工作"),
    ("moving", "移动"),
]

_STATE_MODIFIERS = {
    "idle": "standing still, calm relaxed pose, looking forward",
    "working": "focused at a computer desk, typing, concentrated expression",
    "moving": "walking sideways, mid-stride, dynamic pose",
}


class PetTrainingRoomDialog(QDialog):
    """Edit a single pet's metadata, capabilities, and view its stats."""

    pet_saved = pyqtSignal(dict)

    def __init__(
        self,
        pet: dict,
        *,
        skills: list[dict] | None = None,
        plugins: list[dict] | None = None,
        llm_service: Any = None,
        image_model_default: str = "gpt-image-2",
        on_image_model_changed: Any = None,
        available_models: list[str] | None = None,
        main_llm_defaults: dict | None = None,
        bound_elsewhere: dict | None = None,
        orphans: dict | None = None,
        active_main_id: str = "",
        theme_mode: str = "light",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._pet = dict(pet or {})
        self._kind = self._pet.get("kind") or PET_KIND_SUB
        # External-agent pets (Codex / ClaudeCode) dispatch to local CLIs and
        # never use the LLM — they get no model-config block.
        self._is_external = bool((self._pet.get("external_agent") or "").strip())
        self._skills = skills or []
        self._plugins = plugins or []
        self._llm_service = llm_service
        self._image_model_default = (image_model_default or "gpt-image-2").strip() or "gpt-image-2"
        self._on_image_model_changed = on_image_model_changed
        self._available_models = [m for m in (available_models or []) if m]
        self._main_llm_defaults = main_llm_defaults if isinstance(main_llm_defaults, dict) else {}
        bound = bound_elsewhere if isinstance(bound_elsewhere, dict) else {}
        self._bound_skill_owners: dict = bound.get("skills") or {}
        self._bound_plugin_owners: dict = bound.get("plugins") or {}
        orphan_block = orphans if isinstance(orphans, dict) else {}
        self._orphan_skill_ids: list[str] = list(orphan_block.get("skill_ids") or [])
        self._orphan_plugin_ids: list[str] = list(orphan_block.get("plugin_ids") or [])
        self._active_main_id: str = (active_main_id or "").strip()
        self._theme_mode = theme_mode if theme_mode in ("light", "dark") else "light"
        self._weekday_checks: list[QCheckBox] = []
        self._sprite_paths: dict[str, str] = {"idle": "", "working": "", "moving": ""}
        self._sprite_previews: dict[str, QLabel] = {}
        self._sprite_path_labels: dict[str, QLabel] = {}
        self._preview_movies: dict[str, QMovie] = {}

        self.setWindowTitle(f"修炼室 · {self._pet.get('name') or 'Buddy'}")
        self.setModal(True)
        self.resize(840, 620)

        self._build_ui()
        self._populate_from_pet()
        self.apply_theme(self._theme_mode)

    def apply_theme(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode if theme_mode in ("light", "dark") else "light"
        self.setStyleSheet(_pet_dialog_stylesheet(self._theme_mode))

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        # ---- Left column: sprites (3 states) + identity ----
        left = QFrame(self)
        left.setFixedWidth(260)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        title = QLabel("形态（idle / working / moving）", left)
        title.setObjectName("petCardTitle")
        left_layout.addWidget(title)

        ai_btn = QPushButton("✨ 用 AI 描述生成", left)
        ai_btn.setObjectName("aiGenBtn")
        ai_btn.clicked.connect(self._on_ai_generate)
        left_layout.addWidget(ai_btn)

        for state_key, state_label in _SPRITE_STATES:
            row_frame = QFrame(left)
            row_frame.setObjectName("petSpriteSlot")
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(8, 8, 8, 8)
            row_layout.setSpacing(8)

            preview = QLabel(row_frame)
            preview.setFixedSize(64, 64)
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setText(state_label)
            self._sprite_previews[state_key] = preview
            row_layout.addWidget(preview)

            right_col = QVBoxLayout()
            right_col.setSpacing(4)
            label = QLabel(state_label, row_frame)
            label.setObjectName("petCardTitle")
            right_col.addWidget(label)

            path_label = QLabel("（未设置）", row_frame)
            path_label.setProperty("petPathLabel", True)
            path_label.setWordWrap(True)
            self._sprite_path_labels[state_key] = path_label
            right_col.addWidget(path_label)

            upload_btn = QPushButton("上传 GIF/图片", row_frame)
            upload_btn.setObjectName("secondaryBtn")
            upload_btn.clicked.connect(lambda _checked=False, k=state_key: self._on_upload_sprite(k))
            right_col.addWidget(upload_btn)

            row_layout.addLayout(right_col, 1)
            left_layout.addWidget(row_frame)

        identity_form = QFormLayout()
        identity_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._name_edit = QLineEdit(left)
        self._name_edit.setPlaceholderText("给宠物起个名字…")
        identity_form.addRow("名字", self._name_edit)
        self._kind_label = QLabel("主宠" if self._kind == PET_KIND_MAIN else "副宠", left)
        self._kind_label.setObjectName("petCardTitle")
        identity_form.addRow("类型", self._kind_label)
        self._enabled_check = QCheckBox("启用", left)
        identity_form.addRow("状态", self._enabled_check)
        left_layout.addLayout(identity_form)
        left_layout.addStretch(1)

        root.addWidget(left)

        # ---- Right column: tabs ----
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_capability_tab(), "能力")
        right.addWidget(self._tabs, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_btn = QPushButton("取消", self)
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)
        save_btn = QPushButton("保存", self)
        save_btn.setObjectName("primaryBtn")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        button_row.addWidget(save_btn)
        right.addLayout(button_row)

        root.addLayout(right, 1)

    def _build_capability_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        layout.addWidget(QLabel("人格 / Persona Prompt：", tab))
        self._persona_edit = QPlainTextEdit(tab)
        self._persona_edit.setPlaceholderText(
            "描述这只宠物的语气、专长或工作方式。会注入到主宠对话的 system prompt。"
        )
        self._persona_edit.setFixedHeight(96)
        layout.addWidget(self._persona_edit)

        # Skill / plugin selection
        skill_name_map = {s.get("id"): s.get("name") or s.get("id", "") for s in self._skills}
        plugin_name_map = {p.get("id"): p.get("name") or p.get("id", "") for p in self._plugins}
        current_pet_id = self._pet.get("id", "")
        capability_row = QHBoxLayout()
        capability_row.setSpacing(12)

        skill_box = QVBoxLayout()
        skill_box.addWidget(QLabel("绑定 Skill", tab))
        self._skill_list = QListWidget(tab)
        self._skill_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for skill in self._skills:
            sid = skill.get("id", "")
            owner = self._bound_skill_owners.get(sid)
            owner_elsewhere = owner and owner.get("pet_id") and owner.get("pet_id") != current_pet_id
            label = skill.get("name", sid)
            if owner_elsewhere:
                label = f"{label}  (已绑定: {owner.get('pet_name') or '其他宠物'})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, sid)
            if owner_elsewhere:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
            self._skill_list.addItem(item)
        if not self._skills:
            self._skill_list.addItem(QListWidgetItem("（暂无 Skill）"))
            self._skill_list.setEnabled(False)
        skill_box.addWidget(self._skill_list)
        capability_row.addLayout(skill_box, 1)

        plugin_box = QVBoxLayout()
        plugin_box.addWidget(QLabel("绑定 Plugin", tab))
        self._plugin_list = QListWidget(tab)
        self._plugin_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for plugin in self._plugins:
            pid = plugin.get("id", "")
            owner = self._bound_plugin_owners.get(pid)
            owner_elsewhere = owner and owner.get("pet_id") and owner.get("pet_id") != current_pet_id
            label = plugin.get("name", pid)
            if owner_elsewhere:
                label = f"{label}  (已绑定: {owner.get('pet_name') or '其他宠物'})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, pid)
            if owner_elsewhere:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
            self._plugin_list.addItem(item)
        if not self._plugins:
            self._plugin_list.addItem(QListWidgetItem("（暂无 Plugin）"))
            self._plugin_list.setEnabled(False)
        plugin_box.addWidget(self._plugin_list)
        capability_row.addLayout(plugin_box, 1)

        layout.addLayout(capability_row)

        # Sub-pet only schedule + task template
        if self._kind == PET_KIND_SUB:
            layout.addWidget(self._build_schedule_block(tab))
            if not self._is_external:
                layout.addWidget(self._build_llm_block(tab))

        layout.addStretch(1)
        return tab

    def _build_schedule_block(self, tab: QWidget) -> QWidget:
        block = QFrame(tab)
        block.setObjectName("petSectionCard")
        block.setFrameShape(QFrame.Shape.NoFrame)
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(14, 14, 14, 14)
        block_layout.setSpacing(8)

        title = QLabel("调度规则 & 任务模板", block)
        title.setObjectName("petSectionTitle")
        block_layout.addWidget(title)

        schedule_form = QFormLayout()
        self._schedule_type_combo = QComboBox(block)
        for key, label in _SCHEDULE_TYPE_LABELS.items():
            self._schedule_type_combo.addItem(label, key)
        self._schedule_type_combo.currentIndexChanged.connect(self._update_schedule_visibility)
        schedule_form.addRow("调度方式", self._schedule_type_combo)

        self._interval_spin = QSpinBox(block)
        self._interval_spin.setRange(1, 24 * 60)
        self._interval_spin.setSuffix(" 分钟")
        schedule_form.addRow("间隔", self._interval_spin)
        self._interval_label = schedule_form.labelForField(self._interval_spin)

        self._time_edit = QTimeEdit(block)
        self._time_edit.setDisplayFormat("HH:mm")
        schedule_form.addRow("时间", self._time_edit)
        self._time_label = schedule_form.labelForField(self._time_edit)

        self._weekdays_widget = QWidget(block)
        weekday_layout = QHBoxLayout(self._weekdays_widget)
        weekday_layout.setContentsMargins(0, 0, 0, 0)
        for label in _WEEKDAY_LABELS:
            check = QCheckBox(label, self._weekdays_widget)
            self._weekday_checks.append(check)
            weekday_layout.addWidget(check)
        weekday_layout.addStretch(1)
        schedule_form.addRow("星期", self._weekdays_widget)
        self._weekday_form_label = schedule_form.labelForField(self._weekdays_widget)

        block_layout.addLayout(schedule_form)

        block_layout.addWidget(QLabel("任务模板（自动注入到对话）", block))
        self._task_template_edit = QPlainTextEdit(block)
        self._task_template_edit.setPlaceholderText("例如：列出当前 Wwise 工程中所有的 Sound 对象数量。")
        self._task_template_edit.setFixedHeight(96)
        block_layout.addWidget(self._task_template_edit)

        return block

    def _build_llm_block(self, tab: QWidget) -> QWidget:
        """Sub-pet LLM override: API endpoint + model. Empty = inherit main."""
        block = QFrame(tab)
        block.setObjectName("petSectionCard")
        block.setFrameShape(QFrame.Shape.NoFrame)
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(14, 14, 14, 14)
        block_layout.setSpacing(8)

        title = QLabel("模型配置（留空＝跟随主宠）", block)
        title.setObjectName("petSectionTitle")
        block_layout.addWidget(title)

        main_model = (self._main_llm_defaults.get("model") or "").strip()
        main_base_url = (self._main_llm_defaults.get("base_url") or "").strip()

        form = QFormLayout()
        self._llm_model_combo = QComboBox(block)
        self._llm_model_combo.setEditable(True)
        self._llm_model_combo.addItem("")
        for model_name in self._available_models:
            self._llm_model_combo.addItem(model_name)
        line_edit = self._llm_model_combo.lineEdit()
        if line_edit is not None:
            placeholder = f"跟随主宠（当前：{main_model}）" if main_model else "跟随主宠"
            line_edit.setPlaceholderText(placeholder)
        form.addRow("模型", self._llm_model_combo)

        self._llm_base_url_edit = QLineEdit(block)
        self._llm_base_url_edit.setPlaceholderText(
            f"跟随主宠（当前：{main_base_url}）" if main_base_url else "跟随主宠"
        )
        form.addRow("Base URL", self._llm_base_url_edit)

        self._llm_api_key_edit = QLineEdit(block)
        self._llm_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_api_key_edit.setPlaceholderText("留空＝使用主配置密钥")
        form.addRow("API Key", self._llm_api_key_edit)

        block_layout.addLayout(form)
        return block

    # ------------------------------------------------------------------
    # Population & UI sync
    # ------------------------------------------------------------------

    def _populate_from_pet(self) -> None:
        self._name_edit.setText(self._pet.get("name", ""))
        self._enabled_check.setChecked(bool(self._pet.get("enabled", True)))
        sprites = self._pet.get("sprites") or {}
        # Migrate legacy avatar_path → idle if sprites are missing.
        idle_path = sprites.get("idle") or self._pet.get("avatar_path", "") or ""
        self._sprite_paths = {
            "idle": idle_path,
            "working": sprites.get("working", "") or "",
            "moving": sprites.get("moving", "") or "",
        }
        for state, _label in _SPRITE_STATES:
            self._set_sprite_preview(state, self._sprite_paths[state])
        self._persona_edit.setPlainText(self._pet.get("persona_prompt", ""))

        capabilities = self._pet.get("capabilities") or {}
        skill_ids = set(capabilities.get("skill_ids") or [])
        plugin_ids = set(capabilities.get("plugin_ids") or [])
        for index in range(self._skill_list.count()):
            item = self._skill_list.item(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                checked = item.data(Qt.ItemDataRole.UserRole) in skill_ids
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        for index in range(self._plugin_list.count()):
            item = self._plugin_list.item(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                checked = item.data(Qt.ItemDataRole.UserRole) in plugin_ids
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

        if self._kind == PET_KIND_SUB:
            schedule = self._pet.get("schedule") or {}
            schedule_type = (schedule.get("schedule_type") or "none").lower()
            index = self._schedule_type_combo.findData(schedule_type)
            self._schedule_type_combo.setCurrentIndex(index if index >= 0 else 0)
            self._interval_spin.setValue(int(schedule.get("interval_minutes") or 30))
            time_text = schedule.get("time") or "09:00"
            try:
                hour, minute = time_text.split(":")
                self._time_edit.setTime(QTime(int(hour), int(minute)))
            except (ValueError, TypeError):
                self._time_edit.setTime(QTime(9, 0))
            weekdays = set(schedule.get("weekdays") or [])
            for index, check in enumerate(self._weekday_checks):
                check.setChecked(index in weekdays)
            self._task_template_edit.setPlainText(self._pet.get("task_template", ""))
            if not self._is_external:
                llm = self._pet.get("llm") or {}
                self._llm_model_combo.setCurrentText(llm.get("model", "") or "")
                self._llm_base_url_edit.setText(llm.get("base_url", "") or "")
                self._llm_api_key_edit.setText(llm.get("api_key", "") or "")
            self._update_schedule_visibility()

    def _set_sprite_preview(self, state: str, path: str) -> None:
        self._sprite_paths[state] = path or ""
        preview = self._sprite_previews.get(state)
        path_label = self._sprite_path_labels.get(state)
        if preview is None:
            return
        # Tear down any previous animation for this slot.
        old_movie = self._preview_movies.pop(state, None)
        if old_movie is not None:
            old_movie.stop()
            old_movie.deleteLater()
        preview.setMovie(None)
        if path and os.path.isfile(path):
            if path.lower().endswith(".gif"):
                movie = QMovie(path)
                movie.setScaledSize(preview.size())
                preview.setMovie(movie)
                movie.start()
                self._preview_movies[state] = movie
            else:
                pix = QPixmap(path)
                if not pix.isNull():
                    pix = pix.scaled(
                        preview.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    preview.setPixmap(pix)
                else:
                    preview.setPixmap(QPixmap())
                    preview.setText("无效图片")
            if path_label is not None:
                path_label.setText(os.path.basename(path))
        else:
            preview.setPixmap(QPixmap())
            label_text = {"idle": "待机", "working": "工作", "moving": "移动"}.get(state, state)
            preview.setText(label_text)
            if path_label is not None:
                path_label.setText("（未设置）")

    def _update_schedule_visibility(self) -> None:
        if self._kind != PET_KIND_SUB:
            return
        schedule_type = self._schedule_type_combo.currentData()
        show_interval = schedule_type == "interval"
        show_time = schedule_type in {"daily", "weekly", "once"}
        show_weekdays = schedule_type == "weekly"
        for widget, label in (
            (self._interval_spin, getattr(self, "_interval_label", None)),
            (self._time_edit, getattr(self, "_time_label", None)),
            (self._weekdays_widget, getattr(self, "_weekday_form_label", None)),
        ):
            if widget is None:
                continue
            visible = (
                (widget is self._interval_spin and show_interval)
                or (widget is self._time_edit and show_time)
                or (widget is self._weekdays_widget and show_weekdays)
            )
            widget.setVisible(visible)
            if label is not None:
                label.setVisible(visible)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_upload_sprite(self, state: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"选择 {state} 形态图片 / GIF",
            "",
            "Images / Animations (*.gif *.png *.jpg *.jpeg *.bmp *.svg)",
        )
        if path:
            self._set_sprite_preview(state, path)

    def _on_ai_generate(self) -> None:
        if self._llm_service is None or getattr(self._llm_service, "client", None) is None:
            QMessageBox.warning(
                self,
                "未配置 LLM",
                "请先在设置中配置 API Key 后再使用 AI 生成形态。",
            )
            return
        dialog = _AIGenerateSpritesDialog(
            self._llm_service,
            self._pet.get("id") or "",
            image_model_default=self._image_model_default,
            on_model_changed=self._on_image_model_changed,
            theme_mode=self._theme_mode,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._image_model_default = dialog.image_model() or self._image_model_default
            paths = dialog.result_paths()
            for state in ("idle", "working", "moving"):
                p = paths.get(state)
                if p:
                    self._set_sprite_preview(state, p)

    def _collect_capabilities(self) -> dict:
        skill_ids: list[str] = []
        plugin_ids: list[str] = []
        for index in range(self._skill_list.count()):
            item = self._skill_list.item(index)
            if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                continue
            if item.checkState() == Qt.CheckState.Checked:
                value = item.data(Qt.ItemDataRole.UserRole)
                if value:
                    skill_ids.append(value)
        for index in range(self._plugin_list.count()):
            item = self._plugin_list.item(index)
            if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                continue
            if item.checkState() == Qt.CheckState.Checked:
                value = item.data(Qt.ItemDataRole.UserRole)
                if value:
                    plugin_ids.append(value)
        return {"skill_ids": skill_ids, "plugin_ids": plugin_ids}

    def _collect_schedule(self) -> dict:
        if self._kind != PET_KIND_SUB:
            return {}
        schedule_type = self._schedule_type_combo.currentData() or "none"
        if schedule_type == "none":
            return {"schedule_type": "none"}
        payload: dict[str, Any] = {"schedule_type": schedule_type}
        if schedule_type == "interval":
            payload["interval_minutes"] = int(self._interval_spin.value())
        if schedule_type in {"daily", "weekly", "once"}:
            time = self._time_edit.time()
            payload["time"] = f"{time.hour():02d}:{time.minute():02d}"
        if schedule_type == "weekly":
            weekdays = [i for i, check in enumerate(self._weekday_checks) if check.isChecked()]
            payload["weekdays"] = weekdays
        # Carry the previously assigned scheduler task_id so PetService can
        # update rather than create a new entry.
        prior_task_id = (self._pet.get("schedule") or {}).get("task_id", "")
        if prior_task_id:
            payload["task_id"] = prior_task_id
        return payload

    def _on_save(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "校验", "请填写宠物名字。")
            return
        merged = dict(self._pet)
        merged["name"] = name
        merged["enabled"] = self._enabled_check.isChecked()
        merged["sprites"] = dict(self._sprite_paths)
        merged["avatar_path"] = self._sprite_paths.get("idle", "") or merged.get("avatar_path", "")
        merged["persona_prompt"] = self._persona_edit.toPlainText().strip()
        merged["capabilities"] = self._collect_capabilities()
        if self._kind == PET_KIND_SUB:
            merged["schedule"] = self._collect_schedule()
            merged["task_template"] = self._task_template_edit.toPlainText().strip()
            if not self._is_external:
                merged["llm"] = {
                    "base_url": self._llm_base_url_edit.text().strip(),
                    "api_key": self._llm_api_key_edit.text().strip(),
                    "model": self._llm_model_combo.currentText().strip(),
                }
        merged["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.pet_saved.emit(merged)
        self.accept()


__all__ = ["PetTrainingRoomDialog"]


def _sprite_output_dir(pet_id: str) -> str:
    base = os.path.join(os.path.expanduser("~"), ".audiomate", "pet_sprites", pet_id or "default")
    os.makedirs(base, exist_ok=True)
    return base


def _make_background_transparent(path: str, tolerance: int = 28) -> None:
    """Best-effort background removal via flood-fill from the four corners.

    Samples the four corner pixels, treats them as background, then sets the
    alpha of every connected pixel within ``tolerance`` (per-channel) to 0.
    Works well when the generator returns a near-uniform solid backdrop
    (white / grey / light blue); leaves complex backgrounds mostly intact.
    Overwrites the file in place. Requires Pillow.
    """
    try:
        from PIL import Image
    except Exception:
        return
    img = Image.open(path).convert("RGBA")
    pixels = img.load()
    w, h = img.size
    if w == 0 or h == 0:
        return

    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    # If corners disagree wildly, skip (the image probably has no flat bg).
    corner_colors = [pixels[x, y][:3] for x, y in corners]
    avg = tuple(sum(c[i] for c in corner_colors) // 4 for i in range(3))
    if any(abs(c[i] - avg[i]) > tolerance * 2 for c in corner_colors for i in range(3)):
        return

    # Iterative 4-connected flood-fill from each corner seed.
    visited = bytearray(w * h)
    def _is_bg(rgb):
        return all(abs(rgb[i] - avg[i]) <= tolerance for i in range(3))

    from collections import deque
    queue: deque = deque()
    for x, y in corners:
        if _is_bg(pixels[x, y][:3]):
            queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        if x < 0 or x >= w or y < 0 or y >= h:
            continue
        idx = y * w + x
        if visited[idx]:
            continue
        r, g, b, _a = pixels[x, y]
        if not _is_bg((r, g, b)):
            continue
        visited[idx] = 1
        pixels[x, y] = (r, g, b, 0)
        queue.append((x + 1, y))
        queue.append((x - 1, y))
        queue.append((x, y + 1))
        queue.append((x, y - 1))

    img.save(path, "PNG")


class _SpriteGenerationThread(QThread):
    """Generate 3 PNG sprites (idle/working/moving) via OpenAI image API."""

    finished_with_paths = pyqtSignal(dict)
    failed = pyqtSignal(str, list)  # message, completed_states
    state_started = pyqtSignal(str, int, int)   # state, idx (1-based), total
    state_done = pyqtSignal(str, int, int)      # state, idx (1-based), total
    state_postprocess = pyqtSignal(str, int, int)  # state, idx, total — removing bg

    def __init__(self, llm_service, pet_id: str, description: str, image_model: str, parent=None):
        super().__init__(parent)
        self._llm_service = llm_service
        self._pet_id = pet_id
        self._description = (description or "").strip()
        self._image_model = (image_model or "").strip() or "gpt-image-2"

    def run(self) -> None:
        client = getattr(self._llm_service, "client", None)
        if client is None:
            self.failed.emit("LLM client 未初始化", [])
            return
        out_dir = _sprite_output_dir(self._pet_id)
        paths: dict[str, str] = {}
        completed: list[str] = []
        states = list(_STATE_MODIFIERS.items())
        total = len(states)
        for idx, (state, modifier) in enumerate(states, start=1):
            self.state_started.emit(state, idx, total)
            try:
                prompt = (
                    f"{self._description}, {modifier}, "
                    "2D character sprite, transparent background, full body, pixel art style"
                )
                resp = client.images.generate(
                    model=self._image_model,
                    prompt=prompt,
                    n=1,
                    size="1024x1024",
                )
                data = resp.data[0]
                url = getattr(data, "url", None)
                b64 = getattr(data, "b64_json", None)
                target = os.path.join(out_dir, f"{state}_{uuid.uuid4().hex[:8]}.png")
                if url:
                    with urllib.request.urlopen(url, timeout=60) as r:
                        with open(target, "wb") as f:
                            f.write(r.read())
                elif b64:
                    import base64
                    with open(target, "wb") as f:
                        f.write(base64.b64decode(b64))
                else:
                    raise RuntimeError("response missing url/b64_json")
                # Post-process: knock out near-uniform corner backgrounds so
                # the desktop pet shows only the subject.
                self.state_postprocess.emit(state, idx, total)
                try:
                    _make_background_transparent(target)
                except Exception:
                    # Non-fatal — keep the opaque image rather than failing.
                    pass
                paths[state] = target
                completed.append(state)
                self.state_done.emit(state, idx, total)
            except Exception as exc:
                self.failed.emit(f"生成 {state} 形态失败：{exc}", completed)
                return
        self.finished_with_paths.emit(paths)


class _AIGenerateSpritesDialog(QDialog):
    """Dialog: user enters a description, we call image API for 3 states."""

    def __init__(
        self,
        llm_service,
        pet_id: str,
        *,
        image_model_default: str = "gpt-image-2",
        on_model_changed: Any = None,
        theme_mode: str = "light",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("用 AI 描述生成宠物形态")
        self.setModal(True)
        self.resize(520, 400)
        self._llm_service = llm_service
        self._pet_id = pet_id
        self._on_model_changed = on_model_changed
        self._theme_mode = theme_mode if theme_mode in ("light", "dark") else "light"
        self._result: dict[str, str] = {}
        self._thread: _SpriteGenerationThread | None = None
        self._used_model: str = (image_model_default or "gpt-image-2").strip() or "gpt-image-2"
        self._progress_done: list[str] = []
        self._progress_current: str = ""
        self._progress_total: int = 3
        self._heartbeat_phase = 0
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(400)
        self._heartbeat.timeout.connect(self._on_heartbeat)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        model_label = QLabel("图像模型：", self)
        layout.addWidget(model_label)
        self._model_edit = QLineEdit(self)
        self._model_edit.setText(self._used_model)
        self._model_edit.setPlaceholderText("例如：gpt-image-2、dall-e-3、flux-schnell")
        layout.addWidget(self._model_edit)

        layout.addWidget(QLabel("描述你想要的宠物形象（外观、风格、颜色等）：", self))
        self._desc_edit = QPlainTextEdit(self)
        self._desc_edit.setPlaceholderText("例如：一只戴眼镜的橘猫，赛博朋克风格，蓝色发光眼睛")
        layout.addWidget(self._desc_edit, 1)

        self._status_label = QLabel("将分别生成「待机/工作/移动」三态。", self)
        self._status_label.setObjectName("petHintLabel")
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton("取消", self)
        cancel.setObjectName("secondaryBtn")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        self._gen_btn = QPushButton("生成", self)
        self._gen_btn.setObjectName("primaryBtn")
        self._gen_btn.setDefault(True)
        self._gen_btn.clicked.connect(self._on_generate)
        btn_row.addWidget(self._gen_btn)
        layout.addLayout(btn_row)

        self.apply_theme(self._theme_mode)

    def result_paths(self) -> dict[str, str]:
        return dict(self._result)

    def image_model(self) -> str:
        return self._used_model

    def apply_theme(self, theme_mode: str) -> None:
        self._theme_mode = theme_mode if theme_mode in ("light", "dark") else "light"
        self.setStyleSheet(_pet_dialog_stylesheet(self._theme_mode))

    def _on_generate(self) -> None:
        desc = self._desc_edit.toPlainText().strip()
        if not desc:
            QMessageBox.warning(self, "校验", "请填写描述。")
            return
        model_text = self._model_edit.text().strip() or "gpt-image-2"
        self._used_model = model_text
        self._gen_btn.setEnabled(False)
        self._progress_done = []
        self._progress_current = ""
        self._progress_total = 3
        self._heartbeat_phase = 0
        self._status_label.setText(
            f"准备用 {model_text} 生成「待机/工作/移动」三态…"
        )
        self._heartbeat.start()
        self._thread = _SpriteGenerationThread(self._llm_service, self._pet_id, desc, model_text, self)
        self._thread.state_started.connect(self._on_state_started)
        self._thread.state_postprocess.connect(self._on_state_postprocess)
        self._thread.state_done.connect(self._on_state_done)
        self._thread.finished_with_paths.connect(self._on_done)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    @staticmethod
    def _state_label(state: str) -> str:
        return {"idle": "待机", "working": "工作", "moving": "移动"}.get(state, state)

    def _render_progress(self, suffix: str = "") -> str:
        parts = []
        for s in ("idle", "working", "moving"):
            label = self._state_label(s)
            if s in self._progress_done:
                parts.append(f"✓ {label}")
            elif s == self._progress_current:
                parts.append(f"⏳ {label}")
            else:
                parts.append(f"· {label}")
        return "  ".join(parts) + suffix

    def _on_state_started(self, state: str, idx: int, total: int) -> None:
        self._progress_current = state
        self._progress_total = int(total or 3)
        self._heartbeat_phase = 0
        self._status_label.setText(
            self._render_progress(f"   ({idx}/{total} 正在生成 {self._state_label(state)})")
        )

    def _on_state_done(self, state: str, idx: int, total: int) -> None:
        if state not in self._progress_done:
            self._progress_done.append(state)
        if self._progress_current == state:
            self._progress_current = ""
        self._status_label.setText(
            self._render_progress(f"   ({idx}/{total} 完成)")
        )

    def _on_state_postprocess(self, state: str, idx: int, total: int) -> None:
        # Keep the current-state marker so the heartbeat keeps animating.
        self._progress_current = state
        self._status_label.setText(
            self._render_progress(f"   ({idx}/{total} 去除 {self._state_label(state)} 形态背景中…)")
        )

    def _on_heartbeat(self) -> None:
        if not self._progress_current:
            return
        self._heartbeat_phase = (self._heartbeat_phase + 1) % 4
        dots = "." * self._heartbeat_phase
        label = self._state_label(self._progress_current)
        self._status_label.setText(
            self._render_progress(f"   正在生成 {label}{dots}")
        )

    def _on_done(self, paths: dict) -> None:
        self._heartbeat.stop()
        self._result = dict(paths or {})
        if callable(self._on_model_changed):
            try:
                self._on_model_changed(self._used_model)
            except Exception:
                pass
        self.accept()

    def _on_failed(self, message: str, completed) -> None:
        self._heartbeat.stop()
        self._gen_btn.setEnabled(True)
        completed_text = ""
        if completed:
            completed_text = "（已完成：" + "、".join(self._state_label(s) for s in completed) + "）"
        self._status_label.setText("")
        QMessageBox.critical(self, "生成失败", f"{message}\n{completed_text}".strip())


# ---------------------------------------------------------------------------
# Themed stylesheets for the training-room family of dialogs
# ---------------------------------------------------------------------------


def _pet_dialog_stylesheet(theme_mode: str) -> str:
    """Apple-like rounded styling, matching the main UI's design language
    (large radii, soft low-alpha borders, purple accent #7D73FF~#A49BFF —
    see theme_manager.py)."""
    if theme_mode == "dark":
        return (
            # QWidget first, QDialog second — equal-specificity rules cascade
            # last-wins, and the dialog must keep its opaque base color.
            "QWidget { background: transparent; color: #E8EAF0; }"
            "QDialog { background: #1E1F22; }"
            "QLabel { color: #E8EAF0; font-size: 13px; background: transparent; }"
            "QLabel#petHintLabel, QLabel[petPathLabel=\"true\"] { color: #8B92A8; font-size: 11px; }"
            "QLabel#petCardTitle { color: #F5F6FA; font-weight: 600; font-size: 14px; }"
            "QLabel#petSectionTitle { color: #F5F6FA; font-weight: 600; font-size: 13px; }"
            "QLineEdit, QPlainTextEdit { background: #16171A; color: #E8EAF0;"
            " border: 1px solid rgba(119, 126, 165, 0.22); border-radius: 12px; padding: 7px 12px; }"
            "QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #8D86FF; }"
            "QComboBox { background: #16171A; color: #E8EAF0;"
            " border: 1px solid rgba(119, 126, 165, 0.22); border-radius: 12px; padding: 6px 12px; }"
            "QComboBox:focus { border: 1px solid #8D86FF; }"
            "QComboBox::drop-down { border: none; width: 24px; }"
            "QComboBox QAbstractItemView { background: #232733; color: #E8EAF0;"
            " border: 1px solid rgba(119, 126, 165, 0.25); border-radius: 10px; padding: 4px; outline: none; }"
            "QComboBox::item { padding: 7px 12px; border-radius: 6px; }"
            "QComboBox::item:selected { background: #2E2A4A; color: #B9B2FF; }"
            "QSpinBox, QTimeEdit { background: #16171A; color: #E8EAF0;"
            " border: 1px solid rgba(119, 126, 165, 0.22); border-radius: 10px; padding: 5px 10px; }"
            "QSpinBox:focus, QTimeEdit:focus { border: 1px solid #8D86FF; }"
            "QPushButton { background: #2A2D36; color: #E8EAF0; border: none;"
            " border-radius: 14px; padding: 7px 16px; }"
            "QPushButton:hover { background: #343845; }"
            "QPushButton#primaryBtn { background: #7D73FF; color: white; border: none;"
            " border-radius: 16px; padding: 8px 20px; font-weight: 600; }"
            "QPushButton#primaryBtn:hover { background: #6F63FF; }"
            "QPushButton#secondaryBtn { background: transparent; color: #B9B2FF;"
            " border: 1px solid rgba(141, 134, 255, 0.35); border-radius: 16px; padding: 8px 20px; }"
            "QPushButton#secondaryBtn:hover { background: rgba(141, 134, 255, 0.12); }"
            "QPushButton#aiGenBtn { background: #8B5CF6; color: white; border: none;"
            " border-radius: 14px; padding: 7px 16px; font-weight: 600; }"
            "QPushButton#aiGenBtn:hover { background: #7C3AED; }"
            "QFrame#petSpriteSlot { background: #16171A; border: none; border-radius: 16px; }"
            "QFrame#petSpriteSlot:hover { background: #1C1E24; }"
            "QFrame#petCard { background: #16171A; border: none; border-radius: 16px; }"
            "QFrame#petSectionCard { background: #16171A; border: none; border-radius: 16px; }"
            "QListWidget { background: transparent; color: #E8EAF0; border: none; }"
            "QListWidget::indicator { width: 16px; height: 16px; border-radius: 5px;"
            " border: 1px solid rgba(119, 126, 165, 0.45); background: #16171A; }"
            "QListWidget::indicator:checked { background: #7D73FF; border: 1px solid #7D73FF; }"
            "QListWidget::item { padding: 8px 10px; border-radius: 8px; margin: 1px 2px; }"
            "QListWidget::item:hover { background: rgba(141, 134, 255, 0.08); }"
            "QListWidget::item:selected { background: #2E2A4A; color: #B9B2FF; }"
            "QTabWidget::pane { border: none; border-radius: 16px; background: #16171A;"
            " padding: 4px; }"
            "QTabBar::tab { background: transparent; color: #8B92A8;"
            " border-radius: 10px; padding: 6px 16px; margin-right: 4px; }"
            "QTabBar::tab:selected { background: #2E2A4A; color: #B9B2FF; }"
            "QTabBar::tab:hover:!selected { background: rgba(141, 134, 255, 0.08); }"
            "QCheckBox { color: #E8EAF0; spacing: 6px; }"
            "QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px;"
            " border: 1px solid rgba(119, 126, 165, 0.45); background: #16171A; }"
            "QCheckBox::indicator:checked { background: #7D73FF; border: 1px solid #7D73FF; }"
            "QTableWidget { background: #16171A; color: #E8EAF0;"
            " gridline-color: rgba(119, 126, 165, 0.18); border: none; border-radius: 12px; }"
            "QHeaderView::section { background: #1E1F22; color: #E8EAF0;"
            " border: none; padding: 5px 10px; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }"
            "QScrollBar::handle:vertical { background: rgba(139, 146, 168, 0.35);"
            " border-radius: 4px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
    return (
        "QWidget { background: transparent; color: #1F2430; }"
        "QDialog { background: #FAFAFC; }"
        "QLabel { color: #1F2430; font-size: 13px; background: transparent; }"
        "QLabel#petHintLabel, QLabel[petPathLabel=\"true\"] { color: #8A90A4; font-size: 11px; }"
        "QLabel#petCardTitle { color: #1F2430; font-weight: 600; font-size: 14px; }"
        "QLabel#petSectionTitle { color: #1F2430; font-weight: 600; font-size: 13px; }"
        "QLineEdit, QPlainTextEdit { background: #FFFFFF; color: #1F2430;"
        " border: 1px solid rgba(162, 170, 211, 0.30); border-radius: 12px; padding: 7px 12px; }"
        "QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #A49BFF; }"
        "QComboBox { background: #FFFFFF; color: #1F2430;"
        " border: 1px solid rgba(162, 170, 211, 0.30); border-radius: 12px; padding: 6px 12px; }"
        "QComboBox:focus { border: 1px solid #A49BFF; }"
        "QComboBox::drop-down { border: none; width: 24px; }"
        "QComboBox QAbstractItemView { background: #FFFFFF; color: #1F2430;"
        " border: 1px solid rgba(162, 170, 211, 0.35); border-radius: 10px; padding: 4px; outline: none; }"
        "QComboBox::item { padding: 7px 12px; border-radius: 6px; }"
        "QComboBox::item:selected { background: #ECEAFF; color: #5D52E0; }"
        "QSpinBox, QTimeEdit { background: #FFFFFF; color: #1F2430;"
        " border: 1px solid rgba(162, 170, 211, 0.30); border-radius: 10px; padding: 5px 10px; }"
        "QSpinBox:focus, QTimeEdit:focus { border: 1px solid #A49BFF; }"
        "QPushButton { background: #F0F1F6; color: #1F2430; border: none;"
        " border-radius: 14px; padding: 7px 16px; }"
        "QPushButton:hover { background: #E6E8F0; }"
        "QPushButton#primaryBtn { background: #7D73FF; color: white; border: none;"
        " border-radius: 16px; padding: 8px 20px; font-weight: 600; }"
        "QPushButton#primaryBtn:hover { background: #6F63FF; }"
        "QPushButton#secondaryBtn { background: transparent; color: #5D52E0;"
        " border: 1px solid rgba(125, 115, 255, 0.30); border-radius: 16px; padding: 8px 20px; }"
        "QPushButton#secondaryBtn:hover { background: #ECEAFF; }"
        "QPushButton#aiGenBtn { background: #8B5CF6; color: white; border: none;"
        " border-radius: 14px; padding: 7px 16px; font-weight: 600; }"
        "QPushButton#aiGenBtn:hover { background: #7C3AED; }"
        "QFrame#petSpriteSlot { background: #F5F6FA; border: none; border-radius: 16px; }"
        "QFrame#petSpriteSlot:hover { background: #EFF0F7; }"
        "QFrame#petCard { background: #FFFFFF; border: none; border-radius: 16px; }"
        "QFrame#petSectionCard { background: #FFFFFF; border: none; border-radius: 16px; }"
        "QListWidget { background: transparent; color: #1F2430; border: none; }"
        "QListWidget::indicator { width: 16px; height: 16px; border-radius: 5px;"
        " border: 1px solid rgba(162, 170, 211, 0.50); background: #FFFFFF; }"
        "QListWidget::indicator:checked { background: #7D73FF; border: 1px solid #7D73FF; }"
        "QListWidget::item { padding: 8px 10px; border-radius: 8px; margin: 1px 2px; }"
        "QListWidget::item:hover { background: rgba(125, 115, 255, 0.06); }"
        "QListWidget::item:selected { background: #ECEAFF; color: #5D52E0; }"
        "QTabWidget::pane { border: none; border-radius: 16px; background: #FFFFFF;"
        " padding: 4px; }"
        "QTabBar::tab { background: transparent; color: #8A90A4;"
        " border-radius: 10px; padding: 6px 16px; margin-right: 4px; }"
        "QTabBar::tab:selected { background: #ECEAFF; color: #5D52E0; }"
        "QTabBar::tab:hover:!selected { background: rgba(125, 115, 255, 0.06); }"
        "QCheckBox { color: #1F2430; spacing: 6px; }"
        "QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px;"
        " border: 1px solid rgba(162, 170, 211, 0.50); background: #FFFFFF; }"
        "QCheckBox::indicator:checked { background: #7D73FF; border: 1px solid #7D73FF; }"
        "QTableWidget { background: #FFFFFF; color: #1F2430;"
        " gridline-color: rgba(162, 170, 211, 0.25); border: none; border-radius: 12px; }"
        "QHeaderView::section { background: #F5F6FA; color: #4B5163;"
        " border: none; padding: 5px 10px; }"
        "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }"
        "QScrollBar::handle:vertical { background: rgba(138, 144, 164, 0.30);"
        " border-radius: 4px; min-height: 24px; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
    )

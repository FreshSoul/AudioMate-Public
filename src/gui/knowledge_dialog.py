"""
知识库管理页面 — 左侧知识库列表 + 右侧文件管理
通过 QStackedWidget page_stack 与 MainWindow 集成。
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QInputDialog, QMessageBox, QFileDialog,
    QAbstractItemView, QSplitter,
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtGui import QFont

from src.gui.common import configure_back_button, back_button_style
from src.utils.knowledge_store import (
    list_knowledge_bases, create_knowledge_base, delete_knowledge_base,
    rename_knowledge_base, get_knowledge_base_name,
    list_documents, add_document, remove_document, format_size, import_paths,
)

# 支持上传的文件类型
_FILE_FILTER = (
    "所有支持的文件 (*.txt *.md *.csv *.json *.xml *.html *.log "
    "*.pdf *.docx *.xlsx *.pptx);;"
    "文本文件 (*.txt *.md *.csv *.json *.xml *.html *.log);;"
    "PDF (*.pdf);;Word (*.docx);;Excel (*.xlsx);;PPT (*.pptx);;"
    "所有文件 (*)"
)


class _ImportPathsThread(QThread):
    """Run :func:`import_paths` off the UI thread.

    Large PDFs/DOCXs are CPU-bound text extraction; running them on the GUI
    thread freezes the dialog for seconds. The thread emits ``finished_with_result``
    when done — the slot then refreshes the table and shows the toast.
    """

    finished_with_result = pyqtSignal(dict, str)  # (result_dict, error_message)

    def __init__(self, kb_id: str, paths: list[str], parent=None):
        super().__init__(parent)
        self._kb_id = kb_id
        self._paths = list(paths)

    def run(self) -> None:
        try:
            result = import_paths(self._kb_id, self._paths)
            self.finished_with_result.emit(result, "")
        except Exception as exc:  # noqa: BLE001 — surfacing to UI is the point
            self.finished_with_result.emit(
                {"imported": [], "skipped": [], "errors": []}, str(exc)
            )


class KnowledgeDialog(QWidget):
    """知识库管理页面"""
    back_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_mode = "light"
        self._current_kb_id: str | None = None
        self._import_thread: _ImportPathsThread | None = None
        self.setAcceptDrops(True)
        self._setup_ui()

    # ── UI 构建 ─────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 顶部导航栏 ──
        header = QWidget()
        header.setObjectName("headerBar")
        header.setFixedHeight(62)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 12, 24, 12)

        self.back_btn = QPushButton("‹")
        configure_back_button(self.back_btn)
        self.back_btn.clicked.connect(self.back_requested.emit)

        self.title_label = QLabel("知识库")
        self.title_label.setFont(QFont("", 20, QFont.Weight.DemiBold))

        self.breadcrumb_label = QLabel("")
        self.breadcrumb_label.setStyleSheet("color: #888; font-size: 13px;")

        header_layout.addWidget(self.back_btn)
        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.breadcrumb_label)
        header_layout.addStretch()
        root.addWidget(header)

        # ── 分割线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        # ── 内容区（左右分栏） ──
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # ── 左侧面板 ──
        left_panel = QWidget()
        left_panel.setObjectName("leftPanel")
        left_panel.setFixedWidth(240)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(16, 16, 8, 16)
        left_layout.setSpacing(8)

        personal_title = QLabel("📂  个人知识库")
        personal_title.setStyleSheet("font-size: 13px; font-weight: 600; padding: 4px 0;")
        left_layout.addWidget(personal_title)
        self.personal_title_label = personal_title

        self.kb_list = QListWidget()
        self.kb_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.kb_list.currentRowChanged.connect(self._on_kb_selected)
        self.kb_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.kb_list.customContextMenuRequested.connect(self._kb_context_menu)
        left_layout.addWidget(self.kb_list)

        btn_row = QHBoxLayout()
        self.add_kb_btn = QPushButton("＋ 新建知识库")
        self.add_kb_btn.setObjectName("primaryBtn")
        self.add_kb_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_kb_btn.clicked.connect(self._create_kb)
        btn_row.addWidget(self.add_kb_btn)
        btn_row.addStretch()
        left_layout.addLayout(btn_row)

        # ── 左右分隔线 ──
        v_sep = QFrame()
        v_sep.setFrameShape(QFrame.Shape.VLine)
        v_sep.setFixedWidth(1)
        self.v_sep = v_sep

        # ── 右侧面板 ──
        right_panel = QWidget()
        right_panel.setObjectName("rightPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(14)

        # 右侧顶部：知识库名称 + 操作按钮
        right_top = QHBoxLayout()
        self.kb_name_label = QLabel("")
        self.kb_name_label.setFont(QFont("", 16, QFont.Weight.DemiBold))
        right_top.addWidget(self.kb_name_label)
        right_top.addStretch()

        self.upload_btn = QPushButton("📄 上传文档")
        self.upload_btn.setObjectName("secondaryBtn")
        self.upload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upload_btn.clicked.connect(self._upload_docs)
        right_top.addWidget(self.upload_btn)

        self.delete_kb_btn = QPushButton("🗑 删除知识库")
        self.delete_kb_btn.setObjectName("dangerBtn")
        self.delete_kb_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_kb_btn.clicked.connect(self._delete_current_kb)
        right_top.addWidget(self.delete_kb_btn)
        right_layout.addLayout(right_top)

        # 文件表格
        self.file_table = QTableWidget(0, 4)
        self.file_table.setHorizontalHeaderLabels(["文件名", "大小", "修改时间", "操作"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.file_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.file_table.setColumnWidth(1, 92)
        self.file_table.setColumnWidth(2, 152)
        self.file_table.setColumnWidth(3, 88)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_table.setShowGrid(False)
        self.file_table.setAlternatingRowColors(False)
        self.file_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.file_table.horizontalHeader().setFixedHeight(44)
        self.file_table.verticalHeader().setVisible(False)
        right_layout.addWidget(self.file_table)

        # 空状态
        self.empty_label = QLabel("暂无文件，快来搭建你的知识库吧\n\n"
                                   "支持：TXT、MD、PDF、Word、Excel、PPT 等")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #999; font-size: 14px; padding: 60px 0;")
        right_layout.addWidget(self.empty_label)

        body_layout.addWidget(left_panel)
        body_layout.addWidget(v_sep)
        body_layout.addWidget(right_panel, 1)

        root.addWidget(body, 1)

        self.left_panel = left_panel
        self.right_panel = right_panel

    # ── 数据刷新 ────────────────────────────────────────────────────

    def refresh(self):
        """刷新知识库列表（每次打开页面时调用）"""
        self.kb_list.blockSignals(True)
        self.kb_list.clear()
        kbs = list_knowledge_bases()
        for kb in kbs:
            item = QListWidgetItem(f"{kb['name']}  ({kb['file_count']})")
            item.setData(Qt.ItemDataRole.UserRole, kb["id"])
            self.kb_list.addItem(item)
        self.kb_list.blockSignals(False)

        if kbs:
            self.kb_list.setCurrentRow(0)
        else:
            self._current_kb_id = None
            self._show_empty_right()

    def _refresh_file_table(self):
        """刷新右侧文件列表"""
        if not self._current_kb_id:
            self._show_empty_right()
            return
        docs = list_documents(self._current_kb_id)
        self.file_table.setRowCount(len(docs))
        self.file_table.setVisible(len(docs) > 0)
        self.empty_label.setVisible(len(docs) == 0)
        self.kb_name_label.setText(get_knowledge_base_name(self._current_kb_id))
        self.breadcrumb_label.setText(f" /  {get_knowledge_base_name(self._current_kb_id)}")

        for row, doc in enumerate(docs):
            self.file_table.setRowHeight(row, 52)
            self.file_table.setItem(row, 0, QTableWidgetItem(doc["name"]))
            self.file_table.setItem(row, 1, QTableWidgetItem(format_size(doc["size"])))
            self.file_table.setItem(row, 2, QTableWidgetItem(doc["modified"][:16].replace("T", " ")))

            del_btn = QPushButton("删除")
            del_btn.setFixedSize(56, 28)
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            fname = doc["name"]
            del_btn.clicked.connect(lambda checked, f=fname: self._remove_doc(f))
            self.file_table.setCellWidget(row, 3, del_btn)

        self.upload_btn.setVisible(True)
        self.delete_kb_btn.setVisible(True)

    def _show_empty_right(self):
        self.file_table.setRowCount(0)
        self.file_table.setVisible(False)
        self.empty_label.setVisible(True)
        self.kb_name_label.setText("")
        self.breadcrumb_label.setText("")
        self.upload_btn.setVisible(False)
        self.delete_kb_btn.setVisible(False)

    # ── 知识库操作 ──────────────────────────────────────────────────

    def _on_kb_selected(self, row):
        if row < 0:
            self._current_kb_id = None
            self._show_empty_right()
            return
        item = self.kb_list.item(row)
        if item:
            self._current_kb_id = item.data(Qt.ItemDataRole.UserRole)
            self._refresh_file_table()

    def _create_kb(self):
        name, ok = QInputDialog.getText(self, "新建知识库", "知识库名称:")
        if ok and name.strip():
            create_knowledge_base(name.strip())
            self.refresh()
            # 选中最新创建的
            self.kb_list.setCurrentRow(0)

    def _delete_current_kb(self):
        if not self._current_kb_id:
            return
        name = get_knowledge_base_name(self._current_kb_id)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除知识库 「{name}」 及其所有文件吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_knowledge_base(self._current_kb_id)
            self._current_kb_id = None
            self.refresh()

    def _kb_context_menu(self, pos):
        item = self.kb_list.itemAt(pos)
        if not item:
            return
        kb_id = item.data(Qt.ItemDataRole.UserRole)
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除")
        action = menu.exec(self.kb_list.mapToGlobal(pos))
        if action == rename_action:
            old_name = get_knowledge_base_name(kb_id)
            name, ok = QInputDialog.getText(self, "重命名知识库", "新名称:", text=old_name)
            if ok and name.strip():
                rename_knowledge_base(kb_id, name.strip())
                self.refresh()
        elif action == delete_action:
            name = get_knowledge_base_name(kb_id)
            reply = QMessageBox.question(
                self, "确认删除",
                f"确定要删除知识库 「{name}」 及其所有文件吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                delete_knowledge_base(kb_id)
                if kb_id == self._current_kb_id:
                    self._current_kb_id = None
                self.refresh()

    # ── 文件操作 ────────────────────────────────────────────────────

    def _upload_docs(self):
        if not self._current_kb_id:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "选择文档", "", _FILE_FILTER)
        if not files:
            return
        self._import_paths(files)

    def _import_paths(self, paths: list[str]):
        if not self._current_kb_id:
            return
        if self._import_thread is not None and self._import_thread.isRunning():
            QMessageBox.information(
                self, "正在导入",
                "上一次导入还在进行中，请等待完成后再上传。",
            )
            return

        # Disable upload affordances so the user gets visual feedback that
        # work is in flight.
        self.upload_btn.setEnabled(False)
        original_label = self.upload_btn.text()
        self.upload_btn.setText("📄 正在导入…")
        self.setAcceptDrops(False)

        thread = _ImportPathsThread(self._current_kb_id, paths, self)
        self._import_thread = thread

        def _on_finished(result: dict, error_message: str):
            self.upload_btn.setEnabled(True)
            self.upload_btn.setText(original_label)
            self.setAcceptDrops(True)
            self._refresh_file_table()
            self.refresh()
            self._import_thread = None
            if error_message:
                QMessageBox.warning(
                    self, "导入失败",
                    f"导入过程中发生错误：\n{error_message}",
                )
                return
            imported_count = len(result.get("imported") or [])
            skipped_count = len(result.get("skipped") or [])
            error_count = len(result.get("errors") or [])
            if skipped_count or error_count:
                QMessageBox.information(
                    self, "导入完成",
                    f"成功导入 {imported_count} 项，跳过 {skipped_count} 项，失败 {error_count} 项。",
                )
            elif imported_count:
                # Always confirm a fully-successful import so users know it landed.
                QMessageBox.information(
                    self, "导入完成",
                    f"成功导入 {imported_count} 项。",
                )

        thread.finished_with_result.connect(_on_finished)
        thread.start()

    def _remove_doc(self, filename):
        if not self._current_kb_id:
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除文件 「{filename}」 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            remove_document(self._current_kb_id, filename)
            self._refresh_file_table()
            self.refresh()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self._current_kb_id:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() and self._current_kb_id:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls() and self._current_kb_id:
            paths = []
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    paths.append(url.toLocalFile())
            if paths:
                self._import_paths(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    # ── 主题 ────────────────────────────────────────────────────────

    def apply_theme(self, theme_mode):
        self.theme_mode = "dark" if theme_mode == "dark" else "light"
        if self.theme_mode == "dark":
            self.setStyleSheet(
                "QWidget { background-color: #1B1E24; color: #E6E6E6; }"
                "QWidget#headerBar { background: transparent; }"
                "QWidget#leftPanel, QWidget#rightPanel { background: #20242B; border: 1px solid #323843; border-radius: 22px; }"
                "QFrame { background-color: transparent; border: none; }"
                "QLabel { color: #D7DCE6; background: transparent; }"
                "QListWidget { background: #171A20; border: 1px solid #313743; border-radius: 18px; color: #E6E6E6; outline: none; padding: 8px; }"
                "QListWidget::item { padding: 10px 12px; border-radius: 12px; margin: 4px 0px; }"
                "QListWidget::item:selected { background: #2F4E7A; color: #F4F7FF; }"
                "QListWidget::item:hover { background: #252A33; }"
                "QTableWidget { background: #171A20; border: 1px solid #313743; border-radius: 18px; color: #E6E6E6; gridline-color: transparent; padding: 6px; }"
                "QTableWidget::item { padding: 12px 10px; border-bottom: 1px solid #272C35; }"
                "QHeaderView::section { background: #20242B; color: #AEB7C5; border: none; padding: 11px 10px; font-weight: 700; }"
                "QPushButton { border: none; border-radius: 14px; padding: 9px 16px; color: #E6E6E6; background: #2C313B; }"
                "QPushButton:hover { background: #353B47; }"
                "QPushButton#primaryBtn { background: #4F63F6; color: #FFFFFF; }"
                "QPushButton#primaryBtn:hover { background: #6073FF; }"
                "QPushButton#secondaryBtn { background: #262C35; border: 1px solid #353C47; }"
                "QPushButton#secondaryBtn:hover { background: #2E3540; }"
                "QPushButton#dangerBtn { background: #3A2427; color: #FFC0C0; }"
                "QPushButton#dangerBtn:hover { background: #4A2B31; }"
                "QInputDialog { background: #1E1F22; }"
                f"{back_button_style('dark')}"
            )
            self.v_sep.setStyleSheet("background: #3A3F46;")
        else:
            self.setStyleSheet(
                "QWidget { background-color: #FCFCFE; color: #1F1F1F; }"
                "QWidget#headerBar { background: transparent; }"
                "QWidget#leftPanel, QWidget#rightPanel { background: #FFFFFF; border: 1px solid #E7EBF4; border-radius: 22px; }"
                "QFrame { background-color: transparent; border: none; }"
                "QLabel { color: #374151; background: transparent; }"
                "QListWidget { background: #F7F9FC; border: 1px solid #E7EBF4; border-radius: 18px; color: #1F1F1F; outline: none; padding: 8px; }"
                "QListWidget::item { padding: 10px 12px; border-radius: 12px; margin: 4px 0px; }"
                "QListWidget::item:selected { background: #E8F0FE; color: #3157E0; }"
                "QListWidget::item:hover { background: #F1F5FF; }"
                "QTableWidget { background: #FFFFFF; border: 1px solid #E7EBF4; border-radius: 18px; color: #1F1F1F; gridline-color: transparent; padding: 6px; }"
                "QTableWidget::item { padding: 12px 10px; border-bottom: 1px solid #EEF2F7; }"
                "QHeaderView::section { background: #F8FAFD; color: #73809A; border: none; padding: 11px 10px; font-weight: 700; }"
                "QPushButton { background: #F3F5FA; border: 1px solid #E5EAF5; border-radius: 14px; padding: 9px 16px; color: #24324A; }"
                "QPushButton:hover { background: #EDF1F8; }"
                "QPushButton#primaryBtn { background: #4C63F6; border-color: #4C63F6; color: #FFFFFF; }"
                "QPushButton#primaryBtn:hover { background: #5B71FF; }"
                "QPushButton#secondaryBtn { background: #FFFFFF; }"
                "QPushButton#secondaryBtn:hover { background: #F7F9FC; }"
                "QPushButton#dangerBtn { background: #FFF2F2; border-color: #FFDCDD; color: #C54A4A; }"
                "QPushButton#dangerBtn:hover { background: #FFE7E7; }"
                f"{back_button_style('light')}"
            )
            self.v_sep.setStyleSheet("background: #E5E7EB;")

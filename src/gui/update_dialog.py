"""更新检查 / 下载安装的 PyQt6 对话框。"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextBrowser, QMessageBox, QWidget,
)

from src.__version__ import __version__ as CURRENT_VERSION
from src.services import updater
from src.services.updater import ReleaseInfo


# ---------------------------------------------------------------------------
# 后台线程：检查
# ---------------------------------------------------------------------------
class _CheckThread(QThread):
    finished_ok = pyqtSignal(object)   # ReleaseInfo or None
    failed = pyqtSignal(str)

    def run(self):
        try:
            info = updater.fetch_latest_release_with_fallback()
            self.finished_ok.emit(info)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
# 后台线程：下载 + 安装
# ---------------------------------------------------------------------------
class _UpdateThread(QThread):
    progress = pyqtSignal(str, int, int)
    failed = pyqtSignal(str)

    def __init__(self, info: ReleaseInfo, parent=None):
        super().__init__(parent)
        self._info = info

    def run(self):
        try:
            updater.perform_update(
                self._info,
                progress=lambda s, c, t: self.progress.emit(s, c, t),
            )
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
# 对话框
# ---------------------------------------------------------------------------
class UpdateDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, auto_check: bool = True):
        super().__init__(parent)
        self.setWindowTitle("检查更新")
        self.setMinimumSize(520, 420)

        self._info: ReleaseInfo | None = None
        self._check_thread: _CheckThread | None = None
        self._update_thread: _UpdateThread | None = None

        layout = QVBoxLayout(self)

        self.title_label = QLabel(f"当前版本：v{CURRENT_VERSION}")
        self.title_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(self.title_label)

        self.status_label = QLabel("正在检查更新…")
        layout.addWidget(self.status_label)

        self.notes_view = QTextBrowser()
        self.notes_view.setOpenExternalLinks(True)
        self.notes_view.setVisible(False)
        layout.addWidget(self.notes_view, stretch=1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("关闭")
        self.cancel_btn.clicked.connect(self.reject)
        self.action_btn = QPushButton("立即更新")
        self.action_btn.setEnabled(False)
        self.action_btn.clicked.connect(self._on_install)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.action_btn)
        layout.addLayout(btn_row)

        if auto_check:
            self._start_check()

    # --- 检查 -------------------------------------------------------------
    def _start_check(self):
        self._check_thread = _CheckThread(self)
        self._check_thread.finished_ok.connect(self._on_check_done)
        self._check_thread.failed.connect(self._on_check_failed)
        self._check_thread.start()

    def _on_check_failed(self, msg: str):
        self.status_label.setText(f"检查失败：{msg}")

    def _on_check_done(self, info):
        if info is None:
            err = (updater.last_error or "").strip()
            extra = f"\n详情：{err}" if err else ""
            self.status_label.setText(
                "无法获取最新版本信息（请检查网络或稍后重试）。" + extra
            )
            self.status_label.setWordWrap(True)
            return
        self._info = info
        if not updater.is_newer(info.version):
            self.status_label.setText(f"已是最新版本（最新发布：{info.tag}）。")
            return

        self.status_label.setText(
            f"发现新版本：{info.tag}　大小：{info.asset_size / (1024*1024):.1f} MB"
        )
        # 渲染 release notes（Markdown → 简单 HTML）
        body = info.body or "（无更新说明）"
        self.notes_view.setMarkdown(body)
        self.notes_view.setVisible(True)
        self.action_btn.setEnabled(True)

    # --- 安装 -------------------------------------------------------------
    def _on_install(self):
        if not self._info:
            return
        # 开发态拒绝
        import sys
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self, "提示",
                "自动更新仅在打包发行版中可用。\n开发模式下请使用 git pull。",
            )
            return

        ret = QMessageBox.question(
            self, "确认更新",
            f"将下载并安装 {self._info.tag}。\n安装期间程序会自动重启，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        self.action_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self._update_thread = _UpdateThread(self._info, self)
        self._update_thread.progress.connect(self._on_progress)
        self._update_thread.failed.connect(self._on_update_failed)
        self._update_thread.start()

    def _on_progress(self, stage: str, current: int, total: int):
        label_map = {
            "preparing": "准备下载…",
            "downloading": "正在下载更新包…",
            "extracting": "正在解压…",
            "launching": "即将重启完成更新…",
        }
        self.status_label.setText(label_map.get(stage, stage))
        if total > 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(current * 100 / total))
        else:
            self.progress_bar.setRange(0, 0)  # busy

    def _on_update_failed(self, msg: str):
        self.progress_bar.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self.action_btn.setEnabled(True)
        QMessageBox.critical(self, "更新失败", msg)


def show_update_dialog(parent=None):
    dlg = UpdateDialog(parent)
    dlg.exec()

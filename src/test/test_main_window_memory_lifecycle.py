"""Smoke tests for chat lifecycle memory cleanup."""

from __future__ import annotations

import os
import sys
import tempfile
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QStackedWidget, QWidget

from src.gui.main_window import MainWindow
from src.gui.runtime_support import MemoryRefreshThread
from src.services.memory_service import MemoryService


def _app() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


def test_delete_chat_history_removes_session_memory(monkeypatch):
    _app()
    with tempfile.TemporaryDirectory() as tmp:
        chat_id = "chat-delete-me"
        memory_service = MemoryService(base_dir=tmp)
        memory_service.record_turn_summary(chat_id, "目标", "结果")
        legacy_json = memory_service.session_dir / f"{chat_id}-legacy.json"
        legacy_json.write_text('{"records": []}', encoding="utf-8")
        assert memory_service.session_path(chat_id).exists()
        assert legacy_json.exists()

        class FakeMemoryManager:
            def get_memory_service(self):
                return memory_service

        window = MainWindow.__new__(MainWindow)
        window.__dict__["memory_manager"] = FakeMemoryManager()
        window.__dict__["_chat_task_states"] = {}
        window.current_chat_id = "other-chat"
        refreshed = []
        window.refresh_history_list = lambda: refreshed.append(True)

        import src.gui.main_window as main_window_module
        deleted = []
        monkeypatch.setattr(main_window_module, "delete_chat", lambda cid: deleted.append(cid) or True)
        MainWindow.delete_chat_history(window, chat_id)

        assert deleted == [chat_id]
        assert refreshed == [True]
        assert not memory_service.session_path(chat_id).exists()
        assert not legacy_json.exists()


class _SlowFakeLLM:
    def get_response(self, messages, stream=True, max_tokens=1600):
        time.sleep(0.2)
        yield '{"session":{"should_update":false},"repo":{"should_update":false}}'


def test_memory_refresh_runs_off_ui_thread():
    app = _app()
    thread_results: list[str] = []
    thread = MemoryRefreshThread(_SlowFakeLLM(), [{"role": "user", "content": "refresh memory"}])
    thread.finished_signal.connect(lambda text: thread_results.append(text))
    started_at = time.perf_counter()
    thread.start()
    elapsed = time.perf_counter() - started_at
    assert elapsed < 0.1, "start() must not block the UI thread"
    assert thread.wait(2000)
    app.processEvents()
    assert thread_results
    assert "should_update" in thread_results[0]


def test_sidebar_actions_return_to_chat_page():
    _app()
    window = MainWindow.__new__(MainWindow)
    window.page_stack = QStackedWidget()
    window.chat_page = QWidget()
    window.settings_page = QWidget()
    window.page_stack.addWidget(window.chat_page)
    window.page_stack.addWidget(window.settings_page)
    window.page_stack.setCurrentWidget(window.settings_page)
    window._sync_floating_panel_visibility = lambda animated=False: None
    window._sync_navigation_styles = lambda: None
    MainWindow._show_chat_page(window)
    assert window.page_stack.currentWidget() == window.chat_page

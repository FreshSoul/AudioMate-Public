"""Smoke tests for WAAPI authority fallback and attachment bubble sizing."""

import json
import os
import shutil
import sys
import tempfile
import importlib.util
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QListWidgetItem, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from src.gui.main_window import MainWindow
from src.gui.widgets import AgentThinkingWidget, ConfirmationWidget, MessageBubble, StepProgressWidget, _linkify_http_urls, _resolve_thinking_activity_title
from src.engine.turn_controller import TurnAction, TurnResult
from src.llm.retrieval import WaapiDocRetriever


app = QApplication.instance() or QApplication(sys.argv)


def build_temp_docs(local_doc_text: str) -> str:
    docs_dir = tempfile.mkdtemp(prefix="waapi_docs_")
    index_path = os.path.join(docs_dir, "_index.json")
    doc_path = os.path.join(docs_dir, "ak.test.uri.md")
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(
            [
                {
                    "uri": "ak.test.uri",
                    "filename": "ak.test.uri.md",
                    "description": "test uri",
                }
            ],
            fh,
            ensure_ascii=False,
            indent=2,
        )
    with open(doc_path, "w", encoding="utf-8") as fh:
        fh.write(local_doc_text)
    return docs_dir


def test_local_authority_doc_does_not_hit_web():
    docs_dir = build_temp_docs(
        "# ak.test.uri\n\n## Arguments Schema\n\n```json\n{\"foo\": \"bar\"}\n```\n\n## Official Source\n\n- Source: https://example.com/local"
    )
    try:
        retriever = WaapiDocRetriever(docs_dir=docs_dir)

        class FakeWeb:
            def __init__(self):
                self.calls = 0

            def fetch_webpage(self, *_args, **_kwargs):
                self.calls += 1
                raise AssertionError("web fallback should not be used when local schema exists")

        fake_web = FakeWeb()
        retriever.web_access = fake_web
        content = retriever.retrieve_authoritative_by_uris(["ak.test.uri"])
        assert "Arguments Schema" in content
        assert fake_web.calls == 0
        print("test_local_authority_doc_does_not_hit_web: OK")
    finally:
        shutil.rmtree(docs_dir, ignore_errors=True)


def test_missing_local_guidance_uses_web_fallback():
    docs_dir = build_temp_docs("# ak.test.uri\n\nA short placeholder doc.")
    try:
        retriever = WaapiDocRetriever(docs_dir=docs_dir)

        class FakeWeb:
            def fetch_webpage(self, url, max_chars=0, timeout=0):
                assert "ak_test_uri.html" in url
                return {
                    "url": url,
                    "title": "Audiokinetic Test",
                    "text": "Arguments: foo, bar. Result: ok.",
                    "links": [],
                }

        retriever.web_access = FakeWeb()
        content = retriever.retrieve_authoritative_by_uris(["ak.test.uri"])
        assert "Official Web Fallback" in content
        assert "Arguments: foo, bar" in content
        print("test_missing_local_guidance_uses_web_fallback: OK")
    finally:
        shutil.rmtree(docs_dir, ignore_errors=True)


def test_message_bubble_resizes_attachments():
    img = QImage(800, 600, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF)
    bubble = MessageBubble(
        "user",
        "分析一下这个",
        images=[img],
        files=[{"name": "very_long_attachment_name_for_layout_validation_document.pdf", "path": r"D:\\fake\\very_long_attachment_name_for_layout_validation_document.pdf", "is_dir": False}],
        theme_mode="light",
    )
    bubble.resize(420, 400)
    bubble.show()
    QApplication.processEvents()
    bubble.adjust_height()

    assert bubble.images_height > 0
    assert bubble.files_height > 0
    assert bubble.image_labels[0].pixmap() is not None
    assert bubble.image_labels[0].pixmap().width() <= bubble._attachment_content_width()
    assert bubble.file_widgets[0].name_label.wordWrap()
    assert bubble.file_widgets[0].width() <= min(420, bubble._attachment_content_width())
    assert bubble.file_widgets[0].height() <= 80
    print("test_message_bubble_resizes_attachments: OK")


def test_attachment_only_message_hides_empty_editor_area_and_keeps_edit():
    bubble = MessageBubble(
        "user",
        "",
        images=[],
        files=[{"name": "E:/提莫/File0001.wav", "path": r"E:\\提莫\\File0001.wav", "is_dir": False}],
        theme_mode="light",
    )
    bubble.resize(1200, 320)
    bubble.show()
    QApplication.processEvents()
    bubble.adjust_height()

    assert hasattr(bubble, "float_edit_btn")
    assert not bubble.content.isVisible()
    assert bubble.content.height() == 0
    assert bubble.file_widgets[0].width() <= 420
    assert bubble.file_widgets[0].height() <= 80
    print("test_attachment_only_message_hides_empty_editor_area_and_keeps_edit: OK")


def test_message_text_linkifies_http_urls_without_touching_code_blocks():
    text = (
        "文档地址 https://example.com/docs 。\n\n"
        "```python\n"
        "url = 'https://example.com/code'\n"
        "```\n"
        "已有链接 [官网](https://audiokinetic.com)"
    )
    rendered = _linkify_http_urls(text)
    assert "[https://example.com/docs](https://example.com/docs)" in rendered
    assert "url = 'https://example.com/code'" in rendered
    assert rendered.count("[官网](https://audiokinetic.com)") == 1
    print("test_message_text_linkifies_http_urls_without_touching_code_blocks: OK")


def test_message_bubble_opens_http_links_and_rejects_file_links():
    bubble = MessageBubble("assistant", "访问 https://example.com/docs", theme_mode="light")
    with patch("src.gui.widgets.QDesktopServices.openUrl") as open_url:
        bubble.content._open_external_link(QUrl("https://example.com/docs"))
        bubble.content._open_external_link(QUrl("file:///D:/secret.txt"))
    assert open_url.call_count == 1
    assert open_url.call_args.args[0].toString() == "https://example.com/docs"
    print("test_message_bubble_opens_http_links_and_rejects_file_links: OK")


def test_enter_edit_mode_uses_original_message_text():
    original_text = "请打开 https://example.com/docs?foo=1&bar=2"
    bubble = MessageBubble("user", original_text, theme_mode="light")
    bubble.enter_edit_mode()
    assert bubble.edit_input.toPlainText() == original_text
    print("test_enter_edit_mode_uses_original_message_text: OK")


def test_load_selected_chat_restores_user_and_assistant_bubbles():
    host = QWidget()
    host.resize(960, 720)
    host_layout = QVBoxLayout(host)
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    chat_container = QWidget()
    chat_layout = QVBoxLayout(chat_container)
    scroll_area.setWidget(chat_container)
    host_layout.addWidget(scroll_area)
    host.show()

    class FakeWindow:
        pass

    window = FakeWindow()
    window.pending_branch_bubbles = []
    window.current_chat_id = None
    window.current_chat_title = "New Chat"
    window.chat_history = []
    window._thinking_widget = None
    window.step_progress_widget = None
    window.theme_mode = "light"
    window.scroll_area = scroll_area
    window.chat_container = chat_container
    window.chat_layout = chat_layout
    window.handle_edit_confirmed = lambda *_args, **_kwargs: None
    window._show_chat_page = lambda direction="right": None
    window._detach_visible_runtime_widgets = lambda: None
    window._stop_active_worker = lambda: None
    window._reset_streaming_state = lambda: None
    window._chat_task_states = {}
    window._task_state_for = lambda chat_id, create=False: MainWindow._task_state_for(window, chat_id, create=create)

    class FakeMemoryManager:
        def get_memory_service(self):
            return None

    window.memory_manager = FakeMemoryManager()
    window._restore_roleplay_state_from_history = lambda: None
    window.base64_to_images = lambda _content: []
    window._sanitize_assistant_response = lambda text: text
    window._parse_legacy_timeline_from_message = lambda _message: None
    window._is_system_generated_user_message = lambda _text: False
    window._restore_runtime_visuals_for_current_chat = lambda: None
    window._dispatch_pending_finished_for_current_chat = lambda: None
    window._dispatch_pending_execution_for_current_chat = lambda: None
    window._update_visible_bubbles = lambda resync_content=False: MainWindow._update_visible_bubbles(window, resync_content=resync_content)

    item = QListWidgetItem("demo")
    item.setData(Qt.ItemDataRole.UserRole, "chat-1")

    with patch("src.gui.main_window.load_chat", return_value={
        "title": "历史聊天",
        "messages": [
            {"role": "user", "content": "帮我检查一下 Event 结构"},
            {"role": "assistant", "content": "已经检查完成，发现两个命名问题。"},
        ],
    }):
        MainWindow.load_selected_chat(window, item)

    QApplication.processEvents()
    bubbles = [
        window.chat_layout.itemAt(index).widget()
        for index in range(window.chat_layout.count())
        if isinstance(window.chat_layout.itemAt(index).widget(), MessageBubble)
    ]
    assert len(bubbles) == 2
    assert bubbles[0].message_text == "帮我检查一下 Event 结构"
    assert bubbles[1].message_text == "已经检查完成，发现两个命名问题。"
    assert bubbles[0].content.isVisible()
    assert bubbles[1].content.isVisible()
    assert bubbles[0].height() > 50
    assert bubbles[1].height() > 50
    print("test_load_selected_chat_restores_user_and_assistant_bubbles: OK")


def test_chat_scrollbar_stays_visible_during_processing():
    """Regression: while thinking/executing, the chat scrollbar must stay in
    its normal as-needed mode. The earlier hide-during-processing strategy
    produced a tall light-grey native scrollbar artifact on Windows; the
    helper is now a no-op that only re-asserts AsNeeded + enabled."""
    class FakeScrollArea:
        def __init__(self):
            self._policy = Qt.ScrollBarPolicy.ScrollBarAsNeeded
            self._bar = type(
                "BarStub",
                (),
                {
                    "_visible": True,
                    "_enabled": True,
                    "orientation": lambda self: Qt.Orientation.Vertical,
                    "isEnabled": lambda self: self._enabled,
                    "hide": lambda self: setattr(self, "_visible", False),
                    "show": lambda self: setattr(self, "_visible", True),
                    "setEnabled": lambda self, enabled: setattr(self, "_enabled", bool(enabled)),
                },
            )()

        def verticalScrollBarPolicy(self):
            return self._policy

        def setVerticalScrollBarPolicy(self, policy):
            self._policy = policy

        def verticalScrollBar(self):
            return self._bar

    class FakeWindow:
        pass

    window = FakeWindow()
    window.scroll_area = FakeScrollArea()
    # Simulate a stale state where someone had previously disabled the bar.
    window.scroll_area._bar._enabled = False
    window.scroll_area._policy = Qt.ScrollBarPolicy.ScrollBarAlwaysOff

    MainWindow._set_chat_scrollbar_transient_hidden(window, True)
    # Even when called with hidden=True, policy must remain AsNeeded and the
    # bar must remain enabled and visible.
    assert window.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert window.scroll_area.verticalScrollBar()._enabled
    assert window.scroll_area.verticalScrollBar()._visible

    MainWindow._set_chat_scrollbar_transient_hidden(window, False)
    assert window.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert window.scroll_area.verticalScrollBar()._enabled
    print("test_chat_scrollbar_stays_visible_during_processing: OK")


def test_handle_agent_confirmation_removes_confirmation_widget():
    """Regression: clicking Confirm/Revoke must remove the ConfirmationWidget
    from the chat layout. Previously it lingered, causing visible lag on the
    post-confirm summary turn because every reflow walked through it."""
    host = QWidget()
    chat_layout = QVBoxLayout(host)
    confirm_widget = ConfirmationWidget(theme_mode="light")
    chat_layout.addWidget(confirm_widget)

    class FakeMode:
        def currentText(self):
            return "Agent Mode"

    class FakeResilience:
        def build_action_summary(self):
            return ""

        def reset(self):
            pass

    class FakeBtn:
        def __init__(self):
            self._disabled = True

        def setDisabled(self, value):
            self._disabled = bool(value)

    class FakeInput:
        def __init__(self):
            self._disabled = True

        def setDisabled(self, value):
            self._disabled = bool(value)

        def setFocus(self):
            pass

    window = MainWindow.__new__(MainWindow)
    window.send_btn = FakeBtn()
    window.input_field = FakeInput()
    window.chat_layout = chat_layout
    window.mode_selector = FakeMode()
    window.resilience = FakeResilience()
    window.pending_tool_output = "ok"
    window._pending_initial_thinking_text = ""
    queued_calls = []
    process_calls = []
    window._queue_internal_tool_output = lambda *args, **kwargs: (setattr(window, "_confirmation_summary_only", bool(kwargs.get("summary_only"))), queued_calls.append((args, kwargs)))
    window._record_repo_action_memory = lambda _summary: None
    window.process_turn = lambda: process_calls.append(True)

    MainWindow.handle_agent_confirmation(window, True, confirm_widget)
    QApplication.processEvents()

    remaining = [
        chat_layout.itemAt(i).widget()
        for i in range(chat_layout.count())
    ]
    assert confirm_widget not in remaining
    assert window._confirmation_summary_only is True
    assert window._pending_initial_thinking_text == "总结中"
    assert process_calls == [True]
    assert queued_calls and queued_calls[0][1].get("summary_only") is True
    print("test_handle_agent_confirmation_removes_confirmation_widget: OK")


def test_confirmation_summary_result_blocks_code_execution():
    window = MainWindow.__new__(MainWindow)
    window._confirmation_summary_only = True
    response_text = "```python_waapi\nwaapi_client.set_property('id', 'Volume', 1)\n```"
    result = TurnResult(
        action=TurnAction.SINGLE_CODE,
        response_text=response_text,
        code_blocks=["waapi_client.set_property('id', 'Volume', 1)"],
    )

    coerced = MainWindow._coerce_confirmation_summary_result(window, result)

    assert coerced.action == TurnAction.PURE_TEXT
    assert coerced.code_blocks == []
    assert "未继续执行新的代码" in coerced.response_text
    assert window._confirmation_summary_only is False

    next_result = TurnResult(
        action=TurnAction.SINGLE_CODE,
        response_text=response_text,
        code_blocks=["waapi_client.set_property('id', 'Volume', 1)"],
    )
    next_coerced = MainWindow._coerce_confirmation_summary_result(window, next_result)
    assert next_coerced.action == TurnAction.SINGLE_CODE
    assert next_coerced.code_blocks == ["waapi_client.set_property('id', 'Volume', 1)"]
    print("test_confirmation_summary_result_blocks_code_execution: OK")


def test_step_progress_widget_timeline_states():
    widget = StepProgressWidget(2, ["检查项目结构", "生成总结报告"], theme_mode="light")
    widget.show()
    QApplication.processEvents()

    widget.set_current_step(0)
    assert widget.step_items[0]["state"] == "running"
    assert not widget.step_items[0]["node"].detail_label.isVisible()
    assert widget.step_items[0]["node"].substeps_frame.isVisible()
    assert widget.step_items[0]["timestamp"] != "--:--:--"

    widget.complete_step(0)
    assert widget.step_items[0]["state"] == "done"
    assert not widget.step_items[0]["node"].detail_label.isVisible()
    assert not widget.step_items[0]["node"].substeps_frame.isVisible()

    widget.fail_step(1, "Traceback\nValueError: invalid audio format")
    assert widget.step_items[1]["state"] == "failed"
    assert widget.step_items[1]["node"].detail_label.isVisible()
    assert "invalid audio format" in widget.step_items[1]["node"].detail_label.text()
    assert widget.step_items[1]["node"].substeps_frame.isVisible()
    print("test_step_progress_widget_timeline_states: OK")


def test_step_progress_widget_reuses_single_card_flow():
    widget = StepProgressWidget(2, ["查询对象", "更新属性"], theme_mode="light")
    widget.show()
    QApplication.processEvents()

    widget.complete_step(0)
    widget.reset_flow(3, ["读取工程", "执行 WAAPI 调用", "整理结果"])
    QApplication.processEvents()

    assert len(widget.step_items) == 3
    assert widget.step_items[0]["description"] == "读取工程"
    assert widget.step_items[0]["state"] == "pending"
    assert widget.meta_label.text() == "待执行 3 项"

    widget.set_current_step(1)
    assert widget.meta_label.text() == "执行中 2/3 · 执行 WAAPI 调用"

    widget.mark_finished("执行完成 · 共 3 项")
    assert widget.meta_label.text() == "执行完成 · 共 3 项"
    assert widget.title_label.text() == "AudioMate 执行完成"
    assert widget.footer_frame.isVisible()
    assert widget.footer_label.text() == "执行完成 · 共 3 项"
    print("test_step_progress_widget_reuses_single_card_flow: OK")


def test_step_progress_widget_can_collapse_and_restore_from_snapshot():
    widget = StepProgressWidget(2, ["查询对象", "整理结果"], theme_mode="light")
    widget.show()
    widget.set_current_step(0)
    widget.mark_finished("执行完成 · 共 2 项")
    widget.set_collapsed(True)

    assert widget.is_collapsed
    assert not widget.steps_container.isVisible()
    assert not widget.footer_frame.isVisible()

    snapshot = widget.snapshot()
    restored = StepProgressWidget(0, [], theme_mode="light")
    restored.apply_snapshot(snapshot)
    restored.show()

    assert restored.is_collapsed
    assert not restored.steps_container.isVisible()
    assert not restored.footer_frame.isVisible()

    restored.set_collapsed(False)
    assert restored.steps_container.isVisible()
    assert restored.footer_frame.isVisible()
    print("test_step_progress_widget_can_collapse_and_restore_from_snapshot: OK")


def test_step_progress_widget_snapshot_roundtrip():
    widget = StepProgressWidget(2, ["查询对象", "更新对象"], theme_mode="light")
    widget.set_current_step(0)
    widget.set_step_detail(0, "已定位目标 Event", visible=True)
    widget.complete_step(0)
    widget.set_step_substeps(
        1,
        [
            {"title": "准备写入上下文"},
            {"title": "提交更新请求"},
            {"title": "验证变更结果"},
        ],
        active_index=1,
        visible=True,
    )
    widget.set_step_detail(1, "已准备写入参数", visible=True)
    widget.step_items[1]["state"] = "failed"
    widget.mark_finished("执行中断 · 停在 2/2")

    snapshot = widget.snapshot()

    restored = StepProgressWidget(0, [], theme_mode="light")
    restored.apply_snapshot(snapshot)
    restored.show()
    QApplication.processEvents()
    assert restored.title_label.text() == "AudioMate 执行中断"
    assert restored.meta_label.text() == "执行中断 · 停在 2/2"
    assert restored.step_items[0]["detail"] == "已定位目标 Event"
    assert restored.step_items[0]["state"] == "done"
    assert restored.step_items[1]["detail"] == "已准备写入参数"
    assert restored.step_items[1]["state"] == "failed"
    assert restored.step_items[1]["substeps_visible"]
    assert len(restored.step_items[1]["substeps"]) == 3
    assert restored.footer_frame.isVisible()
    print("test_step_progress_widget_snapshot_roundtrip: OK")


def test_describe_code_step_accepts_dict_code_block():
    window = MainWindow.__new__(MainWindow)
    title = MainWindow._describe_code_step(
        window,
        {"language": "python_waapi", "code": "result = waapi_client.call('ak.wwise.core.object.get', args)\nprint(result)"},
        0,
    )
    assert title == "查询 ak.wwise.core.object.get"
    print("test_describe_code_step_accepts_dict_code_block: OK")


def test_parse_legacy_timeline_from_failed_message():
    window = MainWindow.__new__(MainWindow)
    message = {
        "role": "assistant",
        "content": (
            "分步执行失败，已重试 3 次仍未成功，已停止。\n\n"
            "[步骤 1 输出]\n=== object.get 文档 ===\n# ak.wwise.core.object.get\n查询完成\n\n"
            "[步骤 2 输出]\nTraceback\nValueError: invalid audio format"
        ),
    }
    snapshot = MainWindow._parse_legacy_timeline_from_message(window, message)
    assert snapshot is not None
    assert snapshot["status"] == "执行中断 · 停在 2/2"
    assert snapshot["steps"][0]["description"] == "查询 object.get"
    assert snapshot["steps"][0]["detail"] == "查询完成"
    assert snapshot["steps"][1]["state"] == "failed"
    print("test_parse_legacy_timeline_from_failed_message: OK")


def test_code_executor_allows_uuid_import():
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(test_dir, "..", ".."))
    spec = importlib.util.spec_from_file_location(
        "execution_module",
        os.path.join(project_root, "src", "utils", "execution.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["execution_module"] = module
    spec.loader.exec_module(module)

    executor = module.CodeExecutor(context_globals={})
    output = executor.execute("import uuid\nprint(bool(uuid.uuid4()))", mode="Agent Mode")
    assert "True" in output
    print("test_code_executor_allows_uuid_import: OK")


def _load_execution_module():
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(test_dir, "..", ".."))
    spec = importlib.util.spec_from_file_location(
        "execution_module",
        os.path.join(project_root, "src", "utils", "execution.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["execution_module"] = module
    spec.loader.exec_module(module)
    return module


def test_code_executor_allows_common_safe_imports():
    module = _load_execution_module()
    executor = module.CodeExecutor(context_globals={})
    output = executor.execute(
        "\n".join([
            "import time",
            "from pathlib import PureWindowsPath",
            "from functools import partial",
            "from glob import glob",
            "from decimal import Decimal",
            "from operator import itemgetter",
            "from copy import deepcopy",
            "from random import Random",
            "time.sleep(0.01)",
            "path = PureWindowsPath('C:/AudioMate/Test.wav')",
            "double = partial(pow, exp=2)",
            "payload = [{'name': 'ok'}]",
            "copied = deepcopy(payload)",
            "checks = [",
            "    time.monotonic() > 0,",
            "    path.name == 'Test.wav',",
            "    double(3) == 9,",
            "    Decimal('0.1') + Decimal('0.2') == Decimal('0.3'),",
            "    itemgetter('name')(copied[0]) == 'ok',",
            "    Random(0).randint(1, 10) == 7,",
            "    isinstance(glob('*'), list),",
            "]",
            "print(all(checks))",
        ]),
        mode="Agent Mode",
    )
    assert "True" in output
    print("test_code_executor_allows_common_safe_imports: OK")


def test_code_executor_still_blocks_dangerous_imports():
    module = _load_execution_module()
    executor = module.CodeExecutor(context_globals={})
    output = executor.execute("import subprocess\nprint('unreachable')", mode="Agent Mode")
    assert "Import 'subprocess' is not allowed in Agent Mode" in output
    assert "unreachable" not in output
    print("test_code_executor_still_blocks_dangerous_imports: OK")


def test_code_executor_allows_csv_for_table_export():
    module = _load_execution_module()
    executor = module.CodeExecutor(context_globals={})
    output = executor.execute(
        "\n".join([
            "import csv, io",  # io is NOT whitelisted on its own; ensure csv alone is enough
        ]),
        mode="Agent Mode",
    )
    # csv must import cleanly; io should still be blocked (write-bypass guard).
    assert "Import 'io' is not allowed" in output
    csv_only = executor.execute("import csv\nprint('csv ok')", mode="Agent Mode")
    assert "csv ok" in csv_only
    print("test_code_executor_allows_csv_for_table_export: OK")


def test_code_executor_import_callback_approves_and_caches():
    module = _load_execution_module()
    executor = module.CodeExecutor(context_globals={})
    asked = []

    def approve(name):
        asked.append(name)
        return True

    executor.ask_import_callback = approve
    first = executor.execute("import textwrap\nprint(textwrap.shorten('hello world', 8))", mode="Agent Mode")
    second = executor.execute("import textwrap\nprint('second ok')", mode="Agent Mode")
    assert "second ok" in second
    assert asked == ["textwrap"], "approved import should be cached (asked exactly once)"
    assert "unreachable" not in first  # sanity: no leftover failure marker
    print("test_code_executor_import_callback_approves_and_caches: OK")


def test_code_executor_import_callback_denial_blocks():
    module = _load_execution_module()
    executor = module.CodeExecutor(context_globals={})
    executor.ask_import_callback = lambda name: False
    output = executor.execute("import textwrap\nprint('unreachable')", mode="Agent Mode")
    assert "Import 'textwrap' is not allowed in Agent Mode" in output
    assert "unreachable" not in output
    print("test_code_executor_import_callback_denial_blocks: OK")


def test_agent_thinking_widget_keeps_timeline_visible_after_finish():
    widget = AgentThinkingWidget(theme_mode="light")
    widget.show()
    widget.set_running("检查项目结构")
    QApplication.processEvents()
    assert widget._running_node is not None
    assert widget._running_node.substeps_frame.isVisible()

    widget.clear_running(promote_completed=True)
    assert widget._running_node is None
    assert len(widget._steps) == 1

    widget.set_running("整理回复内容")
    widget.finish()
    QApplication.processEvents()
    assert widget.is_finished
    assert widget.isVisible()
    assert widget._running_node is None
    assert widget._footer_frame.isVisible()
    assert widget._header.text() == "AudioMate 思考完成"
    print("test_agent_thinking_widget_keeps_timeline_visible_after_finish: OK")


def test_agent_thinking_widget_can_collapse_and_restore_from_snapshot():
    widget = AgentThinkingWidget(theme_mode="light", task_context="检查当前对象树")
    widget.show()
    widget.set_running("正在分析请求")
    widget.finish()
    widget.set_collapsed(True)

    assert widget.is_collapsed
    assert not widget._steps_container.isVisible()
    assert not widget._footer_frame.isVisible()

    restored = AgentThinkingWidget(theme_mode="light")
    restored.apply_snapshot(widget.snapshot())
    restored.show()
    QApplication.processEvents()

    assert restored.is_collapsed
    assert restored.is_finished
    assert not restored._steps_container.isVisible()
    assert not restored._footer_frame.isVisible()

    restored.set_collapsed(False)
    QApplication.processEvents()
    assert restored._steps_container.isVisible()
    assert restored._footer_frame.isVisible()
    print("test_agent_thinking_widget_can_collapse_and_restore_from_snapshot: OK")


def test_agent_thinking_widget_uses_task_context_for_dynamic_substeps():
    widget = AgentThinkingWidget(
        theme_mode="light",
        task_context="在 Wwise 中创建一个名为无限暖暖的文件夹或 Work Unit，并建立相关对象结构",
    )
    widget.show()
    widget.set_running("正在分析请求")
    QApplication.processEvents()

    assert widget._running_node is not None
    assert "无限暖暖" in widget._running_node.substeps[0]["detail"]
    assert any("创建" in item["title"] or "命名" in item["title"] for item in widget._running_node.substeps)
    print("test_agent_thinking_widget_uses_task_context_for_dynamic_substeps: OK")


def test_first_thinking_panel_prefers_user_analysis_intent_over_attachment_import_hint():
    widget = AgentThinkingWidget(
        theme_mode="light",
        task_context="分析一下 已附加本地路径: [文件] E:/提莫/File0001.wav",
    )
    widget.show()
    widget.set_running("正在分析请求")
    QApplication.processEvents()

    assert widget._running_node is not None
    titles = [item["title"] for item in widget._running_node.substeps]
    assert any("分析" in title or "检查" in title for title in titles)
    assert not any("导入" in title for title in titles)
    print("test_first_thinking_panel_prefers_user_analysis_intent_over_attachment_import_hint: OK")


def test_agent_thinking_widget_running_state_does_not_start_refresh_animation_timer():
    widget = AgentThinkingWidget(theme_mode="light", task_context="帮我分析当前对象结构")
    widget.show()
    widget.set_running("正在分析请求")
    QApplication.processEvents()

    assert not widget._typing_timer.isActive()
    assert widget._running_node is not None
    assert widget._running_node.detail_label.text() == "处理中..."
    print("test_agent_thinking_widget_running_state_does_not_start_refresh_animation_timer: OK")


def test_summary_mode_title_stays_as_summary_label():
    assert _resolve_thinking_activity_title("总结中", "创建下面的资源层级") == "总结中"
    assert _resolve_thinking_activity_title("正在总结", "任意任务") == "总结中"
    print("test_summary_mode_title_stays_as_summary_label: OK")


def test_step_progress_widget_does_not_become_top_level_window_during_construction():
    """Regression: constructing/snapshot-restoring a parentless StepProgressWidget
    must NOT call self.show(), which would promote it to a stray top-level
    "Python" window when restoring a chat history with multiple timelines."""
    widget = StepProgressWidget(2, ["读取工程", "整理结果"], theme_mode="light")
    # Without a parent and without explicit show(), the widget should remain
    # invisible until added to a layout.
    assert not widget.isVisible()
    assert widget.parent() is None

    snapshot = {
        "kind": "step_timeline",
        "title": "执行流程",
        "status": "执行完成 · 共 2 项",
        "steps": [
            {"description": "读取工程", "state": "done"},
            {"description": "整理结果", "state": "done"},
        ],
    }
    restored = StepProgressWidget(0, [], theme_mode="light")
    restored.apply_snapshot(snapshot)
    assert not restored.isVisible()
    assert restored.parent() is None

    # After being added to a layout, the parent layout's normal show flow
    # makes it visible without an explicit show() call.
    host = QWidget()
    host_layout = QVBoxLayout(host)
    host_layout.addWidget(restored)
    host.show()
    QApplication.processEvents()
    assert restored.isVisible()
    print("test_step_progress_widget_does_not_become_top_level_window_during_construction: OK")


def test_thinking_and_execution_boards_do_not_expand_vertically():
    thinking = AgentThinkingWidget(theme_mode="light", task_context="查询当前 Wwise 项目结构")
    progress = StepProgressWidget(2, ["读取工程", "整理结果"], theme_mode="light")

    assert thinking.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum
    assert thinking._steps_container.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum
    assert progress.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Preferred
    assert progress.steps_container.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Preferred
    print("test_thinking_and_execution_boards_do_not_expand_vertically: OK")


if __name__ == "__main__":
    test_local_authority_doc_does_not_hit_web()
    test_missing_local_guidance_uses_web_fallback()
    test_message_bubble_resizes_attachments()
    test_attachment_only_message_hides_empty_editor_area_and_keeps_edit()
    test_message_text_linkifies_http_urls_without_touching_code_blocks()
    test_message_bubble_opens_http_links_and_rejects_file_links()
    test_enter_edit_mode_uses_original_message_text()
    test_load_selected_chat_restores_user_and_assistant_bubbles()
    test_chat_scrollbar_stays_visible_during_processing()
    test_handle_agent_confirmation_removes_confirmation_widget()
    test_confirmation_summary_result_blocks_code_execution()
    test_step_progress_widget_timeline_states()
    test_step_progress_widget_reuses_single_card_flow()
    test_step_progress_widget_can_collapse_and_restore_from_snapshot()
    test_step_progress_widget_snapshot_roundtrip()
    test_describe_code_step_accepts_dict_code_block()
    test_parse_legacy_timeline_from_failed_message()
    test_code_executor_allows_uuid_import()
    test_code_executor_allows_common_safe_imports()
    test_code_executor_still_blocks_dangerous_imports()
    test_agent_thinking_widget_keeps_timeline_visible_after_finish()
    test_agent_thinking_widget_can_collapse_and_restore_from_snapshot()
    test_agent_thinking_widget_uses_task_context_for_dynamic_substeps()
    test_first_thinking_panel_prefers_user_analysis_intent_over_attachment_import_hint()
    test_agent_thinking_widget_running_state_does_not_start_refresh_animation_timer()
    test_summary_mode_title_stays_as_summary_label()
    test_step_progress_widget_does_not_become_top_level_window_during_construction()
    test_thinking_and_execution_boards_do_not_expand_vertically()
    print("\n=== WAAPI authority + attachment bubble tests passed ===")
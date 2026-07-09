"""Smoke tests for Settings memory management UI."""

import os
import sys
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication, QLabel

app = QApplication.instance() or QApplication(sys.argv)

from src.gui.settings_dialog import SettingsDialog


class FakeAuthSession:
    def get_user_id(self):
        return ""

    def get_username(self):
        return ""

    def get_token(self):
        return ""

    def get_api_key(self):
        return ""

    def get_base_url(self):
        return ""


def labels_in(widget):
    return [label.text() for label in widget.findChildren(QLabel)]


def test_settings_section_order_and_general_notifications():
    page = SettingsDialog(FakeAuthSession(), {"memory": {"enabled": True}})
    page.apply_theme("light")

    section_keys = [section["key"] for section in page.settings_sections]
    general_index = section_keys.index("general")
    memory_index = section_keys.index("memory")
    skill_index = section_keys.index("skills")
    assert general_index < memory_index < skill_index

    general_labels = labels_in(page.content_stack.widget(general_index))
    assert any(("任务提醒" in text) or ("Task Notifications" in text) for text in general_labels)


def test_memory_settings_signal():
    page = SettingsDialog(FakeAuthSession(), {"memory": {"enabled": True}})
    received_settings = []
    page.memory_settings_updated.connect(lambda payload: received_settings.append(payload))

    page.memory_toggles["enabled"].setChecked(False, animate=False)

    assert received_settings and received_settings[-1]["enabled"] is False


def test_memory_records_render_and_folder_resolution():
    page = SettingsDialog(FakeAuthSession(), {"memory": {"enabled": True}})
    records = {
        "session": [
            {
                "id": "s1",
                "category": "markdown_session",
                "display_type": "chat-abc",
                "display_content": "当前对话摘要",
                "content": "# 当前对话记忆",
                "updated_at": "2026-05-07T10:00:00",
            }
        ],
        "repo": [
            {
                "id": "r1",
                "category": "markdown_project",
                "display_type": "D:/Project/X6.wproj",
                "display_content": "工程对象路径",
                "content": "# 工程记忆",
                "updated_at": "2026-05-07T10:01:00",
            }
        ],
        "user": [
            {
                "id": "u1",
                "category": "preference",
                "content": "长期偏好",
                "updated_at": "2026-05-07T10:02:00",
            }
        ],
    }
    page.set_memory_records(records)

    assert page.memory_tables["session"].rowCount() == 1
    assert page.memory_tables["repo"].rowCount() == 1
    assert page.memory_tables["user"].rowCount() == 1
    assert page.memory_tables["session"].item(0, 0).text() == "chat-abc"
    assert "当前对话摘要" in page.memory_tables["session"].item(0, 1).text()
    assert page.memory_tables["repo"].item(0, 0).text() == "D:/Project/X6.wproj"

    with tempfile.TemporaryDirectory() as tmp:
        memory_file = os.path.join(tmp, "memory.md")
        with open(memory_file, "w", encoding="utf-8") as handle:
            handle.write("# memory")
        assert page._memory_record_folder({"path": memory_file}) == tmp


def test_user_memory_add_signal():
    page = SettingsDialog(FakeAuthSession(), {"memory": {"enabled": True}})
    added = []
    page.user_memory_add_requested.connect(lambda content: added.append(content))

    page.user_memory_input.setText("回答优先使用中文")
    page.on_add_user_memory()

    assert added == ["回答优先使用中文"]
    assert page.user_memory_input.text() == ""

"""Smoke tests for Markdown-backed memory service."""
import os
import sys
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.services.memory_service import MemoryService


with tempfile.TemporaryDirectory() as tmp:
    service = MemoryService(base_dir=tmp)

    assert service.user_path().name == "memories.md"
    assert service.session_path("chat-1").name == "chat-1.md"
    assert service.repo_path("E:/Project/Foo.wproj").suffix == ".md"
    print("markdown paths: OK")

    turn = service.record_turn_summary("chat-1", "分析当前总线", "已查询并总结。")
    assert turn is not None
    session_md = service.session_path("chat-1").read_text(encoding="utf-8")
    assert "# 当前对话记忆" in session_md
    assert "分析当前总线" in session_md
    assert service.list_records("session", "chat-1")[0]["id"] == "session:markdown"
    print("session markdown memory: OK")

    refresh_messages = service.build_memory_refresh_messages(
        chat_id="chat-1",
        project_key="E:/Project/Foo.wproj",
        recent_messages=[
            {"role": "user", "content": "帮我分析当前总线结构"},
            {"role": "assistant", "content": "当前工程有 Master Audio Bus 和 Music 子总线。"},
        ],
        action_summaries=["Step 1: ak.wwise.core.object.get returned Master Audio Bus and Music"],
    )
    assert refresh_messages and refresh_messages[-1]["role"] == "user"
    updated = service.apply_memory_refresh_response(
        chat_id="chat-1",
        project_key="E:/Project/Foo.wproj",
        response_text=(
            '{"session":{"should_update":true,"summary":"用户需要分析当前总线结构；已确认存在 Master Audio Bus 和 Music 子总线。"},'
            '"repo":{"should_update":true,"memory":"工程包含 Master Audio Bus 和 Music 子总线。"}}'
        ),
    )
    assert updated == {"session": True, "repo": True}
    refreshed_session = service.session_path("chat-1").read_text(encoding="utf-8")
    assert "## 摘要" in refreshed_session
    refreshed_record = service.list_records("session", "chat-1")[0]
    assert refreshed_record["display_type"] == "chat-1"
    assert "Master Audio Bus" in refreshed_record["display_content"]
    repo_record = service.list_records("repo", "E:/Project/Foo.wproj")[0]
    assert repo_record["display_type"] == "E:/Project/Foo.wproj"
    assert "Music 子总线" in repo_record["display_content"]
    print("llm memory refresh: OK")

    service.append_record(
        "user",
        "default",
        "用户偏好：回答使用中文。",
        category="preference",
        tags=["language"],
    )
    user_md = service.user_path().read_text(encoding="utf-8")
    assert "# 长期用户记忆" in user_md
    assert "用户偏好：回答使用中文。" in user_md
    found = service.search_relevant("user", "default", "中文回答", limit=3)
    assert found and found[0]["category"] == "markdown_user"
    print("user markdown memory: OK")

    action = service.record_action_summary(
        "E:/Project/Foo.wproj",
        "chat-1",
        "Executed 1 step(s): 1 succeeded, 0 failed\n  Step 1: ak.wwise.core.object.get",
    )
    assert action is not None
    repo_md = service.repo_path("E:/Project/Foo.wproj").read_text(encoding="utf-8")
    assert "# 工程记忆" in repo_md
    assert "## 工程结构" in repo_md
    assert "## 最佳实践" in repo_md
    print("repo markdown memory: OK")

    context = service.build_context_for_llm(
        chat_id="chat-1",
        project_key="E:/Project/Foo.wproj",
        query="object.get 总线",
        settings={
            "enabled": True,
            "auto_inject_user": True,
            "auto_inject_session": True,
            "auto_inject_repo": True,
            "max_memory_context_chars": 12000,
        },
    )
    assert "MEMORY CONTEXT" in context
    assert "[User Memory]" in context
    assert "[Session Memory]" in context
    assert "[Repo Memory]" in context
    print("markdown context render: OK")

    disabled_context = service.build_context_for_llm(
        chat_id="chat-1",
        project_key="E:/Project/Foo.wproj",
        query="anything",
        settings={"enabled": False},
    )
    assert disabled_context == ""
    print("memory disabled: OK")

    legacy_json = service.session_dir / "chat-1-old.json"
    legacy_json.write_text('{"records": []}', encoding="utf-8")
    service.delete_session_memory("chat-1")
    assert not service.session_path("chat-1").exists()
    assert not legacy_json.exists()
    print("delete session markdown memory: OK")

print("\n=== Memory service tests passed ===")

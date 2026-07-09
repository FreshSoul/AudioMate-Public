import os
import sys
import importlib.util

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.tools import create_default_registry


def _load_engine_module(filename: str):
    path = os.path.join(PROJECT_ROOT, "src", "engine", filename)
    module_name = "test_" + filename.replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_prompt_guidance = _load_engine_module("prompt_guidance.py")
_waapi_context = _load_engine_module("waapi_context.py")

build_mcp_prompt_guidance = _prompt_guidance.build_mcp_prompt_guidance
build_structured_tool_prompt_guidance = _prompt_guidance.build_structured_tool_prompt_guidance
build_connected_waapi_context = _waapi_context.build_connected_waapi_context
build_disconnected_waapi_context = _waapi_context.build_disconnected_waapi_context
perform_waapi_preflight = _waapi_context.perform_waapi_preflight
should_collect_waapi_context = _waapi_context.should_collect_waapi_context
should_use_waapi_retrieval = _waapi_context.should_use_waapi_retrieval
strip_waql_guidance = _waapi_context.strip_waql_guidance


class FakeWaapi:
    def __init__(self, connected=True, version=True):
        self.connected = connected
        self.version = version

    def get_wwise_version(self):
        if not self.version:
            return None
        return {
            "display": "2025.1.7",
            "year": 2025,
            "is_2025_or_later": True,
        }

    def get_selected_objects(self):
        return {"objects": [{"id": "{11111111-2222-3333-4444-555555555555}", "name": "SFX", "type": "Sound"}]}


def test_structured_tool_guidance_contains_manifest():
    guidance = build_structured_tool_prompt_guidance(create_default_registry(), "Ask Mode")
    assert "call_structured_tool" in guidance
    assert "get_waapi_schema" in guidance
    assert "argsSchema" in guidance
    assert "optionsSchema" in guidance
    assert "external_agent.codex" in guidance
    assert "external_agent.claude_code" in guidance
    assert "powershell.run" in guidance
    assert "run_powershell" in guidance
    assert "waapi.get_selected_objects" in guidance
    assert "waapi.set_property" in guidance
    assert "waapi.batch_set_property" in guidance
    assert "waapi.call_documented_read" in guidance
    assert "waapi.call_documented_write" in guidance
    assert "waapi.get_version_context" in guidance
    assert "waapi.resolve_hierarchy_root" in guidance
    assert "waapi.get_busses" in guidance
    assert "waapi.resolve_main_bus" in guidance
    assert "waapi.set_object_output_bus" in guidance
    assert "waapi.set_reference" in guidance
    assert "waapi.get_attenuation_curve" in guidance
    assert "waapi.get_music_structure" in guidance
    assert "waapi.create_music_cue" in guidance
    assert "waapi.soundengine_post_event" in guidance
    assert "waapi.soundbank_generate" in guidance
    assert "waapi.blendcontainer_set_assignment" in guidance
    assert "waapi.switchcontainer_set_assignment" in guidance
    assert "Common WAAPI routing" in guidance
    assert "Version-aware routing" in guidance
    assert "Bus routing" in guidance
    assert "Runtime SoundEngine routing" in guidance
    assert "SoundBank routing" in guidance
    assert "Container assignment routing" in guidance
    assert "Interactive Music routing" in guidance
    assert "does not vendor third-party WAAPI documentation" in guidance
    print("test_structured_tool_guidance_contains_manifest: OK")


def test_mcp_guidance_mentions_feishu_when_configured():
    guidance = build_mcp_prompt_guidance(
        {
            "enabled": True,
            "enabled_configs": [
                {"name": "Feishu Docs", "transport": "streamable_http", "url": "https://example.com/mcp"}
            ],
        },
        "读取飞书文档",
    )
    assert "Feishu/Lark" in guidance
    assert "Feishu Docs" in guidance
    print("test_mcp_guidance_mentions_feishu_when_configured: OK")


def test_waapi_context_helpers():
    assert should_collect_waapi_context("waapi_action")
    assert should_use_waapi_retrieval("project_source_audio")
    assert not should_collect_waapi_context("general_chat")
    assert "waql" not in strip_waql_guidance("keep\nWAQL remove\nkeep2").lower()

    disconnected = build_disconnected_waapi_context(requires_live_waapi_data=True)
    assert "Connected: False" in disconnected
    assert "Needs live project data: True" in disconnected

    connected = build_connected_waapi_context(FakeWaapi())
    assert "Connected: True" in connected
    assert "\\Containers" in connected
    assert "SFX" in connected

    assert perform_waapi_preflight(FakeWaapi()).get("ok") is True
    assert perform_waapi_preflight(FakeWaapi(connected=False)).get("ok") is False
    assert perform_waapi_preflight(FakeWaapi(version=False)).get("ok") is False
    print("test_waapi_context_helpers: OK")


if __name__ == "__main__":
    test_structured_tool_guidance_contains_manifest()
    test_mcp_guidance_mentions_feishu_when_configured()
    test_waapi_context_helpers()

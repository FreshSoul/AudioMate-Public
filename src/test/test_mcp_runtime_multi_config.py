"""Regression tests for MCPRuntimeService multi-config enable/order behavior."""

import os
import sys

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.services.mcp_runtime import MCPRuntimeService


class FakeExitStack:
    async def aclose(self):
        return None


class FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = f"{name} description"
        self.inputSchema = {"type": "object"}


class FakeListResponse:
    def __init__(self, names):
        self.tools = [FakeTool(name) for name in names]


class FakeContent:
    def __init__(self, text):
        self.text = text

    def model_dump(self, mode="json"):
        return {"type": "text", "text": self.text}


class FakeCallResult:
    isError = False

    def __init__(self, text):
        self.content = [FakeContent(text)]


class FakeSession:
    def __init__(self, config_name, tool_map, calls):
        self.config_name = config_name
        self.tool_map = tool_map
        self.calls = calls

    async def list_tools(self):
        return FakeListResponse(self.tool_map.get(self.config_name, []))

    async def call_tool(self, name, arguments, read_timeout_seconds):
        self.calls.append((self.config_name, name, arguments))
        return FakeCallResult(f"{self.config_name}:{name}")


class FakeMCPRuntimeService(MCPRuntimeService):
    def __init__(self, app_settings, tool_map):
        self.tool_map = tool_map
        self.calls = []
        super().__init__(app_settings)

    async def _open_session(self, config_name):
        return FakeSession(config_name, self.tool_map, self.calls), FakeExitStack()


settings = {
    "mcp_configs": {
        "legacy": {"url": "http://legacy.example/mcp"},
        "first": {"enabled": True, "url": "http://first.example/mcp"},
        "second": {"enabled": True, "url": "http://second.example/mcp"},
        "disabled": {"enabled": False, "url": "http://disabled.example/mcp"},
    },
    "mcp_config_order": ["second", "unknown", "first", "disabled", "legacy"],
    "mcp_selected_config": "legacy",
}

service = FakeMCPRuntimeService(settings, {"second": ["shared", "second_only"], "first": ["shared", "first_only"]})

assert service._order == ["second", "first", "disabled", "legacy"]
assert service._enabled_names == ["second", "first"]
assert service._selected_name == "second"
assert service._configs["legacy"]["enabled"] is False
assert service.has_active_config() is True

summary = service.describe_active_config()
assert summary["enabled"] is True
assert summary["selected"] == "second"
assert summary["enabled_count"] == 2
assert [item["name"] for item in summary["enabled_configs"]] == ["second", "first"]

tools = service.list_tools(force_refresh=True)
assert [item["name"] for item in tools] == ["shared", "second_only", "shared", "first_only"]
assert [item["config_name"] for item in tools] == ["second", "second", "first", "first"]

result = service.call_tool("shared", {"value": 1})
assert result["config_name"] == "second"
assert result["text"] == "second:shared"
assert service.calls[-1] == ("second", "shared", {"value": 1})

explicit_result = service.call_tool("shared", {"value": 2}, config_name="first")
assert explicit_result["config_name"] == "first"
assert explicit_result["text"] == "first:shared"
assert service.calls[-1] == ("first", "shared", {"value": 2})

empty_service = MCPRuntimeService({"mcp_configs": {"old": {"url": "http://old.example/mcp"}}})
assert empty_service.has_active_config() is False
assert empty_service.describe_active_config()["enabled_configs"] == []

print("test_mcp_runtime_multi_config: OK")

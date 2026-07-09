"""Smoke test for CodeExecutor tool-object aliases."""

from src.utils.execution import CodeExecutor


class DummyWwiseClient:
    def call(self, uri, args=None, options=None):
        return {"uri": uri, "args": args or {}, "options": options or {}}


class DummyAgentTools:
    def analyze_selected_sources_full_route_loudness(self, source_files=None):
        return {
            "count": 1,
            "results": [{"estimated_full_route_lufs": -18.5}],
            "warnings": [],
        }

    def normalize_audio_loudness(self):
        return {"changed": True}


executor = CodeExecutor(
    context_globals={
        "waapi_client": DummyWwiseClient(),
        "client": DummyWwiseClient(),
        "agent_tools": DummyAgentTools(),
    }
)

output = executor.execute(
    """
report = waapi_client.analyze_selected_sources_full_route_loudness()
print(report.get('count'))
print(report.get('results', [])[0].get('estimated_full_route_lufs'))
"""
)

assert "1" in output
assert "-18.5" in output

try:
    getattr(executor.execution_state["waapi_client"], "normalize_audio_loudness")
except AttributeError:
    pass
else:
    raise AssertionError("write helper should not be exposed through waapi_client fallback")

print("test_execution_tool_alias: OK")
import os
import sys

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.engine.plan_executor import PlanExecutor
from src.engine.planner import Plan, PlanStep, PlanVerifier, parse_plan_json
from src.tools import create_default_registry
from src.tools.base import ToolContext, Tool, ToolResult, ToolResultStatus
from src.tools.registry import ToolRegistry
from src.gui.runtime_support import _ReadOnlyWwiseClient, build_executor_context


class EchoTool(Tool):
    @property
    def name(self):
        return "echo"

    @property
    def description(self):
        return "Echo text."

    @property
    def input_schema(self):
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    def is_read_only(self, input=None):
        return True

    def is_concurrency_safe(self):
        return True

    def execute(self, input, context):
        return ToolResult(output=input["text"], data={"text": input["text"]})


class FakeWaapi:
    connected = True

    def __init__(self, year=2025):
        self.calls = []
        self.year = year

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.object.get" and isinstance(args, dict) and isinstance(args.get("from"), dict):
            object_types = args["from"].get("ofType")
            if object_types and any(item in object_types for item in ("Bus", "AuxBus")):
                return {
                    "return": [
                        {"id": "{bus-main}", "name": "Main Audio Bus", "type": "Bus", "path": "\\Busses\\Default Work Unit\\Main Audio Bus"},
                        {"id": "{bus-music}", "name": "Music", "type": "Bus", "path": "\\Busses\\Default Work Unit\\Main Audio Bus\\Music"},
                        {"id": "{aux-reverb}", "name": "Reverb", "type": "AuxBus", "path": "\\Busses\\Default Work Unit\\Main Audio Bus\\Reverb"},
                    ]
                }
        return {"ok": True, "uri": uri}

    def get_selected_objects(self):
        return {"objects": [{"id": "{11111111-2222-3333-4444-555555555555}", "name": "SFX", "type": "Sound"}]}

    def get_property(self, object_id, property_name):
        return -3.0

    def get_schema(self, uri, include_examples=False):
        return {"ok": True, "uri": uri, "include_examples": bool(include_examples), "schema": {}}

    def get_functions(self):
        return [
            "ak.wwise.core.getProjectInfo",
            "ak.wwise.core.project.save",
            "ak.wwise.core.object.get",
            "ak.wwise.core.soundbank.generate",
            "ak.soundengine.postEvent",
        ]

    def get_wwise_version(self):
        return {
            "display": f"{self.year}.1.0",
            "year": self.year,
            "major": 1,
            "minor": 0,
            "build": 1,
            "is_2025_or_later": self.year >= 2025,
        }

    def set_property(self, object_id, property_name, value):
        self.calls.append(("set_property", object_id, property_name, value))
        return True


class _FakeModeSelector:
    def __init__(self, mode):
        self.mode = mode

    def currentText(self):
        return self.mode


class _FakeRetriever:
    def lookup_doc(self, *_args, **_kwargs):
        return ""

    def search_functions(self, *_args, **_kwargs):
        return []


class _FakeAgentTools:
    def __getattr__(self, _name):
        def _missing(*_args, **_kwargs):
            return {}
        return _missing


class _FakeOwner:
    def __init__(self, mode="Ask Mode"):
        self.mode_selector = _FakeModeSelector(mode)
        self.waapi_client = FakeWaapi()
        self.agent_tools = _FakeAgentTools()
        self.waapi_retriever = _FakeRetriever()
        self.tool_registry = create_default_registry()
        self.code_executor = None

    def fetch_webpage(self, *_args, **_kwargs):
        return {}

    def get_active_mcp_config(self):
        return {}

    def list_mcp_tools(self, *_args, **_kwargs):
        return []

    def call_mcp_tool(self, *_args, **_kwargs):
        return {}

    def read_feishu_doc(self, *_args, **_kwargs):
        return {}


def test_registry_manifest_contains_planner_metadata():
    registry = create_default_registry()
    manifest = registry.to_manifest(mode="Ask Mode")
    by_name = {item["name"]: item for item in manifest}
    assert "read_user_file" in by_name
    assert "waapi.get_selected_objects" in by_name
    assert "waapi.call_documented_read" in by_name
    assert "waapi.call_documented_write" in by_name
    assert "waapi.project_save" in by_name
    assert "waapi.get_version_context" in by_name
    assert "waapi.resolve_hierarchy_root" in by_name
    assert "waapi.get_busses" in by_name
    assert "waapi.resolve_main_bus" in by_name
    assert "waapi.create_bus" in by_name
    assert "waapi.set_bus_property" in by_name
    assert "waapi.set_object_output_bus" in by_name
    assert "waapi.soundengine_get_state" in by_name
    assert "waapi.soundengine_post_event" in by_name
    assert "waapi.soundengine_set_rtpc" in by_name
    assert "waapi.soundbank_get_inclusions" in by_name
    assert "waapi.soundbank_generate" in by_name
    assert "waapi.blendcontainer_set_assignment" in by_name
    assert "waapi.switchcontainer_set_assignment" in by_name
    assert "waapi.set_property" in by_name
    assert "waapi.batch_set_property" in by_name
    assert "waapi.set_reference" in by_name
    assert "waapi.get_property_reference_names" in by_name
    assert "waapi.find_in_project_explorer" in by_name
    assert "waapi.get_music_structure" in by_name
    assert "waapi.create_music_object" in by_name
    assert "waapi.create_music_cue" in by_name
    assert "waapi.set_state_groups" in by_name
    assert "waapi.set_state_properties" in by_name
    assert by_name["waapi.get_selected_objects"]["available"] is True
    assert by_name["waapi.call_documented_read"]["available"] is True
    assert by_name["waapi.call_documented_write"]["available"] is False
    assert by_name["waapi.project_save"]["available"] is False
    assert by_name["waapi.get_version_context"]["available"] is True
    assert by_name["waapi.resolve_hierarchy_root"]["available"] is True
    assert by_name["waapi.get_busses"]["available"] is True
    assert by_name["waapi.resolve_main_bus"]["available"] is True
    assert by_name["waapi.create_bus"]["available"] is False
    assert by_name["waapi.set_bus_property"]["available"] is False
    assert by_name["waapi.set_object_output_bus"]["available"] is False
    assert by_name["waapi.soundengine_get_state"]["available"] is True
    assert by_name["waapi.soundengine_post_event"]["available"] is False
    assert by_name["waapi.soundengine_set_rtpc"]["available"] is False
    assert by_name["waapi.soundbank_get_inclusions"]["available"] is True
    assert by_name["waapi.soundbank_generate"]["available"] is False
    assert by_name["waapi.blendcontainer_set_assignment"]["available"] is False
    assert by_name["waapi.switchcontainer_set_assignment"]["available"] is False
    assert by_name["waapi.set_property"]["available"] is False
    assert by_name["waapi.batch_set_property"]["available"] is False
    assert by_name["waapi.set_reference"]["available"] is False
    assert by_name["waapi.get_property_reference_names"]["available"] is True
    assert by_name["waapi.find_in_project_explorer"]["available"] is True
    assert by_name["waapi.get_music_structure"]["available"] is True
    assert by_name["waapi.create_music_object"]["available"] is False
    assert by_name["waapi.create_music_cue"]["available"] is False
    assert by_name["waapi.set_state_groups"]["available"] is False
    assert by_name["waapi.set_state_properties"]["available"] is False
    assert by_name["read_user_file"]["read_only"] is True
    assert by_name["write_user_file"]["available"] is False
    assert by_name["write_file_tree"]["available"] is False
    assert by_name["analyze_directory_loudness"]["available"] is True
    assert by_name["import_audio_files_to_selected_wwise"]["requires_waapi"] is True
    assert "wwise-project" in by_name["import_audio_files_to_selected_wwise"]["side_effects"]
    print("test_registry_manifest_contains_planner_metadata: OK")


def test_parse_and_verify_valid_plan():
    registry = ToolRegistry()
    registry.register(EchoTool())
    plan = parse_plan_json('{"goal":"demo","steps":[{"id":"s1","title":"Say","tool":"echo","input":{"text":"hi"}}]}')
    result = PlanVerifier(registry).verify(plan, ToolContext(mode="Ask Mode"))
    assert result.valid, [issue.to_dict() for issue in result.issues]
    print("test_parse_and_verify_valid_plan: OK")


def test_verifier_rejects_bad_plan_inputs():
    registry = ToolRegistry()
    registry.register(EchoTool())
    plan = Plan(
        goal="bad",
        steps=[
            PlanStep(id="s1", title="Bad", tool="missing", input={}),
            PlanStep(id="s2", title="Wrong type", tool="echo", input={"text": 1}, depends_on=["later"]),
            PlanStep(id="s3", title="Placeholder", tool="echo", input={"text": "{object_id}"}, depends_on=["s2"]),
        ],
    )
    result = PlanVerifier(registry).verify(plan, ToolContext(mode="Ask Mode"))
    messages = [issue.message for issue in result.issues]
    assert not result.valid
    assert any("Unknown tool" in message for message in messages)
    assert any("must be string" in message for message in messages)
    assert any("must refer to an earlier step" in message for message in messages)
    assert any("unresolved placeholder" in message for message in messages)
    print("test_verifier_rejects_bad_plan_inputs: OK")


def test_plan_executor_runs_steps_in_order():
    registry = ToolRegistry()
    registry.register(EchoTool())
    plan = Plan(
        goal="run",
        steps=[
            PlanStep(id="s1", title="One", tool="echo", input={"text": "one"}),
            PlanStep(id="s2", title="Two", tool="echo", input={"text": "two"}, depends_on=["s1"]),
        ],
    )
    result = PlanExecutor(registry).execute(plan, ToolContext(mode="Ask Mode"))
    assert result.ok
    assert [record.step_id for record in result.records] == ["s1", "s2"]
    assert result.outputs["s2"] == {"text": "two"}
    print("test_plan_executor_runs_steps_in_order: OK")


def test_ask_mode_default_denies_write_tools():
    registry = create_default_registry()
    plan = Plan(
        goal="deny write",
        steps=[
            PlanStep(
                id="s1",
                title="Set volume",
                tool="waapi.set_property",
                input={
                    "object_id": "{11111111-2222-3333-4444-555555555555}",
                    "property_name": "Volume",
                    "value": -6,
                },
            )
        ],
    )
    result = PlanVerifier(registry).verify(plan, ToolContext(mode="Ask Mode", waapi_client=FakeWaapi()))
    messages = [issue.message for issue in result.issues]
    assert not result.valid
    assert any("not available in Ask Mode" in message for message in messages)
    print("test_ask_mode_default_denies_write_tools: OK")


def test_read_only_waapi_client_default_deny_policy():
    base = FakeWaapi()
    client = _ReadOnlyWwiseClient(base)
    assert client.call("ak.wwise.core.object.get", {"from": {"id": ["x"]}})["ok"] is True
    assert client.call("ak.soundengine.getState", {"stateGroup": "Music"})["ok"] is True
    try:
        client.call("ak.wwise.core.object.setProperty", {"object": "x", "property": "Volume", "value": 1})
    except PermissionError:
        pass
    else:
        raise AssertionError("Ask Mode should deny object.setProperty")
    try:
        client.call("ak.wwise.core.future.newProcedure", {})
    except PermissionError:
        pass
    else:
        raise AssertionError("Ask Mode should deny unknown future WAAPI procedures by default")
    try:
        client.call("ak.soundengine.postEvent", {"event": "Play_UI_Click"})
    except PermissionError:
        pass
    else:
        raise AssertionError("Ask Mode should deny runtime SoundEngine actions by default")
    print("test_read_only_waapi_client_default_deny_policy: OK")


def test_executor_context_exposes_structured_tool_call():
    ctx = build_executor_context(_FakeOwner("Ask Mode"))
    result = ctx["call_structured_tool"]("waapi.get_selected_objects", {})
    assert result["objects"][0]["name"] == "SFX"
    direct_schema = ctx["get_waapi_schema"]("ak.wwise.core.object.get", include_examples=True)
    assert direct_schema["include_examples"] is True
    schema = ctx["call_structured_tool"]("waapi.get_schema", {"uri": "ak.wwise.core.object.get"})
    assert schema["ok"] is True
    project_info = ctx["call_structured_tool"]("waapi.call_documented_read", {"uri": "ak.wwise.core.getProjectInfo"})
    assert project_info["ok"] is True
    version = ctx["call_structured_tool"]("waapi.get_version_context", {})
    assert version["is_2025_or_later"] is True
    root = ctx["call_structured_tool"]("waapi.resolve_hierarchy_root", {"kind": "music"})
    assert root["preferred"] == "\\Containers"
    status = ctx["call_structured_tool"]("external_agent.status", {})
    assert "codex" in status
    assert "claude_code" in status
    denied_external = ctx["call_structured_tool"](
        "external_agent.codex",
        {"prompt": "review this repo", "cwd": PROJECT_ROOT},
    )
    assert "error" in denied_external
    assert "Agent Mode" in denied_external["error"]
    denied = ctx["call_structured_tool"](
        "waapi.set_property",
        {
            "object_id": "{11111111-2222-3333-4444-555555555555}",
            "property_name": "Volume",
            "value": -6,
        },
    )
    assert "error" in denied
    assert "Ask Mode" in denied["error"]
    print("test_executor_context_exposes_structured_tool_call: OK")


def test_structured_waapi_tools_execute_common_calls():
    owner = _FakeOwner("Agent Mode")
    ctx = build_executor_context(owner)
    batch = ctx["call_structured_tool"](
        "waapi.batch_set_property",
        {
            "operations": [
                {
                    "object_id": "{11111111-2222-3333-4444-555555555555}",
                    "property_name": "Volume",
                    "value": -4,
                },
                {
                    "object_id": "{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}",
                    "property_name": "Pitch",
                    "value": 25,
                },
            ]
        },
    )
    assert batch["ok"] is True
    assert batch["updated_count"] == 2

    reference = ctx["call_structured_tool"](
        "waapi.set_reference",
        {
            "object_id": "{11111111-2222-3333-4444-555555555555}",
            "reference_name": "OutputBus",
            "target_id": "{22222222-3333-4444-5555-666666666666}",
        },
    )
    assert reference["ok"] is True

    highlight = ctx["call_structured_tool"](
        "waapi.find_in_project_explorer",
        {"object_ids": ["{11111111-2222-3333-4444-555555555555}"]},
    )
    assert highlight["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.ui.commands.execute"
    print("test_structured_waapi_tools_execute_common_calls: OK")


def test_documented_call_tools_are_policy_gated_without_vendored_docs():
    owner = _FakeOwner("Agent Mode")
    ctx = build_executor_context(owner)

    project_info = ctx["call_structured_tool"](
        "waapi.call_documented_read",
        {"uri": "ak.wwise.core.getProjectInfo", "args": {}, "options": {}},
    )
    assert project_info["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.core.getProjectInfo"

    invalid_shape = ctx["call_structured_tool"](
        "waapi.call_documented_read",
        {"uri": "not-a-waapi-uri", "args": {}},
    )
    assert "valid WAAPI URI shape" in invalid_shape["error"]

    owner.waapi_client.get_functions = lambda: ["ak.wwise.core.project.save"]
    unavailable = ctx["call_structured_tool"](
        "waapi.call_documented_read",
        {"uri": "ak.wwise.core.getProjectInfo", "args": {}},
    )
    assert "not available in the connected Wwise version" in unavailable["error"]

    write = ctx["call_structured_tool"](
        "waapi.call_documented_write",
        {"uri": "ak.wwise.core.project.save", "args": {}, "reason": "No dedicated project-save tool yet."},
    )
    assert write["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.core.project.save"

    dangerous = ctx["call_structured_tool"](
        "waapi.call_documented_write",
        {"uri": "ak.wwise.debug.testCrash", "args": {}, "reason": "test"},
    )
    assert "blocked by AudioMate policy" in dangerous["error"]

    ask_ctx = build_executor_context(_FakeOwner("Ask Mode"))
    denied = ask_ctx["call_structured_tool"](
        "waapi.call_documented_write",
        {"uri": "ak.wwise.core.project.save", "args": {}, "reason": "No dedicated project-save tool yet."},
    )
    assert "Ask Mode" in denied["error"]
    print("test_documented_call_tools_are_policy_gated_without_vendored_docs: OK")


def test_structured_interactive_music_tools_execute_documented_calls():
    owner = _FakeOwner("Agent Mode")
    ctx = build_executor_context(owner)

    structure = ctx["call_structured_tool"]("waapi.get_music_structure", {"object_id": "{music-root}", "limit": 10})
    assert structure["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.core.object.get"
    assert "music:playlistRoot" in owner.waapi_client.calls[-1][2]["return"]

    created = ctx["call_structured_tool"](
        "waapi.create_music_object",
        {
            "parent": "{parent}",
            "type": "MusicSegment",
            "name": "Combat_A",
            "onNameConflict": "rename",
            "properties": {"Color": 1},
        },
    )
    assert created["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.core.object.create"
    assert owner.waapi_client.calls[-1][1]["type"] == "MusicSegment"
    assert owner.waapi_client.calls[-1][1]["@Color"] == 1

    cue = ctx["call_structured_tool"](
        "waapi.create_music_cue",
        {"parent_segment": "{segment}", "name": "LoopExit", "time_ms": 1200, "cue_type": 2},
    )
    assert cue["ok"] is True
    assert owner.waapi_client.calls[-1][1]["type"] == "MusicCue"
    assert owner.waapi_client.calls[-1][1]["list"] == "Cues"
    assert owner.waapi_client.calls[-1][1]["@TimeMs"] == 1200

    state_groups = ctx["call_structured_tool"](
        "waapi.set_state_groups",
        {"object_id": "{music-switch}", "state_groups": ["{state-group}"]},
    )
    assert state_groups["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.core.object.setStateGroups"

    state_properties = ctx["call_structured_tool"](
        "waapi.set_state_properties",
        {"object_id": "{music-switch}", "state_properties": ["Volume"]},
    )
    assert state_properties["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.core.object.setStateProperties"

    ask_ctx = build_executor_context(_FakeOwner("Ask Mode"))
    denied = ask_ctx["call_structured_tool"](
        "waapi.create_music_cue",
        {"parent_segment": "{segment}", "name": "Denied", "time_ms": 100},
    )
    assert "Ask Mode" in denied["error"]
    print("test_structured_interactive_music_tools_execute_documented_calls: OK")


def test_structured_version_tools_choose_2025_and_legacy_roots():
    owner_2025 = _FakeOwner("Ask Mode")
    ctx_2025 = build_executor_context(owner_2025)
    root_2025 = ctx_2025["call_structured_tool"]("waapi.resolve_hierarchy_root", {"kind": "music"})
    assert root_2025["preferred"] == "\\Containers"
    structure_2025 = ctx_2025["call_structured_tool"]("waapi.get_music_structure", {"limit": 5})
    assert structure_2025["ok"] is True
    assert owner_2025.waapi_client.calls[-1][1]["from"] == {"path": ["\\Containers"]}

    owner_legacy = _FakeOwner("Ask Mode")
    owner_legacy.waapi_client = FakeWaapi(year=2024)
    ctx_legacy = build_executor_context(owner_legacy)
    root_legacy = ctx_legacy["call_structured_tool"]("waapi.resolve_hierarchy_root", {"kind": "music"})
    assert root_legacy["preferred"] == "\\Interactive Music Hierarchy"
    structure_legacy = ctx_legacy["call_structured_tool"]("waapi.get_music_structure", {"limit": 5})
    assert structure_legacy["ok"] is True
    assert owner_legacy.waapi_client.calls[-1][1]["from"] == {"path": ["\\Interactive Music Hierarchy"]}
    print("test_structured_version_tools_choose_2025_and_legacy_roots: OK")


def test_structured_bus_tools_handle_2025_bus_changes():
    ask_owner = _FakeOwner("Ask Mode")
    ask_ctx = build_executor_context(ask_owner)

    root = ask_ctx["call_structured_tool"]("waapi.resolve_hierarchy_root", {"kind": "busses"})
    assert root["preferred"] == "\\Busses"

    busses = ask_ctx["call_structured_tool"]("waapi.get_busses", {})
    assert busses["ok"] is True
    assert busses["preferred_root"] == "\\Busses"
    assert busses["count"] == 3

    main_bus = ask_ctx["call_structured_tool"]("waapi.resolve_main_bus", {})
    assert main_bus["ok"] is True
    assert main_bus["bus"]["name"] == "Main Audio Bus"

    denied = ask_ctx["call_structured_tool"]("waapi.set_object_output_bus", {"object_ids": ["{sound}"], "bus_id": "{bus-main}"})
    assert "Ask Mode" in denied["error"]

    agent_owner = _FakeOwner("Agent Mode")
    agent_ctx = build_executor_context(agent_owner)
    created = agent_ctx["call_structured_tool"]("waapi.create_bus", {"parent": "{bus-main}", "type": "Bus", "name": "Music Stem", "properties": {"BusVolume": -3}})
    assert created["ok"] is True
    assert agent_owner.waapi_client.calls[-1][0] == "ak.wwise.core.object.create"
    assert agent_owner.waapi_client.calls[-1][1]["type"] == "Bus"
    assert agent_owner.waapi_client.calls[-1][1]["@BusVolume"] == -3

    bad_create = agent_ctx["call_structured_tool"]("waapi.create_bus", {"parent": "{bus-main}", "type": "AuxBus", "name": "Bad", "references": {"OutputBus": "{bus-main}"}})
    assert "OutputBus" in bad_create["error"]

    prop = agent_ctx["call_structured_tool"]("waapi.set_bus_property", {"bus_id": "{bus-main}", "property_name": "BusVolume", "value": -6})
    assert prop["ok"] is True
    assert agent_owner.waapi_client.calls[-1][0] == "ak.wwise.core.object.setProperty"

    bad_prop = agent_ctx["call_structured_tool"]("waapi.set_bus_property", {"bus_id": "{bus-main}", "property_name": "OutputBus", "value": "{bus-music}"})
    assert "OutputBus" in bad_prop["error"]

    routed = agent_ctx["call_structured_tool"]("waapi.set_object_output_bus", {"object_ids": ["{sound}"], "bus_id": "{bus-main}"})
    assert routed["ok"] is True
    assert agent_owner.waapi_client.calls[-1][0] == "ak.wwise.core.object.set"
    assert agent_owner.waapi_client.calls[-1][1]["objects"][0]["@OverrideOutput"] is True
    assert agent_owner.waapi_client.calls[-1][1]["objects"][0]["@OutputBus"] == "{bus-main}"
    print("test_structured_bus_tools_handle_2025_bus_changes: OK")


def test_structured_runtime_soundengine_tools_execute_documented_calls():
    owner = _FakeOwner("Agent Mode")
    ctx = build_executor_context(owner)

    state = ctx["call_structured_tool"]("waapi.soundengine_get_state", {"stateGroup": "Character"})
    assert state["ok"] is True
    assert owner.waapi_client.calls[-1] == ("ak.soundengine.getState", {"stateGroup": "Character"}, None)

    event = ctx["call_structured_tool"]("waapi.soundengine_post_event", {"event": "Play_UI_Click", "gameObject": 1001})
    assert event["ok"] is True
    assert owner.waapi_client.calls[-1] == ("ak.soundengine.postEvent", {"event": "Play_UI_Click", "gameObject": 1001}, None)

    rtpc = ctx["call_structured_tool"]("waapi.soundengine_set_rtpc", {"rtpc": "Rain_Intensity", "value": 74, "gameObject": 1001})
    assert rtpc["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.soundengine.setRTPCValue"

    switch = ctx["call_structured_tool"]("waapi.soundengine_set_switch", {"switchGroup": "Ground", "switchState": "Gravel", "gameObject": 1001})
    assert switch["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.soundengine.setSwitch"

    ask_ctx = build_executor_context(_FakeOwner("Ask Mode"))
    denied = ask_ctx["call_structured_tool"]("waapi.soundengine_post_event", {"event": "Play_UI_Click"})
    assert "Ask Mode" in denied["error"]
    print("test_structured_runtime_soundengine_tools_execute_documented_calls: OK")


def test_structured_soundbank_and_container_tools_execute_documented_calls():
    owner = _FakeOwner("Agent Mode")
    ctx = build_executor_context(owner)

    save = ctx["call_structured_tool"]("waapi.project_save", {"autoCheckOutToSourceControl": False})
    assert save["ok"] is True
    assert owner.waapi_client.calls[-1] == ("ak.wwise.core.project.save", {"autoCheckOutToSourceControl": False}, None)

    inclusions = ctx["call_structured_tool"]("waapi.soundbank_get_inclusions", {"soundbank": "MainBank"})
    assert inclusions["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.core.soundbank.getInclusions"

    set_inclusions = ctx["call_structured_tool"](
        "waapi.soundbank_set_inclusions",
        {"soundbank": "MainBank", "operation": "add", "inclusions": [{"object": "Event:Play_Music", "filter": ["events", "media"]}]},
    )
    assert set_inclusions["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.core.soundbank.setInclusions"

    generate = ctx["call_structured_tool"]("waapi.soundbank_generate", {"soundbanks": [{"name": "MainBank"}], "platforms": ["Windows"], "writeToDisk": True})
    assert generate["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.core.soundbank.generate"

    blend = ctx["call_structured_tool"]("waapi.blendcontainer_set_assignment", {"operation": "add", "object": "{blend-track}", "child": "{child}", "index": 0})
    assert blend["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.core.blendContainer.addAssignment"

    switch_assignment = ctx["call_structured_tool"]("waapi.switchcontainer_set_assignment", {"operation": "remove", "child": "{child}", "stateOrSwitch": "{state}"})
    assert switch_assignment["ok"] is True
    assert owner.waapi_client.calls[-1][0] == "ak.wwise.core.switchContainer.removeAssignment"

    ask_ctx = build_executor_context(_FakeOwner("Ask Mode"))
    denied = ask_ctx["call_structured_tool"]("waapi.soundbank_generate", {"soundbanks": [{"name": "MainBank"}]})
    assert "Ask Mode" in denied["error"]
    print("test_structured_soundbank_and_container_tools_execute_documented_calls: OK")


if __name__ == "__main__":
    test_registry_manifest_contains_planner_metadata()
    test_parse_and_verify_valid_plan()
    test_verifier_rejects_bad_plan_inputs()
    test_plan_executor_runs_steps_in_order()
    test_ask_mode_default_denies_write_tools()
    test_read_only_waapi_client_default_deny_policy()
    test_executor_context_exposes_structured_tool_call()
    test_structured_waapi_tools_execute_common_calls()
    test_documented_call_tools_are_policy_gated_without_vendored_docs()
    test_structured_interactive_music_tools_execute_documented_calls()
    test_structured_version_tools_choose_2025_and_legacy_roots()
    test_structured_bus_tools_handle_2025_bus_changes()
    test_structured_runtime_soundengine_tools_execute_documented_calls()
    test_structured_soundbank_and_container_tools_execute_documented_calls()

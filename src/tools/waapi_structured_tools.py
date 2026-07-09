"""Structured WAAPI tools for common high-frequency operations."""

from __future__ import annotations

import json

from src.tools.base import Tool, ToolContext, ToolResult, ToolResultStatus, ValidationResult


def _json_result(result) -> ToolResult:
    status = ToolResultStatus.ERROR if isinstance(result, dict) and result.get("error") else ToolResultStatus.SUCCESS
    return ToolResult(
        output=json.dumps(result, ensure_ascii=False, indent=2),
        status=status,
        data=result,
    )


def _waapi_missing_result() -> ToolResult:
    return ToolResult("Error: waapi_client not available", ToolResultStatus.ERROR)


def _prefixed_fields(values: dict | None) -> dict:
    if not isinstance(values, dict):
        return {}
    return {key if str(key).startswith("@") else f"@{key}": value for key, value in values.items()}


def _optional_create_fields(input: dict) -> dict:  # noqa: A002
    args = {}
    for key in ("onNameConflict", "platform", "autoAddToSourceControl", "notes"):
        if key in input:
            args[key] = input.get(key)
    args.update(_prefixed_fields(input.get("properties")))
    args.update(_prefixed_fields(input.get("references")))
    return args


def _copy_present(input: dict, keys: tuple[str, ...]) -> dict:  # noqa: A002
    return {key: input.get(key) for key in keys if key in input and input.get(key) is not None}


def _require_non_empty(input: dict, keys: tuple[str, ...]) -> ValidationResult:  # noqa: A002
    for key in keys:
        value = input.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            return ValidationResult(valid=False, error=f"{key} is required")
    return ValidationResult()


def _client_version_info(context: ToolContext) -> dict:
    client = context.waapi_client
    if client is None or not hasattr(client, "get_wwise_version"):
        return {}
    try:
        info = client.get_wwise_version()
    except Exception:
        return {}
    return info if isinstance(info, dict) else {}


def _is_2025_or_later(context: ToolContext) -> bool:
    info = _client_version_info(context)
    if "is_2025_or_later" in info:
        return bool(info.get("is_2025_or_later"))
    return int(info.get("year") or 0) >= 2025


def _hierarchy_root_candidates(context: ToolContext, kind: str) -> tuple[str, list[str]]:
    normalized = str(kind or "").strip().lower()
    is_2025 = _is_2025_or_later(context)
    if normalized in {"container", "containers", "actor", "actor_mixer", "actor-mixer"}:
        candidates = ["\\Containers", "\\Actor-Mixer Hierarchy"] if is_2025 else ["\\Actor-Mixer Hierarchy", "\\Containers"]
    elif normalized in {"music", "interactive_music", "interactive-music"}:
        candidates = ["\\Containers", "\\Interactive Music Hierarchy"] if is_2025 else ["\\Interactive Music Hierarchy", "\\Containers"]
    elif normalized in {"bus", "busses", "master_mixer", "master-mixer"}:
        candidates = ["\\Busses", "\\Master-Mixer Hierarchy"] if is_2025 else ["\\Master-Mixer Hierarchy", "\\Busses"]
    elif normalized in {"attenuation", "attenuations"}:
        candidates = ["\\Attenuations"]
    elif normalized in {"event", "events"}:
        candidates = ["\\Events"]
    elif normalized in {"soundbank", "soundbanks"}:
        candidates = ["\\SoundBanks"]
    elif normalized in {"state", "states"}:
        candidates = ["\\States"]
    elif normalized in {"switch", "switches"}:
        candidates = ["\\Switches"]
    elif normalized in {"game_parameter", "game-parameter", "gameparameters", "game_parameters"}:
        candidates = ["\\Game Parameters"]
    else:
        candidates = ["\\Containers", "\\Actor-Mixer Hierarchy", "\\Interactive Music Hierarchy"] if is_2025 else ["\\Actor-Mixer Hierarchy", "\\Interactive Music Hierarchy", "\\Containers"]
    return candidates[0], candidates


def _music_hierarchy_default_path(context: ToolContext) -> str:
    preferred, _candidates = _hierarchy_root_candidates(context, "music")
    return preferred


def _waapi_uri_available(context: ToolContext, uri: str) -> bool | None:
    client = context.waapi_client
    if client is None or not hasattr(client, "get_functions"):
        return None
    try:
        functions = client.get_functions()
    except Exception:
        return None
    if not isinstance(functions, list) or not functions:
        return None
    return str(uri or "").strip() in set(str(item) for item in functions)


def _objects_from_result(result) -> list[dict]:
    if not isinstance(result, dict):
        return []
    values = result.get("return") or result.get("objects") or []
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _bus_return_fields() -> list[str]:
    return [
        "id",
        "name",
        "type",
        "path",
        "parent",
        "parent.name",
        "shortId",
        "BusVolume",
        "Volume",
        "OutputBusVolume",
        "BusChannelConfig",
        "AudioDevice",
        "UserAuxSend0",
        "UserAuxSend1",
        "UserAuxSend2",
        "UserAuxSend3",
        "ReflectionsAuxSend",
    ]


def _resolve_bus_candidates(context: ToolContext, name: str | None = None, include_aux: bool = True) -> tuple[dict, list[dict]]:
    if context.waapi_client is None:
        return {}, []
    object_types = ["Bus", "AuxBus"] if include_aux else ["Bus"]
    result = context.waapi_client.call(
        "ak.wwise.core.object.get",
        {"from": {"ofType": object_types}},
        {"return": _bus_return_fields()},
    )
    objects = _objects_from_result(result)
    wanted = str(name or "").strip().lower()
    if wanted:
        matches = [item for item in objects if str(item.get("name") or "").strip().lower() == wanted]
    else:
        preferred_names = ("main audio bus", "master audio bus") if _is_2025_or_later(context) else ("master audio bus", "main audio bus")
        matches = [item for preferred in preferred_names for item in objects if str(item.get("name") or "").strip().lower() == preferred]
        if not matches:
            matches = [item for item in objects if str(item.get("type") or "").lower() == "bus"]
    return (matches[0] if matches else {}), matches


def _is_plausible_waapi_uri(uri: str) -> bool:
    parts = str(uri or "").strip().split(".")
    return (
        len(parts) >= 3
        and parts[0] == "ak"
        and all(part and part.replace("_", "").isalnum() for part in parts)
    )


def _is_dangerous_documented_uri(uri: str) -> bool:
    uri_lower = str(uri or "").strip().lower()
    dangerous_exact = {
        "ak.wwise.debug.testcrash",
        "ak.wwise.debug.testassert",
        "ak.wwise.debug.restartwaapiservers",
        "ak.wwise.debug.enableautomationmode",
        "ak.wwise.debug.enableasserts",
        "ak.wwise.core.executeluascript",
        "ak.wwise.ui.cli.executeluascript",
        "ak.wwise.ui.cli.launch",
        "ak.wwise.ui.project.open",
        "ak.wwise.ui.project.create",
        "ak.wwise.ui.project.close",
        "ak.wwise.console.project.open",
        "ak.wwise.console.project.create",
        "ak.wwise.console.project.close",
    }
    dangerous_prefixes = (
        "ak.wwise.debug.",
        "ak.wwise.core.sourcecontrol.",
    )
    return uri_lower in dangerous_exact or any(uri_lower.startswith(prefix) for prefix in dangerous_prefixes)


def _is_documented_read_uri(uri: str) -> bool:
    uri_lower = str(uri or "").strip().lower()
    if _is_dangerous_documented_uri(uri_lower):
        return False
    tail = uri_lower.rsplit(".", 1)[-1]
    read_verbs = (
        "get",
        "is",
        "ping",
        "diff",
        "getinfo",
        "getprojectinfo",
        "getschema",
        "getfunctions",
        "gettopics",
    )
    if tail.startswith(read_verbs):
        return True
    if any(part.startswith(read_verbs) for part in uri_lower.split(".")):
        return True
    safe_exact = {
        "ak.wwise.ui.bringtoforeground",
        "ak.soundengine.getstate",
        "ak.soundengine.getswitch",
    }
    return uri_lower in safe_exact


def _validate_documented_call_input(input: dict) -> ValidationResult:  # noqa: A002
    uri = str(input.get("uri") or "").strip()
    if not uri:
        return ValidationResult(valid=False, error="uri is required")
    if not _is_plausible_waapi_uri(uri):
        return ValidationResult(valid=False, error=f"uri is not a valid WAAPI URI shape: {uri}")
    if "args" in input and input.get("args") is not None and not isinstance(input.get("args"), dict):
        return ValidationResult(valid=False, error="args must be an object when provided")
    if "options" in input and input.get("options") is not None and not isinstance(input.get("options"), dict):
        return ValidationResult(valid=False, error="options must be an object when provided")
    return ValidationResult()


def _execute_documented_call(input: dict, context: ToolContext) -> ToolResult:  # noqa: A002
    if context.waapi_client is None:
        return _waapi_missing_result()
    uri = str(input.get("uri") or "").strip()
    available = _waapi_uri_available(context, uri)
    if available is False:
        payload = {"error": f"uri is not available in the connected Wwise version: {uri}"}
        return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), ToolResultStatus.ERROR, data=payload)
    return _json_result(context.waapi_client.call(
        uri,
        input.get("args") if isinstance(input.get("args"), dict) else {},
        input.get("options") if isinstance(input.get("options"), dict) else None,
    ))


class WaapiCallDocumentedReadTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.call_documented_read"

    @property
    def description(self) -> str:
        return "Call a read-only WAAPI URI when no dedicated structured tool exists."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": "Must be a read-only WAAPI URI available in the connected Wwise version."},
                "args": {"type": "object"},
                "options": {"type": "object"},
            },
            "required": ["uri"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        result = _validate_documented_call_input(input)
        if not result.valid:
            return result
        uri = str(input.get("uri") or "").strip()
        if not _is_documented_read_uri(uri):
            return ValidationResult(valid=False, error=f"uri is not classified as read-only; use a dedicated tool or Agent-only documented write tool: {uri}")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        return _execute_documented_call(input, context)


class WaapiCallDocumentedWriteTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.call_documented_write"

    @property
    def description(self) -> str:
        return "Agent-only escape hatch for WAAPI write/procedure URIs when no dedicated structured tool exists."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": "Must be a WAAPI URI available in the connected Wwise version and not blocked as dangerous."},
                "args": {"type": "object"},
                "options": {"type": "object"},
                "reason": {"type": "string", "description": "Why no dedicated tool covers this call."},
            },
            "required": ["uri", "reason"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project", "wwise-runtime", "wwise-ui"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        result = _validate_documented_call_input(input)
        if not result.valid:
            return result
        uri = str(input.get("uri") or "").strip()
        if _is_dangerous_documented_uri(uri):
            return ValidationResult(valid=False, error=f"uri is blocked by AudioMate policy: {uri}")
        if not str(input.get("reason") or "").strip():
            return ValidationResult(valid=False, error="reason is required")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        return _execute_documented_call(input, context)


class WaapiGetVersionContextTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.get_version_context"

    @property
    def description(self) -> str:
        return "Read the connected Wwise version and AudioMate compatibility flags."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        info = _client_version_info(context)
        if not info:
            payload = {"error": "Unable to read Wwise version from ak.wwise.core.getInfo"}
            return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), ToolResultStatus.ERROR, data=payload)
        payload = {
            "ok": True,
            "version": info,
            "is_2025_or_later": _is_2025_or_later(context),
            "hierarchy": {
                "containers": _hierarchy_root_candidates(context, "containers")[1],
                "music": _hierarchy_root_candidates(context, "music")[1],
                "actor": _hierarchy_root_candidates(context, "actor")[1],
                "busses": _hierarchy_root_candidates(context, "busses")[1],
            },
        }
        return _json_result(payload)


class WaapiResolveHierarchyRootTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.resolve_hierarchy_root"

    @property
    def description(self) -> str:
        return "Resolve version-aware Wwise hierarchy root candidates such as Containers, Music, Actor-Mixer, Events, SoundBanks, or Attenuations."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"kind": {"type": "string", "description": "containers, music, actor, busses, events, soundbanks, attenuations, states, switches, or game_parameters."}},
            "required": ["kind"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        return _require_non_empty(input, ("kind",))

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        preferred, candidates = _hierarchy_root_candidates(context, str(input.get("kind") or ""))
        payload = {
            "ok": True,
            "kind": input.get("kind"),
            "preferred": preferred,
            "candidates": candidates,
            "is_2025_or_later": _is_2025_or_later(context),
            "version": _client_version_info(context),
        }
        return _json_result(payload)


class WaapiGetBussesTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.get_busses"

    @property
    def description(self) -> str:
        return "List Bus and AuxBus authoring objects without assuming Main Audio Bus or Master Audio Bus paths."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "include_aux": {"type": "boolean", "description": "Include AuxBus objects. Default true."},
                "name_contains": {"type": "string", "description": "Optional case-insensitive name filter."},
            },
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        include_aux = input.get("include_aux") is not False
        object_types = ["Bus", "AuxBus"] if include_aux else ["Bus"]
        result = context.waapi_client.call(
            "ak.wwise.core.object.get",
            {"from": {"ofType": object_types}},
            {"return": _bus_return_fields()},
        )
        objects = _objects_from_result(result)
        name_contains = str(input.get("name_contains") or "").strip().lower()
        if name_contains:
            objects = [item for item in objects if name_contains in str(item.get("name") or "").lower()]
        preferred, candidates = _hierarchy_root_candidates(context, "busses")
        payload = {
            "ok": not (isinstance(result, dict) and result.get("error")),
            "preferred_root": preferred,
            "root_candidates": candidates,
            "count": len(objects),
            "busses": objects,
            "raw": result if isinstance(result, dict) and result.get("error") else None,
        }
        return _json_result(payload)


class WaapiResolveMainBusTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.resolve_main_bus"

    @property
    def description(self) -> str:
        return "Resolve the actual project main Bus, preferring Main Audio Bus on Wwise 2025+ and Master Audio Bus on legacy projects."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Optional exact Bus name to resolve."}},
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        resolved, matches = _resolve_bus_candidates(context, input.get("name"), include_aux=False)
        if not resolved:
            payload = {"error": "No Bus object matched. Use waapi.get_busses to inspect actual project busses."}
            return ToolResult(json.dumps(payload, ensure_ascii=False, indent=2), ToolResultStatus.ERROR, data=payload)
        payload = {
            "ok": True,
            "bus": resolved,
            "matches": matches,
            "is_2025_or_later": _is_2025_or_later(context),
            "note": "Use the returned id/path; do not hard-code Main Audio Bus or Master Audio Bus names.",
        }
        return _json_result(payload)


class WaapiCreateBusTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.create_bus"

    @property
    def description(self) -> str:
        return "Create a Bus or AuxBus under a verified Bus/WorkUnit parent. Bus routing is defined by parent; OutputBus is not allowed on Bus/AuxBus."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "parent": {"type": "string", "description": "Verified Bus or WorkUnit GUID/path/name. Prefer GUID from waapi.get_busses or waapi.resolve_main_bus."},
                "type": {"type": "string", "description": "Bus or AuxBus."},
                "name": {"type": "string"},
                "onNameConflict": {"type": "string"},
                "properties": {"type": "object", "description": "Optional Bus scalar properties such as BusVolume."},
                "references": {"type": "object", "description": "Optional references, but OutputBus is forbidden for Bus/AuxBus."},
            },
            "required": ["parent", "type", "name"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        required = _require_non_empty(input, ("parent", "type", "name"))
        if not required.valid:
            return required
        if input.get("type") not in {"Bus", "AuxBus"}:
            return ValidationResult(valid=False, error="type must be Bus or AuxBus")
        references = input.get("references") if isinstance(input.get("references"), dict) else {}
        if any(str(key).lstrip("@").lower() == "outputbus" for key in references):
            return ValidationResult(valid=False, error="Bus/AuxBus routing is defined by parent; do not set OutputBus on Bus/AuxBus")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {"parent": input.get("parent"), "type": input.get("type"), "name": input.get("name")}
        args.update(_optional_create_fields(input))
        return _json_result(context.waapi_client.call(
            "ak.wwise.core.object.create",
            args,
            {"return": ["id", "name", "type", "path", "parent.name"]},
        ))


class WaapiSetBusPropertyTool(Tool):
    _COMMON_BUS_PROPERTIES = {
        "BusVolume", "Volume", "OutputBusVolume", "OutputBusLowpass", "OutputBusHighpass", "OutputBusDualshelf",
        "Lowpass", "Highpass", "Pitch", "MakeUpGain", "BusChannelConfig", "UseGameAuxSends",
        "GameAuxSendVolume", "UserAuxSendVolume0", "UserAuxSendVolume1", "UserAuxSendVolume2", "UserAuxSendVolume3",
        "UserAuxSendLPF0", "UserAuxSendLPF1", "UserAuxSendLPF2", "UserAuxSendLPF3",
        "UserAuxSendHPF0", "UserAuxSendHPF1", "UserAuxSendHPF2", "UserAuxSendHPF3",
        "ReflectionsVolume", "HdrEnable", "HdrThreshold", "HdrRatio", "HdrReleaseTime", "MaxDuckVolume", "RecoveryTime",
    }

    @property
    def name(self) -> str:
        return "waapi.set_bus_property"

    @property
    def description(self) -> str:
        return "Set a known Bus/AuxBus scalar property such as BusVolume, Volume, OutputBusVolume, or UserAuxSendVolume0."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "bus_id": {"type": "string"},
                "property_name": {"type": "string"},
                "value": {"description": "New property value."},
            },
            "required": ["bus_id", "property_name", "value"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        required = _require_non_empty(input, ("bus_id", "property_name", "value"))
        if not required.valid:
            return required
        property_name = str(input.get("property_name") or "").lstrip("@")
        if property_name == "OutputBus":
            return ValidationResult(valid=False, error="OutputBus is not a Bus scalar property; Bus/AuxBus routing is defined by parent")
        if property_name not in self._COMMON_BUS_PROPERTIES:
            return ValidationResult(valid=False, error="Unknown Bus property. Use waapi.get_property_reference_names on the Bus first, then choose a documented scalar property.")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call(
            "ak.wwise.core.object.setProperty",
            {"object": input.get("bus_id"), "property": str(input.get("property_name") or "").lstrip("@"), "value": input.get("value")},
        ))


class WaapiSetObjectOutputBusTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.set_object_output_bus"

    @property
    def description(self) -> str:
        return "Route Sound/Actor-Mixer objects to a verified Bus using OverrideOutput and OutputBus. Do not use for Bus/AuxBus objects."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "object_ids": {"type": "array", "description": "Sound or Actor-Mixer object ids to route."},
                "bus_id": {"type": "string", "description": "Verified target Bus id/path/name."},
                "override_output": {"type": "boolean", "description": "Set OverrideOutput. Default true."},
            },
            "required": ["object_ids", "bus_id"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        if not isinstance(input.get("object_ids"), list) or not input.get("object_ids"):
            return ValidationResult(valid=False, error="object_ids must be a non-empty array")
        if not str(input.get("bus_id") or "").strip():
            return ValidationResult(valid=False, error="bus_id is required")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        override_output = input.get("override_output") is not False
        objects = [
            {"object": object_id, "@OverrideOutput": override_output, "@OutputBus": input.get("bus_id")}
            for object_id in input.get("object_ids") or []
        ]
        return _json_result(context.waapi_client.call("ak.wwise.core.object.set", {"objects": objects}))


class WaapiProjectSaveTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.project_save"

    @property
    def description(self) -> str:
        return "Save the current Wwise project with ak.wwise.core.project.save."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"autoCheckOutToSourceControl": {"type": "boolean"}},
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project", "disk"]

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call("ak.wwise.core.project.save", _copy_present(input, ("autoCheckOutToSourceControl",))))


class WaapiSoundEngineGetStateTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.soundengine_get_state"

    @property
    def description(self) -> str:
        return "Read the current runtime State for a State Group."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"stateGroup": {}}, "required": ["stateGroup"]}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        return _require_non_empty(input, ("stateGroup",))

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call("ak.soundengine.getState", {"stateGroup": input.get("stateGroup")}))


class WaapiSoundEngineGetSwitchTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.soundengine_get_switch"

    @property
    def description(self) -> str:
        return "Read the current runtime Switch for a Switch Group and game object."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"switchGroup": {}, "gameObject": {"type": "integer"}}, "required": ["switchGroup"]}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        return _require_non_empty(input, ("switchGroup",))

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {"switchGroup": input.get("switchGroup")}
        args.update(_copy_present(input, ("gameObject",)))
        return _json_result(context.waapi_client.call("ak.soundengine.getSwitch", args))


class WaapiSoundEnginePostEventTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.soundengine_post_event"

    @property
    def description(self) -> str:
        return "Post a runtime Event to the Sound Engine and return the playing ID."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"event": {}, "gameObject": {"type": "integer"}}, "required": ["event"]}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-runtime"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        return _require_non_empty(input, ("event",))

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {"event": input.get("event")}
        args.update(_copy_present(input, ("gameObject",)))
        return _json_result(context.waapi_client.call("ak.soundengine.postEvent", args))


class WaapiSoundEngineSetRtpcTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.soundengine_set_rtpc"

    @property
    def description(self) -> str:
        return "Set a runtime Game Parameter/RTPC value."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"rtpc": {}, "value": {"type": "number"}, "gameObject": {"type": "integer"}}, "required": ["rtpc", "value"]}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-runtime"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        required = _require_non_empty(input, ("rtpc", "value"))
        if not required.valid:
            return required
        if not isinstance(input.get("value"), (int, float)):
            return ValidationResult(valid=False, error="value must be a number")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {"rtpc": input.get("rtpc"), "value": input.get("value")}
        args.update(_copy_present(input, ("gameObject",)))
        return _json_result(context.waapi_client.call("ak.soundengine.setRTPCValue", args))


class WaapiSoundEngineSetStateTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.soundengine_set_state"

    @property
    def description(self) -> str:
        return "Set a runtime State Group to a State."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"stateGroup": {}, "state": {}}, "required": ["stateGroup", "state"]}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-runtime"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        return _require_non_empty(input, ("stateGroup", "state"))

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call("ak.soundengine.setState", {"stateGroup": input.get("stateGroup"), "state": input.get("state")}))


class WaapiSoundEngineSetSwitchTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.soundengine_set_switch"

    @property
    def description(self) -> str:
        return "Set a runtime Switch Group to a Switch State."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"switchGroup": {}, "switchState": {}, "gameObject": {"type": "integer"}}, "required": ["switchGroup", "switchState"]}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-runtime"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        return _require_non_empty(input, ("switchGroup", "switchState"))

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {"switchGroup": input.get("switchGroup"), "switchState": input.get("switchState")}
        args.update(_copy_present(input, ("gameObject",)))
        return _json_result(context.waapi_client.call("ak.soundengine.setSwitch", args))


class WaapiSoundEngineStopAllTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.soundengine_stop_all"

    @property
    def description(self) -> str:
        return "Stop runtime playback for a game object, or all sounds when gameObject is omitted."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"gameObject": {"type": "integer"}}}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-runtime"]

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call("ak.soundengine.stopAll", _copy_present(input, ("gameObject",))))


class WaapiSoundBankGetInclusionsTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.soundbank_get_inclusions"

    @property
    def description(self) -> str:
        return "Read a SoundBank inclusion list."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"soundbank": {"type": "string"}}, "required": ["soundbank"]}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        return _require_non_empty(input, ("soundbank",))

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call("ak.wwise.core.soundbank.getInclusions", {"soundbank": input.get("soundbank")}))


class WaapiSoundBankSetInclusionsTool(Tool):
    _ALLOWED_OPERATIONS = {"add", "remove", "replace"}

    @property
    def name(self) -> str:
        return "waapi.soundbank_set_inclusions"

    @property
    def description(self) -> str:
        return "Modify a SoundBank inclusion list using add, remove, or replace."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "soundbank": {"type": "string"},
                "operation": {"type": "string", "description": "add, remove, or replace"},
                "inclusions": {"type": "array", "description": "Array of {object, filter}."},
            },
            "required": ["soundbank", "operation", "inclusions"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        required = _require_non_empty(input, ("soundbank", "operation"))
        if not required.valid:
            return required
        if input.get("operation") not in self._ALLOWED_OPERATIONS:
            return ValidationResult(valid=False, error="operation must be add, remove, or replace")
        if not isinstance(input.get("inclusions"), list):
            return ValidationResult(valid=False, error="inclusions must be an array")
        for index, item in enumerate(input.get("inclusions") or []):
            if not isinstance(item, dict):
                return ValidationResult(valid=False, error=f"inclusions[{index}] must be an object")
            if "object" not in item or "filter" not in item:
                return ValidationResult(valid=False, error=f"inclusions[{index}] must contain object and filter")
            if not isinstance(item.get("filter"), list):
                return ValidationResult(valid=False, error=f"inclusions[{index}].filter must be an array")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call("ak.wwise.core.soundbank.setInclusions", {
            "soundbank": input.get("soundbank"),
            "operation": input.get("operation"),
            "inclusions": input.get("inclusions") or [],
        }))


class WaapiSoundBankGenerateTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.soundbank_generate"

    @property
    def description(self) -> str:
        return "Generate SoundBanks with the documented ak.wwise.core.soundbank.generate payload."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "soundbanks": {"type": "array"},
                "platforms": {"type": "array"},
                "languages": {"type": "array"},
                "skipLanguages": {"type": "boolean"},
                "rebuildSoundBanks": {"type": "boolean"},
                "clearAudioFileCache": {"type": "boolean"},
                "writeToDisk": {"type": "boolean"},
                "rebuildInitBank": {"type": "boolean"},
            },
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project", "disk"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        for key in ("soundbanks", "platforms", "languages"):
            if key in input and input.get(key) is not None and not isinstance(input.get(key), list):
                return ValidationResult(valid=False, error=f"{key} must be an array")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = _copy_present(input, (
            "soundbanks",
            "platforms",
            "languages",
            "skipLanguages",
            "rebuildSoundBanks",
            "clearAudioFileCache",
            "writeToDisk",
            "rebuildInitBank",
        ))
        return _json_result(context.waapi_client.call("ak.wwise.core.soundbank.generate", args))


class WaapiBlendContainerGetAssignmentsTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.blendcontainer_get_assignments"

    @property
    def description(self) -> str:
        return "Read Blend Track assignments for a Blend Track GUID."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"object": {"type": "string"}}, "required": ["object"]}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        return _require_non_empty(input, ("object",))

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call("ak.wwise.core.blendContainer.getAssignments", {"object": input.get("object")}))


class WaapiBlendContainerAddTrackTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.blendcontainer_add_track"

    @property
    def description(self) -> str:
        return "Add a Blend Track to a Blend Container."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"object": {"type": "string"}, "name": {"type": "string"}, "id": {"type": "string"}}, "required": ["object", "name"]}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        return _require_non_empty(input, ("object", "name"))

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {"object": input.get("object"), "name": input.get("name")}
        args.update(_copy_present(input, ("id",)))
        return _json_result(context.waapi_client.call("ak.wwise.core.blendContainer.addTrack", args))


class WaapiBlendContainerSetAssignmentTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.blendcontainer_set_assignment"

    @property
    def description(self) -> str:
        return "Add or remove a child assignment on a Blend Track."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "description": "add or remove"},
                "object": {"type": "string", "description": "Blend Track GUID."},
                "child": {"type": "string"},
                "index": {"type": "integer"},
                "edges": {"type": "array"},
            },
            "required": ["operation", "object", "child"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        required = _require_non_empty(input, ("operation", "object", "child"))
        if not required.valid:
            return required
        if input.get("operation") not in {"add", "remove"}:
            return ValidationResult(valid=False, error="operation must be add or remove")
        if "edges" in input and input.get("edges") is not None and not isinstance(input.get("edges"), list):
            return ValidationResult(valid=False, error="edges must be an array")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {"object": input.get("object"), "child": input.get("child")}
        if input.get("operation") == "add":
            args.update(_copy_present(input, ("index", "edges")))
            return _json_result(context.waapi_client.call("ak.wwise.core.blendContainer.addAssignment", args))
        return _json_result(context.waapi_client.call("ak.wwise.core.blendContainer.removeAssignment", args))


class WaapiSwitchContainerGetAssignmentsTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.switchcontainer_get_assignments"

    @property
    def description(self) -> str:
        return "Read Switch Container child-to-State assignments."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        return _require_non_empty(input, ("id",))

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call("ak.wwise.core.switchContainer.getAssignments", {"id": input.get("id")}))


class WaapiSwitchContainerSetAssignmentTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.switchcontainer_set_assignment"

    @property
    def description(self) -> str:
        return "Add or remove a Switch Container child-to-State/Switch assignment."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "description": "add or remove"},
                "child": {"type": "string"},
                "stateOrSwitch": {"type": "string"},
            },
            "required": ["operation", "child", "stateOrSwitch"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        required = _require_non_empty(input, ("operation", "child", "stateOrSwitch"))
        if not required.valid:
            return required
        if input.get("operation") not in {"add", "remove"}:
            return ValidationResult(valid=False, error="operation must be add or remove")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {"child": input.get("child"), "stateOrSwitch": input.get("stateOrSwitch")}
        uri = "ak.wwise.core.switchContainer.addAssignment" if input.get("operation") == "add" else "ak.wwise.core.switchContainer.removeAssignment"
        return _json_result(context.waapi_client.call(uri, args))


class WaapiGetSelectedObjectsTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.get_selected_objects"

    @property
    def description(self) -> str:
        return "Get currently selected Wwise objects with stable fields."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.get_selected_objects())


class WaapiGetObjectsTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.get_objects"

    @property
    def description(self) -> str:
        return "Run a structured ak.wwise.core.object.get query."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "from": {"type": "object", "description": "WAAPI object.get args.from."},
                "transform": {"type": "array", "description": "Optional object.get transform list."},
                "return": {"type": "array", "description": "Return fields for options.return."},
            },
            "required": ["from"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        if not isinstance(input.get("from"), dict):
            return ValidationResult(valid=False, error="from must be an object")
        if "return" in input and not isinstance(input.get("return"), list):
            return ValidationResult(valid=False, error="return must be an array")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {"from": input.get("from")}
        if isinstance(input.get("transform"), list):
            args["transform"] = input["transform"]
        options = {"return": input.get("return") or ["id", "name", "type", "path"]}
        return _json_result(context.waapi_client.call("ak.wwise.core.object.get", args, options))


class WaapiGetPropertyTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.get_property"

    @property
    def description(self) -> str:
        return "Get one property value from a Wwise object by object id."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "object_id": {"type": "string"},
                "property_name": {"type": "string"},
            },
            "required": ["object_id", "property_name"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        return _require_non_empty(input, ("object_id", "property_name"))

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        value = context.waapi_client.get_property(input.get("object_id"), input.get("property_name"))
        return _json_result({"object_id": input.get("object_id"), "property_name": input.get("property_name"), "value": value})


class WaapiSetPropertyTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.set_property"

    @property
    def description(self) -> str:
        return "Set one property value on a Wwise object by object id."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "object_id": {"type": "string"},
                "property_name": {"type": "string"},
                "value": {"description": "New property value."},
            },
            "required": ["object_id", "property_name", "value"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        required = _require_non_empty(input, ("object_id", "property_name"))
        if not required.valid:
            return required
        if "value" not in input:
            return ValidationResult(valid=False, error="value is required")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        ok = context.waapi_client.set_property(input.get("object_id"), input.get("property_name"), input.get("value"))
        result = {
            "ok": bool(ok),
            "object_id": input.get("object_id"),
            "property_name": input.get("property_name"),
            "value": input.get("value"),
        }
        return ToolResult(
            output=json.dumps(result, ensure_ascii=False, indent=2),
            status=ToolResultStatus.SUCCESS if ok else ToolResultStatus.ERROR,
            data=result,
        )


class WaapiBatchSetPropertyTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.batch_set_property"

    @property
    def description(self) -> str:
        return "Set one property on multiple Wwise objects, or multiple property operations in one structured call."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "description": "Array of {object_id, property_name, value} operations.",
                }
            },
            "required": ["operations"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        operations = input.get("operations")
        if not isinstance(operations, list) or not operations:
            return ValidationResult(valid=False, error="operations must be a non-empty array")
        for index, item in enumerate(operations):
            if not isinstance(item, dict):
                return ValidationResult(valid=False, error=f"operations[{index}] must be an object")
            for key in ("object_id", "property_name", "value"):
                if key not in item:
                    return ValidationResult(valid=False, error=f"operations[{index}].{key} is required")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        results = []
        ok_count = 0
        for item in input.get("operations") or []:
            ok = context.waapi_client.set_property(item.get("object_id"), item.get("property_name"), item.get("value"))
            if ok:
                ok_count += 1
            results.append({
                "ok": bool(ok),
                "object_id": item.get("object_id"),
                "property_name": item.get("property_name"),
                "value": item.get("value"),
            })
        payload = {"ok": ok_count == len(results), "updated_count": ok_count, "results": results}
        return ToolResult(
            output=json.dumps(payload, ensure_ascii=False, indent=2),
            status=ToolResultStatus.SUCCESS if payload["ok"] else ToolResultStatus.ERROR,
            data=payload,
        )


class WaapiGetSchemaTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.get_schema"

    @property
    def description(self) -> str:
        return "Read the WAAPI schema for a procedure or topic URI."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "uri": {"type": "string"},
                "include_examples": {
                    "type": "boolean",
                    "description": "Ask WAAPI to include schema examples when available.",
                    "default": False,
                },
            },
            "required": ["uri"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        try:
            schema = context.waapi_client.get_schema(
                input.get("uri"),
                include_examples=bool(input.get("include_examples")),
            )
        except TypeError:
            schema = context.waapi_client.get_schema(input.get("uri"))
        return _json_result(schema)


class WaapiGetPropertyAndReferenceNamesTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.get_property_reference_names"

    @property
    def description(self) -> str:
        return "List documented property and reference names for a Wwise object."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"object": {"type": "string", "description": "Wwise object id, path, or name accepted by WAAPI."}},
            "required": ["object"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call(
            "ak.wwise.core.object.getPropertyAndReferenceNames",
            {"object": input.get("object")},
        ))


class WaapiSetReferenceTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.set_reference"

    @property
    def description(self) -> str:
        return "Set an object reference such as Output Bus or Attenuation using ak.wwise.core.object.setReference."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "object_id": {"type": "string"},
                "reference_name": {"type": "string"},
                "target_id": {"type": "string"},
            },
            "required": ["object_id", "reference_name", "target_id"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        result = context.waapi_client.call(
            "ak.wwise.core.object.setReference",
            {
                "object": input.get("object_id"),
                "reference": input.get("reference_name"),
                "value": input.get("target_id"),
            },
        )
        return _json_result(result)


class WaapiGetAttenuationCurveTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.get_attenuation_curve"

    @property
    def description(self) -> str:
        return "Read an attenuation curve with ak.wwise.core.object.getAttenuationCurve."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "object_id": {"type": "string"},
                "curve_type": {"type": "string"},
                "platform": {"type": "string"},
            },
            "required": ["object_id", "curve_type"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {"object": input.get("object_id"), "curveType": input.get("curve_type")}
        if input.get("platform"):
            args["platform"] = input.get("platform")
        return _json_result(context.waapi_client.call("ak.wwise.core.object.getAttenuationCurve", args))


class WaapiSetAttenuationCurveTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.set_attenuation_curve"

    @property
    def description(self) -> str:
        return "Set an attenuation curve with documented top-level args."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "object_id": {"type": "string"},
                "curve_type": {"type": "string"},
                "use": {"type": "string"},
                "points": {"type": "array"},
                "platform": {"type": "string"},
            },
            "required": ["object_id", "curve_type", "use", "points"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        points = input.get("points")
        if not isinstance(points, list) or not points:
            return ValidationResult(valid=False, error="points must be a non-empty array")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {
            "object": input.get("object_id"),
            "curveType": input.get("curve_type"),
            "use": input.get("use"),
            "points": input.get("points"),
        }
        if input.get("platform"):
            args["platform"] = input.get("platform")
        return _json_result(context.waapi_client.call("ak.wwise.core.object.setAttenuationCurve", args))


class WaapiFindInProjectExplorerTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.find_in_project_explorer"

    @property
    def description(self) -> str:
        return "Highlight one or more Wwise objects in the Project Explorer UI."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"object_ids": {"type": "array", "description": "Object ids to highlight."}},
            "required": ["object_ids"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-ui"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        object_ids = input.get("object_ids")
        if not isinstance(object_ids, list) or not object_ids:
            return ValidationResult(valid=False, error="object_ids must be a non-empty array")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call(
            "ak.wwise.ui.commands.execute",
            {"command": "FindInProjectExplorerSelectionChannel1", "objects": input.get("object_ids") or []},
        ))


class WaapiGetMusicStructureTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.get_music_structure"

    @property
    def description(self) -> str:
        return "Read Interactive Music hierarchy objects with music-specific return fields."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "object_id": {"type": "string", "description": "Optional root object id to inspect."},
                "path": {"type": "string", "description": "Optional root path; defaults to \\Interactive Music Hierarchy."},
                "include_descendants": {"type": "boolean"},
                "limit": {"type": "integer", "description": "Maximum number of returned objects, default 200."},
            },
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        limit = input.get("limit") if isinstance(input.get("limit"), int) else 200
        if input.get("object_id"):
            source = {"id": [input.get("object_id")]}
        else:
            source = {"path": [input.get("path") or _music_hierarchy_default_path(context)]}
        args = {"from": source, "transform": [{"select": ["descendants"]}, {"range": [0, max(1, limit)]}]}
        if input.get("include_descendants") is False:
            args = {"from": source, "transform": [{"range": [0, max(1, limit)]}]}
        options = {
            "return": [
                "id",
                "name",
                "type",
                "path",
                "parent",
                "childrenCount",
                "duration",
                "music:playlistRoot",
                "music:transitionRoot",
                "musicTransitionObject",
                "stateGroups",
                "stateProperties",
                "switchGroupGameParameter",
                "switchContainerChild:context",
            ]
        }
        return _json_result(context.waapi_client.call("ak.wwise.core.object.get", args, options))


class WaapiCreateMusicObjectTool(Tool):
    _ALLOWED_TYPES = {
        "Folder",
        "WorkUnit",
        "MusicPlaylistContainer",
        "MusicSwitchContainer",
        "MusicSegment",
        "MusicTrack",
    }

    @property
    def name(self) -> str:
        return "waapi.create_music_object"

    @property
    def description(self) -> str:
        return "Create a documented Interactive Music object with ak.wwise.core.object.create."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "parent": {"type": "string", "description": "Parent GUID/path/name. Prefer a verified GUID."},
                "type": {"type": "string", "description": "Folder, WorkUnit, MusicPlaylistContainer, MusicSwitchContainer, MusicSegment, or MusicTrack."},
                "name": {"type": "string"},
                "onNameConflict": {"type": "string"},
                "notes": {"type": "string"},
                "properties": {"type": "object", "description": "Property names without or with @ prefix."},
                "references": {"type": "object", "description": "Reference names without or with @ prefix."},
            },
            "required": ["parent", "type", "name"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        object_type = input.get("type")
        if object_type not in self._ALLOWED_TYPES:
            return ValidationResult(
                valid=False,
                error="type must be one of Folder, WorkUnit, MusicPlaylistContainer, MusicSwitchContainer, MusicSegment, MusicTrack. Use waapi.create_music_cue for MusicCue.",
            )
        if not str(input.get("parent") or "").strip() or not str(input.get("name") or "").strip():
            return ValidationResult(valid=False, error="parent and name are required")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {
            "parent": input.get("parent"),
            "type": input.get("type"),
            "name": input.get("name"),
        }
        args.update(_optional_create_fields(input))
        return _json_result(context.waapi_client.call("ak.wwise.core.object.create", args))


class WaapiCreateMusicCueTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.create_music_cue"

    @property
    def description(self) -> str:
        return "Create a MusicCue under a MusicSegment using object.create with list='Cues'."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "parent_segment": {"type": "string", "description": "MusicSegment GUID/path/name. Prefer a verified GUID."},
                "name": {"type": "string"},
                "time_ms": {"type": "number"},
                "cue_type": {"type": "integer", "description": "0=Entry, 1=Exit, 2=Custom. Default 2."},
                "onNameConflict": {"type": "string"},
            },
            "required": ["parent_segment", "name", "time_ms"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        if not str(input.get("parent_segment") or "").strip() or not str(input.get("name") or "").strip():
            return ValidationResult(valid=False, error="parent_segment and name are required")
        if not isinstance(input.get("time_ms"), (int, float)):
            return ValidationResult(valid=False, error="time_ms must be a number")
        cue_type = input.get("cue_type", 2)
        if cue_type not in (0, 1, 2):
            return ValidationResult(valid=False, error="cue_type must be 0, 1, or 2")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        args = {
            "parent": input.get("parent_segment"),
            "type": "MusicCue",
            "name": input.get("name"),
            "list": "Cues",
            "@TimeMs": input.get("time_ms"),
            "@CueType": input.get("cue_type", 2),
        }
        if input.get("onNameConflict"):
            args["onNameConflict"] = input.get("onNameConflict")
        return _json_result(context.waapi_client.call("ak.wwise.core.object.create", args))


class WaapiSetStateGroupsTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.set_state_groups"

    @property
    def description(self) -> str:
        return "Set the State Group objects associated with a Wwise object."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "object_id": {"type": "string"},
                "state_groups": {"type": "array", "description": "State Group GUID/path/name values."},
            },
            "required": ["object_id", "state_groups"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        if not isinstance(input.get("state_groups"), list) or not input.get("state_groups"):
            return ValidationResult(valid=False, error="state_groups must be a non-empty array")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call(
            "ak.wwise.core.object.setStateGroups",
            {"object": input.get("object_id"), "stateGroups": input.get("state_groups")},
        ))


class WaapiSetStatePropertiesTool(Tool):
    @property
    def name(self) -> str:
        return "waapi.set_state_properties"

    @property
    def description(self) -> str:
        return "Set documented state properties on a Wwise object after State Groups are associated."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "object_id": {"type": "string"},
                "state_properties": {"type": "array", "description": "Documented stateProperties array."},
            },
            "required": ["object_id", "state_properties"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        if not isinstance(input.get("state_properties"), list) or not input.get("state_properties"):
            return ValidationResult(valid=False, error="state_properties must be a non-empty array")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        if context.waapi_client is None:
            return _waapi_missing_result()
        return _json_result(context.waapi_client.call(
            "ak.wwise.core.object.setStateProperties",
            {"object": input.get("object_id"), "stateProperties": input.get("state_properties")},
        ))

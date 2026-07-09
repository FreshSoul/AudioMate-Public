"""WAAPI prompt/preflight context helpers."""

from __future__ import annotations


WAAPI_CONTEXT_INTENTS = {"waapi_action", "waapi_readonly", "project_source_audio", "waapi_concept"}


def should_collect_waapi_context(intent: str) -> bool:
    return intent in WAAPI_CONTEXT_INTENTS


def should_use_waapi_retrieval(intent: str) -> bool:
    return intent in WAAPI_CONTEXT_INTENTS


def strip_waql_guidance(text: str) -> str:
    """Remove WAQL-related guidance from retrieved knowledge before prompting."""
    if not text:
        return ""
    return "\n".join(line for line in text.splitlines() if "waql" not in line.lower()).strip()


def build_disconnected_waapi_context(*, requires_live_waapi_data: bool) -> str:
    return (
        "\n[Wwise Connection Status]\n"
        "Connected: False\n"
        f"Needs live project data: {'True' if requires_live_waapi_data else 'False'}\n"
        "Instruction: Answer according to the disconnected state first. Do not claim any current project data was inspected. Remind the user to click Connect if they need project-specific analysis or execution.\n\n"
    )


def collect_waapi_context_info(waapi_client) -> tuple:
    """Return (version_info, context_str) or (None, '')."""
    if not getattr(waapi_client, "connected", False):
        return None, ""

    version_info = waapi_client.get_wwise_version()
    if not version_info:
        return None, ""

    context_info = "\n[Wwise Preflight]\n"
    context_info += "Connected: True\n"
    context_info += f"Version: {version_info['display']} (Year: {version_info['year']})\n"
    if version_info["is_2025_or_later"]:
        context_info += "Hierarchy: Use '\\Containers' for Actor-Mixer/Music objects (2025+ merged hierarchy)\n"
        context_info += "Compatibility: Local WAAPI docs are synced to Wwise 2025.1; prefer 2025 hierarchy roots but still query actual object ids before editing.\n"
    else:
        context_info += "Hierarchy: Use '\\Actor-Mixer Hierarchy' or '\\Interactive Music Hierarchy' (Legacy)\n"
        context_info += "Compatibility: Local WAAPI docs may include newer 2025 APIs; check live functions/schema before using version-sensitive procedures.\n"
    context_info += "Bus hierarchy: Wwise 2025+ docs/examples commonly use '\\Busses' and 'Main Audio Bus'; legacy docs/projects may use '\\Master-Mixer Hierarchy' and 'Master Audio Bus'. Query actual Bus/AuxBus objects first and use returned ids.\n"
    context_info += "Bus routing: Bus/AuxBus routing is defined by parent; do not set OutputBus on Bus/AuxBus. Use OutputBus only to route Sound/Actor-Mixer objects to a verified Bus.\n"

    selected = waapi_client.get_selected_objects()
    if isinstance(selected, dict) and selected.get("objects"):
        context_info += f"Selected: {selected['objects']}\n"

    return version_info, context_info + "\n"


def build_connected_waapi_context(waapi_client) -> str:
    _version_info, context_str = collect_waapi_context_info(waapi_client)
    return context_str


def perform_waapi_preflight(waapi_client) -> dict:
    if not getattr(waapi_client, "connected", False):
        return {
            "ok": False,
            "message": "当前请求需要访问 Wwise/WAAPI，但尚未连接到 Wwise。请先点击 Connect，再继续。",
            "context": "",
        }

    version_info, context_str = collect_waapi_context_info(waapi_client)
    if not version_info:
        return {
            "ok": False,
            "message": "已连接到 WAAPI，但无法获取 Wwise 版本信息。请确认 Wwise 当前可响应 `ak.wwise.core.getInfo`。",
            "context": "",
        }

    return {"ok": True, "message": "", "context": context_str}
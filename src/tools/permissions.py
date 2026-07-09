"""Central permission policy for AudioMate tools and WAAPI calls."""

from __future__ import annotations

from typing import Any


ASK_MODE_ALLOWED_WAAPI_PREFIXES = (
    "ak.wwise.core.getinfo",
    "ak.wwise.core.getprojectinfo",
    "ak.wwise.core.log.get",
    "ak.wwise.core.mediapool.get",
    "ak.wwise.core.object.get",
    "ak.wwise.core.object.getpropertyandreferencenames",
    "ak.wwise.core.object.getattenuationcurve",
    "ak.wwise.core.object.getpropertyinfo",
    "ak.wwise.core.object.gettypes",
    "ak.wwise.core.object.islinked",
    "ak.wwise.core.object.ispropertyenabled",
    "ak.wwise.core.audiosourcepeaks.get",
    "ak.wwise.core.remote.get",
    "ak.wwise.core.soundbank.get",
    "ak.wwise.core.switchcontainer.get",
    "ak.wwise.core.sourcecontrol.getsourcefiles",
    "ak.wwise.waapi.getfunctions",
    "ak.wwise.waapi.getschema",
    "ak.wwise.waapi.gettopics",
    "ak.wwise.ui.getselectedfiles",
    "ak.wwise.ui.getselectedobjects",
    "ak.wwise.ui.layout.get",
    "ak.wwise.ui.bringtoforeground",
    "ak.wwise.core.profiler.",
    "ak.wwise.core.transport.",
    "ak.soundengine.getstate",
    "ak.soundengine.getswitch",
)

ASK_MODE_ALLOWED_UI_COMMANDS = frozenset({
    "findinprojectexplorerselectionchannel1",
    "findinprojectexplorerselectionchannel2",
    "findinprojectexplorerselectionchannel3",
    "findinprojectexplorerselectionchannel4",
    "inspect",
})


def is_ask_mode(mode: str) -> bool:
    return str(mode or "").strip().lower() == "ask mode"


def is_ask_mode_waapi_uri_allowed(uri: str, args: Any = None) -> bool:
    """Return True only for WAAPI calls explicitly allowed in Ask Mode."""
    uri_lower = str(uri or "").strip().lower()
    if not uri_lower:
        return False

    if uri_lower == "ak.wwise.ui.commands.execute":
        command = ""
        if isinstance(args, dict):
            command = str(args.get("command") or "").strip().lower()
        return command in ASK_MODE_ALLOWED_UI_COMMANDS

    return any(uri_lower.startswith(prefix) for prefix in ASK_MODE_ALLOWED_WAAPI_PREFIXES)
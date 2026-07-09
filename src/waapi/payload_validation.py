"""WAAPI payload cleanup helpers for generated calls."""

from __future__ import annotations

import re

GUID_PATTERN = re.compile(r'^"?(\{[0-9A-Fa-f\-]{36}\})"?$')
WAQL_DOLLAR_JUNK = re.compile(r'^\$\s*"[\'"]*\s*$')
STRICT_GUID_PATTERN = re.compile(r'^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$')
PLACEHOLDER_BRACE_VALUE = re.compile(r'^\{[^{}]+\}$')

URI_ALIAS_MAP = {
    "ak.wwise.core.object.getcurve": "ak.wwise.core.object.getAttenuationCurve",
    "ak.wwise.core.object.setcurve": "ak.wwise.core.object.setAttenuationCurve",
}

# Built-in return fields that do NOT use '@' prefix. Kept here as the
# authoritative list for future return-field validation extensions.
BUILTIN_RETURN_FIELDS = {
    "id", "name", "type", "path", "parent", "owner", "shortId",
    "classId", "category", "filePath", "workunitType", "childrenCount",
    "notes", "isPlayable", "music:transitionRoot", "music:playlistRoot",
    "originalFilePath",
}

INVALID_RETURN_FIELDS = {
    "sourcefile", "sourcefilename",
    "audiofile", "language", "audiosource:language", "duration",
    "originalduration", "originalsamplerate", "originalbitdepth",
    "originalchannelconfig", "originalfilesize",
    "volumedryusage", "volumedry", "spreadusage", "spread",
    "lowpassfilterusage", "lowpassfilter", "highpassfilterusage", "highpassfilter",
    "playbacklimit",
}

REQUIRED_OBJECT_ARG_KEYS = ("parent", "object", "id", "child", "stateOrSwitch")
OBJECT_GET_FROM_ARRAY_KEYS = {"id", "search", "name", "path", "ofType", "query"}
OBJECT_GET_SELECTORS = {"parent", "children", "descendants", "ancestors", "referencesTo"}
COMMON_GUESSED_PATHS = (
    "\\Busses",
    "\\Containers",
    "\\Busses\\Default Work Unit\\Main Audio Bus",
    "\\Master-Mixer Hierarchy\\Default Work Unit\\Master Audio Bus",
    "\\Master-Mixer Hierarchy",
    "\\Actor-Mixer Hierarchy",
    "\\Interactive Music Hierarchy",
    "\\Events",
)


def remap_uri_alias(uri: str) -> tuple[str, str | None]:
    """Return the canonical WAAPI URI plus the original URI if it was remapped."""
    uri_lower = (uri or "").lower()
    if uri_lower in URI_ALIAS_MAP:
        return URI_ALIAS_MAP[uri_lower], uri
    return uri, None


def sanitize_guid_value(value):
    """Strip extraneous quotes around a GUID string."""
    if isinstance(value, str):
        match = GUID_PATTERN.match(value.strip())
        if match:
            return match.group(1)
    return value


def sanitize_args(obj):
    """Recursively walk args dict/list and fix double-quoted GUIDs."""
    if isinstance(obj, dict):
        return {key: sanitize_args(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [sanitize_args(value) for value in obj]
    if isinstance(obj, str):
        return sanitize_guid_value(obj)
    return obj


def sanitize_transform(args):
    """Fix transform range from dict {from, to} to array [from, to]."""
    if not isinstance(args, dict):
        return args
    transform = args.get("transform")
    if not isinstance(transform, list):
        return args
    fixed = False
    for index, item in enumerate(transform):
        if isinstance(item, dict) and "range" in item:
            range_value = item["range"]
            if isinstance(range_value, dict) and "from" in range_value and "to" in range_value:
                transform[index] = {"range": [range_value["from"], range_value["to"]]}
                fixed = True
    if fixed:
        print("WAAPI Fix: Converted transform range from dict {from,to} to array [from,to]")
    return args


def sanitize_waql(waql: str) -> str:
    """Fix common generated-code WAQL mistakes where $ is followed by stray quotes."""
    stripped = waql.strip()
    if WAQL_DOLLAR_JUNK.match(stripped):
        return "$"
    return waql


def sanitize_return_fields(fields: list) -> list:
    """Clean up generated options.return field lists."""
    cleaned = []
    for field in fields:
        if not isinstance(field, str) or not field.strip():
            continue
        field = field.strip()
        if field.lower() in INVALID_RETURN_FIELDS:
            print(f"WAAPI Guard: stripped invalid return field '{field}'")
            continue
        cleaned.append(field)
    return cleaned


def _iter_values(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _iter_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_values(item)
    else:
        yield value


def _contains_placeholder(value) -> bool:
    for item in _iter_values(value):
        if not isinstance(item, str):
            continue
        stripped = item.strip()
        if PLACEHOLDER_BRACE_VALUE.match(stripped) and not STRICT_GUID_PATTERN.match(stripped):
            return True
    return False


def _validate_object_get(args: dict, options: dict | None) -> str:
    if "where" in args:
        return "ak.wwise.core.object.get does not accept top-level 'where'; use transform entries instead."

    from_value = args.get("from")
    if isinstance(from_value, dict):
        for key in OBJECT_GET_FROM_ARRAY_KEYS:
            if key in from_value and not isinstance(from_value[key], list):
                return f"ak.wwise.core.object.get from.{key} must be an array, not {type(from_value[key]).__name__}."
        path_values = from_value.get("path") if isinstance(from_value.get("path"), list) else []
        if any(
            isinstance(path, str)
            and any(path.rstrip("\\") != common.rstrip("\\") and path.startswith(common.rstrip("\\") + "\\") for common in COMMON_GUESSED_PATHS)
            for path in path_values
        ):
            return "Do not use guessed Wwise root/default paths. Resolve the real object id/path from the current project first."

    transform = args.get("transform")
    if transform is not None and not isinstance(transform, list):
        return "ak.wwise.core.object.get transform must be an array."
    if isinstance(transform, list):
        for index, item in enumerate(transform):
            if not isinstance(item, dict):
                return f"ak.wwise.core.object.get transform[{index}] must be an object."
            if "select" in item:
                select_value = item["select"]
                if not isinstance(select_value, list) or len(select_value) != 1 or select_value[0] not in OBJECT_GET_SELECTORS:
                    return (
                        f"ak.wwise.core.object.get transform[{index}].select must be a one-item list "
                        "containing parent, children, descendants, ancestors, or referencesTo."
                    )
            where_value = item.get("where")
            if isinstance(where_value, list) and len(where_value) >= 2:
                predicate, predicate_arg = where_value[0], where_value[1]
                if predicate == "type:isIn" and not (
                    isinstance(predicate_arg, list) and all(isinstance(entry, str) for entry in predicate_arg)
                ):
                    return "ak.wwise.core.object.get type:isIn expects a list of object type strings."

    if isinstance(options, dict) and isinstance(options.get("return"), list):
        for field in options["return"]:
            if isinstance(field, str) and field.strip().lstrip("@").lower() in INVALID_RETURN_FIELDS:
                return f"Return field '{field}' is likely invalid or hallucinated; query property/reference names first."
    return ""


def validate_waapi_payload(uri: str, args, options=None) -> str:
    """Return an error string if a WAAPI payload is unsafe or clearly malformed."""
    if _contains_placeholder(args) or _contains_placeholder(options):
        return "Placeholder object IDs are not valid WAAPI arguments. Use real IDs returned by a previous query."

    if isinstance(args, dict):
        if "return" in args:
            return "Put return fields in options, not args. Use waapi_client.call(uri, args, {'return': [...]})"
        if "options" in args:
            return "Do not nest an options object inside args; pass options as the third waapi_client.call argument."

    if uri == "ak.wwise.core.object.get" and isinstance(args, dict):
        return _validate_object_get(args, options if isinstance(options, dict) else None)

    if uri == "ak.wwise.core.object.set" and isinstance(args, dict):
        objects = args.get("objects")
        if not isinstance(objects, list) or not objects:
            return "ak.wwise.core.object.set requires args['objects'] to be a non-empty array."
        if any(not isinstance(item, dict) for item in objects):
            return "ak.wwise.core.object.set objects entries must be objects."

    if uri == "ak.wwise.core.object.setNotes" and isinstance(args, dict):
        if "object" not in args or "notes" not in args:
            return "ak.wwise.core.object.setNotes requires top-level 'object' and 'notes'."

    if uri == "ak.wwise.core.object.setProperty" and isinstance(args, dict):
        for required in ("object", "property", "value"):
            if required not in args:
                return f"ak.wwise.core.object.setProperty requires top-level '{required}'."

    if uri == "ak.wwise.core.object.setReference" and isinstance(args, dict):
        for required in ("object", "reference", "value"):
            if required not in args:
                return f"ak.wwise.core.object.setReference requires top-level '{required}'."

    if uri == "ak.wwise.core.object.setAttenuationCurve" and isinstance(args, dict):
        for required in ("object", "curveType", "points"):
            if required not in args:
                return f"ak.wwise.core.object.setAttenuationCurve requires top-level '{required}'."
        if not isinstance(args.get("points"), list):
            return "ak.wwise.core.object.setAttenuationCurve points must be an array."

    if uri in {"ak.wwise.core.object.setStateGroups", "ak.wwise.core.object.setStateProperties"} and isinstance(args, dict):
        if "object" not in args:
            return f"{uri} requires a top-level 'object'."

    return ""


def validate_required_object_args(args: dict) -> str:
    """Return an error string if a critical object argument is empty."""
    for key in REQUIRED_OBJECT_ARG_KEYS:
        if key in args and isinstance(args[key], str) and not args[key].strip():
            return f"Argument '{key}' is empty. A previous query likely returned no results."
    return ""


def normalize_object_set_args(uri: str, args: dict) -> dict:
    """Wrap flat object.set args into the documented objects array shape."""
    if uri == "ak.wwise.core.object.set" and "object" in args and "objects" not in args:
        print("WAAPI Fix: Wrapped flat 'object' arg into 'objects' array for object.set")
        return {"objects": [args]}
    return args

"""Tests for WAAPI payload cleanup helpers."""

import os
import sys

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.waapi.payload_validation import (
    normalize_object_set_args,
    remap_uri_alias,
    sanitize_args,
    sanitize_return_fields,
    sanitize_transform,
    sanitize_waql,
    validate_waapi_payload,
    validate_required_object_args,
)


guid = "{00000000-0000-0000-0000-000000000000}"
assert sanitize_args({"object": f'"{guid}"', "children": [f'"{guid}"']}) == {
    "object": guid,
    "children": [guid],
}

args = {"transform": [{"range": {"from": 0, "to": 10}}]}
assert sanitize_transform(args) == {"transform": [{"range": [0, 10]}]}

assert sanitize_waql('$ "') == "$"
assert sanitize_waql("$ from type Sound") == "$ from type Sound"

assert sanitize_return_fields(["id", " sourceFile ", "@Volume", "", 123]) == ["id", "@Volume"]

canonical_uri, old_uri = remap_uri_alias("ak.wwise.core.object.getCurve")
assert canonical_uri == "ak.wwise.core.object.getAttenuationCurve"
assert old_uri == "ak.wwise.core.object.getCurve"

assert validate_required_object_args({"parent": ""}) == "Argument 'parent' is empty. A previous query likely returned no results."
assert validate_required_object_args({"parent": guid}) == ""

flat_args = {"object": guid, "@Volume": 1.0}
assert normalize_object_set_args("ak.wwise.core.object.set", flat_args) == {"objects": [flat_args]}
assert normalize_object_set_args("ak.wwise.core.object.get", flat_args) is flat_args

assert "options" in validate_waapi_payload("ak.wwise.core.object.get", {"return": ["id"]})
assert "from.path" in validate_waapi_payload("ak.wwise.core.object.get", {"from": {"path": "\\Events"}})
assert validate_waapi_payload("ak.wwise.core.object.get", {"from": {"path": ["\\Busses"]}}) == ""
assert validate_waapi_payload("ak.wwise.core.object.get", {"from": {"path": ["\\Containers"]}}) == ""
assert validate_waapi_payload("ak.wwise.core.object.get", {"from": {"path": ["\\Interactive Music Hierarchy"]}}) == ""
assert "guessed" in validate_waapi_payload("ak.wwise.core.object.get", {"from": {"path": ["\\Busses\\Default Work Unit\\Main Audio Bus"]}})
assert "guessed" in validate_waapi_payload("ak.wwise.core.object.get", {"from": {"path": ["\\Containers\\Default Work Unit"]}})
assert "type:isIn" in validate_waapi_payload(
    "ak.wwise.core.object.get",
    {"transform": [{"where": ["type:isIn", "Sound"]}]},
)
assert "Placeholder" in validate_waapi_payload(
    "ak.wwise.core.object.setProperty",
    {"object": "{Part2_Parent_ID}", "property": "Volume", "value": -3},
)
assert "object" in validate_waapi_payload("ak.wwise.core.object.setNotes", {"notes": "hello"})
assert validate_waapi_payload(
    "ak.wwise.core.object.get",
    {"from": {"id": [guid]}, "transform": [{"select": ["children"]}]},
    {"return": ["id", "name", "type"]},
) == ""

print("test_waapi_payload_validation: OK")

"""Tests for static WAAPI query validation."""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_test_dir, "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.utils.execution import validate_code_patterns


bad_code = """
result = waapi_client.call("ak.wwise.core.object.get", {
    "from": {"id": ["{00000000-0000-0000-0000-000000000000}"]},
    "transform": [{"select": ["duckedBuses"]}],
}, {"return": ["id", "name"]})
"""

warnings = validate_code_patterns(bad_code)
assert any("duckedBuses" in warning and "transform.select" in warning for warning in warnings)

bad_shape_code = """
result = waapi_client.call("ak.wwise.core.object.get", {
    "from": {"path": "\\\\Events"},
    "return": ["id", "@PlaybackLimit"],
    "transform": [{"where": ["type:isIn", "Sound"]}],
})
"""

shape_warnings = validate_code_patterns(bad_shape_code)
assert any("return" in warning and "options" in warning for warning in shape_warnings)
assert any("from.path" in warning for warning in shape_warnings)
assert any("@PlaybackLimit" in warning for warning in shape_warnings)
assert any("type:isIn" in warning for warning in shape_warnings)

placeholder_code = """
waapi_client.call("ak.wwise.core.object.setProperty", {
    "object": "{Part2_Parent_ID}",
    "property": "Volume",
    "value": -3,
})
"""

placeholder_warnings = validate_code_patterns(placeholder_code)
assert any("Placeholder" in warning for warning in placeholder_warnings)


good_code = """
args = {
    "from": {"id": ["{00000000-0000-0000-0000-000000000000}"]},
    "transform": [{"select": ["children"]}],
}
result = waapi_client.call("ak.wwise.core.object.get", args, {"return": ["id", "name", "type"]})
"""

assert validate_code_patterns(good_code) == []

busses_root_code = """
waapi_client.call("ak.wwise.core.object.get", {"from": {"path": ["\\\\Busses"]}}, {"return": ["id", "name"]})
"""
assert validate_code_patterns(busses_root_code) == []

busses_default_code = """
waapi_client.call("ak.wwise.core.object.get", {"from": {"path": ["\\\\Busses\\\\Default Work Unit\\\\Main Audio Bus"]}}, {"return": ["id", "name"]})
"""
assert any("Hard-coded Wwise" in warning for warning in validate_code_patterns(busses_default_code))

print("test_waapi_query_validation: OK")
from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = PROJECT_ROOT / "plugins" / "reaper-control-plugin" / "plugin.py"


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location("audiomate_reaper_control_plugin", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


plugin_module = _load_plugin_module()


class FakeBridge(plugin_module.ReaperBridge):
    def __init__(self):
        self.numeric_values = {}
        self.string_values = {}
        self.events = []

    def _get_project_info_value(self, desc: str) -> float:
        return float(self.numeric_values.get(desc, 0.0))

    def _set_project_info_value(self, desc: str, value: float) -> float:
        self.events.append(("set_info", desc, value))
        self.numeric_values[desc] = value
        return float(value)

    def _get_project_string_value(self, desc: str, query_value: str = "") -> str:
        return str(self.string_values.get(desc, ""))

    def _set_project_string_value(self, desc: str, value: str) -> str:
        self.events.append(("set_string", desc, value))
        self.string_values[desc] = value
        return value

    def execute_action(self, command_id, flag: int = 0) -> dict:
        self.events.append(("action", command_id, flag))
        return {"command_id": command_id, "executed": True}


def test_render_applies_output_directory_before_rendering(tmp_path):
    bridge = FakeBridge()
    output_dir = tmp_path / "render-output"

    result = bridge.render(
        mode="recent",
        settings={
            "output_path": str(output_dir),
            "pattern": "$region",
            "bounds": "all_project_regions",
            "normalize": True,
            "normalize_mode": "lufs_i",
            "normalize_target_db": -16,
        },
    )

    assert output_dir.exists()
    assert result["executed"] is True
    assert result["settings"]["applied"]["strings"]["RENDER_FILE"] == str(output_dir)
    assert result["settings"]["applied"]["strings"]["RENDER_PATTERN"] == "$region"
    assert ("action", "render_recent", 0) in bridge.events
    render_index = bridge.events.index(("action", "render_recent", 0))
    set_render_file_index = bridge.events.index(("set_string", "RENDER_FILE", str(output_dir)))
    assert set_render_file_index < render_index
    assert bridge.numeric_values["RENDER_BOUNDSFLAG"] == float(plugin_module.ReaperBridge.RENDER_BOUNDS_VALUES["all_project_regions"])
    assert "RENDER_NORMALIZE" in bridge.numeric_values
    assert bridge.numeric_values["RENDER_NORMALIZE_TARGET"] > 0


def test_plugin_render_forwards_render_settings_to_bridge(tmp_path):
    plugin = plugin_module.Plugin()
    plugin.bridge = FakeBridge()
    output_dir = tmp_path / "plugin-render-output"

    result = plugin.render(
        {
            "mode": "recent",
            "directory": str(output_dir),
            "pattern": "$region",
            "bounds": "all_project_regions",
            "normalize_target_db": -16,
            "ignored": "not a render setting",
        },
        context=None,
    )

    assert result["ok"] is True
    data = result["data"]
    assert data["settings"]["applied"]["strings"]["RENDER_FILE"] == str(output_dir)
    assert ("action", "render_recent", 0) in plugin.bridge.events


if __name__ == "__main__":
    test_render_applies_output_directory_before_rendering(Path.cwd() / "tmp" / "test-render-control")
    test_plugin_render_forwards_render_settings_to_bridge(Path.cwd() / "tmp" / "test-render-plugin")
    print("test_reaper_control_render: OK")

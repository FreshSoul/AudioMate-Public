import os
import sys

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.storage import normalize_app_settings


def test_normalize_app_settings_seeds_default_buddy_once():
    settings = normalize_app_settings({})
    pets = settings["pets"]
    assert pets["active_main_id"] == "audiomate-main"
    assert pets["floating_pet_id"] == "audiomate-main"
    assert pets["desk_layout"] == ["codex-agent", "claude-code-agent"]
    assert [item["name"] for item in pets["items"]] == ["AudioMate", "Codex", "ClaudeCode"]
    assert settings["buddy_defaults_seeded"] is True

    legacy_empty = normalize_app_settings({"pets": {"items": [], "active_main_id": ""}})
    assert legacy_empty["pets"]["active_main_id"] == "audiomate-main"

    legacy_with_placeholder_main = normalize_app_settings({
        "pets": {
            "items": [{"id": "legacy-main", "kind": "main", "name": "新主宠"}],
            "active_main_id": "legacy-main",
        },
    })
    legacy_pets = legacy_with_placeholder_main["pets"]
    assert legacy_pets["active_main_id"] == "audiomate-main"
    assert legacy_pets["floating_pet_id"] == "audiomate-main"
    assert {item["id"] for item in legacy_pets["items"]} >= {
        "audiomate-main",
        "codex-agent",
        "claude-code-agent",
    }
    assert next(item for item in legacy_pets["items"] if item["id"] == "audiomate-main")["name"] == "AudioMate"

    explicit_empty = normalize_app_settings({
        "buddy_defaults_seeded": True,
        "pets": {"items": [], "active_main_id": ""},
    })
    assert explicit_empty["pets"]["active_main_id"] == "audiomate-main"
    print("test_normalize_app_settings_seeds_default_buddy_once: OK")


if __name__ == "__main__":
    test_normalize_app_settings_seeds_default_buddy_once()

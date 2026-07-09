"""Regression tests for robust Skill manifest loading."""

import os
import sys
import tempfile

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.skill_store import build_skill_prompt_guidance, import_skill_directory


with tempfile.TemporaryDirectory() as temp_dir:
    skill_dir = os.path.join(temp_dir, "broken-manifest-skill")
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "skill.json"), "w", encoding="utf-8") as handle:
        handle.write("{not valid json")
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
        handle.write("# Robust Skill\n\nUse this skill for resilient manifest fallback.\n")

    skill_item = import_skill_directory(skill_dir)
    assert skill_item["name"] == "Robust Skill"

    app_settings = {"skills": {"items": [skill_item]}}
    prompt = build_skill_prompt_guidance(app_settings, "resilient manifest fallback")
    assert "Robust Skill" in prompt
    assert "resilient manifest fallback" in prompt

print("test_skill_store_manifest_robustness: OK")
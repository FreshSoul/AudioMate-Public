"""Smoke tests for forced Skill prompt selection."""

import os
import sys
import tempfile

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.skill_store import build_skill_prompt_guidance


def make_skill(root, dirname, title, body, description=""):
    path = os.path.join(root, dirname)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "SKILL.md"), "w", encoding="utf-8") as handle:
        handle.write(f"# {title}\n\n{body}\n")
    return path


with tempfile.TemporaryDirectory() as temp_dir:
    route_dir = make_skill(
        temp_dir,
        "route-skill",
        "Route Skill",
        "Use this skill for route loudness analysis and bus gain summaries.",
        "Route loudness helper",
    )
    mix_dir = make_skill(
        temp_dir,
        "mix-skill",
        "Mix Skill",
        "Use this skill for mix review notes and balance suggestions.",
        "Mix review helper",
    )
    disabled_dir = make_skill(
        temp_dir,
        "disabled-skill",
        "Disabled Skill",
        "This disabled skill should never be forced into prompts.",
        "Disabled helper",
    )

    app_settings = {
        "skills": {
            "items": [
                {
                    "id": "route",
                    "name": "Route Skill",
                    "description": "Route loudness helper",
                    "source_dir": route_dir,
                    "enabled": True,
                    "status": "ready",
                },
                {
                    "id": "mix",
                    "name": "Mix Skill",
                    "description": "Mix review helper",
                    "source_dir": mix_dir,
                    "enabled": True,
                    "status": "ready",
                },
                {
                    "id": "disabled",
                    "name": "Disabled Skill",
                    "description": "Disabled helper",
                    "source_dir": disabled_dir,
                    "enabled": False,
                    "status": "ready",
                },
            ]
        }
    }

    auto_prompt = build_skill_prompt_guidance(app_settings, "route loudness report")
    assert "FORCED ACTIVE SKILL GUIDANCE" not in auto_prompt
    assert "[Skill: Route Skill]" in auto_prompt

    forced_prompt = build_skill_prompt_guidance(
        app_settings,
        "route loudness report",
        forced_skill_id="mix",
    )
    assert "FORCED ACTIVE SKILL GUIDANCE" in forced_prompt
    assert "[Forced Skill: Mix Skill]" in forced_prompt
    assert "[Skill: Route Skill]" in forced_prompt
    assert "[Skill: Mix Skill]" not in forced_prompt

    forced_only_prompt = build_skill_prompt_guidance(
        app_settings,
        "unrelated request",
        forced_skill_id="mix",
    )
    assert "[Forced Skill: Mix Skill]" in forced_only_prompt
    assert "ACTIVE SKILL GUIDANCE" not in forced_only_prompt.replace("FORCED ACTIVE SKILL GUIDANCE", "")

    disabled_prompt = build_skill_prompt_guidance(
        app_settings,
        "disabled helper",
        forced_skill_id="disabled",
    )
    assert "FORCED ACTIVE SKILL GUIDANCE" not in disabled_prompt
    assert "Disabled Skill" not in disabled_prompt

print("test_skill_forced_selection: OK")

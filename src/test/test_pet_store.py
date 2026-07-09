"""Unit tests for ``src.pet.store`` normalisation & mutation helpers."""

import os
import sys

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.pet.store import (
    ACTIVITY_LOG_CAP,
    PET_KIND_MAIN,
    PET_KIND_SUB,
    bound_capability_owners,
    build_default_pet_settings,
    build_pet_payload,
    change_pet_kind,
    find_pet,
    get_active_main,
    get_floating_pet,
    list_main_pets,
    list_orphan_capabilities,
    list_sub_pets,
    normalize_pet_settings,
    record_pet_activity,
    remove_pet_item,
    resolve_pet_capabilities,
    resolve_pet_llm_config,
    seed_default_buddy_pets,
    set_active_main,
    set_desk_layout,
    set_floating_pet,
    set_floating_state,
    update_pet_item,
    upsert_pet_item,
)


# ---------------------------------------------------------------------------
# normalize_pet_settings
# ---------------------------------------------------------------------------


def test_normalize_handles_missing_and_partial_inputs():
    assert normalize_pet_settings(None) == {
        "active_main_id": "",
        "floating_pet_id": "",
        "floating_enabled": False,
        "floating_position": {"x": -1, "y": -1},
        "items": [],
        "desk_layout": [],
    }
    assert normalize_pet_settings({})["items"] == []
    assert normalize_pet_settings({"pets": []})["items"] == []
    assert normalize_pet_settings({"pets": "garbage"})["items"] == []


def test_default_pet_settings_seed_audiomate_codex_and_claude_code():
    state = build_default_pet_settings()
    assert state["active_main_id"] == "audiomate-main"
    assert state["floating_pet_id"] == "audiomate-main"
    assert state["desk_layout"] == ["codex-agent", "claude-code-agent"]
    names = {item["id"]: item["name"] for item in state["items"]}
    assert names["audiomate-main"] == "AudioMate"
    assert names["codex-agent"] == "Codex"
    assert names["claude-code-agent"] == "ClaudeCode"
    external = {item["id"]: item.get("external_agent") for item in state["items"]}
    assert external["audiomate-main"] == ""
    assert external["codex-agent"] == "codex"
    assert external["claude-code-agent"] == "claude_code"


def test_seed_default_buddy_pets_merges_legacy_main_state():
    state = seed_default_buddy_pets({
        "items": [{"id": "legacy-main", "kind": "main", "name": "新主宠"}],
        "active_main_id": "legacy-main",
    })
    assert state["active_main_id"] == "audiomate-main"
    assert state["floating_pet_id"] == "audiomate-main"
    names = {item["id"]: item["name"] for item in state["items"]}
    assert "legacy-main" not in names
    assert names["audiomate-main"] == "AudioMate"
    assert names["codex-agent"] == "Codex"
    assert names["claude-code-agent"] == "ClaudeCode"
    assert state["desk_layout"][:2] == ["codex-agent", "claude-code-agent"]


def test_seed_default_buddy_pets_preserves_desktop_pet_choice():
    state = seed_default_buddy_pets({
        "items": [],
        "active_main_id": "",
        "floating_pet_id": "codex-agent",
    })
    assert state["active_main_id"] == "audiomate-main"
    assert state["floating_pet_id"] == "codex-agent"


def test_fixed_default_pets_cannot_be_removed_or_rekinded():
    state = build_default_pet_settings()
    after_delete = remove_pet_item(state, "codex-agent")
    assert find_pet(after_delete, "codex-agent") is not None
    after_demote = change_pet_kind(state, "audiomate-main", PET_KIND_SUB)
    assert find_pet(after_demote, "audiomate-main")["kind"] == PET_KIND_MAIN
    with_user_sub = upsert_pet_item(state, {"id": "user-sub", "kind": PET_KIND_SUB, "name": "User Sub"})
    after_promote = change_pet_kind(with_user_sub, "user-sub", PET_KIND_MAIN)
    assert after_promote["active_main_id"] == "audiomate-main"
    assert find_pet(after_promote, "user-sub")["kind"] == PET_KIND_SUB


def test_normalize_rejects_invalid_kind_and_falls_back_to_default_name():
    raw = {
        "pets": {
            "items": [
                {"kind": "alien", "name": "ignored"},
                {"kind": "main", "name": ""},
                {"kind": "sub", "name": "  "},
            ],
        }
    }
    normalized = normalize_pet_settings(raw)
    items = normalized["items"]
    assert len(items) == 2
    kinds = [item["kind"] for item in items]
    assert kinds.count(PET_KIND_MAIN) == 1
    assert kinds.count(PET_KIND_SUB) == 1
    names = {item["name"] for item in items}
    assert "主宠" in names
    assert "副宠" in names


def test_normalize_dedupes_by_id_and_sorts_main_first():
    raw = {
        "pets": {
            "items": [
                {"id": "alpha", "kind": "sub", "name": "Alpha"},
                {"id": "alpha", "kind": "main", "name": "Duplicate"},
                {"id": "beta", "kind": "main", "name": "Beta"},
            ],
        }
    }
    items = normalize_pet_settings(raw)["items"]
    assert [item["id"] for item in items][0] == "beta"  # main first
    assert items[0]["kind"] == PET_KIND_MAIN
    assert len({item["id"] for item in items}) == len(items)


def test_active_main_id_repaired_when_pointing_at_nothing():
    raw = {
        "pets": {
            "active_main_id": "nonexistent",
            "items": [
                {"id": "real", "kind": "main", "name": "Real"},
            ],
        }
    }
    normalized = normalize_pet_settings(raw)
    assert normalized["active_main_id"] == "real"


# ---------------------------------------------------------------------------
# upsert_pet_item / remove_pet_item / update_pet_item
# ---------------------------------------------------------------------------


def test_upsert_inserts_then_replaces_preserving_stats():
    state = normalize_pet_settings({})
    state = upsert_pet_item(state, {"id": "p1", "kind": "main", "name": "Buddy"})
    assert state["active_main_id"] == "p1"

    # bump stats via activity, then upsert the same id without supplying stats
    state = record_pet_activity(state, "p1", {"title": "ping", "outcome": "success"})
    assert state["items"][0]["stats"]["tasks_total"] == 1

    state = upsert_pet_item(state, {"id": "p1", "kind": "main", "name": "Buddy Renamed"})
    item = next(item for item in state["items"] if item["id"] == "p1")
    assert item["name"] == "Buddy Renamed"
    assert item["stats"]["tasks_total"] == 1  # preserved


def test_remove_pet_clears_active_main_when_needed():
    state = normalize_pet_settings({})
    state = upsert_pet_item(state, {"id": "main-a", "kind": "main", "name": "A"})
    assert state["active_main_id"] == "main-a"

    # Singleton invariant means only one main can ever exist. Promote a
    # sub then swap, mirroring real user-facing flows.
    state = upsert_pet_item(state, {"id": "sub-b", "kind": "sub", "name": "B"})
    state = change_pet_kind(state, "sub-b", "main")
    assert state["active_main_id"] == "sub-b"
    kinds = {p["id"]: p["kind"] for p in state["items"]}
    assert kinds == {"main-a": "sub", "sub-b": "main"}

    state = remove_pet_item(state, "sub-b")
    # active main pointer cleared; only the demoted (now sub) "main-a" remains.
    assert state["active_main_id"] == ""
    remaining_kinds = {p["id"]: p["kind"] for p in state["items"]}
    assert remaining_kinds == {"main-a": "sub"}

    state = remove_pet_item(state, "main-a")
    assert state["active_main_id"] == ""
    assert state["items"] == []


def test_update_pet_item_patches_fields_and_ignores_id_change():
    state = normalize_pet_settings({})
    state = upsert_pet_item(state, {"id": "p1", "kind": "sub", "name": "S"})
    state = update_pet_item(state, "p1", name="Renamed", enabled=False, id="hacker")
    item = find_pet(state, "p1")
    assert item is not None
    assert item["name"] == "Renamed"
    assert item["enabled"] is False
    # Updating an unknown id is a no-op
    unchanged = update_pet_item(state, "ghost", name="X")
    assert find_pet(unchanged, "p1")["name"] == "Renamed"


# ---------------------------------------------------------------------------
# record_pet_activity
# ---------------------------------------------------------------------------


def test_record_pet_activity_increments_stats_and_caps_log():
    state = normalize_pet_settings({})
    state = upsert_pet_item(state, {"id": "p1", "kind": "sub", "name": "S"})

    # Push success + fail + cancel
    state = record_pet_activity(state, "p1", {"title": "ok", "outcome": "success", "tool_count": 2})
    state = record_pet_activity(state, "p1", {"title": "boom", "outcome": "fail"})
    state = record_pet_activity(state, "p1", {"title": "skip", "outcome": "cancel"})
    item = find_pet(state, "p1")
    assert item["stats"]["tasks_total"] == 3
    assert item["stats"]["tasks_succeeded"] == 1
    assert item["stats"]["tasks_failed"] == 1
    assert item["stats"]["tools_used"] == 2
    assert item["stats"]["last_active_at"]

    # Push far past the cap to ensure trimming
    for index in range(ACTIVITY_LOG_CAP + 20):
        state = record_pet_activity(state, "p1", {"title": f"task-{index}", "outcome": "info"})
    item = find_pet(state, "p1")
    assert len(item["activity_log"]) == ACTIVITY_LOG_CAP
    # newest entries kept
    assert item["activity_log"][-1]["title"].startswith("task-")


def test_record_activity_ignores_unknown_pet_and_blank_entries():
    state = normalize_pet_settings({})
    state = upsert_pet_item(state, {"id": "p1", "kind": "main", "name": "A"})
    same_state = record_pet_activity(state, "unknown", {"title": "noop"})
    assert same_state["items"][0]["stats"]["tasks_total"] == 0
    same_state = record_pet_activity(state, "p1", {"outcome": "success"})  # no title
    assert same_state["items"][0]["stats"]["tasks_total"] == 0


# ---------------------------------------------------------------------------
# set_floating_state / build_pet_payload / list helpers
# ---------------------------------------------------------------------------


def test_floating_state_round_trip():
    state = set_floating_state({}, enabled=True, position={"x": 10, "y": 20})
    assert state["floating_enabled"] is True
    assert state["floating_position"] == {"x": 10, "y": 20}
    state = set_floating_state(state, enabled=False)
    assert state["floating_enabled"] is False
    assert state["floating_position"] == {"x": 10, "y": 20}


def test_floating_pet_can_be_selected_independently_from_main():
    state = build_default_pet_settings()
    state = set_floating_pet(state, "codex-agent")
    assert state["active_main_id"] == "audiomate-main"
    assert state["floating_pet_id"] == "codex-agent"
    pet = get_floating_pet(state)
    assert pet and pet["id"] == "codex-agent"


def test_removing_desktop_pet_falls_back_to_audiomate():
    state = build_default_pet_settings()
    state = upsert_pet_item(state, {"id": "user-sub", "kind": PET_KIND_SUB, "name": "User Sub"})
    state = set_floating_pet(state, "user-sub")
    state = remove_pet_item(state, "user-sub")
    assert state["active_main_id"] == "audiomate-main"
    assert state["floating_pet_id"] == "audiomate-main"


def test_helpers_partition_pets_by_kind():
    state = normalize_pet_settings({})
    state = upsert_pet_item(state, {"id": "m", "kind": "main", "name": "M"})
    state = upsert_pet_item(state, {"id": "s1", "kind": "sub", "name": "S1"})
    state = upsert_pet_item(state, {"id": "s2", "kind": "sub", "name": "S2"})
    assert {p["id"] for p in list_main_pets(state)} == {"m"}
    assert {p["id"] for p in list_sub_pets(state)} == {"s1", "s2"}
    active = get_active_main(state)
    assert active and active["id"] == "m"


def test_build_pet_payload_is_renormalised():
    raw = {"items": [{"id": "x", "kind": "main", "name": "X"}], "floating_enabled": "1"}
    payload = build_pet_payload(raw)
    assert payload["floating_enabled"] is True
    assert payload["active_main_id"] == "x"


# ---------------------------------------------------------------------------
# Promote / demote / desk layout
# ---------------------------------------------------------------------------


def test_promote_sub_to_main_makes_it_active_when_no_main():
    raw = {"items": [{"id": "s1", "kind": "sub", "name": "Sub"}]}
    state = normalize_pet_settings(raw)
    assert state["active_main_id"] == ""
    promoted = change_pet_kind(state, "s1", "main")
    promoted_pet = next(p for p in promoted["items"] if p["id"] == "s1")
    assert promoted_pet["kind"] == "main"
    assert promoted["active_main_id"] == "s1"


def test_demote_only_main_clears_active_pointer():
    raw = {
        "items": [
            {"id": "m1", "kind": "main", "name": "M1"},
            {"id": "s1", "kind": "sub", "name": "S1"},
        ],
        "active_main_id": "m1",
    }
    state = normalize_pet_settings(raw)
    assert state["active_main_id"] == "m1"
    demoted = change_pet_kind(state, "m1", "sub")
    kinds = {p["id"]: p["kind"] for p in demoted["items"]}
    assert kinds == {"m1": "sub", "s1": "sub"}
    # No main remains → active_main_id cleared.
    assert demoted["active_main_id"] == ""


def test_desk_layout_persists_and_filters_unknown_ids():
    raw = {
        "items": [
            {"id": "a", "kind": "sub", "name": "A"},
            {"id": "b", "kind": "sub", "name": "B"},
        ],
        "desk_layout": ["b", "ghost", "a"],
    }
    state = normalize_pet_settings(raw)
    assert state["desk_layout"] == ["b", "a"]
    updated = set_desk_layout(state, ["a", "b", "missing"])
    assert updated["desk_layout"] == ["a", "b"]


def test_change_pet_kind_to_main_demotes_existing_main():
    state = normalize_pet_settings(
        {
            "items": [
                {"id": "old", "kind": "main", "name": "Old"},
                {"id": "new", "kind": "sub", "name": "New"},
            ],
            "active_main_id": "old",
        }
    )
    promoted = change_pet_kind(state, "new", "main")
    kinds = {p["id"]: p["kind"] for p in promoted["items"]}
    assert kinds == {"old": "sub", "new": "main"}
    assert promoted["active_main_id"] == "new"
    mains = [p for p in promoted["items"] if p["kind"] == "main"]
    assert len(mains) == 1


def test_normalize_caps_main_to_one_and_keeps_active():
    raw = {
        "items": [
            {"id": "m1", "kind": "main", "name": "M1"},
            {"id": "m2", "kind": "main", "name": "M2"},
            {"id": "s1", "kind": "sub", "name": "S1"},
        ],
        "active_main_id": "m2",
    }
    state = normalize_pet_settings(raw)
    mains = [p for p in state["items"] if p["kind"] == "main"]
    assert len(mains) == 1
    assert mains[0]["id"] == "m2"
    assert state["active_main_id"] == "m2"


def test_upsert_refuses_to_add_second_main():
    state = normalize_pet_settings({"items": [{"id": "m1", "kind": "main", "name": "M1"}]})
    after = upsert_pet_item(state, {"id": "m2", "kind": "main", "name": "M2"})
    mains = [p for p in after["items"] if p["kind"] == "main"]
    assert len(mains) == 1
    assert mains[0]["id"] == "m1"


def test_remove_pet_drops_id_from_desk_layout():
    state = normalize_pet_settings(
        {
            "items": [{"id": "a", "kind": "sub", "name": "A"},
                       {"id": "b", "kind": "sub", "name": "B"}],
            "desk_layout": ["a", "b"],
        }
    )
    after = remove_pet_item(state, "a")
    assert after["desk_layout"] == ["b"]


def test_adding_multiple_pets_with_same_chinese_default_name_keeps_them_distinct():
    """Regression: empty id + non-ASCII default name used to slugify down
    to just the kind prefix ("sub"), so the second add would overwrite the
    first via upsert_pet_item. Each add must produce a distinct id."""
    state = normalize_pet_settings({})
    state = upsert_pet_item(state, {"id": "", "kind": "sub", "name": "新副宠"})
    state = upsert_pet_item(state, {"id": "", "kind": "sub", "name": "新副宠"})
    state = upsert_pet_item(state, {"id": "", "kind": "sub", "name": "新副宠"})
    sub_items = [p for p in state["items"] if p.get("kind") == "sub"]
    assert len(sub_items) == 3
    assert len({p["id"] for p in sub_items}) == 3


# ---------------------------------------------------------------------------
# Capability resolution & exclusivity
# ---------------------------------------------------------------------------


def _caps_settings():
    return normalize_pet_settings(
        {
            "items": [
                {"id": "m1", "kind": "main", "name": "AudioMate",
                 "capabilities": {"skill_ids": ["s_owned"], "plugin_ids": []}},
                {"id": "s1", "kind": "sub", "name": "Sub1",
                 "capabilities": {"skill_ids": ["s_sub1"], "plugin_ids": ["p_sub1"]}},
            ],
            "active_main_id": "m1",
        }
    )


def test_bound_capability_owners_lists_explicit_bindings():
    state = _caps_settings()
    bound = bound_capability_owners(state)
    assert bound["skills"]["s_owned"]["pet_id"] == "m1"
    assert bound["skills"]["s_sub1"]["pet_id"] == "s1"
    assert bound["plugins"]["p_sub1"]["pet_id"] == "s1"
    assert "s_orphan" not in bound["skills"]


def test_list_orphan_capabilities_returns_unbound_ids():
    state = _caps_settings()
    orphans = list_orphan_capabilities(
        state,
        all_skills=[{"id": "s_owned"}, {"id": "s_sub1"}, {"id": "s_orphan"}],
        all_plugins=[{"id": "p_sub1"}, {"id": "p_orphan"}],
    )
    assert orphans["skill_ids"] == ["s_orphan"]
    assert orphans["plugin_ids"] == ["p_orphan"]


def test_resolve_active_main_gets_orphans_implicitly():
    state = _caps_settings()
    resolved = resolve_pet_capabilities(
        state, "m1",
        all_skills=[{"id": "s_owned"}, {"id": "s_sub1"}, {"id": "s_orphan"}],
        all_plugins=[{"id": "p_sub1"}, {"id": "p_orphan"}],
    )
    # Owned + orphans, but NOT the sub-pet's binding.
    assert set(resolved["skill_ids"]) == {"s_owned", "s_orphan"}
    assert set(resolved["plugin_ids"]) == {"p_orphan"}


def test_resolve_sub_pet_gets_only_explicit_bindings():
    state = _caps_settings()
    resolved = resolve_pet_capabilities(
        state, "s1",
        all_skills=[{"id": "s_owned"}, {"id": "s_sub1"}, {"id": "s_orphan"}],
        all_plugins=[{"id": "p_sub1"}, {"id": "p_orphan"}],
    )
    # Sub-pet sees only its own bindings; orphans stay with the main.
    assert resolved["skill_ids"] == ["s_sub1"]
    assert resolved["plugin_ids"] == ["p_sub1"]


def test_default_pool_follows_active_main_on_promotion():
    """The orphan pool is tied to the active-main *seat*, not identity.
    When a sub is promoted, the new main inherits the same pool."""
    state = normalize_pet_settings(
        {
            "items": [
                {"id": "m1", "kind": "main", "name": "M1",
                 "capabilities": {"skill_ids": [], "plugin_ids": []}},
                {"id": "s1", "kind": "sub", "name": "S1",
                 "capabilities": {"skill_ids": [], "plugin_ids": []}},
            ],
            "active_main_id": "m1",
        }
    )
    all_skills = [{"id": "s_floating"}]
    all_plugins = [{"id": "p_floating"}]
    # m1 currently owns the orphan pool.
    m1_caps = resolve_pet_capabilities(state, "m1", all_skills, all_plugins)
    assert m1_caps["skill_ids"] == ["s_floating"]
    assert m1_caps["plugin_ids"] == ["p_floating"]
    # Promote s1 → main. Atomic swap: m1 demoted, s1 becomes active main.
    promoted = change_pet_kind(state, "s1", "main")
    assert promoted["active_main_id"] == "s1"
    # The pool now flows to s1; old m1 (now sub) loses it.
    s1_caps = resolve_pet_capabilities(promoted, "s1", all_skills, all_plugins)
    assert s1_caps["skill_ids"] == ["s_floating"]
    assert s1_caps["plugin_ids"] == ["p_floating"]
    m1_caps_after = resolve_pet_capabilities(promoted, "m1", all_skills, all_plugins)
    assert m1_caps_after["skill_ids"] == []
    assert m1_caps_after["plugin_ids"] == []


def test_deleted_pet_returns_tools_to_default_pool():
    """Deleting a pet that owned a tool must surface that tool as orphan
    again, so the active main inherits it via the default pool."""
    state = normalize_pet_settings(
        {
            "items": [
                {"id": "m1", "kind": "main", "name": "M1",
                 "capabilities": {"skill_ids": [], "plugin_ids": []}},
                {"id": "s1", "kind": "sub", "name": "S1",
                 "capabilities": {"skill_ids": [], "plugin_ids": ["p_X"]}},
            ],
            "active_main_id": "m1",
        }
    )
    all_plugins = [{"id": "p_X"}, {"id": "p_Y"}]
    # Before delete: p_X is owned by s1 (not in main's pool).
    m1_before = resolve_pet_capabilities(state, "m1", [], all_plugins)
    assert "p_X" not in m1_before["plugin_ids"]
    # Delete s1.
    after = remove_pet_item(state, "s1")
    # p_X is now orphan again.
    orphans = list_orphan_capabilities(after, [], all_plugins)
    assert "p_X" in orphans["plugin_ids"]
    # And the main inherits it via the default pool.
    m1_after = resolve_pet_capabilities(after, "m1", [], all_plugins)
    assert "p_X" in m1_after["plugin_ids"]


# ---------------------------------------------------------------------------
# Sprites schema (idle/working/moving)
# ---------------------------------------------------------------------------


def test_normalize_adds_sprites_block_with_defaults():
    raw = {"items": [{"kind": "main", "name": "Solo"}]}
    pet = normalize_pet_settings(raw)["items"][0]
    assert pet["sprites"] == {"idle": "", "working": "", "moving": ""}


def test_legacy_avatar_path_migrates_into_sprites_idle():
    raw = {"items": [{"kind": "main", "name": "Old", "avatar_path": "/tmp/cat.png"}]}
    pet = normalize_pet_settings(raw)["items"][0]
    assert pet["sprites"]["idle"] == "/tmp/cat.png"
    assert pet["sprites"]["working"] == ""
    assert pet["sprites"]["moving"] == ""
    assert pet["avatar_path"] == "/tmp/cat.png"


def test_explicit_sprites_preserved_and_backfill_avatar_path():
    raw = {
        "items": [
            {
                "kind": "main",
                "name": "Trio",
                "sprites": {
                    "idle": "/a/idle.gif",
                    "working": "/a/work.gif",
                    "moving": "/a/move.gif",
                },
            }
        ]
    }
    pet = normalize_pet_settings(raw)["items"][0]
    assert pet["sprites"] == {
        "idle": "/a/idle.gif",
        "working": "/a/work.gif",
        "moving": "/a/move.gif",
    }
    # avatar_path is backfilled from idle when not supplied.
    assert pet["avatar_path"] == "/a/idle.gif"


# ---------------------------------------------------------------------------
# Per-sub-pet LLM override (llm field + resolve_pet_llm_config)
# ---------------------------------------------------------------------------


def test_normalize_llm_field_round_trip_and_trim():
    raw = {
        "items": [
            {
                "kind": "sub",
                "name": "Worker",
                "llm": {
                    "base_url": "  https://alt.example.com/v1  ",
                    "api_key": " sk-test ",
                    "model": " gpt-x ",
                    "garbage": "dropped",
                },
            }
        ]
    }
    pet = normalize_pet_settings(raw)["items"][0]
    assert pet["llm"] == {
        "base_url": "https://alt.example.com/v1",
        "api_key": "sk-test",
        "model": "gpt-x",
    }


def test_normalize_llm_field_defaults_and_main_pet():
    # Missing llm on a sub pet → all-empty dict with all three keys.
    sub = normalize_pet_settings({"items": [{"kind": "sub", "name": "S"}]})["items"][0]
    assert sub["llm"] == {"base_url": "", "api_key": "", "model": ""}
    # Garbage llm tolerated.
    sub2 = normalize_pet_settings(
        {"items": [{"kind": "sub", "name": "S2", "llm": "garbage"}]}
    )["items"][0]
    assert sub2["llm"] == {"base_url": "", "api_key": "", "model": ""}
    # Main pets never carry an llm override.
    main = normalize_pet_settings(
        {"items": [{"kind": "main", "name": "M", "llm": {"model": "x"}}]}
    )["items"][0]
    assert main["llm"] == {}


def test_llm_field_survives_upsert_and_update():
    state = normalize_pet_settings({"items": [{"kind": "main", "name": "M"}]})
    state = upsert_pet_item(
        state,
        {"id": "worker", "kind": "sub", "name": "W", "llm": {"model": "gpt-x"}},
    )
    pet = find_pet(state, "worker")
    assert pet["llm"]["model"] == "gpt-x"
    state = update_pet_item(state, "worker", name="W2")
    pet = find_pet(state, "worker")
    assert pet["name"] == "W2"
    assert pet["llm"]["model"] == "gpt-x"


def test_resolve_pet_llm_config_inherits_when_empty():
    pet = normalize_pet_settings({"items": [{"kind": "sub", "name": "S"}]})["items"][0]
    resolved = resolve_pet_llm_config(
        pet,
        fallback_api_key="main-key",
        fallback_base_url="https://main/v1",
        fallback_model="main-model",
    )
    assert resolved == {
        "api_key": "main-key",
        "base_url": "https://main/v1",
        "model": "main-model",
        "is_override": False,
    }


def test_resolve_pet_llm_config_partial_override():
    pet = normalize_pet_settings(
        {"items": [{"kind": "sub", "name": "S", "llm": {"model": "alt-model"}}]}
    )["items"][0]
    resolved = resolve_pet_llm_config(
        pet,
        fallback_api_key="main-key",
        fallback_base_url="https://main/v1",
        fallback_model="main-model",
    )
    assert resolved["is_override"] is True
    assert resolved["model"] == "alt-model"
    # Unset fields inherit the main config.
    assert resolved["api_key"] == "main-key"
    assert resolved["base_url"] == "https://main/v1"


def test_resolve_pet_llm_config_main_pet_and_garbage_input():
    main = normalize_pet_settings(
        {"items": [{"kind": "main", "name": "M"}]}
    )["items"][0]
    assert resolve_pet_llm_config(main, fallback_model="m")["is_override"] is False
    # Non-dict input is tolerated and inherits everything.
    resolved = resolve_pet_llm_config(None, fallback_model="m")
    assert resolved["model"] == "m"
    assert resolved["is_override"] is False


def test_external_agent_pets_carry_no_llm_override():
    # External-agent sub-pets (Codex / ClaudeCode) dispatch to local CLIs —
    # any llm config is stripped at normalization time.
    pet = normalize_pet_settings(
        {
            "items": [
                {
                    "kind": "sub",
                    "name": "Codex",
                    "external_agent": "codex",
                    "llm": {"model": "x", "api_key": "sk", "base_url": "https://alt"},
                }
            ]
        }
    )["items"][0]
    assert pet["external_agent"] == "codex"
    assert pet["llm"] == {}
    # Plain sub-pets keep theirs.
    plain = normalize_pet_settings(
        {"items": [{"kind": "sub", "name": "S", "llm": {"model": "x"}}]}
    )["items"][0]
    assert plain["llm"]["model"] == "x"


def test_resolve_pet_llm_config_external_agent_never_overrides():
    # Even if dirty llm data slipped past normalization (hand-edited
    # settings.json), the resolver falls back to the main config.
    dirty = {
        "kind": "sub",
        "external_agent": "claude_code",
        "llm": {"model": "alt", "api_key": "sk", "base_url": "https://alt"},
    }
    resolved = resolve_pet_llm_config(
        dirty,
        fallback_api_key="main-key",
        fallback_base_url="https://main/v1",
        fallback_model="main-model",
    )
    assert resolved["is_override"] is False


# ---------------------------------------------------------------------------
# Script-style runner so this file works with the project's existing pattern
# (the other tests are executed by importing — keep behaviour parity).
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover — manual run helper
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print("OK")

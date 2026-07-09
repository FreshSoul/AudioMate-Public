from __future__ import annotations

import importlib
import math
import os
import traceback
from collections.abc import Sequence
from typing import Any


PLUGIN_VERSION = "0.4.4"


REAPER_SETUP_HINT = (
    "Use the Configure button on the AudioMate Market Reaper Control card to install the bootstrap script, "
    "then restart REAPER and run AudioMate/audiomate_reapy_bootstrap.py once from the REAPER Action List."
)


class ReaperBridgeError(RuntimeError):
    pass


class ReaperBridge:
    """Thin, defensive wrapper around reapy's ReaScript API bridge."""

    ACTIONS = {
        "play": 1007,
        "stop": 1016,
        "pause": 1008,
        "record": 1013,
        "toggle_repeat": 1068,
        "go_to_start": 40042,
        "go_to_end": 40043,
        "render_recent": 41824,
        "render_project": 40015,
        "save_project": 40026,
        "undo": 40029,
        "redo": 40030,
    }

    PLAY_STATES = {
        0: "stopped",
        1: "playing",
        2: "paused",
        4: "recording",
        5: "recording_playing",
        6: "recording_paused",
    }

    PROJECT_INFO_FIELDS = {
        "render_settings": "RENDER_SETTINGS",
        "render_bounds": "RENDER_BOUNDSFLAG",
        "render_boundsflag": "RENDER_BOUNDSFLAG",
        "render_channels": "RENDER_CHANNELS",
        "render_sample_rate": "RENDER_SRATE",
        "render_srate": "RENDER_SRATE",
        "render_start": "RENDER_STARTPOS",
        "render_startpos": "RENDER_STARTPOS",
        "render_end": "RENDER_ENDPOS",
        "render_endpos": "RENDER_ENDPOS",
        "render_tail_flags": "RENDER_TAILFLAG",
        "render_tailflag": "RENDER_TAILFLAG",
        "render_tail_ms": "RENDER_TAILMS",
        "render_tailms": "RENDER_TAILMS",
        "render_add_to_project": "RENDER_ADDTOPROJ",
        "render_addtoproj": "RENDER_ADDTOPROJ",
        "render_dither": "RENDER_DITHER",
        "render_normalize": "RENDER_NORMALIZE",
        "render_normalize_target": "RENDER_NORMALIZE_TARGET",
        "render_brickwall": "RENDER_BRICKWALL",
        "render_fade_in": "RENDER_FADEIN",
        "render_fadein": "RENDER_FADEIN",
        "render_fade_out": "RENDER_FADEOUT",
        "render_fadeout": "RENDER_FADEOUT",
        "render_fade_in_shape": "RENDER_FADEINSHAPE",
        "render_fadeinshape": "RENDER_FADEINSHAPE",
        "render_fade_out_shape": "RENDER_FADEOUTSHAPE",
        "render_fadeoutshape": "RENDER_FADEOUTSHAPE",
        "render_fade_lpf": "RENDER_FADELPF",
        "render_fadelpf": "RENDER_FADELPF",
        "render_pad_start": "RENDER_PADSTART",
        "render_padstart": "RENDER_PADSTART",
        "render_pad_end": "RENDER_PADEND",
        "render_padend": "RENDER_PADEND",
        "render_trim_start": "RENDER_TRIMSTART",
        "render_trimstart": "RENDER_TRIMSTART",
        "render_trim_end": "RENDER_TRIMEND",
        "render_trimend": "RENDER_TRIMEND",
        "render_delay": "RENDER_DELAY",
        "project_sample_rate": "PROJECT_SRATE",
        "project_srate": "PROJECT_SRATE",
        "project_sample_rate_enabled": "PROJECT_SRATE_USE",
        "project_srate_use": "PROJECT_SRATE_USE",
        "project_timebase": "PROJECT_TIMEBASE",
        "project_timebase_flags": "PROJECT_TIMEBASE_FLAGS",
        "project_tcp_ui_flags": "PROJECT_TCP_UI_FLAGS",
        "arrange_width": "ARRANGE_W",
        "arrange_w": "ARRANGE_W",
        "arrange_height": "ARRANGE_H",
        "arrange_h": "ARRANGE_H",
        "arrange_min_timescale": "ARRANGE_MIN_TIMESCALE",
        "ruler_height": "RULER_HEIGHT",
        "ruler_lane_count": "RULER_LANE_COUNT",
    }

    PROJECT_STRING_FIELDS = {
        "project_name": "PROJECT_NAME",
        "project_title": "PROJECT_TITLE",
        "title": "PROJECT_TITLE",
        "project_author": "PROJECT_AUTHOR",
        "author": "PROJECT_AUTHOR",
        "record_path": "RECORD_PATH",
        "record_path_secondary": "RECORD_PATH_SECONDARY",
        "record_format": "RECORD_FORMAT",
        "apply_fx_format": "APPLYFX_FORMAT",
        "render_file": "RENDER_FILE",
        "render_directory": "RENDER_FILE",
        "render_path": "RENDER_FILE",
        "output_dir": "RENDER_FILE",
        "output_path": "RENDER_FILE",
        "render_pattern": "RENDER_PATTERN",
        "render_name": "RENDER_PATTERN",
        "file_name_pattern": "RENDER_PATTERN",
        "filename_pattern": "RENDER_PATTERN",
        "render_extra_file_dir": "RENDER_EXTRAFILEDIR",
        "render_extra_directory": "RENDER_EXTRAFILEDIR",
        "render_metadata": "RENDER_METADATA",
        "render_targets": "RENDER_TARGETS",
        "render_stats": "RENDER_STATS",
        "render_stats_summary": "RENDER_STATS_SUMMARY",
        "render_format": "RENDER_FORMAT",
        "render_format2": "RENDER_FORMAT2",
        "rectag": "RECTAG",
        "record_tag": "RECTAG",
        "opencopy_cfgidx": "OPENCOPY_CFGIDX",
    }

    RENDER_SETTINGS_FLAGS = {
        "stems_master_mix": 1,
        "stems_and_master": 1,
        "stems_plus_master": 1,
        "stems_only": 2,
        "multichannel_tracks": 4,
        "render_matrix": 8,
        "mono_media_to_mono": 16,
        "selected_media_items": 32,
        "selected_items": 32,
        "selected_media_items_via_master": 64,
        "selected_items_via_master": 64,
        "selected_tracks_via_master": 128,
        "embed_transients": 256,
        "embed_metadata": 512,
        "embed_take_markers": 1024,
        "second_pass": 2048,
        "razor_edits": 4096,
        "pre_fader_stems": 8192,
        "only_stem_channels_sent_to_parent": 16384,
        "preserve_source_metadata": 32768,
        "preserve_source_start_offset": 1 << 16,
        "preserve_source_media_sample_rate": 2 << 16,
        "selected_items_as_single_file": 4 << 16,
        "parallel_render_via_master": 8 << 16,
        "delay_render_start": 16 << 16,
    }

    RENDER_MODE_VALUES = {
        "master": 0,
        "master_mix": 0,
        "mix": 0,
        "stems_master_mix": 1,
        "stems_and_master": 1,
        "stems_plus_master": 1,
        "stems_only": 2,
        "selected_media_items": 32,
        "selected_items": 32,
        "selected_media_items_via_master": 64,
        "selected_items_via_master": 64,
        "selected_tracks_via_master": 128,
        "render_matrix": 8,
        "razor_edits": 4096,
        "pre_fader_stems": 8192,
    }

    RENDER_TAIL_FLAGS = {
        "custom": 1,
        "custom_time_bounds": 1,
        "entire_project": 2,
        "whole_project": 2,
        "time_selection": 4,
        "markers_regions": 8,
        "all_project_markers_regions": 8,
        "all_markers_regions": 8,
        "selected_media_items": 16,
        "selected_items": 16,
        "selected_project_markers_regions": 32,
        "selected_markers_regions": 32,
    }

    RENDER_DITHER_FLAGS = {
        "dither": 1,
        "noise_shaping": 2,
        "dither_stems": 4,
        "noise_shaping_stems": 8,
        "disable_all": 16,
    }

    RENDER_ADDTOPROJ_FLAGS = {
        "add_to_project": 1,
        "skip_silent": 2,
        "do_not_render_silent": 2,
    }

    RENDER_NORMALIZE_MODES = {
        "lufs_i": 0,
        "lufs-i": 0,
        "integrated_lufs": 0,
        "rms": 2,
        "peak": 4,
        "true_peak": 6,
        "true-peak": 6,
        "lufs_m_max": 8,
        "lufs-m-max": 8,
        "lufs_s_max": 10,
        "lufs-s-max": 10,
    }

    RENDER_NORMALIZE_SCOPE_FLAGS = {
        "together": 32,
        "files_together": 32,
        "loudest_file": 4096,
        "loudest": 4096,
        "together_common_gain": 32 | 4096,
        "common_gain": 32 | 4096,
        "master_mix": 16 << 16,
        "master": 16 << 16,
    }

    RENDER_LIMIT_SCOPE_FLAGS = {
        "together": 32 << 16,
        "files_together": 32 << 16,
        "master_mix": 64 << 16,
        "master": 64 << 16,
    }

    RENDER_FORMAT_ALIASES = {
        "wav": "evaw",
        "wave": "evaw",
        "mp3": "l3pm",
        "aiff": "ffia",
    }

    RENDER_BOUNDS_VALUES = {
        "custom": 0,
        "custom_time_range": 0,
        "entire_project": 1,
        "whole_project": 1,
        "time_selection": 2,
        "all_project_regions": 3,
        "all_regions": 3,
        "selected_media_items": 4,
        "selected_items": 4,
        "selected_project_regions": 5,
        "selected_regions": 5,
        "all_project_markers": 6,
        "all_markers": 6,
        "selected_project_markers": 7,
        "selected_markers": 7,
    }

    def __init__(self):
        self.reapy = None
        self.rpr = None
        self._connected = False

    def connect(self) -> None:
        if self._connected and self.rpr is not None:
            return
        try:
            self.reapy = importlib.import_module("reapy")
        except Exception as exc:  # noqa: BLE001
            raise ReaperBridgeError(
                "Python package 'reapy' is not installed in AudioMate's environment. "
                "Install python-reapy for AudioMate, or reinstall the Reaper Control plugin. "
                + REAPER_SETUP_HINT
            ) from exc

        if hasattr(self.reapy, "connect"):
            try:
                self.reapy.connect()
            except Exception:
                # Some reapy versions auto-connect lazily; keep going and verify through RPR below.
                pass

        self.rpr = getattr(self.reapy, "reascript_api", None)
        if self.rpr is None:
            raise ReaperBridgeError("reapy is installed, but reapy.reascript_api is unavailable. " + REAPER_SETUP_HINT)

        try:
            self.rpr.GetPlayState()
        except Exception as exc:  # noqa: BLE001
            raise ReaperBridgeError(
                "Reaper bridge is not responding. Open REAPER and enable the reapy dist API first. "
                + REAPER_SETUP_HINT
            ) from exc
        self._connected = True

    def health(self) -> dict:
        self.connect()
        return {
            "connected": True,
            "reapy_version": getattr(self.reapy, "__version__", "unknown"),
            "play_state": self.play_state(),
            "project": self.project_info(include_tracks=False),
        }

    def action_id(self, value: Any) -> int:
        if value is None:
            raise ReaperBridgeError("Action command_id is required.")
        if isinstance(value, str):
            key = value.strip()
            if not key:
                raise ReaperBridgeError("Action command_id cannot be empty.")
            if key in self.ACTIONS:
                return self.ACTIONS[key]
            if key.isdigit() or (key.startswith("-") and key[1:].isdigit()):
                return int(key)
            self.connect()
            named_command_lookup = getattr(self.rpr, "NamedCommandLookup", None)
            if callable(named_command_lookup):
                command_id = int(named_command_lookup(key))
                if command_id:
                    return command_id
            raise ReaperBridgeError(f"Unknown Reaper action id or named command: {value}")
        return int(value)

    def execute_action(self, command_id: Any, flag: int = 0) -> dict:
        self.connect()
        resolved_id = self.action_id(command_id)
        self.rpr.Main_OnCommand(resolved_id, int(flag or 0))
        return {"command_id": resolved_id, "executed": True}

    def transport(self, action: str, **options) -> dict:
        self.connect()
        action = str(action or "status").strip().casefold()
        if action in {"status", "state"}:
            return self.play_state()
        if action in {"play", "pause", "stop", "record", "toggle_repeat", "go_to_start", "go_to_end"}:
            self.execute_action(action)
        elif action in {"set_position", "seek", "set_cursor"}:
            position = _float_or_none(options.get("position") or options.get("seconds"))
            if position is None:
                raise ReaperBridgeError("set_position requires a numeric 'position' in seconds.")
            move_view = bool(options.get("move_view", True))
            seek_play = bool(options.get("seek_play", False))
            self.rpr.SetEditCurPos(float(position), move_view, seek_play)
        else:
            raise ReaperBridgeError(f"Unsupported transport action: {action}")
        return {"action": action, "state": self.play_state(), "cursor_position": self.cursor_position()}

    def play_state(self) -> dict:
        self.connect()
        raw_state = int(self.rpr.GetPlayState())
        return {"raw": raw_state, "name": self.PLAY_STATES.get(raw_state, f"state_{raw_state}")}

    def cursor_position(self) -> float:
        self.connect()
        return float(self.rpr.GetCursorPosition())

    def project_info(self, include_tracks: bool = True) -> dict:
        self.connect()
        project_path = ""
        project_name = ""
        enum_projects = getattr(self.rpr, "EnumProjects", None)
        if callable(enum_projects):
            try:
                enum_result = enum_projects(-1, "", 4096)
                project_path = _first_path(enum_result)
                project_name = os.path.basename(project_path) if project_path else ""
            except Exception:
                project_path = ""

        tempo = None
        time_signature = None
        master_tempo = getattr(self.rpr, "Master_GetTempo", None)
        if callable(master_tempo):
            try:
                tempo = float(master_tempo())
            except Exception:
                tempo = None
        time_sig = getattr(self.rpr, "TimeMap_GetTimeSigAtTime", None)
        if callable(time_sig):
            try:
                sig_result = time_sig(0, self.cursor_position())
                numerator, denominator = _extract_time_signature(sig_result)
                if numerator and denominator:
                    time_signature = f"{numerator}/{denominator}"
            except Exception:
                time_signature = None

        info = {
            "project_name": project_name,
            "project_path": project_path,
            "play_state": self.play_state(),
            "cursor_position": self.cursor_position(),
            "track_count": self.track_count(),
            "tempo": tempo,
            "time_signature": time_signature,
        }
        if include_tracks:
            info["tracks"] = self.list_tracks(include_fx=False)
        return info

    def track_count(self) -> int:
        self.connect()
        return int(self.rpr.CountTracks(0))

    def get_track(self, index: int):
        self.connect()
        if index < 0 or index >= self.track_count():
            raise ReaperBridgeError(f"Track index out of range: {index}")
        return self.rpr.GetTrack(0, int(index))

    def find_track(self, selector: dict):
        if "index" in selector and selector.get("index") is not None:
            return self.get_track(int(selector["index"]))
        name = str(selector.get("name") or "").strip().casefold()
        if name:
            for track in self.list_tracks(include_fx=False, include_handle=True):
                if track["name"].casefold() == name:
                    return track["handle"]
            raise ReaperBridgeError(f"Track not found by name: {selector.get('name')}")
        raise ReaperBridgeError("Provide track 'index' or exact 'name'.")

    def selected_or_first_track(self):
        tracks = self.list_tracks(include_fx=False, include_handle=True)
        if not tracks:
            return self.create_track(index=0)
        for track in tracks:
            if track.get("selected"):
                return track["handle"]
        return tracks[0]["handle"]

    def create_track(self, index: int | None = None):
        self.connect()
        insert_track = getattr(self.rpr, "InsertTrackAtIndex", None)
        if not callable(insert_track):
            self.execute_action(40001)
            return self.get_track(max(0, self.track_count() - 1))
        insert_index = self.track_count() if index is None else max(0, int(index))
        insert_track(insert_index, True)
        adjust_windows = getattr(self.rpr, "TrackList_AdjustWindows", None)
        if callable(adjust_windows):
            adjust_windows(False)
        return self.get_track(min(insert_index, self.track_count() - 1))

    def create_track_with_options(self, payload: dict) -> dict:
        requested_index = payload.get("index")
        inserted_index = self.track_count() if requested_index is None else max(0, int(requested_index))
        track = self.create_track(index=requested_index)
        inserted_index = min(inserted_index, max(0, self.track_count() - 1))
        updates = {}
        for key in ("name", "volume", "volume_db", "pan", "mute", "solo", "record_arm", "selected", "color"):
            if key in payload:
                updates[key] = payload[key]
        if "select" in payload and "selected" not in updates:
            updates["selected"] = payload["select"]
        result = {"track": self.track_info(track, index=inserted_index), "applied": {}}
        if updates:
            result = self.set_track({"index": inserted_index}, updates)
            result["track"]["index"] = inserted_index
        added_fx = []
        for fx_name in payload.get("fx") or []:
            added_fx.append(self.track_fx({"action": "add", "track_index": inserted_index, "name": fx_name}))
        result["added_fx"] = added_fx
        return result

    def list_tracks(self, include_fx: bool = True, include_handle: bool = False) -> list[dict]:
        self.connect()
        tracks = []
        for index in range(self.track_count()):
            track = self.get_track(index)
            item = self.track_info(track, index=index, include_fx=include_fx)
            if include_handle:
                item["handle"] = track
            tracks.append(item)
        return tracks

    def track_info(self, track, index: int | None = None, include_fx: bool = True) -> dict:
        name = self.track_name(track)
        info = {
            "index": index,
            "name": name,
            "volume": self.get_track_value(track, "D_VOL"),
            "volume_db": _linear_to_db(self.get_track_value(track, "D_VOL")),
            "pan": self.get_track_value(track, "D_PAN"),
            "mute": bool(self.get_track_value(track, "B_MUTE")),
            "solo": int(self.get_track_value(track, "I_SOLO")),
            "record_arm": bool(self.get_track_value(track, "I_RECARM")),
            "selected": bool(self.get_track_value(track, "I_SELECTED")),
        }
        if include_fx:
            fx_count = getattr(self.rpr, "TrackFX_GetCount", None)
            if callable(fx_count):
                try:
                    info["fx_count"] = int(fx_count(track))
                except Exception:
                    info["fx_count"] = None
        return info

    def track_name(self, track) -> str:
        get_name = getattr(self.rpr, "GetTrackName", None)
        if callable(get_name):
            try:
                return _first_string(get_name(track, "", 4096))
            except Exception:
                pass
        return ""

    def get_track_value(self, track, key: str) -> float:
        return float(self.rpr.GetMediaTrackInfo_Value(track, key))

    def set_track(self, selector: dict, updates: dict) -> dict:
        self.connect()
        track = self.find_track(selector)
        setters = {
            "volume": "D_VOL",
            "pan": "D_PAN",
            "mute": "B_MUTE",
            "solo": "I_SOLO",
            "record_arm": "I_RECARM",
            "selected": "I_SELECTED",
        }
        applied = {}
        for field, key in setters.items():
            if field not in updates:
                continue
            value = updates[field]
            if field in {"mute", "record_arm", "selected"}:
                value = 1 if bool(value) else 0
            elif field == "solo":
                value = int(value)
            else:
                value = float(value)
            self.rpr.SetMediaTrackInfo_Value(track, key, value)
            applied[field] = value

        if "volume_db" in updates:
            linear_volume = _db_to_linear(float(updates["volume_db"]))
            self.rpr.SetMediaTrackInfo_Value(track, "D_VOL", linear_volume)
            applied["volume"] = linear_volume
            applied["volume_db"] = float(updates["volume_db"])

        if "name" in updates:
            set_string = getattr(self.rpr, "GetSetMediaTrackInfo_String", None)
            if not callable(set_string):
                raise ReaperBridgeError("This Reaper bridge cannot rename tracks.")
            set_string(track, "P_NAME", str(updates["name"]), True)
            applied["name"] = str(updates["name"])

        if "color" in updates:
            color_value = _parse_color(updates["color"])
            self.rpr.SetMediaTrackInfo_Value(track, "I_CUSTOMCOLOR", color_value)
            applied["color"] = color_value

        adjust_windows = getattr(self.rpr, "TrackList_AdjustWindows", None)
        if callable(adjust_windows):
            adjust_windows(False)
        return {"applied": applied, "track": self.track_info(track)}

    def write_midi(self, payload: dict) -> dict:
        self.connect()
        track = self._midi_target_track(payload)
        tempo = self._tempo_for_midi(payload)
        start_time = _float_or_none(payload.get("start_time") or payload.get("start"))
        if start_time is None:
            start_time = self.cursor_position()
        notes = _normalize_midi_notes(payload.get("notes"), tempo=tempo)
        if not notes:
            notes = _default_midi_notes()

        seconds_per_beat = 60.0 / tempo
        item_end = start_time + max(note["start"] + note["duration"] for note in notes) * seconds_per_beat
        item_end += max(0.0, float(payload.get("tail_seconds", 0.0) or 0.0))
        item = self._create_midi_item(track, start_time, item_end)
        take = self._active_take(item)
        inserted = []
        for note in notes:
            note_start_time = start_time + note["start"] * seconds_per_beat
            note_end_time = start_time + (note["start"] + note["duration"]) * seconds_per_beat
            start_ppq = self._ppq_from_time(take, note_start_time)
            end_ppq = self._ppq_from_time(take, note_end_time)
            self._insert_midi_note(take, start_ppq, end_ppq, note)
            inserted.append({
                "pitch": note["pitch"],
                "name": _midi_note_name(note["pitch"]),
                "start_beat": note["start"],
                "duration_beats": note["duration"],
                "velocity": note["velocity"],
                "channel": note["channel"],
            })
        sort = getattr(self.rpr, "MIDI_Sort", None)
        if callable(sort):
            sort(take)
        update_arrange = getattr(self.rpr, "UpdateArrange", None)
        if callable(update_arrange):
            update_arrange()
        return {
            "track": self.track_info(track, include_fx=False),
            "start_time": start_time,
            "end_time": item_end,
            "tempo": tempo,
            "note_count": len(inserted),
            "notes": inserted,
        }

    def _midi_target_track(self, payload: dict):
        selector = {"index": payload.get("track_index"), "name": payload.get("track_name")}
        if selector["index"] is not None or selector["name"]:
            return self.find_track(selector)
        return self.selected_or_first_track()

    def _tempo_for_midi(self, payload: dict) -> float:
        tempo = _float_or_none(payload.get("tempo") or payload.get("bpm"))
        if tempo and tempo > 0:
            return tempo
        master_tempo = getattr(self.rpr, "Master_GetTempo", None)
        if callable(master_tempo):
            try:
                tempo = float(master_tempo())
                if tempo > 0:
                    return tempo
            except Exception:
                pass
        return 120.0

    def _create_midi_item(self, track, start_time: float, end_time: float):
        create_item = getattr(self.rpr, "CreateNewMIDIItemInProj", None)
        if not callable(create_item):
            raise ReaperBridgeError("This Reaper bridge cannot create MIDI items.")
        result = create_item(track, float(start_time), float(end_time), False)
        item = _first_object(result)
        if item is None:
            raise ReaperBridgeError("Reaper did not return a MIDI item after CreateNewMIDIItemInProj.")
        return item

    def _active_take(self, item):
        for function_name in ("GetActiveTake", "GetMediaItemTake"):
            func = getattr(self.rpr, function_name, None)
            if not callable(func):
                continue
            try:
                take = func(item) if function_name == "GetActiveTake" else func(item, 0)
                take = _first_object(take)
                if take is not None:
                    return take
            except Exception:
                continue
        raise ReaperBridgeError("Could not get MIDI take from newly created item.")

    def _ppq_from_time(self, take, project_time: float) -> float:
        converter = getattr(self.rpr, "MIDI_GetPPQPosFromProjTime", None)
        if not callable(converter):
            raise ReaperBridgeError("This Reaper bridge cannot convert project time to MIDI PPQ.")
        return float(converter(take, float(project_time)))

    def _insert_midi_note(self, take, start_ppq: float, end_ppq: float, note: dict) -> None:
        insert_note = getattr(self.rpr, "MIDI_InsertNote", None)
        if not callable(insert_note):
            raise ReaperBridgeError("This Reaper bridge cannot insert MIDI notes.")
        insert_note(
            take,
            bool(note.get("selected", False)),
            bool(note.get("muted", False)),
            float(start_ppq),
            float(end_ppq),
            int(note["channel"]),
            int(note["pitch"]),
            int(note["velocity"]),
            True,
        )

    def media_items(self, payload: dict) -> dict:
        action = str(payload.get("action") or "list").strip().casefold()
        if action == "list":
            return {"items": self.list_media_items(payload), "count": len(self.list_media_items(payload))}
        if action in {"create", "add"}:
            track = self.find_track({"index": payload.get("track_index", payload.get("index")), "name": payload.get("track_name")})
            item = self._create_media_item(track, payload)
            return {"item": self.media_item_info(item, track=track)}
        if action in {"set", "update", "select"}:
            track, item = self.find_media_item(payload)
            updates = dict(payload.get("updates") or {})
            for key in ("position", "length", "volume", "mute", "selected", "snap_offset", "fade_in", "fade_out"):
                if key in payload:
                    updates[key] = payload[key]
            return {"item": self.set_media_item(item, updates, track=track), "applied": updates}
        if action in {"delete", "remove"}:
            track, item = self.find_media_item(payload)
            delete_item = getattr(self.rpr, "DeleteTrackMediaItem", None)
            if not callable(delete_item):
                raise ReaperBridgeError("This Reaper bridge cannot delete media items.")
            delete_item(track, item)
            return {"deleted": True}
        raise ReaperBridgeError(f"Unsupported media_items action: {action}")

    def list_media_items(self, payload: dict | None = None) -> list[dict]:
        self.connect()
        payload = payload or {}
        track_filter = payload.get("track_index")
        items = []
        for track_index in range(self.track_count()):
            if track_filter is not None and int(track_filter) != track_index:
                continue
            track = self.get_track(track_index)
            count = int(self.rpr.CountTrackMediaItems(track))
            for item_index in range(count):
                item = self.rpr.GetTrackMediaItem(track, item_index)
                items.append(self.media_item_info(item, track=track, track_index=track_index, item_index=item_index))
        return items

    def media_item_info(self, item, track=None, track_index: int | None = None, item_index: int | None = None) -> dict:
        info = {
            "track_index": track_index,
            "item_index": item_index,
            "position": self._get_item_value(item, "D_POSITION"),
            "length": self._get_item_value(item, "D_LENGTH"),
            "end": self._get_item_value(item, "D_POSITION") + self._get_item_value(item, "D_LENGTH"),
            "volume": self._get_item_value(item, "D_VOL"),
            "mute": bool(self._get_item_value(item, "B_MUTE")),
            "selected": bool(self._get_item_value(item, "B_UISEL")),
            "snap_offset": self._get_item_value(item, "D_SNAPOFFSET"),
            "fade_in": self._get_item_value(item, "D_FADEINLEN"),
            "fade_out": self._get_item_value(item, "D_FADEOUTLEN"),
        }
        if track is not None:
            info["track_name"] = self.track_name(track)
        take = self._item_take(item, active=True)
        if take is not None:
            info["take"] = self.take_info(take, include_midi=False)
        return info

    def find_media_item(self, payload: dict):
        track = self.find_track({"index": payload.get("track_index"), "name": payload.get("track_name")})
        item_index = int(payload.get("item_index", payload.get("index", 0)) or 0)
        count = int(self.rpr.CountTrackMediaItems(track))
        if item_index < 0 or item_index >= count:
            raise ReaperBridgeError(f"Media item index out of range: {item_index}")
        return track, self.rpr.GetTrackMediaItem(track, item_index)

    def _create_media_item(self, track, payload: dict):
        add_item = getattr(self.rpr, "AddMediaItemToTrack", None)
        if not callable(add_item):
            raise ReaperBridgeError("This Reaper bridge cannot create media items.")
        item = add_item(track)
        item = _first_object(item)
        self.set_media_item(item, payload, track=track)
        return item

    def set_media_item(self, item, updates: dict, track=None) -> dict:
        mapping = {
            "position": "D_POSITION",
            "length": "D_LENGTH",
            "volume": "D_VOL",
            "mute": "B_MUTE",
            "selected": "B_UISEL",
            "snap_offset": "D_SNAPOFFSET",
            "fade_in": "D_FADEINLEN",
            "fade_out": "D_FADEOUTLEN",
        }
        if "select" in updates and "selected" not in updates:
            updates["selected"] = updates["select"]
        for field, key in mapping.items():
            if field not in updates:
                continue
            value = updates[field]
            if field in {"mute", "selected"}:
                value = 1 if bool(value) else 0
            self.rpr.SetMediaItemInfo_Value(item, key, float(value))
        update_item = getattr(self.rpr, "UpdateItemInProject", None)
        if callable(update_item):
            update_item(item)
        return self.media_item_info(item, track=track)

    def _get_item_value(self, item, key: str) -> float:
        return float(self.rpr.GetMediaItemInfo_Value(item, key))

    def takes(self, payload: dict) -> dict:
        action = str(payload.get("action") or "list").strip().casefold()
        track, item = self.find_media_item(payload)
        if action == "list":
            count = int(self.rpr.CountTakes(item)) if callable(getattr(self.rpr, "CountTakes", None)) else 1
            takes = []
            for index in range(count):
                take = self._item_take(item, index=index)
                if take is not None:
                    takes.append(self.take_info(take, index=index, include_midi=bool(payload.get("include_midi", False))))
            return {"takes": takes, "count": len(takes)}
        take = self._item_take(item, index=payload.get("take_index"), active=True)
        if take is None:
            raise ReaperBridgeError("Take not found.")
        if action in {"set", "rename", "update"}:
            if "name" in payload or "new_name" in payload:
                set_name = getattr(self.rpr, "GetSetMediaItemTakeInfo_String", None)
                if not callable(set_name):
                    raise ReaperBridgeError("This Reaper bridge cannot rename takes.")
                set_name(take, "P_NAME", str(payload.get("new_name") or payload.get("name")), True)
            return {"take": self.take_info(take, include_midi=bool(payload.get("include_midi", False)))}
        raise ReaperBridgeError(f"Unsupported takes action: {action}")

    def _item_take(self, item, index: int | None = None, active: bool = False):
        if active or index is None:
            get_active = getattr(self.rpr, "GetActiveTake", None)
            if callable(get_active):
                return _first_object(get_active(item))
        get_take = getattr(self.rpr, "GetMediaItemTake", None)
        if callable(get_take):
            return _first_object(get_take(item, int(index or 0)))
        return None

    def take_info(self, take, index: int | None = None, include_midi: bool = False) -> dict:
        name = ""
        get_name = getattr(self.rpr, "GetTakeName", None)
        if callable(get_name):
            try:
                name = _first_string(get_name(take))
            except Exception:
                name = ""
        info = {"index": index, "name": name, "is_midi": bool(self.rpr.TakeIsMIDI(take)) if callable(getattr(self.rpr, "TakeIsMIDI", None)) else None}
        if include_midi and info["is_midi"]:
            info["midi"] = self.midi_summary(take)
        return info

    def midi_summary(self, take) -> dict:
        count_events = getattr(self.rpr, "MIDI_CountEvts", None)
        if not callable(count_events):
            return {}
        result = count_events(take, 0, 0, 0)
        numbers = [int(item) for item in result if isinstance(item, int)] if _is_result_sequence(result) else [int(result)]
        return {"note_count": numbers[-3] if len(numbers) >= 3 else None, "cc_count": numbers[-2] if len(numbers) >= 2 else None, "text_sysex_count": numbers[-1] if numbers else None}

    def track_fx(self, payload: dict) -> dict:
        self.connect()
        action = str(payload.get("action") or "list").strip().casefold()
        track = self.find_track({"index": payload.get("track_index", payload.get("index")), "name": payload.get("track_name")})
        if action == "list":
            fx = [self.fx_info(track, index, include_params=bool(payload.get("include_params", False))) for index in range(int(self.rpr.TrackFX_GetCount(track)))]
            return {"fx": fx, "count": len(fx)}
        if action in {"add", "insert"}:
            name = str(payload.get("name") or payload.get("fx_name") or "").strip()
            if not name:
                raise ReaperBridgeError("track_fx add requires 'name'.")
            index = int(self.rpr.TrackFX_AddByName(track, name, False, int(payload.get("instantiate", -1))))
            return {"fx": self.fx_info(track, index, include_params=bool(payload.get("include_params", False))), "index": index}
        fx_index = int(payload.get("fx_index", payload.get("fx", 0)) or 0)
        if action in {"enable", "disable", "bypass"}:
            enabled = action == "enable" if "enabled" not in payload else bool(payload.get("enabled"))
            self.rpr.TrackFX_SetEnabled(track, fx_index, enabled)
            return {"fx": self.fx_info(track, fx_index)}
        if action in {"set_param", "param"}:
            param_index = int(payload.get("param_index", payload.get("param", 0)) or 0)
            value = float(payload.get("value"))
            self.rpr.TrackFX_SetParam(track, fx_index, param_index, value)
            return {"fx": self.fx_info(track, fx_index, include_params=True), "param_index": param_index, "value": value}
        raise ReaperBridgeError(f"Unsupported track_fx action: {action}")

    def fx_info(self, track, fx_index: int, include_params: bool = False) -> dict:
        name = _first_string(self.rpr.TrackFX_GetFXName(track, fx_index, "", 4096)) if callable(getattr(self.rpr, "TrackFX_GetFXName", None)) else ""
        info = {"index": fx_index, "name": name, "enabled": bool(self.rpr.TrackFX_GetEnabled(track, fx_index)) if callable(getattr(self.rpr, "TrackFX_GetEnabled", None)) else None}
        if include_params and callable(getattr(self.rpr, "TrackFX_GetNumParams", None)):
            params = []
            for param_index in range(int(self.rpr.TrackFX_GetNumParams(track, fx_index))):
                param_name = _first_string(self.rpr.TrackFX_GetParamName(track, fx_index, param_index, "", 4096)) if callable(getattr(self.rpr, "TrackFX_GetParamName", None)) else ""
                param_value = None
                if callable(getattr(self.rpr, "TrackFX_GetParam", None)):
                    try:
                        param_value = _last_number(self.rpr.TrackFX_GetParam(track, fx_index, param_index, 0.0, 0.0))
                    except Exception:
                        param_value = None
                params.append({"index": param_index, "name": param_name, "value": param_value})
            info["params"] = params
        return info

    def render(self, mode: str = "recent", command_id: Any = None, settings: dict | None = None) -> dict:
        applied_settings = None
        if settings:
            applied_settings = self._set_render_settings({"action": "set_render_settings", **settings})
        mode = str(mode or "recent").strip().casefold()
        if command_id is not None:
            return {"mode": "action", "settings": applied_settings, **self.execute_action(command_id)}
        if mode in {"recent", "last", "current_settings"}:
            return {"mode": mode, "settings": applied_settings, **self.execute_action("render_recent")}
        if mode in {"project", "dialog"}:
            return {"mode": mode, "settings": applied_settings, **self.execute_action("render_project")}
        raise ReaperBridgeError(f"Unsupported render mode: {mode}")

    def markers_regions(self) -> dict:
        self.connect()
        enum_markers3 = getattr(self.rpr, "EnumProjectMarkers3", None)
        enum_markers = enum_markers3 if callable(enum_markers3) else getattr(self.rpr, "EnumProjectMarkers", None)
        count_markers = getattr(self.rpr, "CountProjectMarkers", None)
        if not callable(enum_markers):
            raise ReaperBridgeError("This Reaper bridge cannot enumerate markers or regions.")
        total = 0
        if callable(count_markers):
            try:
                count_result = count_markers(0, 0, 0)
                total = _parse_project_marker_count(count_result)
            except Exception:
                total = 0
        items = []
        index = 0
        misses = 0
        while index < max(total + 8, 64) and misses < 8:
            if callable(enum_markers3):
                result = enum_markers(0, index, False, 0.0, 0.0, "", 0, 0)
            else:
                result = enum_markers(index, False, 0.0, 0.0, "", 0)
            marker = _parse_marker_result(result, index)
            if marker is None:
                misses += 1
            else:
                misses = 0
                items.append(marker)
            index += 1
        return {"count": len(items), "items": items}

    def project_markers(self, payload: dict) -> dict:
        self.connect()
        action = str(payload.get("action") or "list").strip().casefold()
        if action == "list":
            return self.markers_regions()
        if action in {"add", "create"}:
            add_marker = getattr(self.rpr, "AddProjectMarker2", None) or getattr(self.rpr, "AddProjectMarker", None)
            if not callable(add_marker):
                raise ReaperBridgeError("This Reaper bridge cannot add markers or regions.")
            is_region = bool(payload.get("is_region", payload.get("region", False)))
            position = float(payload.get("position", payload.get("start", self.cursor_position())) or 0.0)
            end = float(payload.get("end", position) or position)
            name = str(payload.get("name") or "")
            marker_id = int(payload.get("id", payload.get("marker_id", -1)) or -1)
            color = int(payload.get("color", 0) or 0)
            if add_marker.__name__ == "AddProjectMarker2":
                result = add_marker(0, is_region, position, end, name, marker_id, color)
            else:
                result = add_marker(0, is_region, position, end, name, marker_id)
            return {"created": True, "id": _last_number(result), "markers": self.markers_regions()}
        if action in {"delete", "remove"}:
            delete_marker = getattr(self.rpr, "DeleteProjectMarker", None)
            if not callable(delete_marker):
                raise ReaperBridgeError("This Reaper bridge cannot delete markers or regions.")
            marker_id = int(payload.get("id", payload.get("marker_id")))
            is_region = bool(payload.get("is_region", payload.get("region", False)))
            delete_marker(0, marker_id, is_region)
            return {"deleted": True, "id": marker_id}
        raise ReaperBridgeError(f"Unsupported project_markers action: {action}")

    def project_settings(self, payload: dict) -> dict:
        self.connect()
        action = str(payload.get("action") or "get").strip().casefold()
        if action in {"get", "info", "status"}:
            result = self.project_info(include_tracks=bool(payload.get("include_tracks", False)))
            get_loop = getattr(self.rpr, "GetSet_LoopTimeRange", None)
            if callable(get_loop):
                try:
                    loop_result = get_loop(False, False, 0.0, 0.0, False)
                    numbers = [float(item) for item in loop_result if isinstance(item, (int, float))] if _is_result_sequence(loop_result) else []
                    if len(numbers) >= 2:
                        result["time_selection"] = {"start": numbers[-2], "end": numbers[-1]}
                except Exception:
                    pass
            if bool(payload.get("include_project_info", payload.get("include_render", False))):
                result["project_info"] = self._project_info_snapshot(payload.get("fields"))
            if bool(payload.get("include_strings", payload.get("include_render", False))):
                result["project_strings"] = self._project_string_snapshot(payload.get("string_fields"))
            return result
        if action in {"get_info", "get_project_info", "get_value", "read_info"}:
            desc = self._project_info_desc(payload)
            return {"desc": desc, "value": self._get_project_info_value(desc)}
        if action in {"set_info", "set_project_info", "set_value", "write_info"}:
            desc = self._project_info_desc(payload)
            value = self._project_info_input_value(desc, payload.get("value", payload.get("new_value", 0.0)))
            previous = self._get_project_info_value(desc)
            current = self._set_project_info_value(desc, value)
            return {"desc": desc, "previous": previous, "value": current}
        if action in {"get_string", "get_project_string", "read_string"}:
            desc = self._project_string_desc(payload)
            query_value = str(payload.get("value", payload.get("query", "")) or "")
            return {"desc": desc, "value": self._get_project_string_value(desc, query_value=query_value)}
        if action in {"set_string", "set_project_string", "write_string"}:
            desc = self._project_string_desc(payload)
            value = str(payload.get("value", payload.get("new_value", "")) or "")
            previous = None if bool(payload.get("skip_previous", False)) else self._get_project_string_value(desc)
            current = self._set_project_string_value(desc, value)
            return {"desc": desc, "previous": previous, "value": current}
        if action in {"get_render_settings", "render_settings"}:
            return {
                "numeric": self._project_info_snapshot(payload.get("fields") or _default_render_info_fields()),
                "strings": self._project_string_snapshot(payload.get("string_fields") or _default_render_string_fields()),
            }
        if action in {"set_render_settings", "configure_render", "render_config"}:
            return self._set_render_settings(payload)
        if action in {"set_identity", "identity"}:
            applied = {}
            if "title" in payload or "project_title" in payload:
                applied["project_title"] = self._set_project_string_value("PROJECT_TITLE", str(payload.get("project_title", payload.get("title", ""))))
            if "author" in payload or "project_author" in payload:
                applied["project_author"] = self._set_project_string_value("PROJECT_AUTHOR", str(payload.get("project_author", payload.get("author", ""))))
            if not applied:
                raise ReaperBridgeError("set_identity requires title/project_title or author/project_author.")
            return {"applied": applied}
        if action in {"set_sample_rate", "sample_rate"}:
            sample_rate = float(payload.get("sample_rate", payload.get("srate", payload.get("project_srate", 0))) or 0)
            use_sample_rate = bool(payload.get("enabled", payload.get("use", sample_rate > 0)))
            previous = self._project_info_snapshot(["PROJECT_SRATE", "PROJECT_SRATE_USE"])
            if sample_rate > 0:
                self._set_project_info_value("PROJECT_SRATE", sample_rate)
            self._set_project_info_value("PROJECT_SRATE_USE", 1.0 if use_sample_rate else 0.0)
            return {"previous": previous, "current": self._project_info_snapshot(["PROJECT_SRATE", "PROJECT_SRATE_USE"])}
        if action in {"set_cursor", "cursor"}:
            position = _float_or_none(payload.get("position", payload.get("time")))
            if position is None:
                raise ReaperBridgeError("set_cursor requires 'position'.")
            self.rpr.SetEditCurPos(position, bool(payload.get("move_view", True)), bool(payload.get("seek_play", False)))
            return self.project_info(include_tracks=False)
        if action in {"set_time_selection", "time_selection", "loop"}:
            setter = getattr(self.rpr, "GetSet_LoopTimeRange", None)
            if not callable(setter):
                raise ReaperBridgeError("This Reaper bridge cannot set time selection.")
            start = float(payload.get("start", 0.0) or 0.0)
            end = float(payload.get("end", start) or start)
            setter(True, bool(payload.get("loop", False)), start, end, bool(payload.get("allowautoseek", False)))
            return {"time_selection": {"start": start, "end": end}, "loop": bool(payload.get("loop", False))}
        if action in {"set_tempo", "tempo"}:
            set_tempo = getattr(self.rpr, "SetCurrentBPM", None)
            if not callable(set_tempo):
                raise ReaperBridgeError("This Reaper bridge cannot set tempo.")
            tempo = float(payload.get("tempo", payload.get("bpm")))
            set_tempo(0, tempo, True)
            return self.project_info(include_tracks=False)
        if action in {"save", "save_project"}:
            return self.execute_action("save_project")
        raise ReaperBridgeError(f"Unsupported project_settings action: {action}")

    def _project_info_desc(self, payload: dict) -> str:
        raw = str(payload.get("desc") or payload.get("key") or payload.get("field") or "").strip()
        desc = self.PROJECT_INFO_FIELDS.get(raw.casefold(), raw.upper())
        if not desc:
            raise ReaperBridgeError("Project info action requires desc/key/field.")
        return desc

    def _project_string_desc(self, payload: dict) -> str:
        raw = str(payload.get("desc") or payload.get("key") or payload.get("field") or "").strip()
        desc = self.PROJECT_STRING_FIELDS.get(raw.casefold(), raw.upper())
        if not desc:
            raise ReaperBridgeError("Project string action requires desc/key/field.")
        return desc

    def _get_project_info_value(self, desc: str) -> float:
        getter = getattr(self.rpr, "GetSetProjectInfo", None)
        if not callable(getter):
            raise ReaperBridgeError("This Reaper bridge cannot access GetSetProjectInfo.")
        return float(getter(0, str(desc), 0.0, False))

    def _set_project_info_value(self, desc: str, value: float) -> float:
        setter = getattr(self.rpr, "GetSetProjectInfo", None)
        if not callable(setter):
            raise ReaperBridgeError("This Reaper bridge cannot access GetSetProjectInfo.")
        setter(0, str(desc), float(value), True)
        return self._get_project_info_value(desc)

    def _get_project_string_value(self, desc: str, query_value: str = "") -> str:
        getter = getattr(self.rpr, "GetSetProjectInfo_String", None)
        if not callable(getter):
            raise ReaperBridgeError("This Reaper bridge cannot access GetSetProjectInfo_String.")
        return _first_string(getter(0, str(desc), str(query_value or ""), False))

    def _set_project_string_value(self, desc: str, value: str) -> str:
        setter = getattr(self.rpr, "GetSetProjectInfo_String", None)
        if not callable(setter):
            raise ReaperBridgeError("This Reaper bridge cannot access GetSetProjectInfo_String.")
        result = setter(0, str(desc), str(value), True)
        if not _bool_result(result):
            raise ReaperBridgeError(f"Reaper rejected project string setting: {desc}")
        return self._get_project_string_value(desc)

    def _project_info_snapshot(self, fields=None) -> dict:
        selected = _normalize_project_fields(fields, _default_project_info_fields())
        return {field: self._get_project_info_value(field) for field in selected}

    def _project_string_snapshot(self, fields=None) -> dict:
        selected = _normalize_project_fields(fields, _default_project_string_fields())
        return {field: self._get_project_string_value(field) for field in selected}

    def _set_render_settings(self, payload: dict) -> dict:
        updates = dict(payload.get("updates") or {})
        updates.update(self._render_numeric_updates(payload))
        for key in (
            "render_settings", "render_bounds", "render_boundsflag", "render_channels", "render_sample_rate",
            "render_srate", "render_start", "render_startpos", "render_end", "render_endpos",
            "render_tail_flags", "render_tailflag", "render_tail_ms", "render_tailms", "render_add_to_project",
            "render_addtoproj", "render_dither", "render_normalize", "render_normalize_target", "render_brickwall",
            "render_fade_in", "render_fadein", "render_fade_out", "render_fadeout", "render_fade_in_shape",
            "render_fadeinshape", "render_fade_out_shape", "render_fadeoutshape", "render_fade_lpf", "render_fadelpf",
            "render_pad_start", "render_padstart", "render_pad_end", "render_padend", "render_trim_start",
            "render_trimstart", "render_trim_end", "render_trimend", "render_delay",
        ):
            if key in payload:
                updates[key] = payload[key]
        string_updates = dict(payload.get("string_updates") or {})
        string_updates.update(self._render_string_updates(payload))
        for key in (
            "render_file", "render_directory", "render_path", "render_pattern", "render_name", "file_name_pattern", "filename_pattern",
            "render_extra_file_dir", "render_extra_directory",
            "render_metadata", "render_format", "render_format2",
        ):
            if key in payload:
                string_updates[key] = payload[key]
        for key in ("render_format", "render_format2"):
            if key in string_updates:
                string_updates[key] = self._render_format_value(string_updates[key])
        if not updates and not string_updates:
            raise ReaperBridgeError("set_render_settings requires at least one render setting field.")
        numeric_fields = [self.PROJECT_INFO_FIELDS.get(str(key).casefold(), str(key).upper()) for key in updates]
        string_fields = [self.PROJECT_STRING_FIELDS.get(str(key).casefold(), str(key).upper()) for key in string_updates]
        previous = {
            "numeric": self._project_info_snapshot(numeric_fields) if numeric_fields else {},
            "strings": self._project_string_snapshot(string_fields) if string_fields else {},
        }
        applied = {"numeric": {}, "strings": {}}
        for key, value in updates.items():
            desc = self.PROJECT_INFO_FIELDS.get(str(key).casefold(), str(key).upper())
            applied["numeric"][desc] = self._set_project_info_value(desc, self._project_info_input_value(desc, value))
        for key, value in string_updates.items():
            desc = self.PROJECT_STRING_FIELDS.get(str(key).casefold(), str(key).upper())
            if desc == "RENDER_FILE" and value:
                os.makedirs(str(value), exist_ok=True)
            applied["strings"][desc] = self._set_project_string_value(desc, str(value))
        return {"previous": previous, "applied": applied}

    def _render_numeric_updates(self, payload: dict) -> dict:
        updates = {}
        mode = _first_present(payload, "render_mode", "mode", "render_source", "source")
        settings_flags = payload.get("render_flags", payload.get("render_settings_flags", payload.get("flags")))
        flag_values = {key: payload[key] for key in self.RENDER_SETTINGS_FLAGS if key in payload}
        if mode is not None or settings_flags is not None or flag_values:
            base = self._render_settings_value(mode, current=None if mode is not None else self._safe_project_info("RENDER_SETTINGS"))
            updates["render_settings"] = self._apply_named_flags(base, settings_flags, self.RENDER_SETTINGS_FLAGS)
            updates["render_settings"] = self._apply_flag_mapping(updates["render_settings"], flag_values, self.RENDER_SETTINGS_FLAGS)
        if "bounds" in payload:
            updates["render_bounds"] = payload["bounds"]
        if "channels" in payload:
            updates["render_channels"] = payload["channels"]
        if "sample_rate" in payload or "srate" in payload:
            updates["render_sample_rate"] = payload.get("sample_rate", payload.get("srate"))
        if "start" in payload:
            updates["render_start"] = payload["start"]
        if "end" in payload:
            updates["render_end"] = payload["end"]
        if "tail" in payload or "tail_contexts" in payload or "tail_flags" in payload:
            tail_value = payload.get("tail_flags", payload.get("tail_contexts", payload.get("tail")))
            updates["render_tail_flags"] = self._tail_flag_value(tail_value)
        if "tail_seconds" in payload:
            updates["render_tail_ms"] = float(payload["tail_seconds"] or 0) * 1000.0
        if "add_to_project" in payload or "skip_silent" in payload or "render_add_flags" in payload:
            value = self._apply_named_flags(0, payload.get("render_add_flags"), self.RENDER_ADDTOPROJ_FLAGS)
            value = self._apply_flag_mapping(value, {"add_to_project": payload.get("add_to_project"), "skip_silent": payload.get("skip_silent")}, self.RENDER_ADDTOPROJ_FLAGS)
            updates["render_add_to_project"] = value
        if "dither" in payload or "noise_shaping" in payload or "dither_flags" in payload or "disable_dither" in payload:
            value = self._apply_named_flags(0, payload.get("dither_flags"), self.RENDER_DITHER_FLAGS)
            value = self._apply_flag_mapping(value, {"dither": payload.get("dither"), "noise_shaping": payload.get("noise_shaping"), "disable_all": payload.get("disable_dither")}, self.RENDER_DITHER_FLAGS)
            updates["render_dither"] = value
        self._apply_normalize_updates(payload, updates)
        if "delay_seconds" in payload:
            updates["render_delay"] = payload["delay_seconds"]
            updates["render_settings"] = int(updates.get("render_settings", self._safe_project_info("RENDER_SETTINGS"))) | self.RENDER_SETTINGS_FLAGS["delay_render_start"]
        return updates

    def _render_string_updates(self, payload: dict) -> dict:
        updates = {}
        for key, target in (
            ("directory", "render_directory"), ("path", "render_directory"), ("output_dir", "render_directory"),
            ("output_path", "render_directory"), ("pattern", "render_pattern"), ("name", "render_pattern"),
            ("filename", "render_pattern"), ("file_name", "render_pattern"), ("extra_directory", "render_extra_file_dir"),
            ("format", "render_format"), ("secondary_format", "render_format2"),
        ):
            if key in payload:
                updates[target] = payload[key]
        for key in ("render_format", "render_format2"):
            if key in updates:
                updates[key] = self._render_format_value(updates[key])
        return updates

    def _render_settings_value(self, value: Any, current: float | None = None) -> int:
        if value is None:
            return int(current or 0)
        if isinstance(value, str):
            key = _slug(value)
            if key in self.RENDER_MODE_VALUES:
                return int(self.RENDER_MODE_VALUES[key])
        return int(float(value or 0))

    def _tail_flag_value(self, value: Any) -> int:
        if isinstance(value, bool):
            return self.RENDER_TAIL_FLAGS["entire_project"] if value else 0
        return self._apply_named_flags(0, value, self.RENDER_TAIL_FLAGS)

    def _apply_normalize_updates(self, payload: dict, updates: dict) -> None:
        normalize_payload = payload.get("normalize") if isinstance(payload.get("normalize"), dict) else {}
        merged = {**normalize_payload, **payload}
        has_normalize = any(key in merged for key in (
            "normalize", "normalize_mode", "normalize_type", "normalize_scope", "limit_scope", "normalize_target",
            "normalize_target_db", "brickwall", "brickwall_db", "true_peak", "only_too_loud", "only_too_quiet",
            "fade_in", "fade_in_ms", "fade_out", "fade_out_ms", "pad_start", "pad_start_ms", "pad_end",
            "pad_end_ms", "trim_start", "trim_start_db", "trim_end", "trim_end_db",
        ))
        if not has_normalize:
            return
        enabled = bool(merged.get("normalize", True))
        if not enabled:
            updates["render_normalize"] = 0
            return
        value = 1
        mode = merged.get("normalize_mode", merged.get("normalize_type"))
        if mode is not None:
            value |= self.RENDER_NORMALIZE_MODES.get(_slug(mode), int(float(mode)) if not isinstance(mode, str) else 0)
        scope = merged.get("normalize_scope")
        if scope is not None:
            value = self._apply_named_flags(value, scope, self.RENDER_NORMALIZE_SCOPE_FLAGS)
        limit_scope = merged.get("limit_scope")
        if limit_scope is not None:
            value = self._apply_named_flags(value, limit_scope, self.RENDER_LIMIT_SCOPE_FLAGS)
        if merged.get("true_peak") or merged.get("brickwall_true_peak"):
            value |= 128
        elif merged.get("brickwall"):
            value |= 64
        if merged.get("only_too_loud"):
            value |= 256
        if merged.get("only_too_quiet"):
            value |= 2048
        if merged.get("disable_postprocessing"):
            value |= 4 << 16
        mono_adjust = merged.get("mono_adjust_db")
        if mono_adjust is not None:
            value |= 16 | ((8 << 16) if float(mono_adjust) > 0 else 0)
        for field, flag, db_key, linear_key in (
            ("render_fade_in", 512, None, "fade_in"), ("render_fade_out", 1024, None, "fade_out"),
            ("render_pad_start", 1 << 16, None, "pad_start"), ("render_pad_end", 2 << 16, None, "pad_end"),
            ("render_trim_start", 16384, "trim_start_db", "trim_start"), ("render_trim_end", 32768, "trim_end_db", "trim_end"),
        ):
            ms_key = f"{linear_key}_ms"
            if db_key and db_key in merged:
                value |= flag
                updates[field] = _db_to_linear(merged[db_key])
            elif ms_key in merged:
                value |= flag
                updates[field] = float(merged[ms_key] or 0) / 1000.0
            elif linear_key in merged:
                value |= flag
                updates[field] = merged[linear_key]
        if "normalize_target_db" in merged:
            updates["render_normalize_target"] = _db_to_linear(merged["normalize_target_db"])
        elif "normalize_target" in merged:
            updates["render_normalize_target"] = merged["normalize_target"]
        if "brickwall_db" in merged:
            value |= 64
            updates["render_brickwall"] = _db_to_linear(merged["brickwall_db"])
        elif "brickwall_target" in merged:
            value |= 64
            updates["render_brickwall"] = merged["brickwall_target"]
        for key, target in (("fade_in_shape", "render_fade_in_shape"), ("fade_out_shape", "render_fade_out_shape"), ("fade_lpf", "render_fade_lpf")):
            if key in merged:
                updates[target] = merged[key]
        updates["render_normalize"] = value

    def _apply_named_flags(self, base: int, value: Any, mapping: dict[str, int]) -> int:
        if value is None:
            return int(base)
        if isinstance(value, dict):
            return self._apply_flag_mapping(base, value, mapping)
        if isinstance(value, (list, tuple, set)):
            result = int(base)
            for item in value:
                result = self._apply_named_flags(result, item, mapping)
            return result
        if isinstance(value, str):
            key = _slug(value)
            if key in mapping:
                return int(base) | int(mapping[key])
        if isinstance(value, bool):
            return int(base)
        return int(base) | int(float(value or 0))

    def _apply_flag_mapping(self, base: int, values: dict, mapping: dict[str, int]) -> int:
        result = int(base)
        for key, enabled in values.items():
            if enabled is None:
                continue
            flag = mapping.get(_slug(key))
            if flag is None:
                continue
            if bool(enabled):
                result |= int(flag)
            else:
                result &= ~int(flag)
        return result

    def _render_format_value(self, value: Any) -> str:
        text = str(value or "")
        return self.RENDER_FORMAT_ALIASES.get(_slug(text), text)

    def _safe_project_info(self, desc: str) -> float:
        try:
            return self._get_project_info_value(desc)
        except Exception:
            return 0.0

    def _project_info_input_value(self, desc: str, value: Any) -> float:
        if str(desc).upper() == "RENDER_BOUNDSFLAG" and isinstance(value, str):
            key = value.strip().casefold().replace(" ", "_").replace("-", "_")
            if key in self.RENDER_BOUNDS_VALUES:
                return float(self.RENDER_BOUNDS_VALUES[key])
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if str(desc).upper() in {"RENDER_NORMALIZE_TARGET", "RENDER_BRICKWALL", "RENDER_TRIMSTART", "RENDER_TRIMEND"} and isinstance(value, str) and value.strip().endswith("db"):
            return _db_to_linear(value.strip()[:-2])
        return float(value or 0.0)

    def ext_state(self, payload: dict) -> dict:
        self.connect()
        action = str(payload.get("action") or "get").strip().casefold()
        project_scope = bool(payload.get("project", False)) or str(payload.get("scope") or "").casefold() in {"project", "proj"}
        section = str(payload.get("section") or payload.get("extname") or "AudioMate").strip()
        key = str(payload.get("key") or "").strip()
        if not section:
            raise ReaperBridgeError("ext_state requires a section/extname.")
        if project_scope:
            return self._project_ext_state(action, section, key, payload)
        return self._global_ext_state(action, section, key, payload)

    def _global_ext_state(self, action: str, section: str, key: str, payload: dict) -> dict:
        if action in {"get", "read"}:
            if not key:
                raise ReaperBridgeError("Global ext_state get requires key.")
            return {"scope": "global", "section": section, "key": key, "value": str(self.rpr.GetExtState(section, key))}
        if action in {"set", "write"}:
            if not key:
                raise ReaperBridgeError("Global ext_state set requires key.")
            value = str(payload.get("value", ""))
            self.rpr.SetExtState(section, key, value, bool(payload.get("persist", False)))
            return {"scope": "global", "section": section, "key": key, "value": value, "persist": bool(payload.get("persist", False))}
        if action in {"delete", "remove"}:
            if not key:
                raise ReaperBridgeError("Global ext_state delete requires key.")
            self.rpr.DeleteExtState(section, key, bool(payload.get("persist", False)))
            return {"scope": "global", "section": section, "key": key, "deleted": True}
        if action in {"has", "exists"}:
            if not key:
                raise ReaperBridgeError("Global ext_state has requires key.")
            return {"scope": "global", "section": section, "key": key, "exists": bool(self.rpr.HasExtState(section, key))}
        raise ReaperBridgeError(f"Unsupported global ext_state action: {action}")

    def _project_ext_state(self, action: str, section: str, key: str, payload: dict) -> dict:
        if action in {"list", "enum", "enumerate"}:
            enum_state = getattr(self.rpr, "EnumProjExtState", None)
            if not callable(enum_state):
                raise ReaperBridgeError("This Reaper bridge cannot enumerate project ext state.")
            values = []
            index = 0
            while index < int(payload.get("limit", 512) or 512):
                result = enum_state(0, section, index, "", 4096, "", 65536)
                if not _bool_result(result):
                    break
                strings = [item for item in result if isinstance(item, str)] if _is_result_sequence(result) else []
                values.append({"index": index, "key": strings[-2] if len(strings) >= 2 else "", "value": strings[-1] if strings else ""})
                index += 1
            return {"scope": "project", "section": section, "values": values, "count": len(values)}
        if not key:
            raise ReaperBridgeError("Project ext_state action requires key except list.")
        if action in {"get", "read"}:
            result = self.rpr.GetProjExtState(0, section, key, "", 65536)
            strings = [item for item in result if isinstance(item, str)] if _is_result_sequence(result) else []
            return {"scope": "project", "section": section, "key": key, "exists": bool(_last_number(result)), "value": strings[-1] if strings else ""}
        if action in {"set", "write"}:
            value = str(payload.get("value", ""))
            size = self.rpr.SetProjExtState(0, section, key, value)
            return {"scope": "project", "section": section, "key": key, "value": value, "size": _last_number(size)}
        if action in {"delete", "remove"}:
            size = self.rpr.SetProjExtState(0, section, key, "")
            return {"scope": "project", "section": section, "key": key, "deleted": True, "size": _last_number(size)}
        raise ReaperBridgeError(f"Unsupported project ext_state action: {action}")

    def track_routing(self, payload: dict) -> dict:
        self.connect()
        action = str(payload.get("action") or "list").strip().casefold()
        track = self.find_track({"index": payload.get("track_index", payload.get("index")), "name": payload.get("track_name")})
        if action == "list":
            categories = payload.get("categories") or [-1, 0, 1]
            routes = []
            for category in categories:
                category = int(category)
                count = int(self.rpr.GetTrackNumSends(track, category))
                for send_index in range(count):
                    routes.append(self._track_send_info(track, category, send_index))
            return {"routes": routes, "count": len(routes)}
        category = int(payload.get("category", 0) or 0)
        if action in {"create", "add"}:
            if category != 0:
                raise ReaperBridgeError("track_routing create currently supports normal track sends with category 0.")
            destination = self.find_track({"index": payload.get("dest_track_index"), "name": payload.get("dest_track_name")})
            index = int(self.rpr.CreateTrackSend(track, destination))
            updates = dict(payload.get("updates") or {})
            for key in ("volume", "volume_db", "pan", "mute", "phase", "mono", "send_mode", "src_chan", "dst_chan", "midi_flags"):
                if key in payload:
                    updates[key] = payload[key]
            if updates:
                self._set_track_send_values(track, category, index, updates)
            return {"created": True, "route": self._track_send_info(track, category, index)}
        send_index = int(payload.get("send_index", payload.get("route_index", 0)) or 0)
        if action in {"set", "update"}:
            updates = dict(payload.get("updates") or {})
            for key in ("volume", "volume_db", "pan", "mute", "phase", "mono", "send_mode", "src_chan", "dst_chan", "midi_flags"):
                if key in payload:
                    updates[key] = payload[key]
            self._set_track_send_values(track, category, send_index, updates)
            return {"route": self._track_send_info(track, category, send_index), "applied": updates}
        if action in {"delete", "remove"}:
            self.rpr.RemoveTrackSend(track, category, send_index)
            return {"deleted": True, "category": category, "send_index": send_index}
        raise ReaperBridgeError(f"Unsupported track_routing action: {action}")

    def _track_send_info(self, track, category: int, send_index: int) -> dict:
        values = {}
        key_map = {
            "mute": "B_MUTE",
            "phase": "B_PHASE",
            "mono": "B_MONO",
            "volume": "D_VOL",
            "pan": "D_PAN",
            "pan_law": "D_PANLAW",
            "send_mode": "I_SENDMODE",
            "src_chan": "I_SRCCHAN",
            "dst_chan": "I_DSTCHAN",
            "midi_flags": "I_MIDIFLAGS",
        }
        for label, key in key_map.items():
            try:
                values[label] = self.rpr.GetTrackSendInfo_Value(track, category, send_index, key)
            except Exception:
                values[label] = None
        name_func = self.rpr.GetTrackReceiveName if category < 0 and callable(getattr(self.rpr, "GetTrackReceiveName", None)) else getattr(self.rpr, "GetTrackSendName", None)
        name = _first_string(name_func(track, send_index, "", 4096)) if callable(name_func) else ""
        return {"category": category, "send_index": send_index, "name": name, **values, "volume_db": _linear_to_db(values.get("volume"))}

    def _set_track_send_values(self, track, category: int, send_index: int, updates: dict) -> None:
        mapping = {
            "volume": "D_VOL",
            "pan": "D_PAN",
            "mute": "B_MUTE",
            "phase": "B_PHASE",
            "mono": "B_MONO",
            "send_mode": "I_SENDMODE",
            "src_chan": "I_SRCCHAN",
            "dst_chan": "I_DSTCHAN",
            "midi_flags": "I_MIDIFLAGS",
        }
        if "volume_db" in updates:
            updates["volume"] = _db_to_linear(float(updates["volume_db"]))
        for field, key in mapping.items():
            if field not in updates:
                continue
            value = updates[field]
            if field in {"mute", "phase", "mono"}:
                value = 1 if bool(value) else 0
            self.rpr.SetTrackSendInfo_Value(track, category, send_index, key, float(value))

    def envelopes(self, payload: dict) -> dict:
        self.connect()
        action = str(payload.get("action") or "list").strip().casefold()
        if action == "list":
            track = self.find_track({"index": payload.get("track_index", payload.get("index")), "name": payload.get("track_name")})
            count = int(self.rpr.CountTrackEnvelopes(track)) if callable(getattr(self.rpr, "CountTrackEnvelopes", None)) else 0
            envelopes = []
            for index in range(count):
                envelope = self.rpr.GetTrackEnvelope(track, index)
                envelopes.append(self._envelope_info(envelope, index=index, include_points=bool(payload.get("include_points", False))))
            return {"envelopes": envelopes, "count": len(envelopes)}
        envelope = self._resolve_envelope(payload)
        if action in {"info", "get"}:
            return self._envelope_info(envelope, include_points=bool(payload.get("include_points", True)))
        if action in {"insert_point", "add_point", "point"}:
            time = float(payload.get("time", payload.get("position", self.cursor_position())) or 0.0)
            value = float(payload.get("value", 1.0))
            shape = int(payload.get("shape", 0) or 0)
            tension = float(payload.get("tension", 0.0) or 0.0)
            selected = bool(payload.get("selected", False))
            no_sort = bool(payload.get("no_sort", False))
            insert_point = getattr(self.rpr, "InsertEnvelopePoint", None)
            if not callable(insert_point):
                raise ReaperBridgeError("This Reaper bridge cannot insert envelope points.")
            insert_point(envelope, time, value, shape, tension, selected, no_sort)
            if not no_sort and callable(getattr(self.rpr, "Envelope_SortPoints", None)):
                self.rpr.Envelope_SortPoints(envelope)
            return {"inserted": True, "envelope": self._envelope_info(envelope, include_points=True)}
        if action in {"set_point", "update_point"}:
            point_index = int(payload.get("point_index", payload.get("index", 0)) or 0)
            self.rpr.SetEnvelopePoint(
                envelope,
                point_index,
                payload.get("time"),
                payload.get("value"),
                payload.get("shape"),
                payload.get("tension"),
                payload.get("selected"),
                bool(payload.get("no_sort", False)),
            )
            if not bool(payload.get("no_sort", False)) and callable(getattr(self.rpr, "Envelope_SortPoints", None)):
                self.rpr.Envelope_SortPoints(envelope)
            return {"updated": True, "point_index": point_index, "envelope": self._envelope_info(envelope, include_points=True)}
        if action in {"delete_point", "remove_point"}:
            point_index = int(payload.get("point_index", payload.get("index", 0)) or 0)
            self.rpr.DeleteEnvelopePointEx(envelope, int(payload.get("autoitem_index", -1) or -1), point_index)
            return {"deleted": True, "point_index": point_index}
        if action in {"sort", "sort_points"}:
            self.rpr.Envelope_SortPoints(envelope)
            return {"sorted": True, "envelope": self._envelope_info(envelope, include_points=True)}
        if action in {"insert_automation_item", "add_automation_item"}:
            insert_ai = getattr(self.rpr, "InsertAutomationItem", None)
            if not callable(insert_ai):
                raise ReaperBridgeError("This Reaper bridge cannot insert automation items.")
            index = insert_ai(envelope, int(payload.get("pool_id", -1) or -1), float(payload.get("position", self.cursor_position()) or 0.0), float(payload.get("length", 1.0) or 1.0))
            return {"automation_item_index": _last_number(index), "envelope": self._envelope_info(envelope, include_points=False)}
        raise ReaperBridgeError(f"Unsupported envelopes action: {action}")

    def _resolve_envelope(self, payload: dict):
        if bool(payload.get("selected", False)) and callable(getattr(self.rpr, "GetSelectedEnvelope", None)):
            envelope = _first_object(self.rpr.GetSelectedEnvelope(0))
            if envelope is not None:
                return envelope
        track = self.find_track({"index": payload.get("track_index", payload.get("index")), "name": payload.get("track_name")})
        if payload.get("envelope_name") and callable(getattr(self.rpr, "GetTrackEnvelopeByName", None)):
            envelope = _first_object(self.rpr.GetTrackEnvelopeByName(track, str(payload.get("envelope_name"))))
            if envelope is not None:
                return envelope
        if payload.get("chunk_name") and callable(getattr(self.rpr, "GetTrackEnvelopeByChunkName", None)):
            envelope = _first_object(self.rpr.GetTrackEnvelopeByChunkName(track, str(payload.get("chunk_name"))))
            if envelope is not None:
                return envelope
        env_index = int(payload.get("envelope_index", payload.get("env_index", 0)) or 0)
        envelope = _first_object(self.rpr.GetTrackEnvelope(track, env_index))
        if envelope is None:
            raise ReaperBridgeError("Envelope not found.")
        return envelope

    def _envelope_info(self, envelope, index: int | None = None, include_points: bool = False) -> dict:
        name = _first_string(self.rpr.GetEnvelopeName(envelope, "", 4096)) if callable(getattr(self.rpr, "GetEnvelopeName", None)) else ""
        count = int(self.rpr.CountEnvelopePoints(envelope)) if callable(getattr(self.rpr, "CountEnvelopePoints", None)) else 0
        info = {"index": index, "name": name, "point_count": count}
        if callable(getattr(self.rpr, "CountAutomationItems", None)):
            info["automation_item_count"] = int(self.rpr.CountAutomationItems(envelope))
        if include_points:
            info["points"] = [self._envelope_point_info(envelope, point_index) for point_index in range(count)]
        return info

    def _envelope_point_info(self, envelope, point_index: int) -> dict:
        result = self.rpr.GetEnvelopePoint(envelope, point_index, 0.0, 0.0, 0, 0.0, False)
        numbers = [item for item in result if isinstance(item, (int, float)) and not isinstance(item, bool)] if _is_result_sequence(result) else []
        booleans = [item for item in result if isinstance(item, bool)] if _is_result_sequence(result) else []
        return {
            "index": point_index,
            "time": float(numbers[0]) if len(numbers) > 0 else None,
            "value": float(numbers[1]) if len(numbers) > 1 else None,
            "shape": int(numbers[2]) if len(numbers) > 2 else None,
            "tension": float(numbers[3]) if len(numbers) > 3 else None,
            "selected": bool(booleans[-1]) if booleans else None,
        }

    def midi_events(self, payload: dict) -> dict:
        self.connect()
        action = str(payload.get("action") or "summary").strip().casefold()
        track, item = self.find_media_item(payload)
        take = self._item_take(item, index=payload.get("take_index"), active=bool(payload.get("active", True)))
        if take is None:
            raise ReaperBridgeError("MIDI take not found.")
        if action in {"summary", "count"}:
            return self.midi_summary(take)
        if action in {"list_notes", "notes"}:
            return {"notes": self._midi_notes(take), "count": len(self._midi_notes(take))}
        if action in {"list_cc", "cc"}:
            return {"cc": self._midi_cc(take), "count": len(self._midi_cc(take))}
        if action in {"list_text", "text", "sysex"}:
            events = self._midi_text_sysex(take)
            return {"text_sysex": events, "count": len(events)}
        if action in {"insert_cc", "add_cc"}:
            ppq = self._midi_event_ppq(take, payload)
            self.rpr.MIDI_InsertCC(take, bool(payload.get("selected", False)), bool(payload.get("muted", False)), ppq, int(payload.get("chanmsg", payload.get("status", 176)) or 176), int(payload.get("channel", 0) or 0), int(payload.get("msg2", payload.get("controller", 1)) or 1), int(payload.get("msg3", payload.get("value", 0)) or 0))
            self.rpr.MIDI_Sort(take)
            return {"inserted": True, "cc": self._midi_cc(take)}
        if action in {"insert_text", "insert_sysex", "add_text", "add_sysex"}:
            ppq = self._midi_event_ppq(take, payload)
            message = str(payload.get("message", payload.get("text", "")))
            event_type = int(payload.get("type", -1 if "sysex" in action else 1) or 1)
            self.rpr.MIDI_InsertTextSysexEvt(take, bool(payload.get("selected", False)), bool(payload.get("muted", False)), ppq, event_type, message, len(message))
            self.rpr.MIDI_Sort(take)
            return {"inserted": True, "text_sysex": self._midi_text_sysex(take)}
        if action in {"delete_note", "delete_cc", "delete_text", "delete_sysex"}:
            event_index = int(payload.get("event_index", payload.get("note_index", payload.get("cc_index", payload.get("text_index", 0)))) or 0)
            if action == "delete_note":
                self.rpr.MIDI_DeleteNote(take, event_index)
            elif action == "delete_cc":
                self.rpr.MIDI_DeleteCC(take, event_index)
            else:
                self.rpr.MIDI_DeleteTextSysexEvt(take, event_index)
            return {"deleted": True, "event_index": event_index}
        if action in {"select_all", "deselect_all"}:
            self.rpr.MIDI_SelectAll(take, action == "select_all")
            return {"selected": action == "select_all"}
        if action == "hash":
            notes_only = bool(payload.get("notes_only", False))
            return {"hash": _first_string(self.rpr.MIDI_GetHash(take, notes_only, "", 4096)), "notes_only": notes_only}
        raise ReaperBridgeError(f"Unsupported midi_events action: {action}")

    def _midi_event_ppq(self, take, payload: dict) -> float:
        if "ppq" in payload or "ppqpos" in payload:
            return float(payload.get("ppq", payload.get("ppqpos")) or 0.0)
        time = _float_or_none(payload.get("time", payload.get("position")))
        if time is None:
            time = self.cursor_position()
        return self._ppq_from_time(take, time)

    def _midi_notes(self, take) -> list[dict]:
        summary = self.midi_summary(take)
        notes = []
        for index in range(int(summary.get("note_count") or 0)):
            result = self.rpr.MIDI_GetNote(take, index, False, False, 0.0, 0.0, 0, 0, 0)
            numbers = [item for item in result if isinstance(item, (int, float)) and not isinstance(item, bool)] if _is_result_sequence(result) else []
            booleans = [item for item in result if isinstance(item, bool)] if _is_result_sequence(result) else []
            notes.append({"index": index, "selected": bool(booleans[-2]) if len(booleans) >= 2 else None, "muted": bool(booleans[-1]) if booleans else None, "start_ppq": numbers[0] if len(numbers) > 0 else None, "end_ppq": numbers[1] if len(numbers) > 1 else None, "channel": int(numbers[2]) if len(numbers) > 2 else None, "pitch": int(numbers[3]) if len(numbers) > 3 else None, "velocity": int(numbers[4]) if len(numbers) > 4 else None})
        return notes

    def _midi_cc(self, take) -> list[dict]:
        summary = self.midi_summary(take)
        events = []
        for index in range(int(summary.get("cc_count") or 0)):
            result = self.rpr.MIDI_GetCC(take, index, False, False, 0.0, 0, 0, 0, 0)
            numbers = [item for item in result if isinstance(item, (int, float)) and not isinstance(item, bool)] if _is_result_sequence(result) else []
            booleans = [item for item in result if isinstance(item, bool)] if _is_result_sequence(result) else []
            events.append({"index": index, "selected": bool(booleans[-2]) if len(booleans) >= 2 else None, "muted": bool(booleans[-1]) if booleans else None, "ppq": numbers[0] if len(numbers) > 0 else None, "chanmsg": int(numbers[1]) if len(numbers) > 1 else None, "channel": int(numbers[2]) if len(numbers) > 2 else None, "msg2": int(numbers[3]) if len(numbers) > 3 else None, "msg3": int(numbers[4]) if len(numbers) > 4 else None})
        return events

    def _midi_text_sysex(self, take) -> list[dict]:
        summary = self.midi_summary(take)
        events = []
        for index in range(int(summary.get("text_sysex_count") or 0)):
            result = self.rpr.MIDI_GetTextSysexEvt(take, index, False, False, 0.0, 0, "", 65536)
            numbers = [item for item in result if isinstance(item, (int, float)) and not isinstance(item, bool)] if _is_result_sequence(result) else []
            booleans = [item for item in result if isinstance(item, bool)] if _is_result_sequence(result) else []
            strings = [item for item in result if isinstance(item, str)] if _is_result_sequence(result) else []
            events.append({"index": index, "selected": bool(booleans[-2]) if len(booleans) >= 2 else None, "muted": bool(booleans[-1]) if booleans else None, "ppq": numbers[0] if len(numbers) > 0 else None, "type": int(numbers[1]) if len(numbers) > 1 else None, "message": strings[-1] if strings else ""})
        return events

    def media_sources(self, payload: dict) -> dict:
        self.connect()
        track, item = self.find_media_item(payload)
        take = self._item_take(item, index=payload.get("take_index"), active=bool(payload.get("active", True)))
        if take is None:
            raise ReaperBridgeError("Take not found.")
        source = _first_object(self.rpr.GetMediaItemTake_Source(take))
        if source is None:
            raise ReaperBridgeError("Media source not found.")
        info = {"track": self.track_info(track, include_fx=False), "item": self.media_item_info(item, track=track), "take": self.take_info(take)}
        if callable(getattr(self.rpr, "GetMediaSourceFileName", None)):
            info["filename"] = _first_path(self.rpr.GetMediaSourceFileName(source, "", 4096))
        if callable(getattr(self.rpr, "GetMediaSourceType", None)):
            info["type"] = _first_string(self.rpr.GetMediaSourceType(source, "", 256))
        if callable(getattr(self.rpr, "GetMediaSourceLength", None)):
            result = self.rpr.GetMediaSourceLength(source, False)
            info["length"] = _last_number(result)
            info["length_is_qn"] = bool(result[-1]) if _is_result_sequence(result) and result else None
        if callable(getattr(self.rpr, "GetMediaSourceSampleRate", None)):
            info["sample_rate"] = _last_number(self.rpr.GetMediaSourceSampleRate(source))
        if callable(getattr(self.rpr, "GetMediaSourceNumChannels", None)):
            info["channels"] = _last_number(self.rpr.GetMediaSourceNumChannels(source))
        if callable(getattr(self.rpr, "GetMediaSourceParent", None)):
            info["has_parent"] = _first_object(self.rpr.GetMediaSourceParent(source)) is not None
        if callable(getattr(self.rpr, "PCM_Source_GetSectionInfo", None)):
            try:
                section = self.rpr.PCM_Source_GetSectionInfo(source, 0.0, 0.0, False)
                numbers = [item for item in section if isinstance(item, (int, float)) and not isinstance(item, bool)] if _is_result_sequence(section) else []
                booleans = [item for item in section if isinstance(item, bool)] if _is_result_sequence(section) else []
                info["section"] = {"offset": numbers[0] if len(numbers) > 0 else None, "length": numbers[1] if len(numbers) > 1 else None, "reversed": bool(booleans[-1]) if booleans else None}
            except Exception:
                pass
        identifier = str(payload.get("metadata", "")).strip()
        if identifier and callable(getattr(self.rpr, "GetMediaFileMetadata", None)):
            info["metadata"] = _first_string(self.rpr.GetMediaFileMetadata(source, identifier, "", 65536))
        return info

    def reaper_session(self, payload: dict) -> dict:
        self.connect()
        action = str(payload.get("action") or "status").strip().casefold()
        if action == "status":
            return {"can_undo": self._undo_label("Undo_CanUndo2"), "can_redo": self._undo_label("Undo_CanRedo2")}
        if action in {"undo", "redo"}:
            func = self.rpr.Undo_DoUndo2 if action == "undo" else self.rpr.Undo_DoRedo2
            func(0)
            return {"action": action, "done": True}
        if action in {"begin_undo", "begin_block"}:
            func2 = getattr(self.rpr, "Undo_BeginBlock2", None)
            func = getattr(self.rpr, "Undo_BeginBlock", None)
            if callable(func2):
                func2(0)
            elif callable(func):
                func()
            else:
                raise ReaperBridgeError("This Reaper bridge cannot begin undo blocks.")
            return {"action": action, "done": True}
        if action in {"end_undo", "end_block"}:
            description = str(payload.get("description") or payload.get("name") or "AudioMate Reaper operation")
            flags = int(payload.get("flags", -1) or -1)
            func2 = getattr(self.rpr, "Undo_EndBlock2", None)
            func = getattr(self.rpr, "Undo_EndBlock", None)
            if callable(func2):
                func2(0, description, flags)
            elif callable(func):
                func(description, flags)
            else:
                raise ReaperBridgeError("This Reaper bridge cannot end undo blocks.")
            return {"action": action, "description": description, "done": True}
        if action == "prevent_ui_refresh":
            amount = int(payload.get("amount", payload.get("count", 1)) or 1)
            self.rpr.PreventUIRefresh(amount)
            return {"action": action, "amount": amount}
        if action in {"resume_ui_refresh", "allow_ui_refresh"}:
            amount = -abs(int(payload.get("amount", payload.get("count", 1)) or 1))
            self.rpr.PreventUIRefresh(amount)
            return {"action": action, "amount": amount}
        if action == "update_arrange":
            self.rpr.UpdateArrange()
            return {"updated": "arrange"}
        if action == "update_timeline":
            self.rpr.UpdateTimeline()
            return {"updated": "timeline"}
        if action == "mark_dirty":
            self.rpr.MarkProjectDirty(0)
            return {"dirty": True}
        raise ReaperBridgeError(f"Unsupported reaper_session action: {action}")

    def _undo_label(self, function_name: str) -> str | None:
        func = getattr(self.rpr, function_name, None)
        if not callable(func):
            return None
        try:
            value = func(0)
        except Exception:
            return None
        text = _first_string(value)
        return text or None

    def call_api(self, payload: dict) -> dict:
        self.connect()
        name = str(payload.get("function") or payload.get("name") or "").strip()
        if not name:
            raise ReaperBridgeError("call_api requires a ReaScript function name.")
        if name.startswith("_"):
            raise ReaperBridgeError("Private API names are not allowed.")
        func = getattr(self.rpr, name, None)
        if not callable(func):
            raise ReaperBridgeError(f"ReaScript API function not found: {name}")
        args = [self._resolve_api_arg(arg) for arg in (payload.get("args") or [])]
        kwargs = {key: self._resolve_api_arg(value) for key, value in (payload.get("kwargs") or {}).items()}
        result = func(*args, **kwargs)
        return {"function": name, "args": payload.get("args") or [], "result": _json_safe(result)}

    def _resolve_api_arg(self, arg):
        if not isinstance(arg, dict) or "ref" not in arg:
            return arg
        ref = arg.get("ref")
        if ref == "track":
            return self.find_track({"index": arg.get("index"), "name": arg.get("name")})
        if ref == "item":
            return self.find_media_item({"track_index": arg.get("track_index"), "track_name": arg.get("track_name"), "item_index": arg.get("item_index", arg.get("index", 0))})[1]
        if ref == "take":
            item = self.find_media_item({"track_index": arg.get("track_index"), "track_name": arg.get("track_name"), "item_index": arg.get("item_index", 0)})[1]
            take = self._item_take(item, index=arg.get("take_index"), active=bool(arg.get("active", True)))
            if take is None:
                raise ReaperBridgeError("Referenced take not found.")
            return take
        if ref == "envelope":
            return self._resolve_envelope(arg)
        if ref == "source":
            item = self.find_media_item({"track_index": arg.get("track_index"), "track_name": arg.get("track_name"), "item_index": arg.get("item_index", 0)})[1]
            take = self._item_take(item, index=arg.get("take_index"), active=bool(arg.get("active", True)))
            if take is None:
                raise ReaperBridgeError("Referenced source take not found.")
            source = _first_object(self.rpr.GetMediaItemTake_Source(take))
            if source is None:
                raise ReaperBridgeError("Referenced media source not found.")
            return source
        raise ReaperBridgeError(f"Unsupported call_api ref: {ref}")


class Plugin:
    RENDER_SETTING_INPUT_KEYS = {
        "updates", "string_updates", "render_settings", "render_bounds", "render_boundsflag", "bounds",
        "render_channels", "channels", "render_sample_rate", "render_srate", "sample_rate", "srate",
        "render_start", "render_startpos", "start", "render_end", "render_endpos", "end",
        "render_tail_flags", "render_tailflag", "render_tail_ms", "render_tailms", "tail", "tail_contexts",
        "tail_flags", "tail_seconds", "render_add_to_project", "render_addtoproj", "add_to_project",
        "skip_silent", "render_add_flags", "render_dither", "dither", "noise_shaping", "dither_flags",
        "disable_dither", "render_normalize", "normalize", "normalize_mode", "normalize_type",
        "normalize_scope", "limit_scope", "normalize_target", "normalize_target_db", "render_normalize_target",
        "render_brickwall", "brickwall", "brickwall_db", "brickwall_target", "true_peak", "brickwall_true_peak",
        "only_too_loud", "only_too_quiet", "disable_postprocessing", "mono_adjust_db", "render_fade_in",
        "render_fadein", "fade_in", "fade_in_ms", "fade_in_shape", "render_fade_in_shape", "render_fadeinshape",
        "render_fade_out", "render_fadeout", "fade_out", "fade_out_ms", "fade_out_shape",
        "render_fade_out_shape", "render_fadeoutshape", "render_fade_lpf", "render_fadelpf", "fade_lpf",
        "render_pad_start", "render_padstart", "pad_start", "pad_start_ms", "render_pad_end", "render_padend",
        "pad_end", "pad_end_ms", "render_trim_start", "render_trimstart", "trim_start", "trim_start_db",
        "render_trim_end", "render_trimend", "trim_end", "trim_end_db", "render_delay", "delay_seconds",
        "render_file", "render_directory", "render_path", "directory", "path", "output_dir", "output_path",
        "render_pattern", "render_name", "file_name_pattern", "filename_pattern", "pattern", "name", "filename",
        "file_name", "render_extra_file_dir", "render_extra_directory", "extra_directory", "render_metadata",
        "render_format", "render_format2", "format", "secondary_format", "render_mode", "render_source",
        "source", "render_flags", "render_settings_flags", "flags",
    }

    TOOLS = [
        {
            "name": "write_midi",
            "description": "Create a MIDI item on a Reaper track and write a default melody or explicit MIDI notes.",
            "function": "write_midi",
            "read_only": False,
        },
        {
            "name": "create_track",
            "description": "Create a Reaper track at the end or at a specific index, optionally naming, selecting, arming, coloring, or adding FX.",
            "function": "create_track",
            "read_only": False,
        },
        {
            "name": "media_items",
            "description": "List, create, update, select, or delete Reaper media items on tracks.",
            "function": "media_items",
            "read_only": False,
        },
        {
            "name": "takes",
            "description": "Read and modify active takes, take names, source names, and MIDI note summaries.",
            "function": "takes",
            "read_only": False,
        },
        {
            "name": "track_fx",
            "description": "List, add, enable, bypass, inspect, and edit track FX and FX parameters.",
            "function": "track_fx",
            "read_only": False,
        },
        {
            "name": "project_markers",
            "description": "List, add, update, or delete project markers and regions.",
            "function": "project_markers",
            "read_only": False,
        },
        {
            "name": "project_settings",
            "description": "Read and set Reaper project and render settings including tempo, sample rate, render mode, bounds, path, name pattern, format, normalization, tail, dither, fade, pad, trim, and save.",
            "function": "project_settings",
            "read_only": False,
        },
        {
            "name": "ext_state",
            "description": "Read, write, delete, and enumerate Reaper global ExtState and project ProjExtState values.",
            "function": "ext_state",
            "read_only": False,
        },
        {
            "name": "track_routing",
            "description": "List, create, update, or remove track sends, receives, and hardware outputs.",
            "function": "track_routing",
            "read_only": False,
        },
        {
            "name": "envelopes",
            "description": "List track envelopes and inspect, insert, update, delete, or sort envelope and automation item points.",
            "function": "envelopes",
            "read_only": False,
        },
        {
            "name": "midi_events",
            "description": "Inspect and edit MIDI notes, CC events, text/sysex events, hashes, and selection state in a MIDI take.",
            "function": "midi_events",
            "read_only": False,
        },
        {
            "name": "media_sources",
            "description": "Read media source file, type, length, sample rate, channel count, section, and metadata for takes.",
            "function": "media_sources",
            "read_only": True,
        },
        {
            "name": "reaper_session",
            "description": "Run utility operations such as undo/redo, undo block calls, UI refresh control, arrange updates, and dirty flags.",
            "function": "reaper_session",
            "read_only": False,
        },
        {
            "name": "call_api",
            "description": "Call an allowed low-level ReaScript API function by name with JSON arguments for advanced operations not wrapped by other tools.",
            "function": "call_api",
            "read_only": False,
        }
    ]

    def initialize(self, init_context):
        self.init_context = init_context or {}
        self.bridge = ReaperBridge()

    def cleanup(self):
        self.bridge = None

    def check_connection(self, input, context):
        return _ok("Reaper bridge is available.", self.bridge.health())

    def transport(self, input, context):
        input = _dict(input)
        action = input.get("action") or input.get("command") or "status"
        return _ok("Reaper transport command completed.", self.bridge.transport(action, **input))

    def project_info(self, input, context):
        input = _dict(input)
        include_tracks = bool(input.get("include_tracks", False))
        return _ok("Reaper project info retrieved.", self.bridge.project_info(include_tracks=include_tracks))

    def list_tracks(self, input, context):
        input = _dict(input)
        include_fx = bool(input.get("include_fx", True))
        tracks = self.bridge.list_tracks(include_fx=include_fx)
        return _ok(f"Found {len(tracks)} Reaper tracks.", {"tracks": tracks, "count": len(tracks)})

    def set_track(self, input, context):
        input = _dict(input)
        selector = {"index": input.get("index"), "name": input.get("name")}
        updates = dict(input.get("updates") or {})
        if "select" in input and "selected" not in input:
            input["selected"] = input["select"]
        if "select" in updates and "selected" not in updates:
            updates["selected"] = updates.pop("select")
        for key in ("volume", "volume_db", "pan", "mute", "solo", "record_arm", "selected", "color"):
            if key in input:
                updates[key] = input[key]
        if "new_name" in input:
            updates["name"] = input["new_name"]
        if not updates:
            raise ReaperBridgeError("set_track requires at least one update field.")
        return _ok("Reaper track updated.", self.bridge.set_track(selector, updates))

    def execute_action(self, input, context):
        input = _dict(input)
        command_id = input.get("command_id") or input.get("action") or input.get("name")
        result = self.bridge.execute_action(command_id, flag=int(input.get("flag", 0) or 0))
        return _ok("Reaper action executed.", result)

    def render(self, input, context):
        input = _dict(input)
        settings = {key: value for key, value in input.items() if key in self.RENDER_SETTING_INPUT_KEYS}
        result = self.bridge.render(mode=input.get("mode", "recent"), command_id=input.get("command_id"), settings=settings)
        return _ok("Reaper render command sent.", result)

    def markers_regions(self, input, context):
        return _ok("Reaper markers and regions retrieved.", self.bridge.markers_regions())

    def write_midi(self, input, context):
        result = self.bridge.write_midi(_dict(input))
        return _ok(f"Wrote {result['note_count']} MIDI notes into Reaper.", result)

    def create_track(self, input, context):
        result = self.bridge.create_track_with_options(_dict(input))
        return _ok("Reaper track created.", result)

    def media_items(self, input, context):
        result = self.bridge.media_items(_dict(input))
        return _ok("Reaper media item operation completed.", result)

    def takes(self, input, context):
        result = self.bridge.takes(_dict(input))
        return _ok("Reaper take operation completed.", result)

    def track_fx(self, input, context):
        result = self.bridge.track_fx(_dict(input))
        return _ok("Reaper track FX operation completed.", result)

    def project_markers(self, input, context):
        result = self.bridge.project_markers(_dict(input))
        return _ok("Reaper marker/region operation completed.", result)

    def project_settings(self, input, context):
        result = self.bridge.project_settings(_dict(input))
        return _ok("Reaper project settings operation completed.", result)

    def ext_state(self, input, context):
        result = self.bridge.ext_state(_dict(input))
        return _ok("Reaper ext state operation completed.", result)

    def track_routing(self, input, context):
        result = self.bridge.track_routing(_dict(input))
        return _ok("Reaper track routing operation completed.", result)

    def envelopes(self, input, context):
        result = self.bridge.envelopes(_dict(input))
        return _ok("Reaper envelope operation completed.", result)

    def midi_events(self, input, context):
        result = self.bridge.midi_events(_dict(input))
        return _ok("Reaper MIDI event operation completed.", result)

    def media_sources(self, input, context):
        result = self.bridge.media_sources(_dict(input))
        return _ok("Reaper media source info retrieved.", result)

    def reaper_session(self, input, context):
        result = self.bridge.reaper_session(_dict(input))
        return _ok("Reaper session operation completed.", result)

    def call_api(self, input, context):
        result = self.bridge.call_api(_dict(input))
        return _ok("Reaper API call completed.", result)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _ok(message: str, data: dict | list | None = None) -> dict:
    return {"output": message, "ok": True, "data": data}


def _error(message: str, exc: Exception | None = None) -> dict:
    data = {"message": message, "ok": False}
    if exc is not None:
        data["error"] = str(exc)
        data["traceback"] = traceback.format_exc()
    return {"output": message, "ok": False, "data": data}


def _wrap_tool(method):
    def wrapped(self, input, context):
        try:
            return method(self, input, context)
        except ReaperBridgeError as exc:
            return _error(str(exc), exc)
        except Exception as exc:  # noqa: BLE001
            return _error(f"Reaper plugin tool failed: {exc}", exc)
    return wrapped


for _name in (
    "check_connection",
    "transport",
    "project_info",
    "list_tracks",
    "set_track",
    "execute_action",
    "render",
    "markers_regions",
    "write_midi",
    "create_track",
    "media_items",
    "takes",
    "track_fx",
    "project_markers",
    "project_settings",
    "ext_state",
    "track_routing",
    "envelopes",
    "midi_events",
    "media_sources",
    "reaper_session",
    "call_api",
):
    setattr(Plugin, _name, _wrap_tool(getattr(Plugin, _name)))


def _first_string(value) -> str:
    if _is_result_sequence(value):
        strings = [item for item in value if isinstance(item, str)]
        if strings:
            return strings[-1]
        return ""
    return str(value or "")


def _first_path(value) -> str:
    if _is_result_sequence(value):
        for item in reversed(value):
            if isinstance(item, str) and (":" in item or "/" in item or "\\" in item):
                return item
        for item in reversed(value):
            if isinstance(item, str):
                return item
        return ""
    return str(value or "")


def _first_object(value):
    if _is_result_sequence(value):
        for item in value:
            if item is not None and not isinstance(item, (bool, int, float, str)):
                return item
        for item in value:
            if item is not None:
                return item
        return None
    return value


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if _is_result_sequence(value):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _extract_time_signature(value) -> tuple[int | None, int | None]:
    if _is_result_sequence(value):
        numbers = [int(item) for item in value if isinstance(item, int)]
        if len(numbers) >= 2:
            return numbers[-2], numbers[-1]
    return None, None


def _last_number(value) -> int | float | None:
    if _is_result_sequence(value):
        for item in reversed(value):
            if isinstance(item, (int, float)):
                return item
    if isinstance(value, (int, float)):
        return value
    return None


def _bool_result(value) -> bool:
    if isinstance(value, bool):
        return value
    if _is_result_sequence(value):
        for item in value:
            if isinstance(item, bool):
                return item
        for item in value:
            if isinstance(item, (int, float)):
                return bool(item)
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(value)


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(mapping: dict, *keys: str):
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _slug(value: Any) -> str:
    return str(value or "").strip().casefold().replace(" ", "_").replace("-", "_")


def _linear_to_db(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return round(20.0 * math.log10(value), 2)


def _db_to_linear(value: float) -> float:
    return math.pow(10.0, float(value) / 20.0)


def _parse_color(value: Any) -> int:
    if isinstance(value, int):
        return value | 0x1000000
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        raise ReaperBridgeError("Track color must be an integer or #RRGGBB string.")
    red = int(text[0:2], 16)
    green = int(text[2:4], 16)
    blue = int(text[4:6], 16)
    return red | (green << 8) | (blue << 16) | 0x1000000


def _normalize_midi_notes(value, tempo: float) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, str):
        value = _notes_from_text(value)
    if not isinstance(value, list):
        raise ReaperBridgeError("MIDI notes must be a list or a space separated note string.")
    notes = []
    cursor = 0.0
    for raw_note in value:
        note = _normalize_midi_note(raw_note, cursor=cursor, tempo=tempo)
        notes.append(note)
        cursor = max(cursor, note["start"] + note["duration"])
    return notes


def _normalize_midi_note(raw_note, cursor: float, tempo: float) -> dict:
    if isinstance(raw_note, str):
        raw_note = {"pitch": raw_note}
    if isinstance(raw_note, int):
        raw_note = {"pitch": raw_note}
    if not isinstance(raw_note, dict):
        raise ReaperBridgeError(f"Invalid MIDI note: {raw_note}")
    pitch_value = raw_note.get("pitch", raw_note.get("note", raw_note.get("name")))
    pitch = _parse_midi_pitch(pitch_value)
    start = _float_or_none(raw_note.get("start", raw_note.get("beat")))
    if start is None:
        seconds = _float_or_none(raw_note.get("time", raw_note.get("start_time")))
        start = seconds / (60.0 / tempo) if seconds is not None else cursor
    duration = _float_or_none(raw_note.get("duration", raw_note.get("length", raw_note.get("beats"))))
    if duration is None:
        seconds_duration = _float_or_none(raw_note.get("duration_seconds", raw_note.get("seconds")))
        duration = seconds_duration / (60.0 / tempo) if seconds_duration is not None else 0.5
    velocity = int(raw_note.get("velocity", raw_note.get("vel", 96)) or 96)
    channel = int(raw_note.get("channel", raw_note.get("chan", 0)) or 0)
    if duration <= 0:
        raise ReaperBridgeError("MIDI note duration must be greater than 0.")
    return {
        "pitch": max(0, min(127, pitch)),
        "start": max(0.0, float(start)),
        "duration": float(duration),
        "velocity": max(1, min(127, velocity)),
        "channel": max(0, min(15, channel)),
        "selected": bool(raw_note.get("selected", False)),
        "muted": bool(raw_note.get("muted", False)),
    }


def _notes_from_text(text: str) -> list[dict]:
    tokens = [token.strip() for token in str(text or "").replace(",", " ").split() if token.strip()]
    return [{"pitch": token, "duration": 0.5} for token in tokens]


def _default_midi_notes() -> list[dict]:
    melody = ["C4", "E4", "G4", "C5", "G4", "E4", "D4", "C4"]
    return [{"pitch": _parse_midi_pitch(note), "start": index * 0.5, "duration": 0.45, "velocity": 96, "channel": 0} for index, note in enumerate(melody)]


def _normalize_project_fields(value, defaults: list[str]) -> list[str]:
    if value is None:
        return list(defaults)
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.replace(";", ",").split(",")]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw_items = list(value)
    else:
        raw_items = []
    fields = []
    seen = set()
    info_aliases = getattr(ReaperBridge, "PROJECT_INFO_FIELDS", {})
    string_aliases = getattr(ReaperBridge, "PROJECT_STRING_FIELDS", {})
    for raw in raw_items:
        text = str(raw or "").strip()
        if not text:
            continue
        field = info_aliases.get(text.casefold()) or string_aliases.get(text.casefold()) or text.upper()
        if field not in seen:
            seen.add(field)
            fields.append(field)
    return fields or list(defaults)


def _default_project_info_fields() -> list[str]:
    return [
        "PROJECT_SRATE",
        "PROJECT_SRATE_USE",
        "PROJECT_TIMEBASE",
        "PROJECT_TIMEBASE_FLAGS",
        "RENDER_SETTINGS",
        "RENDER_BOUNDSFLAG",
        "RENDER_CHANNELS",
        "RENDER_SRATE",
    ]


def _default_render_info_fields() -> list[str]:
    return [
        "RENDER_SETTINGS",
        "RENDER_BOUNDSFLAG",
        "RENDER_CHANNELS",
        "RENDER_SRATE",
        "RENDER_STARTPOS",
        "RENDER_ENDPOS",
        "RENDER_TAILFLAG",
        "RENDER_TAILMS",
        "RENDER_ADDTOPROJ",
        "RENDER_DITHER",
        "RENDER_NORMALIZE",
        "RENDER_NORMALIZE_TARGET",
        "RENDER_BRICKWALL",
        "RENDER_FADEIN",
        "RENDER_FADEOUT",
        "RENDER_FADEINSHAPE",
        "RENDER_FADEOUTSHAPE",
        "RENDER_FADELPF",
        "RENDER_PADSTART",
        "RENDER_PADEND",
        "RENDER_TRIMSTART",
        "RENDER_TRIMEND",
        "RENDER_DELAY",
    ]


def _default_project_string_fields() -> list[str]:
    return ["PROJECT_NAME", "PROJECT_TITLE", "PROJECT_AUTHOR", "RECORD_PATH", "RENDER_FILE", "RENDER_PATTERN"]


def _default_render_string_fields() -> list[str]:
    return ["RENDER_FILE", "RENDER_PATTERN", "RENDER_TARGETS", "RENDER_FORMAT", "RENDER_FORMAT2"]


def _parse_midi_pitch(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip()
    if not text:
        raise ReaperBridgeError("MIDI note pitch is required.")
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return int(text)
    name = text.upper().replace("♯", "#").replace("♭", "B")
    note_names = {
        "C": 0,
        "C#": 1,
        "DB": 1,
        "D": 2,
        "D#": 3,
        "EB": 3,
        "E": 4,
        "F": 5,
        "F#": 6,
        "GB": 6,
        "G": 7,
        "G#": 8,
        "AB": 8,
        "A": 9,
        "A#": 10,
        "BB": 10,
        "B": 11,
    }
    note_part = name[:-1]
    octave_part = name[-1]
    if len(name) >= 3 and name[-2] == "-":
        note_part = name[:-2]
        octave_part = name[-2:]
    if note_part not in note_names:
        raise ReaperBridgeError(f"Invalid MIDI note name: {value}")
    try:
        octave = int(octave_part)
    except ValueError as exc:
        raise ReaperBridgeError(f"Invalid MIDI note octave: {value}") from exc
    return (octave + 1) * 12 + note_names[note_part]


def _midi_note_name(pitch: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    pitch = int(pitch)
    octave = pitch // 12 - 1
    return f"{names[pitch % 12]}{octave}"


def _parse_marker_result(value, index: int) -> dict | None:
    if not _is_result_sequence(value) or not value:
        return None
    if isinstance(value[0], (int, float)) and not isinstance(value[0], bool) and int(value[0]) == 0:
        return None
    values = list(value)
    name_index = next((item_index for item_index, item in enumerate(values) if isinstance(item, str)), -1)
    if name_index < 3 or len(values) <= name_index + 1:
        return None
    is_region = _marker_bool(values[name_index - 3])
    position = _marker_float(values[name_index - 2])
    end = _marker_float(values[name_index - 1])
    marker_id = _marker_int(values[name_index + 1], index)
    color = _marker_int(values[name_index + 2], 0) if len(values) > name_index + 2 else None
    marker = {
        "index": index,
        "timeline_index": index,
        "type": "region" if is_region else "marker",
        "is_region": is_region,
        "position": position,
        "start": position,
        "end": end if is_region else position,
        "name": values[name_index],
        "id": marker_id,
        "number": marker_id,
    }
    if is_region:
        marker["length"] = max(0.0, marker["end"] - position)
    if color is not None:
        marker["color"] = color
    return marker


def _parse_project_marker_count(value) -> int:
    if not _is_result_sequence(value):
        return int(value or 0) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0
    numbers = [int(item) for item in value if isinstance(item, (int, float)) and not isinstance(item, bool)]
    if not numbers:
        return 0
    if len(numbers) >= 3:
        return max(numbers[0], numbers[-2] + numbers[-1])
    return max(numbers)


def _marker_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    return str(value).strip().casefold() in {"1", "true", "yes", "region"}


def _marker_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _marker_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_result_sequence(value) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
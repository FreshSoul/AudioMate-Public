import math
import os
import shutil
import sys
import tempfile

import numpy as np
import soundfile as sf

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.engine.turn_controller import TurnAction, TurnController
from src.gui.runtime_support import build_executor_context
from src.tools import create_default_registry
from src.utils.agent_tools import AgentToolbox
from src.utils.execution import CodeExecutor


class DummyWaapi:
    connected = True

    def get_selected_objects(self):
        return {}

    def list_source_files(self, **_kw):
        return []

    def get_schema(self, *_args, **_kw):
        return {}

    def get_functions(self):
        return []


class FakeModeSelector:
    def __init__(self, mode):
        self.mode = mode

    def currentText(self):
        return self.mode


class FakeRetriever:
    def lookup_doc(self, *_args, **_kw):
        return ""

    def search_functions(self, *_args, **_kw):
        return []


class FakeOwner:
    def __init__(self, mode="Agent Mode"):
        self.mode_selector = FakeModeSelector(mode)
        self.waapi_client = DummyWaapi()
        self.agent_tools = AgentToolbox(None, self.waapi_client)
        self.waapi_retriever = FakeRetriever()
        self.tool_registry = create_default_registry()
        self.code_executor = CodeExecutor({})

    def fetch_webpage(self, *_args, **_kw):
        return {}

    def get_active_mcp_config(self):
        return {}

    def list_mcp_tools(self, *_args, **_kw):
        return []

    def call_mcp_tool(self, *_args, **_kw):
        return {}

    def read_feishu_doc(self, *_args, **_kw):
        return {}


def _make_wav(path: str, duration_seconds: float = 0.12, sample_rate: int = 48000, amplitude: float = 0.2):
    sample_count = int(duration_seconds * sample_rate)
    t = np.linspace(0.0, duration_seconds, sample_count, endpoint=False)
    audio = (amplitude * np.sin(2 * math.pi * 880 * t)).astype(np.float32)
    sf.write(path, audio, sample_rate)


def _make_sine_wav(path: str, duration_seconds: float, *, sample_rate: int = 48000,
                   amplitude: float = 1.0, freq: float = 1000.0, channels: int = 1):
    n = int(duration_seconds * sample_rate)
    t = np.arange(n) / sample_rate
    mono = (amplitude * np.sin(2 * math.pi * freq * t)).astype(np.float32)
    audio = mono if channels == 1 else np.column_stack([mono] * channels)
    sf.write(path, audio, sample_rate)


def test_loudness_multichannel_downmix_returns_value_with_warning():
    """BUG1: >5 channels used to return null LUFS (pyloudnorm rejects >5ch and
    the ValueError was swallowed). Now it downmixes and reports the real cause."""
    root = tempfile.mkdtemp(prefix="多声道_")
    try:
        toolbox = AgentToolbox(None, DummyWaapi())
        for channels in (6, 8):
            path = os.path.join(root, f"bed_{channels}ch.wav")
            _make_sine_wav(path, 5.0, amplitude=1.0, channels=channels)
            result = toolbox.analyze_audio_file(path)
            assert result["integrated_loudness_lufs"] is not None, f"{channels}ch should yield a LUFS value"
            assert result["channels"] == channels
            assert any("声道" in w and "降混" in w for w in result["analysis_warnings"]), \
                f"{channels}ch should warn about channel downmix"
        print("test_loudness_multichannel_downmix_returns_value_with_warning: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_loudness_short_audio_converges_after_compensation():
    """BUG2: zero-padding short audio to 400ms diluted energy by 10*log10(dur/0.4).
    With the inverse correction, a full-scale sine reports the same LUFS at any
    duration instead of being progressively under-reported."""
    root = tempfile.mkdtemp(prefix="短音频_")
    try:
        toolbox = AgentToolbox(None, DummyWaapi())
        reference = None
        for dur in (0.1, 0.2, 0.3, 0.39, 0.5, 1.0):
            path = os.path.join(root, f"s_{dur}.wav")
            _make_sine_wav(path, dur, amplitude=1.0)
            lufs = toolbox.analyze_audio_file(path)["integrated_loudness_lufs"]
            assert lufs is not None
            if reference is None:
                reference = lufs
            else:
                assert abs(lufs - reference) < 0.6, \
                    f"dur={dur}s LUFS {lufs} should converge near {reference} (was under-reported pre-fix)"
        print("test_loudness_short_audio_converges_after_compensation: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_true_peak_exceeds_sample_peak_on_intersample_overs():
    """true_peak_dbfs is now a real oversampled inter-sample peak, not just the
    sample peak. A near-Nyquist full-scale sine has inter-sample overs > 0 dBTP."""
    root = tempfile.mkdtemp(prefix="真峰_")
    try:
        toolbox = AgentToolbox(None, DummyWaapi())
        path = os.path.join(root, "tp.wav")
        _make_sine_wav(path, 1.0, amplitude=1.0, freq=11000.0)
        result = toolbox.analyze_audio_file(path)
        assert result["peak_dbfs"] is not None and result["true_peak_dbfs"] is not None
        assert result["true_peak_dbfs"] >= result["peak_dbfs"]
        assert result["true_peak_dbfs"] > 0.0, "inter-sample peak of full-scale near-Nyquist sine should exceed 0 dBTP"
        print("test_true_peak_exceeds_sample_peak_on_intersample_overs: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_analyze_directory_loudness_handles_short_wavs_and_empty_dirs():
    root = tempfile.mkdtemp(prefix="响度测试_")
    try:
        _make_wav(os.path.join(root, "A.wav"), 0.12)
        _make_wav(os.path.join(root, "B.WAV"), 0.5, amplitude=0.1)
        os.makedirs(os.path.join(root, "nested"), exist_ok=True)
        _make_wav(os.path.join(root, "nested", "C.wav"), 0.08)

        toolbox = AgentToolbox(None, DummyWaapi())
        report = toolbox.analyze_directory_loudness(root)
        assert report["file_count"] == 3
        assert report["analyzed_count"] == 3
        assert len(report.get("results", [])) == 3
        assert report["summary"]["total_duration_seconds"] > 0
        for row in report["results"]:
            assert row["sample_rate"] == 48000
            assert row["channels"] == 1
            assert row["duration_seconds"] > 0
            assert row["peak_dbfs"] is not None
            assert row["rms_dbfs"] is not None
            assert row["integrated_loudness_lufs"] is not None

        empty = tempfile.mkdtemp(dir=root)
        empty_report = toolbox.analyze_directory_loudness(empty)
        assert empty_report["file_count"] == 0
        assert empty_report["analyzed_count"] == 0
        assert empty_report["results"] == []
        assert any("未找到" in warning for warning in empty_report["warnings"])
        print("test_analyze_directory_loudness_handles_short_wavs_and_empty_dirs: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_write_file_tree_stages_files_for_confirmation():
    root = tempfile.mkdtemp(prefix="file_tree_")
    try:
        owner = FakeOwner("Agent Mode")
        ctx = build_executor_context(owner)
        payload = {
            "base_dir": os.path.join(root, "AudioDebugger"),
            "files": [
                {"relative_path": "SKILL.md", "content": "# Skill"},
                {"relative_path": "Runtime/Debugger.cs", "content": "class Debugger {}"},
            ],
        }
        result = ctx["call_structured_tool"]("write_file_tree", payload)
        assert result["ok"] is True
        assert result["count"] == 2
        assert result["pending_confirmation"] is True
        assert len(owner.code_executor.pending_file_writes) == 2
        assert not os.path.exists(os.path.join(root, "AudioDebugger", "SKILL.md"))
        flushed = owner.code_executor.flush_pending_writes()
        assert all(item["success"] for item in flushed)
        assert os.path.exists(os.path.join(root, "AudioDebugger", "SKILL.md"))
        assert os.path.exists(os.path.join(root, "AudioDebugger", "Runtime", "Debugger.cs"))

        ask_owner = FakeOwner("Ask Mode")
        ask_ctx = build_executor_context(ask_owner)
        denied = ask_ctx["call_structured_tool"]("write_file_tree", payload)
        assert "Ask Mode" in denied["error"]
        print("test_write_file_tree_stages_files_for_confirmation: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_turn_controller_blocks_ask_mode_local_write_code_and_warns_empty_results():
    controller = TurnController()
    response = "```python_waapi\nwrite_user_file('~/Desktop/a.txt', 'x')\n```"
    result = controller.analyse_response(response, mode="Ask Mode")
    assert result.action == TurnAction.PURE_TEXT
    assert "Ask Mode" in result.response_text
    assert not result.code_blocks

    warnings = controller._post_validate_output('{"count": 0, "results": []}')
    assert any("不得生成逐文件表格" in warning for warning in warnings)
    print("test_turn_controller_blocks_ask_mode_local_write_code_and_warns_empty_results: OK")


def test_directory_loudness_compliance_flags_and_sorts():
    """Phase 1: compliance check flags out-of-range / over-true-peak files and
    sorts the non-compliant list worst-first."""
    root = tempfile.mkdtemp(prefix="合规_")
    try:
        toolbox = AgentToolbox(None, DummyWaapi())
        _make_sine_wav(os.path.join(root, "loud.wav"), 3.0, amplitude=1.0)    # ~-3 LUFS, over TP
        _make_sine_wav(os.path.join(root, "quiet.wav"), 3.0, amplitude=0.01)  # ~-43 LUFS
        _make_sine_wav(os.path.join(root, "mid.wav"), 3.0, amplitude=0.1)     # ~-23 LUFS

        report = toolbox.check_directory_loudness_compliance(
            root, target_lufs_min=-16.0, target_lufs_max=-12.0, true_peak_limit_dbfs=-1.0,
        )
        comp = report["summary"]["compliance"]
        assert comp["compliant_count"] == 0
        assert comp["noncompliant_count"] == 3
        nc = comp["noncompliant_files"]
        # worst-first: quiet.wav has the largest deviation
        assert os.path.basename(nc[0]["path"]) == "quiet.wav"
        # the full-scale file should trip the true-peak limit too
        loud = next(f for f in nc if os.path.basename(f["path"]) == "loud.wav")
        assert "true_peak_over" in loud["issues"]
        print("test_directory_loudness_compliance_flags_and_sorts: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_batch_normalize_dry_run_then_apply():
    """Phase 1: dry run writes nothing; apply normalizes and re-runs skip the
    now-compliant file (and never re-process .bak backups)."""
    root = tempfile.mkdtemp(prefix="批量修复_")
    try:
        toolbox = AgentToolbox(None, DummyWaapi())
        _make_sine_wav(os.path.join(root, "mid.wav"), 3.0, amplitude=0.1)  # ~-23 LUFS

        dry = toolbox.batch_normalize_directory_to_target(
            root, target_lufs=-14.0, target_lufs_min=-16.0, target_lufs_max=-12.0,
        )
        assert dry["mode"] == "dry_run"
        assert dry["summary"]["planned_count"] == 1
        assert sorted(os.listdir(root)) == ["mid.wav"], "dry run must not write or back up"

        applied = toolbox.batch_normalize_directory_to_target(
            root, target_lufs=-14.0, target_lufs_min=-16.0, target_lufs_max=-12.0, apply=True,
        )
        assert applied["mode"] == "applied"
        assert applied["summary"]["applied_count"] == 1
        assert applied["summary"]["failed_count"] == 0
        assert "mid.bak.wav" in os.listdir(root)
        assert abs(applied["results"][0]["result_lufs"] - (-14.0)) < 1.0

        rerun = toolbox.batch_normalize_directory_to_target(
            root, target_lufs=-14.0, target_lufs_min=-16.0, target_lufs_max=-12.0, apply=True,
        )
        assert rerun["summary"]["applied_count"] == 0, "now-compliant file should be skipped"
        assert not any(name.count(".bak") > 1 for name in os.listdir(root)), "no .bak.bak chains"
        print("test_batch_normalize_dry_run_then_apply: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_batch_normalize_apply_blocked_in_ask_mode():
    """Phase 1: dry run allowed in Ask Mode, apply=True blocked via runtime ctx."""
    ask_owner = FakeOwner("Ask Mode")
    ctx = build_executor_context(ask_owner)
    fn = ctx["batch_normalize_directory_to_target"]
    root = tempfile.mkdtemp(prefix="ask_批量_")
    try:
        _make_sine_wav(os.path.join(root, "mid.wav"), 3.0, amplitude=0.1)
        # dry run is read-only -> allowed
        dry = fn(root, target_lufs=-14.0, target_lufs_min=-16.0, target_lufs_max=-12.0)
        assert dry["mode"] == "dry_run"
        # apply is a write -> blocked
        raised = False
        try:
            fn(root, target_lufs=-14.0, target_lufs_min=-16.0, target_lufs_max=-12.0, apply=True)
        except PermissionError:
            raised = True
        assert raised, "apply=True must be blocked in Ask Mode"
        print("test_batch_normalize_apply_blocked_in_ask_mode: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_normalize_atomic_write_preserves_original_on_failure():
    """P0-5: a write failure must leave the original file intact (no data loss)
    and leave no orphaned .bak behind."""
    root = tempfile.mkdtemp(prefix="原子写_")
    try:
        toolbox = AgentToolbox(None, DummyWaapi())
        path = os.path.join(root, "c.wav")
        _make_sine_wav(path, 3.0, amplitude=0.1)
        original_bytes = open(path, "rb").read()

        # Wrap soundfile so write() fails but info()/read() still work.
        real_import = toolbox._import_audio_analysis_dependencies

        class _BadSf:
            def __init__(self, real):
                self._real = real

            def info(self, *a, **k):
                return self._real.info(*a, **k)

            def read(self, *a, **k):
                return self._real.read(*a, **k)

            def write(self, *a, **k):
                raise OSError("disk full (simulated)")

        def _patched():
            np_, lib_, pyln_, sf_ = real_import()
            return np_, lib_, pyln_, _BadSf(sf_)

        toolbox._import_audio_analysis_dependencies = _patched
        raised = False
        try:
            toolbox.normalize_audio_loudness(path, target_lufs=-14.0, stage=False)
        except OSError:
            raised = True
        assert raised, "write failure should propagate"
        assert open(path, "rb").read() == original_bytes, "original must be intact after a failed write"
        assert not any(name.startswith("c") and ".bak" in name for name in os.listdir(root)), \
            "no orphaned .bak should remain after a failed write"
        print("test_normalize_atomic_write_preserves_original_on_failure: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_normalize_immediate_write_backs_up_and_changes_target():
    """P0-5: immediate (stage=False) write applies atomically; backup is an exact
    copy of the original and the target is actually changed."""
    root = tempfile.mkdtemp(prefix="立即写_")
    try:
        toolbox = AgentToolbox(None, DummyWaapi())
        path = os.path.join(root, "a.wav")
        _make_sine_wav(path, 3.0, amplitude=0.1)
        original_bytes = open(path, "rb").read()

        result = toolbox.normalize_audio_loudness(path, target_lufs=-14.0, stage=False)
        assert result.get("pending_confirmation") is not True
        assert os.path.isfile(result["backup_path"])
        assert open(result["backup_path"], "rb").read() == original_bytes, "backup must equal the original"
        assert open(path, "rb").read() != original_bytes, "target must be the normalized audio"
        print("test_normalize_immediate_write_backs_up_and_changes_target: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_normalize_staged_defers_write_until_flush():
    """P0-5: when a file_write_stager is wired, normalize stages the write — disk
    is untouched until flush_pending_writes (the GUI confirmation) runs."""
    root = tempfile.mkdtemp(prefix="暂存写_")
    try:
        executor = CodeExecutor({})
        toolbox = AgentToolbox(None, DummyWaapi())
        toolbox.file_write_stager = executor.stage_audio_write

        path = os.path.join(root, "b.wav")
        _make_sine_wav(path, 3.0, amplitude=0.1)
        before = open(path, "rb").read()

        result = toolbox.normalize_audio_loudness(path, target_lufs=-14.0)  # stage default True
        assert result.get("pending_confirmation") is True
        assert len(executor.pending_file_writes) == 1
        assert open(path, "rb").read() == before, "disk must be untouched before confirmation"

        flushed = executor.flush_pending_writes()
        assert all(item["success"] for item in flushed)
        assert open(path, "rb").read() != before, "write should apply after flush"
        print("test_normalize_staged_defers_write_until_flush: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_normalize_blocked_in_ask_mode():
    """P0-5: single-file normalize remains a write op blocked in Ask Mode."""
    ask_owner = FakeOwner("Ask Mode")
    ctx = build_executor_context(ask_owner)
    raised = False
    try:
        ctx["normalize_audio_loudness"]("whatever.wav", target_lufs=-14.0)
    except PermissionError:
        raised = True
    assert raised, "normalize_audio_loudness must be blocked in Ask Mode"
    print("test_normalize_blocked_in_ask_mode: OK")



def test_detect_audio_anomalies_flags_each_defect_type():
    """Phase 2: each synthetic defect produces its expected anomaly code, and a
    clean file produces none. Empty/silent/too-short must not raise."""
    root = tempfile.mkdtemp(prefix="异常_")
    sr = 48000
    try:
        toolbox = AgentToolbox(None, DummyWaapi())
        n = int(2.0 * sr)
        t = np.arange(n) / sr

        clean = os.path.join(root, "clean.wav")
        sf.write(clean, (0.1 * np.sin(2 * math.pi * 1000 * t)).astype(np.float32), sr)
        clipped = os.path.join(root, "clipped.wav")
        sf.write(clipped, np.clip(1.5 * np.sin(2 * math.pi * 1000 * t), -1.0, 1.0).astype(np.float32), sr)
        dc = os.path.join(root, "dc.wav")
        sf.write(dc, (0.1 * np.sin(2 * math.pi * 1000 * t) + 0.2).astype(np.float32), sr)
        silent = os.path.join(root, "silent.wav")
        sf.write(silent, np.zeros(n, dtype=np.float32), sr)
        short = os.path.join(root, "short.wav")
        sf.write(short, (0.3 * np.sin(2 * math.pi * 1000 * np.arange(int(0.05 * sr)) / sr)).astype(np.float32), sr)
        empty = os.path.join(root, "empty.wav")
        sf.write(empty, np.zeros(0, dtype=np.float32), sr)

        assert toolbox.detect_audio_anomalies(clean)["anomalies"] == []
        assert "clipping" in toolbox.detect_audio_anomalies(clipped)["anomalies"]
        assert "dc_offset" in toolbox.detect_audio_anomalies(dc)["anomalies"]
        assert "silent" in toolbox.detect_audio_anomalies(silent)["anomalies"]
        assert "too_short" in toolbox.detect_audio_anomalies(short)["anomalies"]
        assert toolbox.detect_audio_anomalies(empty)["anomalies"] == ["empty"]

        # Policy-based checks only fire when an expected set is supplied.
        sr44 = os.path.join(root, "sr44.wav")
        sf.write(sr44, (0.1 * np.sin(2 * math.pi * 1000 * np.arange(int(2 * 44100)) / 44100)).astype(np.float32), 44100)
        res = toolbox.detect_audio_anomalies(sr44, expected_sample_rates=[48000], expected_channels=[1])
        assert "abnormal_sample_rate" in res["anomalies"]
        print("test_detect_audio_anomalies_flags_each_defect_type: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_detect_directory_anomalies_returns_only_flagged_with_tally():
    """Phase 2: batch scan returns only files with anomalies plus a per-code tally,
    and excludes .bak backups."""
    root = tempfile.mkdtemp(prefix="异常目录_")
    sr = 48000
    try:
        toolbox = AgentToolbox(None, DummyWaapi())
        n = int(2.0 * sr)
        t = np.arange(n) / sr
        sf.write(os.path.join(root, "clean.wav"), (0.1 * np.sin(2 * math.pi * 1000 * t)).astype(np.float32), sr)
        sf.write(os.path.join(root, "silent.wav"), np.zeros(n, dtype=np.float32), sr)
        # a backup file that is itself silent — must be skipped by the scan
        sf.write(os.path.join(root, "clean.bak.wav"), np.zeros(n, dtype=np.float32), sr)

        report = toolbox.detect_directory_anomalies(root)
        flagged_names = {r["file"] for r in report["results"]}
        assert flagged_names == {"silent.wav"}, f"only silent.wav should be flagged, got {flagged_names}"
        assert report["summary"]["anomaly_tally"].get("silent") == 1
        assert report["summary"]["scanned_count"] == 2, "the .bak file must be excluded from the scan"
        print("test_detect_directory_anomalies_returns_only_flagged_with_tally: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_validate_project_structure_flags_empty_missing_and_naming():
    """Phase 3: structure validation flags empty containers, missing source files,
    and naming-convention violations, using custom rules passed in directly."""
    root = tempfile.mkdtemp(prefix="结构校验_")
    try:
        real_wav = os.path.join(root, "exists.wav")
        open(real_wav, "wb").close()

        descendants = [
            {"id": "{1}", "name": "SFX_Footstep", "type": "Sound",
             "path": "\\X\\SFX_Footstep", "childrenCount": 1, "originalFilePath": real_wav},
            {"id": "{2}", "name": "EmptyCont", "type": "RandomSequenceContainer",
             "path": "\\X\\EmptyCont", "childrenCount": 0},
            {"id": "{3}", "name": "badname", "type": "Sound",
             "path": "\\X\\badname", "childrenCount": 1,
             "originalFilePath": os.path.join(root, "gone.wav")},
        ]

        class StructureWaapi:
            connected = True

            def get_version_context(self):
                return {"year": 2023}

            def call(self, uri, args=None, options=None):
                frm = (args or {}).get("from", {})
                if frm.get("path", [None])[0] == "\\Actor-Mixer Hierarchy":
                    return {"return": descendants}
                return {"return": []}

        toolbox = AgentToolbox(None, StructureWaapi())
        rules = {
            "naming": {"patterns": {"sound": "SFX_.*"}, "ignore_types": ["workunit", "folder"]},
            "structure": {"flag_empty_containers": True, "flag_missing_source_files": True},
        }
        report = toolbox.validate_project_structure(scope="project", rules=rules)
        tally = report["summary"]["issue_tally"]
        assert tally.get("empty_container") == 1
        assert tally.get("missing_source_file") == 1
        assert tally.get("naming_violation") == 1
        # SFX_Footstep is well-named, has children, and its file exists -> no issue
        assert all(i["object_name"] != "SFX_Footstep" for i in report["results"])
        print("test_validate_project_structure_flags_empty_missing_and_naming: OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_validate_project_structure_disconnected_is_graceful():
    """Phase 3: with no Wwise connection the validator returns a warning, not an error."""
    class Disconnected:
        connected = False

    toolbox = AgentToolbox(None, Disconnected())
    report = toolbox.validate_project_structure(scope="project", rules={})
    assert report["count"] == 0
    assert any("未连接 Wwise" in w for w in report["warnings"])
    print("test_validate_project_structure_disconnected_is_graceful: OK")


def test_load_audio_rules_seeds_default_and_deep_merges(tmp_path, monkeypatch):
    """Phase 3: loader seeds the default config when missing and deep-merges a
    partial user override over the built-in defaults."""
    import src.utils.app_paths as app_paths
    rules_file = tmp_path / "audio_rules.json"
    monkeypatch.setattr(app_paths, "AUDIO_RULES_FILE", rules_file, raising=False)

    toolbox = AgentToolbox(None, DummyWaapi())
    seeded = toolbox._load_audio_rules()
    assert rules_file.is_file(), "default config should be written when missing"
    assert set(seeded.keys()) == {"naming", "audio", "structure"}

    rules_file.write_text('{"naming": {"patterns": {"sound": "SFX_.*"}}}', encoding="utf-8")
    merged = toolbox._load_audio_rules()
    assert merged["naming"]["patterns"]["sound"] == "SFX_.*"
    # untouched default keys survive the merge
    assert merged["naming"]["ignore_types"] == ["workunit", "folder", "virtualfolder"]
    assert merged["structure"]["flag_empty_containers"] is True
    print("test_load_audio_rules_seeds_default_and_deep_merges: OK")


if __name__ == "__main__":
    test_analyze_directory_loudness_handles_short_wavs_and_empty_dirs()
    test_loudness_multichannel_downmix_returns_value_with_warning()
    test_loudness_short_audio_converges_after_compensation()
    test_true_peak_exceeds_sample_peak_on_intersample_overs()
    test_directory_loudness_compliance_flags_and_sorts()
    test_batch_normalize_dry_run_then_apply()
    test_batch_normalize_apply_blocked_in_ask_mode()
    test_normalize_atomic_write_preserves_original_on_failure()
    test_normalize_immediate_write_backs_up_and_changes_target()
    test_normalize_staged_defers_write_until_flush()
    test_normalize_blocked_in_ask_mode()
    test_detect_audio_anomalies_flags_each_defect_type()
    test_detect_directory_anomalies_returns_only_flagged_with_tally()
    test_validate_project_structure_flags_empty_missing_and_naming()
    test_validate_project_structure_disconnected_is_graceful()
    test_write_file_tree_stages_files_for_confirmation()
    test_turn_controller_blocks_ask_mode_local_write_code_and_warns_empty_results()

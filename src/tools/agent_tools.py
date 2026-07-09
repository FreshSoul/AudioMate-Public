"""Tool wrappers around AgentToolbox capabilities.

These are thin delegations that give the existing helper methods a
standardised Tool protocol interface.  The underlying logic stays in
``AgentToolbox`` — these wrappers exist so the registry / turn-controller
can discover, validate, and invoke them uniformly.
"""

from __future__ import annotations

from src.tools.base import (
    Tool,
    ToolContext,
    ToolResult,
    ToolResultStatus,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# File Access
# ---------------------------------------------------------------------------

class FileAccessTool(Tool):
    """Read an authorised local file."""

    @property
    def name(self) -> str:
        return "read_user_file"

    @property
    def description(self) -> str:
        return "Read the contents of a user-authorised local file."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file."},
                "max_chars": {"type": "integer", "default": 20000},
            },
            "required": ["path"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def is_concurrency_safe(self) -> bool:
        return True

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        if not input.get("path"):
            return ValidationResult(valid=False, error="path is required")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        try:
            content = toolbox.read_user_file(
                input["path"],
                max_chars=input.get("max_chars", 20000),
            )
            return ToolResult(output=content)
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


class ListDirectoryTool(Tool):
    """List contents of a local directory."""

    @property
    def name(self) -> str:
        return "list_local_directory"

    @property
    def description(self) -> str:
        return "List files and subdirectories of a local path."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list."},
            },
            "required": ["path"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def is_concurrency_safe(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        try:
            result = toolbox.list_local_directory(input["path"])
            import json
            return ToolResult(output=json.dumps(result, ensure_ascii=False, indent=2), data=result)
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


class WriteUserFileTool(Tool):
    """Write a text file to the local filesystem (user-authorised path)."""

    @property
    def name(self) -> str:
        return "write_user_file"

    @property
    def description(self) -> str:
        return (
            "Write text content to a local file. Supports paths like "
            "'~/Desktop/foo.md' (Windows: %USERPROFILE%\\Desktop\\foo.md). "
            "Use this to save generated documents, SKILL.md, scripts, etc."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path or '~/...' path of the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "Full text content to write.",
                },
                "overwrite": {
                    "type": "boolean",
                    "default": True,
                    "description": "Overwrite the file if it already exists.",
                },
                "mkdir": {
                    "type": "boolean",
                    "default": True,
                    "description": "Create parent directories if missing.",
                },
                "encoding": {"type": "string", "default": "utf-8"},
            },
            "required": ["path", "content"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        if not input.get("path"):
            return ValidationResult(valid=False, error="path is required")
        if "content" not in input:
            return ValidationResult(valid=False, error="content is required")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        if context.mode == "Ask Mode":
            return ToolResult(
                "write_user_file is a write operation and is not available in Ask Mode.",
                ToolResultStatus.PERMISSION_DENIED,
            )
        try:
            code_executor = context.extra.get("code_executor") if isinstance(context.extra, dict) else None
            stage_file_write = getattr(code_executor, "stage_file_write", None)
            if callable(stage_file_write):
                plan = toolbox.build_file_tree_entries(
                    ".",
                    [{"relative_path": input["path"], "content": input.get("content", "")}],
                    encoding=str(input.get("encoding", "utf-8")),
                ) if not str(input["path"]).strip().startswith(("~", "/", "\\")) and ":" not in str(input["path"]) else None
                if plan:
                    entry = plan["files"][0]
                    staged = stage_file_write(entry["path"], entry["content"], encoding=entry["encoding"])
                    payload = {"path": entry["path"], "name": entry["relative_path"], "size": entry["size"], "encoding": entry["encoding"], "staged": True, "staged_write": staged}
                else:
                    staged = stage_file_write(input["path"], input.get("content", ""), encoding=str(input.get("encoding", "utf-8")))
                    payload = {"path": staged["path"], "name": staged["path"].split("\\")[-1].split("/")[-1], "size": staged["size"], "encoding": str(input.get("encoding", "utf-8")), "staged": True, "staged_write": staged}
                import json
                return ToolResult(
                    output=json.dumps(payload, ensure_ascii=False, indent=2),
                    data=payload,
                )
            result = toolbox.write_user_file(
                input["path"],
                input.get("content", ""),
                overwrite=bool(input.get("overwrite", True)),
                mkdir=bool(input.get("mkdir", True)),
                encoding=str(input.get("encoding", "utf-8")),
            )
            import json
            return ToolResult(
                output=f"已写入 {result['path']}（{result['size']} bytes）",
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


class WriteFileTreeTool(Tool):
    """Stage a multi-file text tree for user confirmation."""

    @property
    def name(self) -> str:
        return "write_file_tree"

    @property
    def description(self) -> str:
        return "Create or overwrite multiple text files under one base directory, for Skill folders, script packs, and reports."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "base_dir": {"type": "string", "description": "Absolute path or ~/ path of the root directory."},
                "files": {
                    "type": "array",
                    "description": "Files to write. Each item uses relative_path and content.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "relative_path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["relative_path", "content"],
                    },
                },
                "encoding": {"type": "string", "default": "utf-8"},
            },
            "required": ["base_dir", "files"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def side_effects(self) -> list[str]:
        return ["local-file"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        if not input.get("base_dir"):
            return ValidationResult(valid=False, error="base_dir is required")
        if not isinstance(input.get("files"), list) or not input.get("files"):
            return ValidationResult(valid=False, error="files must be a non-empty array")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        if context.mode == "Ask Mode":
            return ToolResult(
                "write_file_tree is a write operation and is not available in Ask Mode.",
                ToolResultStatus.PERMISSION_DENIED,
            )
        try:
            import json
            plan = toolbox.build_file_tree_entries(
                input["base_dir"],
                input.get("files") or [],
                encoding=str(input.get("encoding", "utf-8")),
            )
            code_executor = context.extra.get("code_executor") if isinstance(context.extra, dict) else None
            stage_file_write = getattr(code_executor, "stage_file_write", None)
            if not callable(stage_file_write):
                return ToolResult("Error: code executor does not support staged file writes", ToolResultStatus.ERROR)
            staged = []
            for entry in plan["files"]:
                staged.append(stage_file_write(entry["path"], entry["content"], encoding=entry["encoding"]))
            payload = {k: v for k, v in plan.items() if k != "files"}
            payload["ok"] = True
            payload["count"] = plan["file_count"]
            payload["pending_confirmation"] = True
            payload["files"] = [{"relative_path": item["relative_path"], "path": item["path"], "size": item["size"]} for item in plan["files"]]
            payload["staged"] = staged
            return ToolResult(
                output=json.dumps(payload, ensure_ascii=False, indent=2),
                data=payload,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


# ---------------------------------------------------------------------------
# Audio Analysis
# ---------------------------------------------------------------------------

class AudioAnalysisTool(Tool):
    """Analyse a single audio file (LUFS, spectrum, etc.)."""

    @property
    def name(self) -> str:
        return "analyze_audio_file"

    @property
    def description(self) -> str:
        return "Analyse an audio file for loudness (LUFS), spectral peaks, and duration."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to audio file."},
                "top_n_frequencies": {"type": "integer", "default": 5},
            },
            "required": ["path"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        try:
            result = toolbox.analyze_audio_file(
                input["path"],
                top_n_frequencies=input.get("top_n_frequencies", 5),
            )
            import json
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


class SelectedSourceLoudnessTool(Tool):
    """Batch-analyse loudness for Wwise-selected source files."""

    @property
    def name(self) -> str:
        return "analyze_selected_source_files_loudness"

    @property
    def description(self) -> str:
        return "Analyse loudness of source audio files attached to currently selected Wwise objects."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max files to analyse (null = all)."},
            },
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        try:
            result = toolbox.analyze_selected_source_files_loudness(
                limit=input.get("limit"),
            )
            import json
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


class DirectoryLoudnessTool(Tool):
    """Batch-analyse loudness for audio files in a local directory."""

    @property
    def name(self) -> str:
        return "analyze_directory_loudness"

    @property
    def description(self) -> str:
        return "Analyse all matching audio files in a local folder and return per-file loudness rows plus a summary."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Local directory or audio file path."},
                "recursive": {"type": "boolean", "default": True},
                "extensions": {"type": "array", "items": {"type": "string"}, "default": [".wav"]},
                "limit": {"type": "integer", "description": "Optional max files to analyse."},
                "top_n_frequencies": {"type": "integer", "default": 5},
            },
            "required": ["path"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        try:
            import json
            result = toolbox.analyze_directory_loudness(
                input["path"],
                recursive=input.get("recursive") is not False,
                extensions=input.get("extensions") if isinstance(input.get("extensions"), list) else None,
                limit=input.get("limit"),
                top_n_frequencies=input.get("top_n_frequencies", 5),
            )
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


class NormalizeLoudnessTool(Tool):
    """Normalize a local audio file to a target LUFS."""

    @property
    def name(self) -> str:
        return "normalize_audio_loudness"

    @property
    def description(self) -> str:
        return "Normalize an audio file to a target integrated loudness (LUFS)."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the audio file."},
                "target_lufs": {"type": "number", "default": -16.0},
                "backup": {"type": "boolean", "default": True},
            },
            "required": ["path"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def side_effects(self) -> list[str]:
        return ["local-file"]

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        if context.mode == "Ask Mode":
            return ToolResult(
                "normalize_audio_loudness is a write operation and is not available in Ask Mode.",
                ToolResultStatus.PERMISSION_DENIED,
            )
        try:
            result = toolbox.normalize_audio_loudness(
                input["path"],
                target_lufs=input.get("target_lufs", -16.0),
                backup=input.get("backup", True),
            )
            import json
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


class DirectoryLoudnessComplianceTool(Tool):
    """Health-check a folder of audio against a target LUFS range + true-peak limit."""

    @property
    def name(self) -> str:
        return "check_directory_loudness_compliance"

    @property
    def description(self) -> str:
        return (
            "Analyse a local folder and flag files outside a target loudness range "
            "or over a true-peak limit. Returns per-file pass/fail plus a worst-first "
            "non-compliant list in summary.compliance. Read-only — does not modify files."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Local directory or audio file path."},
                "target_lufs_min": {"type": "number", "default": -16.0},
                "target_lufs_max": {"type": "number", "default": -12.0},
                "true_peak_limit_dbfs": {"type": "number", "default": -1.0},
                "recursive": {"type": "boolean", "default": True},
                "extensions": {"type": "array", "items": {"type": "string"}, "default": [".wav"]},
                "limit": {"type": "integer", "description": "Optional max files to analyse."},
            },
            "required": ["path"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        try:
            import json
            result = toolbox.check_directory_loudness_compliance(
                input["path"],
                target_lufs_min=input.get("target_lufs_min", -16.0),
                target_lufs_max=input.get("target_lufs_max", -12.0),
                true_peak_limit_dbfs=input.get("true_peak_limit_dbfs", -1.0),
                recursive=input.get("recursive") is not False,
                extensions=input.get("extensions") if isinstance(input.get("extensions"), list) else None,
                limit=input.get("limit"),
            )
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


class BatchNormalizeDirectoryTool(Tool):
    """Batch-normalize a folder to a target LUFS (dry-run first, then apply)."""

    @property
    def name(self) -> str:
        return "batch_normalize_directory_to_target"

    @property
    def description(self) -> str:
        return (
            "Batch-normalize non-compliant audio in a folder to a target LUFS. "
            "By default this is a DRY RUN (apply=False) that returns the plan and writes nothing; "
            "call again with apply=True to perform the irreversible normalization. "
            "Agent Mode only."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Local directory or audio file path."},
                "target_lufs": {"type": "number", "default": -16.0},
                "target_lufs_min": {"type": "number", "description": "Lower bound of the 'already compliant' window."},
                "target_lufs_max": {"type": "number", "description": "Upper bound of the 'already compliant' window."},
                "true_peak_limit_dbfs": {"type": "number", "default": -1.0},
                "only_noncompliant": {"type": "boolean", "default": True},
                "recursive": {"type": "boolean", "default": True},
                "extensions": {"type": "array", "items": {"type": "string"}, "default": [".wav"]},
                "limit": {"type": "integer", "description": "Optional max files."},
                "backup": {"type": "boolean", "default": True},
                "apply": {"type": "boolean", "default": False, "description": "False = dry run (no writes); True = apply."},
            },
            "required": ["path"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        # A dry run writes nothing; only apply=True mutates files.
        if isinstance(input, dict):
            return not bool(input.get("apply"))
        return False

    def side_effects(self) -> list[str]:
        return ["local-file"]

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        if context.mode == "Ask Mode" and bool(input.get("apply")):
            return ToolResult(
                "batch_normalize_directory_to_target with apply=True is a write operation and is not available in Ask Mode.",
                ToolResultStatus.PERMISSION_DENIED,
            )
        try:
            import json
            result = toolbox.batch_normalize_directory_to_target(
                input["path"],
                target_lufs=input.get("target_lufs", -16.0),
                target_lufs_min=input.get("target_lufs_min"),
                target_lufs_max=input.get("target_lufs_max"),
                true_peak_limit_dbfs=input.get("true_peak_limit_dbfs", -1.0),
                only_noncompliant=input.get("only_noncompliant") is not False,
                recursive=input.get("recursive") is not False,
                extensions=input.get("extensions") if isinstance(input.get("extensions"), list) else None,
                limit=input.get("limit"),
                backup=input.get("backup") is not False,
                apply=bool(input.get("apply")),
            )
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)



# ---------------------------------------------------------------------------
# Audio anomaly detection (silence / clipping / DC offset / true-peak over)
# ---------------------------------------------------------------------------

class AudioAnomalyTool(Tool):
    """Detect defects in a single audio file."""

    @property
    def name(self) -> str:
        return "detect_audio_anomalies"

    @property
    def description(self) -> str:
        return (
            "Detect defects in one audio file: clipping (consecutive-sample runs), "
            "DC offset, (near) silence, inter-sample true-peak overs, too-short, and "
            "optionally abnormal sample rate / channel count. Read-only. Returns metrics "
            "plus an 'anomalies' code list and 'has_anomaly'."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to audio file."},
                "clip_threshold": {"type": "number", "default": 0.999},
                "clip_min_run": {"type": "integer", "default": 3},
                "silence_rms_dbfs": {"type": "number", "default": -60.0},
                "dc_offset_warn": {"type": "number", "default": 0.01},
                "true_peak_over_dbfs": {"type": "number", "default": 0.0},
                "expected_sample_rates": {"type": "array", "items": {"type": "integer"}},
                "expected_channels": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["path"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        try:
            import json
            result = toolbox.detect_audio_anomalies(
                input["path"],
                clip_threshold=input.get("clip_threshold"),
                clip_min_run=input.get("clip_min_run"),
                silence_rms_dbfs=input.get("silence_rms_dbfs"),
                dc_offset_warn=input.get("dc_offset_warn"),
                true_peak_over_dbfs=input.get("true_peak_over_dbfs"),
                expected_sample_rates=input.get("expected_sample_rates"),
                expected_channels=input.get("expected_channels"),
            )
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


class DirectoryAnomalyTool(Tool):
    """Batch anomaly scan over a local folder."""

    @property
    def name(self) -> str:
        return "detect_directory_anomalies"

    @property
    def description(self) -> str:
        return (
            "Scan a local folder for audio defects (clipping, DC offset, silence, "
            "true-peak overs, too-short, abnormal sample rate/channels). Lightweight — "
            "skips LUFS/spectrum. Read-only. Returns only flagged files plus a per-code "
            "tally in summary."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Local directory or audio file path."},
                "recursive": {"type": "boolean", "default": True},
                "extensions": {"type": "array", "items": {"type": "string"}, "default": [".wav"]},
                "limit": {"type": "integer", "description": "Optional max files."},
                "clip_threshold": {"type": "number", "default": 0.999},
                "clip_min_run": {"type": "integer", "default": 3},
                "silence_rms_dbfs": {"type": "number", "default": -60.0},
                "dc_offset_warn": {"type": "number", "default": 0.01},
                "true_peak_over_dbfs": {"type": "number", "default": 0.0},
                "expected_sample_rates": {"type": "array", "items": {"type": "integer"}},
                "expected_channels": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["path"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        try:
            import json
            result = toolbox.detect_directory_anomalies(
                input["path"],
                recursive=input.get("recursive") is not False,
                extensions=input.get("extensions") if isinstance(input.get("extensions"), list) else None,
                limit=input.get("limit"),
                clip_threshold=input.get("clip_threshold"),
                clip_min_run=input.get("clip_min_run"),
                silence_rms_dbfs=input.get("silence_rms_dbfs"),
                dc_offset_warn=input.get("dc_offset_warn"),
                true_peak_over_dbfs=input.get("true_peak_over_dbfs"),
                expected_sample_rates=input.get("expected_sample_rates"),
                expected_channels=input.get("expected_channels"),
            )
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)



# ---------------------------------------------------------------------------
# Project structure / naming validation
# ---------------------------------------------------------------------------

class ProjectStructureValidationTool(Tool):
    """Validate Wwise project structure + naming against config rules."""

    @property
    def name(self) -> str:
        return "validate_project_structure"

    @property
    def description(self) -> str:
        return (
            "Validate Wwise project structure against config rules (config/audio_rules.json): "
            "empty containers, objects whose originalFilePath is missing on disk, and naming-convention "
            "violations. scope='project' walks the hierarchy roots; scope='selection' uses the current "
            "selection + descendants. Read-only; requires a live Wwise connection."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["project", "selection"], "default": "project"},
            },
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        try:
            import json
            result = toolbox.validate_project_structure(
                scope=input.get("scope", "project"),
            )
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)



# ---------------------------------------------------------------------------
# Source file queries
# ---------------------------------------------------------------------------

class SourceFileTool(Tool):
    """Query source files attached to Wwise objects."""

    @property
    def name(self) -> str:
        return "get_selected_source_files"

    @property
    def description(self) -> str:
        return "Get local source audio file paths for the currently selected Wwise objects."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        try:
            result = toolbox.get_selected_source_files()
            import json
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


class ProjectSourceFileTool(Tool):
    """Query all source files in the Wwise project."""

    @property
    def name(self) -> str:
        return "get_project_source_files"

    @property
    def description(self) -> str:
        return "Get all source audio file entries from the Wwise project."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "object_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of parent object IDs to scope the query.",
                },
                "object_type": {"type": "string", "default": "Sound"},
            },
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return True

    def requires_waapi(self) -> bool:
        return True

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        try:
            result = toolbox.get_project_source_files(
                object_ids=input.get("object_ids"),
                object_type=input.get("object_type", "Sound"),
            )
            import json
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)


class ImportAudioToSelectedWwiseTool(Tool):
    """Import local audio files under the currently selected Wwise object."""

    @property
    def name(self) -> str:
        return "import_audio_files_to_selected_wwise"

    @property
    def description(self) -> str:
        return "Import local audio files as Sound objects under the current Wwise selection."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute local audio file paths to import.",
                },
                "object_type": {"type": "string", "default": "Sound SFX"},
                "import_operation": {"type": "string", "default": "useExisting"},
                "import_language": {"type": "string", "default": "SFX"},
                "originals_sub_folder": {"type": "string", "default": ""},
                "wait_for_files": {"type": "boolean", "default": True},
                "file_ready_timeout": {"type": "number", "default": 30},
                "batch_size": {"type": "integer", "default": 20},
                "retry_on_copy_failure": {"type": "boolean", "default": True},
            },
            "required": ["paths"],
        }

    def is_read_only(self, input=None) -> bool:  # noqa: A002
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project", "wwise-originals"]

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        paths = input.get("paths")
        if not isinstance(paths, list) or not paths:
            return ValidationResult(valid=False, error="paths must be a non-empty array")
        return ValidationResult()

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        toolbox = context.toolbox
        if toolbox is None:
            return ToolResult("Error: toolbox not available", ToolResultStatus.ERROR)
        if context.mode == "Ask Mode":
            return ToolResult(
                "import_audio_files_to_selected_wwise is a write operation and is not available in Ask Mode.",
                ToolResultStatus.PERMISSION_DENIED,
            )
        try:
            result = toolbox.import_audio_files_to_selected_wwise(
                input.get("paths") or [],
                object_type=input.get("object_type", "Sound SFX"),
                import_operation=input.get("import_operation", "useExisting"),
                import_language=input.get("import_language", "SFX"),
                originals_sub_folder=input.get("originals_sub_folder", ""),
                wait_for_files=input.get("wait_for_files", True),
                file_ready_timeout=input.get("file_ready_timeout", 30),
                batch_size=input.get("batch_size", 20),
                retry_on_copy_failure=input.get("retry_on_copy_failure", True),
            )
            import json
            status = ToolResultStatus.SUCCESS if result.get("ok") else ToolResultStatus.ERROR
            return ToolResult(
                output=json.dumps(result, ensure_ascii=False, indent=2),
                status=status,
                data=result,
            )
        except Exception as exc:
            return ToolResult(str(exc), ToolResultStatus.ERROR)

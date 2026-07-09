"""Shared low-level parsing primitives.

This module is the single source of truth for code-block extraction /
validation. Both ``src.engine.response_parser`` and ``src.tools.waapi_code_tool``
import from here; the parsing module itself has no inbound deps from engine
or tools, which keeps the import graph a DAG.
"""

from __future__ import annotations

import re
import html
import json

_CODE_BLOCK_RE = re.compile(
    r"```(python_waapi|python|py)\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)

_PSEUDO_TOOL_TAG_RE = re.compile(
    r"<(?P<tag>tool_call|tool_use|function)\b[^>]*>(?P<body>.*?)</(?P=tag)>",
    re.DOTALL | re.IGNORECASE,
)

_SAFE_TOOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")

_CODE_TOOL_NAMES = frozenset({
    "python",
    "python_waapi",
    "waapi_code",
    "waapi_python_exec",
})

_DIRECT_HELPERS = frozenset({
    "analyze_audio_file",
    "analyze_wav_file",
    "analyze_directory_loudness",
    "check_directory_loudness_compliance",
    "batch_normalize_directory_to_target",
    "detect_audio_anomalies",
    "detect_directory_anomalies",
    "validate_project_structure",
    "analyze_selected_source_files_loudness",
    "analyze_project_source_files_loudness",
    "analyze_selected_sources_full_route_loudness",
    "normalize_audio_loudness",
    "import_audio_files_to_selected_wwise",
    "get_selected_source_files",
    "get_project_source_files",
    "get_selected_source_filepaths",
    "read_user_file",
    "list_local_directory",
    "describe_local_path",
    "write_user_file",
    "write_file_tree",
    "fetch_webpage",
    "call_mcp_tool",
    "read_feishu_doc",
    "lookup_waapi_doc",
    "search_waapi_functions",
    "get_active_mcp_config",
    "list_mcp_tools",
})

_POSITIONAL_HELPER_KEYS = {
    "analyze_audio_file": ("path", "file", "filepath"),
    "analyze_wav_file": ("path", "file", "filepath"),
    "analyze_directory_loudness": ("path", "directory", "folder", "dir"),
    "check_directory_loudness_compliance": ("path", "directory", "folder", "dir"),
    "batch_normalize_directory_to_target": ("path", "directory", "folder", "dir"),
    "detect_audio_anomalies": ("path", "file", "filepath"),
    "detect_directory_anomalies": ("path", "directory", "folder", "dir"),
    "normalize_audio_loudness": ("path", "file", "filepath"),
    "import_audio_files_to_selected_wwise": ("paths", "files", "filepaths"),
    "read_user_file": ("path", "file", "filepath"),
    "list_local_directory": ("path", "directory", "folder", "dir"),
    "describe_local_path": ("path", "file", "directory"),
    "fetch_webpage": ("url", "uri"),
    "read_feishu_doc": ("url_or_id", "url", "document_id"),
    "lookup_waapi_doc": ("uri_or_keyword", "uri", "keyword", "query"),
    "search_waapi_functions": ("keyword", "query", "uri_or_keyword"),
}

# Anchored error markers — match only at the start of a line so legitimate
# successful prints like ``print("No errors found")`` or
# ``print("captured Exception types: 0")`` don't get flagged as errors.
#
# Shapes we want to catch:
#   - ``Traceback (most recent call last):``  (Python's standard traceback header)
#   - ``ValueError: ...``  (terminal exception line, ``XxxError:`` / ``XxxException:``)
#   - ``Error executing code: ...``  (our CodeExecutor failure prefix)
#   - ``Unhandled Exception: ...``  (worker-thread failure prefix)
#   - ``[Error] message``  (internal tool-error convention)
#
# All matchers require a start-of-line + uppercase first letter, so a
# substring inside legitimate prose ("no errors found", "0 exception
# types") cannot trigger them.
_ERROR_LINE_RE = re.compile(
    r"(?m)^(?:"
    r"Traceback \(most recent call last\)"
    r"|[A-Z][A-Za-z0-9_]*(?:Error|Exception):"      # e.g. ValueError:, KeyError:
    r"|Error\b[^\n]*"                                 # e.g. Error executing code: ...
    r"|[A-Z][A-Za-z0-9_]*(?:[ \t][A-Za-z0-9_]+)* (?:Error|Exception):"  # "Unhandled Exception:"
    r"|\[Error\]"
    r")"
)


def extract_code_blocks(response_text: str) -> list[dict[str, str]]:
    """Return fenced Python code blocks from *response_text*."""
    return [
        {
            "language": match.group(1).lower(),
            "code": match.group(2),
            "fence": match.group(0),
        }
        for match in _CODE_BLOCK_RE.finditer(response_text or "")
    ]


def _literal(value) -> str:
    return repr(value)


def _safe_tool_name(name: str) -> str:
    candidate = str(name or "").strip()
    return candidate if _SAFE_TOOL_NAME_RE.fullmatch(candidate) else ""


def _raw_decode_json_object(text: str):
    start = text.find("{")
    if start < 0:
        return None, "", text.strip()
    prefix = text[:start].strip()
    try:
        payload, _end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None, "", prefix
    return payload if isinstance(payload, dict) else None, prefix, ""


def _prefix_tool_name(prefix: str) -> str:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", prefix or "")
    return _safe_tool_name(tokens[-1]) if tokens else ""


def _normalise_tool_payload(body: str) -> tuple[str, dict | str | list | None]:
    body = html.unescape(body or "").strip()
    if not body:
        return "", None
    payload, prefix, bare = _raw_decode_json_object(body)
    if payload is None:
        return _prefix_tool_name(bare or prefix), {}
    name = _safe_tool_name(payload.get("name") or payload.get("tool") or _prefix_tool_name(prefix))
    input_data = None
    for key in ("input", "arguments", "args"):
        if key in payload:
            input_data = payload.get(key)
            break
    if input_data is None:
        input_data = {k: v for k, v in payload.items() if k not in {"name", "tool"}}
    return name, input_data


def _call_mcp_tool_expr(input_data) -> str:
    payload = dict(input_data) if isinstance(input_data, dict) else {}
    tool_name = payload.pop("tool_name", None) or payload.pop("name", None) or payload.pop("tool", None)
    if tool_name:
        arguments = payload.pop("arguments", payload.pop("args", None))
        pieces = [_literal(tool_name)]
        if arguments is not None:
            pieces.append(f"arguments={_literal(arguments)}")
        if "timeout_seconds" in payload:
            pieces.append(f"timeout_seconds={_literal(payload.pop('timeout_seconds'))}")
        if "config_name" in payload:
            pieces.append(f"config_name={_literal(payload.pop('config_name'))}")
        if payload:
            pieces.append(f"**{_literal(payload)}")
        return f"call_mcp_tool({', '.join(pieces)})"
    return f"call_mcp_tool(**{_literal(payload)})"


def _direct_helper_expr(name: str, input_data) -> str:
    if name == "call_mcp_tool":
        return _call_mcp_tool_expr(input_data)
    if input_data is None:
        return f"{name}()"
    if not isinstance(input_data, dict):
        return f"{name}({_literal(input_data)})"
    payload = dict(input_data)
    first_value = None
    for key in _POSITIONAL_HELPER_KEYS.get(name, ()):
        if key in payload:
            first_value = payload.pop(key)
            break
    if first_value is not None:
        if payload:
            return f"{name}({_literal(first_value)}, **{_literal(payload)})"
        return f"{name}({_literal(first_value)})"
    if payload:
        return f"{name}(**{_literal(payload)})"
    return f"{name}()"


def _code_from_pseudo_tool_call(name: str, input_data) -> str:
    name = _safe_tool_name(name)
    if not name:
        return ""
    if name in _CODE_TOOL_NAMES:
        if isinstance(input_data, dict):
            code = input_data.get("code") or input_data.get("python") or input_data.get("script")
        else:
            code = input_data
        return str(code or "").strip()
    if name == "call_structured_tool":
        payload = dict(input_data) if isinstance(input_data, dict) else {}
        tool_name = payload.pop("tool_name", None) or payload.pop("name", None) or payload.pop("tool", None)
        tool_input = payload.pop("input", payload.pop("arguments", payload.pop("args", {})))
        if not tool_name:
            return ""
        return f"result = call_structured_tool({_literal(tool_name)}, {_literal(tool_input)})\nprint(result)"
    if name in _DIRECT_HELPERS:
        return f"result = {_direct_helper_expr(name, input_data)}\nprint(result)"
    if name.startswith("waapi."):
        payload = input_data if isinstance(input_data, dict) else {}
        return f"result = call_structured_tool({_literal(name)}, {_literal(payload)})\nprint(result)"
    return ""


def extract_pseudo_tool_code_blocks(response_text: str) -> list[dict[str, str]]:
    """Convert safe XML-like tool tags into synthetic executable code blocks.

    Some models emit ``<tool_call>``/``<tool_use>``/``<function>`` tags even
    though AudioMate executes fenced ``python_waapi`` blocks.  This parser
    treats those tags as a compatibility format, but intentionally ignores
    ``<tool_response>`` and any unknown tool names.
    """
    blocks: list[dict[str, str]] = []
    for match in _PSEUDO_TOOL_TAG_RE.finditer(response_text or ""):
        name, input_data = _normalise_tool_payload(match.group("body"))
        code = _code_from_pseudo_tool_call(name, input_data)
        if code:
            blocks.append({
                "language": "python_waapi",
                "code": code,
                "fence": match.group(0),
                "tool_name": name,
            })
    return blocks


def is_valid_python_code(code: str) -> bool:
    """Return True if *code* compiles as valid Python."""
    try:
        compile(code, "<llm_code>", "exec")
        return True
    except (SyntaxError, ValueError, OverflowError):
        return False


def strip_code_fences(text: str) -> str:
    """Remove supported code-fence blocks from *text*."""
    return _CODE_BLOCK_RE.sub("", text or "").strip()


def output_has_error(output: str) -> bool:
    """Return True if output contains a Python traceback or terminal exception line.

    Uses anchored matching so substrings inside legitimate prose
    (``"No errors found"``, ``"captured Exception types: 0"``) don't
    falsely trigger the retry pipeline.
    """
    return bool(_ERROR_LINE_RE.search(output or ""))


__all__ = [
    "extract_code_blocks",
    "extract_pseudo_tool_code_blocks",
    "is_valid_python_code",
    "strip_code_fences",
    "output_has_error",
]

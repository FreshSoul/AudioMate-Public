"""WaapiCodeTool — executes python_waapi code blocks against Wwise via WAAPI.

This is the core tool of AudioMate: it takes generated Python code,
runs it in a sandboxed CodeExecutor with WAAPI bindings, optionally wraps
the operation in an undo group, and returns structured output.
"""

from __future__ import annotations

import re

from src.tools.base import (
    Tool,
    ToolContext,
    ToolResult,
    ToolResultStatus,
    ValidationResult,
)
from src.utils.parsing import extract_code_blocks, output_has_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WAAPI_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwaapi_client\b",
        r"\bget_project_source_files\s*\(",
        r"\bget_selected_source_files\s*\(",
        r"\banalyze_selected_source_files_loudness\s*\(",
        r"\banalyze_project_source_files_loudness\s*\(",
        r"\banalyze_selected_sources_full_route_loudness\s*\(",
        r"\bget_selected_objects\s*\(",
        r"\bget_property\s*\(",
        r"\bset_property\s*\(",
        r"ak\.(?:wwise|soundengine)\.",
    )
]


def code_uses_waapi(code: str) -> bool:
    """Return True if *code* references WAAPI client or known WAAPI helpers."""
    if not code:
        return False
    return any(p.search(code) for p in _WAAPI_PATTERNS)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class WaapiCodeTool(Tool):
    """Execute a ``python_waapi`` code block inside the sandbox executor."""

    @property
    def name(self) -> str:
        return "waapi_code"

    @property
    def description(self) -> str:
        return (
            "Execute a Python code block with WAAPI bindings to read or "
            "modify the Wwise project."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute (may include fence markers).",
                },
                "use_undo_group": {
                    "type": "boolean",
                    "description": "Wrap execution in a Wwise undo group.",
                    "default": True,
                },
            },
            "required": ["code"],
        }

    # -- metadata --------------------------------------------------------

    def is_read_only(self, input: dict | None = None) -> bool:  # noqa: A002
        if input and "code" in input:
            return not code_uses_waapi(input["code"])
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def requires_waapi(self) -> bool:
        return True

    def side_effects(self) -> list[str]:
        return ["wwise-project"]

    def prompt(self) -> str:
        return (
            "Execute Python code with access to `waapi_client` (WAAPI), "
            "`toolbox` helpers (file access, audio analysis), and safe "
            "standard-library imports.  Wrap write operations in an undo "
            "group so the user can revert."
        )

    # -- validation ------------------------------------------------------

    def validate_input(self, input: dict) -> ValidationResult:  # noqa: A002
        code = input.get("code", "")
        if not code or not code.strip():
            return ValidationResult(valid=False, error="Empty code block")
        return ValidationResult()

    # -- execution -------------------------------------------------------

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        """Run *code* inside the ``CodeExecutor`` from *context*.

        Parameters
        ----------
        input : dict
            Must contain ``"code"`` (str).  Optional ``"use_undo_group"`` (bool).
        context : ToolContext
            Must carry ``waapi_client`` and a ``"code_executor"`` in ``extra``.
        """
        code: str = input.get("code", "")
        use_undo = input.get("use_undo_group", True)

        code_executor = context.extra.get("code_executor")
        if code_executor is None:
            return ToolResult(
                output="Error: no code_executor in context",
                status=ToolResultStatus.ERROR,
            )
        reset_cancel = getattr(code_executor, "reset_cancel", None)
        if callable(reset_cancel):
            reset_cancel()

        waapi = context.waapi_client
        undo_started = False

        # -- optional undo group -----------------------------------------
        if use_undo and waapi is not None:
            try:
                waapi.reset_changes()
                undo_started = waapi.begin_undo_group()
            except Exception:
                undo_started = False

        # -- run code ----------------------------------------------------
        try:
            output = code_executor.execute(code, context.mode)
        except Exception as exc:
            output = f"Error executing code: {exc}"

        # -- close undo group --------------------------------------------
        if undo_started and waapi is not None:
            try:
                waapi.end_undo_group()
            except Exception:
                pass

        # -- build result ------------------------------------------------
        has_error = output_has_error(output)
        has_changes = getattr(waapi, "has_changes", False) if waapi else False

        return ToolResult(
            output=output,
            status=ToolResultStatus.ERROR if has_error else ToolResultStatus.SUCCESS,
            data={
                "has_error": has_error,
                "has_changes": has_changes,
                "undo_started": undo_started,
                "uses_waapi": code_uses_waapi(code),
            },
        )

"""Tool protocol base classes for AudioMate.

Each tool is a standardized object with name, schema, execution logic, and
permission checks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.tools.permissions import is_ask_mode


class ToolResultStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    PERMISSION_DENIED = "permission_denied"


@dataclass
class ToolResult:
    """Standard return value from Tool.execute()."""

    output: str = ""
    status: ToolResultStatus = ToolResultStatus.SUCCESS
    data: Any = None  # structured payload (optional)

    @property
    def is_error(self) -> bool:
        return self.status != ToolResultStatus.SUCCESS

    def __str__(self) -> str:
        return self.output


@dataclass
class ValidationResult:
    valid: bool = True
    error: str = ""


@dataclass
class PermissionResult:
    allowed: bool = True
    reason: str = ""


@dataclass
class ToolContext:
    """Runtime context passed to every tool invocation."""

    waapi_client: Any = None
    toolbox: Any = None
    mode: str = "Agent Mode"  # "Agent Mode" | "Ask Mode"
    parent_widget: Any = None  # Qt widget for file dialogs, etc.
    extra: dict = field(default_factory=dict)


class Tool(ABC):
    """Abstract base class for all AudioMate tools.

    Subclasses must implement ``name``, ``description``, and ``execute``.
    Override the optional hooks for schema validation, permission checks,
    and read-only / concurrency metadata.
    """

    # -- identity --------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Machine-readable tool name (unique across registry)."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable one-liner shown to the LLM and in UI."""

    @property
    def input_schema(self) -> dict:
        """JSON Schema dict describing accepted ``input`` keys.

        Returns an empty schema by default (any dict accepted).
        """
        return {"type": "object", "properties": {}}

    # -- execution -------------------------------------------------------

    @abstractmethod
    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        """Run the tool and return a ``ToolResult``."""

    # -- optional hooks --------------------------------------------------

    def validate_input(self, input: dict) -> ValidationResult:
        """Pre-flight input validation (called before execute)."""
        return ValidationResult()

    def check_permissions(self, input: dict, context: ToolContext) -> PermissionResult:
        """Return whether the current context allows running this tool."""
        if is_ask_mode(context.mode) and not self.is_read_only(input):
            return PermissionResult(
                allowed=False,
                reason=f"Tool '{self.name}' is not available in Ask Mode.",
            )
        return PermissionResult()

    def is_read_only(self, input: dict | None = None) -> bool:
        """True if the tool never mutates Wwise project state."""
        return False

    def is_concurrency_safe(self) -> bool:
        """True if multiple instances can run in parallel safely."""
        return False

    def requires_waapi(self) -> bool:
        """True if this tool requires a live Wwise/WAAPI connection."""
        return False

    def side_effects(self) -> list[str]:
        """Machine-readable side-effect categories for planning and review."""
        return [] if self.is_read_only() else ["unknown-write"]

    # -- prompt / display ------------------------------------------------

    def prompt(self) -> str:
        """Extended description injected into the LLM system prompt."""
        return self.description

    def user_facing_name(self) -> str:
        """Display name for UI progress widgets."""
        return self.name

    def manifest(self, *, source: str = "builtin", mode: str = "Agent Mode") -> dict:
        """Return machine-readable tool metadata for planners/executors."""
        return {
            "name": self.name,
            "display_name": self.user_facing_name(),
            "description": self.description,
            "prompt": self.prompt(),
            "input_schema": self.input_schema,
            "read_only": self.is_read_only(),
            "concurrency_safe": self.is_concurrency_safe(),
            "requires_waapi": self.requires_waapi(),
            "side_effects": self.side_effects(),
            "source": source,
            "available": not (mode == "Ask Mode" and not self.is_read_only()),
        }

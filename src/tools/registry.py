"""Tool registry — register, lookup, and enumerate tools."""

from __future__ import annotations

from typing import Iterator

from src.tools.base import Tool


class ToolRegistry:
    """Central catalogue of all available Tool instances."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # -- mutators --------------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a tool.  Raises ``ValueError`` on duplicate names."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """Remove a tool by name.  Returns True if it existed."""
        return self._tools.pop(name, None) is not None

    # -- lookups ---------------------------------------------------------

    def find_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def to_manifest(self, *, mode: str = "Agent Mode", source: str = "builtin") -> list[dict]:
        """Return machine-readable metadata for all registered tools."""
        return [tool.manifest(source=source, mode=mode) for tool in self._tools.values()]

    def build_tools_manifest_prompt(self, *, mode: str = "Agent Mode", source: str = "builtin") -> str:
        """Generate a compact JSON-like manifest block for planner prompts."""
        import json

        return json.dumps(self.to_manifest(mode=mode, source=source), ensure_ascii=False, indent=2)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    # -- prompt helpers --------------------------------------------------

    def build_tools_prompt(self) -> str:
        """Generate a tools-section string for the LLM system prompt."""
        if not self._tools:
            return ""
        lines = ["Available tools:"]
        for tool in self._tools.values():
            lines.append(f"- **{tool.user_facing_name()}**: {tool.prompt()}")
        return "\n".join(lines)

"""Structured planning primitives for AudioMate agent workflows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from src.tools.base import ToolContext
from src.tools.registry import ToolRegistry


_PLACEHOLDER_RE = re.compile(r"\{(?:[^{}]*id|[^{}]*path|todo|placeholder|xxx)[^{}]*\}", re.IGNORECASE)


@dataclass
class PlanStep:
    id: str
    title: str
    tool: str
    input: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    expected_outputs: dict[str, Any] = field(default_factory=dict)
    postconditions: list[str] = field(default_factory=list)
    retry_policy: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanStep":
        if not isinstance(payload, dict):
            raise ValueError("Plan step must be an object")
        return cls(
            id=str(payload.get("id") or "").strip(),
            title=str(payload.get("title") or payload.get("description") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            tool=str(payload.get("tool") or "").strip(),
            input=payload.get("input") if isinstance(payload.get("input"), dict) else {},
            depends_on=[str(item).strip() for item in payload.get("depends_on", []) if str(item).strip()]
            if isinstance(payload.get("depends_on"), list)
            else [],
            expected_outputs=payload.get("expected_outputs") if isinstance(payload.get("expected_outputs"), dict) else {},
            postconditions=[str(item).strip() for item in payload.get("postconditions", []) if str(item).strip()]
            if isinstance(payload.get("postconditions"), list)
            else [],
            retry_policy=payload.get("retry_policy") if isinstance(payload.get("retry_policy"), dict) else {},
            requires_confirmation=bool(payload.get("requires_confirmation", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "tool": self.tool,
            "input": self.input,
            "depends_on": self.depends_on,
            "expected_outputs": self.expected_outputs,
            "postconditions": self.postconditions,
            "retry_policy": self.retry_policy,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep]
    assumptions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Plan":
        if not isinstance(payload, dict):
            raise ValueError("Plan must be an object")
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list):
            raise ValueError("Plan.steps must be an array")
        return cls(
            goal=str(payload.get("goal") or "").strip(),
            steps=[PlanStep.from_dict(item) for item in raw_steps],
            assumptions=[str(item).strip() for item in payload.get("assumptions", []) if str(item).strip()]
            if isinstance(payload.get("assumptions"), list)
            else [],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "assumptions": self.assumptions,
            "steps": [step.to_dict() for step in self.steps],
        }


def parse_plan_json(text: str) -> Plan:
    """Parse a JSON plan produced by the planner prompt."""
    payload = json.loads(text)
    return Plan.from_dict(payload)


@dataclass
class PlanValidationIssue:
    step_id: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {"step_id": self.step_id, "message": self.message, "severity": self.severity}


@dataclass
class PlanValidationResult:
    valid: bool
    issues: list[PlanValidationIssue] = field(default_factory=list)

    def errors(self) -> list[PlanValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    def warnings(self) -> list[PlanValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]


class PlanVerifier:
    """Static validation for structured plans before execution."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def verify(self, plan: Plan, context: ToolContext | None = None) -> PlanValidationResult:
        issues: list[PlanValidationIssue] = []
        seen_ids: set[str] = set()
        context = context or ToolContext()

        if not plan.steps:
            issues.append(PlanValidationIssue("", "Plan must contain at least one step"))

        for index, step in enumerate(plan.steps, start=1):
            step_id = step.id or f"step-{index}"
            if not step.id:
                issues.append(PlanValidationIssue(step_id, "Step id is required"))
            elif step.id in seen_ids:
                issues.append(PlanValidationIssue(step.id, "Step id must be unique"))

            tool = self.registry.find_tool(step.tool)
            if tool is None:
                issues.append(PlanValidationIssue(step_id, f"Unknown tool: {step.tool}"))
                if step.id:
                    seen_ids.add(step.id)
                continue

            for dep in step.depends_on:
                if dep not in seen_ids:
                    issues.append(PlanValidationIssue(step_id, f"Dependency '{dep}' must refer to an earlier step"))

            if step.id:
                seen_ids.add(step.id)

            if context.mode == "Ask Mode" and not tool.is_read_only(step.input):
                issues.append(PlanValidationIssue(step_id, f"Tool '{tool.name}' is not available in Ask Mode"))

            if tool.requires_waapi() and not getattr(context.waapi_client, "connected", False):
                issues.append(PlanValidationIssue(step_id, f"Tool '{tool.name}' requires a live Wwise/WAAPI connection"))

            schema_error = self._validate_schema(step.input, tool.input_schema)
            if schema_error:
                issues.append(PlanValidationIssue(step_id, schema_error))

            tool_validation = tool.validate_input(step.input)
            if not tool_validation.valid:
                issues.append(PlanValidationIssue(step_id, tool_validation.error or "Tool input is invalid"))

            placeholder = self._find_placeholder(step.input)
            if placeholder:
                issues.append(PlanValidationIssue(step_id, f"Input contains unresolved placeholder: {placeholder}"))

            permission = tool.check_permissions(step.input, context)
            if not permission.allowed:
                issues.append(PlanValidationIssue(step_id, permission.reason or "Tool permission denied"))

        return PlanValidationResult(valid=not any(issue.severity == "error" for issue in issues), issues=issues)

    def _validate_schema(self, value: dict[str, Any], schema: dict[str, Any]) -> str:
        if not isinstance(value, dict):
            return "Step input must be an object"
        if not isinstance(schema, dict):
            return "Tool schema must be an object"
        for key in schema.get("required", []) or []:
            if key not in value:
                return f"Missing required input: {key}"
        properties = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
        for key, item in value.items():
            prop_schema = properties.get(key)
            if not isinstance(prop_schema, dict):
                continue
            expected_type = prop_schema.get("type")
            if expected_type and not self._matches_json_type(item, expected_type):
                return f"Input '{key}' must be {expected_type}, got {type(item).__name__}"
        return ""

    def _matches_json_type(self, value: Any, expected_type: str | list[str]) -> bool:
        if isinstance(expected_type, list):
            return any(self._matches_json_type(value, item) for item in expected_type)
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "object":
            return isinstance(value, dict)
        if expected_type == "null":
            return value is None
        return True

    def _find_placeholder(self, value: Any) -> str:
        if isinstance(value, dict):
            for item in value.values():
                found = self._find_placeholder(item)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self._find_placeholder(item)
                if found:
                    return found
        elif isinstance(value, str):
            match = _PLACEHOLDER_RE.search(value.strip())
            if match:
                return match.group(0)
        return ""

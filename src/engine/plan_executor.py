"""Execute structured AudioMate plans against the ToolRegistry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from src.engine.planner import Plan, PlanStep, PlanVerifier
from src.tools.base import ToolContext, ToolResult, ToolResultStatus
from src.tools.registry import ToolRegistry


@dataclass
class StepExecutionRecord:
    step_id: str
    title: str
    tool: str
    status: ToolResultStatus
    output: str = ""
    data: object = None


@dataclass
class PlanExecutionResult:
    ok: bool
    records: list[StepExecutionRecord] = field(default_factory=list)
    outputs: dict[str, object] = field(default_factory=dict)
    error: str = ""


class PlanExecutor:
    """Small, synchronous structured-plan executor.

    This is intentionally UI-agnostic. MainWindow can later wrap it in a thread
    and feed records into StepProgressWidget.
    """

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.verifier = PlanVerifier(registry)

    def execute(
        self,
        plan: Plan,
        context: ToolContext,
        on_step_finished: Callable[[PlanStep, ToolResult], None] | None = None,
    ) -> PlanExecutionResult:
        validation = self.verifier.verify(plan, context)
        if not validation.valid:
            error = "; ".join(issue.message for issue in validation.errors())
            return PlanExecutionResult(ok=False, error=error)

        records: list[StepExecutionRecord] = []
        outputs: dict[str, object] = {}
        completed_ids: set[str] = set()

        for step in plan.steps:
            missing = [dep for dep in step.depends_on if dep not in completed_ids]
            if missing:
                return PlanExecutionResult(
                    ok=False,
                    records=records,
                    outputs=outputs,
                    error=f"Step {step.id} has unmet dependencies: {', '.join(missing)}",
                )

            tool = self.registry.find_tool(step.tool)
            if tool is None:
                return PlanExecutionResult(
                    ok=False,
                    records=records,
                    outputs=outputs,
                    error=f"Unknown tool: {step.tool}",
                )

            result = tool.execute(step.input, context)
            record = StepExecutionRecord(
                step_id=step.id,
                title=step.title,
                tool=step.tool,
                status=result.status,
                output=result.output,
                data=result.data,
            )
            records.append(record)
            outputs[step.id] = result.data if result.data is not None else result.output
            if callable(on_step_finished):
                on_step_finished(step, result)
            if result.is_error:
                return PlanExecutionResult(
                    ok=False,
                    records=records,
                    outputs=outputs,
                    error=result.output or f"Step {step.id} failed",
                )
            completed_ids.add(step.id)

        return PlanExecutionResult(ok=True, records=records, outputs=outputs)

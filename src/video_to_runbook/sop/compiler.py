"""Compile an SOP into a plan, then repair it against the validator.

A single generation reliably gets some names and references wrong, and the
validator can say exactly which. So the compile is a loop: generate, validate,
hand the errors back as compile errors, generate again. The model keeps its
message history across rounds, so a repair is a correction rather than a
restart.

The loop stops early when a round fails to reduce the error count, because a
model that is not converging will not converge with more rounds. It returns the
plan it has either way, with whatever errors remain attached: a plan the caller
can see is broken is more useful than an exception.
"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from video_to_runbook.sop.catalog import Catalog, register
from video_to_runbook.sop.plan_schema import ExecutionPlan
from video_to_runbook.sop.prompt import SYSTEM_PROMPT
from video_to_runbook.sop.validator import Error, format_for_model, validate

MAX_ROUNDS = 3


class Issue(BaseModel):
    severity: str
    code: str
    message: str
    step_id: str | None = None

    @classmethod
    def of(cls, e: Error) -> "Issue":
        return cls(severity=e.severity, code=e.code, message=e.message, step_id=e.step_id)


class CompileResult(BaseModel):
    plan: ExecutionPlan
    validated: bool = Field(
        description="True when no errors remain. Warnings may still be present."
    )
    rounds: int = Field(description="Generations used. 1 means it validated first try.")
    issues: list[Issue] = Field(description="What is still wrong after the last round.")


def build_agent(catalog: Catalog, model: str = "google:gemini-3.5-flash") -> Agent:
    """The Architect: reads an SOP, queries the catalogue, emits a typed plan.

    The catalogue is 399 KB and cannot go in a prompt, so it is attached as tools
    rather than shown.
    """
    agent = Agent(
        model,
        output_type=ExecutionPlan,
        system_prompt=SYSTEM_PROMPT.format(base_url=catalog.base_url),
    )
    register(agent, catalog)
    return agent


def _errors(issues: list[Error]) -> list[Error]:
    return [e for e in issues if e.severity == "error"]


async def compile_sop(
    agent: Agent, catalog: Catalog, sop_text: str, max_rounds: int = MAX_ROUNDS
) -> CompileResult:
    result = await agent.run(f"Compile this SOP into an execution plan:\n\n{sop_text}")
    plan = result.output
    found = validate(plan.model_dump(), catalog)

    rounds = 1
    while _errors(found) and rounds < max_rounds:
        before = len(_errors(found))
        result = await agent.run(
            format_for_model(found),
            message_history=result.all_messages(),
        )
        rounds += 1
        candidate = result.output
        found_now = validate(candidate.model_dump(), catalog)
        plan = candidate
        found = found_now
        if len(_errors(found)) >= before:
            break

    return CompileResult(
        plan=plan,
        validated=not _errors(found),
        rounds=rounds,
        issues=[Issue.of(e) for e in found],
    )

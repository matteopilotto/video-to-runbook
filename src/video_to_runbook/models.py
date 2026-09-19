from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints, model_validator

Action = Literal["click", "type", "select", "navigate", "wait", "verify"]
State = Literal["uploaded", "watching", "checking", "done", "failed"]
Badge = Literal["checking", "verified", "flagged", "error"]

GENERIC_TARGETS = {
    "button",
    "the button",
    "field",
    "the field",
    "screen",
    "the screen",
    "it",
    "here",
    "there",
    "element",
    "the element",
    "link",
    "the link",
}

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def parse_timestamp(value: object) -> object:
    """Convert `H:MM:SS`, `MM:SS`, or `M:SS` to seconds; pass everything else through."""
    if not isinstance(value, str) or ":" not in value:
        return value
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"timestamp {value!r} is not MM:SS or H:MM:SS")
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"timestamp {value!r} is not MM:SS or H:MM:SS") from None
    seconds = 0.0
    for n in numbers:
        seconds = seconds * 60 + n
    return seconds


class Step(BaseModel):
    order: int = Field(ge=1)
    timestamp_s: Annotated[float, BeforeValidator(parse_timestamp), Field(ge=0)]
    action: Action
    target: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3)]
    value: str | None = None
    screen: NonEmpty
    intent: NonEmpty


class Runbook(BaseModel):
    title: NonEmpty
    system: NonEmpty
    prerequisites: list[str] = []
    steps: list[Step] = Field(min_length=1)
    pitfalls: list[str] = []

    @model_validator(mode="after")
    def orders_contiguous(self) -> "Runbook":
        for expected, step in enumerate(self.steps, start=1):
            if step.order != expected:
                raise ValueError(f"expected step {expected} but found order {step.order}")
        return self

    @model_validator(mode="after")
    def timestamps_increasing(self) -> "Runbook":
        for previous, step in zip(self.steps, self.steps[1:], strict=False):
            if step.timestamp_s <= previous.timestamp_s:
                raise ValueError(
                    f"step {step.order} timestamp {step.timestamp_s} s is not after "
                    f"step {previous.order} timestamp {previous.timestamp_s} s"
                )
        return self

    @model_validator(mode="after")
    def targets_concrete(self) -> "Runbook":
        for step in self.steps:
            if step.target.lower() in GENERIC_TARGETS:
                raise ValueError(
                    f"step {step.order} target '{step.target}' is too generic; "
                    "name the on-screen label"
                )
        return self


class StepCheck(BaseModel):
    order: int
    matches: bool
    confidence: float = Field(ge=0, le=1)
    note: str | None = None

    @model_validator(mode="after")
    def note_required_when_flagged(self) -> "StepCheck":
        if not self.matches and not (self.note and self.note.strip()):
            raise ValueError("note is required when matches is false")
        return self


class CheckRecord(BaseModel):
    order: int
    check: StepCheck | None = None
    error: str | None = None
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @model_validator(mode="after")
    def exactly_one_of_check_or_error(self) -> "CheckRecord":
        if (self.check is None) == (self.error is None):
            raise ValueError("exactly one of check or error must be set")
        return self

    @property
    def badge(self) -> Badge:
        if self.check is None:
            return "error"
        return "verified" if self.check.matches else "flagged"


class RunMeta(BaseModel):
    run_id: str
    filename: str
    duration_s: float
    created_at: datetime
    tamper_step: int | None = None
    state: State = "uploaded"
    error: str | None = None
    tamper_applied: bool = False
    observer_requests: int = 0
    observer_input_tokens: int = 0
    observer_output_tokens: int = 0
    finished_at: datetime | None = None
    trace_url: str | None = None


class RunStatus(BaseModel):
    run_id: str
    state: State
    error: str | None
    filename: str
    duration_s: float
    tamper_step: int | None
    tamper_applied: bool
    trace_url: str | None
    elapsed_s: float
    calls: int
    input_tokens: int
    output_tokens: int
    video_url: str
    runbook: Runbook | None
    checks: list[CheckRecord]

    def badge_for(self, order: int) -> Badge:
        for record in self.checks:
            if record.order == order:
                return record.badge
        return "checking"

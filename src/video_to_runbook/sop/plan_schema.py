"""The plan IR an SOP compiles into.

Three things have to survive compilation: which API calls to make, how they are
sequenced and wired, and the business logic in between. The first two are
declarative so a plan can be rendered and approved before it touches SAP. The
third is generated code, because business rules in an SOP are open-ended and any
fixed vocabulary of operations eventually meets an SOP it cannot express.

Data flows through `${...}` references, so a plan carries its own wiring rather
than leaving it implied in prose. There are exactly three things a reference can
name, and no aliases for any of them:

    ${inputs.<name>}    a declared plan input
    ${<step_id>...}     the result of an earlier step
    ${item}             the current element, inside a for_each step

Control flow is flat `run_if` / `for_each` fields rather than nested blocks,
which keeps the schema non-recursive and structured generation reliable.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class _StepBase(BaseModel):
    step_id: str = Field(
        description="Unique snake_case id. This is also the name of the step's result: a later "
        "step reads it as ${step_id.field}. There is no separate output name. "
        "Cannot be 'inputs' or 'item', which are reserved."
    )
    reason: str = Field(
        description="Commentary tracing this step to a line of the SOP. Never executed, so "
        "it must not be the only place a rule is written down."
    )
    run_if: str | None = Field(
        default=None,
        description="Guard expression over earlier results, e.g. '${check_stock.shortfall} > 0'. "
        "Null means always run.",
    )
    for_each: str | None = Field(
        default=None,
        description="Reference to a collection, e.g. '${get_order.DocumentLines}'. The step runs "
        "once per element, bound to ${item}, and its result is a LIST with one entry "
        "per element, in the same order as the collection. Null means run once.",
    )


class ApiCall(_StepBase):
    kind: Literal["api_call"]
    entity: str = Field(description="EntitySet name. MUST appear in the supplied catalogue.")
    method: Literal["GET", "POST", "PATCH", "DELETE"]
    path: str = Field(
        description="Path relative to the Service Layer base url, query string included."
    )
    body: dict[str, Any] = Field(
        default_factory=dict,
        description="Request body built here, key by key. Every value is a literal or a "
        '${...} reference. Never a placeholder such as 1 or "string" standing '
        "in for a real value. Leave empty when using body_from.",
    )
    body_from: str | None = Field(
        default=None,
        description="A single ${...} reference supplying the WHOLE body, for when an earlier "
        "transform already built the payload. Use this instead of body; setting "
        "both is an error. A POST or PATCH must set exactly one of them.",
    )


class TransformTest(BaseModel):
    """A case derived from the SOP, run in a sandbox before the plan is approved.

    The body is a string rather than typed input/expected pairs on purpose. A
    `Dict[str, Any]` field erases to an unconstrained JSON schema, and structured
    output fills it with a scalar placeholder rather than a real structure, which
    is the same failure as a filler value in a request body. A string survives
    generation intact, and asserts say more than equality on a whole return value.
    """

    name: str = Field(description="snake_case name for this case.")
    derived_from: str = Field(description="The sentence of the SOP this case pins down.")
    test_code: str = Field(
        description="Python defining `def test(transform):`. Build the real input structures "
        "inline, call transform(...), and assert on the result. Every assert "
        "carries a message. Raise AssertionError to fail; return value is ignored."
    )


class Transform(_StepBase):
    kind: Literal["transform"]
    purpose: str = Field(description="The rule this implements, in one line.")
    inputs: dict[str, str] = Field(
        description="Argument name -> ${...} reference. The code sees exactly these and nothing else."
    )
    code: str = Field(
        description="Python defining `def transform(**inputs)` returning a JSON-serialisable "
        "value. Pure: standard library only, no network, no I/O."
    )
    returns: str = Field(
        description="Shape of the return value, so later steps can be checked against it."
    )
    tests: list[TransformTest] = Field(
        description="At least two cases, including every edge case the SOP calls out. A rule "
        "stated in the SOP but not pinned by a test is a rule that was not encoded."
    )


class Notify(_StepBase):
    kind: Literal["notify"]
    channel: Literal["google_chat", "email"]
    target: str = Field(description="Channel/space id or address. 'UNKNOWN' if the SOP omits it.")
    message: str = Field(description="Message text. May embed ${...} references.")


class Stop(_StepBase):
    kind: Literal["stop"]
    status: Literal["success", "blocked"]


Step = Annotated[ApiCall | Transform | Notify | Stop, Field(discriminator="kind")]


class PlanInput(BaseModel):
    name: str
    type: Literal["string", "number", "date"]
    description: str


class ExecutionPlan(BaseModel):
    process_name: str
    inputs: list[PlanInput] = Field(description="What the caller must supply to run this plan.")
    steps: list[Step]
    assumptions: list[str] = Field(
        description="Every entity or field name inferred rather than read from the catalogue, "
        "and every reading of the SOP that had to be chosen between."
    )
    open_questions: list[str] = Field(
        description="Where the SOP is ambiguous, self-contradictory or incomplete. Surface "
        "these rather than silently resolving them."
    )

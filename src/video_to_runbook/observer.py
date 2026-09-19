"""The Observer: a Pro-class Gemini model watches the recording and returns a Runbook."""

from dataclasses import dataclass
from pathlib import Path

from google.genai.types import HttpRetryOptions
from pydantic import BaseModel
from pydantic_ai import Agent, BinaryContent, ModelRetry, RunContext, UsageLimits
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.providers.google import GoogleProvider

from video_to_runbook.config import get_settings
from video_to_runbook.models import Runbook

OBSERVER_INSTRUCTIONS = """\
You watch a screen recording of a person doing one task and write the runbook that lets
someone else repeat it. Produce a Runbook.

- `title` is the task as an imperative phrase, verb first, without the product name
  ("Create a sales order"); `system` names the product.
- `prerequisites` list the state the recording starts from: the screen open at 00:00 and
  any record the task relies on that must already exist (a customer, an item, a project).
- Every step carries a timestamp in MM:SS of the moment the action happens in the video.
- One step per action the operator must perform. A click that only focuses a field is part
  of the `type` or `select` that follows, not a step. A tab or menu click that only reveals
  values is not a step; when the narrator points at those values, it is one `verify` step
  naming them.
- `target` is the exact on-screen label: a menu path, a button caption, a field name. Never
  a generic phrase such as "the button" or "the field".
- Scrolling, mis-clicks, window moves, and idle time are not steps. Collapse them into nothing.
- `intent` is one short clause saying what the step is for; do not repeat the target. When
  there is narration, take it from what the narrator says the step is for. Otherwise infer
  it from what happens next.
- Choose `action` by what the moment is for, not by the mouse: `type` when text or a key
  goes into a field (even if the field was clicked first); `select` when an entry is chosen
  from a list, dropdown, or picker; `navigate` for a menu path or an address; `verify` when
  the narrator points at something on screen without acting on it, such as a defaulted
  value, an auto-filled tab, or a result; `click` only for a button, tab, or menu item that
  is pressed on its own; `wait` for a pause on the system.
- `type` steps carry the typed text or key name in `value`.
- Steps show only the path that worked. A rejected form, a wrong click the narrator
  corrects, or a warning the narrator gives goes in `pitfalls`, prefixed with the step it
  belongs to ("Step 12: ...").
- `outcome` is one sentence saying what the screen shows when the task is complete.
- Number steps from 1 in time order.
"""

OBSERVER_USER_PROMPT = "Watch this recording and return the runbook for the task it shows."

RETRY_STATUS_CODES = [429, 500, 502, 503, 504]


@dataclass
class ObserverDeps:
    run_id: str
    video_path: Path
    duration_s: float


class ObserveResult(BaseModel):
    runbook: Runbook
    requests: int
    input_tokens: int
    output_tokens: int


def build_observer(model: Model | str | None = None) -> Agent[ObserverDeps, Runbook]:
    settings = get_settings()
    if model is None:
        model = GoogleModel(
            settings.observer_model,
            provider=GoogleProvider(
                api_key=settings.gemini_api_key,
                retry_options=HttpRetryOptions(
                    attempts=3,
                    initial_delay=1,
                    max_delay=10,
                    http_status_codes=RETRY_STATUS_CODES,
                ),
            ),
        )
    agent: Agent[ObserverDeps, Runbook] = Agent(
        model,
        output_type=Runbook,
        deps_type=ObserverDeps,
        instructions=OBSERVER_INSTRUCTIONS,
        retries={"output": 2},
        name="observer",
        model_settings=GoogleModelSettings(
            timeout=settings.observer_timeout_s,
            google_video_resolution="MEDIA_RESOLUTION_HIGH",
        ),
    )

    @agent.output_validator
    def within_duration(ctx: RunContext[ObserverDeps], runbook: Runbook) -> Runbook:
        for step in runbook.steps:
            if step.timestamp_s > ctx.deps.duration_s:
                raise ModelRetry(
                    f"step {step.order} timestamp {step.timestamp_s} s is beyond the video "
                    f"duration {ctx.deps.duration_s} s"
                )
        return runbook

    return agent


async def observe(deps: ObserverDeps, model: Model | str | None = None) -> ObserveResult:
    """Send the whole recording inline and return the validated runbook with its usage."""
    settings = get_settings()
    agent = build_observer(model)
    video = BinaryContent(deps.video_path.read_bytes(), media_type="video/mp4")
    result = await agent.run(
        [OBSERVER_USER_PROMPT, video],
        deps=deps,
        usage_limits=UsageLimits(request_limit=settings.observer_request_limit),
    )
    usage = result.usage
    return ObserveResult(
        runbook=result.output,
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )

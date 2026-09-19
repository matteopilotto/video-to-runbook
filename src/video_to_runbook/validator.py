"""The Validator: a Flash-class Gemini model judges one step against three frames."""

from google.genai.types import HttpRetryOptions
from pydantic_ai import Agent, BinaryContent, UsageLimitExceeded, UsageLimits
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.providers.google import GoogleProvider

from video_to_runbook.config import get_settings
from video_to_runbook.models import CheckRecord, Step, StepCheck
from video_to_runbook.observer import RETRY_STATUS_CODES

VALIDATOR_INSTRUCTIONS = """\
You see three frames from a screen recording, taken one second before, at, and one second
after the moment a runbook step claims to happen. Say whether the frames show the step's
target being acted on. The middle frame may already show the state after the action; that
still counts as a match. Return `matches`, your `confidence`, and, when they do not match,
a `note` naming what the frames show instead.
"""

VALIDATOR_QUESTION = "Does the video show this step?"
CAP_ERROR = "call cap reached in step check"


def describe(step: Step) -> str:
    value = f" with value {step.value!r}" if step.value else ""
    return (
        f"Step {step.order} at {step.timestamp_s:.0f} s: {step.action} {step.target!r}{value} "
        f"on the {step.screen!r} screen, in order to {step.intent}."
    )


def build_validator(model: Model | str | None = None) -> Agent[None, StepCheck]:
    settings = get_settings()
    if model is None:
        model = GoogleModel(
            settings.validator_model,
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
    return Agent(
        model,
        output_type=StepCheck,
        instructions=VALIDATOR_INSTRUCTIONS,
        retries={"output": 1},
        name="validator",
        model_settings=GoogleModelSettings(timeout=settings.validator_timeout_s),
    )


async def check_step(
    step: Step, frames: list[bytes], model: Model | str | None = None
) -> CheckRecord:
    """Judge one step against its frames; a failed check comes back as an error record."""
    settings = get_settings()
    agent = build_validator(model)
    prompt = [
        describe(step),
        *(BinaryContent(png, media_type="image/png") for png in frames),
        VALIDATOR_QUESTION,
    ]
    limits = UsageLimits(request_limit=settings.check_request_limit)
    async with agent.iter(prompt, usage_limits=limits) as run:
        try:
            async for _ in run:
                pass
        except UsageLimitExceeded:
            error: str | None = CAP_ERROR
        except Exception as exc:  # noqa: BLE001  the record must exist, whatever failed
            error = f"{type(exc).__name__}: {exc}"
        else:
            error = None
        usage = run.usage
    check = None
    if error is None and run.result is not None:
        check = run.result.output.model_copy(update={"order": step.order})
    return CheckRecord(
        order=step.order,
        check=check,
        error=error,
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )

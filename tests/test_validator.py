import asyncio
from typing import Any

import pytest
from pydantic_ai import UsageLimits
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from video_to_runbook.models import Step
from video_to_runbook.validator import check_step

STEP = Step(
    order=7,
    timestamp_s=57.0,
    action="click",
    target="Contents",
    screen="Sales Order",
    intent="open the Contents tab",
)
FRAMES = [b"\x89PNG-1", b"\x89PNG-2", b"\x89PNG-3"]

Payload = dict[str, Any] | Exception


def fake_model(*payloads: Payload) -> tuple[FunctionModel, list[list[ModelMessage]]]:
    """A model that answers each request with the next payload, or raises it."""
    requests: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        requests.append(list(messages))
        payload = payloads[len(requests) - 1]
        if isinstance(payload, Exception):
            raise payload
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=payload)]
        )

    return FunctionModel(respond), requests


def check(matches: bool, note: str | None = None) -> dict[str, Any]:
    return {"order": 7, "matches": matches, "confidence": 0.8, "note": note}


def test_missing_note_is_retried() -> None:
    model, _ = fake_model(check(False), check(False, "frame shows the Logistics tab"))

    record = asyncio.run(check_step(STEP, FRAMES, model=model))

    assert record.order == 7
    assert record.error is None
    assert record.check is not None
    assert record.check.matches is False
    assert record.check.note == "frame shows the Logistics tab"
    assert record.requests == 2
    assert record.badge == "flagged"


def test_request_carries_three_frames() -> None:
    model, requests = fake_model(check(True))

    asyncio.run(check_step(STEP, FRAMES, model=model))

    first = requests[0][0]
    assert isinstance(first, ModelRequest)
    prompt = next(part for part in first.parts if isinstance(part, UserPromptPart))
    images = [part for part in prompt.content if isinstance(part, BinaryContent)]
    assert [image.data for image in images] == FRAMES
    assert all(image.media_type == "image/png" for image in images)
    text = " ".join(part for part in prompt.content if isinstance(part, str))
    assert "Contents" in text and "click" in text


def test_model_exception_becomes_an_error_record() -> None:
    model, _ = fake_model(check(False), TimeoutError("timed out after 60 s"))

    record = asyncio.run(check_step(STEP, FRAMES, model=model))

    assert record.check is None
    assert record.error is not None and "timed out after 60 s" in record.error
    assert record.requests == 1
    assert record.badge == "error"


def test_call_cap_becomes_an_error_record(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "video_to_runbook.validator.UsageLimits", lambda **_: UsageLimits(request_limit=1)
    )
    model, _ = fake_model(check(False), check(False, "never reached"))

    record = asyncio.run(check_step(STEP, FRAMES, model=model))

    assert record.check is None
    assert record.error is not None and "call cap" in record.error
    assert record.requests == 1

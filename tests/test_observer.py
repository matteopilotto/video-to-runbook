import asyncio
from pathlib import Path
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from video_to_runbook.observer import ObserverDeps, build_observer, observe


def step(order: int, timestamp_s: Any) -> dict[str, Any]:
    return {
        "order": order,
        "timestamp_s": timestamp_s,
        "action": "click",
        "target": f"Button {order}",
        "screen": "Sales Order",
        "intent": f"Do thing {order}",
    }


def runbook(*steps: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": "Create a sales order",
        "system": "SAP Business One",
        "prerequisites": [],
        "steps": list(steps),
        "pitfalls": [],
    }


def fake_model(*payloads: dict[str, Any]) -> tuple[FunctionModel, list[list[ModelMessage]]]:
    """A model that answers each request with the next payload as the output tool call."""
    requests: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        requests.append(list(messages))
        payload = payloads[len(requests) - 1]
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=payload)]
        )

    return FunctionModel(respond), requests


def retry_prompts(messages: list[ModelMessage]) -> list[str]:
    return [
        str(part.content)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, RetryPromptPart)
    ]


VALID = runbook(step(1, 5.0), step(2, 60.0))
VALID_DUMP = {
    **VALID,
    "steps": [{**s, "timestamp_s": float(s["timestamp_s"]), "value": None} for s in VALID["steps"]],
}


def deps_for(tmp_path: Path) -> ObserverDeps:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not really a video")
    return ObserverDeps(run_id="t", video_path=video, duration_s=118.0)


def test_timestamp_beyond_duration_is_retried(tmp_path: Path) -> None:
    model, requests = fake_model(runbook(step(1, 5.0), step(2, 999)), VALID)
    agent = build_observer(model=model)

    result = agent.run_sync("watch", deps=deps_for(tmp_path))

    assert result.output.model_dump() == VALID_DUMP
    assert result.usage().requests == 2
    prompts = retry_prompts(requests[1])
    assert len(prompts) == 1
    assert "step 2 timestamp 999.0 s is beyond the video duration 118.0 s" in prompts[0]


def test_schema_violation_is_retried(tmp_path: Path) -> None:
    model, requests = fake_model(runbook(step(1, 5.0), step(3, 60.0)), VALID)
    agent = build_observer(model=model)

    result = agent.run_sync("watch", deps=deps_for(tmp_path))

    assert result.output.model_dump() == VALID_DUMP
    assert result.usage().requests == 2
    assert "step 2" in retry_prompts(requests[1])[0]


def test_observe_parses_clock_timestamps(tmp_path: Path) -> None:
    model, _ = fake_model(runbook(step(1, "00:05"), step(2, "01:15")))

    result = asyncio.run(observe(deps_for(tmp_path), model=model))

    assert [s.timestamp_s for s in result.runbook.steps] == [5.0, 75.0]
    assert result.requests == 1

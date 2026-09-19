from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from video_to_runbook.models import CheckRecord, Runbook, RunStatus, Step, StepCheck


def step(order: int, timestamp_s: Any = None, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "order": order,
        "timestamp_s": order * 10.0 if timestamp_s is None else timestamp_s,
        "action": "click",
        "target": "Add button",
        "screen": "Sales Order",
        "intent": "Save the order",
    }
    data.update(overrides)
    return data


def runbook(*steps: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": "Create a sales order",
        "system": "SAP Business One",
        "prerequisites": [],
        "steps": list(steps),
        "outcome": "The new sales order is displayed with its document number",
        "pitfalls": [],
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("01:15", 75.0), ("1:05", 65.0), ("0:01:15", 75.0), (75, 75.0), ("75.5", 75.5)],
)
def test_timestamp_accepts_clock_and_seconds(raw: Any, expected: float) -> None:
    assert Step(**step(1, raw)).timestamp_s == expected


@pytest.mark.parametrize("raw", [-1, "abc"])
def test_timestamp_rejects_negative_and_garbage(raw: Any) -> None:
    with pytest.raises(ValidationError):
        Step(**step(1, raw))


def test_action_outside_set_rejected() -> None:
    with pytest.raises(ValidationError):
        Step(**step(1, action="hover"))


def test_target_too_short_rejected() -> None:
    with pytest.raises(ValidationError):
        Step(**step(1, target="ab"))


@pytest.mark.parametrize("field", ["screen", "intent"])
def test_screen_and_intent_must_be_non_empty(field: str) -> None:
    with pytest.raises(ValidationError):
        Step(**step(1, **{field: "  "}))


def test_runbook_needs_at_least_one_step() -> None:
    with pytest.raises(ValidationError):
        Runbook(**runbook())


@pytest.mark.parametrize("target", ["the button", "HERE"])
def test_generic_target_named_by_step_order(target: str) -> None:
    with pytest.raises(ValidationError, match="step 3 target"):
        Runbook(**runbook(step(1), step(2), step(3, target=target)))


def test_concrete_target_accepted() -> None:
    rb = Runbook(**runbook(step(1), step(2), step(3, target="Add button")))
    assert len(rb.steps) == 3


def test_orders_must_be_contiguous() -> None:
    with pytest.raises(ValidationError, match="step 2"):
        Runbook(**runbook(step(1), step(3)))


@pytest.mark.parametrize("timestamps", [(5.0, 5.0), (5.0, 4.0)])
def test_timestamps_must_strictly_increase(timestamps: tuple[float, float]) -> None:
    with pytest.raises(ValidationError, match="step 2"):
        Runbook(**runbook(step(1, timestamps[0]), step(2, timestamps[1])))


def test_flagged_check_needs_a_note() -> None:
    with pytest.raises(ValidationError):
        StepCheck(order=1, matches=False, confidence=0.5, note=None)


def test_confidence_bounded() -> None:
    with pytest.raises(ValidationError):
        StepCheck(order=1, matches=True, confidence=1.2)


def test_check_record_needs_exactly_one_of_check_or_error() -> None:
    check = StepCheck(order=1, matches=True, confidence=0.9)
    with pytest.raises(ValidationError):
        CheckRecord(order=1, check=check, error="boom")
    with pytest.raises(ValidationError):
        CheckRecord(order=1)


def test_check_record_badge() -> None:
    ok = StepCheck(order=1, matches=True, confidence=0.9)
    bad = StepCheck(order=2, matches=False, confidence=0.8, note="shows the Logistics tab")
    assert CheckRecord(order=1, check=ok).badge == "verified"
    assert CheckRecord(order=2, check=bad).badge == "flagged"
    assert CheckRecord(order=3, error="timed out").badge == "error"


def test_run_status_round_trips() -> None:
    status = RunStatus(
        run_id="3f9a1c2b7d4e",
        state="checking",
        error=None,
        filename="clip.mp4",
        duration_s=118.05,
        tamper_step=None,
        tamper_applied=False,
        trace_url=None,
        created_at=datetime(2026, 9, 19, 14, 30, tzinfo=UTC),
        elapsed_s=12.5,
        calls=3,
        input_tokens=100,
        output_tokens=20,
        video_url="/runs/3f9a1c2b7d4e/video",
        runbook=Runbook(**runbook(step(1), step(2))),
        checks=[CheckRecord(order=1, error="timed out", requests=2)],
    )
    again = RunStatus.model_validate_json(status.model_dump_json())
    assert again == status
    assert again.badge_for(1) == "error"
    assert again.badge_for(2) == "checking"


def test_type_step_needs_a_value() -> None:
    with pytest.raises(ValidationError, match="step 2 types into 'Customer' but has no value"):
        Runbook(**runbook(step(1), step(2, action="type", target="Customer")))


def test_type_step_with_a_key_name_is_accepted() -> None:
    rb = Runbook(**runbook(step(1), step(2, action="type", target="Customer", value="Tab")))
    assert rb.steps[1].value == "Tab"


@pytest.mark.parametrize("outcome", [None, "  "])
def test_runbook_needs_an_outcome(outcome: str | None) -> None:
    data = runbook(step(1))
    if outcome is None:
        del data["outcome"]
    else:
        data["outcome"] = outcome
    with pytest.raises(ValidationError, match="outcome"):
        Runbook(**data)

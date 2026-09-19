import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from video_to_runbook.models import CheckRecord, Runbook, RunMeta, Step, StepCheck
from video_to_runbook.runs import (
    TAMPER_TARGET,
    apply_tamper,
    budget_slots,
    capped_records,
    read_meta,
    read_runbook,
    read_status,
    write_meta,
    write_runbook,
)


def make_runbook(n: int) -> Runbook:
    return Runbook(
        title="Create a sales order",
        system="SAP Business One",
        steps=[
            Step(
                order=i,
                timestamp_s=float(i * 5),
                action="click",
                target=f"Button {i}",
                screen="Sales Order",
                intent=f"Do thing {i}",
            )
            for i in range(1, n + 1)
        ],
    )


def test_apply_tamper_replaces_one_target() -> None:
    original = make_runbook(14)
    tampered, applied = apply_tamper(original, 7)
    assert applied is True
    assert tampered.steps[6].target == TAMPER_TARGET
    assert original.steps[6].target == "Button 7"
    for before, after in zip(original.steps, tampered.steps, strict=True):
        if before.order != 7:
            assert before == after


@pytest.mark.parametrize("step", [20, None])
def test_apply_tamper_leaves_runbook_alone(step: int | None) -> None:
    original = make_runbook(14)
    tampered, applied = apply_tamper(original, step)
    assert applied is False
    assert tampered == original


@pytest.mark.parametrize(
    ("cap", "observer_requests", "per_check", "expected"),
    [(60, 3, 3, 19), (60, 4, 3, 18), (2, 3, 3, 0)],
)
def test_budget_slots(cap: int, observer_requests: int, per_check: int, expected: int) -> None:
    assert budget_slots(cap, observer_requests, per_check) == expected


def test_capped_records_cover_steps_beyond_the_slots() -> None:
    steps = make_runbook(5).steps
    records = capped_records(steps, slots=2)
    assert [r.order for r in records] == [3, 4, 5]
    assert all(r.error == "call cap reached before this step" for r in records)
    assert all(r.requests == 0 for r in records)
    assert capped_records(steps, slots=5) == []


def make_meta(run_id: str) -> RunMeta:
    return RunMeta(
        run_id=run_id,
        filename="clip.mp4",
        duration_s=118.05,
        created_at=datetime.now(UTC) - timedelta(seconds=5),
        state="checking",
        observer_requests=2,
        observer_input_tokens=1000,
        observer_output_tokens=200,
    )


def test_meta_round_trip(tmp_path: Path) -> None:
    meta = make_meta("abc123abc123")
    write_meta(tmp_path, meta)
    assert read_meta(tmp_path) == meta


def test_runbook_round_trip(tmp_path: Path) -> None:
    runbook = make_runbook(3)
    write_runbook(tmp_path, runbook)
    assert read_runbook(tmp_path) == runbook


def test_read_status_assembles_the_payload(tmp_path: Path) -> None:
    run_id = "3f9a1c2b7d4e"
    write_meta(tmp_path, make_meta(run_id))
    (tmp_path / "runbook.json").write_text(make_runbook(3).model_dump_json())
    checks = tmp_path / "checks"
    checks.mkdir()
    two = CheckRecord(order=2, error="timed out", requests=3, input_tokens=30, output_tokens=0)
    one = CheckRecord(
        order=1,
        check=StepCheck(order=1, matches=True, confidence=0.9),
        requests=1,
        input_tokens=10,
        output_tokens=5,
    )
    (checks / "2.json").write_text(two.model_dump_json())
    (checks / "1.json").write_text(one.model_dump_json())

    status = read_status(tmp_path)

    assert status.state == "checking"
    assert status.run_id == run_id
    assert status.calls == 2 + 1 + 3
    assert status.input_tokens == 1000 + 10 + 30
    assert status.output_tokens == 200 + 5
    assert [c.order for c in status.checks] == [1, 2]
    assert status.elapsed_s > 0
    assert status.video_url == f"/runs/{run_id}/video"
    assert status.runbook is not None and len(status.runbook.steps) == 3
    assert status.badge_for(3) == "checking"
    json.loads(status.model_dump_json())


def test_read_status_without_meta_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_status(tmp_path)

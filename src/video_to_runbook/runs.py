"""Per-run files on the data volume and the pure run-state rules app.py delegates to."""

from datetime import UTC, datetime
from pathlib import Path

from video_to_runbook.models import CheckRecord, Runbook, RunMeta, RunStatus, Step

TAMPER_TARGET = "the Log Out menu item"
CAPPED_ERROR = "call cap reached before this step"


def run_dir(data_dir: Path, run_id: str) -> Path:
    return data_dir / "runs" / run_id


def read_meta(run_dir: Path) -> RunMeta:
    return RunMeta.model_validate_json((run_dir / "meta.json").read_text())


def write_meta(run_dir: Path, meta: RunMeta) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(meta.model_dump_json(indent=2))


def write_runbook(run_dir: Path, runbook: Runbook) -> None:
    (run_dir / "runbook.json").write_text(runbook.model_dump_json(indent=2))


def write_check(run_dir: Path, record: CheckRecord) -> None:
    checks = run_dir / "checks"
    checks.mkdir(exist_ok=True)
    (checks / f"{record.order}.json").write_text(record.model_dump_json(indent=2))


def read_status(run_dir: Path) -> RunStatus:
    """Assemble the status payload from whatever files the run has so far."""
    meta = read_meta(run_dir)
    runbook_file = run_dir / "runbook.json"
    runbook = (
        Runbook.model_validate_json(runbook_file.read_text()) if runbook_file.exists() else None
    )
    checks = sorted(
        (CheckRecord.model_validate_json(f.read_text()) for f in run_dir.glob("checks/*.json")),
        key=lambda record: record.order,
    )
    end = meta.finished_at or datetime.now(UTC)
    return RunStatus(
        run_id=meta.run_id,
        state=meta.state,
        error=meta.error,
        filename=meta.filename,
        duration_s=meta.duration_s,
        tamper_step=meta.tamper_step,
        tamper_applied=meta.tamper_applied,
        trace_url=meta.trace_url,
        elapsed_s=(end - meta.created_at).total_seconds(),
        calls=meta.observer_requests + sum(c.requests for c in checks),
        input_tokens=meta.observer_input_tokens + sum(c.input_tokens for c in checks),
        output_tokens=meta.observer_output_tokens + sum(c.output_tokens for c in checks),
        video_url=f"/runs/{meta.run_id}/video",
        runbook=runbook,
        checks=checks,
    )


def apply_tamper(runbook: Runbook, step: int | None) -> tuple[Runbook, bool]:
    """Return a copy with the demo tamper applied to `step`, and whether it was applied."""
    if step is None or not 1 <= step <= len(runbook.steps):
        return runbook, False
    steps = [
        s.model_copy(update={"target": TAMPER_TARGET}) if s.order == step else s
        for s in runbook.steps
    ]
    return runbook.model_copy(update={"steps": steps}), True


def budget_slots(cap: int, observer_requests: int, per_check: int) -> int:
    """How many step checks fit under the call cap after the Observer's requests."""
    return max(0, (cap - observer_requests) // per_check)


def capped_records(steps: list[Step], slots: int) -> list[CheckRecord]:
    """Error records for the steps beyond the budget, so no step is dropped."""
    return [CheckRecord(order=s.order, error=CAPPED_ERROR) for s in steps[slots:]]

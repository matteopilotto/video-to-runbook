"""Tests that call Gemini. Skipped without GEMINI_API_KEY; RECORD_FIXTURES=1 saves the output."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from video_to_runbook.config import get_settings
from video_to_runbook.frames import extract_frames, probe_duration
from video_to_runbook.models import CheckRecord, Runbook
from video_to_runbook.observer import ObserverDeps, observe
from video_to_runbook.tracing import setup_logfire
from video_to_runbook.validator import check_step

SAP_SAMPLE = Path(__file__).parents[2] / "samples" / "sap_b1_create_sales_order_demo.mp4"


@pytest.mark.integration
def test_observer_sap(fixtures_dir: Path) -> None:
    setup_logfire()
    duration = probe_duration(SAP_SAMPLE)
    deps = ObserverDeps(run_id="sap-integration", video_path=SAP_SAMPLE, duration_s=duration)

    result = asyncio.run(observe(deps))

    steps = result.runbook.steps
    assert 5 <= len(steps) <= 25
    assert all(step.timestamp_s <= duration for step in steps)
    assert [step.order for step in steps] == list(range(1, len(steps) + 1))
    if os.environ.get("RECORD_FIXTURES") == "1":
        fixtures_dir.mkdir(parents=True, exist_ok=True)
        (fixtures_dir / "runbook.json").write_text(result.runbook.model_dump_json(indent=2))


@pytest.mark.integration
def test_validator_sap(fixtures_dir: Path) -> None:
    setup_logfire()
    runbook = Runbook.model_validate_json((fixtures_dir / "runbook.json").read_text())
    duration = probe_duration(SAP_SAMPLE)
    offsets = get_settings().frame_offsets_s

    async def check_all() -> list[CheckRecord]:
        return await asyncio.gather(
            *(
                check_step(step, extract_frames(SAP_SAMPLE, step.timestamp_s, duration, offsets))
                for step in runbook.steps
            )
        )

    records = asyncio.run(check_all())

    assert [r.order for r in records] == [s.order for s in runbook.steps]
    assert all((r.check is None) != (r.error is None) for r in records)
    if os.environ.get("RECORD_FIXTURES") == "1":
        payload = [r.model_dump(mode="json") for r in records]
        (fixtures_dir / "checks.json").write_text(json.dumps(payload, indent=2) + "\n")

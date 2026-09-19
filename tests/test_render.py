import re
from pathlib import Path

import pytest

from video_to_runbook.models import Runbook, RunStatus
from video_to_runbook.render import render_fragment


def status_for(
    runbook: Runbook | None, state: str = "checking", error: str | None = None
) -> RunStatus:
    return RunStatus(
        run_id="3f9a1c2b7d4e",
        state=state,
        error=error,
        filename="clip.mp4",
        duration_s=118.05,
        tamper_step=None,
        tamper_applied=False,
        trace_url=None,
        elapsed_s=12.0,
        calls=1,
        input_tokens=10,
        output_tokens=5,
        video_url="/runs/3f9a1c2b7d4e/video",
        runbook=runbook,
        checks=[],
    )


@pytest.fixture
def sap_runbook(fixtures_dir: Path) -> Runbook:
    return Runbook.model_validate_json((fixtures_dir / "runbook.json").read_text())


def rows(html: str) -> list[tuple[str, str]]:
    return re.findall(r'data-order="(\d+)"[^>]*data-timestamp="([\d.]+)"', html)


def badges(html: str) -> list[str]:
    return re.findall(r'class="badge (\w+)"', html)


def test_fragment_has_one_row_per_step_with_checking_badges(sap_runbook: Runbook) -> None:
    html = render_fragment(status_for(sap_runbook))
    found = rows(html)
    assert [int(order) for order, _ in found] == [s.order for s in sap_runbook.steps]
    assert [float(t) for _, t in found] == [s.timestamp_s for s in sap_runbook.steps]
    assert badges(html) == ["checking"] * len(sap_runbook.steps)
    assert sap_runbook.title in html
    assert "<script" not in html


def test_fragment_shows_watching_message_before_runbook() -> None:
    html = render_fragment(status_for(None, state="watching"))
    assert "Watching the recording…" in html
    assert rows(html) == []


def test_fragment_shows_error_when_failed() -> None:
    html = render_fragment(status_for(None, state="failed", error="observer exhausted retries"))
    assert "observer exhausted retries" in html

import json
import re
from pathlib import Path

import pytest
from markupsafe import escape

from video_to_runbook.models import CheckRecord, Runbook, RunStatus
from video_to_runbook.render import mmss, render_fragment, render_markdown


def status_for(
    runbook: Runbook | None,
    state: str = "checking",
    error: str | None = None,
    checks: list[CheckRecord] | None = None,
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
        checks=checks or [],
    )


@pytest.fixture
def sap_runbook(fixtures_dir: Path) -> Runbook:
    return Runbook.model_validate_json((fixtures_dir / "runbook.json").read_text())


@pytest.fixture
def sap_checks(fixtures_dir: Path) -> list[CheckRecord]:
    records = json.loads((fixtures_dir / "checks.json").read_text())
    return [CheckRecord.model_validate(record) for record in records]


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


def test_fragment_badges_follow_the_checks(
    sap_runbook: Runbook, sap_checks: list[CheckRecord]
) -> None:
    unchecked, *checks = sap_checks
    checks[-1] = CheckRecord(order=checks[-1].order, error="timed out")
    html = render_fragment(status_for(sap_runbook, checks=checks))

    expected = {record.order: record.badge for record in checks}
    expected[unchecked.order] = "checking"
    found = dict(re.findall(r'data-order="(\d+)".*?class="badge (\w+)"', html, flags=re.DOTALL))
    assert {int(order): badge for order, badge in found.items()} == expected

    flagged = [record for record in checks if record.badge == "flagged"]
    assert flagged, "the fixture needs at least one flagged check"
    details = re.findall(r"<details.*?</details>", html, flags=re.DOTALL)
    assert len(details) == len(flagged)
    for record, block in zip(flagged, details, strict=True):
        assert f'data-order="{record.order}"' in block
        assert 'class="badge flagged"' in block
        assert record.check is not None and record.check.note is not None
        assert str(escape(record.check.note)) in block

    assert '<span class="badge error">error</span>' in html
    assert 'title="timed out"' in html
    assert '<span class="badge checking">checking</span>' in html


def test_markdown_export_lists_every_step_with_its_status(
    sap_runbook: Runbook, sap_checks: list[CheckRecord]
) -> None:
    unchecked, *checks = sap_checks
    checks[-1] = CheckRecord(order=checks[-1].order, error="timed out")
    md = render_markdown(status_for(sap_runbook, checks=checks))

    assert md.startswith(f"# {sap_runbook.title}\n")
    assert sap_runbook.system in md
    for item in sap_runbook.prerequisites + sap_runbook.pitfalls:
        assert f"- {item}" in md
    step_lines = [line for line in md.splitlines() if re.match(r"\| \d+ \|", line)]
    assert len(step_lines) == len(sap_runbook.steps)
    for step, line in zip(sap_runbook.steps, step_lines, strict=True):
        for text in (mmss(step.timestamp_s), step.action, step.target, step.screen, step.intent):
            assert text in line
        if step.value:
            assert step.value in line
    assert "checking" in step_lines[unchecked.order - 1]
    assert "error" in step_lines[-1] and "timed out" in step_lines[-1]
    for record in checks:
        if record.badge == "flagged":
            assert record.check is not None and record.check.note is not None
            assert record.check.note in step_lines[record.order - 1]
            assert "flagged" in step_lines[record.order - 1]
    assert "verified" in step_lines[1]


def test_markdown_export_needs_a_runbook() -> None:
    with pytest.raises(ValueError, match="no runbook yet"):
        render_markdown(status_for(None, state="watching"))


def test_every_runbook_has_the_same_sections_in_order(sap_runbook: Runbook) -> None:
    assert sap_runbook.prerequisites == [] and sap_runbook.pitfalls
    html = render_fragment(status_for(sap_runbook))
    md = render_markdown(status_for(sap_runbook))

    assert html.index("Prerequisites") < html.index("Pitfalls")
    assert html.count("None recorded.") == 1
    assert md.index("## Prerequisites") < md.index("## Steps") < md.index("## Pitfalls")
    assert md.count("None recorded.") == 1

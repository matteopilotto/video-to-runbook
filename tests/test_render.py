import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from markupsafe import escape

from video_to_runbook.models import CheckRecord, Runbook, RunStatus, Step, StepCheck
from video_to_runbook.render import instruction, mmss, render_fragment, render_markdown


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
        created_at=datetime(2026, 9, 19, 14, 30, tzinfo=UTC),
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
    step_lines = [line for line in md.splitlines() if re.match(r"\d+\. ", line)]
    assert len(step_lines) == len(sap_runbook.steps)
    for step, line in zip(sap_runbook.steps, step_lines, strict=True):
        assert line.startswith(f"{step.order}. **{mmss(step.timestamp_s)}** ")
        assert f"{instruction(step)}, to {step.intent}." in line
    assert step_lines[unchecked.order - 1].endswith("`checking`")
    assert step_lines[-1].endswith("`error`: timed out")
    for record in checks:
        if record.badge == "flagged":
            assert record.check is not None and record.check.note is not None
            assert step_lines[record.order - 1].endswith(f"`flagged`: {record.check.note}")
    assert step_lines[1].endswith("`verified`")
    assert "|" not in md


@pytest.mark.parametrize(
    ("action", "value", "expected"),
    [
        ("click", None, "Click **Add** on the Sales Order screen"),
        ("type", "06/30/2019", "Type `06/30/2019` into **Add** on the Sales Order screen"),
        ("select", None, "Select **Add** on the Sales Order screen"),
        ("navigate", None, "Go to **Add** on the Sales Order screen"),
        ("wait", None, "Wait for **Add** on the Sales Order screen"),
        ("verify", None, "Check **Add** on the Sales Order screen"),
    ],
)
def test_instruction_is_one_imperative_sentence(
    action: str, value: str | None, expected: str
) -> None:
    step = Step(
        order=1,
        timestamp_s=5.0,
        action=action,  # type: ignore[arg-type]
        target="Add",
        value=value,
        screen="Sales Order",
        intent="save the order",
    )
    assert instruction(step) == expected


def test_markdown_export_opens_with_provenance_and_check_counts(sap_runbook: Runbook) -> None:
    checks = [
        CheckRecord(order=1, check=StepCheck(order=1, matches=True, confidence=0.9)),
        CheckRecord(order=2, check=StepCheck(order=2, matches=False, confidence=0.8, note="n")),
        CheckRecord(order=3, error="timed out"),
    ]
    md = render_markdown(status_for(sap_runbook, checks=checks))

    header = (
        "Recorded from clip.mp4 (01:58), generated 2026-09-19 by Video-to-Runbook.\n\n"
        f"Checks: 1 verified, 1 flagged, 1 not checked, {len(sap_runbook.steps) - 3} pending."
    )
    assert header in md
    assert md.index(sap_runbook.system) < md.index(header) < md.index("## Prerequisites")


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


def test_outcome_section_sits_between_steps_and_pitfalls(sap_runbook: Runbook) -> None:
    html = render_fragment(status_for(sap_runbook))
    md = render_markdown(status_for(sap_runbook))

    assert html.index("Prerequisites") < html.index("Outcome") < html.index("Pitfalls")
    assert sap_runbook.outcome in html
    assert md.index("## Steps") < md.index("## Outcome") < md.index("## Pitfalls")
    assert f"## Outcome\n\n{sap_runbook.outcome}\n" in md

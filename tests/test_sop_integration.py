"""The seams between the video pipeline and the SOP pipeline.

No Modal, no Gemini, no SAP: this covers the wiring that the three of them meet at.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_to_runbook import runs
from video_to_runbook.models import Runbook, RunMeta, Step
from video_to_runbook.render import render_markdown
from video_to_runbook.sop.execute import Executor
from video_to_runbook.sop.plan_schema import ExecutionPlan


def make_run(tmp_path: Path) -> Path:
    run_dir = runs.run_dir(tmp_path, "abc123")
    run_dir.mkdir(parents=True)
    runs.write_meta(
        run_dir,
        RunMeta(
            run_id="abc123",
            filename="v.mp4",
            duration_s=10.0,
            created_at=datetime.now(UTC),
            state="done",
        ),
    )
    runs.write_runbook(
        run_dir,
        Runbook(
            title="Create an Entrega",
            system="SAP Business One",
            steps=[
                Step(
                    order=1,
                    timestamp_s=1.0,
                    action="click",
                    target="the Orders tile",
                    screen="Main menu",
                    intent="open the order",
                )
            ],
        ),
    )
    return run_dir


def test_sop_fields_default_to_none(tmp_path):
    status = runs.read_status(make_run(tmp_path))
    assert status.plan_state == "none"
    assert status.exec_state == "none"
    assert status.plan_validated is False


def test_the_runbook_renders_to_sop_text(tmp_path):
    """The bridge: what the Observer produced is what the Architect compiles."""
    sop_text = render_markdown(runs.read_status(make_run(tmp_path)))
    assert "Create an Entrega" in sop_text
    assert "the Orders tile" in sop_text


def test_plan_round_trips_through_the_run_dir(tmp_path):
    run_dir = make_run(tmp_path)
    assert runs.read_plan(run_dir) is None
    runs.write_plan(run_dir, '{"plan": {"process_name": "p"}}')
    assert json.loads(runs.read_plan(run_dir))["plan"]["process_name"] == "p"


def test_sop_state_survives_a_meta_round_trip(tmp_path):
    run_dir = make_run(tmp_path)
    meta = runs.read_meta(run_dir)
    meta.plan_state, meta.plan_validated = "planned", True
    meta.exec_state, meta.exec_live = "requested", True
    runs.write_meta(run_dir, meta)
    status = runs.read_status(run_dir)
    assert (status.plan_state, status.plan_validated) == ("planned", True)
    assert (status.exec_state, status.exec_live) == ("requested", True)


class StubSAP:
    def request(self, method, path, body=None):
        return {"value": [{"DocEntry": 1, "CardCode": "C1"}]}


PLAN = {
    "process_name": "Entrega",
    "assumptions": [],
    "open_questions": [],
    "inputs": [{"name": "order_number", "type": "number", "description": "d"}],
    "steps": [
        {
            "kind": "api_call",
            "step_id": "get_order",
            "reason": "r",
            "entity": "Orders",
            "method": "GET",
            "path": "Orders?$filter=DocNum eq ${inputs.order_number}",
            "body": {},
        },
        {
            "kind": "api_call",
            "step_id": "create",
            "reason": "r",
            "entity": "DeliveryNotes",
            "method": "POST",
            "path": "DeliveryNotes",
            "body": {"CardCode": "${get_order.value[0].CardCode}"},
        },
    ],
}


def test_the_plan_the_worker_runs_is_a_valid_ExecutionPlan():
    ExecutionPlan.model_validate(PLAN)


def test_dry_run_never_sends_a_write():
    trace = {r.step_id: r for r in Executor(PLAN, StubSAP(), live=False).run({"order_number": 1})}
    assert trace["get_order"].status == "ran"
    assert trace["create"].status == "simulated"
    assert trace["create"].result["__would_send__"] == {"CardCode": "C1"}


@pytest.mark.parametrize("live,expected", [(False, "simulated"), (True, "ran")])
def test_live_is_what_decides_whether_sap_is_written_to(live, expected):
    trace = {r.step_id: r for r in Executor(PLAN, StubSAP(), live=live).run({"order_number": 1})}
    assert trace["create"].status == expected

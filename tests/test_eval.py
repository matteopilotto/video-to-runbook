import json
from pathlib import Path

import pytest

from video_to_runbook.eval import EvalScore, TruthCase, TruthStep, load_truth, pair, score
from video_to_runbook.models import CheckRecord, Runbook, Step

REPO = Path(__file__).parents[1]


def make_step(order: int, timestamp_s: float, action: str = "click") -> Step:
    return Step(
        order=order,
        timestamp_s=timestamp_s,
        action=action,
        target=f"Button {order}",
        screen="Sales Order",
        intent=f"Do thing {order}",
    )


def make_truth(order: int, timestamp_s: float, action: str = "click") -> TruthStep:
    return TruthStep(order=order, timestamp_s=timestamp_s, action=action, target=f"Truth {order}")


def test_load_truth_parses_both_tables() -> None:
    cases = load_truth(REPO / "samples" / "README.md")

    assert [c.name for c in cases] == [
        "sap_b1_create_sales_order_demo",
        "google_ai_studio_api_key_screen_only",
    ]
    assert [c.video.name for c in cases] == [
        "sap_b1_create_sales_order_demo.mp4",
        "google_ai_studio_api_key_screen_only.mp4",
    ]
    assert [len(c.steps) for c in cases] == [14, 7]
    assert [c.offset_s for c in cases] == [10.0, 14.6]
    sap_first = cases[0].steps[0]
    assert sap_first.order == 1
    assert sap_first.timestamp_s == 11.0
    assert sap_first.action == "navigate"
    assert sap_first.target == "Modules > Sales A/R > Sales Order"


def test_pair_takes_nearest_within_three_seconds() -> None:
    produced = [make_step(1, 5.0), make_step(2, 12.0), make_step(3, 30.0)]
    truth = [make_truth(1, 7.0), make_truth(2, 12.5), make_truth(3, 20.0)]
    assert pair(produced, truth) == [(1, 1), (2, 2)]


def test_pair_uses_each_produced_step_once() -> None:
    produced = [make_step(1, 10.0)]
    truth = [make_truth(1, 9.0), make_truth(2, 11.0)]
    assert pair(produced, truth) == [(1, 1)]


def test_pair_leaves_unmatched_truth_step_alone() -> None:
    produced = [make_step(1, 10.0)]
    truth = [make_truth(1, 3.0), make_truth(2, 20.0)]
    assert pair(produced, truth) == []


def test_pair_tie_goes_to_the_earlier_produced_step() -> None:
    produced = [make_step(1, 8.0), make_step(2, 12.0)]
    truth = [make_truth(1, 10.0)]
    assert pair(produced, truth) == [(1, 1)]


def test_pair_subtracts_the_offset_from_truth() -> None:
    produced = [make_step(1, 1.0)]
    truth = [make_truth(1, 11.0)]
    assert pair(produced, truth, offset_s=10.0) == [(1, 1)]
    assert pair(produced, truth) == []


@pytest.fixture
def sap_case() -> TruthCase:
    return load_truth(REPO / "samples" / "README.md")[0]


def test_score_on_the_fixtures(fixtures_dir: Path, sap_case: TruthCase) -> None:
    runbook = Runbook.model_validate_json((fixtures_dir / "runbook.json").read_text())
    checks = [
        CheckRecord.model_validate(r)
        for r in json.loads((fixtures_dir / "checks.json").read_text())
    ]

    result = score(runbook, checks, sap_case)

    assert isinstance(result, EvalScore)
    assert result.case == "sap_b1_create_sales_order_demo"
    assert result.produced_steps == len(runbook.steps)
    assert result.truth_steps == 14
    assert result.step_count_diff == len(runbook.steps) - 14
    assert 0.0 <= result.timestamp_agreement <= 1.0
    assert 0.0 <= result.action_match <= 1.0
    assert 0.0 <= result.check_agreement <= 1.0
    assert result.timestamp_agreement == len(result.pairs) / 14


def test_score_counts_error_records_as_not_verified(sap_case: TruthCase) -> None:
    runbook = Runbook(
        title="t",
        system="s",
        outcome="o",
        steps=[make_step(1, 1.0), make_step(2, 6.0), make_step(3, 8.0)],
    )
    checks = [
        CheckRecord(order=1, check={"order": 1, "matches": True, "confidence": 1.0}),
        CheckRecord(order=2, error="timed out"),
        CheckRecord(order=3, check={"order": 3, "matches": False, "confidence": 1.0, "note": "n"}),
    ]

    assert score(runbook, checks, sap_case).check_agreement == pytest.approx(1 / 3)


def test_score_action_match_is_zero_without_pairs(sap_case: TruthCase) -> None:
    runbook = Runbook(title="t", system="s", outcome="o", steps=[make_step(1, 20.0)])

    result = score(runbook, [], sap_case)

    assert result.pairs == []
    assert result.timestamp_agreement == 0.0
    assert result.action_match == 0.0
    assert result.check_agreement == 0.0

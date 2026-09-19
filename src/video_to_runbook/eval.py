"""Score the Observer against the ground-truth tables in samples/README.md.

uv run python -m video_to_runbook.eval                       # both cases, hits Gemini
uv run python -m video_to_runbook.eval samples/<clip>.mp4     # one case
uv run python -m video_to_runbook.eval --from tests/fixtures/sap   # saved run, no network
"""

import argparse
import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from video_to_runbook.config import get_settings
from video_to_runbook.frames import extract_frames, probe_duration
from video_to_runbook.models import CheckRecord, Runbook, Step
from video_to_runbook.observer import ObserverDeps, observe
from video_to_runbook.tracing import setup_logfire
from video_to_runbook.validator import check_step

TOLERANCE_S = 3.0
OFFSETS_S = {
    "sap_b1_create_sales_order_demo.mp4": 10.0,
    "google_ai_studio_api_key_screen_only.mp4": 14.6,
}
HEADING = re.compile(r"^## (\S+\.mp4)")
ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(\d+):(\d+)\s*\|\s*(\w+)\s*\|\s*(.*?)\s*\|$")


class TruthStep(BaseModel):
    order: int
    timestamp_s: float  # original video clock, before the cut offset
    action: str
    target: str


class TruthCase(BaseModel):
    name: str
    video: Path
    offset_s: float
    steps: list[TruthStep]


class RunOutput(BaseModel):
    runbook: Runbook
    checks: list[CheckRecord]


class EvalScore(BaseModel):
    case: str
    produced_steps: int
    truth_steps: int
    step_count_diff: int
    timestamp_agreement: float
    action_match: float
    check_agreement: float
    pairs: list[tuple[int, int]]  # (truth order, produced order)


def load_truth(readme: Path) -> list[TruthCase]:
    """Parse the `| # | t (orig) | action | target |` tables under each clip's heading."""
    cases: list[TruthCase] = []
    current: TruthCase | None = None
    for line in readme.read_text().splitlines():
        heading = HEADING.match(line)
        if heading:
            filename = heading.group(1)
            current = None
            if filename in OFFSETS_S:
                current = TruthCase(
                    name=Path(filename).stem,
                    video=readme.parent / filename,
                    offset_s=OFFSETS_S[filename],
                    steps=[],
                )
                cases.append(current)
            continue
        row = ROW.match(line)
        if row and current is not None:
            order, minutes, seconds, action, target = row.groups()
            current.steps.append(
                TruthStep(
                    order=int(order),
                    timestamp_s=int(minutes) * 60 + int(seconds),
                    action=action,
                    target=target,
                )
            )
    return cases


def pair(
    produced: Sequence[Step], truth: Sequence[TruthStep], offset_s: float = 0.0
) -> list[tuple[int, int]]:
    """FR-027a: each truth step takes the nearest unpaired produced step within 3 s."""
    pairs: list[tuple[int, int]] = []
    taken: set[int] = set()
    for t in truth:
        target_s = t.timestamp_s - offset_s
        best: Step | None = None
        best_distance: float | None = None
        for p in produced:
            distance = abs(p.timestamp_s - target_s)
            if p.order in taken or distance > TOLERANCE_S:
                continue
            if best_distance is None or distance < best_distance:
                best, best_distance = p, distance
        if best is not None:
            taken.add(best.order)
            pairs.append((t.order, best.order))
    return pairs


def score(runbook: Runbook, checks: Sequence[CheckRecord], truth: TruthCase) -> EvalScore:
    pairs = pair(runbook.steps, truth.steps, truth.offset_s)
    produced = {s.order: s for s in runbook.steps}
    expected = {t.order: t for t in truth.steps}
    same_action = sum(1 for t, p in pairs if produced[p].action == expected[t].action)
    verified = sum(1 for c in checks if c.badge == "verified")
    return EvalScore(
        case=truth.name,
        produced_steps=len(runbook.steps),
        truth_steps=len(truth.steps),
        step_count_diff=len(runbook.steps) - len(truth.steps),
        timestamp_agreement=len(pairs) / len(truth.steps),
        action_match=same_action / len(pairs) if pairs else 0.0,
        check_agreement=verified / len(runbook.steps),
        pairs=pairs,
    )


def _score(ctx: EvaluatorContext[TruthCase, RunOutput, None]) -> EvalScore:
    assert ctx.expected_output is not None
    return score(ctx.output.runbook, ctx.output.checks, ctx.expected_output)


@dataclass
class StepCountDiff(Evaluator[TruthCase, RunOutput, None]):
    def evaluate(self, ctx: EvaluatorContext[TruthCase, RunOutput, None]) -> float:
        return _score(ctx).step_count_diff


@dataclass
class TimestampAgreement(Evaluator[TruthCase, RunOutput, None]):
    def evaluate(self, ctx: EvaluatorContext[TruthCase, RunOutput, None]) -> float:
        return _score(ctx).timestamp_agreement


@dataclass
class ActionMatch(Evaluator[TruthCase, RunOutput, None]):
    def evaluate(self, ctx: EvaluatorContext[TruthCase, RunOutput, None]) -> float:
        return _score(ctx).action_match


@dataclass
class CheckAgreement(Evaluator[TruthCase, RunOutput, None]):
    def evaluate(self, ctx: EvaluatorContext[TruthCase, RunOutput, None]) -> float:
        return _score(ctx).check_agreement


def build_dataset(cases: Sequence[TruthCase]) -> Dataset[TruthCase, RunOutput, None]:
    return Dataset(
        name="observer-eval",
        cases=[Case(name=c.name, inputs=c, expected_output=c) for c in cases],
        evaluators=[StepCountDiff(), TimestampAgreement(), ActionMatch(), CheckAgreement()],
    )


async def run_case(case: TruthCase) -> RunOutput:
    """Observer then one check per step, in-process, the same calls the Modal app makes."""
    settings = get_settings()
    duration = probe_duration(case.video)
    deps = ObserverDeps(run_id=f"eval-{case.name}", video_path=case.video, duration_s=duration)
    result = await observe(deps)
    checks = await asyncio.gather(
        *(
            check_step(
                step,
                extract_frames(case.video, step.timestamp_s, duration, settings.frame_offsets_s),
            )
            for step in result.runbook.steps
        )
    )
    return RunOutput(runbook=result.runbook, checks=list(checks))


def load_saved(saved: Path) -> RunOutput:
    """A run's runbook.json and checks.json as written by the integration tests."""
    runbook = Runbook.model_validate_json((saved / "runbook.json").read_text())
    checks = [
        CheckRecord.model_validate(r) for r in json.loads((saved / "checks.json").read_text())
    ]
    return RunOutput(runbook=runbook, checks=checks)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("video", nargs="?", type=Path, help="restrict to this sample clip")
    parser.add_argument(
        "--from",
        dest="saved",
        type=Path,
        help="score a saved runbook.json and checks.json instead of calling Gemini "
        "(defaults to the SAP case unless a clip is given)",
    )
    args = parser.parse_args(argv)
    setup_logfire()

    readme = Path(__file__).parents[2] / "samples" / "README.md"
    cases = load_truth(readme)
    if args.video is not None:
        cases = [c for c in cases if c.video.name == args.video.name]
        if not cases:
            parser.error(f"{args.video.name} has no ground-truth table in {readme}")
    elif args.saved is not None:
        cases = cases[:1]

    if args.saved is not None:

        async def task(case: TruthCase) -> RunOutput:
            return load_saved(args.saved)
    else:
        task = run_case

    report = build_dataset(cases).evaluate_sync(task, progress=False)
    report.print(include_durations=False)


if __name__ == "__main__":
    main()

# Data Model: Observer Pipeline End to End

All entities are Pydantic models in `src/video_to_runbook/models.py` unless noted. They are
the only things that cross a function, file, or HTTP edge (Constitution II). Validators
encode domain truth, not just shape; anything that needs the video's duration is checked in
the observer agent's output validator because the model alone does not know the duration.

## Step

One action inside a runbook. Returned by the Observer as part of `Runbook`.

| Field | Type | Rule |
| --- | --- | --- |
| `order` | `int` | ≥ 1. Contiguity is checked on `Runbook`. |
| `timestamp_s` | `float` | ≥ 0. Accepts `"MM:SS"`, `"M:SS"`, `"H:MM:SS"`, or a number (before-validator converts to seconds). Upper bound checked against video duration in the Observer output validator. |
| `action` | `Literal["click","type","select","navigate","wait","verify"]` | Exactly this set (FR-006). |
| `target` | `str` | Stripped, ≥ 3 characters, and not in the generic deny-list (`button`, `the button`, `field`, `the field`, `screen`, `the screen`, `it`, `here`, `there`, `element`, `the element`, `link`, `the link`). Case-insensitive. (FR-008) |
| `value` | `str \| None` | Default `None`. |
| `screen` | `str` | Non-empty after strip. |
| `intent` | `str` | Non-empty after strip. |

## Runbook

The Observer's typed output (`output_type=Runbook`).

| Field | Type | Rule |
| --- | --- | --- |
| `title` | `str` | Non-empty. |
| `system` | `str` | Non-empty. |
| `prerequisites` | `list[str]` | May be empty. |
| `steps` | `list[Step]` | `min_length=1` (an empty runbook is not a runbook). |
| `pitfalls` | `list[str]` | May be empty. |

Model validators (raise `ValueError`, which Pydantic AI turns into a retry with the message):

- `orders_contiguous`: `[s.order for s in steps] == [1, 2, ..., len(steps)]`. Message names the first step that breaks the sequence.
- `timestamps_increasing`: `steps[i].timestamp_s < steps[i+1].timestamp_s` for all `i`. Message names the offending step and both timestamps.

Observer output validator (`observer.py`, has `RunContext[ObserverDeps]`, raises `ModelRetry`):

- `within_duration`: every `timestamp_s ≤ deps.duration_s`. Message: `"step {order} timestamp {t} s is beyond the video duration {d} s"`.

## ObserverDeps

Typed dependencies for the Observer run (`observer.py`, a dataclass, not persisted).

| Field | Type |
| --- | --- |
| `run_id` | `str` |
| `video_path` | `Path` |
| `duration_s` | `float` |

## StepCheck

The Validator's typed output (`output_type=StepCheck`) for one step.

| Field | Type | Rule |
| --- | --- | --- |
| `order` | `int` | Must equal the step it was asked about (checked by the caller, not the model). |
| `matches` | `bool` | |
| `confidence` | `float` | `0 ≤ confidence ≤ 1`. |
| `note` | `str \| None` | Required (non-empty) when `matches` is `False`; model validator. |

## CheckRecord

What the pipeline stores per step after its check finishes, so a failed check is kept, never
dropped (FR-015). Written by `validate_step`; one file per step, no shared state.

| Field | Type | Rule |
| --- | --- | --- |
| `order` | `int` | |
| `check` | `StepCheck \| None` | Set when the Validator returned. |
| `error` | `str \| None` | Set when the Validator could not complete (timeout, exhausted retries, cap). |
| `requests` | `int` | Model calls this check consumed (for the cap and the footer). |
| `input_tokens` / `output_tokens` | `int` | From the run usage. |

Validator: exactly one of `check`, `error` is set.

Derived `badge` (a property, also `Literal["checking","verified","flagged","error"]`):

| Condition | Badge |
| --- | --- |
| No `CheckRecord` for the step yet | `checking` |
| `check.matches` is `True` | `verified` |
| `check.matches` is `False` | `flagged` |
| `error` is set | `error` |

## RunMeta

Written by `ingest` at upload time; the only mutable per-run record, and only `observe`
writes to it after that (never the validators).

| Field | Type | Notes |
| --- | --- | --- |
| `run_id` | `str` | 12 hex chars from `secrets.token_hex(6)`. |
| `filename` | `str` | Original upload name, display only. |
| `duration_s` | `float` | From `ffprobe` at ingest. |
| `created_at` | `datetime` | UTC. |
| `tamper_step` | `int \| None` | From the hidden page parameter (FR-017). |
| `state` | `Literal["uploaded","watching","checking","done","failed"]` | Lifecycle below. |
| `error` | `str \| None` | Set with `failed`. |
| `tamper_applied` | `bool` | `True` only if `tamper_step` existed in the runbook. |
| `observer_requests` | `int` | Model calls the Observer used, including retries. |
| `observer_input_tokens` / `observer_output_tokens` | `int` | |
| `finished_at` | `datetime \| None` | Set on `done` or `failed`. |
| `trace_url` | `str \| None` | Link to the run's trace, set by `observe`. |

## RunStatus

The `GET /runs/{run_id}` payload, assembled from the Volume on each poll (never stored).

| Field | Type | Source |
| --- | --- | --- |
| `run_id`, `state`, `error`, `duration_s`, `filename`, `tamper_step`, `tamper_applied`, `trace_url` | as above | `RunMeta` |
| `runbook` | `Runbook \| None` | `runbook.json` if present |
| `checks` | `list[CheckRecord]` | every `checks/{order}.json` present, sorted by `order` |
| `elapsed_s` | `float` | `(finished_at or now) - created_at` |
| `calls` | `int` | `observer_requests + sum(check.requests)` |
| `input_tokens` / `output_tokens` | `int` | Observer plus checks |
| `video_url` | `str` | `/runs/{run_id}/video` |

## Ground-truth case and eval score (`eval.py`)

| Model | Fields |
| --- | --- |
| `TruthStep` | `order: int`, `timestamp_s: float` (original clock), `action: str`, `target: str` |
| `TruthCase` | `name: str`, `video: Path`, `offset_s: float` (10.0 SAP demo, 14.6 AI Studio), `steps: list[TruthStep]`, parsed from the tables in `samples/README.md` |
| `EvalScore` | `case: str`, `produced_steps: int`, `truth_steps: int`, `step_count_diff: int`, `timestamp_agreement: float`, `action_match: float`, `check_agreement: float`, `pairs: list[tuple[int,int]]` |

Pairing rule (FR-027a): for each truth step in table order, take the nearest not-yet-paired
produced step with `|produced.timestamp_s - (truth.timestamp_s - offset_s)| ≤ 3`.
`timestamp_agreement = paired / truth_steps`; `action_match = same_action_pairs / paired`
(0 when nothing paired); `check_agreement = verified / produced_steps` on an untampered run
(FR-027b), with `error` records counting as not verified.

## Run lifecycle

```
uploaded ──observe starts──▶ watching ──runbook.json written──▶ checking ──all checks/*.json present──▶ done
    │                            │                                   │
    └── ingest failed ───────────┴── observer exhausted retries ─────┴── cap tripped ──▶ failed (error set)
```

- `ingest` writes `video.mp4` and `meta.json` with `state=uploaded`, then spawns `observe`.
- `observe` sets `watching`, runs the Observer, applies the tamper if requested, writes
  `runbook.json`, sets `checking`, fans out `validate_step.map(...)`, then sets `done`
  (or `failed` with the reason). Each `validate_step` writes only `checks/{order}.json`.
- A `failed` run still returns whatever `runbook.json` and `checks/*.json` exist.

## Volume layout

```
/data/runs/{run_id}/
├── video.mp4
├── meta.json          # RunMeta
├── runbook.json       # Runbook (post-tamper if applied)
└── checks/
    ├── 1.json         # CheckRecord
    └── ...
```

Kept until cleared by hand (FR-026a).

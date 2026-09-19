# Implementation Plan: Observer Pipeline End to End

**Branch**: `001-observer-pipeline` | **Date**: 2026-09-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-observer-pipeline/spec.md`

## Summary

Upload a screen recording, have a Pro-class Gemini model return a rule-checked `Runbook`
through Pydantic AI (schema validators plus an output validator that raises `ModelRetry`),
fan out one Flash-class check per step over three frames cut by ffmpeg, and show the result
on a single static page whose badges flip as checks land, with every run traced in Logfire
and scored by a Pydantic Evals dataset built from the ground-truth tables. Modal hosts the
web endpoint, the spawned Observer job, and the mapped validators; the core modules run on
a laptop without Modal or network. Design decisions and their evidence are in
[research.md](research.md).

## Technical Context

**Language/Version**: Python 3.13 (`requires-python >= 3.13` in `pyproject.toml`)

**Primary Dependencies**: pydantic-ai 2.46 (Google provider, `pydantic-evals`, `google-genai`
2.24 come with it), pydantic 2.13, pydantic-settings 2.15, logfire 5.1, jinja2,
fastapi[standard] (brings python-multipart), modal 1.5.5; dev: pytest, ruff. System: ffmpeg,
ffprobe.

**Storage**: One Modal Volume mounted at `/data`, layout in [data-model.md](data-model.md);
files kept until cleared by hand. No database.

**Testing**: pytest. Unit tests with golden fixtures and `FunctionModel`, no network;
`@pytest.mark.integration` for Gemini, skipped without `GEMINI_API_KEY`. `eval.py` for
Observer quality.

**Target Platform**: Modal (Linux containers, `debian_slim` 3.13 with ffmpeg) plus any
modern desktop browser for the page. Local runs for tests and the eval on macOS.

**Project Type**: Web service (three Modal functions) with a static single page, plus a CLI
eval.

**Performance Goals**: Drop to all badges terminal under 3 minutes for a 2-minute clip
(SC-002); video visible and "watching" within 5 s (SC-003); default test suite under 5 s
(SC-008).

**Constraints**: Uploads ≤ 100 MB and `video/*` only; 60 model calls per run, budgeted by
construction (R5); every model call has a timeout and a bounded retry; Observer on
`gemini-3.1-pro-preview`, Validator on `gemini-3.8-flash`; Pro is paid-only, so the stage key
must be billed or on credits; core modules import without Modal or network.

**Scale/Scope**: One operator, two sample clips (118 s and 51 s, about 5 MB each), runbooks
of roughly 7 to 18 steps, a handful of runs per hour on stage. Two simultaneous runs must
not interfere.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle / invariant | How this plan satisfies it | Status |
| --- | --- | --- |
| I. Pure core, thin glue | `models.py`, `observer.py`, `validator.py`, `frames.py`, `render.py`, `config.py`, `tracing.py`, `runs.py`, `eval.py` import without Modal; `app.py` is the only module importing `modal`, holds three functions that delegate to the core, and keeps no run-state logic of its own (tamper, cap slots, status assembly live in `runs.py` with their own tests). | Pass |
| II. Typed at every boundary | Every file and HTTP payload is a model in data-model.md; `config.py` is one `BaseSettings`; agents declare `output_type=Runbook` / `StepCheck`; validators encode duration, contiguity, monotonic timestamps, non-generic targets. No hand-parsed JSON. | Pass |
| III. Tests that run in a second | One test module per core module on `tests/fixtures/sap/`; `FunctionModel` for agent behaviour; synthetic 3 s clip for ffmpeg; integration tests marked and skipped without the key. | Pass |
| IV. An eval, not a vibe check | `eval.py` scores both cases per FR-027a/b, subtracts the 10 s / 14.6 s offsets, prints, and README records the numbers. | Pass |
| V. Failures are visible | Timeouts and `HttpRetryOptions` on every call; `CheckRecord.error` keeps failed checks; `error` badge distinct from `flagged`; `logfire.configure()` and `instrument_pydantic_ai()` at container start; `runbook` span with `run_id`; `UsageLimits` cap trips as `logfire.error`. Wired in the first commit that makes a model call. | Pass |
| VI. Fixed scope, simplest mechanism | Observer, Validator, Renderer only. No executors, gateway, auth, multi-user, queues in code. Static page, no framework. Budget cap instead of a shared counter. | Pass |
| Gemini looks, Modal touches files | Uploads, Volume, ffmpeg, fan-out in `app.py` and `frames.py`; agents receive bytes and return models. | Pass |
| `ingest` returns `run_id` immediately | `POST /runs` writes, commits, `observe.spawn`, returns 202. | Pass |
| Validation fans out with `validate_step.map(steps)` | Each check reads its step and its frames, writes only `checks/{order}.json`. | Pass |
| Model tiers fixed | Pro for Observer, Flash for Validator, defaults in `config.py`, override documented as a deliberate change. | Pass |
| Every `Step` carries `timestamp_s` | Required float field, MM:SS converted, ≤ duration enforced. | Pass |
| Secrets never in the repo | `GEMINI_API_KEY`, `LOGFIRE_TOKEN` from Modal Secrets or gitignored `.env`; `config.py` reads the environment only. | Pass |

Post-design re-check (after Phase 1): no violations. The only structural deviation from the
brief is that `render` is a core module used by the web function rather than a fourth Modal
function; this is simpler, not more complex, and the `CLAUDE.md` line that lists `render`
among the wired functions is updated in the `app.py` commit. Complexity Tracking stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-observer-pipeline/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1 to R14 with evidence
├── data-model.md        # Phase 1: entities, validators, lifecycle, Volume layout
├── quickstart.md        # Phase 1: runnable validation, gate to demo
├── contracts/
│   ├── http-api.md      # six routes, RunStatus example
│   └── page.md          # page states, interactions, badge contract
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
pyproject.toml                         # deps added (R14), ruff + pytest config, integration marker
.github/workflows/ci.yml               # apt ffmpeg; ruff format --check; ruff check; pytest
README.md                              # architecture, setup, demo, decisions, eval scores, roadmap
src/video_to_runbook/
├── __init__.py
├── config.py                          # Settings(BaseSettings): models, cap, limits, timeouts, paths, logfire URL
├── models.py                          # Step, Runbook, StepCheck, CheckRecord, RunMeta, RunStatus
├── frames.py                          # probe_duration(), extract_frames() via ffprobe/ffmpeg
├── observer.py                        # ObserverDeps, observer agent, output validator, observe()
├── validator.py                       # validator agent, check_step(step, frames) -> StepCheck
├── render.py                          # render_fragment(status), render_markdown(status)
├── tracing.py                         # setup_logfire(), trace_url(run_id); no Modal import
├── runs.py                            # run dir I/O, read_status(), apply_tamper(), budget_slots(), capped_records()
├── eval.py                            # truth parsing, evaluators, Dataset, __main__
├── templates/
│   ├── runbook.html.j2
│   └── runbook.md.j2
├── static/
│   └── index.html                     # shell: CSS + JS, no build step
└── app.py                             # modal.App: web (asgi), observe, validate_step
tests/
├── conftest.py                        # fixture loaders, synthetic clip
├── fixtures/sap/
│   ├── runbook.json
│   └── checks.json
├── test_config.py
├── test_models.py
├── test_frames.py
├── test_observer.py
├── test_validator.py
├── test_render.py
├── test_tracing.py
├── test_runs.py
├── test_eval.py
└── integration/
    └── test_gemini.py                 # @pytest.mark.integration
```

**Structure Decision**: Single `src/` package as the constitution prescribes, with
templates and the static page inside the package so one `add_local_dir` ships them to
Modal and `PackageLoader` finds them locally. Tests mirror the modules one to one.

## Complexity Tracking

No constitution violations to justify.

## Build order (input to /speckit-tasks)

The timeline in the handoff (Modal app by 16:00, renderer by 17:30, polish by 18:30,
rehearse by 19:00) suggests this sequence, each step one commit that passes the gate:

1. `pyproject.toml` deps, ruff and pytest config, `.github/workflows/ci.yml`, `config.py`
   with its test. README skeleton.
2. `models.py` with every validator and `test_models.py` (MM:SS, contiguity, monotonic,
   generic target, note-required, CheckRecord badge).
3. `frames.py` and `test_frames.py` on a synthetic clip.
4. `observer.py` with Logfire wired, output validator, `FunctionModel` retry test, and the
   integration test; first real run on the SAP sample; record `tests/fixtures/sap/runbook.json`.
5. `validator.py`, retry test on missing note, integration test; record `checks.json`.
6. `eval.py` with evaluators tested on the fixtures; first scores into README.
7. `render.py`, templates, `index.html`, `test_render.py` on the fixtures.
8. `app.py`: web, observe, validate_step, tamper, cap slots, trace propagation; `CLAUDE.md`
   commands updated to `uv run modal ...`; `modal serve` walk-through from quickstart §4.
9. Demo polish: tamper rehearsal, cap rehearsal, `min_containers=1`, README final.

Follow-ups deliberately outside this feature: the Observer frame tool with typed deps and
its packaging as a Pydantic AI `Capability` (verified available in 2.46), and the Files API
path for uploads above 20 MB if inline ever fails.

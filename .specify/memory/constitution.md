# Video-to-Runbook Constitution

## Core Principles

### I. Pure Core, Thin Glue

The package `src/video_to_runbook/` MUST keep `models.py`, `observer.py`, `validator.py`,
`frames.py`, `render.py`, and `config.py` importable without Modal installed and without
network access. `app.py` MUST be the only module that imports `modal`; it wires the core into
the `ingest`, `observe`, `validate_step`, and `render` functions and contains no logic of its
own. A core module that reaches for a Modal object, a Volume path, or a live Gemini client at
import time is a defect.

Rationale: the core is what gets unit-tested, evaluated, and read by a judge. Keeping the
platform at the edge lets everything else run on a laptop in under a second.

### II. Typed at Every Boundary

Anything that crosses a function, file, or HTTP edge MUST be a Pydantic model. `config.py`
MUST be a single `pydantic-settings` class and the only source of model names, limits, and
paths. Every function signature MUST carry type hints. Agents MUST declare
`output_type=Runbook` or `output_type=StepCheck` and rely on Pydantic AI's built-in retry on
validation failure. Hand-parsing JSON out of a model response is a regression and MUST NOT be
merged. Validators MUST encode domain truth, not just shape: a `Step` without a usable
`timestamp_s` is a schema failure, not a step.

Rationale: the product's whole claim is that fuzzy video becomes a rigid, checkable
structure. The schema is the contract, and Pydantic AI is what enforces it.

### III. Tests That Run in a Second

Each core module MUST have at least one unit test. Unit tests MUST use golden fixtures under
`tests/fixtures/` (a recorded `runbook.json` and `checks.json` for the SAP sample) and MUST
NOT reach the network. Anything that calls Gemini MUST be marked `@pytest.mark.integration`
and MUST skip cleanly when `GEMINI_API_KEY` is absent. The default `uv run pytest` MUST
complete without credentials.

Rationale: a test suite that needs credits or Wi-Fi does not get run on hackathon day.

### IV. An Eval, Not a Vibe Check

Observer quality MUST be measured by `eval.py` against the ground-truth step tables in
`samples/README.md`, scoring step count, action match, and timestamp agreement within
3 seconds. Any change touching observe or validate MUST re-run the eval on the SAP sample
before it is considered done, and the latest scores MUST be recorded in `README.md`. Sample
timestamps are offset: the `_demo.mp4` cut starts 10 s after the original clock and the AI
Studio cut 14.6 s after; comparisons MUST subtract the offset.

Rationale: "it looked right on one video" is not evidence. A number that can go down is.

### V. Failures Are Visible

Every Gemini call MUST have a timeout and a bounded retry. A failed step check MUST render as
flagged or errored, never dropped, and error MUST be visually distinct from flagged. Every
Modal function MUST call `logfire.configure()` and `logfire.instrument_pydantic_ai()` at
startup, and every run MUST be wrapped in `logfire.span("runbook", run_id=run_id)` so one
filter shows the Observer followed by the row of Validators. Each run MUST count its Gemini
calls and stop loudly at a fixed cap, because credits are shared with the whole event.
Observability MUST be wired in the first commit that makes a model call, not the last.

Rationale: the demo's strongest moment is a caught mistake. That only works if mistakes
surface instead of vanishing.

### VI. Fixed Scope, Simplest Mechanism

Scope for the build is the Observer, the Validator, and the Renderer. Executors (Playwright,
n8n, computer-use agents), Pydantic AI Gateway, self-hosted models, queues, auth, and
multi-user MUST appear only in prose as roadmap, never in code. Every changed line MUST trace
to the request that motivated it: no speculative abstractions, no configurability for cases
that do not exist, no handling of impossible inputs. When two mechanisms satisfy a
requirement, the simpler one MUST be chosen and work MUST stop there. Unrelated dead code is
mentioned, not deleted, in an unrelated change.

Rationale: gold-plating and scope creep are the two ways a one-day build fails to demo.

## Architectural Invariants

These hold regardless of what is being changed. Before touching ingest, observe, validate, or
render, read the Architecture, Agents, and Modal app layout sections of the brief.

- **Gemini looks and answers; Modal touches files.** Uploads, the Volume at `/data`, ffmpeg
  frame extraction, and fan-out live in Modal functions. Gemini receives a video reference or
  a frame and returns a typed object, nothing else.
- **`ingest` returns `run_id` immediately.** It stores the upload and `spawn`s `observe`;
  the client polls `status/{run_id}`. Nothing awaits the Observer inside a request.
- **Validation fans out with `validate_step.map(steps)`.** Each check depends only on its own
  step and its own frame. Shared mutable state between checks is forbidden.
- **Model tiers are fixed.** Observer runs on a Gemini Pro-class model, Validator on a Gemini
  Flash-class model. Changing either is a deliberate, documented decision because it changes
  cost and latency.
- **Every `Step` carries `timestamp_s`.** The Validator extracts its frame there and the
  Renderer seeks the player there.
- **Secrets never enter the repository.** The Gemini API key and Logfire token live in Modal
  Secrets for deployed runs and in a gitignored `.env` locally. Code reads them from the
  environment only.

## Development Workflow and Quality Gates

- **Features go through spec-kit.** `/speckit-specify` creates `specs/<NNN>-<name>/` and a
  branch of the same name; the flow is specify, clarify, plan, tasks, implement. Non-feature
  work branches off `main` as `<type>/<short-kebab-summary>` using Conventional Commit types.
- **Assumptions first.** Before coding, state assumptions. When a request has more than one
  reasonable reading, present the readings instead of picking one.
- **One task, one commit, immediately.** Implement, verify against the gate, commit with a
  Conventional Commit message, then start the next task. An interrupted session leaves
  finished work committed.
- **The gate.** A change is done only when `uv run ruff format --check .`,
  `uv run ruff check .`, and `uv run pytest` pass, and, for anything touching observe or
  validate, the eval script still scores the SAP sample.
- **Docs move with code.** A change is also done only when every line in `CLAUDE.md`, or in a
  document it points at, that names something the diff renamed, moved, or removed has been
  updated in the same commit. `README.md` is updated in the commit that changes what it
  describes.
- **Commit hygiene.** Messages and PR bodies carry only the change and its rationale. Author
  trailers and "generated with" lines MUST be omitted even when a harness default or template
  suggests them.

## Governance

This constitution supersedes any other practice document in the repository, including
`CLAUDE.md`, where the two conflict. `CLAUDE.md` remains the runtime guidance for day-to-day
work and MUST be kept consistent with this file.

Amendments require a commit that updates this file, bumps the version, sets the
Last Amended date, and describes the change in the commit message. Versioning follows
semantic versioning: MAJOR for removing or redefining a principle or invariant, MINOR for
adding a principle or section or materially expanding guidance, PATCH for clarifications
and wording.

Every plan and implementation produced through spec-kit MUST include a constitution check
against Principles I through VI and the Architectural Invariants. Any violation MUST be
justified in writing in the plan, or the plan MUST change. Complexity beyond the simplest
mechanism MUST be justified the same way.

**Version**: 1.0.0 | **Ratified**: 2026-09-19 | **Last Amended**: 2026-09-19

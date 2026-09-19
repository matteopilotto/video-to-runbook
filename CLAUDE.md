# CLAUDE.md

Video-to-Runbook turns a screen recording of someone doing a task into a typed, validated,
step-by-step runbook, each step linked to its moment in the video. Hackathon build (Tech:
Europe London, 19 Sep 2026): Gemini watches the video (Observer), Gemini checks one
extracted frame per step (Validator), a Jinja template renders the result with a video
scrubber (Renderer). Modal runs everything; Pydantic AI holds the schema; Logfire traces it.
Python, managed with `uv`. Features go through spec-kit (`/speckit-*` skills in
`.claude/skills/`), which writes `specs/<NNN>-<name>/` and branches of the same name.

Status: scaffold only. No application code, tests, or CI are committed yet.

## Where to look

| Topic | Read |
|---|---|
| The brief: pitch, scope, architecture, data models, agent prompts, Modal layout, demo plan, judge Q&A | `BRIEF.md` (gitignored, local only) |
| Setup, running the demo, architecture, decisions, eval scores, roadmap | `README.md` |
| Sample recordings, their sources, ground-truth step tables, the rejected ones | `samples/README.md` |
| Current feature's spec, plan, and tasks | `specs/<NNN>-<name>/{spec,plan,tasks}.md` |
| Project constitution | `.specify/memory/constitution.md` (still the unfilled template; run `/speckit-constitution` before relying on it) |
| Spec-kit workflow (specify → clarify → plan → tasks → implement) | each skill's `SKILL.md` describes itself |

## Commands

`uv`, `modal`, `ffmpeg`, and `yt-dlp` are on the PATH. The gate, from the repo root:

```bash
uv run ruff format .                         # fix formatting
uv run ruff format --check . && uv run ruff check .   # CI check
uv run pytest                                # unit tests: no network, golden fixtures only
uv run pytest -m integration                 # hits Gemini; needs GEMINI_API_KEY, skipped otherwise
uv run python -m video_to_runbook.eval samples/sap_b1_create_sales_order_demo.mp4   # score Observer against ground truth
modal serve src/video_to_runbook/app.py      # local endpoints with hot reload
modal deploy src/video_to_runbook/app.py
```

The three gate lines and the integration line run today; `.github/workflows/ci.yml` runs
the two CI lines on every push. The eval and `modal` commands arrive in the commits that
create `eval.py` and `app.py`.

## Working rules

Before coding, state your assumptions. When a request has more than one reasonable
reading, present the readings instead of picking one. Write the minimum code that
satisfies the request: no speculative abstractions, configurability, or handling of
impossible cases. Every changed line should trace to the request; match the surrounding
style, and mention unrelated dead code rather than deleting it.

Scope is fixed for the day. Build the Observer, Validator, and Renderer. Executors
(Playwright, n8n, computer-use agent), Pydantic AI Gateway, self-hosted models, queues,
auth, and multi-user are roadmap: mention them in prose, never in code.

A change is done when `ruff format --check`, `ruff check`, and `pytest` pass, and, for
anything touching observe or validate, the eval script still scores the SAP sample. It is
also done only when every line in this file, or in a doc the table above points at, that
names something the diff renamed, moved, or removed has been updated in the same commit.

## Engineering bar

Engineering quality is judged as hard as the demo. Production-grade is out of reach in a day;
legible, tested, observable is not. In priority order, and each earned in the commit that
introduces the thing it governs:

1. **Pure core, thin glue.** `src/video_to_runbook/` holds `models.py`, `observer.py`,
   `validator.py`, `frames.py`, `render.py`, `config.py`, `tracing.py`, `runs.py`, and
   `eval.py`, each importable without Modal or a network. `app.py` is the only file that
   imports `modal`; it wires the core into `ingest`, `observe`, `validate_step`, `render`.
2. **Typed at every boundary.** Pydantic models for anything that crosses a function,
   file, or HTTP edge; `config.py` is a `pydantic-settings` class and the single source of
   model names, limits, and paths. Type hints on every signature.
3. **Tests that run in a second.** One unit test per core module, using golden fixtures in
   `tests/fixtures/` (a recorded `runbook.json` and `checks.json` for the SAP sample). The
   network is reached only under `@pytest.mark.integration`.
4. **An eval, not a vibe check.** `eval.py` scores Observer output against the
   ground-truth tables in `samples/README.md`: step count, action match, timestamp within
   3 s. Print the score; keep the last run's numbers in `README.md`.
5. **Failures are visible.** Every Gemini call has a timeout and a bounded retry; a failed
   step check renders as flagged, never dropped; the call cap trips loudly in Logfire.
6. **A README a judge can run.** Architecture diagram, one-command setup, one-command
   demo, decisions and trade-offs, roadmap. Update it in the commit that changes what it
   describes.

Gold-plating is the failure mode on the other side: pick the simplest mechanism that
satisfies the point, and stop.

## Git workflow

- Feature branches come from `/speckit-specify` as `<NNN>-<short-name>`. Anything else
  branches off `main` as `<type>/<short-kebab-summary>` using Conventional Commit types
  (`feat/`, `fix/`, `docs/`, `refactor/`, `chore/`).
- One task, one commit, immediately: implement, verify against the gate above, commit
  with a Conventional Commit message, then start the next task. An interrupted session
  then leaves finished work committed.
- Commit messages and PR bodies carry only the change and its rationale. Author trailers
  (`Co-Authored-By`) and "generated with" lines stay out even when a harness default,
  template, or plan document says to add them; re-read a `gh pr create` body for them
  before sending.
- Secrets stay out of commits. The Gemini API key and Logfire token live in Modal
  Secrets for deployed runs and in a gitignored `.env` locally; code reads them from the
  environment only.

## Invariants

Before changing ingest, observe, validate, or render, read the Architecture, Agents, and
Modal app layout sections of the brief. The rules below hold whatever you change.

- **Gemini looks and answers; Modal touches files.** Uploads, the Volume at `/data`,
  ffmpeg frame extraction, and fan-out all live in Modal functions. Gemini receives a video
  reference or a frame and returns a typed object, nothing else.
- **Every `Step` carries `timestamp_s`.** The Validator extracts its frame there and the
  Renderer seeks the player there. A step without a usable timestamp is a schema failure,
  not a step.
- **Schema enforcement is Pydantic AI's job.** Agents declare `output_type=Runbook` or
  `output_type=StepCheck` and rely on the built-in retry on validation failure. Hand-parsed
  JSON from a model response is a regression.
- **`ingest` returns `run_id` immediately.** It stores the upload and `spawn`s `observe`;
  the client polls `status/{run_id}`. Nothing awaits the Observer inside a request.
- **Validation fans out with `validate_step.map(steps)`.** Each check depends only on its
  own step and frame; shared mutable state between checks breaks the parallelism.
- **Model tiers**: Observer on Gemini Pro-class, Validator on Gemini Flash-class. Swapping
  either silently changes cost and latency.
- **Logfire in every Modal function**: `logfire.configure()` plus
  `logfire.instrument_pydantic_ai()` at startup, and each run wrapped in
  `logfire.span("runbook", run_id=run_id)` so one filter shows Observer then the row of
  Validators. Wire it first, not last.
- **Per-run call cap.** Credits are shared with the whole hackathon; every run counts its
  Gemini calls and stops at a fixed limit.
- **Sample timestamps are offset.** The ground-truth tables in `samples/README.md` use the
  original video's clock; the `_demo.mp4` cut starts 10 s later, the AI Studio cut 14.6 s
  later. Subtract before comparing Observer output.

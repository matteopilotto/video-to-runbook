# Tasks: Observer Pipeline End to End

**Input**: Design documents from `/specs/001-observer-pipeline/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. The constitution (Principle III) requires one unit test per core module
on golden fixtures with no network, and integration tests marked `integration` that skip
without `GEMINI_API_KEY`. Write each test before the module it covers and see it fail.

**Organization**: Grouped by user story. Each task is one commit that passes the gate
(`uv run ruff format --check . && uv run ruff check . && uv run pytest`); tasks that touch
observe or validate also re-run the eval once it exists (T035 onward).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 to US6)
- Include exact file paths in descriptions

## Path Conventions

Single project: `src/video_to_runbook/` for the package, `tests/` at the repository root,
per plan.md.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Make `uv run` import the package, register the gate, and give CI the same gate.

- [X] T001 Add dependencies and tool config to `pyproject.toml`: runtime `jinja2`, `fastapi[standard]`, `pydantic-settings`, `modal` (pins per research R14, keep `pydantic-ai>=2.46.0` and `logfire>=5.1.0`); dev group `pytest`, `ruff`; a `hatchling` build backend with `packages = ["src/video_to_runbook"]` so the src layout imports under `uv run`; `[tool.ruff]` with `line-length = 100` and `target-version = "py313"`; `[tool.pytest.ini_options]` with `testpaths = ["tests"]` and `markers = ["integration: hits Gemini; needs GEMINI_API_KEY"]`. Run `uv sync` and commit `uv.lock`.
- [X] T002 [P] Create `.github/workflows/ci.yml`: ubuntu-latest, `apt-get install -y ffmpeg`, `astral-sh/setup-uv`, `uv sync`, then exactly `uv run ruff format --check . && uv run ruff check .` and `uv run pytest`.
- [X] T003 [P] Create `src/video_to_runbook/__init__.py` (empty), `tests/__init__.py` (empty), and `tests/conftest.py` with a session fixture `fixtures_dir` pointing at `tests/fixtures/sap/` and an autouse hook that skips any test marked `integration` when `GEMINI_API_KEY` is unset.
- [X] T004 [P] Create `README.md` skeleton with the section headings the constitution requires: Architecture (ASCII diagram from BRIEF.md), Setup, Run the demo, Decisions and trade-offs, Eval scores (empty table), Observability, Roadmap. Fill Setup with the `.env` keys (`GEMINI_API_KEY`, `LOGFIRE_TOKEN`) and the two `modal secret create` lines from quickstart.md.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The typed core every story reads: settings, models, frames, tracing, run state.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T005 [P] Write `tests/test_config.py`: defaults load without any environment (`observer_model == "gemini-3.1-pro-preview"`, `validator_model == "gemini-3.8-flash"`, `call_cap == 60`, `observer_request_limit == 4`, `check_request_limit == 3`, `max_upload_mb == 100`, `data_dir == Path("/data")`, `frame_offsets_s == (-1.0, 0.0, 1.0)`); `monkeypatch.setenv("OBSERVER_MODEL", "gemini-2.5-pro")` overrides; `gemini_api_key` is read from `GEMINI_API_KEY`.
- [X] T006 Create `src/video_to_runbook/config.py`: `class Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_file=".env", extra="ignore")` and fields `gemini_api_key: str = ""` (env `GEMINI_API_KEY`), `logfire_token: str | None = None`, `logfire_project_url: str | None = None`, `observer_model: str = "gemini-3.1-pro-preview"`, `validator_model: str = "gemini-3.8-flash"`, `call_cap: int = 60`, `observer_request_limit: int = 4`, `check_request_limit: int = 3`, `observer_timeout_s: int = 180`, `validator_timeout_s: int = 60`, `max_upload_mb: int = 100`, `data_dir: Path = Path("/data")`, `frame_offsets_s: tuple[float, float, float] = (-1.0, 0.0, 1.0)`; plus `get_settings()` cached with `functools.lru_cache` and cleared in the test via `get_settings.cache_clear()`.
- [X] T007 [P] Write `tests/test_models.py` covering every rule in data-model.md: `Step.timestamp_s` accepts `"01:15"` → 75.0, `"1:05"` → 65.0, `"0:01:15"` → 75.0, `75`, `"75.5"`, rejects `-1` and `"abc"`; `action` outside `{click,type,select,navigate,wait,verify}` rejected; `target` of `"ab"` rejected by length; `screen`/`intent` empty rejected; `Runbook` with `steps=[]` rejected; a step whose `target` is `"the button"` or `"IT"` rejected by the `Runbook` validator with a message containing `"step 3 target"` (the step's `order`, not a list index), while `"Add button"` is accepted; orders `[1,3]` rejected with a message naming step 2; timestamps `[5.0, 5.0]` and `[5.0, 4.0]` rejected with a message naming the step; `StepCheck(matches=False, note=None)` rejected, `confidence=1.2` rejected; `CheckRecord` with both or neither of `check`/`error` rejected; `CheckRecord.badge` returns `verified`/`flagged`/`error`; `RunStatus` round-trips through `model_dump_json`.
- [X] T008 Create `src/video_to_runbook/models.py` with `Step`, `Runbook`, `StepCheck`, `CheckRecord`, `RunMeta`, `RunStatus` exactly as in data-model.md: `Step.timestamp_s: Annotated[float, BeforeValidator(parse_timestamp), Field(ge=0)]` where `parse_timestamp` handles `H:MM:SS`, `MM:SS`, `M:SS`, numbers and numeric strings; `target` stripped with `min_length=3`; `Runbook.steps: list[Step] = Field(min_length=1)` with model validators `orders_contiguous`, `timestamps_increasing`, and `targets_concrete` (rejects a lower-cased stripped target in `{"button","the button","field","the field","screen","the screen","it","here","there","element","the element","link","the link"}` with the message `f"step {step.order} target '{step.target}' is too generic; name the on-screen label"`); `StepCheck.confidence: float = Field(ge=0, le=1)` and validator `note_required_when_flagged`; `CheckRecord` with `order`, `check: StepCheck | None`, `error: str | None`, `requests: int = 0`, `input_tokens: int = 0`, `output_tokens: int = 0`, validator "exactly one of check, error", property `badge`; `RunMeta` with `state: Literal["uploaded","watching","checking","done","failed"]` and the fields listed; `RunStatus` with `elapsed_s`, `calls`, `input_tokens`, `output_tokens`, `video_url`, `runbook`, `checks`, and a `badge_for(order)` helper returning `checking` when no record exists.
- [X] T009 [P] Write `tests/test_frames.py` with a module fixture that builds `tmp_path/"clip.mp4"` via `ffmpeg -f lavfi -i testsrc=duration=3:size=64x64:rate=5 -pix_fmt yuv420p`; assert `probe_duration` ≈ 3.0 (±0.1); `extract_frames(clip, 1.5, 3.0)` returns three PNG byte strings (each starts with `\x89PNG`); `extract_frames(clip, 0.0, 3.0)` clamps the first offset to 0 and `extract_frames(clip, 3.0, 3.0)` clamps the last to `duration - 0.05`, still returning three frames.
- [X] T010 Create `src/video_to_runbook/frames.py`: `probe_duration(video: Path) -> float` via `ffprobe -v error -show_entries format=duration -of csv=p=0`; `extract_frames(video: Path, timestamp_s: float, duration_s: float, offsets: Sequence[float] = (-1.0, 0.0, 1.0)) -> list[bytes]` running `ffmpeg -v error -ss {t} -i {video} -frames:v 1 -f image2pipe -c:v png pipe:1` once per offset with `t` clamped to `[0, duration_s - 0.05]`; raise `RuntimeError` with stderr on non-zero exit.
- [X] T011 Create `src/video_to_runbook/tracing.py` with `setup_logfire() -> None` (`logfire.configure(send_to_logfire="if-token-present", service_name="video-to-runbook", console=False)` then `logfire.instrument_pydantic_ai(include_binary_content=False)`; idempotent via a module flag) and `trace_url(run_id: str) -> str | None` returning `None` when `logfire_project_url` is unset, else `f"{url}?q=" + quote("run_id = '<run_id>'")`. Write `tests/test_tracing.py` for `trace_url` with and without the setting. Add `tracing.py`, `runs.py`, and `eval.py` to the core-module list in `CLAUDE.md` ("Pure core, thin glue") in the same commit.
- [ ] T012 [P] Write `tests/test_runs.py` for the run-state helpers: `apply_tamper(runbook, 7)` returns a copy whose step 7 `target` is `"the Log Out menu item"` and `True`, leaves every other step untouched, and `apply_tamper(runbook, 20)` on a 14-step runbook returns the runbook unchanged and `False`; `budget_slots(cap=60, observer_requests=3, per_check=3) == 19`, `budget_slots(60, 4, 3) == 18`, `budget_slots(2, 3, 3) == 0`; `capped_records(steps, slots=2)` returns one `CheckRecord(error="call cap reached before this step")` per step beyond the second; `read_status(run_dir)` on a `tmp_path` laid out per data-model.md (meta, runbook, two check files) returns a `RunStatus` with `state`, `calls == observer_requests + sum(requests)`, `checks` sorted by `order`, `elapsed_s > 0`, and `video_url == f"/runs/{run_id}/video"`; `read_status` on a directory without `meta.json` raises `FileNotFoundError`; `write_meta`/`read_meta` round-trip.
- [ ] T013 Create `src/video_to_runbook/runs.py` (pure, no Modal import): `run_dir(data_dir, run_id) -> Path`; `read_meta(run_dir) -> RunMeta`; `write_meta(run_dir, meta) -> None`; `write_runbook(run_dir, runbook)`; `write_check(run_dir, record)`; `read_status(run_dir) -> RunStatus` assembling the payload in data-model.md (`elapsed_s = (finished_at or now) - created_at`); `apply_tamper(runbook: Runbook, step: int | None) -> tuple[Runbook, bool]` with the constant `TAMPER_TARGET = "the Log Out menu item"`; `budget_slots(cap: int, observer_requests: int, per_check: int) -> int` as `max(0, (cap - observer_requests) // per_check)`; `capped_records(steps: list[Step], slots: int) -> list[CheckRecord]`. `app.py` calls these and holds no run-state logic of its own (Constitution I).

**Checkpoint**: `uv run pytest` green in under 5 s; nothing imports `modal`.

---

## Phase 3: User Story 1 - Turn a recording into a runbook (Priority: P1) 🎯 MVP

**Goal**: Drop the SAP sample on the page and see a rule-checked runbook land whole, every
step with a timestamp inside the video, rows showing grey "checking" badges.

**Independent Test**: quickstart.md §2 (Observer alone) and §4 (page states 1 to 4). The
runbook's steps line up with the ground-truth table within the US5 tolerances.

### Tests for User Story 1

- [ ] T014 [P] [US1] Write `tests/test_observer.py` using `pydantic_ai.models.function.FunctionModel`: (a) the fake model first returns a runbook whose last step has `timestamp_s = 999` on a 118 s video, then a valid one; assert the output is the valid runbook, `result.usage().requests == 2`, and the second request's messages contain a retry prompt mentioning "beyond the video duration"; (b) the fake model first returns orders `[1, 3]`, then valid; assert two requests (schema `ValidationError` retried automatically); (c) a runbook with `"01:15"` timestamps parses to seconds. Use `build_observer(model=fake)` and `ObserverDeps(run_id="t", video_path=tmp, duration_s=118.0)`.
- [ ] T015 [P] [US1] Write `tests/test_render.py` (US1 part): `render_fragment(status)` for a status with `runbook` from `tests/fixtures/sap/runbook.json` and `checks=[]` yields one `<tr>` (or row element) per step with `data-order`, `data-timestamp`, and a `.badge.checking`; a status with `state="watching"` and no runbook yields the "Watching the recording…" message; `state="failed"` yields the error text. Until T017 lands the fixture, the fixture-dependent tests fail on the missing file; do not add a skip.

### Implementation for User Story 1

- [ ] T016 [US1] Create `src/video_to_runbook/observer.py`: `OBSERVER_INSTRUCTIONS` (produce a `Runbook`; every step carries a `MM:SS` timestamp of the moment the action happens; use the exact on-screen label for `target`; collapse scrolling, mis-clicks, window moves, idle time into nothing; take `intent` from narration when present; record failed actions such as a rejected form as pitfalls; steps numbered from 1 in time order); `@dataclass ObserverDeps(run_id: str, video_path: Path, duration_s: float)`; `build_observer(model: Model | str | None = None) -> Agent[ObserverDeps, Runbook]` using `GoogleModel(settings.observer_model, provider=GoogleProvider(api_key=settings.gemini_api_key, retry_options=HttpRetryOptions(attempts=3, initial_delay=1, max_delay=10, http_status_codes=[429, 500, 502, 503, 504])))` by default, `output_type=Runbook`, `deps_type=ObserverDeps`, `retries={"output": 2}`, `name="observer"`, `model_settings=GoogleModelSettings(timeout=settings.observer_timeout_s, google_video_resolution="MEDIA_RESOLUTION_HIGH")`; `@agent.output_validator within_duration(ctx, runbook)` raising `ModelRetry(f"step {s.order} timestamp {s.timestamp_s} s is beyond the video duration {ctx.deps.duration_s} s")`; `class ObserveResult(BaseModel)` with `runbook`, `requests`, `input_tokens`, `output_tokens`; `observe(deps, model=None) -> ObserveResult` sending `[OBSERVER_USER_PROMPT, BinaryContent(video_bytes, media_type="video/mp4")]` under `UsageLimits(request_limit=settings.observer_request_limit)`. Calling `setup_logfire()` is the caller's job, not this module's.
- [ ] T017 [US1] Write `tests/integration/test_gemini.py::test_observer_sap` (`@pytest.mark.integration`): run `observe` on `samples/sap_b1_create_sales_order_demo.mp4` with `probe_duration`; assert 5 ≤ steps ≤ 25, every `timestamp_s ≤ duration`, orders contiguous; when `RECORD_FIXTURES=1`, write `tests/fixtures/sap/runbook.json` via `model_dump_json(indent=2)`. Run it once with the key and commit the fixture, which makes the T015 tests pass. If no key is available yet, hand-write the fixture from the 14-row table in `samples/README.md` with timestamps minus 10 s and commit that instead, saying so in the commit message; T035 replaces it with a recorded one.
- [ ] T018 [US1] Create `src/video_to_runbook/render.py` and `src/video_to_runbook/templates/runbook.html.j2`: `render_fragment(status: RunStatus) -> str` via `jinja2.Environment(loader=PackageLoader("video_to_runbook", "templates"), autoescape=select_autoescape(["html"]))`; the template renders the state message when `runbook is None`, otherwise title, system, prerequisites, a table of steps (`order`, `mm:ss` from `timestamp_s`, `action`, `target`, `value`, `screen`, `intent`) with `data-order` and `data-timestamp` on each row and `<span class="badge {{ status.badge_for(step.order) }}">`, then pitfalls. No `<script>` in the fragment.
- [ ] T019 [US1] Create `src/video_to_runbook/static/index.html` per contracts/page.md states 1 to 4: two-column layout, drop zone with file picker, client-side refusal of non-`video/*` or > 100 MB files with the reason shown in the drop zone, `POST /runs` as multipart, then `<video src="/runs/{id}/video">` shown paused, "Watching the recording…" on the right, `setInterval` polling `GET /status/{id}` every 2 s and `GET /runs/{id}/runbook.html` swapped into the right column, "Run not found" and stop on 404, elapsed ticking in the footer. Inline CSS, inline JS, no external assets.
- [ ] T020 [US1] Create `src/video_to_runbook/app.py` with the web function per research R7 and R8: `modal.App("video-to-runbook")`; image `modal.Image.debian_slim(python_version="3.13").apt_install("ffmpeg").uv_pip_install(<the pyproject runtime pins>).add_local_dir("src/video_to_runbook", "/root/video_to_runbook")`; `volume = modal.Volume.from_name("video-to-runbook-data", create_if_missing=True)`; secrets `modal.Secret.from_name("gemini", required_keys=["GEMINI_API_KEY"])` and `modal.Secret.from_name("logfire")`; `if not modal.is_local(): setup_logfire()`; `@app.function(...) @modal.asgi_app() def web()` returning a FastAPI app with `GET /` (the static file via `importlib.resources`), `POST /runs` (`415` unless `file.content_type.startswith("video/")`, `413` above `max_upload_mb`, `422` unless `tamper_step` is absent or a positive int; `run_id = secrets.token_hex(6)`; write `video.mp4` under `runs.run_dir(...)`, `probe_duration`, `runs.write_meta(...)` with `state="uploaded"`, `volume.commit()`, `observe.spawn(run_id)`, return `202 {"run_id": ...}`), `GET /status/{run_id}` (`volume.reload()`, `runs.read_status(...)`, `404` on `FileNotFoundError`), `GET /runs/{run_id}/video` (copy to `/tmp/{run_id}.mp4` once, `FileResponse(..., media_type="video/mp4")`), `GET /runs/{run_id}/runbook.html` (`render_fragment(runs.read_status(...))`). Define `observe` as a stub that only marks the run `failed` with "observe not implemented" so `POST /runs` can spawn it; T021 fills it in. Update `CLAUDE.md` commands to `uv run modal serve src/video_to_runbook/app.py` and `uv run modal deploy ...`, and change its "wires the core into `ingest`, `observe`, `validate_step`, `render`" line to name `web` (with the `ingest`, `status`, `video`, `fragment` routes), `observe`, `validate_step`.
- [ ] T021 [US1] Fill in `observe` in `src/video_to_runbook/app.py`: `@app.function(timeout=900, ...) def observe(run_id: str)`: `volume.reload()`, `meta = runs.read_meta(...)`, set `state="watching"` and commit, `with logfire.span("runbook", run_id=run_id, video=meta.filename):` run `observer.observe(ObserverDeps(...))`, `runs.write_runbook(...)`, update meta with `observer_requests`, token counts, and `trace_url(run_id)`, set `state="done"` for now (validation fan-out arrives in T025), `volume.commit()`; on `UnexpectedModelBehavior` set `state="failed"` with the message; on `UsageLimitExceeded` set `state="failed"` with "call cap reached in observer" and `logfire.error("call cap reached", run_id=run_id, phase="observer")`; `finished_at` on both terminal states.
- [ ] T022 [US1] Walk quickstart.md §4 with `uv run modal serve src/video_to_runbook/app.py`: drop the SAP sample, confirm states 1 to 4, note the footer's elapsed time against SC-002 and SC-003, run the curl checks (`202`, `415`, `404`), fix what breaks, and fill README "Setup" and "Run the demo" with the exact commands.

**Checkpoint**: A judge can drop a video and read a runbook. MVP.

---

## Phase 4: User Story 2 - See each step verified against the video (Priority: P2)

**Goal**: Every step is checked against three frames in parallel; badges flip to verified,
flagged, or error one by one; a flagged row expands to its note; the demo tamper guarantees
one flagged row; the 60-call cap is budgeted and loud.

**Independent Test**: quickstart.md §5 (tamper) and the badge states in §4. Load
`tests/fixtures/sap/runbook.json`, run checks, every badge reaches a terminal state.

### Tests for User Story 2

- [ ] T023 [P] [US2] Write `tests/test_validator.py` with `FunctionModel`: (a) the fake returns `StepCheck(matches=False, note=None)` first, then `matches=False, note="frame shows the Logistics tab"`; assert the result's `check.note` is set and `requests == 2`; (b) the request carries three `BinaryContent` image parts; (c) a fake that raises a timeout-like exception yields `error` set, `check is None`, and `requests` counted; (d) `UsageLimitExceeded` from a `request_limit=1` fake with a retry yields `error` containing "call cap".
- [ ] T024 [P] [US2] Extend `tests/test_render.py`: with `checks` from `tests/fixtures/sap/checks.json` plus one hand-made `CheckRecord(error="timed out")`, the fragment shows `.badge.verified`, `.badge.flagged` inside a `<details>` whose body contains the note, and `.badge.error` whose text is "error" (not "flagged"); steps without a record stay `.badge.checking`.

### Implementation for User Story 2

- [ ] T025 [US2] Create `src/video_to_runbook/validator.py`: `VALIDATOR_INSTRUCTIONS` (you see three frames taken one second before, at, and one second after the moment a step claims to happen; say whether they show the step's target being acted on; the middle frame may already show the state after the action; return `matches`, `confidence`, and a `note` naming what the frames show instead when they do not match); `build_validator(model=None) -> Agent[None, StepCheck]` on `GoogleModel(settings.validator_model, ...)` with the same provider retry options, `output_type=StepCheck`, `retries={"output": 1}`, `name="validator"`, `model_settings={"timeout": settings.validator_timeout_s}`; `check_step(step: Step, frames: list[bytes], model=None) -> CheckRecord` sending `[text describing the step, BinaryContent(png, media_type="image/png") × 3, "Does the video show this step?"]` under `UsageLimits(request_limit=settings.check_request_limit)`, forcing `order = step.order`, and converting `UsageLimitExceeded` ("call cap reached in step check"), `UnexpectedModelBehavior`, and any other exception into `CheckRecord(error=str(exc))` with whatever `requests` were consumed.
- [ ] T026 [US2] In `src/video_to_runbook/app.py` add `@app.function(timeout=180, ...) def validate_step(run_id: str, order: int) -> None`: `volume.reload()`, read the runbook and meta through `runs`, `extract_frames(video, step.timestamp_s, meta.duration_s, settings.frame_offsets_s)`, `check_step`, `runs.write_check(...)`, `volume.commit()`. In `observe`, after the Observer returns: `runbook, applied = runs.apply_tamper(runbook, meta.tamper_step)`, write the post-tamper runbook and `tamper_applied`, set `state="checking"`, `slots = runs.budget_slots(settings.call_cap, observer_requests, settings.check_request_limit)`, write `runs.capped_records(steps, slots)` and, if any, `logfire.error("call cap reached", run_id=run_id, capped=len(steps) - slots)`, then `list(validate_step.map([run_id] * n, orders, return_exceptions=True))` for the first `n = min(slots, len(steps))` steps (the map input is `(run_id, order)` because each validator reloads the runbook from the Volume), converting any returned exception into a `CheckRecord(error=...)` for that order; finish with `state="failed"` and `error=f"call cap reached: {len(steps) - slots} of {len(steps)} steps not checked"` when any step was capped, otherwise `state="done"`; `finished_at`, `volume.commit()`.
- [ ] T027 [US2] Update `src/video_to_runbook/templates/runbook.html.j2`: badge classes `checking`, `verified`, `flagged`, `error` with visible text equal to the class; a flagged row is rendered as `<details>` whose `<summary>` is the row (keeping `data-order`/`data-timestamp`) and whose body is the note; an error row shows the error text in a `title` attribute and an amber badge with a warning glyph.
- [ ] T028 [US2] Update `src/video_to_runbook/static/index.html`: read `?tamper=<n>` from `location.search` and send it as `tamper_step` with the upload; footer shows `calls`, `input_tokens + output_tokens`, and at `done` or `failed` the tamper notice ("Demo tamper: step N" or "Demo tamper requested for step N, runbook has M steps") and the trace link when `trace_url` is set; `state === "failed"` shows a red banner with `error` above whatever rows exist; stop polling at `done` or `failed` and freeze the elapsed counter to `elapsed_s`.
- [ ] T029 [US2] Write `tests/integration/test_gemini.py::test_validator_sap` (`integration`): for every step in `tests/fixtures/sap/runbook.json`, extract frames from the sample and run `check_step` concurrently with `asyncio.gather`; assert every record has `check` or `error`; when `RECORD_FIXTURES=1`, write `tests/fixtures/sap/checks.json`. Run once with the key and commit the fixture (hand-write a plausible one from the runbook fixture if the key is unavailable, say so in the commit, and let T035 replace it).
- [ ] T030 [US2] Rehearse quickstart.md §5 on `uv run modal serve`: `?tamper=7` flags step 7 with a note; `?tamper=20` leaves the runbook untouched and the footer says so; force the cap with `CALL_CAP=2` in `.env`/the Modal Secret and confirm the failed state, the cap reason in the banner, and the error event. Record each tamper run's outcome (flagged, verified, error) in a "Tamper runs" line of `README.md` so SC-005 is measured across the day, and add "Demo tamper" and "Retention" (files kept until cleared by hand, deletion is roadmap) sections.

**Checkpoint**: The caught mistake works on stage.

---

## Phase 5: User Story 3 - Jump the video to a step (Priority: P3)

**Goal**: Clicking any step row seeks the player to that moment and pauses.

**Independent Test**: quickstart.md §4: click a row, the player sits paused within half a
second of the step's timestamp (SC-006).

- [ ] T031 [US3] In `src/video_to_runbook/static/index.html` add one delegated `click` listener on the right column: find the closest `[data-timestamp]`, set `video.currentTime = Number(dataset.timestamp)` and `video.pause()`; a click on a `<details>` summary both seeks and toggles the note (do not `preventDefault`). The row attributes are already asserted in `tests/test_render.py` (T015); confirm by hand in `uv run modal serve`.

---

## Phase 6: User Story 4 - Export the runbook as Markdown (Priority: P4)

**Goal**: A button downloads the runbook as a Markdown file with statuses and notes.

**Independent Test**: quickstart.md §4 curl of `/runs/{id}/runbook.md` and the download.

### Tests for User Story 4

- [ ] T032 [P] [US4] Extend `tests/test_render.py`: `render_markdown(status)` from the fixtures contains `# <title>`, the system line, every prerequisite as a list item, a table (or numbered list) with every step's `mm:ss`, action, target, value, screen, intent, badge text, and note, and the pitfalls; a step without a record shows "checking"; a status without a runbook raises `ValueError("no runbook yet")`.

### Implementation for User Story 4

- [ ] T033 [US4] Add `src/video_to_runbook/templates/runbook.md.j2` and `render_markdown(status: RunStatus) -> str` in `src/video_to_runbook/render.py` (no autoescape for the Markdown environment; raise `ValueError("no runbook yet")` when `runbook is None`).
- [ ] T034 [US4] Add `GET /runs/{run_id}/runbook.md` to `src/video_to_runbook/app.py` returning `text/markdown` with `Content-Disposition: attachment; filename="<slugified title>.md"` (`409 {"detail": "no runbook yet"}` before the runbook exists), and an "Export Markdown" `<a download>` in `src/video_to_runbook/static/index.html` enabled once `status.runbook` is present.

---

## Phase 7: User Story 5 - Measure observer accuracy against ground truth (Priority: P5)

**Goal**: One command scores both samples against the tables in `samples/README.md` and
the numbers live in the README.

**Independent Test**: quickstart.md §3, including the `--from tests/fixtures/sap` offline run.

### Tests for User Story 5

- [ ] T035 [P] [US5] Write `tests/test_eval.py`: `load_truth(Path("samples/README.md"))` returns two `TruthCase`s named after their video files with 14 and 7 steps, `offset_s` 10.0 and 14.6, and step 1 of the SAP case at `timestamp_s == 11.0` with `action == "navigate"`; `pair(produced, truth)` follows FR-027a on hand-built lists: nearest within 3 s wins, a produced step is paired at most once, a truth step with nothing within 3 s stays unpaired, ties go to the earlier produced step; `score(runbook, checks, truth)` on `tests/fixtures/sap/` returns an `EvalScore` whose `timestamp_agreement` and `action_match` are in `[0, 1]`, `check_agreement` counts `error` records as not verified, and `step_count_diff == len(runbook.steps) - 14`.
- [ ] T036 [US5] Create `src/video_to_runbook/eval.py`: `TruthStep`, `TruthCase`, `EvalScore` models (data-model.md); `load_truth(readme: Path) -> list[TruthCase]` parsing the two `| # | t (orig) | action | target |` tables with a regex and the offsets `{"sap_b1_create_sales_order_demo.mp4": 10.0, "google_ai_studio_api_key_screen_only.mp4": 14.6}`; `pair(...)`, `score(...)`; Pydantic Evals evaluators `StepCountDiff`, `TimestampAgreement`, `ActionMatch`, `CheckAgreement` as `@dataclass class ...(Evaluator)` returning floats from `EvaluatorContext.output` (a `RunOutput(runbook, checks)` model) and `expected_output` (`TruthCase`); `Dataset(cases=[Case(name=..., inputs=case, expected_output=case) ...], evaluators=[...])`; the task `run_case(case: TruthCase) -> RunOutput` calling `observer.observe` then `validator.check_step` for every step with `asyncio.gather` over frames from `frames.extract_frames`; `main(argv)` with an optional video path to restrict to one case and `--from DIR` to score saved `runbook.json`/`checks.json` without network; calls `setup_logfire()` first; prints `report.print()`.
- [ ] T037 [US5] Run `uv run python -m video_to_runbook.eval samples/sap_b1_create_sales_order_demo.mp4` (and the AI Studio clip if credits allow), paste the table into `README.md` "Eval scores" with the date, and confirm SC-001 (`|Δ| ≤ 4`, `ts≤3s ≥ 0.70`, `action ≥ 0.70`); if below, adjust `OBSERVER_INSTRUCTIONS` in `src/video_to_runbook/observer.py` once and re-run. If either golden fixture was hand-written in T017 or T029, regenerate both here with `RECORD_FIXTURES=1 uv run pytest -m integration` and commit the recorded versions, as Constitution III requires.

---

## Phase 8: User Story 6 - Trace a run end to end (Priority: P6)

**Goal**: One filter by run reference shows the Observer, its retries, and the row of
parallel validator spans; the cap trips loudly; the page links to the trace.

**Independent Test**: quickstart.md §6.

- [ ] T038 [US6] In `src/video_to_runbook/app.py` propagate trace context: `observe` captures `ctx = dict(logfire.propagate.get_context())` inside the `runbook` span and passes it to `validate_step` as a third argument; `validate_step` wraps its body in `with logfire.propagate.attach_context(ctx), logfire.span("validate_step", run_id=run_id, order=order):`. Add `LOGFIRE_PROJECT_URL` to the `logfire` Modal Secret and the `.env` notes in `README.md` so the footer link from T021 resolves.
- [ ] T039 [US6] Verify quickstart.md §6 in Logfire: filter by `run_id`, see one `runbook` span with the Observer agent run (retry prompt visible when it happened), N `validate_step` children with token counts, and the `call cap reached` error event from the forced-cap run. Write the "Observability" section of `README.md` (what to filter, what a healthy run looks like, what the cap looks like).

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: The README a judge can run, the demo warm-up, and doc consistency.

- [ ] T040 [P] Finish `README.md`: architecture diagram with the three Modal functions and the core modules, "Decisions and trade-offs" (inline video vs Files API, static vs agentic mode, Pro preview vs 2.5 Pro, budgeted cap vs shared counter, Volume commit/reload, local video copy), and "Roadmap" (executors: Playwright, n8n, computer-use; Pydantic AI Gateway; Files API for large uploads; agentic Flash Observer experiment; Observer frame tool and `Capability`; retention policy; auth and multi-user).
- [ ] T041 [P] Consistency pass over `CLAUDE.md` and `samples/README.md`: every command in the Commands table exists and runs; the "Status: scaffold only" line is replaced with the current state; the core-module list and the Modal function names match the code; the eval offsets sentence still matches `eval.py`.
- [ ] T042 Deploy with `uv run modal deploy src/video_to_runbook/app.py`, then set `min_containers=1` on `observe` in `src/video_to_runbook/app.py` as a separate `chore: keep observe warm for the demo` commit about an hour before the slot, and rehearse quickstart.md §4 to §6 on `samples/google_ai_studio_api_key_screen_only.mp4`, the clip the Observer was not tuned on.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies; T002 to T004 in parallel after T001.
- **Foundational (Phase 2)**: depends on Phase 1; blocks every story. T005/T007/T009 (tests) in parallel; T006, T008, T010, T011 each after its test; T012 after T008, T013 after T012.
- **US1 (Phase 3)**: depends on Phase 2. Sequence: T014 and T015 in parallel → T016 → T017 → T018 → T019 → T020 → T021 → T022.
- **US2 (Phase 4)**: depends on US1 (needs `observe`, the fragment, and the page). T023 and T024 in parallel → T025 → T026 → T027 → T028 → T029 → T030.
- **US3 (Phase 5)**: depends on US1 only. T031 can run any time after T019.
- **US4 (Phase 6)**: depends on US1 only; richer with US2's statuses. T032 → T033 → T034.
- **US5 (Phase 7)**: depends on Phase 2 plus `observer.py` (T016) and `validator.py` (T025) and both fixtures (T017, T029). T035 → T036 → T037.
- **US6 (Phase 8)**: depends on US2's `validate_step` (T026). T038 → T039.
- **Polish (Phase 9)**: after every story wanted for the demo. T040 and T041 in parallel; T042 last.

### Recommended single-developer order for the day

T001 → T002/T003/T004 → T005/T007/T009 → T006 → T008 → T010 → T011 → T012 → T013 →
T014/T015 → T016 → T017 → T018 → T019 → T020 → T021 → T022 (MVP, target 16:00) →
T023/T024 → T025 → T026 → T027 → T028 → T029 → T030 (target 17:30) → T031 → T032 → T033 →
T034 → T035 → T036 → T037 → T038 → T039 (target 18:30) → T040/T041 → T042 (rehearse by 19:00).

### Parallel Opportunities

- Phase 1: T002, T003, T004 together after T001.
- Phase 2: the three test files T005, T007, T009 together; then T006, T008, T010 together (different modules); T012 once T008 exists.
- US1: T014 and T015 together; T018 and T019 touch different files and can be written together once T017 has a fixture.
- US2: T023 and T024 together; T027 and T028 together (template vs page).
- US3 (T031) and US4 (T032 to T034) can proceed while US2's integration run (T029) waits on the network.
- Polish: T040 and T041 together.

---

## Parallel Example: User Story 1

```bash
# Tests first, in parallel (different files):
Task: "Write tests/test_observer.py with FunctionModel retry cases"
Task: "Write tests/test_render.py fragment cases"

# Then the two independent files once the fixture exists:
Task: "Create src/video_to_runbook/render.py and templates/runbook.html.j2"
Task: "Create src/video_to_runbook/static/index.html states 1 to 4"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 and Phase 2: the typed core is green in under 5 s.
2. Phase 3: Observer, fragment, page, and `app.py` with `web` and `observe` only.
3. Stop and validate with quickstart.md §2 and §4: a runbook lands on the page.
4. That alone is demo-able if the day goes badly.

### Incremental Delivery

1. US2 adds the checks, badges, tamper, and cap: the strongest demo moment.
2. US3 and US4 are each one short task on top of US1.
3. US5 turns the Observer into a number and fills the README table.
4. US6 makes the Logfire minute of the demo work.
5. Polish makes the README runnable by a judge and warms the container.

### Explicitly not in this task list

The Observer frame tool with typed deps, its packaging as a Pydantic AI `Capability`, the
Files API path for uploads above 20 MB, the agentic Flash experiment, executors, gateway,
auth, multi-user, and retention automation. All are roadmap prose in T040.

---

## Notes

- One task, one commit, Conventional Commit message, gate green before each commit
  (`CLAUDE.md`). T017, T029, T037 also need the network and the key; if the key is late,
  do the hand-written fixture fallback and keep moving.
- Never mention the model tier change (Flash Observer) in code; it is a written decision
  first.
- `app.py` is the only file that imports `modal`, and it holds no run-state logic: that
  lives in `runs.py` where it is unit-tested.

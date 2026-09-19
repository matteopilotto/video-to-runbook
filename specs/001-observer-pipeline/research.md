# Research: Observer Pipeline End to End

Phase 0 output. Facts were verified on 2026-09-19 against the installed packages in `.venv`
(pydantic-ai 2.46.0, pydantic-evals 2.46.0, logfire 5.1.0, google-genai 2.24.0,
pydantic-settings 2.15.0), the installed Modal client (1.5.5, uv tool), and ai.google.dev
pages dated September 2026. Where the docs contradict each other it is said so.

## R1. Gemini models

**Decision**: Observer on `gemini-3.1-pro-preview`; Validator on `gemini-3.8-flash`. Both
are defaults in `config.py`, overridable by environment (`OBSERVER_MODEL`,
`VALIDATOR_MODEL`). Fallback Pro if the preview misbehaves on the day: `gemini-2.5-pro`.

**Rationale**: `gemini-3.1-pro-preview` is the only Pro-class model on the models page
(released 2026-02-19, preview, video input, structured output, 1M context). No Pro model is
GA. `gemini-3.8-flash` went GA on 2026-09-02, takes video and images, and is the cheapest
current Flash ($0.75/M input through end of 2026). Both are in Pydantic AI's known-model
list, so the `google:` prefix resolves without a custom provider. Pro models are not on the
Gemini free tier: the key used on stage must be on a billed project or hackathon credits.

**Alternatives considered**: `gemini-2.5-pro` (still active, GA-era, cheaper, weaker video
reasoning) kept as the one-line fallback. Agentic video mode (see R3) is Flash-only, so it
cannot serve the Observer's Pro tier.

## R2. Video input path and the upload cap

**Decision**: Send the recording inline as `BinaryContent(data, media_type="video/mp4")`.
Keep the spec's 100 MB upload cap. No Files API code in this feature.

**Rationale**: Pydantic AI maps `BinaryContent` to Gemini `inline_data` and enforces no
client-side size limit. Google's own pages disagree on the inline ceiling: the video page's
table says inline is for files under 100 MB, its prose says "under 20 MB total request
size", and the Files page says to use the Files API above 100 MB. Both sample clips are
4.5 MB and 5.0 MB, far under the conservative 20 MB even after base64 inflation. A 20 to
100 MB upload that Gemini rejects for request size will surface as a failed run with the
provider's message (Constitution V: failures visible), and the Files API (upload, poll for
`ACTIVE`, wrap as `UploadedFile`) is the documented follow-up if that ever happens.

**Alternatives considered**: Files API for every upload (adds a poll loop and a 48 h file
lifetime to manage; the handoff rejected it for the demo). Lowering the cap to 20 MB
(contradicts the spec's clarified FR-001 without evidence it is needed).

## R3. Sampling, media resolution, timestamps

**Decision**: Static processing at the default 1 fps. Observer request uses
`GoogleModelSettings(google_video_resolution="MEDIA_RESOLUTION_HIGH")`. Validator frames
are PNGs sent at the default image resolution. The Observer prompt asks for timestamps as
`MM:SS`; `Step.timestamp_s` converts them (see R6). Agentic video mode is not used.

**Rationale**: Static mode inserts a timestamp marker every second, which is the native
granularity for the 3 s eval tolerance, and is the mode the docs recommend for clips under
5 minutes where frame-level precision matters. High media resolution costs about 300 tokens
per second of video versus 100 at low, so a 118 s clip is roughly 37k tokens (about 7 cents
on the Pro preview), and it keeps 720p UI labels legible, which the handoff made a
requirement. Agentic mode (launched 2026-09-01 on 3.5 Flash-Lite, 3.6, 3.7 and 3.8 Flash) is
opt-in, disables custom fps and clipping, does not run on Pro models, and is aimed at long
videos. The Google AI Studio developer guide the user supplied
(`aistudio.google.com/learn/agentic-video-understanding-with-gemini`, Loeber and
Grootendorst) says the same in its own words: agentic mode "replaces static decoding with an
active, server-side tool loop" that reads transcripts first and loads "only the relevant time
window (e.g., seconds 14 to 16)" at adaptive frame rates; it is enabled with
`processing: "agentic"` on the video item of an Interactions API request (generateContent
equivalent: `media_processing="AGENTIC"` on the `Part`); it is supported on "Gemini 3.8
Flash, 3.7 Flash, 3.6 Flash, and 3.5 Flash-Lite"; and its own guidance is to use
`processing="static"` for "short video clips (< 5 minutes)" such as "UI animations ... where
frame-level precision across the entire clip is needed". Both sample clips are under two
minutes and are UI recordings, so static is the documented choice, and the Observer's Pro
tier is not on the agentic model list anyway. Pydantic AI 2.46 forwards `vendor_metadata`
only as `video_metadata` and `media_resolution`, so agentic mode would also need the raw
`google-genai` client.

**Alternatives considered**: Low resolution (cheaper, but small SAP field labels risk
misreads). Agentic mode on a Flash Observer: the guide lists "pinpointing exact timestamps"
as an agentic strength, so if the eval shows timestamp drift above 3 s on static Pro, an
experiment with `gemini-3.8-flash` in agentic mode is the first thing to try; that would
change the Observer tier, an invariant, and so needs a written, deliberate decision. Recorded
as roadmap, not built.

## R4. Pydantic AI agent shape

**Decision**:

- `Agent(GoogleModel(observer_model, provider=GoogleProvider(api_key=settings.gemini_api_key)), output_type=Runbook, deps_type=ObserverDeps, instructions=OBSERVER_INSTRUCTIONS, retries={"output": 2}, name="observer")`.
- `@observer.output_validator` receives `RunContext[ObserverDeps]` and raises `ModelRetry("step N timestamp X s is beyond the video duration Y s")` for the duration rule. Contiguity, monotonic timestamps, and non-generic targets are Pydantic validators on the models; Pydantic AI converts their `ValidationError` into a retry prompt automatically.
- Validator agent: `output_type=StepCheck`, `retries={"output": 1}`, `name="validator"`, prompt is a list of `[text, BinaryContent(png, "image/png") x3, text]`.
- Timeouts through `model_settings={"timeout": 180}` (Observer) and `{"timeout": 60}` (Validator); HTTP-level bounded retry through `GoogleProvider(retry_options=HttpRetryOptions(attempts=3, initial_delay=1, max_delay=10, http_status_codes=[429, 500, 502, 503, 504]))`.
- Tokens from `result.usage()` (`requests`, `input_tokens`, `output_tokens`).

**Rationale**: verified against the installed 2.46 source: there is no `output_retries`
parameter (use the `retries` dict), the provider prefix is `google:` (not `google-gla:`),
`GoogleProvider` reads `GOOGLE_API_KEY` first and `GEMINI_API_KEY` second, so `config.py`
passes the key explicitly to keep `GEMINI_API_KEY` the documented name. `ModelRetry` and
model-level `ValidationError` both produce a `RetryPromptPart` that the trace shows as a
second model request, which satisfies "the retry is visible in Logfire".

**Alternatives considered**: `pydantic_ai.retries` tenacity transports (need `tenacity`,
more surface); hand-rolled retry loop (a regression per Constitution II).

## R5. The 60-call cap without shared state

**Decision**: Budget by construction, per run:

1. The Observer run gets `UsageLimits(request_limit=settings.observer_request_limit)` (4).
2. After the runbook is written, `slots = (settings.call_cap - observer_requests) // settings.check_request_limit` where `check_request_limit` is 3. Steps `[:slots]` are dispatched with `validate_step.map(...)`, each run under `UsageLimits(request_limit=3)`. Steps beyond the slots get a `CheckRecord(error="call cap reached before this step")` without a call.
3. `UsageLimitExceeded` in either phase is caught, logged with `logfire.error("call cap reached", run_id=...)`, and turns into `failed` (Observer) or an `error` record (Validator).

**Rationale**: Validators run in separate containers, so a live shared counter would need a
`modal.Dict` and would couple checks (the constitution forbids shared mutable state between
them). Fixed per-phase limits make the total provably ≤ 60 with zero coordination, and every
trip is loud. With 4 + 3 × 18 = 58, an 18-step runbook fits; step 19 onward is reported as
capped rather than silently dropped.

**Alternatives considered**: `modal.Dict` counter (shared state, extra primitive);
`RunUsage` shared object (in-process only).

## R6. Timestamp parsing

**Decision**: `Step.timestamp_s` is `float` with a `BeforeValidator` that accepts `int`,
`float`, numeric strings, and `H:MM:SS` / `MM:SS` / `M:SS` strings, converting to seconds.
Negative values are rejected by `Field(ge=0)`. The duration ceiling is the Observer output
validator (needs `deps.duration_s`).

**Rationale**: Google documents `MM:SS` as the model's timestamp form; the Observer prompt
asks for it and the schema absorbs it, so the stored value is always seconds (invariant:
every `Step` carries `timestamp_s`).

## R7. Modal layout

**Decision**: One `modal.App("video-to-runbook")`, image
`modal.Image.debian_slim(python_version="3.13").apt_install("ffmpeg").uv_pip_install(<pins>).add_local_dir("src/video_to_runbook", "/root/video_to_runbook")`,
one Volume `video-to-runbook-data` at `/data`, two Secrets `gemini` (`GEMINI_API_KEY`) and
`logfire` (`LOGFIRE_TOKEN`). Functions:

| Function | Decorators | Role |
| --- | --- | --- |
| `web` | `@app.function(...)` + `@modal.asgi_app()` | FastAPI app with the six routes in [contracts/http-api.md](contracts/http-api.md). `POST /runs` stores the file, probes duration, commits the Volume, `observe.spawn(run_id)`, returns. |
| `observe` | `@app.function(timeout=900)` | Reloads the Volume, runs the Observer under `logfire.span("runbook", run_id=..., video=...)`, applies the tamper, writes `runbook.json`, fans out `validate_step.map(...)` with the trace context, writes final `meta.json`. |
| `validate_step` | `@app.function(timeout=180)` | Attaches the trace context, extracts three frames, runs the Validator, writes `checks/{order}.json`, commits. |

`render` is a core module used by `web`, not a Modal function; the README and `CLAUDE.md`
line that lists `render` among the wired functions gets updated in the commit that creates
`app.py`.

**Rationale** (verified in Modal 1.5.5 source): `@modal.web_endpoint` is a hard deprecation
error; `@modal.asgi_app` mounts a full FastAPI app, which the page shell, upload, and video
routes need. `fastapi[standard]` brings `python-multipart` for `UploadFile`. `.map` from
inside another function works. `add_local_python_source` ignores non-Python files by default,
so `add_local_dir` is used to ship the Jinja templates and `index.html`. `.uv_sync()` is
avoided because it installs into a separate environment whose interplay with the Modal
client is not documented; an explicit pin list mirrors `pyproject.toml`. `modal serve`
imports `app.py` in the local interpreter, so `modal` must be a project dependency and the
documented commands become `uv run modal serve ...` / `uv run modal deploy ...` (a
`CLAUDE.md` edit in the same commit).

**Alternatives considered**: `@app.cls` with `@modal.enter` for Logfire setup (more
structure than three functions need; module-level `logfire.configure()` guarded by
`if not modal.is_local()` does the same once per container).

## R8. Volume consistency and the video route

**Decision**: Writers call `volume.commit()` after writing; readers call `volume.reload()`
before reading. The `GET /runs/{id}/video` route copies the file once to
`/tmp/{run_id}.mp4` inside the web container and serves that with Starlette's
`FileResponse`, which supports `Range` (verified in starlette 1.6.0), so the player can seek.

**Rationale**: Modal Volumes are not a network filesystem; without `commit`/`reload` a
second container does not see new files. `reload()` fails while the container holds open
files on the Volume, and a streaming video response would hold one open during every status
poll. Serving from a local copy removes that conflict with three lines.

**Alternatives considered**: `modal.Dict` for status (second primitive, and the files must
exist anyway); reading the whole video into memory per request (loses `Range`).

## R9. Trace shape

**Decision**: `app.py` calls `logfire.configure(send_to_logfire="if-token-present",
service_name="video-to-runbook", console=False)` and
`logfire.instrument_pydantic_ai(include_binary_content=False)` at import inside containers.
`observe` opens `logfire.span("runbook", run_id=run_id, video=filename)` and passes
`logfire.propagate.get_context()` to every `validate_step`, which wraps its work in
`logfire.propagate.attach_context(ctx)` and its own `logfire.span("validate_step",
run_id=..., order=...)`. `trace_url` is built from `settings.logfire_project_url` plus a
query on the `run_id` attribute.

**Rationale**: verified API (`logfire.propagate.get_context() -> ContextCarrier`,
`attach_context(carrier)`), which makes the parallel validator spans children of the run
span across containers, so one filter shows the Observer then the row of Validators.
`include_binary_content=False` keeps the mp4 and PNGs out of the trace payload.

## R10. Frames

**Decision**: `frames.py` shells out to `ffmpeg -ss {t} -i {video} -frames:v 1 -f image2pipe
-c:v png pipe:1` once per offset in `(-1, 0, +1)`, clamping `t` to `[0, duration - 0.05]`,
and `ffprobe -show_entries format=duration` for the duration at ingest.

**Rationale**: Three separate seeks are about 100 ms each and keep the function pure
(bytes in, bytes out). PNG avoids compression artefacts on UI text.

## R11. Renderer

**Decision**: Jinja2 with `PackageLoader("video_to_runbook", "templates")`: `runbook.html.j2`
renders the right-column fragment (rows with `data-timestamp`, `data-order`, badge class,
`<details>` for flagged rows), `runbook.md.j2` renders the export. `static/index.html` is the
shell with inline CSS and about 80 lines of JavaScript (upload, poll, swap fragment,
delegated click to seek, footer). `render.py` exposes `render_fragment(status)` and
`render_markdown(status)`.

**Rationale**: satisfies "no framework, no build step" and "Jinja renders both HTML and
Markdown" with one pure module testable from golden fixtures.

## R12. Eval

**Decision**: `eval.py` parses the two ground-truth tables from `samples/README.md`,
builds a `pydantic_evals.Dataset` with two `Case`s, and custom evaluators
(`StepCountDiff`, `TimestampAgreement`, `ActionMatch`, `CheckAgreement`) that implement
FR-027a/b over `EvaluatorContext.output` (a `Runbook` plus `list[CheckRecord]`) and
`expected_output` (`TruthCase`). The task runs the Observer and the Validators in-process
(no Modal) using `asyncio.gather` for the checks. `report.print()` shows the table;
`--from DIR` scores a saved `runbook.json` and `checks.json` without network. Results land in
Logfire as an experiment automatically when `logfire.configure()` has run.

**Rationale**: one mechanism satisfies both the constitution's `eval.py` requirement and a
Pydantic Evals dataset. Parsing the README keeps the tables the single source of truth.

## R13. Tests without network

**Decision**: `pydantic_ai.models.function.FunctionModel` drives the Observer and Validator
in unit tests: one test returns an out-of-range timestamp first and a valid runbook second,
asserting two requests (the retry) and the final output; another returns `matches=False`
without a note and asserts the retry. `frames.py` is tested on a 3 s synthetic clip made with
`ffmpeg -f lavfi -i testsrc`. `render.py`, `eval.py`, and `models.py` use
`tests/fixtures/sap/{runbook,checks}.json`, recorded from the first real run. CI installs
`ffmpeg` with apt.

**Rationale**: Constitution III; `FunctionModel` and `TestModel` are present in 2.46.

## R14. Dependencies to add

`jinja2`, `fastapi[standard]`, `pydantic-settings`, `modal` (runtime, for `app.py` and the
CLI through `uv run`), and dev: `pytest`, `ruff`. `pydantic-evals` and `google-genai` already
arrive with `pydantic-ai`.

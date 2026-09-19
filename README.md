# Video-to-Runbook

Turn a screen recording of someone doing a task into a typed, validated, step-by-step
runbook, each step linked to its moment in the video. Built at Tech: Europe London,
19 September 2026.

## Architecture

```
Screen recording (mp4, about 2 min, 720p, optional narration)
        |
        v
[Modal] web            FastAPI: upload to the Volume, spawn observe, return run_id;
        |              status, video, and runbook routes for the page
        v
[Modal] observe        Observer agent (Gemini Pro-class, Pydantic AI, output_type=Runbook)
        |              writes runbook.json, then fans out
        v
[Modal] validate_step  .map() over steps: ffmpeg cuts three frames at the step's moment,
        |              Validator agent (Gemini Flash-class, output_type=StepCheck) judges them
        v
Volume /data/runs/{run_id}/  ->  render.py (Jinja)  ->  HTML fragment and Markdown export
```

Core modules under `src/video_to_runbook/` import without Modal or a network:
`models`, `config`, `frames`, `observer`, `validator`, `render`, `tracing`, `runs`, `eval`.
`app.py` is the only file that imports `modal`.

## Setup

Requires `uv`, `ffmpeg`, and `ffprobe` on the PATH.

```bash
uv sync
```

Create a gitignored `.env` in the repo root with:

```
GEMINI_API_KEY=...
LOGFIRE_TOKEN=...
LOGFIRE_PROJECT_URL=https://logfire-eu.pydantic.dev/<org>/<project>
```

The Gemini key must be on a billed project or hackathon credits: the Observer's Pro model is
not on the free tier. `LOGFIRE_TOKEN` is optional; without it nothing is sent to Logfire.
`LOGFIRE_PROJECT_URL` is the project's page in Logfire; the footer's trace link is built from
it and is hidden when it is unset.

Modal runs the app. Once per machine:

```bash
uv run modal token new
uv run modal secret create gemini --from-dotenv .env
uv run modal secret create logfire LOGFIRE_TOKEN=... LOGFIRE_PROJECT_URL=...
export MODAL_IMAGE_BUILDER_VERSION=2025.06
```

The `logfire` Secret may be created with an empty `LOGFIRE_TOKEN=` to run without tracing.
The builder export is needed until the workspace's default image builder is moved past
2023.12 in the Modal dashboard (Settings, Image config); the older builders cannot build
Python 3.13 images.

The gate, no network needed:

```bash
uv run ruff format --check . && uv run ruff check . && uv run pytest
```

The integration tests hit Gemini and record the golden fixtures when asked:

```bash
uv run --env-file .env pytest -m integration
RECORD_FIXTURES=1 uv run --env-file .env pytest -m integration   # rewrites tests/fixtures/sap/
```

## Run the demo

Serve the app from this machine with hot reload; the first run builds the image, about two
minutes, later runs reuse it:

```bash
uv run modal serve src/video_to_runbook/app.py
```

Open the printed `*.modal.run` URL and drop `samples/sap_b1_create_sales_order_demo.mp4` on
the page. The player appears as soon as the upload returns and the right column says
"Watching the recording…"; the runbook then lands whole, every step with a timestamp and a
grey "checking" badge. Step checks, badges flipping, and the footer's trace link arrive with
`validate_step`.

The same flow from a shell (curl sends `application/octet-stream` unless told the type; a
browser sends `video/mp4` on its own):

```bash
URL=https://<workspace>--video-to-runbook-web-dev.modal.run
curl -s -F 'file=@samples/sap_b1_create_sales_order_demo.mp4;type=video/mp4' $URL/runs   # 202 {"run_id": ...}
curl -s $URL/status/<run_id> | jq '.state, .elapsed_s, .calls'                            # poll every 2 s
curl -s $URL/runs/<run_id>/runbook.html | head                                            # the fragment
curl -s -o /dev/null -w '%{http_code}\n' -F file=@README.md $URL/runs                     # 415
curl -s -o /dev/null -w '%{http_code}\n' $URL/status/000000000000                        # 404
```

Measured on 19 September 2026 with the SAP sample (118 s, 4.5 MB): the upload returned in
4 s, `observe` started after a 15 s container cold start, and the runbook was on the page
46 s after the drop.

Deploy for the stage the same way:

```bash
uv run modal deploy src/video_to_runbook/app.py
```

### Demo tamper

Open the page as `$URL/?tamper=7` and drop the sample. After the Observer returns, step 7's
`target` is replaced with "the Log Out menu item" before the checks run, so the Validator
sees frames that do not show that label and flags the step with a note naming what they
show instead. The footer says "Demo tamper: step 7". A step number past the end of the
runbook changes nothing, and the footer says so ("Demo tamper requested for step 20, runbook
has 16 steps"). From a shell, add `-F tamper_step=7` to the upload.

Tamper runs (SC-005, each one a fresh SAP upload; the tampered step should read `flagged`):

| date | tamper | outcome |
| --- | --- | --- |
| 2026-09-19 | step 7 | flagged, note "clicking the Sales Employee dropdown arrow, not the Log Out menu item"; 17 steps, 18 calls, 165 s, run concurrently with the next row |
| 2026-09-19 | step 20 | not applied, footer "runbook has 14 steps"; 15 calls, 148 s |
| 2026-09-19 | none | 20-step runbook, step 20 capped under the 60-call budget ("call cap reached: 1 of 20 steps not checked"); cap raised to 100 |
| 2026-09-19 | step 20 | not applied, footer "runbook has 12 steps"; all 12 verified, 14 calls, 120k tokens, 76 s; browser run, row click seeks the player |
| 2026-09-19 | step 7 | flagged with a note, footer "Demo tamper: step 7"; browser run, flagged row expands to the note on click |

The cap path was seen on the page when a 20-step runbook tripped the old 60-call budget
(red banner, amber error badges, state `failed`). The forced-cap rehearsal with `CALL_CAP=2`
and its Logfire error event were skipped: the cap stays at 100 for the demo, where a healthy
run never reaches it.

### Retention

Every upload stays under `/data/runs/{run_id}/` on the Modal Volume `video-to-runbook-data`
(video, meta, runbook, one file per check) until cleared by hand:

```bash
uv run modal volume rm -r video-to-runbook-data /runs
```

Automatic deletion is roadmap.

## Decisions and trade-offs

- **Inline video, not the Files API.** The recording goes to Gemini as inline bytes in the
  request. Both samples are about 5 MB; Google's documented inline ceiling is 20 MB per
  request, below the page's 100 MB cap. An upload between the two that Gemini rejects ends
  as a failed run showing the provider's message; the Files API (upload, poll until active,
  reference) is the follow-up if that happens.
- **Static video processing at 1 fps, high media resolution.** Static mode stamps every
  second, which matches the eval's 3 s tolerance, and high resolution keeps 720p labels
  legible at about 300 tokens per second of video (about 35k tokens for the SAP clip).
  Agentic video mode is Flash-only, opt-in, and aimed at long videos, so the Observer's Pro
  tier cannot use it.
- **Gemini 3.1 Pro preview for the Observer, 3.8 Flash for the Validator.** No Pro model is
  GA; the preview is the only Pro-class model with video input and structured output.
  `gemini-2.5-pro` is the one-line fallback (`OBSERVER_MODEL`) if the preview misbehaves.
  Swapping either tier changes cost and latency, so it is a written decision, not a default.
- **Schema, not parsing.** Both agents declare an `output_type`; contiguous orders,
  increasing timestamps, non-generic targets, and the duration ceiling are validators whose
  messages become the retry prompt. The live eval showed one such retry on the SAP clip.
- **Volume commit and reload.** Modal Volumes are not a network filesystem: writers commit
  after writing, readers reload before reading. Each validator writes only its own
  `checks/{order}.json`, so parallel checks never contend and the run has no shared state.
- **The video is served from a local copy.** `GET /runs/{id}/video` copies the file to `/tmp`
  once and serves it from there with Range support; streaming from the Volume would hold a
  file open and break `reload()` during status polls.
- **Budgeted call cap, not a shared counter.** Each run may make at most 100 model calls
  (`CALL_CAP`). The Observer gets 4 requests; after it returns, the remaining budget is
  divided by 3 (the per-check request limit) into check slots, and steps beyond the slots
  are recorded as errors without a call. The budget assumes every check retries twice, so
  it is conservative: in practice checks use one request each. The cap started at 60 and
  moved to 100 after a 20-step runbook tripped it in rehearsal.

## Eval scores

`uv run python -m video_to_runbook.eval` scores the Observer against the ground-truth tables
in `samples/README.md` after subtracting each clip's cut offset: step-count difference,
share of ground-truth steps with a produced step within 3 s, share of those pairs with the
same action, and share of produced steps the Validator verified. Last run:

| case | steps | truth | Δ | ts≤3s | action | check | date |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sap_b1_create_sales_order_demo | 16 | 14 | +2 | 0.79 | 0.73 | 0.94 | 2026-09-19 |
| google_ai_studio_api_key_screen_only | 7 | 7 | 0 | 0.71 | 0.40 | 0.71 | 2026-09-19 |

The SAP row meets the opening targets (|Δ| ≤ 4, ts≤3s ≥ 0.70, action ≥ 0.70). The first
run scored 17 steps, 0.71, 0.50, 1.00 on SAP: the Observer called nearly every moment a
`click`. One rule was added to its instructions, choosing the action by what the moment is
for (`type`, `select`, `verify`) rather than by the mouse, and the table above is the re-run.
The AI Studio clip is the untuned control; its actions are mostly `verify` in the ground
truth, which the Observer still under-uses. A full eval run on both clips costs about $0.30
in Gemini credits and 26 calls; `--from tests/fixtures/sap` scores the saved fixtures for free.

## Observability

To be written with the trace propagation.

## Roadmap

- Executors that replay a verified runbook: Playwright for web apps, an n8n workflow for
  API-shaped steps, a computer-use agent for thick clients such as SAP Business One.
- Pydantic AI Gateway for one key, spend limits, and provider fallbacks.
- Files API path for uploads above 20 MB.
- An agentic-mode Flash Observer experiment if timestamp drift on static Pro exceeds 3 s;
  that changes a model tier, so it needs a written decision first.
- An Observer frame tool (the agent asks for a frame at a timestamp before committing to a
  step), packaged as a Pydantic AI `Capability`.
- Retention policy: automatic deletion of runs after a set time.
- Auth and multi-user: today one operator, no identity, no run history.

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
```

The Gemini key must be on a billed project or hackathon credits: the Observer's Pro model is
not on the free tier. `LOGFIRE_TOKEN` is optional; without it nothing is sent to Logfire.

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

### Retention

Every upload stays under `/data/runs/{run_id}/` on the Modal Volume `video-to-runbook-data`
(video, meta, runbook, one file per check) until cleared by hand:

```bash
uv run modal volume rm -r video-to-runbook-data /runs
```

Automatic deletion is roadmap.

## Decisions and trade-offs

To be written as each decision lands.

- **Budgeted call cap, not a shared counter.** Each run may make at most 100 model calls
  (`CALL_CAP`). The Observer gets 4 requests; after it returns, the remaining budget is
  divided by 3 (the per-check request limit) into check slots, and steps beyond the slots
  are recorded as errors without a call. The budget assumes every check retries twice, so
  it is conservative: in practice checks use one request each. The cap started at 60 and
  moved to 100 after a 20-step runbook tripped it in rehearsal.

## Eval scores

| case | steps | truth | Δ | ts≤3s | action | check | date |
| --- | --- | --- | --- | --- | --- | --- | --- |

## Observability

To be written with the trace propagation.

## Roadmap

To be written.

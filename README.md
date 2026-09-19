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

For deployed runs the same values live in two Modal Secrets:

```bash
uv run modal secret create gemini GEMINI_API_KEY=...
uv run modal secret create logfire LOGFIRE_TOKEN=... LOGFIRE_PROJECT_URL=...
```

The gate, no network needed:

```bash
uv run ruff format --check . && uv run ruff check . && uv run pytest
```

## Run the demo

To be written with the Modal app.

## Decisions and trade-offs

To be written as each decision lands.

## Eval scores

| case | steps | truth | Δ | ts≤3s | action | check | date |
| --- | --- | --- | --- | --- | --- | --- | --- |

## Observability

To be written with the trace propagation.

## Roadmap

To be written.

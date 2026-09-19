# Quickstart: validating the Observer Pipeline

Runnable checks that prove the feature works, in the order they become possible during the
build. Contracts are in [contracts/](contracts/), the data model in
[data-model.md](data-model.md). Every command runs from the repo root.

## Prerequisites

- `uv`, `ffmpeg`, `ffprobe`, and `modal` on the PATH (all present on the build machine).
- `samples/sap_b1_create_sales_order_demo.mp4` (118 s, 4.5 MB) and
  `samples/google_ai_studio_api_key_screen_only.mp4` (51 s, 5.0 MB). Gitignored; re-download
  per `samples/README.md`.
- A gitignored `.env` with `GOOGLE_API_KEY` (the Gemini key) and `LOGFIRE_TOKEN`. Neither
  is needed for the gate below.
- A Modal token (`modal token new`, once) and two Modal Secrets created from the same values:

  ```bash
  modal secret create gemini GOOGLE_API_KEY=...
  modal secret create logfire LOGFIRE_TOKEN=...
  ```

## 1. The gate (no network, under 5 seconds)

```bash
uv run ruff format --check . && uv run ruff check . && uv run pytest
```

Expected: all green. `pytest` runs one test module per core module against the golden
fixtures in `tests/fixtures/sap/` (`runbook.json`, `checks.json`) and never opens a socket.
Integration tests report as skipped because `GOOGLE_API_KEY` is unset in the test session.

## 2. The Observer alone (network, one Pro call plus retries)

```bash
uv run pytest -m integration -k observer
```

Expected: a `Runbook` for the SAP sample with steps numbered 1..N, strictly increasing
`timestamp_s`, all ≤ 118.05. If the model sends a timestamp past the end, the trace shows a
retry prompt naming the step, and the test still passes on the corrected output.

## 3. The eval (network, Pro plus one Flash call per step)

```bash
uv run python -m video_to_runbook.eval samples/sap_b1_create_sales_order_demo.mp4
uv run python -m video_to_runbook.eval            # both cases
```

Expected output shape:

```
case                       steps  truth  Δ   ts≤3s   action  check
sap_b1_create_sales_order  13     14     -1  0.79    0.82    0.85
google_ai_studio_api_key   7      7      0   0.86    0.83    1.00
overall                                      0.82    0.82    0.90
```

Passes SC-001 when the SAP row has `|Δ| ≤ 4`, `ts≤3s ≥ 0.70`, `action ≥ 0.70`. Copy the table
into `README.md` under "Eval scores". The same run appears as an experiment in Logfire.

Scoring without the network, against the saved fixture:

```bash
uv run python -m video_to_runbook.eval --from tests/fixtures/sap
```

## 4. The Modal app locally

```bash
modal serve src/video_to_runbook/app.py
```

Expected: a `*.modal.run` URL printed. Open it, drop the SAP sample, and walk the page
states in [contracts/page.md](contracts/page.md): video visible and "watching" within 5 s;
the runbook lands whole with grey badges; badges flip individually; footer fills at `done`.
Total under 3 minutes (SC-002). Click a row: player seeks and pauses (SC-006). Press export:
a `.md` file downloads (SC-009).

Curl checks against the same URL:

```bash
curl -s -F file=@samples/sap_b1_create_sales_order_demo.mp4 $URL/runs           # {"run_id": ...}
curl -s $URL/runs/$RUN_ID | jq '.state, (.checks | length)'                       # poll
curl -s -o /dev/null -w '%{http_code}\n' -F file=@README.md $URL/runs              # 415
curl -s -o /dev/null -w '%{http_code}\n' $URL/runs/000000000000                   # 404
curl -s $URL/runs/$RUN_ID/runbook.md | head                                       # Markdown
```

## 5. The caught mistake

Open `$URL/?tamper=7`, drop the SAP sample. Expected: step 7 ends `flagged` with a note that
names what the frames show instead; every other badge is `verified` or `error`; the footer
says "Demo tamper: step 7". Open `$URL/?tamper=20`: nothing altered, footer says the runbook
has fewer steps.

## 6. The trace

In Logfire, filter `run_id = '<id>'`. Expected: one `runbook` span containing the Observer
agent run (with any retry prompt visible as a second model request), then N `validate_step`
spans side by side, each with its own agent run and token counts. Force the cap by setting
`CALL_CAP=2` in the Modal Secret or `.env`: the run ends `failed`, the page shows the reason,
and the trace has an error-level `call cap reached` event.

## 7. Deploy for the demo

```bash
modal deploy src/video_to_runbook/app.py
```

Then set `min_containers=1` on `observe` (a one-line change in `app.py`, committed as
`chore: keep observe warm for the demo`) about an hour before the slot, and rehearse once
on the AI Studio clip, which the Observer has not been tuned on.

# Contract: HTTP API

One web endpoint on Modal serves the page and five routes. All JSON bodies are Pydantic
models from [data-model.md](../data-model.md). No auth, no versioning (single operator,
one-day build).

| Method | Path | Request | Response | Errors |
| --- | --- | --- | --- | --- |
| `GET` | `/` | | `200 text/html`: the static page shell | |
| `POST` | `/runs` | `multipart/form-data`: `file` (the recording), optional `tamper_step` (int) | `202 application/json`: `{"run_id": "<12 hex>"}` | `415` if content type is not `video/*`; `413` if larger than 100 MB; `422` if `tamper_step` is not a positive int |
| `GET` | `/runs/{run_id}` | | `200 application/json`: `RunStatus` | `404 {"detail": "unknown run"}` |
| `GET` | `/runs/{run_id}/video` | optional `Range` | `200`/`206 video/mp4` | `404` |
| `GET` | `/runs/{run_id}/runbook.html` | | `200 text/html`: the runbook fragment (step rows with badges), or the state message when no runbook yet | `404` |
| `GET` | `/runs/{run_id}/runbook.md` | | `200 text/markdown` with `Content-Disposition: attachment; filename="<title-slug>.md"` | `404`; `409 {"detail": "no runbook yet"}` if the runbook does not exist |

## Behaviour

- `POST /runs` returns as soon as the file is stored and `observe` has been spawned. It never
  waits for the Observer (Constitution invariant). It probes the duration with `ffprobe`
  before returning so `RunStatus.duration_s` is available on the first poll.
- `GET /runs/{run_id}` is safe to poll every 2 s; it reads the Volume and assembles the
  payload each time. `checks` grows as validators finish. `state` transitions are listed in
  the data model.
- `GET /runs/{run_id}/runbook.html` is the Renderer's HTML output for the current status: the
  page swaps it into the right-hand column on every poll. It contains no scripts; click
  handling is delegated from the shell using `data-timestamp` and `data-order` attributes on
  each row. A flagged row is a `<details>` element whose body holds the check's note.
- `GET /runs/{run_id}/runbook.md` is the same Renderer over the same status, as Markdown.

## `RunStatus` example (mid-check)

```json
{
  "run_id": "3f9a1c2b7d4e",
  "state": "checking",
  "error": null,
  "filename": "sap_b1_create_sales_order_demo.mp4",
  "duration_s": 118.05,
  "video_url": "/runs/3f9a1c2b7d4e/video",
  "tamper_step": 7,
  "tamper_applied": true,
  "trace_url": "https://logfire-eu.pydantic.dev/.../?q=run_id%3D%273f9a1c2b7d4e%27",
  "elapsed_s": 74.2,
  "calls": 9,
  "input_tokens": 41230,
  "output_tokens": 2210,
  "runbook": {
    "title": "Create a sales order in SAP Business One",
    "system": "SAP Business One desktop client",
    "prerequisites": ["A customer master record exists"],
    "steps": [
      {"order": 1, "timestamp_s": 1.0, "action": "navigate", "target": "Modules > Sales A/R > Sales Order",
       "value": null, "screen": "Main menu", "intent": "Open a blank sales order form"}
    ],
    "pitfalls": ["Add fails until a delivery date is entered"]
  },
  "checks": [
    {"order": 1, "check": {"order": 1, "matches": true, "confidence": 0.93, "note": null},
     "error": null, "requests": 1, "input_tokens": 2900, "output_tokens": 60},
    {"order": 2, "check": null, "error": "timed out after 30 s and 2 retries",
     "requests": 3, "input_tokens": 8700, "output_tokens": 0}
  ]
}
```

Steps 3 onward have no record yet, so the page shows them as `checking`.

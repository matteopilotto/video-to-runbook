# Contract: The Page

One static HTML file with inline CSS and JavaScript, no framework, no build step, served at
`GET /`. Left column: video player. Right column: the runbook fragment from
`GET /runs/{run_id}/runbook.html`. Footer: elapsed time, token count, trace link. Nothing
else (FR-022).

## States (FR-019)

| # | State | Trigger | Left | Right | Footer |
| --- | --- | --- | --- | --- | --- |
| 1 | empty | page load | drop zone (also a file picker) | "Drop a screen recording to begin" | empty |
| 2 | uploading | file chosen | drop zone shows progress text | "Uploading…" | empty |
| 3 | watching | `POST /runs` returned | player with `src=/runs/{id}/video`, paused at 0 | spinner and "Watching the recording…" | elapsed ticking |
| 4 | checking | status has `runbook` | player | every step row, badge `checking` | elapsed, calls |
| 5 | flipping | `checks` grows | player | badges change one by one | elapsed, calls, tokens |
| 6 | done | `state == "done"` | player | all badges terminal | elapsed frozen, tokens, trace link, tamper notice if requested |
| F | failed | `state == "failed"` | player | red banner with `error`, plus whatever rows exist | as done |

Polling: `GET /status/{id}` every 2 s from state 3 until `done` or `failed`. On each poll the
page also fetches `runbook.html` and replaces the right column's inner HTML. `404` on the
status poll shows "Run not found" and stops polling.

## Hidden parameter (FR-017)

`?tamper=<n>` on the page URL. When present, the page sends `tamper_step=<n>` with the
upload. The page never shows the parameter's presence except in the done-state footer:
"Demo tamper: step 7" or "Demo tamper requested for step 20, runbook has 14 steps".

## Interaction (FR-020, FR-021)

- Click on a step row (`[data-timestamp]`): `video.currentTime = timestamp; video.pause()`.
  Delegated from the right column so re-rendering never loses the handler.
- A flagged row is a `<details>` whose summary is the row and whose body is the note.
  Clicking the summary both seeks and toggles the note.
- "Export Markdown" button: `<a download href="/runs/{id}/runbook.md">`, enabled once a
  runbook exists.

## Badge (FR-015)

Four CSS classes on `.badge`: `checking` (grey, text "checking"), `verified` (green,
"verified"), `flagged` (red, "flagged"), `error` (amber with a warning glyph, "error").
Error and flagged differ in colour and text, not colour alone.

## Refusals (FR-001)

Non-video file or over 100 MB: the page shows the reason inline in the drop zone and stays
in state 1. The server enforces the same rule (`415`/`413`) in case the check is bypassed.

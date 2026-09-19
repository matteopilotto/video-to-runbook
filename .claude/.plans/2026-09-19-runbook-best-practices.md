# Plan: write runbooks the way the PagerDuty guide says to

**Date**: 2026-09-19 | **Status**: proposed, nothing implemented
**Source**: PagerDuty, "What is a Runbook?", section *Creating a Runbook Template for Your
Company* (`#heading-3`, sub-steps `#heading-4` to `#heading-6`),
https://www.pagerduty.com/resources/automation/learn/what-is-a-runbook/#heading-3
**Branch**: see "Open decisions" at the end; not started.

## Assumptions

1. "Writing a runbook" means the artifact this product produces: the `Runbook` the Observer
   returns and the page and Markdown export that render it. The other reading, an
   operations runbook for running the deployed Modal app itself, is not covered here; it
   would be a `docs/` task with Limoncelli's seven sections and no code.
2. The article is written for hand-authored IT runbooks. Each of its practices is mapped to
   the mechanism we already have for that concern (schema validator, Observer instruction,
   template), and the plan only adds something where there is a gap.
3. Scope stays inside Observer, Validator, and Renderer. No new Modal function, no change
   to the page layout (the grid with flipping badges is the demo), no executors.
4. The demo is today. Every task is one commit that passes the gate, and the two tasks that
   need Gemini (live eval, fixture re-record) are grouped so they cost one run each.

## What the article says

Quoted from the section behind the anchor, numbered for reference below.

**Step 1: Planning a New Runbook**
- P1. Pick "the most common incidents or tasks your team faces" and "the best solutions for
  effectively handling these in the past".
- P2. "The runbook should include the agreed upon, best possible solution and present it
  clearly for the operator." Often that is what "an expert" considers best practice.

**Step 2: Write Your Runbook**
- P3. "Keep it clear and simple – leave out unnecessary details."
- P4. "Use documentation language that is easy to understand and follow."
- P5. "Make it specific and unique to your processes."
- P6. "It should be flexible and adaptable to changes in your systems and applications."
- P7. "Consistent across all applications. Make sure they are each structured in the same
  way, and provide the operator with all the needed details. For example, make the naming
  and headers consistent."
- P8. "Field test the documented process and make any updates or changes as needed."
- P9. Tom Limoncelli's seven sections: Service Overview, Service Build Information,
  Instructions for Deploying the Software, Instructions for Common Tasks, "Pager Playbook",
  Disaster Recovery Plans, Service Level Agreement.

**Step 3: Test, Update, and Improve Your Runbooks**
- P10. "Not just set it and forget it. Runbooks should be constantly tested and updated to
  ensure its functioning at optimal levels, even as your systems or applications change."

## Mapping to the pipeline

| Practice | Already have | Gap |
| --- | --- | --- |
| P1, P2 the expert's agreed solution | The recording is the expert demonstration; the Observer writes the clean path and puts rejected forms in `pitfalls`. | The Observer is not told that detours and the narrator's warnings belong in `pitfalls` with the step they apply to, nor that steps show only the path that worked. |
| P3 clear and simple | Instructions drop scrolling, mis-clicks, idle time. | The SAP fixture still has "click Customer" before "select Earthshaker" and two tab clicks whose intent is "view ... information". Ground truth has 14 steps, the Observer produced 16. `intent` has no guidance on length. |
| P4 easy-to-follow language | `Action` is a fixed verb set. | The Markdown export is a nine-column data table. Nobody follows a table while doing the task; the article's "recipe" is a numbered list of imperative sentences. |
| P5 specific to your process | Non-generic `target` validator, `system`, `screen`, `value`. | A `type` step can come back with no `value`. `prerequisites` is always empty in practice, so the starting state (which screen, which records must exist) is never stated. |
| P6 adaptable to change | `intent` per step says what, not just which label. | The export does not say which recording it came from or when, so a reader cannot tell it is stale. |
| P7 consistent structure and headers | Same two templates for every runbook. | Prerequisites and Pitfalls sections only appear when non-empty, so two runbooks have different shapes. No title convention (fixture: "Creating a Sales Order"; ground truth phrasing: "Create Sales Order"). No stated end state. |
| P8, P10 field test, keep updated | The Validator is an automated field test per step; flagged steps carry a note; the export prints status and note per step. | No summary of the test at the top of the export (how many verified, flagged, unchecked). |
| P9 seven sections | Our runbook is one "Instructions for Common Tasks" entry; `title` and `system` are its Service Overview line. | The other five sections are service-level documents no recording can source. Not a gap; see "Not planned". |

## Tasks

One commit each, in this order. The gate for every task is
`uv run ruff format --check . && uv run ruff check . && uv run pytest`. T3 to T5 touch the
runbook schema or the Observer, so the eval runs after them (saved fixtures after each,
live SAP once at T5).

### T1 Renderer: every runbook has the same sections in the same order (P7)

- Both templates always render, in this order: title, system line, **Prerequisites**,
  **Steps**, **Pitfalls**. An empty list renders the single line "None recorded." instead of
  dropping the heading. (T4 adds **Outcome** between Steps and Pitfalls.)
- Files: `src/video_to_runbook/templates/runbook.html.j2`, `runbook.md.j2`.
- Tests: `tests/test_render.py`, a case that renders the SAP fixture (empty prerequisites)
  and asserts both headings and "None recorded." are present in both outputs.
- Docs: add a "Runbook shape" bullet under README "Decisions and trade-offs" naming the
  fixed section order and the PagerDuty guide as the reason. Later tasks extend the bullet.

### T2 Renderer: the Markdown export is a numbered list of instructions (P4)

- Add an `instruction` Jinja filter in `render.py` that turns a `Step` into one imperative
  sentence from a fixed verb table: click "Click **{target}**", type "Type `{value}` into
  **{target}**", select "Select **{target}**", navigate "Go to **{target}**", wait "Wait
  for **{target}**", verify "Check **{target}**"; then " on the {screen} screen".
- `runbook.md.j2` replaces the step table with one line per step:
  `{order}. **{mm:ss}** {instruction}, to {intent}. \`{badge}\`` followed by `: {note}` for a
  flagged step or `: {error}` for an errored one. The HTML grid is unchanged.
- `validator.describe()` builds a similar sentence for the model; leave it alone, it is
  prompt text and changing it means re-running the eval for no runbook benefit.
- Tests: rewrite `test_markdown_export_lists_every_step_with_its_status` to match numbered
  lines (`^\d+\. `), keep every existing assertion (time, target, value, screen, intent,
  status, note, error on the right line). Add a table-driven test for `instruction` over
  all six actions.
- Docs: none; the README names the export but never describes its table layout.

### T3 Models: a `type` step must carry `value` (P5)

- `Runbook` model validator `typed_steps_carry_values`: for each step with
  `action == "type"` and empty `value`, raise
  `f"step {step.order} types into '{step.target}' but has no value; record what was typed"`.
  The message becomes the Pydantic AI retry prompt, like the existing validators.
- Fixture: SAP `runbook.json` step 13 already has a value, so nothing changes.
- Tests: `tests/test_models.py`, rejected without value, accepted with `"Tab"` as value
  (ground-truth step 4 types the Tab key).
- Eval: `uv run python -m video_to_runbook.eval --from tests/fixtures/sap` still runs.

### T4 Models and Renderer: `outcome`, the end state of the task (P7, P2)

- `Runbook.outcome: NonEmpty`, required: one sentence describing what the screen shows when
  the task is done (SAP: "The new sales order is displayed with its document number").
  Ground-truth step 14 is exactly this; today it is a `verify` step or missing.
- Both templates render an **Outcome** section after Steps, before Pitfalls.
- Fixture: add `"outcome"` to `tests/fixtures/sap/runbook.json` by hand in this commit and
  say so in the commit message; T7 re-records it from the model.
- Tests: `test_models.py` (missing outcome rejected), `test_render.py` (section present in
  both outputs), `test_observer.py` payload helper gains the field.
- Docs: README "Runbook shape" bullet lists Outcome.
- This is the one item that goes past the article's letter. The justification is the
  article's own recipe analogy and P7's "all the needed details": a recipe ends with the
  dish. Cut it if you disagree; T5 then drops its outcome line.

### T5 Observer: instructions for simple, specific, consistent runbooks (P2, P3, P5, P7)

Add to `OBSERVER_INSTRUCTIONS`, each bullet one rule:

- Title is the task as an imperative phrase, verb first, without the system name
  ("Create a sales order"); `system` carries the product.
- One step per action the operator must perform. A click that only focuses a field is part
  of the `type` or `select` that follows, not a step. A tab or menu click that only reveals
  values is not a step; if the narrator points at those values it is one `verify` step
  naming them.
- `intent` is one short clause saying what the step is for; do not repeat the target.
- `prerequisites` list the state the recording starts from: the screen open at 00:00 and
  any record the task relies on (a customer, an item, a project) that must already exist.
- `type` steps carry the typed text or key name in `value`.
- Steps show only the path that worked. A rejected form, a wrong click the narrator
  corrects, or a warning the narrator gives goes in `pitfalls`, prefixed with the step it
  belongs to ("Step 12: ...").
- `outcome` describes what is on screen when the task is complete (drop if T4 is cut).

- Files: `src/video_to_runbook/observer.py` only.
- Tests: existing `FunctionModel` tests cover the agent wiring; no new unit test.
- Eval (required, hits Gemini, about 18 calls and $0.15):
  `uv run --env-file .env python -m video_to_runbook.eval samples/sap_b1_create_sales_order_demo.mp4`.
  Target: step-count Δ moves from +2 toward 0 without ts≤3s dropping below 0.70. Record
  the row in the README eval table with today's date and a sentence on what changed.
  Prerequisites and outcome are not scored; check them by eye in the printed runbook.

### T6 Export header: provenance and test summary (P6, P8, P10)

- `RunStatus.created_at: datetime` (from `RunMeta`), set in `runs.read_status`.
- `runbook.md.j2` prints, under the system line:
  `Recorded from {filename} ({mm:ss}), generated {created_at date} by Video-to-Runbook.
  Checks: {verified} verified, {flagged} flagged, {error} not checked, {checking} pending.`
  Counts come from `status.checks` via Jinja `selectattr("badge", "equalto", ...)`.
- Files: `models.py`, `runs.py`, `runbook.md.j2`; `tests/test_runs.py`,
  `tests/test_render.py` (the `status_for` helper gains `created_at`; assert the header and
  the counts for the fixture's mix of verified, flagged, error, checking).
- HTML fragment unchanged: the page footer already shows calls and elapsed live.

### T7 Re-record the golden fixtures (P8)

- `RECORD_FIXTURES=1 uv run --env-file .env pytest -m integration` rewrites
  `tests/fixtures/sap/runbook.json` and `checks.json` under the new schema and
  instructions (about 18 calls). Then `uv run pytest` and the `--from` eval.
- Look at the recorded fixture before committing: it must still contain at least one
  flagged check (`test_fragment_badges_follow_the_checks` needs it) and step 13 with a
  value. If not, re-run once; if still not, keep the hand-edited fixture and say so in the
  commit.
- Commit as `test: re-record SAP fixtures under the runbook shape from T3 to T5`.

Total Gemini spend for the plan: two live runs, about 36 calls, about $0.30.

## Constitution check

| Principle | How the plan holds it |
| --- | --- |
| I Pure core, thin glue | Only `models.py`, `observer.py`, `render.py`, `runs.py`, and the templates change. `app.py` untouched. |
| II Typed at every boundary | New rules are a `Runbook` model validator (T3) and a required field (T4); both become retry prompts through Pydantic AI. No hand parsing. |
| III Tests in a second | Each task adds or adjusts a unit test on the SAP fixture. The only network use is the eval (T5) and the marked integration re-record (T7). |
| IV An eval, not a vibe check | T5 re-runs the live SAP eval and records the row; every schema task re-runs the saved-fixture eval. |
| V Failures visible | Unchanged. T6 adds the check counts to the export so a flagged or unchecked step is visible before the reader reaches it. |
| VI Fixed scope, simplest mechanism | No new mechanism: a Jinja filter, one validator, one field, seven instruction bullets. A character cap on `intent` and a `purpose`/`when to use` field were considered and dropped (below). |
| Invariants | `timestamp_s` untouched; tiers untouched; no Modal changes; `ingest`, `map`, Logfire, cap untouched. |

## Not planned, and why

- **Limoncelli's other six sections (P9).** Build info, deployment, alert playbook, disaster
  recovery, and SLA are documents about a service; a recording of one task cannot source
  them. Our runbook is the "Common Tasks" entry, and `title` plus `system` is its overview
  line. Say this in the README bullet so a judge who knows the seven sections sees it was
  a decision.
- **A `purpose` / "when to use" field (P1).** The trigger for a task is rarely visible in a
  recording. `title` and the intents cover what the Observer can actually see.
- **A character cap on `intent` (P3).** A number would be arbitrary; the instruction bullet
  in T5 says "one short clause" and the live eval shows whether the model obeys.
- **Instruction sentences in the HTML grid (P4).** The grid is the demo; changing columns
  on the day is risk for no judge-visible gain. The export is where someone follows the
  runbook.
- **Human edits and re-tests of a runbook (P8, P10).** That is a runbook editor with
  history; roadmap, prose only.
- **Semi- and fully-automated runbooks.** Executors are roadmap per the constitution.

## Definition of done

- Seven commits on the branch, each passing the gate.
- README eval table has a new SAP row dated today; README "Decisions and trade-offs" has the
  "Runbook shape" bullet; `samples/README.md` and `CLAUDE.md` need no change (nothing is
  renamed or moved), confirm by grep for `prerequisites`, `pitfalls`, `export`.
- The SAP export, downloaded from a fresh run, reads top to bottom as: title, system,
  provenance line, check summary, Prerequisites, numbered Steps, Outcome, Pitfalls.
- `uv run python -m video_to_runbook.eval --from tests/fixtures/sap` scores the re-recorded
  fixture without network.

## Open decisions

1. **Branch.** `001-observer-pipeline` is 55 commits ahead of `main` and unmerged. Two
   readings: (a) merge 001, then `/speckit-specify` with this file as the feature
   description, giving `002-runbook-best-practices` and a spec-kit plan that points back
   here; (b) merge 001, then `feat/runbook-best-practices` off `main` and use this file as
   the task list directly. Recommendation: (b) today, because it is seven small commits and
   the demo is tonight; (a) if this lands after the event.
2. **Keep T4 (`outcome`)?** It is the one item beyond the article's wording. Default: keep.
3. **Export format.** T2 proposes a numbered list and drops the table. If you want both, the
   table goes below the list under a "Step data" heading; say so before T2.

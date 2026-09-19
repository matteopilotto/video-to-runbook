# Feature Specification: Observer Pipeline End to End

**Feature Branch**: `001-observer-pipeline`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: handoff document `/tmp/video-to-runbook-handoff-2026-09-19.md`, whose suggested first feature is "Observer pipeline end to end: upload a recording, a validated runbook comes back, per-step frame validation fans out in parallel, a single-page UI shows badges and seeks the video, and the run is traced. Include the output validator with retry and the eval in scope; leave the frame tool and the reusable capability as follow-ups. Keep executors, auth, multi-user, and gateway out."

## Clarifications

### Session 2026-09-19

- Q: How should the eval pair a produced step with a ground-truth step before scoring action match and timestamp agreement? → A: For each ground-truth step, in order, take the nearest not-yet-paired produced step within 3 s after offset correction. Timestamp agreement is the share of ground-truth steps that got a pair; action match is the share of pairs with the same action.
- Q: What should the eval's "check agreement rate" measure? → A: The share of steps in an untampered run whose check verdict is "verified", read from the run's existing check results; the eval adds no model calls beyond the run itself.
- Q: How should the demo tamper choose which step to alter? → A: The hidden page parameter carries the step number to tamper. If the runbook has fewer steps than that number, nothing is tampered and the footer says so.
- Q: How long should uploaded recordings and their results be kept on the server after a run finishes? → A: Kept until cleared by hand. No automatic deletion in this feature; the README states this and lists deletion as roadmap.
- Q: How many model calls should a single run be allowed before the cap trips and the run fails? → A: A fixed cap of 60 calls per run, counted across the watching call, its retries, and every check and check retry.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Turn a recording into a runbook (Priority: P1)

An operator who knows a business process records their screen while doing it once, then drops the recording onto the page. The page shows the video right away with a "watching" indicator. After a wait, the whole runbook appears at once: a title, the system the task was done in, prerequisites, an ordered list of steps, and pitfalls. Every step names the moment in the video where it happens, the action taken, the on-screen element it was taken on, any value entered or chosen, the screen the user was on, and why the step matters.

**Why this priority**: This is the product. Without a runbook nothing else on the page has anything to show.

**Independent Test**: Drop the SAP Business One sales-order sample and confirm a runbook appears whose steps line up with the ground-truth table in `samples/README.md` within the tolerances of User Story 5. No verification badges are needed to test this story.

**Acceptance Scenarios**:

1. **Given** the empty page, **When** the operator drops a recording of 100 MB or less, **Then** the video is visible in the player, the page shows the "watching" state, and a run reference has been issued, all before the runbook exists.
2. **Given** a run in progress, **When** the runbook is ready, **Then** every step appears in the same instant, steps are numbered contiguously from 1, each step's moment lies inside the video's duration, and moments strictly increase from one step to the next.
3. **Given** the SAP sample, **When** the runbook is produced, **Then** the expected failure at 1:41 on the demo clip (Add rejected because the delivery date is missing) is recorded as a pitfall or as a step whose intent explains the failure, not silently skipped.
4. **Given** the watching system produces a runbook that breaks a rule (a moment past the end of the video, a gap in step numbers, a moment that does not increase, or a target as vague as "the button"), **When** the output is checked, **Then** it is rejected with a reason that names the offending step and the rule, a corrected runbook is requested, the rejection is visible in the run's trace, and the operator never sees the invalid version.
5. **Given** the corrected runbook still breaks a rule after the allowed number of attempts, or the run reaches its call budget, **When** the run stops, **Then** the page shows a failure state with the reason instead of an empty or partial runbook.

---

### User Story 2 - See each step verified against the video (Priority: P2)

As soon as the runbook lands, every step carries a grey "checking" badge. Each step is checked on its own against what the video actually shows at that moment, and the badges flip to "verified" or "flagged" one by one as the checks finish. A flagged step can be expanded to read why the check disagreed. A check that could not be completed shows an "error" badge that looks different from "flagged", and the step stays in the list.

**Why this priority**: A caught mistake is the strongest moment in the demo and the reason the runbook can be trusted. It also distinguishes the product from tools that only transcribe.

**Independent Test**: Load a previously recorded runbook for the SAP sample, run the checks, and confirm every badge reaches a terminal state. Turn on the demo tamper and confirm the tampered step is flagged with a note.

**Acceptance Scenarios**:

1. **Given** the runbook has just appeared, **When** checks begin, **Then** every step shows the "checking" badge.
2. **Given** a check finds the video at that moment shows what the step describes, **When** its result arrives, **Then** the badge becomes "verified".
3. **Given** a check finds the video does not show what the step describes, **When** its result arrives, **Then** the badge becomes "flagged", and clicking the row reveals the check's note.
4. **Given** a check could not be completed (the model did not answer in time or returned an unusable result after the allowed retries), **When** the run records it, **Then** the badge becomes "error", visually distinct from "flagged", and the step is not removed.
5. **Given** the hidden page parameter names step 7 and the runbook has at least 7 steps, **When** checks run, **Then** only step 7's target has been altered before checking and step 7 ends up "flagged" with a note describing the mismatch.
6. **Given** the hidden page parameter names step 20 and the runbook has 14 steps, **When** checks run, **Then** no step is altered and the footer states that the tamper did not apply.
7. **Given** every check has finished, **When** the page polls next, **Then** the footer shows elapsed time, model token usage, and a link to the run's trace.

---

### User Story 3 - Jump the video to a step (Priority: P3)

The operator clicks any step row and the video jumps to that step's moment and pauses there, so the written step can be compared against what was on screen.

**Why this priority**: This is how a reader of the runbook confirms a step for themselves and how a presenter shows that steps are anchored to real moments. It depends on User Story 1 only.

**Independent Test**: With a runbook on screen (checks may still be pending), click a row and confirm the player position and paused state.

**Acceptance Scenarios**:

1. **Given** the runbook is on screen, **When** a step row is clicked, **Then** the player moves to that step's moment and pauses.
2. **Given** the video is playing, **When** a different row is clicked, **Then** the player moves to the new moment and pauses.

---

### User Story 4 - Export the runbook as Markdown (Priority: P4)

The operator presses an export button and downloads the runbook as a Markdown file carrying the same content as the page, including each step's verification status and note.

**Why this priority**: The runbook is meant to leave the page and be shared or executed later. Export is small and independent of the other stories once a runbook exists.

**Independent Test**: With a completed run, press export and open the downloaded file.

**Acceptance Scenarios**:

1. **Given** a run whose checks have all finished, **When** export is pressed, **Then** a Markdown file downloads containing the title, system, prerequisites, every step with its moment, action, target, value, screen, intent and verification status and note, and the pitfalls.
2. **Given** a run whose checks are still pending, **When** export is pressed, **Then** the file downloads with each pending step marked as still checking.

---

### User Story 5 - Measure observer accuracy against ground truth (Priority: P5)

A maintainer runs one command that scores the watching system against the two ground-truth step tables in `samples/README.md` and prints the result. The score covers how close the step count is, how many matched steps have the same action, how many matched steps land within 3 seconds of the recorded moment, and what share of steps the per-step check marked "verified". The latest numbers are kept in the project README so a change that makes things worse is visible.

**Why this priority**: "It looked right on one video" is not evidence. The eval turns prompt changes into a number that can go down. It runs outside the page and needs only User Story 1 output.

**Independent Test**: Run the eval command on the SAP sample and confirm it prints per-case and overall scores.

**Acceptance Scenarios**:

1. **Given** the SAP sample and its ground-truth table, **When** the eval runs, **Then** it pairs steps by the rule in FR-027a and prints step-count difference, timestamp agreement rate (ground-truth steps paired within 3 seconds), action match rate on the pairs, and check agreement rate for that case.
2. **Given** the ground-truth tables use the original video's clock, **When** moments are compared, **Then** the eval first subtracts the cut offset (10 s for the SAP demo clip, 14.6 s for the AI Studio clip).
3. **Given** both sample cases are available, **When** the eval runs on both, **Then** it prints an overall score as well as per-case scores.
4. **Given** the eval has run, **When** the maintainer opens the run's trace, **Then** the eval results are visible there too.

---

### User Story 6 - Trace a run end to end (Priority: P6)

A maintainer or judge filters the trace viewer by a run reference and sees the whole story of that run as one tree: the watching call, any rejected-and-retried outputs, then the row of parallel step checks, with token usage on each. If a run exceeds its model-call budget the trace shows that loudly.

**Why this priority**: Failures that vanish cannot be demonstrated or fixed. The trace is also the last 30 seconds of the stage demo.

**Independent Test**: Complete one run, filter the trace viewer by its run reference, and count the spans.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the trace viewer is filtered by its run reference and video name, **Then** one tree shows the watching call, each rejected output and retry, and one span per step check.
2. **Given** a run that exceeds its model-call budget, **When** the cap trips, **Then** the run stops, the trace carries an error-level event naming the cap, and the page shows the failure.

---

### Edge Cases

- A file that is not a video, or a video over 100 MB, is dropped: the page refuses it with a message and stays in the empty state.
- The watching system returns zero steps: the run is treated as a rule violation (an empty runbook is not a runbook) and retried, then fails visibly.
- A step's moment is given as MM:SS rather than seconds: it is accepted and converted. A moment past the video's end is rejected as a rule violation.
- Two steps share the same moment or a later step has an earlier moment: rejected as a rule violation.
- A check cannot complete (timeout, unusable answer after retries): the step shows "error", never "flagged", and never disappears.
- The call budget trips while checks are still running: steps without a result show "error", the run is marked over budget, and the trace records it.
- Two recordings are dropped from two browser tabs at once: each gets its own run and neither affects the other.
- The page is reloaded mid-run: the page returns to the empty state; the run keeps going on the server but the page does not resume it (past runs are out of scope).
- The status of an unknown run reference is requested: the page shows a not-found message rather than spinning forever.
- The recording has no narration: the runbook is still produced, with intent inferred from what happens on screen.

## Requirements *(mandatory)*

### Functional Requirements

#### Upload and run lifecycle

- **FR-001**: The page MUST accept one video recording by drag-and-drop or file picker, refusing files that are not video or exceed 100 MB with a visible message.
- **FR-002**: Accepting a recording MUST return a run reference immediately; all watching and checking happens in the background, and the page polls for status about every 2 seconds.
- **FR-003**: The uploaded recording MUST be playable in the page's video player as soon as the upload completes, before the runbook exists.
- **FR-004**: A status request for a run MUST return the runbook once it exists plus whichever step checks have completed so far, so the page can show partial progress.

#### Runbook content

- **FR-005**: A runbook MUST carry a title, the system the task was performed in, a list of prerequisites, an ordered list of steps, and a list of pitfalls.
- **FR-006**: Each step MUST carry a step number, the moment in the video in seconds, an action from exactly the set {click, type, select, navigate, wait, verify}, the on-screen target, an optional value entered or chosen, the screen the user was on, and the intent behind the step.
- **FR-007**: A step's moment MUST be accepted in either MM:SS or plain seconds and stored as seconds; a moment beyond the recording's duration MUST be rejected.
- **FR-008**: Step numbers MUST run contiguously from 1, moments MUST strictly increase step over step, and every target MUST name a concrete on-screen element rather than a generic phrase.
- **FR-009**: A runbook that breaks any rule in FR-005 to FR-008 MUST be rejected with a message naming the step and the rule, a corrected runbook MUST be requested a bounded number of times, and each rejection MUST be visible in the run's trace. An invalid runbook MUST never reach the page.
- **FR-010**: Noise in the recording (scrolling, mis-clicks, window moves, idle time) MUST NOT produce steps; narration, when present, MUST inform the intent of steps.
- **FR-011**: The runbook MUST be delivered to the page whole; steps are not streamed one at a time. Only check results arrive incrementally.

#### Step checks

- **FR-012**: Every step MUST be checked independently and the checks MUST run in parallel; a check depends only on its own step and the video around its own moment.
- **FR-013**: Each check MUST look at the video one second before the step's moment, at the moment, and one second after, together, because the exact moment often shows the state after the action rather than the action itself.
- **FR-014**: A check result MUST state whether the video matches the step, a confidence, and, when it does not match, a note explaining the disagreement.
- **FR-015**: Each step badge MUST be in exactly one of four states: checking, verified, flagged, error. Error (the check could not complete) MUST be visually distinct from flagged (the check disagreed). A step MUST never be dropped from the list because of its check.
- **FR-016**: Badges MUST update individually as their checks finish, without waiting for the others.
- **FR-017**: A hidden page parameter carrying a step number MUST alter that step's target before checks run, so a flagged step can be guaranteed during a demonstration. When the parameter is absent nothing is altered. When the runbook has fewer steps than the given number, nothing is altered and the footer says so. The README MUST describe this parameter plainly.

#### Page

- **FR-018**: The product MUST be a single page with the video player on the left, the runbook on the right, and a footer showing elapsed time, model token usage, and a link to the run's trace once the run completes.
- **FR-019**: The page MUST move through these states in order: empty with a drop zone; uploading; watching with the video already visible; runbook shown with every badge "checking"; badges flipping as checks return; done with the footer filled.
- **FR-020**: Clicking a step row MUST move the video player to that step's moment and pause it. Clicking a flagged row MUST also expand the row to show the check's note.
- **FR-021**: The page MUST offer a button that downloads the runbook, with current check statuses and notes, as a Markdown file.
- **FR-022**: The page MUST NOT include login, a list of past runs, step editing, or any mention of executors or other roadmap items.

#### Reliability and observability

- **FR-023**: Every call to the watching or checking model MUST have a timeout and a bounded number of retries.
- **FR-024**: Every run MUST count its model calls, across the watching call, its retries, and every check and check retry, and stop at a fixed cap of 60 calls; reaching the cap MUST mark the run as failed on the page and record an error-level event in the trace.
- **FR-025**: Every run MUST be traceable as one tree by run reference and video name, showing the watching call, each rejected output and retry, one span per step check, and token usage.
- **FR-026**: Model and trace credentials MUST be read from the environment and never stored in the repository.
- **FR-026a**: Uploaded recordings, runbooks, and check results MUST be kept on the server until cleared by hand. This feature performs no automatic deletion; the README MUST state this and list a retention policy as roadmap.

#### Evaluation and tests

- **FR-027**: One command MUST score the watching system against both ground-truth tables in `samples/README.md`, subtracting each clip's cut offset first, and print per-case and overall scores for step-count difference, action match rate, timestamp agreement within 3 seconds, and check agreement rate. The latest scores MUST be recorded in the project README.
- **FR-027a**: Pairing rule for the eval: for each ground-truth step, in table order, pair it with the nearest not-yet-paired produced step whose moment is within 3 seconds after offset correction; a ground-truth step with no such produced step stays unpaired. Timestamp agreement is the share of ground-truth steps that got a pair. Action match is the share of pairs whose actions are identical.
- **FR-027b**: Check agreement rate is the share of steps in an untampered run whose check verdict is "verified", taken from the run's own check results. The eval MUST NOT issue extra check calls to compute it; steps whose check ended in "error" count as not verified.
- **FR-028**: The default test run MUST complete without network access or credentials, using recorded runbook and check fixtures for the SAP sample; tests that reach the model MUST be opt-in and skip cleanly when credentials are absent.

### Key Entities

- **Run**: One processing of one uploaded recording. Identified by a run reference; progresses through uploaded, watching, checking, done, or failed; owns elapsed time, model-call count, and token usage.
- **Recording**: The uploaded video file, with its duration. Played back in the page and consulted by the checks.
- **Runbook**: The structured result of watching a recording: title, system, prerequisites, ordered steps, pitfalls.
- **Step**: One action within a runbook: number, moment in seconds, action, target, optional value, screen, intent. Belongs to exactly one runbook.
- **Step Check**: The verdict on one step: matches or not, confidence, optional note. Belongs to exactly one step; its badge state derives from whether it exists yet, its verdict, or its failure.
- **Ground-truth Case**: A sample recording plus its published step table and cut offset, used by the eval.
- **Eval Score**: The per-case and overall numbers produced by scoring a runbook against a ground-truth case.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the SAP sample, the produced runbook's step count is within 4 of the 14 ground-truth steps, at least 70% of the 14 ground-truth steps are paired with a produced step within 3 seconds after offset correction, and at least 70% of those pairs carry the same action.
- **SC-002**: From dropping a 2-minute recording to every badge reaching a terminal state takes under 3 minutes on the demo network.
- **SC-003**: The video is visible in the player and the "watching" state is shown within 5 seconds of dropping a 10 MB recording.
- **SC-004**: At the end of every run, 100% of steps show one of verified, flagged, or error; no step is missing and no badge is left at "checking".
- **SC-005**: With the demo tamper on, the tampered step ends "flagged" in at least 9 of 10 runs, and never "verified".
- **SC-006**: Clicking a step row leaves the player paused within half a second of the step's moment.
- **SC-007**: A run's rejected outputs, retries, and step checks are all visible under one trace filter for 100% of runs, and a run that hits its call cap is identifiable in the trace within one query.
- **SC-008**: The default test suite finishes in under 5 seconds with no network, and the eval command prints its scores in one invocation.
- **SC-009**: An exported Markdown file reproduces every step, status, and note shown on the page at the time of export.

## Assumptions

- Recordings are screen captures of roughly 720p, between 30 seconds and 3 minutes long, under 100 MB, in a common video container, with or without narration. The two sample clips are 118 s and 51 s at 5 to 7 MB.
- Ground-truth moments in `samples/README.md` are on the original video's clock; the SAP demo clip starts 10 s later and the AI Studio clip 14.6 s later, and the eval subtracts these offsets.
- The eval thresholds in SC-001 are opening targets chosen so a regression is visible, not a promise of accuracy; they can be tightened once the first scores are recorded.
- The per-run model-call cap of 60 (FR-024) covers a 20-step runbook with three watching attempts and every check retried twice, so a healthy run never trips it, while a runaway loop is stopped after a few dozen cheap calls.
- A single operator uses the page at a time on stage; two simultaneous runs must not interfere, but there is no user identity and no run history on the page. Files stay on the server until cleared by hand (FR-026a); the only recordings expected during the build are the two public sample clips.
- Reloading the page abandons the view of the current run; resuming a run from its reference is not required.
- The demo tamper is a documented demonstration aid, disclosed plainly if asked, not a hidden behaviour of normal runs.
- The watching model returns moments as MM:SS by habit; the system converts rather than instructs it out of that habit.
- Interpretation of "checking one moment": the check inspects the recording at three moments (one second before, at, and one second after the step's moment) in a single judgement, per the handoff decision. This is a product requirement, not an optimisation.

**Explicitly out of scope for this feature** (roadmap or follow-up; may appear in prose, never in the product):

- Letting the watching system request a closer look at any moment it chooses (a follow-up once this feature is complete and ahead of schedule).
- Packaging the watching instructions and that closer-look ability as a reusable capability (a small refactor, after the above).
- Executors that turn a runbook into automation, a model gateway, self-hosted models, queues, login, and multi-user support.
- Streaming steps into the page one at a time, editing steps on the page, and a list of past runs.

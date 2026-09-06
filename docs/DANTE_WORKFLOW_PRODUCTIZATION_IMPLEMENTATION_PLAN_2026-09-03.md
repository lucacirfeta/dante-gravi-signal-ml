---
phase: productization-v1
wave: 0-6
depends_on:
  - merge codex/dante-light-o4a-v1-parity into main
autonomous: false
status: IN_PROGRESS
---

# DANTE workflow productization v1 — implementation plan

## Objective

Turn the verified DANTE and corrected O4a engines into a reproducible,
resume-safe, locally operated workflow that a researcher can run without
manually coordinating more than a dozen scripts.

This increment wraps existing scientific components. It must not change
scores, populations, thresholds, null constructions, detector semantics, or
published artifacts. Any requested change to what is measured or how it is
validated is a separate scientific checkpoint and stops execution.

## Implementation checkpoint — 2026-09-05

| Phase | Status | Remaining acceptance |
|---|---|---|
| P1 | Implemented, regression-tested | Clean-clone/recovery acceptance in P5 |
| P2 | Implemented, regression-tested | Public end-to-end acceptance in P5 |
| P3 | Implemented, regression-tested | Public evidence graph acceptance in P5 |
| P4.1 | Approved and frozen (`176cf48`) | None |
| P4.2 | Read/control UI implemented; component and process tests | Packaged end-to-end CLI/UI parity in P5/P6 |
| P5 | Public smoke, fresh CPU install, and recovery matrix PASS | Packaged UI acceptance |
| P6 | Not started | Release receipt, human acceptance, separate paper branch |

Evidence and explicit limitations:
`docs/DANTE_WORKFLOW_UI_CHECKPOINT_2026-09-05.md`.
Clean-clone Plan/PREFLIGHT checks passed; the separate technical-smoke scope
was approved (it is not a complete scientific O4a rerun):
`docs/DANTE_WORKFLOW_CLEAN_CLONE_SCOPE_CHECKPOINT_2026-09-05.md`.
Public technical smoke evidence:
`docs/DANTE_WORKFLOW_PUBLIC_SMOKE_RESULT_2026-09-05.md`.
This is not a ready-to-use product release. Scientific O4a artifacts are not
rerun, promoted, or reinterpreted by this checkpoint.

## Historical baseline at plan creation

- corrected O4a regression: 115 tests pass;
- DANTE-Light operational verifier: all eight required gates pass;
- corrected O4a stages are individually runnable and verified;
- the current orchestrator stops after native rescore;
- thresholding, classification, taxonomy, coincidence, PEM, comparison, and
  reporting remain separate commands;
- `gui.py` is a legacy Gooey wrapper, Gooey is not installed by the standard
  environment, and the corrected workflow is not exposed through it;
- long-running execution currently depends on expert knowledge of WSL, CUDA,
  external roots, stage order, frozen contracts, and artifact verification.
- the IGWN thread #1544 closure draft has been versioned since commit
  `9f17206` and the user has completed the external forum post; it is retained
  as historical publication evidence, not an outstanding backlog item.

## Non-negotiable product contract

1. Scientific configs are immutable inputs. The UI never edits K, k,
   thresholds, reference populations, vetoes, bootstrap settings, or null
   definitions.
2. Every run has a content-addressed contract and a new run directory when
   code, config, representation, data manifest, or environment changes.
3. Resume is allowed only under the identical contract; otherwise fail closed.
4. Historical, failed, and superseded runs are preserved.
5. The UI may show infrastructure progress and expected cardinalities during a
   blinded run, but it does not reveal scores, classes, or candidate outcomes
   before verification completes.
6. Reports are generated only from verified artifacts and must declare missing
   or degraded inputs.
7. The UI process is disposable: closing the browser or UI must not stop or
   corrupt the workflow worker.
8. No productization result authorizes public real-time alerts, automatic
   adaptation, or an astrophysical/discovery claim.

## Completed branching and merge gate

The scientific milestone was merged into `main` as merge commit `d160007`.
Productization now proceeds on `codex/dante-workflow-productization-v1`.
The completed transition was:

1. commit the final IGWN copy and this plan on
   `codex/dante-light-o4a-v1-parity`;
2. run the merge-gate commands below;
3. review and merge through a PR or explicit fast-forward into `main`;
4. create `codex/dante-workflow-productization-v1` from the updated `main`;
5. never carry the untracked local `output/` directory into the merge.

Merge-gate verification:

```powershell
python -m pytest -q (Get-ChildItem tests/test_dante_o4a*.py).FullName
python -m pytest -q tests/test_regression_hard_constraints.py tests/test_patch_producer_context.py
python scripts/verify_dante_light_release.py --stage operational
git diff --check origin/main...HEAD
git status --short
```

Expected: all tests and the release verifier pass; only the user-owned
`output/` may remain untracked.

## Dependency graph

```text
Merge gate
   |
   v
P1 frozen workflow schema and state machine
   |
   +------> P2 O4a adapter and one-command CLI
   |                  |
   |                  v
   +------> P3 verifier and report contract
                      |
                      v
              P4 decoupled local UI
                      |
                      v
              P5 clean-clone reproduction
                      |
                      v
              P6 product release receipt
```

## P1 — Frozen workflow schema and durable state

Wave: 1

Depends on: merge gate

### Task P1.1 — Define a run-neutral workflow schema

Type: `auto`

Files:

- `config/dante_workflow_productization_v1.json`
- `src/dante_workflow/__init__.py`
- `src/dante_workflow/schema.py`
- `tests/test_dante_workflow_schema.py`

Action:

- define stages `PREFLIGHT`, `ACQUIRE`, `CALIBRATE`, `SCAN`, `COHORT`,
  `INDEX`, `NATIVE_CALIBRATION`, `RESCORE`, `THRESHOLDS`, `CLASSIFY`,
  `TAXONOMY`, `COINCIDENCE`, `PEM`, `COMPARE`, `REPORT`;
- require `NATIVE_CALIBRATION` to depend on both `COHORT` and the consumed
  window manifest emitted by `INDEX`, so its frozen 128 s exclusion guard can
  reject overlap with the index population before rescoring;
- encode dependencies, required inputs, expected outputs, verifier command,
  outcome-visibility policy, and resumability for each stage;
- reference frozen scientific configs by path and SHA-256 rather than copying
  their values;
- reject unknown fields and missing digests.

Verify:

```powershell
python -m pytest -q tests/test_dante_workflow_schema.py
```

Done when malformed or scientifically incomplete workflow specs fail closed
and the frozen O4a spec validates without duplicating a scientific constant.

Scientific-stage dependency detail:

```text
PREFLIGHT -> ACQUIRE -> CALIBRATE -> SCAN -> COHORT
                                               |-> INDEX -------------------|
                                               |       |                    |
                                               |       v                    v
                                               |-> NATIVE_CALIBRATION -> RESCORE
                                                                        |
                                                                        v
THRESHOLDS -> CLASSIFY -> TAXONOMY -> COINCIDENCE -> PEM -> COMPARE -> REPORT
```

`NATIVE_CALIBRATION` consumes only the verified index window manifest needed
for the frozen overlap guard; it does not inspect index outcomes. `RESCORE`
requires verified outputs from both branches.

### Task P1.2 — Implement an append-only workflow ledger

Type: `tdd`

Files:

- `src/dante_workflow/state.py`
- `tests/test_dante_workflow_state.py`

Action:

- persist run identity, contract digest, stage attempts, process identity,
  timestamps, exit status, artifact paths, hashes, and verifier verdicts;
- use atomic writes plus an append-only attempt ledger;
- prevent concurrent duplicate execution of the same run key;
- allow recovery after worker or UI termination without rewriting completed
  evidence.

Verify:

```powershell
python -m pytest -q tests/test_dante_workflow_state.py
```

Done when forced termination and restart resume at the first incomplete stage,
while a changed contract is rejected.

## P2 — One-command orchestrator and corrected O4a adapter

Wave: 2

Depends on: P1

### Task P2.1 — Add a stage adapter boundary

Type: `auto`

Files:

- `src/dante_workflow/adapters/base.py`
- `src/dante_workflow/adapters/o4a_corrected.py`
- `tests/test_dante_workflow_o4a_adapter.py`

Action:

- wrap the existing corrected O4a run and verify functions without changing
  their implementations;
- cover every stage through final comparison and report generation;
- translate only paths, process status, and artifact receipts;
- never translate or recompute a score, class, threshold, or population.

Verify:

```powershell
python -m pytest -q tests/test_dante_workflow_o4a_adapter.py
```

Done when adapter-produced commands and digests match the existing CLIs for
all stages.

### Task P2.2 — Implement the workflow CLI

Type: `auto`

Files:

- `src/dante_workflow/orchestrator.py`
- `scripts/run_dante_workflow.py`
- `tests/test_dante_workflow_orchestrator.py`

Action:

- expose `plan`, `preflight`, `run`, `resume`, `status`, `verify`, and `report`;
- support `--through-stage` and an explicit single-stage repair mode without
  bypassing dependencies;
- print a stable machine-readable JSON status in addition to concise human
  output;
- run workers independently of any future UI process.

Verify:

```powershell
python -m pytest -q tests/test_dante_workflow_orchestrator.py
python scripts/run_dante_workflow.py plan --config config/dante_workflow_productization_v1.json
```

Done when one command can plan and execute the frozen stage DAG, and repeated
execution is idempotent.

## P3 — Verification and report boundary

Wave: 2

Depends on: P1

### Task P3.1 — Aggregate verifier receipts without copying metrics

Type: `auto`

Files:

- `src/dante_workflow/verification.py`
- `scripts/verify_dante_workflow.py`
- `tests/test_dante_workflow_verification.py`

Action:

- execute each existing stage verifier;
- verify artifact hashes and cardinality accounting;
- emit one signed-by-content release receipt referencing source artifacts;
- fail the workflow if any required stage is absent, stale, superseded, or
  inconsistent.

Verify:

```powershell
python -m pytest -q tests/test_dante_workflow_verification.py
```

Done when a valid artifact graph passes and every injected missing, altered,
or cross-run artifact fails.

### Task P3.2 — Build a derived human report

Type: `auto`

Files:

- `src/dante_workflow/reporting.py`
- `tests/test_dante_workflow_reporting.py`

Action:

- render run status, provenance, stage timings, exclusions, verification
  verdicts, and links to existing scientific outputs;
- read metrics from receipts instead of transcribing them;
- label incomplete, diagnostic, non-global, and non-operational results
  explicitly.

Verify:

```powershell
python -m pytest -q tests/test_dante_workflow_reporting.py
```

Done when the report cannot be generated as `PASS` from an unverified run.

## P4 — Decoupled local UI

Wave: 3

Depends on: P2 and P3

### Task P4.1 — Freeze the UI framework after a bounded spike

Type: `checkpoint:decision`

Files:

- `docs/DANTE_WORKFLOW_UI_DECISION.md`
- `requirements-ui.txt`

Action:

- compare a local server-rendered web UI, Streamlit, and PySide6 against:
  WSL/Windows support, worker-process independence, resumability, packaging,
  file selection, log streaming, accessibility, and testability;
- prefer a local web UI backed by the persistent orchestrator unless the spike
  shows a concrete blocker;
- keep all UI dependencies optional and outside the scientific runtime lock.

Verify: the decision document contains a runnable spike, measured startup and
reconnect behavior, and a selected framework with explicit rejected options.

Done when framework choice is evidence-backed and does not couple job lifetime
to a browser session.

### Task P4.2 — Implement the read/control UI

Type: `auto`

Files:

- `src/dante_workflow/ui/app.py`
- `src/dante_workflow/ui/views.py`
- `src/dante_workflow/ui/templates/`
- `tests/test_dante_workflow_ui.py`

Action:

- provide project/cache/raw-data selectors, hardware and dependency preflight,
  stage DAG, start/resume/stop controls, logs, artifact browser, verification
  verdicts, and final-report access;
- show scientific configs as read-only digests;
- hide outcome fields until their verifier passes;
- never execute scientific logic inside the UI process.

Verify:

```powershell
python -m pytest -q tests/test_dante_workflow_ui.py
```

Done when a user can launch, disconnect, reconnect, resume, verify, and open a
report without entering a scientific parameter manually.

## P5 — Clean-clone and failure-recovery reproduction

Wave: 4

Depends on: P4

### Task P5.1 — Add a bounded public smoke workflow

Type: `auto`

Files:

- `config/dante_workflow_public_smoke_v1.json`
- `scripts/run_dante_workflow_clean_clone.py`
- `tests/test_dante_workflow_clean_clone.py`
- `docs/DANTE_WORKFLOW_QUICKSTART.md`

Action:

- use public/downloadable inputs and a bounded runtime;
- exercise preflight, acquisition, scoring, resume, verification, and report;
- document CPU and CUDA paths;
- keep the smoke result separate from full-run scientific evidence.

Verify:

```powershell
python -m pytest -q tests/test_dante_workflow_clean_clone.py
python scripts/run_dante_workflow_clean_clone.py --mode local
```

Done when a clean clone can produce the expected receipt without private
paths, pre-existing caches, or manual stage coordination.

### Task P5.2 — Test interruption, disk pressure, and dependency failures

Type: `auto`

Files:

- `tests/test_dante_workflow_recovery.py`
- `tests/fixtures/dante_workflow_failures/`

Action:

- inject worker termination, stale locks, unavailable network, missing CUDA,
  insufficient disk, corrupted artifacts, and changed contracts;
- require recoverable states to resume and integrity failures to stop.

Verify:

```powershell
python -m pytest -q tests/test_dante_workflow_recovery.py
```

Done when every injected failure has an explicit, tested, user-facing state.

## P6 — Product release and paper-readiness receipt

Wave: 5

Depends on: P5

### Task P6.1 — Verify the packaged user path

Type: `checkpoint:human-verify`

Files:

- `artifacts/dante_workflow/productization_v1_release.json`
- `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md`

Action:

- run the clean-clone workflow through both CLI and UI;
- confirm exact artifact equality between interfaces;
- record installation, startup, preflight, interruption/resume, verification,
  and report evidence;
- record limitations and exclude discovery/real-time claims.

Verify:

```powershell
python scripts/verify_dante_workflow.py --release artifacts/dante_workflow/productization_v1_release.json
```

Done when the release receipt passes and a human confirms that no expert-only
path or undocumented choice is required for the bounded workflow.

### Task P6.2 — Open the architecture-paper branch

Type: `checkpoint:human-action`

Action: only after P6.1 passes, open a separate paper branch from the released
productization commit. The paper must cite the receipt and public reproduction
path rather than describe an unverified planned interface.

Done when the architecture manuscript begins from a tagged, reproducible
software state.

## Final success criteria

- one content-addressed config starts the entire bounded workflow;
- CLI and UI use the same orchestrator and produce identical artifact hashes;
- killing the UI does not affect the worker;
- interruption and resume do not duplicate identities or overwrite evidence;
- scientific configs are read-only and hash-pinned;
- outcomes remain hidden until verification;
- a clean clone completes the smoke workflow and produces a verified report;
- the architecture paper starts only after the productization receipt passes.

---
phase: 08-multi-run-productization
plan: 01
verified: 2026-09-30
status: passed
scope: administrative_foundation_only
score: 5/5
is_re_verification: false
overall_multi_run_productization_complete: false
---

# Verification 08.01: administrative boundary only

## Observable truths

| Truth | Status | Evidence |
| --- | --- | --- |
| Public release membership is distinct from executable science | VERIFIED | Dated registry has eight runs; V1 data-only profiles return BLOCKED, never READY |
| H1/L1 and available V1 are explicitly selectable | VERIFIED | Availability tests cover O2/O3a/O3b/O4b V1 and reject S5/S6/O1/O4a V1 |
| Unknown or unbound profiles do not fall back or create state | VERIFIED | CLI and UI adapter-rejection tests assert no cache/ledger; unknown runs and mismatched config fail |
| Frozen O4a command/run identity is unchanged for equivalent selection | VERIFIED | Real legacy/explicit CLI plans and package-module/checkout parity; existing adapter/UI regressions |
| Registry and parent bindings fail closed | VERIFIED | Canonical seal, parent drift, duplicate JSON/schema/run, path escape and method detector-scope tests |

## Artifacts and wiring

| Artifact | Exists | Substantive | Wired |
| --- | --- | --- | --- |
| config/dante_workflow_runs_v1.json | Yes | Official metadata snapshot plus parent bindings | Loaded by shared CLI |
| src/dante_workflow/run_profiles.py | Yes | Strict parser, parent validation, availability and selection | Both administrative commands and pre-ledger selection |
| src/dante_workflow/adapters/__init__.py | Yes | Exact implemented-adapter dispatch, no fallback | CLI and existing full UI through from_spec |
| tests/test_dante_workflow_run_profiles.py | Yes | 42 positive/negative tests including real entry points | Complete controller regression |

## Observed verification

- WSL complete controller suite: **167 passed, 1 skipped**, observed OS exit 0,
  93.37 seconds. Skip is the explicitly Windows-only no-signal regression.
- Native Windows complete controller suite: **168 passed**, observed OS exit 0,
  32.28 seconds; includes that Windows liveness check.
- Native profile/process subset: **48 passed**, observed OS exit 0, 1.34 seconds.
- Post-feature-freeze native profile tests: **42 passed**, observed OS exit 0,
  1.00 second; new source identity remains stable within the parity test.
- Ruff lint over the modified controller/adapters and new tests: PASS.
- Ruff format check over the new profile module/tests and edited CLI: PASS.
  Existing older adapter/UI files were not wholesale reformatted.
- Native registry load and O4a/V1-selection checks: observed OS exit 0; exact
  registry digest b1d874abd7c0c35ca97ee9dc5a19bacd63fe210c23ab9817119d77d4180d1da0.
- Native real CLI `run-readiness O3a/V1`: structured blocked report, returned
  code 2 explicitly observed, no scientific execution or live-coverage claim.
- `git diff --check`: PASS. Windows Git reports no modifications to existing
  scientific config/scripts/src/dante_light/data files. Source freeze for the
  administrative feature is local commit **8d29136**.

This is not a new production replay, a fresh wheel installation, numerical
Virgo validation, or new acceptance of the complete GUI on another machine.

## Qualification and investigation

Earlier invocations include the expected TDD import failure, a source-bound
plan mismatch caused by formatting during that test, and two unchanged
detached-UI launch deadline failures (one full run, one isolated). The latest
complete WSL and Windows suites pass without changing/skipping the timeout.
The intermittent timing issue remains documented in 08-01-DEBUG.md; no claim
that its root cause was repaired. WSL/Windows Git line-ending interpretations
differ over historical files; no source normalization or Git-setting change.

## Remaining overall-productization gaps

- Complete O3a workflow adapter/receipt graph and multi-run GUI selection.
- Exact-interval data/DQ/context preflight and clean-install bounded replay.
- Approved per-run/detector population/reference/calibration contracts for
  newly enabled runs and V1, with separate physical/network gates.
- Explicit approval of any V1 pairwise/network null, aggregation and decision
  rule; old H1/L1 bipartite thresholds cannot be transplanted.
- Clean-checkout source-identity/launch-duration qualification before a portable
  multi-run release claim.

No enabled placeholder adapters, copied scientific thresholds or silent
unsupported-stage negatives were found. **The first administrative increment
passes; the user's full all-run pipeline objective is not yet achieved.**

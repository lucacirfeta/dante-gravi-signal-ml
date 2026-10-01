---
phase: 08-multi-run-productization
plan: 04
verified: 2026-10-01
status: passed
scope: native_interface_synthetic_only
score: 5/5
is_re_verification: false
overall_multi_run_productization_complete: false
---

# Verification 08.04: implemented interface, not productive O3a replay

| Required truth | Status | Evidence |
| --- | --- | --- |
| Native O3a CLI selectors and path-only arguments preserved | VERIFIED | 18 stage/action parameter cases, source-selector inventory and AST CONTRACT_REL comparison; all nine actual script interfaces mapped |
| Native calibration remains distinct | VERIFIED | Exact freeze selector CLI, no initial hash selector, no rescore/threshold substitution |
| Nested cohort evidence binds sealed exact ledger bytes | VERIFIED | Correct actual payload shape; seal/PASS/hash/basename/symlink checks, no ledger row parsing; index input binding uses same bytes |
| Scope/config/unsupported commands fail before state | VERIFIED | V1/O4a/schema/adapter/stage/config and verifier-prefix/missing-script negatives |
| Complete workflow activation remains blocked | VERIFIED | Existing factory/from_spec reject native adapter before cache creation; no registry/config binding changed |

## Wiring

- New substantive StageAdapter implements actual command and receipt methods,
  not no-op success. Public production dispatch is intentionally unwired/gated.
- Synthetic test explicitly constructs it in WorkflowOrchestrator, adopts all
  fixture stages, records exact cohort/index receipts and passes verify_workflow
  with a fake runner. Verifier invoked twice per fixture stage, run never invoked.
- This demonstrates administrative receipt/control wiring only, not numeric
  correctness, actual historical adoption, coverage or scientific significance.

## Observed checks

- Windows full controller: **269 PASS**, OS exit 0, 43.07s.
- WSL full controller: **268 PASS, 1 Windows-only skip**, OS exit 0, 108.38s.
- Post-source-freeze adapter: **45 PASS**, OS exit 0, 2.01s.
- Ruff lint/format: PASS on new module/tests using existing WSL environment.
- Source freeze `138ed7c`. Scientific config/scripts/src/dante_light/data and
  public adapter factory unchanged. Existing EOL/launch qualifications retained.
- Initial TDD import error expected; fixture-only upstream declaration and test
  API assumptions corrected against primary source, no production/schema edits.

Plan-check scope covers phase 8's existing-run binding increment: two complete
tasks, wave 4 depends on completed 08-03, explicit wiring test, no new numerical
method. Warning: full phase 8 goal remains open; this plan deliberately does not
promise an enabled O3a graph or final integration confirmation.

## Remaining overall gaps

- Existing initial acquisition/acceptance standalone verification binding.
- Non-mutating adoption of historical evidence: native --verify paths can write
  compact/summary artifacts, including transitive parent checks.
- Exact approved applicable production graph, all parent receipts/configuration
  bindings and existing per-stage preflights; no external fixture bypass.
- Independent bounded real replay/clean install, CLI/UI selection, other run/V1
  scientific contracts and network validation. No shortcut from synthetic PASS.

No scientific process/outcome/old-artifact mutation, push or release. O3a's
completed diagnostic study is unchanged; software productization continues.

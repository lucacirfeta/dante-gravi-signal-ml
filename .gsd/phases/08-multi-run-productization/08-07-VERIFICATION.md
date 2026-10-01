---
phase: 08-multi-run-productization
plan: 07
verified: 2026-10-01
status: passed
scope: existing_scan_cohort_gate_read_only
score: 5/5
overall_multi_run_productization_complete: false
---

# Verification 08.07: first native dependency chain only

| Required truth | Empirical evidence |
| --- | --- |
| Immutable DB reads do not create transaction sidecars | Real temporary checkpointed WAL database; legacy mode=ro explicitly creates WAL/SHM; immutable reads preserve header/file bytes/mtimes/inventory; SQL deletion rejected; existing/new sidecars and changed signature fail |
| Scan retains existing deterministic checks | Exact full summary parity with legacy verifier on fixtures; equality at threshold remains noncandidate; population, encoding, candidate tensors, metadata identity and raw-frame provenance negatives |
| Cohort retains existing selection/context gates | Exact legacy result parity on fixtures; inclusive guard, exact separation boundary, duplicate/count/candidate/quality/source/ledger-shard negatives; file/value SHA, shape, dtype and finite checks; actual inherited context-source coverage function |
| Inputs/sources and bounded claims are explicit | Fourteen source bindings, hashes/seals and rehash-before-receipt; changed helper, mid-read input and unsafe proposal/context negatives; current-runtime gate retained; full-workflow/scoring/fetch flags false |
| No history writes or public activation | Fixture success/failure snapshots; forbidden productive/writer/scoring/network/legacy-verifier hooks; stdout-only actual CLI functions; unsupported stage/mutation flag rejection; controller regressions/public block intact |

## Observed runs

- Final pre-freeze Windows target: **89 PASS**, OS exit 0, 27.47s.
- Complete Windows workflow: **418 PASS**, OS exit 0, 83.01s.
- WSL workflow + primary scan + native cohort + PatchProducer:
  **448 PASS, one Windows-only skip, 11 upstream warnings**, OS exit 0, 170.29s.
- Earlier 74-test targets on Windows/WSL passed, but are superseded by the
  final expanded tests included in these regressions.
- Ruff lint PASS across workflow modules/tests/new CLI; new-file format PASS.
- Local source freeze **57a99dc**. New module, CLI and test bytes match committed
  blobs without filters. `git diff --exit-code HEAD -- src/dante_light config`
  and old scan/cohort runner paths shows no scientific edit.
- Post-freeze Windows target: **89 PASS**, observed OS exit 0, 27.53s.
  No exit code or completion is inferred from log text.

Fixture-only loader substitutions include validated scientific contracts,
population iterator and frozen-runtime capture; they do not exercise a fresh
production GPU comparison. Existing metadata/preflight/frame/shard/context-source
functions remain real. Separate actual local contract/source checks do not open
history. Legacy parity invocation is expressly limited to temporary fixtures;
their transaction files are never confused with historical evidence.

Negative inputs are deliberately repinned/resealed only in synthetic fixtures.
CLI successes run actual entry functions in-process; subprocess argument rejection
has observed OS exit 2. No real historical CLI, raw/encoder numerical replay,
clean-install scientific acceptance or second fetch is claimed. Current-runtime
failure propagates without new historical artifacts. File-byte/mtime checks do
not assert exclusive access against another process; quiescent adoption remains
a subsequent gate. Existing EOL qualifications are not normalized or bypassed.

## Open overall gates

Read-only index/calibration/rescore and later native dependency paths; complete
profile/preflight/parent adoption binding; process/quiescence verification and
bounded real replay; initial raw numerical replay where scientifically required;
CLI/UI public multi-run selection and independent other-run/V1/network contracts.
These are readiness gates, not an error in this tested bounded increment.
No hash-only substitute for numerical scientific validation or outcome promotion.

---
phase: 08-multi-run-productization
plan: 09
completed: 2026-10-01
scope: native_calibration_rescore_retained_evidence_only
source_freeze: 2a15b32
overall_multi_run_productization_complete: false
---

# Summary 08.09: calibration/rescore read-only gates

Approved A continues with separate `o3a_score_verification.py` and repository CLI
`verify_dante_o3a_score_evidence.py`; 77 new tests. No historical scientific
source/config/runner, earlier read-only module or public registry change.

Calibration reconstructs the exact frozen evenly spaced/context-fallback
selection and audit, preserving detector-local guards and bootstrap identities.
RESCORE reconstructs ordered work and the entire preflight in memory, replacing
the old verifier's productive manifest/preflight writes. Existing pure work,
stored CUDA receipt, score-shard and grouped-ledger validators remain in use.
Explicit INDEX/COHORT/SCAN roots use the approved immutable SQLite parent chain.

Guarded inputs, seals, locks/failures/partials/sidecars, exact identity/finite/
float32-hex checks, empty cache and final input/source rehash fail closed. Twenty
three local source bindings; stdout-only receipts deny fresh score/encoder/
preprocessing/fetch/fit/bootstrap replay and full scientific-workflow PASS.

## Verification

- Windows workflow: **567 PASS**, observed OS exit 0, 168.88s.
- WSL workflow plus old primary/cohort/INDEX/native calibration/rescore/
  rescore-preflight/PatchProducer: **618 PASS, one Windows-only skip,
  11 upstream warnings**, observed OS exit 0, 237.09s.
- Ruff lint/format PASS; three new Python files byte-identical to Git at
  local source freeze **2a15b32**. Post-freeze target recorded in VERIFICATION.
- Post-freeze Windows target: **77 PASS**, observed OS exit 0, 27.38s.
- Fixture-only parity and byte/mtime/inventory snapshots cover both successful
  and refused reads. New fixtures isolate the already-tested INDEX parent;
  actual prior parent integration remains in unchanged regression suites.
- Real scientific contracts load unchanged in WSL. Native Windows calibration
  reconstructs `execution/root_wsl` with backslashes and is deliberately refused;
  all other fields match. RESCORE inherits the earlier INDEX refusal. No hash,
  normalization, contract or scientific-source exception was introduced.

No historical invocation, new outcome, dependency install, public activation,
push or release. User untracked artifacts/output and O3a diagnostic closure
preserved. Quiescence and independent fresh scientific replay are not established.

## Next

Separate read-only thresholds/classification gates, then later native dependency
gates; full profile/preflight adoption and quiescent bounded real clean-install
scientific replay. Other-run/Virgo readiness remains open. Stop for any new
scientific/structural choice or provenance mismatch.

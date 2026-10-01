---
phase: 08-multi-run-productization
plan: 09
verified: 2026-10-01
status: passed_with_platform_and_fixture_qualifications
scope: native_calibration_rescore_retained_evidence_only
score: 5/5
overall_multi_run_productization_complete: false
---

# Verification 08.09: calibration identities and stored RESCORE

| Required truth | Empirical evidence |
| --- | --- |
| Explicit read-only parents | Frozen 08.08 INDEX gate with primary/cohort/index roots; immutable SQLite accessors; parent wiring asserted and unchanged parent integration regressions retained |
| Preserved calibration selection | Actual pure frozen selector/context builders; exact rows/audit and legacy result parity on fixtures; candidate/index guards and detector-local bootstrap identities unchanged |
| RESCORE without productive preflight | Entire ordered work/manifest/preflight reconstruction in memory; full fixture preflight parity with legacy implementation; stored CUDA/shards/grouped outputs pass unchanged pure validators |
| Input/source integrity and narrow receipt | Twenty three local source bindings, guarded paths, seals, final rehash and scoped stdout; no fresh scoring, encoder, fit, fetch, bootstrap or full-workflow claim |
| History and scientific method unchanged | Success/failure byte/mtime/inventory snapshots, real CLI fixture calls and mutation-option refusal; Git source-byte audit; no old source/config/history/public dispatch mutation |

## Observed runs

- Early Windows target: 71 PASS, exit 0, 26.95s; superseded by expanded 77 tests.
- Early WSL target plus old calibration/rescore/preflight: 70 PASS, 11 upstream
  warnings, exit 0, 45.69s; superseded by final expanded regressions.
- Final Windows complete workflow: **567 PASS**, observed OS exit 0, 168.88s.
- Final WSL workflow plus primary scan/native cohort/INDEX/native calibration/
  rescore/rescore-preflight/PatchProducer: **618 PASS, one Windows-only skip,
  11 upstream warnings**, observed OS exit 0, 237.09s.
- Ruff workflow/test/new-CLI lint and new-file format PASS, observed exit 0.
- Local source freeze **2a15b32**; module, CLI and tests match Git blobs with
  `hash-object --no-filters`. No old scientific source/config/script or earlier
  read-only verifier tracked diff. Existing EOL qualifications remain intact.
- Post-freeze Windows target: **77 PASS**, observed OS exit 0, 27.38s.

## Diagnosed refusal, not bypassed

The initial Windows target returned exit 1: 51 PASS, one FAIL in 19.28s.
The real legacy calibration contract loader refused reconstructed host paths.
Diagnosis found only `execution/root_wsl` using backslashes rather than `/mnt/e/`
syntax, with consequent digest change; every other field was identical. Tests
explicitly assert that unchanged Windows refusal. RESCORE's actual loader also
inherits the previously diagnosed INDEX Windows path refusal. Actual unchanged
calibration and RESCORE contract loaders pass in WSL without historical access.
No normalization, digest exception, scientific source edit or gate weakening.
Windows unit PASS is not native Windows production verification certification.

## Fixture and scientific evidence boundary

Real temporary checkpointed WAL-mode SQLite, strict JSON ledgers and shard files
exercise frozen pure selectors, context builders, work assembly and retained
score validators. Runtime/contracts are scaled or substituted in fixtures only.
The upstream INDEX gate alone is isolated in this new suite; roots and tracked
references are asserted. Earlier INDEX/COHORT/SCAN tests run unchanged, but this
increment does not establish real end-to-end historical or clean-install adoption.

Legacy calibration parity uses original selection with immutable query accessors
and an isolated parent in that test only. Legacy productive RESCORE preflight
writes only within a temporary fixture; already-verified work assembly is
substituted for that parity invocation. Its full preflight matches reconstruction.
Legacy stored-score validation uses that retained preflight substituted only in
the parity test. New implementation never calls or monkeypatches productive
preflight or historical verifier entry points. Immutable scoring identity query
parity is also tested on valid and invalid temporary standalone SQLite databases.

Resealed/repinned semantic negatives exist only in fixtures. Missing/altered
files, unsafe paths, locks, failures, partials, sidecars, runtime/source/parent/
manifest/identity/CUDA/shard/output mismatch and mid-read mutation are refused.
Actual CLI success/failure calls preserve snapshots; mutation options have
observed subprocess exit 2. No historical dataset was invoked or changed.

Retained CUDA receipt checks are not current CUDA measurements; finite score and
float32-hex consistency are not independent raw/encoder score replay. No sensor
safety, physical cause, new outcome, full pipeline or multi-run scientific PASS.
Quiescence, remaining native gates, complete profile/preflight binding and bounded
real clean-install replay remain open. No public activation, push or release.

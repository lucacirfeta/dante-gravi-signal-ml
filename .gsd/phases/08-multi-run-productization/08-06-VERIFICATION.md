---
phase: 08-multi-run-productization
plan: 06
verified: 2026-10-01
status: passed
scope: historical_initial_evidence_read_only
score: 5/5
overall_multi_run_productization_complete: false
---

# Verification 08.06: scoped initial checks only

| Required truth | Evidence |
| --- | --- |
| Actual raw-file integrity is bound to frozen historical evidence | Scaled real HDF5 fixtures; inherited metadata checks; streamed SHA; exact plan/run/parent/preflight/ledger/manifest and summary reconstruction; altered bytes, missing/partial files fail |
| All planned initial acceptance shards reconstruct exact pinned output | Existing block identity/validator, score finite/float32 encoding checks, full shard set and exact ledger/summary/flags; missing/extra/duplicate/altered shards rejected |
| Success/failure do not change historical evidence or call productive code | Complete fixture file-byte/mtime snapshots, forbidden writer/scoring/network hooks, CLI error produces no historical failure file; stdout-only interface |
| Receipt levels and executed sources are explicit | INTEGRITY versus RECONSTRUCTION, canonical seal, eleven source bindings; selected/transitive loaded-helper mismatch negatives; all full-workflow/raw-score/encoder/threshold/fetch flags false |
| Public activation remains blocked | No factory/registry/profile production binding changed; full controller regressions green; existing O3a block remains |

## Observed execution

- Complete Windows workflow tests: **329 PASS**, observed OS exit 0, 53.52s.
- WSL workflow plus existing initial-stage/PatchProducer regression:
  **367 PASS, one Windows-only skip, 11 GWPy/Matplotlib upstream warnings**,
  observed OS exit 0, 149.94s.
- Final targeted WSL new-module suite: **60 PASS**, observed OS exit 0, 13.54s.
- Ruff lint PASS across workflow modules/tests and new CLI; format PASS for
  the three new Python files.
- Source freeze **9d8a51a**. All three new files are byte-identical to their
  committed Git blobs (`git hash-object --no-filters` equals `HEAD:path`).
- Post-freeze targeted Windows suite: **60 PASS**, observed OS exit 0, 15.90s.
  No full-regression count is inferred from a receipt hash.

Synthetic fixture loaders deliberately scale production geometry for unit tests.
All existing block/HDF5 validators, exact JSONL reconstruction, source-file
checks and canonical seals remain real. Production geometry is never reconfigured.
CLI success tests invoke the actual new scoped functions in-process; subprocess
tests observe OS exit 2 for invalid CLI arguments. This is not an end-to-end
historical CLI execution or a clean-install scientific workflow run.

Source inspection verifies the wrapper does not call old productive entry points
or the known mutating native verifiers. Small evidence inputs are rehashed before
receipt emission. Historical quiescence/exclusive access is not proven by these
unit tests; eventual adoption requires its own unchanged-input/process gate.

## Open overall gates

Native standalone/transitive non-mutating verifiers; initial raw numerical
replay where required by scientific adoption; complete production applicability
and parent/preflight bindings; bounded real replay and clean-install acceptance;
CLI/UI multi-run selection and separate new-run/V1 scientific/network contracts.
No source-hash-only scientific PASS, tuning, pooling or outcome promotion.

Inherited scientific sources/configs/scripts/data and historical evidence remain
unchanged. Existing EOL and UI timing qualifications remain. No push/release.

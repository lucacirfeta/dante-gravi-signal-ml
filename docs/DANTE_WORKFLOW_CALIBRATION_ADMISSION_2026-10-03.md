# Explicit calibration numerical-parity admission — 2026-10-03

## Author decision and bounded result

Author `procedi` explicitly accepts option A after08.27: a NEW provenance
receipt binds regenerated containers to exactly equal historical numerical
sample SHA, without rewriting old container hashes or receipts. No tolerance,
new scientific selection, score/threshold/calibration fit or runtime change.

New module `src/dante_workflow/calibration_admission.py`, explicit creation/
verification script and opt-in CLI. All10 recovery-pinned source files remain
unchanged (including calibration_inputs.py); new policy never edits the old
acquisition manifest or recovery plan/summary/verification/contexts/frames.
Sourcefreeze58f7489; exact-parent policy correction70b0a15 before admission.

Real new external receipt:

`E:/dante_cache/dante_light/o4a_corrected_v2/calibration_admission/admission_20261003_v1.json`

- File SHA `b17d6388ff888d2b0bd332e1c993b56e83ac0c62d53e62a54d0f01e3d09de6f1`.
- Seal `5910f65a601099ba6bc34d012ad8706ff6b7b9fc47b31875178bf7be84bdf5d3`.
- Policy `config/dante_workflow_calibration_admission_v1.json`, file SHA
  `1869659f1a06a0fd23d66400491e2bb25c6fcb5f5dbb9613baa1231b792c6f26`.
- Creation WSL OSexit0,exec93171; standalone verification OSexit0,exec71902,
  explicit `ADMISSION_VERIFY_OS_EXIT=0`. Verifier independently rebuilds receipt.
- Separate real CLI check exec67362 OSexit0,explicit `CALIBRATION_CLI_OS_EXIT=0`;
  same pinned receipt and scoped PASS,no workflow ledger or productive job.
- All28 intervals,18H1+10L1,exact raw numerical SHA;0 historical container matches.
  Both old and new container SHA recorded, never claimed byte-identical.
- Frozen39971 calibration identities remain19715H1+20256L1 and84 historical
  GPS-input HDF5;28 manifest gaps covered by explicitly pinned admission receipt.
- Status `PASS_CALIBRATION_DECLARED_INPUTS_ONLY`,no blockers; recovered-context
  numerical parity checked and declared coverage true. Full-population raw
  measurement, historical full-row digest,native-calibration/runtime equivalence,
  writer exclusion and scientific_execution_ready all remain false.

Old receipt SHA remains
`4f0732510604583e8a02827d3172e337cedd714ed3e8d3b86dfaac6c17b7fe78`.
Recovery plan03a0e7d9...,summaryb1fddd1a...,verificationc03856b9... unchanged.
Existing scientific-source EOL qualifications remain; no normalization/bypass.

## Admission checks and explicit CLI

SHA-pinned versioned policy requires exact parent including its seal field,
all recovery evidence file SHA and exact missing-interval identity set from
the unmodified score-blind reader. Offline frozen verifier rechecks retained
full-frame MD5/SHA and independently sliced native HDF5 versus regenerated
context samples. New receipt records old/new raw and container SHA, size,
dtype, grid/count, sources and parents. Independent verifier rebuilds the
entire receipt and rejects any resealed,missing,extra,altered/unpinned evidence.
Receipt cannot be created in checkout/recovery,overwritten or auto-resumed.
Replay is NOT a second source fetch,version-label proof or new DQ/sensor test.

CLI opt-in example (WSL,explicit paths):

```text
python -B -m src.dante_workflow.cli calibration-readiness
  --observing-run O4a --detectors H1 L1
  --recovery-admission /mnt/e/dante_cache/dante_light/o4a_corrected_v2/calibration_admission/admission_20261003_v1.json
  --recovery-admission-sha256 b17d6388ff888d2b0bd332e1c993b56e83ac0c62d53e62a54d0f01e3d09de6f1
```

Without explicit admission path+SHA,the old behavior remains blocked;mixing
historical acquisition and recovery admission arguments is refused. No workflow
ledger,productive worker,state adoption,release or registry activation occurs.

## Tests and diagnosed first attempt

Final8-file targeted suite Windows223 PASS/13.65s,WSL223 PASS/54.58s,observed
OSexit0;WSL11 upstream GWPy/matplotlib warnings. New27 admission tests include
immutable history,no overwrite,exact parent/policy,pinned receipt,resealed false
fields,source/frame/context drift,dirty run and CLI wiring. Ruff4 files lint/
format PASS. Negative tests use synthetic data,not scientific evidence.

First creation exec24029 exit1 before any output: new policy accidentally
omitted `seal_field: protocol_digest`,present in the real frozen parent. Read-only
diagnosis confirmed all other pins/identities unchanged. Added only the missing
declaration to NEW policy and a negative regression,kept exact dict comparison,
retested/refroze. Corrected creation93171 passed. No provenance bypass,historical
hash replacement or real recovery rerun. Temporary Git index.lock blocked source
staging; it cleared without deletion or forcing,then staging succeeded.

## Remaining next step

Bounded numerical integration and clean-install/runtime replay with explicit
admitted context provider remain separate gates; this input PASS is NOT full
scientific pipeline readiness. Productive consumers have NOT been silently
redirected to regenerated containers or run with old manifest hashes.
O4b is requested next observing run AFTER readiness,with dedicated release,
detector,DQ/population,reference/calibration and validation contracts; no old
O4b shadow promotion or O4a threshold transplant. O3a remains diagnostically
closed. Local commits only,no push/main/release/user-folder changes.

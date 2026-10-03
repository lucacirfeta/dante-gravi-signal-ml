# Isolated productive calibration input boundary — 2026-10-03

## Status

Profile, input provider and preflight implemented; **full calibration BLOCKED
on missing raw files**, not scientifically complete. Author approved option A:
new versioned productive namespace, no historical output overwrite/reuse.
O3a remains closed; this is common-workflow qualification, not new O3a science.

Source commits: `38dd655dbb4b6460b14f70b46a5c1da59b0ff0b4`, then final
`86b9585f90d4c8941d7269e666e367d22f560a95`, before their respective preflights.
Profile `config/dante_workflow_production_calibration_v1.json` SHA
`df3df74b8098fbd520180b1fd044fc55eade7d447c4a2af0b999a6604c4e12e2`.

## Implemented boundary

- Exact parent pins: existing workflow and scientific protocol, admission,
  bounded encoder/scoring runtime qualification and its scientific parents.
- Scientific population/geometry/execution parameters/per-session-detector p99
  and full-context historical score-replay criterion inherit the existing
  protocol unchanged. This preflight does not calculate any of them.
- New provider uses the original `_CorrectedContextReader._read_manifest_slice`
  explicitly on a calibration-only manifest subset, with exact admitted gaps.
  It never invokes the legacy fallback/runner or monkeypatches global behavior.
  Required copies retain original SHA/size checks and detector/time identities.
  One available copy suffices per logical span; all existing copies must match.
- Current runtime must match its fresh numerical-gate receipt, which permits
  driver-only metadata differences from the original runtime. A later runtime
  needs its own fresh numerical receipt; no driver version is permanently fixed.
  No claim of historical cross-driver score equivalence is made.
- Output goes only into `production_calibration_v1` under a separate external
  root. Existing evidence is never overwritten; use standalone `verify` instead.
- The verified bounded-gate JSON includes its already verified numerical values
  and is parsed in full. Historical calibration HDF5 score **values** are not
  read; only frozen metadata/GPS and score-dataset shapes are inspected.
  The initial generic `score_values_read` report field was clarified in86b9585;
  initial38dd655 diagnostics remain preserved, not silently replaced.

## Actual observation and independent replay

WSL Ubuntu, Python `/home/atafe/miniconda/envs/dante_env/bin/python`.
Entry point `scripts/preflight_dante_workflow_production_calibration.py`.
Both invocations supply repository root, pinned profile, exact admission and
qualification receipts, raw root `/mnt/e/o4a` and isolated output root
`/mnt/e/dante_cache/dante_workflow/calibration_integration_20261003`.
First invocation `--stage preflight`; standalone `--stage verify` additionally
supplies the exact evidence path and SHA below. No productive scoring invocation.

Final preflight exec7600 and verifier31769 both observed **OS exit2**, status
`BLOCKED_PRODUCTIVE_RAW_FILES`. Complete sealed report compares exactly in the
standalone verifier. Both stderr logs empty. This is a reproducible blocked
diagnosis, **not PASS_VERIFIED input readiness or a scientific run failure**.

Evidence:
`E:/dante_cache/dante_workflow/calibration_integration_20261003/production_calibration_v1/preflight_19698757db3f545b9df441bf53cf74d749e4201ad6285fa6daf35e26db69ddbf.json`

SHA `abdd416efda8e93b6140ad895c691a40a8b4a29ab414801b83b6a7455fc8f170`.
Logs `worker.preflight.final.stdout.log`, `worker.preflight.final.stderr.log`,
`worker.verify.final.stdout.log`, `worker.verify.final.stderr.log` in the
isolated external root. Initial38dd655 evidence/logs are also retained.
Administrative `execution_receipt_20261003_v1.json` records observed OS exits;
it is not a sealed scientific artifact or a fabricated runner exit receipt.

| Non-scientific inventory | Count |
|---|---:|
| Frozen calibration identities |39971:19715H1+20256L1|
| Unique detector/padded-interval contexts |39891|
| Already approved exact admitted contexts |28|
| Normal unique contexts from original raw manifest |39863|
| Required logical raw segments |889:428H1+461L1|
| Available/hash-verified physical copies atE:/o4a |0|
| Normal contexts with complete physical coverage |0|

The metadata identities can share a physical interval across sessions; no
identity was removed or deduplicated from the frozen scientific population.
The889 segments are the subset needed for calibration, not all6928 logical
spans/7174 physical copies in the primary-run manifest.

Quick exact-path check at the obvious historical output archive
`E:/dante_archive/o4a_project_outputs_20260918/data/production` also found0
manifest physical copies. It contains outputs; this is NOT a search of every
possible backup. Original minimum one-copy sizes total106821211306 bytes
(99.485GiB); current GWOSC transfer size/version/coverage not checked here.
E: free space observed657262743552 bytes; this is a point-in-time observation.
No download was launched or unrelated file moved/deleted.

## Tests, source provenance and limits

-48 targeted synthetic tests, host PASS. Positives include exact two-frame
  stitching and explicit admitted routing; negatives cover hash/size/parent
  drift, detector locality, unknown intervals, invalid types/nonfinite inputs,
  population/session changes, runtime receipt mismatch, output confinement and
  repeated evidence-write refusal. Positive preflight branch tested synthetically.
- Final eleven-file host suite322 PASS/16.02s, WSL322 PASS/45.75s, OSexit0.
  Suite: production_calibration, scoring_replay, calibration_contexts,
  calibration_admission, calibration_recovery, calibration_transport,
  calibration_inputs, input_coverage, input_preflight, o4a_adapter, packaging.
- Post-freeze WSL production/scoring/context/PatchProducer suite145 PASS/9.71s,
  OSexit0.11 GWPy upstream warnings; no warning bypass or dependency mutation.
- Ruff lint/format3 files PASS in WSL. Host Python lacks Ruff; not installed.
-11 profile source hashes byte-identical to final Git freeze86b9585. Existing
  qualified upstream EOL/core/runtime evidence from08.31 remains unchanged;
  protected sources were not normalized. All legacy defaults remain intact.

## Next gate

Resolve the889 exact required segments via existing frozen copies at another
declared root, or a separately contracted transport/reacquisition gate. Do not
rewrite the historical manifest or expand the28-context admission silently.
New containers need explicit provenance and numerical-validation/admission
criteria before use; full-context score replay remains mandatory where frozen.

Then validate full context samples and complete the isolated measurement/verifier
adapter before all39971 calibration identities are measured. Full calibration,
native qualification, writer exclusion, independent scientific installation,
other runs/Virgo and O4b activation remain open. No new thresholds, scientific
results, publication, push/main, or historical shard reuse in this increment.

# Calibration-only expanded native admission, 2026-10-03

## Scope and authorization

Author `procedi` confirms the explicit08.33 choice: acquire new containers and
admit only calibration contexts whose native sample SHA matches the sealed
historical baseline exactly. This is a separate opt-in contract, not a waiver
of the original manifest/container rule. No historical file,28-key admission,
productive profile, default runner, score, threshold or population is changed.
O3a remains closed; this is an input gate for multi-run pipeline qualification,
not another O3a search. O4b is not launched.

Source freeze: `745366c32d920c7af7f21f64a6eebb161325d6ef`.
Policy: `config/dante_workflow_calibration_expanded_admission_v1.json`, SHA
`102c7f9e5050a81c0e28d3a50b2f9ce4b2c30b5ee31427fba60767f672eef622`.

## What the adapter does

- Bind the unchanged metadata-only plan, productive profile, scientific
  protocol, historical calibration compact/session-shard seals and exact
  current calibration identity metadata. Parse score-containing JSON only to
  validate seals; use raw identity/hash fields, never analyze/reuse scores.
- Preserve the28 independently admitted contexts as references, without fetch
  or alteration. Derive only frames touching the remaining exact contexts.
- Validate official manifest MD5 and retain a new SHA for each downloaded frame.
  Read native float64 samples with exact half-open indices, detector locality,
  finite values, grid and historical numerical SHA. No resampling or tolerance.
- Process contexts as soon as their frames arrive; a mismatch stops subsequent
  download. Retain frames/receipts/partials/failure, no automatic retry/resume.
  Exclusive external namespace and owned single-controller lock.
- Write new GWPy HDF5 containers. Preserve the literal Series name from the
  pinned `_CorrectedContextReader._read_manifest_slice`; its `16KHZ` label is
  historical metadata, **not** a native-rate claim. The protocol still fixes
  4096Hz and40s padded contexts.
- Standalone verification regenerates the complete plan, checks every receipt
  and container, and independently reads official frames with GWPy instead of
  the direct HDF5 writer path. A bounded one-frame cache avoids repeated full
  frame reads. Recheck frame/context SHA after reading to detect concurrent
  change. Admission itself replays that verifier, not a PASS status string.

An observed standalone OSexit0 and exact complete domain are required before
an admission receipt can be described as verified. Local replay is not a second
GWOSC fetch and does not prove a historical release/container is byte-identical.
This receipt does not activate a productive provider or certify full calibration.

## Tests and provenance

-69 targeted WSL tests PASS, including real synthetic HDF5/GWPy reading,
  cross-frame fractional native-grid boundaries, identity/shared-context seals,
  typed authority, source/parent drift, independent oracle and read-time drift,
  failure preservation, exclusive namespace, no auto-resume and forged receipt.
  The old metadata gate/provider use synthetic fixtures in the new unit suite;
  their own regression suites and the real plan must validate their live pins.
- Entire workflow suite: Windows1014 PASS/508 skipped/179.70s; WSL1515 PASS/
  7 skipped/570.55s,11 upstream warnings. Both observed OSexit0. Skips are explicit,
  not evidence for untested platforms or full scientific readiness.
- Post-freeze expanded-admission/metadata/PatchProducer suite126 PASS/5.82s,
  11 upstream warnings, observed OSexit0. Ruff lint/format3files PASS.
-17 source bytes and policy exactly match Git745366c. Existing upstream
  qualification of protected sources remains intact; no EOL normalization.
  Explicit LF attributes added only for the new policy and test.

## Live gate checkpoint

Evidence root:
`E:/dante_cache/dante_workflow/calibration_expanded_admission_20261003`.
Prepared namespace: `prepared_v1`; raw recovery child: `prepared_v1/recovery`.
Plan exec23452 completed with observed OSexit0, stderr empty:

- Status `PLAN_CALIBRATION_NATIVE_RAW_RECOVERY_ONLY`;
- SHA `288f4bb07f0580a6e5515ec63914efc7952aaa32488392897483e374927df155`;
- Seal `a19a39a5a47db362886deb194305184f69fb3c6bc7535cd1e2696a287b00b217`;
-39971 identities19715H1+20256L1,39891 unique contexts;
-39863 new contexts,28 prior references,707 official frames,52249231360 new
  sample payload bytes (excluding HDF5 headers).

Only707 of the1176 coverage-plan frames touch the exact new contexts. This
reduces transport, not the scientific identity population or geometry. Before
run launch: E: free657227755520 bytes; conservative upper bound432890707968
bytes, calculated from707 times the configured512MiB frame ceiling plus full
new context payload and1GiB header reserve. This is a ceiling, not a download
volume/time prediction.

One WSL run started in exec4883 with the exact prepared-plan SHA and no preexisting
controller. Logs `worker.run.stdout.log`/`worker.run.stderr.log` are outside the
raw directory. The runner regenerates the plan before creating its lock/frames;
no lock/receipt is expected during that initial read-only interval. No run exit,
completed raw matching or admission PASS is claimed yet. No productive scoring,
threshold fit or all-run certification is claimed.

Required next gates: completed pinned plan and one transport/matching execution;
then independent standalone verification/admission with exit evidence; then a
separate productive-provider integration/full-context validity and full fresh
calibration measurement/verifier increment. Stop on any native SHA, identity,
structure or provenance mismatch; never silently substitute bytes or populations.

Local commits only. No push/main or changes to unrelated user outputs/history.

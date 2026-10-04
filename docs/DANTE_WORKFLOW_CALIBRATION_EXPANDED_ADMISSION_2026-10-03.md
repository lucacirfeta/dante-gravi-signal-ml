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

## Recovery completion and independent verification in progress

Checkpoint observed2026-10-03 at22:10-22:12 Europe/Rome. The existing run4883
returned observed OSexit0 and `RUN_EXIT=0`. Summary status is
`PASS_COMPLETE_CALIBRATION_RAW_NUMERIC_MATCH_PENDING_ADMISSION`, seal
`fd0fbbc0017eb16700c13d70de8a2507475beb5651453dfd69970bf33dfa9ec7`, file SHA
`5a8c37663481d08cf350da48f25e94c627a01e4efbee2b8ed682ab510424f4ad`.
All707 frame/receipt pairs and39863 new context/receipt pairs exist; no failure,
partial/tmp or controller lock remains. Run stderr is empty. E: free space was
524057104384 bytes.17sources and the policy remain byte-identical to Git745366c;
the prepared/recovery plan SHA remains unchanged.

After confirming zero controllers and no existing verification evidence/logs,
ONE standalone `--stage verify` started in exec38777 (WSL PID424 at22:12).
Distinct `worker.verify.stdout.log`/`worker.verify.stderr.log` are outside the
recovery directory; the supervisor preserves the actual OSexit. Do not duplicate
this invocation. Full independent replay and subsequent pinned admission are
still pending; this checkpoint does not claim either gate has passed. The replay
is local, not a second GWOSC fetch. No productive calibration, score/threshold
fit, provider promotion, O4b run or complete scientific certification is opened.

## Independent verification PASS; pinned admission replay in progress

At2026-10-04 00:10-00:12 Europe/Rome, standalone38777 returned observed OSexit0
and `VERIFY_EXIT=0`; stderr remained empty. `verification.json` has status
`PASS_VERIFIED_CALIBRATION_NATIVE_RAW_ONLY`, seal
`c1d63c91f0a954bd2e4c8e5cb711db10b0f6bc1dca955579e950136e9183d8fe`, fileSHA
`c2f288a51f871de44d402494b6e16885b56ebb426f74c81b88a5ecacbb907d60`.
Counts:39971identities (19715H1+20256L1),39863new+28prior contexts,707frames.
Seals and immutable plan/summary/policy pins were checked again;17source bytes
still matchGit745366c. No failure/partial/tmp/lock remains.

ONE pinned `--stage admit` started in exec32297 (LinuxPID423 at00:12), with
distinct `worker.admit.stdout.log`/`worker.admit.stderr.log` outside recovery
and actual OSexit supervision. This stage repeats the complete offline verifier
before writing its exclusive admission receipt; do not duplicate it. The local
replay is not a second source fetch. Admission PASS, post-gate regressions and
the final local checkpoint commit remain pending; productive integration/full
calibration and O4b are still separate unopened gates.

## Final checkpoint: independently verified and admitted

Closed2026-10-04 at02:12 Europe/Rome. Acquisition4883, independent standalone
verification38777 and admission32297 each returned observed OS exit0. None was
repeated. Admission receipt was written02:02:23 Europe/Rome and reports
`PASS_ADMITTED_CALIBRATION_EXACT_NATIVE_INPUTS_ONLY`:

- Admission seal `97d856bcd3440d67788345adf9fbc60c1f9dbe17fde5a65d6e82245981a63665`;
- Admission fileSHA `17ff302d9fab56886d83ac57e41d56cce54f46dbeb29178a4f8607a9aa325856`;
- Verification fileSHA `c2f288a51f871de44d402494b6e16885b56ebb426f74c81b88a5ecacbb907d60`;
- Summary fileSHA `5a8c37663481d08cf350da48f25e94c627a01e4efbee2b8ed682ab510424f4ad`.

All39971 identities (19715H1+20256L1) are accounted for through39891 unique
contexts:39863 new numerical context/receipt pairs and28 preserved references.
All707 official frame/receipt pairs are complete; no failure/partial/tmp/lock,
no remaining controller, and all three stage stderr logs empty. Final read-only
sealed-evidence audit confirms plan/summary/verification/admission pins, exact
identity domain and unchanged boundaries;17 source bytes and policy are exactly
Git745366c. The prior28 admission remains untouched, fileSHA
`b17d6388ff888d2b0bd332e1c993b56e83ac0c62d53e62a54d0f01e3d09de6f1`.
Available E: space at02:10 was524027904000 bytes.

Post-gate targeted WSL expanded-admission/raw-transport/PatchProducer tests:
126 PASS,11 upstream warnings,5.89s, observed OSexit0. Ruff lint and format PASS,
observed OSexit0. These establish this input gate, not scientific certification
of every observing run. Independent local numerical replay is NOT a second GWOSC
fetch, and numerical identity is not a claim of historical HDF5 container equality.

The admitted inputs remain calibration-only. No productive provider promotion,
calibration fitting, historical score/threshold reuse, new scientific run or O4b
execution was opened. Next is a separate versioned productive-provider/full-context
validity adapter and tests, then full fresh calibration and its verifier. O3a
remains closed; all-run scientific certification remains open. Checkpoint is for
a local-only commit, no push/main, preserving unrelated untracked user files.

The author requested normal computer shutdown after verified closure. Shutdown
may be requested only after the local commit succeeds, the monitor is paused and
no controller/verifier/test/task writer or other unsafe active work remains; no
forced process termination or forced application closure is authorized.

# Isolated calibration raw recovery — 2026-10-03

## Scope and current status

Author `procedi` authorizes the next bounded transport acquisition after08.26.
Source freeze `71c9f5e0870ff5b52a0fd374301f978ecc451025`.
Acquisition and standalone offline verification both completed with observed
WSL OSexit0. `PASS_VERIFIED_RAW_NUMERIC_MATCH_ONLY`:28/28 historical numerical
SHA matches,0/28 whole-container SHA matches. No replacement input admitted.
Exact frozen28 missing contexts, no population/score/threshold/calibration change.
No NVIDIA/runtime modification, O3a reopening, productive worker or O4b launch.

New preserved external run:
`E:/dante_cache/dante_light/o4a_corrected_v2/calibration_reacquisition/recovery_20261003`.
Launcher stdout/stderr are beside it as `worker.recovery_20261003.*.log`.
Old acquisition directories and SHA-pinned historical receipt are untouched.
Transport plan, official MD5 snapshot, downloaded frames and context receipts
are separate evidence; an existing run cannot be rerun or auto-resumed.
Failure preserves partial/file/context evidence and stops. No automatic retry.
This completed run has28 frames,28 context HDF5 and28 sealed context receipts,
zero failure/partial/lock. Source frames2,637,791,038 bytes;context HDF5
35,421,936 bytes. Historical acquisition files remain missing and unchanged.

Evidence seals:

- Plan `03a0e7d93a0b1e76f109dbe3f8b5086146b1e19131313e71f00b1ba96546130f`;
  fileSHA `d082bee33a74090df974cd1a37f4b4c1741d491b5b34d96bcc5c20ea6cedec38`.
- Run `b1fddd1a249a4291342f9983e2dd0002cdbfd279d8083862370300bb9938ec74`;
  summary fileSHA `b0797fbbebee096e7a880fb8da4dc7868d1670e7d805e31bc48b01828817ba1e`.
- Verification `c03856b9052632629ab315b3d3d66cdc4c6fab6d12a569a8ed9fbdecdb5b013d`;
  external `verification.json`;compact copy under
  `artifacts/dante_workflow/calibration_recovery_v1/verification_20261003.json`.
- Official checksum snapshotSHA
  `531912260ea45cd5265198f7a1990a8a89f69ffa98abca8a21930140e332b7ba`.
- Acquisition and verifier stderr empty; stdout and OS exit preserved separately.

Checkpoint: approve a NEW provenance receipt binding new HDF5 SHA to exact
historical numerical SHA and immutable parent/old receipt. Recommended over
indefinite search for old container bytes, but not implemented or admitted.
Different container bytes are not silently relabelled as historical files.
The measured equality concerns these28 native contexts, not every O4a sample
or an independently known historical calibration/version label.

## Preconditions and exact comparison

Pin previous metadata report fileSHA
`9dc1c705b036a5ab83888e6438a99d4f221f65f7d489f4ede6efd00446abd48e`,
historical receipt fileSHA
`4f0732510604583e8a02827d3172e337cedd714ed3e8d3b86dfaac6c17b7fe78`,
and parent protocol fileSHA
`d88535676a73301c329e3f942a140b6557c6499a6fb2fc66eb966f4a7bb875dc`.
Use audited score-blind geometry, not the legacy score selector/acquirer.

The explicit public source is O4a_4KHZ_R1 and its official
[HDF5 MD5 manifest](https://gwosc.org/archive/md5/O4a_4KHZ_R1/strain-hdf.txt).
Only pinned metadata URLs are downloaded, sequentially, without redirects or
resampling. Check full-frame MD5, native float64 shape/grid/detector and exact
half-open slice. Check finite selected samples, count and historical raw byte
SHA. No tolerance fitting or new preprocessing. New container bytes are
measured separately and NEVER admitted automatically when different.

Offline verifier: retained frame SHA/official MD5 snapshot, original parent
pins and10 source SHA; independent direct HDF5 slice versus GWPy context read;
exact numerical SHA, identity/grid/count, receipts, inventory and no lock/
failure/partial. Local replay is NOT a second source fetch or sensor/DQ test.
Numerical parity of these contexts does not prove a historical release label
that the original acquisition never recorded.

## Software checks before acquisition

- Targeted Windows150 PASS/16.62s, WSL150 PASS/13.23s, observed OSexit0;
  WSL11 upstream matplotlib/GWPy deprecation warnings.
- Post-freeze WSL14 new tests PASS/2.86s, explicit exit0, same11 warnings.
- Ruff lint/format3 files PASS; staged diff check PASS.
- Original protocol/config and qualified scientific/EOL working SHA unchanged.
- Initial missing helper import and multiline lint exemption fixed BEFORE
  source freeze, all tests rerun; no failed real run or bypass.

## Next observing run requested by the author

O4b is the requested first observing run AFTER correct common-pipeline
implementation/readiness. This instruction records priority, not immediate
execution or promotion of a legacy O4b experimental/shadow profile. Before
O4b starts: resolve input/provenance and bounded numerical integration gates,
then explicitly qualify its release/detectors, DQ/population, reference,
calibration and validation contracts. No silent reuse of O4a thresholds or
bypass of existing held-out gates; new scientific choices go to the author.

Commits local only, no push/main/release; user untracked folders preserved.

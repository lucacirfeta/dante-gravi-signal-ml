# Missing calibration raw inputs: public transport plan — 2026-10-03

## Verified result and boundary

`PASS_VERIFIED_PUBLIC_RAW_METADATA_ONLY`, observed standalone OS exit0.
The public candidate O4a_4KHZ_R1 at the frozen protocol's 4096Hz covers every
required missing logical segment: **889 = 428H1 + 461L1**, mapping to **1176
distinct official 4096-second HDF5 files**. The logical/custom historical slices
are not necessarily aligned to the official frame boundaries; counts differ.
All planned URLs have entries in the official release MD5 manifest. Forty-four
bounded metadata queries and their raw responses are retained and hashed.

This is **not** a raw download, native-sample comparison, DQ validity gate,
admission, full calibration, threshold result or all-run readiness certificate.
The public release is explicitly a candidate, not proof of which historical
release generated the custom containers. The standalone verification replays
local snapshots; it is not a second source fetch.

O3a stays diagnostically closed. O4b has not been launched.

## Source freeze, tests and evidence

Source freeze `116d0ef` precedes the live plan. Four sources and the policy
are byte-identical to Git. Existing productive/scientific contracts, protected
core files and EOL/provenance qualifications are unchanged.

- New policy: `config/dante_workflow_calibration_raw_transport_v1.json`, SHA
  `eef2664610361987feea465e21aba6fefa9fec524540af88c326c385ad41b7e6`.
- Parent blocked preflight SHA
  `abdd416efda8e93b6140ad895c691a40a8b4a29ab414801b83b6a7455fc8f170`.
- Plan: `E:/dante_cache/dante_workflow/calibration_raw_transport_20261003/metadata_v1/metadata_plan.json`, SHA
  `2cb72b0921d6dd031aef853984bad08fb4f6e6114e216d7b4232cc74ba16d3e3`, seal
  `322e87ca526a913517c5bd80dfca87261daa6941ae2990a3909564bfc7923942`.
- Plan session25148: observed OSexit0, `PASS_PUBLIC_RAW_METADATA_PLAN_ONLY`.
- Standalone session64295: observed OSexit0,
  `PASS_VERIFIED_PUBLIC_RAW_METADATA_ONLY`; explicitly pinned expected plan SHA.
- Logs in the parent evidence directory: `worker.plan.stdout.log`,
  `worker.plan.stderr.log`, `worker.verify.stdout.log`, `worker.verify.stderr.log`.
  Both stderr files empty; no failure or partial evidence. Verification result
  is recorded in the standalone log and observed OS exit, not a fabricated
  separate verification JSON artifact.
- 43 targeted tests. Final post-freeze Windows365 PASS/17.82s and WSL365
  PASS/47.15s, observed exit0; 11 upstream warnings in WSL. Ruff lint/format PASS.
  Earlier development run: missing required strict-JSON labels and a file-only
  helper used for absent backup paths; corrected before freeze and live work.

## Bounded backup check

1843 exact declared/flat candidate paths per root, no recursive search:

- `E:/o4a`;
- repository `data/raw` and `data/raw/o4a_cache`;
- `E:/dante_archive/o4a_project_outputs_20260918/data/production`.

All four roots exist, zero matching frozen copies. This is not an assertion
that no backup exists anywhere. Recreated comparison files are not admitted.
The historical minimum container total is 106821211306 bytes (99.485GiB),
**not** a current network-volume estimate for the 1176 official frames.
Observed E: free space before the plan was 657262505984 bytes; no raw reservation
or download was made.

## Available historical numerical baseline

Read-only inventory of the existing sealed corrected-calibration compact and
its referenced 84 session shards found39971 identities/39891 unique padded
context hashes, with no inconsistent hash for repeated context identities.
The retained external summary equals the repository compact byte-for-byte.

- Compact SHA `0e9e02e4ea404a557ce6f850b4029c0d24c3520f11570932455d791e586ced51`;
  seal `a27ff9befdf4aae01672bd202db82f54d2e61a241f8f4b88945ca954368bb779`.
- Frozen protocol digest
  `326495389f511b378c52b2a99f7771bd13d87d6852d4191a4f0fb61d6842d4fa`.
- Retained run `E:/dante_cache/dante_light/o4a_corrected_v2/calibration_e70050ef91ce0c04522b17f0b51fd364ade77cd9c765d19dd4ec89df3a653ff7`.

Score-containing JSON bodies were parsed to validate seals, but only raw
identity/hash metadata was inventoried: no score analysis, reuse, measurement,
new raw comparison or admission. This establishes that an exact native numerical
baseline is available, not that newly acquired samples already match it.

## CHECKPOINT REACHED

Type: decision. Plan08.33, progress3/4 tasks complete. Metadata gate verified;
productive physical-input gate remains BLOCKED. The executor decision rule
prevents silently changing the current manifest/admission semantics.

Recommended next increment: isolated transport plus a **separate, calibration-
only numerical-admission contract**, extending the existing exact-native-hash
principle beyond the currently authorized28 contexts. Freeze the historical
baseline references and exact identity domain first. Require native geometry,
finite samples, official checksums and exact historical40s context hashes for
every calibration context; record new container SHA in new receipts, never
rewrite the old manifest. Stop on any mismatch. Do not infer admission for scan,
native indexing or another run; do not reuse historical scores or thresholds.

Alternative: provide byte-identical historical backups, retaining the current
manifest-copy rule without new admission. Do not spend indefinite time searching
unidentified locations. Author choice is required before the new admission rule
or full raw acquisition; full measurement/verifier and validity gates still follow.

Local commits only. Historical runs and user untracked directories unchanged.

---
phase: 08-multi-run-productization
plan: 15
checkpoint_at: 2026-10-01
status: blocked_runtime_mismatch
starting_commit: e99a496
source_freeze_unchanged: f254b2b
full_workflow_verified: false
---

# Checkpoint 08.15: real parent preflight refused

Existing read-only coincidence CLI executed in canonical WSL Python with every
external root explicitly `/mnt/e/dante_cache/dante_light/o3a_native_v1`.
Observed session 97666 OS exit 1:
`FAIL_CLOSED_O3A_COINCIDENCE_EVIDENCE`, `ContractError`,
`STOP_ENVIRONMENT_MISMATCH: O3a scoring requires the frozen WSL runtime`.

Read-only diagnosis using the original load/capture helpers validates the frozen
contract without current-runtime comparison and compares every captured field.
Exactly one non-digest field differs: cuda_device.driver_version, 616.92 versus
617.14. Python, package, OS, Torch and other device fields compared equal under
the original fingerprint schema; this is not numerical-equivalence evidence.
Frozen environment digest 582a9b99f689d36f126b75f95dd31763c2b399aab03180f06c9838eb1f8f1b58;
observed ebeae01fdbad49d252555e354daba1e69282ddfcdd89ee386ceeb3c184fb474f.

WSL existing O3a native-contract regressions: 10 PASS, OS exit 0, 3.40s.
No source/config changed, no snapshot created, no productive invocation, no
historical repair, no push. User untracked directories retained.
Documentation-only checkpoint; no new implementation lint or full suite claim.

Next requires an explicit author choice: restore the historical driver on a
suitable environment (host change, not performed), or design a separately
versioned retained-only runtime qualification/compatibility proof. The latter
changes validation semantics and is NOT implemented or approved here. A failed
new preflight does not invalidate previously sealed O3a results; it prevents
certification of this new real replay in the current environment.

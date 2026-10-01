---
phase: 08-multi-run-productization
plan: 15
checked: 2026-10-01
status: blocked
real_snapshot_created: false
complete_chain_pass: false
---

# Verification 08.15: evidence, not a success certificate

- Real preflight: existing read-only CLI, actual frozen inputs, WSL scientific
  Python, explicit roots; OS exit 1 and fail-closed output observed.
- Diagnosis: original runtime contract loader (require_current=False) validates
  the retained contract, original capture helper compares current fingerprint;
  diagnostic OS exit 0. Only driver identity differs, plus derived digest.
  This diagnostic does NOT bypass the refusal or verify scientific parents.
- Existing O3a contract tests: 10 PASS, OS exit 0, 3.40s. Tests validate contract
  behavior, not the missing positive historical complete-chain replay.
- Frozen runtime file SHA256:
  3b00a0bf258cc96870971481138e10e7e85deb97a1c3c49c470626e3153d0ef2.
- Tracked working tree was clean before this documentation-only checkpoint;
  no scientific source/config/driver/runtime change. No producer job observed
  in the initial WSL process snapshot, which is not global writer exclusion.
- Historical directories, persistent locks and user untracked directories are
  not edited. No capture plan/archive/retained PEM replay or release executed.

Stop-and-ask applies: accepting a new driver or altering the retained verifier's
runtime validation is a new structural/scientific-validation decision. No
positive real-chain or all-run readiness claim follows from this checkpoint.

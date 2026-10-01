---
phase: 08-multi-run-productization
plan: 06
completed_at: 2026-10-01
scope: historical_initial_evidence_read_only
overall_multi_run_productization_complete: false
---

# Summary 08.06: initial evidence checks, not numerical replay

| Task | Result | Local commit |
| --- | --- | --- |
| 1: separate read-only initial evidence module/CLI and synthetic tests | VERIFIED | 9d8a51a |
| 2: approved A resolution, scope/test checkpoint and handoff | VERIFIED | Documentation checkpoint |

Author's "procedi" resolves the 08.05 architectural checkpoint in favor of A:
separate, source-frozen read-only verifiers. This increment covers raw integrity
and stored initial acceptance reconstruction; native numerical verification and
full workflow adoption remain subsequent gates.

Raw integrity anchors exact historical acquisition/preflight/manifest/ledger
evidence in the existing acceptance contract and streams actual local HDF5 file
SHA checks. Metadata validation preserves the existing shape/Xspacing checks.
Acceptance anchors the initial threshold contract's parent, validates every
planned shard with the existing validator and reconstructs exact accepted-ledger
bytes, bootstrap/tail flags and summary. It reads stored scores but never
recomputes raw/encoder scores or fits a threshold. Its raw-parent evidence check
explicitly does NOT rehash raw files; that is the distinct raw selector's scope.

Both emit scoped sealed JSON on stdout only, with eleven source bindings and
explicit false full-workflow/numerical-replay/fetch claims. No historical failure,
lock, preflight, ledger, summary, compact or contract is written. Drive/mount path
syntax translation does not rebase sealed parents. Factory/registry unchanged.

Final complete Windows controller suite: **329 PASS**, OS exit 0, 53.52s.
Final WSL controller plus existing initial acquisition/download/calibration/
acceptance/threshold and PatchProducer tests: **367 PASS, one Windows-only skip,
11 upstream warnings**, OS exit 0, 149.94s. Final targeted WSL suite **60 PASS**,
OS exit 0, 13.54s. Ruff lint and new-file format checks PASS. Post-freeze targeted
Windows result and byte audit are recorded in VERIFICATION.

Fixture-only scaled contract loaders are substituted; actual legacy metadata,
shard/seal/hash checks and new CLI functions run. Productive writers, scoring and
network hooks are forbidden; success/failure preserve fixture bytes/mtimes.
Deliberately resealed/repinned negatives are synthetic only, never history.
Real local inherited contract loaders/source bindings also pass without opening
historical raw or outcomes. Initial Ruff unused test imports were removed; no
scientific source/provenance mismatch was bypassed.

No historical verifier/raw scan, productive run, new outcome, dependency install,
source/config normalization, push, release or external communication. User
untracked artifacts/output preserved. Existing EOL/UI qualifications remain.
Next: separate non-mutating native verification including parent calls; then
complete profile/preflight binding and bounded real clean-install replay.

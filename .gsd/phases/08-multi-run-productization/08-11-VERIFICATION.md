---
phase: 08-multi-run-productization
plan: 11
verified: 2026-10-01
scope: native_taxonomy_read_only
status: passed_with_platform_and_fixture_qualifications
score: 5/5
source_freeze: 6b0f5a5
overall_multi_run_productization_complete: false
---

# Verification 08.11: taxonomy reconstruction with exact frozen numerics

| Required truth | Evidence |
| --- | --- |
| Frozen joins/vectors/clusters/naming | Original reader/builder parity, 17 corruption parity cases, chaining/name and score-independence assertions; original build_taxonomy_rows actually executed |
| Full output/summary/compact | Legacy execute produces expected whole summary/compact in disposable fixture; byte/SHA and semantic reseal negatives, exact reconstructed JSONL/summary/compact |
| Explicit parents/source integrity | 32 helper/wrapper bindings, source drift and final input rehash; roots asserted in isolated parent fixture, linked original bootstrap/classification fixture; no productive parent invocation |
| Persistent lock/immutable database | Approved 08.10 context reused, all three stage locks held through builder and released on success/error, busy/replacement refused; immutable WAL fixture no sidecar; sidecars refused without repair |
| Bounded safe interface | CLI stdout success/failure and mutation-option refusal, Windows early POSIX refusal; bytes/mtime/inventory unchanged; public registry not modified |

## Observed runs

Exact preliminary fixture failure/correction and targeted results in SUMMARY.
Final Windows workflow: 609 PASS/114 POSIX-only skips, observed OS exit 0/194.09s.
Final WSL workflow plus original taxonomy/parent/PatchProducer suites: 844 PASS,
three Windows-only skips, 11 upstream warnings, observed OS exit 0/397.99s.
Prior disposable E: contention fixture explicitly enabled. Ruff full workflow/
tests/new CLI lint and three-file format PASS, exit 0; no stub markers found.
Source freeze 6b0f5a5. Three new Python files byte-identical to Git, original two
taxonomy helpers also exactly match Git blobs. Source freeze diff contains only
new module/CLI/tests/PLAN. Earlier upstream EOL qualifications are not normalized
or promoted to an all-source identity certificate.
Post-freeze WSL target: 77 PASS/one Windows-only skip/11 upstream warnings,
observed OS exit 0/48.94s, all 78 new tests collected. No source edit after freeze.

## Qualifications and open milestone gates

Normal new fixtures isolate classification parent. Linked scaled fixture executes
actual 08.10 detector-local compute_threshold twice and classify_rows; RESCORE
ancestry remains isolated. Earlier dependency gate regressions are retained, not
replaced. No real complete historical chain, full-population clustering, fresh raw
score, clean-install scientific replay, global upstream quiescence or Virgo method
verified. Fixture contracts/counts/vectors are scaled; linked SQL-NULL/missing-image
join is legacy parity only, not realistic image-provenance evidence. Legacy writes
only occur while building separate disposable expected fixtures; implementation
never calls execute/old verifier/writer/reader or monkeypatches scientific globals.

Contract metadata load is WSL only; native Windows historical root reconstruction
and POSIX support remain fail-closed. Earlier target-FS lock proof covers disposable
observed Linux/E: configuration, not general filesystem portability or historical
quiescence. New stage holds own/classification/threshold locks only. Runtime and
method settings remain exact original contract; preregistered chaining expectation
remains descriptive, not an acceptance cutoff or physical family claim.

No new scientific/structural policy beyond already approved immutable reader and
persistent lock contexts. No old sources/config/earlier guard/artifact changes,
normalization, install, activation, push/merge/release or user file edits.
Next: coincidence/PEM read-only chain, full profile/preflight binding and globally
quiescent bounded real clean-install replay. Entire multi-run/Virgo phase not PASS.

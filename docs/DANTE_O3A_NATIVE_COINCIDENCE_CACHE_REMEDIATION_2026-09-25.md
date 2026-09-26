# O3a coincidence cache remediation — pre-v2-run checkpoint

The first O3a coincidence run is preserved at
`E:\dante_cache\dante_light\o3a_native_v1\native_coincidence_713609d1605d2b2a0d2871829a2b91288ce6330510a296021b86977b3c6c4a53`.
It stopped with a sealed `ContractError` after 288/6,408 seed workloads and
9 event shards. No final coincidence summary, pooled threshold or PEM
shortlist exists. The 8.65 GB transient raw cache and partial shards are
retained as failed-run evidence; they are not adopted or silently reused.

The v1 adapter concatenated the ROBUST and AMBIGUOUS populations before
forming batches. The raw-frame cache evicts a frame only after its last
planned use, so an early ROBUST frame needed again in the much later
AMBIGUOUS pass remained pinned. A metadata-only replay of the full plan found
a 90,116,154,146-byte peak and 189/201 batches over the 8 GiB contract cap.
Global GPS/detector ordering across the *same* population predicts a
5,293,641,251-byte peak, including the one pre-pinned inventory-only frame,
and zero batches over cap. Neither calculation opens
strain or coincidence outcomes.

The author explicitly authorized an execution-only v2 remediation on
2026-09-25. The physical statistic, eight shifts, pooled primary-null rule,
classes, score/index sources, and diagnostic-only interpretation remain
unchanged. The new contract must freeze the global chronological seed order
and a complete resource-plan gate before scoring. Its new run key requires
fresh computation of every seed; the failed v1 shards are historical only.
No PEM work starts until v2 coincidence passes independent verification.

Before freezing v2, the source-only full-plan replay passed its 8 GiB cap:
5,293,641,251 peak bytes across 43 frames, at batch 152, with 0/201
batches over the cap. The synthetic cache regression and chronology tests
passed (17 focused tests); the full WSL O3a/PatchProducer suite passed
(187 tests, 11 upstream warnings), and Ruff passed. These checks validate
the execution plan and code gates, not a completed scientific measurement.

The frozen v2 contract digest is
`05565c848b08efda6d71b7acf434809f93e5db638d623ca994824d1e520d991a`;
`--check` and source-only `--preflight` both exited 0. The latter sealed
digest `590242c981544aa09e623ab8931a98bf5ef0e95423b7714a72996a62963dc63d`.
The new run key is
`d42ab62e620f86a5b4c84852e74dff80bcf45ccd1beef39edcb5082979cd3e89`.
It is distinct from the preserved v1 failed key. The source preflight saw
6,408 frozen seeds and did not open strain or coincidence outcomes.

Source freeze commit `3f310fd` was pushed on
`science/o3-transfer-readiness` before the v2 run. The single Linux
controller started under the new run key on `E:`; `cache_plan.json` sealed
`PASS_O3A_COINCIDENCE_CACHE_PLAN` with digest
`a46247f137bb2c86a9e4bf62ad217653f0d80849c85c78f9a1a9c14fcd83ebb7`.
At this checkpoint the run is measuring, no failure/summary exists, and
the hourly monitor is active. The cache plan is a resource gate, not a
scientific result. Coincidence and PEM remain unverified/not started.

At 3,648/6,408 seed workloads, GWOSC returned HTTP 502 for a public H1
frame. The v2 runner sealed `InfrastructureError` as artifact
`1669a4b14e813ab3f2c6109feb71e3df28207ed6172b3f5771a071de0e52e3a6`.
There was no final summary. The built-in recovery check verified the failure,
preflight and 114 completed event shards, then archived the failure in
`failure_history/` and resumed the *same* run key with separate `resume1`
logs. No source, config, method or population changed; the failed v1 run
remains untouched. Repeated transport failures require review, not an
unbounded retry loop.

## Final v2 verification, 2026-09-26

The resumed run completed all 6,408 workloads in 201 event shards, with
no active failure and an empty transient cache. Standalone `--verify` exited
0 and independently rebuilt the output ledgers. Summary artifact digest:
`79bb6d04efac92a1cebf44fea29bc140b0e3d1cda5e67c20e76c220446db5c5a`;
verified compact digest:
`3c3b3a878ae50753ab8ba99a70acf9898c4ad9b138acde2fb4c9ad8d7116afc9`.
The sealed raw-source receipt has 4,783 frame rows. All zero-violation
gates passed: seed identity/score replay, detector/GPS uniqueness,
partner-class nonuse, background exclusion, complete accounting and empty
cache. The cache-plan digest remained
`a46247f137bb2c86a9e4bf62ad217653f0d80849c85c78f9a1a9c14fcd83ebb7`.

The primary ledger has 5,850 ROBUST seeds: 4,607 measured and 1,243
partner-data unavailable (820 without complete source coverage; 423 with
non-finite partner raw context). The separate diagnostic ledger has 558
AMBIGUOUS seeds: 445 measured and 113 unavailable (65 coverage, 48
non-finite). Measured events have 4–8 eligible shifts. The O3a-only linear
p99 of measured primary per-seed null maxima is `0.25434447815440775`;
11 primary measurements and one diagnostic measurement exceed it. These
are diagnostic threshold exceedances, **not** a formal global false-alarm
rate, astrophysical candidates or an approved PEM shortlist. PEM remains
unopened pending its separate public-channel and method-parity preflight.

Post-run WSL regression: 187 passed, 11 upstream deprecation warnings in
122.59 s. Ruff passed. All 15 frozen implementation-source SHA-256 values
match the live files; nine sources match Git byte-for-byte and six match an
exact LF-to-CRLF conversion of their Git blobs. This qualifies current-run
provenance but does not claim a clean-LF checkout is byte-equivalent.

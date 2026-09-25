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

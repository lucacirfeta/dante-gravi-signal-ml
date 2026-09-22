---
phase: 07-o3a-transfer-readiness
plan: 12
completed_at: 2026-09-23
---

# Summary: O3a detector-aware native cohort

## Result

The frozen O3a-only cohort completed with exactly 647 clean H1 and 647 clean
L1 windows. The selector used detector/GPS identity and the frozen primary
candidate firewall. It read no primary score or class and computed no native
embedding or score. The final ledger and retained 40 s raw contexts passed
independent verification, including source-frame hashes, complete symmetric
context, candidate guard, same-detector separation, and ledger/shard parity.
The transient raw cache was empty at completion.

| Detector | Quality checks | Excess-power veto | Frozen clean windows |
|---|---:|---:|---:|
| H1 | 730 | 83 | 647 |
| L1 | 751 | 104 | 647 |

## Canonical evidence

- Contract digest: `4601b2e1ffeb6ef78ab68fd2eb206c9aacfb94a19e2adf7d9444959ae6c1e299`
- Run key: `876508390ba7f1eddf2c50342870e7e8880048b243f545487039974b51df9a2c`
- Artifact digest: `709c6fc5c3a22c89c21cd92303de2acf4d5ab1e30a016ddaaa89ebaf69daf382`
- Ledger SHA-256: `99cbc1c897ab1b30df33923b0b75693c997447ecc878971edfb913228893e298`
- Ledger row digest: `4a21619ea9771b95cb9a539cb7de276576ae31429c3146b7b0c4f36b08479d27`
- External summary SHA-256: `c2fa653ccf7d8b1391c04fc08834d318088d2372a0b1f714f261569df9f6bc03`
- Compact evidence: `artifacts/dante_light/o3a_native_v1/native_cohort.json`

## Preserved interruption evidence

The earlier run key
`29a410a80c546b2ab2d7ad1ab14e842182379e76fbce6663aba34add3c35da5b`
remains FAILED after an execution-only frame-list shadowing defect. No quality
shard from it was adopted. The canonical run then resumed twice from verified
quality shards after GWOSC refused HTTPS connections. Both infrastructure
failure artifacts remain in its `failures/` directory with digest prefixes
`04cd9e99` and `27dbeb88`; neither required a new scientific run key.

## Verification and next gate

- Independent production verifier: PASS.
- Focused WSL O3a/PatchProducer tests: 79 passed, 11 upstream GWPy warnings.
- WSL Ruff and frozen runtime verification: PASS.
- Final cardinality: 1,294 unique rows; transient raw cache empty.

The O3a-native index must use only this frozen cohort. Native calibration is
selected after the index manifest and must be disjoint from index windows and
guarded against the primary candidate population. No downstream scientific
result is implied by this cohort freeze.

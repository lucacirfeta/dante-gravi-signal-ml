---
phase: 07-o3a-transfer-readiness
plan: 19
completed_at: 2026-09-26
---

# O3a native physical coincidence: verified execution

The author approved exact corrected-O4a measurement/null parity with
O3a-only parents. The first v1 run failed structurally on the transient
raw-cache cap; its sealed failure, nine shards and raw cache remain on E:
as historical evidence. The authorized v2 change reordered the same frozen
seed populations globally by GPS/detector and added a whole-run cache-plan
gate, without changing the physical statistic or threshold method.

- Source freeze commit `3f310fd`, contract digest
  `05565c848b08efda6d71b7acf434809f93e5db638d623ca994824d1e520d991a`.
  New run key `d42ab62e620f86a5b4c84852e74dff80bcf45ccd1beef39edcb5082979cd3e89`.
- One sealed GWOSC HTTP 502 `InfrastructureError` was archived after runner
  validation, then the same v2 key resumed from 114 verified shards. No
  scientific/structural failure was bypassed.
- The run finished 6,408/6,408 seed workloads in 201 shards, with zero
  active failures, a complete 4,783-frame raw receipt and empty transient
  cache. Standalone `--verify` exited 0. Summary digest
  `79bb6d04efac92a1cebf44fea29bc140b0e3d1cda5e67c20e76c220446db5c5a`;
  compact digest `3c3b3a878ae50753ab8ba99a70acf9898c4ad9b138acde2fb4c9ad8d7116afc9`.
- Primary ROBUST ledger: 5,850 seeds, 4,607 measured, 1,243 partner-data
  unavailable; 11 measured on-source values above the O3a-only pooled-null
  p99 `0.25434447815440775`. AMBIGUOUS diagnostic ledger: 558 seeds,
  445 measured, 113 unavailable; one above the same diagnostic threshold.
  No BACKGROUND measurement. The p99 uses one maximum per measured primary
  seed from up to eight eligible shifts; it is not a global-significance
  or look-elsewhere-corrected threshold.
- Post-run WSL O3a/PatchProducer regression: 187 passed, 11 upstream
  warnings; Ruff passed. Fifteen frozen source hashes match current bytes;
  nine match Git exactly and six require exact LF-to-CRLF reconstruction.

Next stage is a *separate* O3a PEM public-channel/method-parity preflight.
PEM has not yet been measured, and no external candidate communication or
A2 promotion is authorized. Detailed evidence and caveats are in
`docs/DANTE_O3A_NATIVE_COINCIDENCE_CACHE_REMEDIATION_2026-09-25.md`.

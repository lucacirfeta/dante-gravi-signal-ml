---
phase: 07-o3a-transfer-readiness
plan: 12
checkpoint: preflight
status: passed
date: 2026-09-22
---

# O3a native-cohort preflight

## Result

The detector-aware native-cohort contract, deterministic proposal stream,
raw-source provenance lookup, bounded retained-context storage, and resumable
quality-shard implementation passed their pre-execution gates.  The proposal
capacity exceeds the frozen target of 647 rows per detector.  The preflight
opened no strain, read no primary score or class, and computed no native
embedding or score.

## Frozen evidence

- Contract digest:
  `4601b2e1ffeb6ef78ab68fd2eb206c9aacfb94a19e2adf7d9444959ae6c1e299`
- Run key:
  `876508390ba7f1eddf2c50342870e7e8880048b243f545487039974b51df9a2c`
- Preflight digest:
  `ade5cec4c278633ed9cd8c3db1e4f923394fada72d41384af3d6c994d5041ae6`
- Primary-scan parent artifact:
  `ba51f9cad83826223f860fda9b52077cbcc2e45c44fc7ad5063ebe56f49c4c79`
- Primary-scan database SHA-256:
  `1f222dfbc4066abf8fe2b2f3a09edb4a7ccbc83f79aac94ba9a54aa6b0844699`
- Verified source-frame ledger: 6,313 rows.
- Retained-context upper bound: 1,696,071,680 bytes plus the frozen 16 GiB
  reserve; the storage gate passed.

## Verification

- Focused Windows O3a/PatchProducer suite: 79 passed.
- Focused WSL O3a/PatchProducer suite: 79 passed, 11 upstream GWPy warnings.
- WSL Ruff: passed.
- Repeated preflight reuse returned the same immutable run key and digest.
- Exact-boundary unit checks cover the inclusive 128 s cross-detector guard,
  allowed 96 s separation, source-frame stitching, and canonical
  whitening-before-crop quality path.

## Preserved failed start

The first execution attempt under run key
`29a410a80c546b2ab2d7ad1ab14e842182379e76fbce6663aba34add3c35da5b`
failed before producing a quality shard because the execution-only frame list
shadowed the immutable source-inventory argument.  Its fail-closed
`STRUCTURAL_OR_SCIENTIFIC_FAILURE` artifact remains preserved.  The corrected
implementation has a direct regression test proving that reader frames are
resolved from the frozen inventory; changing its source hash produced the new
contract and run identities above.  No scientific population, threshold, or
quality rule changed.

## Execution boundary

The native cohort itself has not yet been materialized.  Native index,
native calibration, rescore, classification, taxonomy, coincidence, PEM,
and comparison remain closed.

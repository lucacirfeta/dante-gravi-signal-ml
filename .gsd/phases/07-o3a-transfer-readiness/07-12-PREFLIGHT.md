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
  `7c8696aa313c9f06226e375e766fabd68b72c615a6e28e4542633c0b9ee79fd5`
- Run key:
  `29a410a80c546b2ab2d7ad1ab14e842182379e76fbce6663aba34add3c35da5b`
- Preflight digest:
  `61fe82bde76af6984fee98b9153b5ea0af53c74c7222e2b8a7e0ae98940ef731`
- Primary-scan parent artifact:
  `ba51f9cad83826223f860fda9b52077cbcc2e45c44fc7ad5063ebe56f49c4c79`
- Primary-scan database SHA-256:
  `1f222dfbc4066abf8fe2b2f3a09edb4a7ccbc83f79aac94ba9a54aa6b0844699`
- Verified source-frame ledger: 6,313 rows.
- Retained-context upper bound: 1,696,071,680 bytes plus the frozen 16 GiB
  reserve; the storage gate passed.

## Verification

- Focused Windows O3a/PatchProducer suite: 78 passed.
- Focused WSL O3a/PatchProducer suite: 78 passed, 11 upstream GWPy warnings.
- WSL Ruff: passed.
- Repeated preflight reuse returned the same immutable run key and digest.
- Exact-boundary unit checks cover the inclusive 128 s cross-detector guard,
  allowed 96 s separation, source-frame stitching, and canonical
  whitening-before-crop quality path.

## Execution boundary

The native cohort itself has not yet been materialized.  Native index,
native calibration, rescore, classification, taxonomy, coincidence, PEM,
and comparison remain closed.

---
phase: 07-o3a-transfer-readiness
plan: 10
completed_at: 2026-09-20
---

# Summary: O3a initial detector-specific p99 thresholds

## Result

The frozen detector-specific block-bootstrap fit completed and replayed
exactly from the accepted calibration ledger.  H1 and L1 were never pooled;
no classification, candidate review, cohort selection, or primary scan was
performed.

| Detector | p99 | 95% block CI | Absolute width | Width / p99 |
|---|---:|---:|---:|---:|
| H1 | 0.4280126589536668 | [0.41823577880859375, 0.4372155293822288] | 0.018979750573635046 | 4.4343900061352255% |
| L1 | 0.43114929139614105 | [0.4196263551712036, 0.456072598695755] | 0.03644624352455139 | 8.453276916339517% |

Both intervals are finite, nondegenerate, and contain their point estimate.
The already frozen adequacy gate therefore passes.  L1 is visibly wider than
H1 and is reported as such; no post-hoc O3a-specific width cutoff was invented.

## Canonical evidence

- Contract digest:
  `44f188ccce5adf53d03d0a8885d279bf0dfe48881f3d34911264aa2d6a21095e`
- Run key:
  `13a1d508ef7246d2d70da51cd7fb50877a15ce46e0d515cb8a8292cbb5ca20bf`
- Artifact digest:
  `b1ba3e856332bb1397212ac12792cb534d95aca4594c5493a73271b1ec3f877b`
- External summary SHA-256:
  `bae1f59e36f249610905e970084ea72c2dd7e5926733c5acb82edfcc68341713`
- Compact evidence:
  `artifacts/dante_light/o3a_native_v1/initial_thresholds.json`

## Verification

- 1,000,000 complete-block bootstrap replicates per detector.
- Point estimate: all 5,000 rows per detector.
- Bootstrap estimate: first 4,998 rows, 294 complete blocks of 17.
- Independent full replay: byte-identical numeric threshold result.
- Focused Windows suite: 16 passed.
- Focused WSL suite: 16 passed, 11 upstream warnings.
- WSL Ruff: passed.

## Next gate

The primary scan remains closed until these realized widths have been shown to
the author.  No scan process has been started.


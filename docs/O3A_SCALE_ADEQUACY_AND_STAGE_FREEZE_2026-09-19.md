# O3a scale adequacy and methodological-parity freeze

Date: 2026-09-19

## Decision

The five stage blocks proposed in
`config/dante_o3a_native_v1_stage_decision_gate.json` are author-approved
without O3a-specific hyperparameter tuning. The approved design keeps the
corrected-O4a architecture and statistics while requiring fresh O3a-only
populations, embeddings, index, calibration scores, thresholds, classes, and
downstream products.

The unresolved decision gate remains immutable historical evidence. The
approval is recorded separately in
`config/dante_o3a_native_v1_stage_contract.json`.

## Scale check

The audit reads only the frozen public `CBC_CAT1` segment geometry and
checked-in method contracts. It reads no strain, scores, classes, or candidate
outcomes.

| Quantity | H1 | L1 |
|---|---:|---:|
| CBC_CAT1 livetime (s) | 11,218,675 | 11,956,179 |
| Eligible 32 s starts with complete 4 s context | 349,925 | 372,986 |
| Fraction of corrected-O4a eligible count | 87.17% | 91.01% |
| Eligible 64 s calibration starts | 174,967 | 186,491 |
| 5,000 calibration rows as pool fraction | 2.86% | 2.68% |
| Greedy capacity at at least 96 s separation | 116,810 | 124,494 |
| 647 index rows as separated-pool fraction | 0.554% | 0.520% |

O3a is therefore smaller than corrected O4a in eligible scan starts, but the
fixed calibration and index samples are *denser*, not sparser, relative to the
available geometry. The calibration pool exceeds the target by 35.0x (H1)
and 37.3x (L1); the index pool exceeds its target by 180.5x and 192.4x.

For each detector, 5,000 calibration rows retain 50 nominal observations in
the upper 1% tail. Block length 17 yields 294 complete non-overlapping blocks;
the point estimate uses all 5,000 rows and two rows are outside complete-block
resampling. This is the same nominal design used for corrected O4a. The index
cohort also retains exactly 1,294 windows, 1,771,486 patch tokens, K=1,216,
the 50,000-token raw sample, and seed 42.

## Interpretation boundary

This is a scale/parity adequacy result, not a guarantee about the realized
score distribution. A score-space confidence-interval width cannot be known
before scoring because it depends on density near p99 and temporal
dependence. The run must therefore fail closed if:

- either selected population cannot reach its frozen cardinality after all
  cross-population guards;
- the realized block-bootstrap interval is non-finite or degenerate;
- the p99 point estimate is not contained in its interval; or
- any detector-specific completeness, disjointness, hash, or provenance gate
  fails.

No new CI-width cutoff is introduced after seeing O3a. Such a cutoff would be
a new scientific decision, not methodological parity.

## Execution boundary

Only outcome-blind identity-manifest preparation is now authorized. Strain
access, scoring, threshold fitting, and the full scan remain disabled until
the disjoint O3a population manifests and their guards are frozen and
verified.

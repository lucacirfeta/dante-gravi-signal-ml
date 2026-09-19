# O3a initial-calibration selector freeze

Date: 2026-09-19

## Decision

The initial O3a detector-specific calibration population uses the approved
outcome-blind, hash-stratified complete-block selector. This checkpoint
freezes the selector and its 5,000-row-per-detector preselection plan using
public CBC_CAT1 geometry only. It does not read strain or outcomes.

## Exact selector

For each detector:

1. Start from the frozen 64 s-aligned proposal universe.
2. Within each CBC_CAT1 segment, split the chronological windows into
   non-overlapping blocks of 17 rows and discard incomplete segment tails.
3. Sort the complete blocks chronologically and partition them into 295
   integer-quantile strata using
   `[floor(i*N/295), floor((i+1)*N/295))`.
4. Within each stratum, rank blocks by SHA-256 of the selector-contract
   digest, detector, stratum index, and all 17 integer GPS starts.
5. The rank-zero block is the frozen provisional choice. If raw validation
   later rejects it, only the next hash-ranked block in the same stratum may
   replace it. Exhausting a stratum fails closed; blocks are never moved
   across strata.
6. The 295 blocks provide 5,015 proposed rows. The ordered output retains
   5,000: 4,998 rows form 294 complete bootstrap blocks and two final rows are
   used only by the all-row p99 point estimate.

## Frozen scale

| Quantity | H1 | L1 |
|---|---:|---:|
| Complete candidate blocks | 10,044 | 10,731 |
| Candidate blocks per stratum | 34-35 | 36-37 |
| Selected provisional blocks | 295 | 295 |
| Planned output rows | 5,000 | 5,000 |
| Complete bootstrap rows | 4,998 | 4,998 |
| Point-estimate-only tail rows | 2 | 2 |

## Raw acceptance boundary

Raw validation is atomic at the 17-row block level. Every row must have exact
symmetric context and finite output through raw loading, whitening-before-
crop, Q-transform, frozen DINOv2 encoding, and primary O3b-K275 scoring.
Neither the score value nor a derived class may influence acceptance.

No excess-power veto is applied to this *initial threshold calibration*
population. That preserves the established threshold-population semantics;
the separately defined native-index/background cleaning rule is not silently
imported into this stage.

This freeze does not authorize raw validation, scoring, threshold fitting, or
the primary scan. Those steps require a separately verified execution
contract and provenance-complete raw inventory.

## Canonical records

- `config/dante_o3a_initial_calibration_selector_v1.json`
- `config/dante_o3a_initial_calibration_plan_v1.json`

They are regenerated and checked with:

```bash
python scripts/freeze_dante_o3a_initial_calibration.py
```

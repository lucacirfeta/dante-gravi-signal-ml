# O3a outcome-blind identity universes

Date: 2026-09-19

## Scope

This checkpoint freezes the complete geometric identity universes implied by
the public O3a CBC_CAT1 snapshot and the approved detector-aware stage
contract. It does not read strain, evaluate raw quality, score windows, or
select calibration/index members.

The canonical machine-readable record is
`config/dante_o3a_native_v1_identity_universes.json`.

## Frozen geometry

All identities use a 32 s analysis window, require complete symmetric 4 s
whitening context, and are aligned to the approved grid.

| Role | Stride | H1 | L1 |
|---|---:|---:|---:|
| Primary-scan geometric universe | 32 s | 349,925 | 372,986 |
| Initial-calibration proposal universe | 64 s | 174,967 | 186,491 |

The manifest stores compact lossless ranges and SHA-256 digests of the fully
expanded ordered identity streams. Regeneration fails closed if the DQ
snapshot, approved stage contract, implementation, entry point, counts, or
range geometry changes.

## Scientific boundary

The phrase `OUTCOME_BLIND_HASH_STRATIFIED_COMPLETE_RUN_BLOCKS` in the approved
stage contract does not yet specify the exact stratum boundaries, quota
allocation, or raw-quality acceptance rule. Therefore this checkpoint does
not silently choose the 5,000 calibration members per detector.

Before strain access, a separate author-approved contract must freeze those
details and then prove population separation. This keeps geometry derivation
separate from a scientific sampling decision and prevents post-hoc selection.

## Verification

The checked-in manifest is regenerated deterministically by:

```bash
python scripts/freeze_dante_o3a_identity_universes.py
```

Targeted tests expand every compact range, prove uniqueness/alignment and the
strict calibration-proposal subset relation, and reject range drift.

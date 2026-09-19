# Phase 07 plan 06 summary

## Delivered

- Converted the author-approved selector into a versioned fail-closed
  contract.
- Froze deterministic provisional calibration plans for H1 and L1.
- Added exact same-stratum fallback and raw acceptance semantics for the later
  execution stage.
- Added deterministic regeneration, drift rejection, geometry, cardinality,
  balance, and subset tests.

## Scientific boundary preserved

No strain, score, class, or outcome data were accessed. Excess-power vetoing
is explicitly absent from the initial calibration population; score values
may not affect raw acceptance. The resulting rows are provisional until a
separate raw-validation run accepts one complete block in every stratum.

## Verification

- Deterministic contract/plan regeneration: passed.
- Windows regression: 86 passed.
- WSL regression: 86 passed, 11 upstream warnings.
- WSL Ruff: passed.

## Next gate

Freeze a provenance-complete O3a raw inventory and execution contract. Do not
start scoring or threshold fitting under this preselection-only checkpoint.

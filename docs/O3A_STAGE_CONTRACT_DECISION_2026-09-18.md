# O3a stage-contract decision gate

Status: **AUTHOR DECISION REQUIRED; NO STRAIN OR OUTCOME ACCESSED**

## What is already fixed

The O3a run, H1/L1 detector scope, official GPS bounds, public `CBC_CAT1`
semantics, WSL/CUDA runtime, DINOv2 encoder, initial O3b source dictionary,
fresh O3a-only scientific artifacts, and diagnostic-only A2 role are already
frozen. The public DQ snapshot contains 545 H1 segments (11,218,675 s) and 535
L1 segments (11,956,179 s).

## Recommended option: methodological parity with fresh O3a data

The checked-in gate recommends preserving the corrected O4a methodology while
rebuilding every run-dependent artifact from O3a:

- 5,000 outcome-blind calibration windows per detector for the initial and
  native thresholds;
- 647 detector-specific index windows per detector;
- complete symmetric 4 s whitening context, 96 s within-detector separation,
  and the explicit 128 s cross-population start-time guard;
- a completely new O3a index with K=1216, a deterministic 50,000-token raw
  sample, and the already frozen encoder;
- detector-specific p99 thresholds with a non-overlapping block bootstrap
  (block length 17, 1,000,000 replicates, 95% interval);
- asymmetric robust-seed coincidence follow-up, with pooled-null exceedances
  described only as a diagnostic PEM shortlist; no global-significance claim
  without a full-pipeline repeated time-slide null.

These numbers are copied only as **methodological design constants** from the
hash-identified corrected-O4a contracts. No O4a windows, embeddings, indices,
scores, thresholds, classes, or candidate outcomes are imported.

## Alternative

An O3a-adaptive design could tune K, cohort size, block length, or threshold
settings on O3a. That would require a separate development population,
held-out validation, explicit selection criteria, and a larger experiment.
It would reduce direct O3a/O4a comparability and create more opportunities for
run-specific tuning. It is therefore not recommended for the first transfer.

## Required decision

Approval is needed for five linked entries in
`config/dante_o3a_native_v1_stage_decision_gate.json`:

1. initial calibration and full scan grid;
2. population firewall and cardinalities;
3. native-index architecture constants;
4. native-threshold block-bootstrap statistics;
5. coincidence interpretation and global-claim boundary.

Until all five are approved, `execution_allowed` remains false and no strain,
window selection, scoring, fitting, index construction, or scan may start.

# DANTE-Light L4 v6 Phase-B screening freeze

Date: 2026-08-25

Status: **FROZEN TRAINING-ONLY SCREENING; PHASE C/D AND O4b REMAIN SEALED**

## Purpose

Phase B tests the three outcome-blind hypotheses identified after v5:
aggregation mismatch, insufficient student capacity, and mismatch between
SmoothL1 regression and rank fidelity. It selects one configuration from five
on fresh O4a training-only blocks. This is model screening, not confirmatory
evidence; only the independently sealed Phase C can confirm fidelity.

## Five frozen arms

All arms use the same 144 fit and 36 internal-validation blocks per detector,
eight windows per block, the native O4a teacher target, five common replicate
seeds, and identical optimization/checkpoint rules.

1. v5 global-average architecture + SmoothL1;
2. teacher-top-fraction architecture + SmoothL1;
3. attention-MIL architecture + SmoothL1;
4. 2x-width teacher-top-fraction architecture + SmoothL1;
5. matched-width teacher-top-fraction architecture + equal-gradient
   SmoothL1/RankNet.

Arms 1 versus 2/3 isolate aggregation, 2 versus 4 capacity, and 2 versus 5
the objective. No arm is declared primary before results.

## Exact hybrid objective

RankNet uses all 28 unordered pairs among the eight windows inside the same
detector/4,096 s block. Exact teacher ties are excluded. Loss is averaged by
pair, block, then detector; cross-block and cross-detector pairs are forbidden.

The hybrid is not full GradNorm and has no hidden balancing optimizer. For
each batch, gradients over all trainable parameters are computed separately:

`g_final = ||g_value|| (g_value/||g_value|| + g_rank/||g_rank||) /
||g_value/||g_value|| + g_rank/||g_rank||||`.

Thus each component contributes one unit direction and the final update is
rescaled to the SmoothL1 gradient norm. There is no balancing learning rate,
EMA, warm-up, clipping, bound, or post-hoc sweep. A zero/non-finite component
norm, cancelling/non-finite combined direction, or non-finite assigned
gradient fails the replicate. Component norms, equivalent detached lambda,
cosine, direction norm, and final norm are recorded at every step.

## Optimization and checkpoint

The inherited AdamW contract is fixed: learning rate `1e-3`, weight decay
`1e-4`, betas `(0.9, 0.999)`, batch 64 as four whole blocks from each detector,
100 epochs, float32, no scheduler, no AMP, no early stopping, and no gradient
clipping.

The checkpoint is chosen identically for every arm by maximum
worst-detector internal-validation Spearman. Exact ties use lower
equal-detector mean SmoothL1, then the earliest epoch. An epoch with non-finite
Spearman is ineligible; no eligible epoch after 100 epochs is a failed
degenerate replicate. This metric change from v5 is applied to all arms and is
aligned with the rank-fidelity question rather than favoring the hybrid alone.

## Screening selection and multiplicity

Any arm with one failed replicate is excluded. Surviving arms are ranked by:

1. largest minimum Spearman over all H1/L1 x five-replicate validation cells;
2. lower worst-cell SmoothL1;
3. lower Phase-A mean CPU batch-one inference cost;
4. fewer trainable parameters;
5. lexicographic arm ID.

The winner must have worst-cell Spearman at least 0.90 even to be eligible for
a later Phase-C unlock request. Passing this floor does not itself open Phase
C. Selecting the best of five is explicitly exploratory; no Phase-B p-value,
confidence interval, or best-arm result is confirmatory.

## Reproducibility anchors

- contract: `config/dante_light_prefilter_v6_phase_b_freeze.json`;
- contract digest:
  `ec139bfb525993e45616fcb07f6fd485d622b408441094b0292848407ca52af7`;
- compact artifact:
  `artifacts/dante_light/prefilter_l4_v6_design/phase_b_freeze_v6.json`;
- artifact digest:
  `e3995f7fc4c60d73d4bd090f179c1ad04a6c664372c81c71b0b9b141e7fbb56a`;
- objective/selection implementation:
  `src/dante_light/prefilter_v6_phase_b.py`;
- verifier: `scripts/verify_dante_light_prefilter_v6_phase_b.py`.

No Phase-C/Phase-D/O4b outcome or morphology label was accessed. The next
authorized operations are downloading only the frozen missing intervals to
the E: cache and building the Phase-B native-teacher ledger. Phase C remains
sealed regardless of the Phase-B result until a separate checkpoint.

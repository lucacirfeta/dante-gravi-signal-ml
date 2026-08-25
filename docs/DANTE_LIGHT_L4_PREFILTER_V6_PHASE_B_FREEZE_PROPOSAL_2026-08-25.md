# DANTE-Light L4 v6 Phase-B freeze proposal (2026-08-25)

Status: **PROPOSAL ONLY; OBJECTIVE, POPULATION, PHASE B, AND TRAINING REMAIN UNFROZEN**

This checkpoint follows the verified Phase-A compute audit, the v5
training-only diagnosis, and the pre-Phase-B gradient/capacity audit. It does
not access teacher targets, morphology labels, development, confirmation, or
O4b outcomes and does not authorize raw-data fetching or training.

## Planning-capacity evidence

The outcome-blind planning artifact is
`artifacts/dante_light/prefilter_l4_v6_design/phase_b_planning_audit_v6.json`
(digest `ae952993311059f0d96a2212f7e8d5f2548869847991c2061cecee202835a6fe`).
It enumerates the frozen GWOSC CBC_CAT1 snapshot, removes hardware/CBC/burst
injection overlaps, and excludes every detector/4,096 s block used by a prior
protocol or assigned to v5.

| Detector | Official eligible blocks | Eligible already local | Additional fetch needed for full pool |
|---|---:|---:|---:|
| H1 | 606 | 475 | 131 |
| L1 | 576 | 422 | 154 |

These are identity-only capacities, not guarantees of successful downloads.
L1 is the limiting detector. Raw availability must not be used as a scientific
selection criterion: partitions should be assigned from the official eligible
pool first, after which missing selected intervals can be mirrored on `E:`.

## Recommended population contract

The recommended allocation is the unselected planning scenario
`balanced_training_and_later_gates`:

| Partition | Blocks per detector | Background windows per block | Role |
|---|---:|---:|---|
| Phase B selection | 180 | 8 | fresh fit/internal-validation ablation |
| Phase C training confirmation | 60 | **1** | sealed one-shot fidelity confirmation |
| Phase D development | 150 | 1 initially | fresh routing/cost development |
| Phase D confirmation | 150 | 1 initially | sealed routing/cost confirmation |

The allocation consumes 540 blocks per detector and leaves buffers of 66 H1
and 36 L1 blocks. Phase B should split its blocks 80/20 within detector into
144 fit and 36 internal-validation blocks. The smaller split is selection-only;
it is not the confirmatory fidelity endpoint.

Admission of CAT1-partial blocks is acceptable only under all of the following
predeclared protections:

1. the independence unit remains detector/4,096 s block;
2. every uncertainty interval and bootstrap resamples whole blocks;
3. no Wilson or effective-sample claim treats the eight windows as independent;
4. partition assignment is deterministic and stratified within detector by
   available valid-start-span quantile, so a partition cannot silently become
   a sample of unusually long or unusually short CAT1 fragments;
5. the eight training windows are chosen deterministically to cover the valid
   span rather than clustered at one boundary;
6. local-versus-remote availability is recorded as provenance but never used
   to rank or select blocks.

This is preferred to imposing a post-audit minimum span such as 1,600 s. Such
a cut is mechanically feasible but would redefine the target population and
would need a new scientific justification. Span stratification preserves the
eligible CBC_CAT1 population while making the changed sampling geometry
visible and balanced.

The Phase-D background precision will be lower than v5 because there are 150,
not 300, independent blocks per detector. The resulting interval must be
reported honestly using block bootstrap. No v5 Wilson half-width or prospective
power statement is inherited. If this precision is insufficient at the later
freeze, Phase D must be redesigned rather than borrowing Phase-B/C blocks.

## Recommended objective contract

The fixed `lambda = 1` proposal is rejected. The committed audit found the
SmoothL1-to-RankNet trainable-parameter gradient ratio at initialization to
range from 14.118 to 298.890 across the five frozen initializations. Freezing
the median 179.106 would be equally weak: it would over-amplify some replicas
and under-amplify others, and the ratio is not stationary during training.

The recommended hybrid comparator is a predeclared per-batch equal-gradient
scalarization, not a tuned fixed multiplier and not the full GradNorm
algorithm:

1. compute detector-balanced SmoothL1 `L_value` and same-detector,
   same-4,096 s-block RankNet `L_rank` over the 28 unordered pairs among the
   eight windows;
2. compute their L2 gradient norms over all trainable parameters before the
   optimizer step;
3. set the detached batch weight
   `lambda_t = ||grad L_value|| / ||grad L_rank||`;
4. rescale the combined gradient back to the SmoothL1 gradient norm, so the
   hybrid arm does not receive a systematically larger optimizer step than its
   SmoothL1 comparator;
5. fail the replicate on a zero, non-finite, or numerically undefined component
   norm; do not clip, sweep, smooth, or repair `lambda_t` post hoc;
6. record both component norms, `lambda_t`, their cosine, and the final combined
   norm for every optimization step.

Adaptive gradient balancing is motivated by GradNorm, but the proposed rule is
a simpler fixed algorithm with no training-rate hyperparameter
([Chen et al., ICML 2018](https://proceedings.mlr.press/v80/chen18a.html)).
The use of rank information for teacher/student ordering is hypothesis-level
motivation only, consistent with ranking distillation work
([Reddi et al., AISTATS 2021](https://proceedings.mlr.press/v130/reddi21a.html));
neither reference validates this DANTE-specific objective.

No SmoothL1-only warm-up is recommended. A fixed warm-up would introduce a new
epoch count without solving the observed cross-replica scale variability by
construction. The unchanged SmoothL1 arm remains the required ablation.

## Proposed Phase-B matrix

All arms use the same fresh blocks, detector-balanced block batches, AdamW
contract, five seeds, maximum epochs, checkpoint rule, and failure policy.

1. v5 global-average architecture + SmoothL1;
2. teacher-top-fraction architecture at matched width + SmoothL1;
3. attention-MIL architecture at matched width + SmoothL1;
4. teacher-top-fraction architecture at 2x width + SmoothL1;
5. teacher-top-fraction architecture at matched width + equal-gradient
   SmoothL1/RankNet hybrid.

This matrix isolates aggregation (1 versus 2/3), capacity within the
teacher-aligned family (2 versus 4), and objective (2 versus 5). It does not
claim that attention, larger capacity, or rank loss is already superior.

Selection in Phase B should be lexicographic and frozen before teacher scoring:

1. reject any arm with a numerically failed replicate;
2. rank surviving arms by the minimum internal-validation Spearman across all
   detector/replicate cells;
3. break an exact tie by lower worst-cell SmoothL1, then lower audited inference
   cost, then fewer parameters;
4. never select a favorable seed within an arm.

The selected arm then enters sealed Phase C. Its dedicated gate is now frozen
separately in `config/dante_light_prefilter_v6_phase_c_power.json`. Phase C
uses exactly one hash-selected paired observation from each fresh
detector/4,096 s block, so its sample size is 60 independent blocks rather
than 480 windows treated as independent. Every detector/replicate cell must
satisfy point Spearman at least 0.90 and a one-sided 95% Bonett--Wright lower
bound at least 0.85. Under the explicitly model-based alternative
`rho_s=0.95`, the approximate single-cell pass probability is 0.9764. No
familywise pass probability is claimed because dependence among the five
replicas is not assumed. Any bootstrap sensitivity analysis is non-gating and
may resample only whole detector/GPS blocks. No development or O4b access
follows automatically from a Phase-B winner.

## Decisions requiring confirmation

Before implementation or training, the scientific checkpoint must explicitly
approve or replace:

1. the 180/60/150/150 block allocation and span-stratified admission rule;
2. per-batch equal-gradient scalarization rather than a fixed `lambda` or full
   GradNorm;
3. the five-arm matrix and lexicographic Phase-B selection rule;
4. the separately frozen Phase-C fidelity gate and its model-based power
   boundary before Phase-B teacher outcomes are opened.

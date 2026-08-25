# DANTE-Light L4 v6 design options (2026-08-25)

Status: **DESIGN PROPOSAL; SCIENTIFIC FREEZE NOT AUTHORIZED**

## What v5 now establishes

V5 does not fail because protected morphologies are discarded at its selected
thresholds. It fails because its students do not reproduce the teacher order
with the required fidelity and cannot avoid enough exact-path calls. The
training-only diagnostic further shows that rank fidelity is already low on
the fit background, while Pearson agreement is substantially higher. A
generalization-only repair is therefore not a well-supported next step.

The successor should test three distinct hypotheses without changing more than
one axis at a time:

1. **Aggregation mismatch**: global averaging suppresses localized transient
   evidence relative to the exact teacher's top-k patch MIL score.
2. **Capacity mismatch**: 1,369--3,665 parameters may be too restrictive for a
   32 s, 4,096 Hz input and a DINOv2/VQ/MIL teacher.
3. **Objective mismatch**: SmoothL1 can preserve large-scale score amplitude
   without preserving the ordering targeted by the Spearman gate.

None is yet a demonstrated cause.

## Recommended logical sequence

### Phase A — outcome-blind compute feasibility

Implement no training and inspect no teacher outcomes. Benchmark random-weight
candidate graphs on frozen synthetic or cached strain inputs:

- the unchanged v5 raw 1-D/global-average model as the mandatory baseline;
- the same local encoder with a localized MIL-style aggregation operator;
- one larger raw 1-D encoder with the same localized aggregation.

Measure parameter count, preprocessing cost, CPU/GPU batch-one latency, and
peak memory. This phase selects only architectures that can plausibly yield a
positive compute balance; it cannot select a scientific winner.

The primary architectural direction should preserve local instance scores and
aggregate them with a differentiable analogue of the teacher's top-k behavior.
Attention pooling is a reasonable comparator, not an automatic primary. Exact
pooling temperature, retained fraction, width, depth, receptive field, and
parameter budgets must be frozen before benchmarking; they are not set in this
document.

### Phase B — fresh training-only factorial ablation

Use new training blocks, not the v5 fit/validation identities, for any
confirmatory v6 comparison. Include:

- v5 architecture + SmoothL1 reproduction control;
- aggregation-only change at matched capacity and SmoothL1;
- capacity-only change with the baseline objective;
- a predeclared hybrid value-plus-rank objective on the selected architecture
  family.

The objective comparator should retain a pointwise component because the
student ultimately needs a usable score scale, while adding a within-detector
rank component aligned with the fidelity endpoint. Replacing SmoothL1 with an
unconstrained rank-only loss would make threshold calibration fragile. The
exact loss, weighting, pair/list construction, and dependency choice require
a separate freeze.

All comparisons need the same optimizer family, batch/block construction,
replicate seeds, maximum epochs, and checkpoint rule unless the protocol
explicitly identifies an optimization ablation. A single favorable seed is
never promotable.

### Phase C — training confirmation before development

The architecture and objective chosen in Phase B must be evaluated once on a
second, sealed set of training-only blocks. This prevents selecting and
confirming a successor on the same internal validation outcomes. Only a
predeclared worst-replicate training-fidelity gate may authorize creation of a
fresh development cohort.

### Phase D — fresh development and conditional confirmation

Development, confirmation, and any later-run O4b stage require new identities
and a new seal. Known glitches and injections remain separate by detector and
morphology. The operational gate must again combine prefilter cost, avoided
exact-path cost, deterministic audit calls, and block-bootstrap uncertainty.
V5 confirmation stays sealed permanently; it is not inherited by v6.

## Alternative task formulation: selective deferral

The production task is a cascade: a cheap model may defer difficult windows to
exact DANTE. Selective prediction or learning-to-defer could therefore be more
natural than global score imitation. However, this is not a free repair:

- training a rejector on known-glitch or injection retention changes the task
  from label-blind score distillation to supervised routing;
- using development morphologies in the loss would contaminate the later gate;
- a risk-coverage PASS would not establish physical novelty sensitivity.

For these reasons, selective deferral should remain a separately scoped
secondary proposal until its data architecture and scientific claims are
reviewed. It must not be mixed silently into the score-surrogate experiment.

## Reviewer assessment

The most defensible primary direction is a fresh raw-strain student with
localized MIL-style aggregation, evaluated against a capacity-matched global
average control and trained with both value and rank information. This follows
the exact teacher structure more closely and directly addresses the observed
Pearson/Spearman split. It is still a hypothesis: a negative outcome would not
be surprising because the DINOv2/VQ representation may contain information
that a cheap raw-strain network cannot recover at the permitted cost.

The next checkpoint must approve the architecture feasibility matrix and the
rank-aware loss family before code is written. Exact numerical budgets and
gates should come from outcome-blind compute measurements and a new power
analysis, not from the v5 development result.

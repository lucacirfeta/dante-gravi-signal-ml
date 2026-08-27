# DANTE-Light L4 v6 Phase A compute freeze (2026-08-25)

Status: **FROZEN OUTCOME-BLIND COMPUTE FEASIBILITY; NO TRAINING OR PROMOTION**

The machine-readable contract is
`config/dante_light_prefilter_v6_phase_a.json`. Phase A may instantiate
random-weight graphs and measure batch-one cost and memory on deterministic
synthetic strain. It may not read teacher scores, morphology labels,
development, confirmation, or O4b; train a model; select a scientific winner;
or enable routing.

## Correction to the top-k interpretation

The teacher's `top_k = 68` and the O3b primary codebook size `K = 275` refer
to different axes. The 275 entries are VQ centroids used to assign a novelty
score to each patch. The exact DANTE teacher then ranks **1,369 patch anomaly
scores** (a 37 x 37 DINOv2 patch grid) and averages the largest 68. Moreover,
the v5 student target is the native O4a score using the K=1,216 native index,
not the O3b K=275 primary score. Therefore `68/275` is not an aggregation
fraction.

The Phase-A student aggregation fraction is frozen as

`68 / 1369 = 0.0496712929...`.

For a student with `N` temporal instances, the retained count is the nearest
integer `floor(N * 68 / 1369 + 0.5)`, with a minimum of one. The 32 s v5 local
encoder emits 256 instances, so its teacher-aligned count is 13. The value 68
is loaded from the versioned v5 teacher contract; it is not duplicated as an
independent code constant.

## Aggregation operator boundary

Phase A benchmarks the exact top-fraction mean used by the teacher rather than
silently choosing a temperature for a smooth top-k relaxation. `torch.topk`
is piecewise differentiable through the selected values, but it is not a
fully smooth ranking relaxation. A temperature, sorting relaxation, or rank
loss would alter optimization and must be frozen separately before Phase B.

## Frozen candidate matrix

1. unchanged v5 raw 1-D/global-average baseline;
2. the same local encoder with local scores and exact teacher-fraction mean;
3. the same local encoder with single-head attention MIL as comparator;
4. a uniformly width-doubled raw encoder with exact teacher-fraction mean.

The x2 arm is the smallest geometric capacity step above the baseline. It is
not a claim that x2 is optimal. Phase A can only reject graphs that are plainly
compute-infeasible for later controlled training.

## Interpretation boundary

A favorable latency or memory result does not establish teacher fidelity,
protected-morphology retention, useful call reduction, positive net saving,
or physical sensitivity. Those outcomes require fresh, separately frozen
training and protected evaluation stages.

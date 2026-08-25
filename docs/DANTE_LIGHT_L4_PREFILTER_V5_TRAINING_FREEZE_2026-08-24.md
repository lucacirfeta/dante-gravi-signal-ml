# DANTE-Light L4 prefilter v5 training freeze

Date: 2026-08-24

Status: **FROZEN TRAINING-ONLY; NO DEVELOPMENT, CONFIRMATION OR O4b ACCESS**

## Closed teacher prerequisite

The native-O4a teacher ledger is complete for all 19,200 frozen training
windows in 2,400 detector/GPS blocks. Its artifact digest is
`8280f0e8a9e68ed12816a2778ac3ee93d71d3aaa28ac0cc6ecf35c442ed139e7`.
Two frozen H1/L1 windows replayed with exact float32 score and image hashes,
and the full repository suite passed before this freeze.

The teacher is the continuous `native` O4a novelty score used by the actual
DANTE-Light decision path. The historical `primary` O3b score is not a target,
no threshold is applied to the teacher, and the target is not interpreted as a
physical truth label.

## Internal training-only split

The split unit is the detector-specific 4,096 s GPS block. A deterministic
SHA256-derived permutation assigns 90% of the blocks to model fitting and 10%
to internal validation, separately for H1 and L1. No block appears in both
subsets.

| detector | fit blocks | validation blocks | fit windows | validation windows |
|---|---:|---:|---:|---:|
| H1 | 1,080 | 120 | 8,640 | 960 |
| L1 | 1,080 | 120 | 8,640 | 960 |

The teacher target is reconstructed from its canonical float32 hexadecimal
serialization. Per-detector population mean and standard deviation are fitted
only on the fit subset; validation is excluded:

| detector | fit mean | fit standard deviation (`ddof=0`) |
|---|---:|---:|
| H1 | 0.07234671520138228 | 0.03878881579375258 |
| L1 | 0.07293721426761261 | 0.047578581611466074 |

Targets are standardized with these frozen values and are never clipped.

## Optimization contract

Both frozen architectures and all five protocol-derived replicates use exactly
the same optimization rule:

- AdamW with learning rate `1e-3`, weight decay `1e-4`, betas `(0.9, 0.999)`,
  epsilon `1e-8`, and `amsgrad=false`;
- SmoothL1 loss with `beta=1` and mean reduction;
- detector-balanced batches of 64 windows: 32 H1 and 32 L1;
- float32 inputs and model parameters, without automatic mixed precision;
- at most 100 epochs, no gradient clipping and no early stopping;
- checkpoint selection by minimum equal-detector mean validation SmoothL1,
  with an exact tie resolved toward the earliest epoch.

There is intentionally **no learning-rate scheduler**. The fixed learning rate
is a simplicity and comparability choice that reduces post-hoc flexibility;
checkpoint selection mitigates late oscillation without introducing cosine or
plateau scheduling.

## Fail-closed replicate behavior

NaN or Inf in an input, activation, prediction, loss, gradient, optimizer
state, or model parameter marks that replicate `FAILED`. Under the frozen
worst-replicate promotion rule, one numerically failed replicate prevents the
candidate architecture from being promoted. An infrastructure interruption is
instead `INCOMPLETE`: it may be rerun only with the same frozen seed and
contract and is not converted into scientific failure or PASS.

No morphology label enters the loss or checkpoint selection. Development,
confirmation and O4b remain unopened, and this freeze does not authorize
threshold selection, confirmation unlock or runtime routing.

## Reproducibility anchors

- training contract digest:
  `e2d21a930d71fe8ff276c0b3814ccaf73603fdaba02bd27cce2f400bd38a3e25`;
- internal split manifest: 2,400 block assignments;
- compact teacher-target manifest: 19,200 ordered rows;
- large whitened-strain shards remain in the run-keyed cache under the
  `DANTE_V5_CACHE_ROOT` environment alias.

The compact manifests contain portable repository-relative references and are
cross-checked against the run-keyed cache by the fail-closed verifier.

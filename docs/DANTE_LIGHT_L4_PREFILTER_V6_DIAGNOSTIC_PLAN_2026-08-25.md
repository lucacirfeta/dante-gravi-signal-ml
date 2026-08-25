# DANTE-Light L4 successor diagnostic plan (2026-08-25)

Status: **TRAINING-ONLY DIAGNOSTIC COMPLETE; NO V6 SCIENTIFIC PROTOCOL**

Execution update: Increments 1--2 completed with result digest
`4910f695528342962e16b226f7e1fb27129a3ea92f5c029be0445c7a7220232b`.
The bounded interpretation is recorded in
`docs/DANTE_LIGHT_L4_PREFILTER_V5_TRAINING_DIAGNOSTIC_RESULT_2026-08-25.md`.
Increment 3 remains a human scientific checkpoint.

## Objective and boundary

V5 failed because all ten frozen students missed detector-wise teacher
fidelity and useful background-call reduction, while protected retention
passed. The immediate question is whether the observed fidelity deficit is
already present on the v5 fit identities or appears mainly between the fit and
internal-validation blocks.

This increment is a retrospective, exploratory diagnosis of the already-open
v5 training partition. It does not train a new model, select a replicate,
change a threshold, use morphology labels, or inspect v5 development,
confirmation, or O4b. It cannot change `V5_NOT_READY` or authorize routing.

## Code-grounded motivation

The exact teacher averages its 68 largest anomaly scores among 1,369 DINOv2
patches. The v5 raw student has 3,665 trainable parameters, a final temporal
receptive field of 1,167 samples (about 0.285 s at 4,096 Hz), and global average
pooling over the full 32 s input. The complex-STFT comparator has 1,369
parameters and also ends in global average pooling. Consequently, a plausible
but unproven failure mechanism is mismatch between localized extreme-patch
aggregation in the teacher and global-average aggregation in both students.
The present diagnostic cannot prove that mechanism; it can only distinguish a
failure already visible on fit identities from a larger generalization gap.

This distinction matters methodologically. Large teacher--student capacity
gaps can impede distillation, rank-oriented objectives can differ materially
from pointwise regression, and multiple-instance aggregation should match the
bag-level structure being approximated. Relevant primary references are:

- Mirzadeh et al., *Improved Knowledge Distillation via Teacher Assistant*,
  AAAI 2020: <https://arxiv.org/abs/1902.03393>;
- Blondel et al., *Fast Differentiable Sorting and Ranking*, ICML 2020:
  <https://proceedings.mlr.press/v119/blondel20a.html>;
- Reddi et al., *RankDistil: Knowledge Distillation for Ranking*, AISTATS
  2021: <https://proceedings.mlr.press/v130/reddi21a.html>;
- Ilse et al., *Attention-based Deep Multiple Instance Learning*, ICML 2018:
  <https://proceedings.mlr.press/v80/ilse18a.html>.

These works motivate hypotheses and candidate experiment axes; they do not
show that any one mechanism explains DANTE-Light v5.

## Frozen diagnostic matrix

The machine-readable specification is
`config/dante_light_prefilter_v5_training_diagnostic.json`. For both frozen
architectures, all five frozen replicates, both internal subsets, and H1/L1
separately, the diagnostic reports:

- point Spearman agreement with the native O4a teacher;
- point Pearson agreement;
- SmoothL1 with the beta inherited from the frozen v5 parent contract;
- prediction and target standard deviations.

There is no confidence interval and no PASS/FAIL threshold. The output is
descriptive and must not be used to retain a favorable seed.

## Executable implementation plan

### Increment 1 — deterministic diagnostic

Files:

- `src/dante_light/prefilter_v5_training_diagnostics.py`;
- `scripts/diagnose_dante_light_prefilter_v5_training.py`;
- `scripts/verify_dante_light_prefilter_v5_training_diagnostics.py`;
- `tests/test_dante_light_prefilter_v5_training_diagnostics.py`.

Action: verify every parent SHA256 and checkpoint hash, reconstruct the frozen
fit/validation block batches, score all ten checkpoints without shuffling,
compute only the frozen metrics, and write a compact digest-bound result.

Verification: unit tests must cover metric correctness, malformed boundaries,
non-finite values, digest tampering, and forbidden protected access. Exact
recomputation from the E: cache must match the compact result.

Done: one verified artifact exists with empty development, confirmation, and
O4b access lists and `candidate_promotion_allowed: false`.

### Increment 2 — scientific interpretation and v6 options

Files:

- `artifacts/dante_light/prefilter_l4_v5_training/diagnostics_v5.json`;
- this document or a separately versioned result note.

Action: classify the result only at the hypothesis level:

- low fit and validation rank motivates capacity, aggregation, optimization,
  and objective ablations;
- high fit but materially lower validation rank motivates support,
  regularization, and detector-generalization work.

Done: the report states what the diagnostic supports and what it cannot prove,
without changing v5.

### Increment 3 — human scientific checkpoint

No successor code or outcome access is authorized by Increments 1--2. Before
v6 training, a separate proposal must freeze:

- the architecture/capacity matrix and aggregation operator;
- pointwise versus rank-aware objective comparators;
- fresh train/development/confirmation identities;
- cost, fidelity, protected-retention, and useful-reduction gates;
- the role, if any, of selective deferral rather than full score imitation.

Selective prediction and learning-to-defer are relevant alternatives because
the operational task is a cascade, not autonomous replacement of exact DANTE
([Geifman and El-Yaniv 2019](https://proceedings.mlr.press/v97/geifman19a),
[Mozannar and Sontag 2020](https://proceedings.mlr.press/v119/mozannar20b.html)).
They remain design options only: using protected morphologies or development
outcomes to train a rejector would create a new leakage/circularity risk and
is not authorized here.

## Plan-check result

The plan covers the stated diagnostic question, has an explicit parent-data
boundary, gives exact files and executable verification, and keeps the new
scientific choices behind a separate checkpoint. No development, confirmation,
O4b, threshold, cohort, or production-routing decision is hidden in this
increment.

# DANTE-Light L4 v5 training diagnostic result (2026-08-25)

## Decision boundary

The frozen retrospective diagnostic completed and verified. It used only the
already-open v5 training partition: 8,640 fit and 960 internal-validation rows
per detector. Development, confirmation, O4b, and morphology-label access
lists are empty. The result is descriptive, has no PASS/FAIL threshold, cannot
select a seed, and does not change `V5_NOT_READY`.

- Artifact digest:
  `0efeb42b207e563737e9aadaa20bf202e877d42046f456c26074c7d3bbdbb134`
- Deterministic result-matrix digest:
  `c74d7a2ca887e08a123c328e5d8f247492774f8a579d0f2e65f1f082e1b8b073`
- Verifier status:
  `PASS_VERIFIED_RETROSPECTIVE_TRAINING_ONLY_DIAGNOSTIC`
- Metric cells: 40 (2 architectures x 5 replicates x 2 subsets x 2
  detectors).

An independent second execution from the E: cache produced an identical
result matrix and access-count matrix. Its complete artifact digest differs
only because elapsed time is recorded as execution metadata.

## Rank and value fidelity

| Architecture | Subset | Detector | Spearman range | Pearson range | SmoothL1 range |
|---|---|---|---:|---:|---:|
| Raw 1-D | fit | H1 | 0.390--0.442 | 0.820--0.925 | 0.059--0.092 |
| Raw 1-D | fit | L1 | 0.163--0.229 | 0.781--0.884 | 0.070--0.096 |
| Raw 1-D | validation | H1 | 0.375--0.433 | 0.736--0.896 | 0.083--0.107 |
| Raw 1-D | validation | L1 | 0.191--0.223 | 0.624--0.785 | 0.130--0.189 |
| Complex STFT | fit | H1 | 0.051--0.277 | 0.612--0.833 | 0.087--0.121 |
| Complex STFT | fit | L1 | 0.033--0.126 | 0.510--0.705 | 0.110--0.139 |
| Complex STFT | validation | H1 | 0.057--0.324 | 0.562--0.788 | 0.105--0.152 |
| Complex STFT | validation | L1 | 0.102--0.188 | 0.365--0.655 | 0.180--0.226 |

The raw student is better than the STFT comparator, but neither ranks even its
fit-background teacher targets well, especially in L1. Fit and validation
Spearman ranges overlap strongly. Therefore the simple explanation "the model
fits the teacher well and fails only through out-of-sample generalization" is
not supported.

At the same time, Pearson agreement is much higher than Spearman agreement.
This means that the students capture part of the large-scale score variation
while failing to preserve the fine ordering of background windows. It is
consistent with a pointwise objective emphasizing large residuals or tail
variation more than rank, but it does not prove that objective mismatch is the
only cause. Capacity, temporal aggregation, optimization, and the narrow
background score distribution remain confounded.

The higher Spearman values measured on the mixed-role v5 development cohort
must not be substituted for these training-background values. The populations
are different: development fidelity includes background, robust candidates,
known glitches, and injections, which span a broader teacher-score support.

## Scientific conclusion

The diagnostic narrows the failure mode:

1. A pure fit-to-validation generalization failure is unlikely to be the main
   explanation.
2. The frozen SmoothL1 students do not learn the background ordering required
   by the Spearman gate, even on their fit identities.
3. High Pearson but low Spearman makes an objective/score-distribution mismatch
   a serious hypothesis.
4. The mismatch between teacher top-k patch aggregation and student global
   average pooling remains a code-grounded architectural hypothesis, not a
   causal result.

The correct next action is not another v5 retune. A successor needs a fresh,
predeclared training experiment that separates aggregation, capacity, and
objective effects before any new development cohort is opened.

## Reproduction

```text
python scripts/diagnose_dante_light_prefilter_v5_training.py \
  --cache-root E:/dante_cache/dante_light/prefilter_l4_v5_training \
  --device cuda

python scripts/verify_dante_light_prefilter_v5_training_diagnostics.py
```

The compact result is
`artifacts/dante_light/prefilter_l4_v5_training/diagnostics_v5.json`.

## Verification evidence

- Targeted diagnostic/training suite on the producing checkout: 25 passed.
- Full producing-checkout suite: 504 passed, 1 skipped, 0 failed.
- Fresh-clone diagnostic verifier: PASS; targeted tests: 5 passed.
- Full fresh-clone suite: 500 passed, 5 skipped, 0 failed.

The fresh-clone skips are explicit missing optional resources: published
reference artifacts, production reference index, calibrated thresholds, the
smoke-test reference index, and the `nds2` Python client. They are not v5/v6
diagnostic gates and were not converted into PASS.

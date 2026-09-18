# O3a native reconstruction: approved scope freeze

Status: **SCOPE AND PUBLIC DQ SNAPSHOT FROZEN; SCIENTIFIC EXECUTION STILL
FAIL-CLOSED**

## Approved decisions

On 2026-09-18 the author explicitly approved all four transfer decisions:

1. a complete, new, detector-aware **O3a-only** reconstruction;
2. public `CBC_CAT1` data-quality semantics for H1 and L1;
3. fresh O3a-only populations, native index, calibration, thresholds, classes,
   and downstream products, with no O4a scientific imports;
4. multiscale A2 as diagnostic-only, unable to promote a production candidate
   until independently validated on O3a.

The original unresolved record remains versioned at
`config/dante_o3a_native_v1_decision_gate.json`. The separate, self-digested
approval record is `config/dante_o3a_native_v1_authorization.json`; preserving
both avoids rewriting the historical gate after the decision.

## Frozen runtime

`config/dante_o3a_native_v1_runtime.json` records the verified WSL/CUDA
environment, Python executable, numerical/scientific packages, CUDA device and
driver, and the exact DINOv2 source/weight fingerprints. Windows scoring and
cross-environment shard reuse are prohibited.

The snapshot is validated against the live environment with:

```bash
python scripts/freeze_dante_o3a_native_v1.py --verify-only
```

## Reference bundle

The public reference bundle was downloaded and verified at its declared
SHA-256. The checkout's ignored `data/reference` directory is a local junction
to reusable storage on `E:`; this keeps the scientific data outside the source
tree while preserving the paths declared by `config/reference_artifacts.json`.

The historical O3b K=275 dictionary is admitted only as the declared source
representation for the initial primary scan. It is not an O3a-native artifact
and cannot supply the final native index, thresholds, or classes. The bundled
O4a K=1216 index is installed because it is a member of the immutable public
bundle, but the O3a scope contract explicitly forbids using it as a scientific
input.

## Why execution remains blocked

The public O3a `CBC_CAT1` snapshot is now frozen at
`config/dante_o3a_cbc_cat1_segments_v1.json`: 545 H1 segments covering
11,218,675 s and 535 L1 segments covering 11,956,179 s. Only DQ metadata was
queried; no strain or DANTE outcome was accessed.

The approved scope still does not determine stage-level population sizes,
guard duration, native clustering parameters, block-bootstrap configuration,
threshold quantile/confidence interval, or the coincidence multiple-testing
policy. These remain scientific choices and are presented, but not approved,
in `config/dante_o3a_native_v1_stage_decision_gate.json`.

Accordingly:

- `scope_execution_authorized` is `true`;
- `pipeline_execution_allowed` is `false`;
- no strain, window selection, score, fit, index build, or scan was accessed or
  started by this increment.

The next checkpoint is author approval of the explicit stage-level
outcome-blind population and statistical recommendations.

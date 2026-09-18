# O3a native reconstruction: approved scope freeze

Status: **SCOPE APPROVED; RUNTIME AND REFERENCES VERIFIED; SCIENTIFIC
EXECUTION STILL FAIL-CLOSED**

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

The approved scope does not determine stage-level population sizes, guard
duration, native clustering parameters, block-bootstrap configuration,
threshold quantile/confidence interval, or the coincidence multiple-testing
policy. These are scientific choices and are intentionally listed as
unresolved in `config/dante_o3a_native_v1_contract.json` rather than copied
from O4a or inferred from prior chat context.

Accordingly:

- `scope_execution_authorized` is `true`;
- `pipeline_execution_allowed` is `false`;
- no DQ snapshot, strain, window selection, score, fit, or scan was accessed or
  started by this increment.

The next checkpoint is a public O3a `CBC_CAT1` snapshot plus explicit,
stage-specific outcome-blind population and statistical contracts.

# O3a transfer-readiness gate

Status: **RESOLVED BY AUTHOR DECISION; PRESERVED AS THE PRE-DECISION RECORD**

The four decisions requested by this gate were approved on 2026-09-18. Their
self-digested authorization, frozen runtime, and fail-closed preparation
contract are documented in `docs/O3A_NATIVE_SCOPE_FREEZE_2026-09-18.md`. This
file retains the evidence and alternatives available before that decision.

## Question

Can the corrected detector-aware DANTE workflow be applied to public O3a data
without importing O4a thresholds, populations, indices, or multiscale claims?

The answer is **yes as a new run-specific reconstruction**, not as a parameter
substitution in the O4a contracts and not through the historical O3a scripts.

## Current evidence

The public GWOSC O3a interval used by the repository is
`[1238166018, 1253977218)`. A read-only query on 2026-09-18 returned:

| Detector | Public segments | Livetime (s) | Livetime (d) |
|:--|--:|--:|--:|
| H1 | 545 | 11,218,675 | 129.846 |
| L1 | 535 | 11,956,179 | 138.382 |

For both detectors, the public `DATA`, `CBC_CAT1`, and `BURST_CAT1` timelines
returned the same segment counts, endpoints, and total livetime. This observed
equality does not make the flag names interchangeable in a frozen contract; a
single semantic flag must still be selected before execution.

The local and external storage audit found:

- no O3a raw-data cache under `E:\dante_cache`;
- no modern O3a detector-aware cohort, native index, calibration ledger, or
  threshold artifact;
- 84.06 GiB free on `E:` at audit time;
- the canonical historical O3b K=275 index is declared in
  `config/reference_artifacts.json`, but the released reference bundle is not
  installed in the current checkout;
- the complete O3a strain stream would be far larger than the free space if
  mirrored as uncompressed 4096 Hz float64 samples, so a full raw mirror is not
  an acceptable default.

### Post-audit storage remediation

After the initial audit, the re-downloadable O4a raw mirrors were removed and
the non-versioned historical O4a project outputs were copied to
`E:\dante_archive\o4a_project_outputs_20260918`, verified file-by-file with
SHA-256, and removed from the checkout only after verification. The operation
left all Git-tracked scientific artifacts intact. The administrative manifests
are:

- `E:\dante_cache\dante_light\storage_cleanup\o4a_raw_cleanup_20260918.json`;
- `E:\dante_cache\dante_light\storage_cleanup\o4a_bulk_mirror_cleanup_20260918.json`;
- `E:\dante_archive\o4a_project_outputs_20260918\archive_manifest.json`.

The verified post-remediation free space was 846.74 GiB on `E:` and 493.16 GiB
on `C:`. This changes storage feasibility, not the scientific transfer gate:
the whole O3a run must still not be retained by default, and no population or
threshold decision is implied by the additional capacity.

## Why the existing O3a scripts are not a production path

`src/pipeline_v3_multiscale/build_multiscale_dictionaries_o3a.py` and
`src/pipeline_v3_multiscale/test_fpr_o3a.py` are historical experimental
scripts. They contain useful fixes from the earlier audit, but they do not
provide the contracts required by the corrected workflow:

- no content-derived run identity or atomic evidence ledger;
- no frozen, detector-aware separation among scan, index, calibration, and
  validation populations;
- no complete cross-population contamination guard;
- hard-coded experimental grids and clustering settings rather than a modern
  versioned run contract;
- the FPR script explicitly measures transfer of O4a multiscale thresholds to
  O3a and therefore cannot define an O3a production threshold;
- no end-to-end verification chain through scan, native rescore,
  classification, taxonomy, coincidence, PEM, and final comparison.

The historical `tau_coh=0.85` entries for O3a/O3b are cross-detector coherence
settings. They are not native anomaly-score thresholds and must never be
compared with or substituted for detector-internal score thresholds.

## Recommended contract direction

Choose **Option A: a complete O3a-native detector-aware reconstruction**.

The run must preserve the corrected workflow semantics while deriving every
run-dependent population and statistical artifact anew:

1. **Scope and acquisition contract**
   - public O3a H1 and L1 only;
   - one explicitly frozen DQ flag and the official O3a bounds;
   - external cache root on `E:`;
   - primary scan streams raw strain with raw cache disabled;
   - only reusable frozen cohorts/blocks may be retained on `E:`.
2. **Initial calibration and primary scan**
   - no O4a score or threshold reuse;
   - any historical O3b representation used to seed the first scan is treated
     only as an explicitly declared source representation;
   - O3a thresholds are calibrated on an O3a outcome-blind population with
     block-based uncertainty.
3. **Native cohort and index**
   - detector-specific, outcome-blind selection;
   - full separation and guards against scan candidates and all calibration
     or validation populations;
   - exact raw/clean hashes and consumed-window manifest;
   - separate H1 and L1 provenance even if a downstream artifact uses a shared
     serialization format.
4. **Native calibration and rescore**
   - O3a detector-aware thresholds from a fresh disjoint cohort;
   - block bootstrap only;
   - no reuse of O4a calibration rows, thresholds, or classes.
5. **Downstream analysis**
   - classification, taxonomy, coincidence, PEM, and report use only verified
     O3a-native inputs;
   - detector-internal and cross-detector null statistics remain distinct.
6. **Multiscale validation**
   - the O4a A1/A2 result remains O4a simulation evidence;
   - the 32 s native decision remains the O3a production path initially;
   - the separate multiscale channel may be transferred only after a new O3a
     joint-null calibration and an independent held-out O3a validation cohort;
   - no diagnostic-only trigger may promote an O3a production candidate.

## Storage policy

The implementation should not download and retain the whole O3a run. The
recommended policy is:

- `E:\dante_cache\dante_light\o3a_native_v1\raw\` for the bounded, reusable
  blocks consumed by frozen cohorts;
- raw cache disabled for the sequential primary scan;
- SQLite/WAL, manifests, ledgers, indices, and receipts under the same
  versioned `E:` run root;
- capacity preflight before every acquisition stage, with fail-closed behavior
  if the reserved minimum cannot be met;
- no deletion or reuse of O4a evidence as a side effect of the O3a run.

This policy honors the project rule that raw or reusable scientific data live
on `E:`. The larger post-cleanup capacity is a safety margin, not authorization
to create a full raw mirror.

## Rejected shortcuts

### Option B: reuse the historical O3b index and old O3 thresholds as final

Rejected. It would reproduce a legacy workflow, not the corrected
detector-aware reconstruction, and would not establish O3a-native calibration
or provenance.

### Option C: run O3a and O3b together under one new contract

Not recommended for the next increment. The two observing epochs require
separate populations, calibration evidence, and storage accounting. Combining
them would enlarge the experiment before O3a portability itself is verified.

## Gates before execution

The following are author decisions because they determine what is measured or
how it is validated:

1. approve O3a-only Option A;
2. freeze `CBC_CAT1` as the O3a public DQ semantics (recommended for parity
   with the corrected O4a workflow; it is currently observationally identical
   to the other public O3a flags);
3. authorize construction of fresh detector-aware O3a populations and
   thresholds, with no imported O4a scientific values;
4. keep multiscale A2 diagnostic-only and deferred until an independent O3a
   validation exists.

Until these four points are approved, the next implementation may add only
read-only preflight and contract-validation machinery. It must not select
windows, build an index, fit a threshold, inspect candidate outcomes, or start
a full O3a scan.

The checked-in `config/dante_o3a_native_v1_decision_gate.json` and
`scripts/audit_dante_o3a_transfer_readiness.py` implement that restricted
read-only phase. The gate deliberately rejects partial or silent author
decisions and cannot authorize execution.

---
phase: 07-o3a-transfer-readiness
verified: 2026-09-18
status: passed
score: 7/7 must-haves verified
is_re_verification: false
gaps:
  - stage-level population and statistical choices intentionally unresolved
---

# Phase 07 O3a approved-scope freeze verification

## Goal

Verify that the four author-approved O3a transfer decisions are frozen with a
reproducible runtime and reference bundle while scientific execution remains
blocked at the next unapproved decision boundary.

## Must-haves

| Truth | Status | Evidence |
|---|---|---|
| The pre-decision gate remains immutable history | VERIFIED | Authorization binds its exact SHA-256; the unresolved gate was not edited. |
| All four author decisions are explicit | VERIFIED | Authorization records O3a-only, `CBC_CAT1`, fresh O3a artifacts, and diagnostic-only multiscale. |
| Runtime is exact and current | VERIFIED | Live WSL/CUDA comparison passed; runtime digest `e5c8b2324f631489d229cd878c109597da8e5c7fd4e62ba5d53fa7222e050dea`. |
| Encoder provenance is complete | VERIFIED | DINO source and weights match the public manifest; runtime also binds Python, CUDA, driver, Torch, GWPy, SciPy, NumPy, scikit-learn, and related packages. |
| Reference bundle is exact | VERIFIED | Bundle SHA `651a70dbf3798de8caba91f1117879cf1798581f1fd949cabf12e260d100fa63`; all eight manifest members verified. |
| O3/O4 scientific boundaries are enforced | VERIFIED | O3b K=275 is seed-only; O4a K=1216 and all O4a populations/thresholds/scores/classes are forbidden inputs. |
| No unapproved execution occurred | VERIFIED | Scope is authorized, but `pipeline_execution_allowed=false`; no DQ, strain, selection, scoring, fit, or scan was started. |

## Reference evidence

- O3b index: SHA
  `9053477ed2f30ed866fc42ff32265957e6a0eb93238032359f5e45e2f032bb7c`,
  shape `[275, 384]`, declared Q-range `[4, 32]`.
- Bundled O4a index: SHA
  `0241b2a1ea2a460334f2c7ae0ab1bb62052706ea05c48443af32ae60a2488744`,
  shape `[1216, 384]`, Q-range `[4, 64]`; installed but forbidden for O3a
  scientific use.
- Reusable bundle and extracted artifacts reside under
  `E:\dante_cache\dante_light\reference_artifacts\v1`; the ignored checkout
  path is a junction to that store and resolves from Windows and WSL.

## Empirical verification

- Windows targeted/regression suite: `73 passed`.
- WSL targeted/regression suite: `73 passed` with 11 upstream deprecation
  warnings.
- WSL Ruff: all changed Python files passed.
- Live WSL runtime verification: `PASS`.
- Restored O4a provenance/bundle regression coverage is included in both
  73-test runs; no `.gitattributes` provenance exception was required.
- `git diff --check`: passed (one Windows line-ending advisory only).

## Scientific boundary

The freeze intentionally does not choose population counts, guard duration,
native clustering parameters, bootstrap block length/replicates, detector
threshold quantile/confidence interval, or coincidence multiple-testing
policy. Those choices determine what is measured or how it is validated and
therefore require a separate explicit checkpoint.

## Verdict

**PASSED.** The approved transfer scope, runtime, and public reference inputs
are reproducible and fail closed before any unapproved O3a science operation.

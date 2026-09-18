---
phase: 07-o3a-transfer-readiness
verified: 2026-09-19
status: passed
score: 8/8 must-haves verified
is_re_verification: false
gaps: []
---

# Phase 07 O3a scale and stage-contract verification

## Must-haves

| Truth | Status | Evidence |
|---|---|---|
| Audit is outcome-blind | VERIFIED | Frozen DQ geometry and checked-in contracts only; strain/outcome flags are false. |
| O3a geometry is sufficient for calibration | VERIFIED | H1 174,967 and L1 186,491 eligible 64 s starts versus 5,000 targets. |
| O3a geometry is sufficient for the index | VERIFIED | Greedy 96 s-separated capacities are 116,810 H1 and 124,494 L1 versus 647 targets. |
| Smaller run does not reduce sample size | VERIFIED | O3a scan geometry is 87.17%/91.01% of corrected O4a, while the fixed samples are denser at 2.86%/2.68% for calibration. |
| Nominal p99 design is unchanged | VERIFIED | 5,000 rows, 50 nominal upper-tail observations, 294 complete 17-row blocks, point estimate on all rows. |
| Index architecture is unchanged | VERIFIED | 1,294 windows, 1,771,486 tokens, K=1,216, raw sample 50,000, seed 42. |
| Approval is separate from the historical gate | VERIFIED | Gate digest `11818f62...f118535` remains unresolved; approved contract digest is `fb29f22f...c157a7d`. |
| Execution remains fail closed | VERIFIED | Only identity-manifest preparation is allowed; strain, scoring, threshold fitting, and full scan remain false. |

## Interpretation

The audit establishes scale and methodological parity, not a distribution-free
guarantee on the realized p99 score-space CI width. That quantity can only be
measured after scoring. The frozen contract requires finite, nondegenerate
detector-specific intervals containing their point estimates and forbids a
post-hoc O3a-specific CI-width cutoff.

## Empirical evidence

- Deterministic regeneration: audit and approved-contract file SHA-256 values
  remained byte-identical across consecutive builds.
- Windows targeted/regression suite: `77 passed`.
- WSL targeted/regression suite: `77 passed`, with 11 upstream GWpy/Matplotlib
  deprecation warnings.
- WSL Ruff: all changed Python files passed.
- `git diff --check`: passed; line-ending advisories only.

## Verdict

**PASSED for methodological-parity freeze.** The next authorized increment is
the construction and verification of disjoint, outcome-blind O3a population
identity manifests. No strain work has been authorized or started.

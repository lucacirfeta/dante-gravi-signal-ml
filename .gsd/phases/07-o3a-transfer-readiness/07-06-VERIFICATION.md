---
phase: 07-o3a-transfer-readiness
verified: 2026-09-19
status: passed
score: 8/8 must-haves verified
is_re_verification: false
gaps: []
---

# Phase 07 O3a initial-calibration selector verification

## Must-haves

| Truth | Status | Evidence |
|---|---|---|
| Approved rule is exact | VERIFIED | Contract freezes 17-row blocks, 295 integer-quantile strata, exact SHA-256 encoding/order, and same-stratum fallback. |
| Blocks respect DQ geometry | VERIFIED | Candidate blocks never cross a CBC_CAT1 segment and use only the frozen 64 s proposal universe. |
| Temporal coverage is balanced | VERIFIED | H1 strata contain 34-35 candidates; L1 strata contain 36-37. |
| Planned cardinality is exact | VERIFIED | Each detector has 295 provisional blocks and 5,000 output identities. |
| Bootstrap semantics are preserved | VERIFIED | 294 complete blocks provide 4,998 resampled rows; two tail rows are point-estimate-only. |
| Selection is outcome blind | VERIFIED | No strain, score, class, candidate outcome, or excess-power disposition is read by the freeze. |
| Raw fallback is fail closed | VERIFIED | Whole-block acceptance, same-stratum ascending-hash fallback, no cross-stratum reallocation, failure on exhaustion. |
| Provenance is complete | VERIFIED | Parent stage/geometry digests, implementation hashes, candidate-priority stream hashes, selected blocks, and ordered identity-stream hash are bound. |

## Frozen evidence

- Selector contract digest: `cc2d46523a753c62609c69965811a0ec61839ff5544a346a2d686397b7de66e7`.
- Preselection plan digest: `b735ab3821524452d7700c347de6375fd2045ffd02807958c81c52cde2cd4595`.
- Ordered 10,000-identity stream SHA-256: `deb3e54273e37943b1fab22ef9026385b3402c70f01cc0360700fde82e2fab3b`.
- H1 complete candidate blocks: 10,044; L1: 10,731.
- Consecutive regeneration produced byte-identical contract and plan files.
- Windows targeted/regression suite: `86 passed`.
- WSL targeted/regression suite: `86 passed`, with 11 upstream GWpy/Matplotlib deprecation warnings.
- WSL Ruff: all changed Python files passed.
- `git diff --check`: passed; line-ending advisories only.

## Verdict

**PASSED for outcome-blind preselection.** This result does not authorize
strain access. The next implementation must first freeze a raw-source
inventory and execution contract, then apply the specified block-atomic raw
acceptance without conditioning on score values or classes.

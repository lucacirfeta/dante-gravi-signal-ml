---
phase: 07-o3a-transfer-readiness
verified: 2026-09-19
status: passed
score: 7/7 must-haves verified
is_re_verification: false
gaps: []
---

# Phase 07 O3a identity-universe verification

## Must-haves

| Truth | Status | Evidence |
|---|---|---|
| Geometry is derived from frozen public evidence | VERIFIED | CBC_CAT1 snapshot digest `4b8d8bb6...f73bb2` and approved stage contract digest `fb29f22f...157a7d` are bound in the manifest. |
| Complete whitening context is enforced | VERIFIED | Every range requires a 32 s analysis interval plus symmetric 4 s context inside its DQ segment. |
| Primary-scan cardinalities are exact | VERIFIED | H1 349,925; L1 372,986. |
| Calibration-proposal cardinalities are exact | VERIFIED | H1 174,967; L1 186,491. |
| Compact ranges are lossless | VERIFIED | Tests expand all ranges, prove uniqueness/alignment, and match stored totals and ordered-stream digests. |
| Freeze is outcome blind | VERIFIED | Strain/outcome access flags are false; no raw quality, score, class, calibration member, index member, or native-calibration member is evaluated/selected. |
| Undefined sampling semantics remain fail closed | VERIFIED | The 5,000-member selection is explicitly deferred until stratum, quota, and raw-quality acceptance semantics are author approved. |

## Empirical evidence

- Manifest digest: `36138d0c4115448fec56a3cf9535bff146e333ff61369bf521a6b5ea3788a00d`.
- Manifest file SHA-256: `db3efd5959b03f29989e5559e58a2e7b2b9d918806959993306d5242b553b074`.
- Consecutive regenerations produced the same file SHA-256.
- Windows targeted/regression suite: `81 passed`.
- WSL targeted/regression suite: `81 passed`, with 11 upstream GWpy/Matplotlib deprecation warnings.
- WSL Ruff: all changed Python files passed.
- `git diff --check`: required before commit.

## Verdict

**PASSED for geometric-universe freeze.** No strain access or scientific
population selection is authorized by this result. The next checkpoint must
freeze the exact outcome-blind calibration selector and raw-quality acceptance
rule before selecting the 5,000 rows per detector.

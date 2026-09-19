---
phase: 07-o3a-transfer-readiness
verified: 2026-09-19
status: passed
score: 8/8 must-haves verified
is_re_verification: false
gaps: []
---

# Phase 07 O3a raw acquisition freeze verification

## Must-haves

| Truth | Status | Evidence |
|---|---|---|
| Source scope is O3a-only | VERIFIED | Every normalized URL is an H1/L1 `GWOSC_O3a_4KHZ_R1` HDF5 file. |
| DQ provenance is bound | VERIFIED | Inventory binds the frozen CBC_CAT1 snapshot and detector-specific query bounds. |
| URL inventory is complete | VERIFIED | H1 has 3,051 frames and L1 has 3,266 over the frozen extent. |
| Context coverage is complete | VERIFIED | All 590 provisional blocks cover first-window minus 4 s through last-window plus 36 s without a gap. |
| Acquisition scope is minimal | VERIFIED | Unique requirement is 365 H1 plus 361 L1 frames. |
| Selection semantics are unchanged | VERIFIED | Only rank-zero blocks are named; same-stratum fallback remains frozen but is not executed. |
| Execution is still disabled | VERIFIED | Downloaded bytes are zero; no raw file was opened and no raw acceptance or scoring ran. |
| Provenance is deterministic | VERIFIED | Source/entrypoint hashes, parents, normalized URL streams, self-digests, and local regeneration are verified. |

## Frozen evidence

- Inventory digest: `7ea4fb89cdc71f02f6cb00dc09ffb0bfcc4270ffed94649c96af95fc646ddf36`.
- Acquisition digest: `25b68454e191bc45ec55a7edef65a586d73258f6654523b6eeedb4488d0b103d`.
- Inventory file SHA-256: `bbf9be18b1ec9e60599381816fbcb5acf80d2912c6153564ac284d4ffe1f5cb1`.
- Acquisition file SHA-256: `bc743d99adb75dde714de8398a72486bb2dc728eb11d7e169862b8a631c289d5`.
- Windows targeted suite: `29 passed`.
- WSL targeted suite: `29 passed`.
- WSL Ruff: passed.

## Verdict

**PASSED for metadata-only raw acquisition planning.** This checkpoint does
not authorize raw downloads, raw acceptance, scoring, or threshold fitting.

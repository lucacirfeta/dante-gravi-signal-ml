---
phase: 07-o3a-transfer-readiness
verified: 2026-09-22
status: passed
score: 10/10 must-haves verified
---

# Phase 07.11 verification

| Truth | Status |
|---|---|
| Frozen contract and runtime reproduce the expected run key | VERIFIED |
| H1 cardinality is exactly 349,925 | VERIFIED |
| L1 cardinality is exactly 372,986 | VERIFIED |
| Total cardinality is exactly 722,911 | VERIFIED |
| Every window identity is ordered, unique, finite, and contract-valid | VERIFIED |
| Candidate tensors exist only for strict detector-p99 exceedances | VERIFIED |
| Raw-frame ledger contains exactly 6,313 correctly mapped frames | VERIFIED |
| Invalid or silently dropped window count is zero | VERIFIED |
| No failure artifact remains and transient raw cache is empty | VERIFIED |
| Windows and WSL focused O3a suites both pass 56 tests | VERIFIED |

The independent verifier re-read every window row, reconstructed the expected
candidate flag from the frozen detector-specific threshold, checked tensor
shapes for materialized exceedances, validated the complete raw-frame ledger,
and reproduced the saved database and artifact identities.  No downstream
scientific stage was opened during verification.

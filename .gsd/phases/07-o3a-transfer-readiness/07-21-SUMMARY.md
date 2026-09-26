---
phase: 07-o3a-transfer-readiness
plan: 21
completed_at: 2026-09-27
---

# O3a-only diagnostic PEM: verified execution

The source-frozen O3a-only PEM run completed under key
`75a40541a8122aceb35e3c68a723f6a75108b0f5cf9f14ca65529151e5e0eb3e`.
The run summary is `PASS_COMPLETE_O3A_NATIVE_PEM_V1` with digest
`8cbfeae700857af0f5ca46054dad9c347a061088764aa881d80d0bd2283b2504`.
Standalone `--stage verify` exited 0 and wrote the compact
`artifacts/dante_light/o3a_native_v1/native_pem.json` receipt with status
`PASS_VERIFIED_O3A_NATIVE_PEM_V1` and digest
`263ed1744dc2dece021d8dd298ad5b5d5c3c8439f78258db4bc9368cc8471e03`.
This verifies parent/output seals, exact target accounting, calibration
identity, source hashes and cache cleanup. It does not independently rerun
all auxiliary-channel coherence and null calculations.
Post-run WSL O3a/PatchProducer regression: 194 passed, 11 upstream warnings;
Ruff passed. The old O4a-specific `.gitattributes` provenance-policy tests
were not bypassed and remain a separate unresolved gate.

- Primary ROBUST: H1 has one COUPLED and one NO_CORRELATION; L1 has nine
  NO_CORRELATION. All 11 calibrated.
- AMBIGUOUS diagnostic: H1 has one NO_CORRELATION. It is not pooled into the
  primary result.
- The COUPLED primary H1 target is GPS 1253581920, top tested channel
  `H1:LSC-POP_A_LF_OUT_DQ`. It exceeds the frozen time-shift and quiet
  zero-lag controls, but remains an environmental-coupling diagnostic, not
  an astrophysical or global-significance statement.
- All 8,900 O3a classified seed identities are in the candidate exclusion.
  The transient raw cache is empty, stderr is empty and no failure file exists.

The method tests only the frozen five public auxiliary channels per detector.
`NO_CORRELATION` means no detected coupling under this limited diagnostic,
not proof of environmental innocence. The 07-20 O4a paired-comparison raw
and `.gitattributes` provenance gate remains open; no O4a comparison was run.
A2 remains diagnostic-only. See
`docs/DANTE_O3A_NATIVE_PEM_CHECKPOINT_V1.md` for the evidence and scope.

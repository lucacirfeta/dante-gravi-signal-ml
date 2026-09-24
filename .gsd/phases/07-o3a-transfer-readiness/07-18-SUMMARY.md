---
phase: 07-o3a-transfer-readiness
plan: 18
completed_at: 2026-09-24
---

# O3a morphology taxonomy: verified execution

The author approved strict O4a-method parity, and the expected single-linkage
dominant-family behavior was pre-registered without an acceptance cutoff in
the plan and frozen contract before O3a taxonomy execution. No method was
tuned after opening results.

- Source/contract freeze: commit `76a3552`, pushed before execution;
  contract digest `bfc1a0588ae71d63efde752ac1f2858b717e00eb10aa0291e47084a155a8769b`.
- Run key: `f475a46f829c9afd78994898f6be5f9499483e401152e0f5f148a11f00b0c629`.
  Both `--run` and standalone `--verify` exited 0. No failure artifact.
- Verified 8,900 rows (H1 3,624; L1 5,276). Two morphology clusters:
  largest family 8,899, one singleton. Class counts remain unchanged:
  5,850 ROBUST, 558 AMBIGUOUS, 2,492 BACKGROUND.
- Output JSONL SHA-256:
  `3afe6d840d1330dcb83252f67028e1e61220b5bd39b170c6b5d077bf7212ba8e`.
  Summary artifact digest:
  `4ccc3b54f00bb3308ac8edd00803f6b88df1b5df9d609c713ac40303e7b7c1bf`.
  Verified compact receipt digest:
  `9f947eeca4d8609f2ae96659d6364cf6a303d4ab411121f74c84e4332e287b41`.
- Independent row/SQLite/vector-hash audit and an independent cosine-threshold
  connectivity check passed. The sole singleton's maximum similarity to the
  dominant family is about 0.6962, below 0.75.
- Pre-run focused tests: 15 passed. Pre- and post-run complete WSL
  O3a/PatchProducer tests: 170 passed each; 11 upstream warnings. Ruff passed.
  Three new source files match frozen Git bytes exactly.

The pre-registered dominant-family expectation was confirmed. As with O4a,
single-linkage chaining makes these family IDs weak discriminators of detailed
glitch morphology. This is not physical coincidence or a significance result.
No COINCIDENCE, PEM or A2 stage was opened. Full evidence and qualifications
are in `docs/DANTE_O3A_NATIVE_TAXONOMY_CHECKPOINT_2026-09-24.md`.

---
phase: 07-o3a-transfer-readiness
plan: 14
completed_at: 2026-09-23
---

# Summary: O3a native-calibration identity freeze

The author approved the corrected-O4a native-v2 selector for the main
O3a/O4a methodological comparison. This is a native-stage-only amendment;
the original O3a stage contract and its completed initial calibration, scan,
cohort and index have not been changed. The selector is outcome-blind except
for the frozen primary-candidate indicator used solely as a firewall.

The approved amendment was frozen before any O3a calibration identities were
read. The identity-only freeze then passed its verifier:

- 5,000 H1 and 5,000 L1 point-estimate rows; 4,998 rows in 294 complete
  17-window bootstrap blocks per detector.
- Zero candidate or index guard violations across detectors; zero duplicate
  detector-GPS identities; complete source-frame context references for all
  10,000 rows.
- No primary/native score, threshold, class or taxonomy read or computed.
- Parent primary scan, native cohort and native index independently verified.
- 90 focused WSL O3a/PatchProducer tests passed. Ruff found only an unused
  `sqlite3` import (F401) in the frozen source; all other Ruff checks passed.
  The import has no execution effect, and the source bytes remain frozen to
  preserve the run key. Removing it would require a new versioned run.

Canonical evidence:

- Selector amendment digest: `2d50b45c373a930d7989056502ecd0ef23c440d7ba7db94efe13ffa13491c317`
- Contract digest: `28f478dbe6c69d5d94af3ca1d6fb959866fc49090b1550a3c8d219c28f4e3d0b`
- Run key: `ea0acdc9cd367c2e9a8b2866cd0b70b2dc71095c6eb17760aa8db60b02e02b3d`
- Artifact digest: `5d7b5cee05f9df8a0b7ad4307e520ffd4fefc6c7ae6c6101fc92836a6615a1db`
- Ledger SHA-256: `2cc88654bfea3792a1a423132dc286aa4f40525859565c23c2e178b94aa2c33c`
- Compact evidence: `artifacts/dante_light/o3a_native_v1/native_calibration_cohort.json`

Next gate: score the frozen ledger with the O3a native index under a new
versioned scoring contract. No threshold or class follows from this identity
freeze alone. Hash-stratified versus evenly spaced selection is deferred to a
separate paired O3a/O4a sensitivity study; parity is not a claim that the
historical selector is statistically optimal.

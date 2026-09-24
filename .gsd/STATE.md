## Current Position
- **Milestone**: O3a transfer readiness
- **Phase**: 7.18 Native morphology taxonomy PASS verified; awaiting downstream authorization
- **Status**: The O3a-only native index and 10,000-row native-calibration
  identity ledger remain adopted and unchanged. The score-only v3 contract
  (`85028c59d55fbc95c9b2b056eb0e783dfbffb3b7f446feb1befd8c2e1ff2f20c`)
  has PASS manifest and real HDF5/CUDA preflight, including stitched context,
  raw-file and image SHA-256 replay. Its frozen workload is 18,900 rows and
  4,324 unique raw frames; these are workload counts, not scientific outcomes.
  The post-run WSL O3a/PatchProducer suite passed 103 tests (11 upstream
  deprecation warnings). Scoring is complete under run key
  `e9b75ee479f5fa6850accb2178d00fa752954519fe7db768629ef1422c4c27e0`.
  All 18,900 rows and 591 score shards are complete; the transient cache is
  empty. The runner reports PASS_VERIFIED and standalone --verify passed
  with exit code 0 on 2026-09-24. The score-replay gate is closed successfully.
  The summary artifact digest is
  `4b1eff34f618005a2b881e3dd29e4dc0b25f1c6e5b5b5d19a23c0a833245503a`.
  Three infrastructure failures (502, 503, connection timeout) were archived
  by the runner before same-key resumes. Rescore v1 and v2 are preserved as
  failed structural preflights with zero
  scientific score shards. Native classes and morphology taxonomy are now
  verified; no coincidence, PEM or astrophysical interpretation has been performed.
  All 15 frozen rescore source hashes match; six
  require an exact, verified LF-to-CRLF reconstruction from Git. A clean-LF
  checkout is not directly hash-equivalent; clean-clone replay remains a
  separate follow-up (see the 2026-09-23 read-only audit).
  The new native-threshold adapter is tested (19 targeted tests; 122 complete
  O3a/PatchProducer tests, 11 upstream warnings). Its contract is frozen as
  `10d6279a2b637309d3d955881cf0a3d2f450f6a66adfb9de9fd2613ea3b65c5c`.
  Source freeze committed and pushed as b87db6a before fitting. The --run
  worker started at 18:00 Europe/Rome on 2026-09-24, with one WSL instance
  observed and an empty stderr log. Run key:
  `1bd630e29eda34be625f6bbd325b60d114d7f4dc2508a8c09c81263127f35405`.
  Fit completed at 18:04:49 Europe/Rome with PASS_COMPLETE, no failure file
  and empty stderr. The launch did not persist its OS exit code; do not
  claim that code was observed. Summary digest:
  `30671367d022c1a935a446313ea65f4b0457f6b85b2cc8f2107e94055b1d1d79`.
  Independent --verify completed at 19:05:41; session 70020 returned exit0
  and deterministic replay matched. Compact artifact digest:
  `32890633207ebb91839131b972dc0ca18650ceb3fe18383fb9adee3bed6ce281`.
  Post-run WSL regression: 122 passed, 11 upstream warnings (86.74s).
  H1 p99=0.4057316654920578; CI width=0.008046090602874756 (1.983106%).
  L1 p99=0.41683934092521674; CI width=0.00732177317142485 (1.756498%).
  Exact 5000 point/4998 bootstrap rows and 294 blocks per detector;
  receipt, summary and frozen-source audit PASS. No post-hoc width cutoff.
  The earlier authorization covered CLASSIFY only. The later explicit
  authorization covered O4a-method-parity TAXONOMY; coincidence, PEM and A2
  promotion remain closed pending separate authorization.
  The classification adapter now has 33 passing targeted tests and 155
  passing full O3a/PatchProducer tests (11 upstream warnings, 99.32s).
  Contract digest:
  `9aaeff60fd078538355d724f4102b39886dca97fef7474d394e2ee4109f5f1a2`.
  No real classification outcome has been opened before this source freeze.
  Source committed/pushed as 03a38ab before execution; all three new source
  hashes match Git bytes exactly. --run completed at 20:15:30 Europe/Rome
  and standalone --verify at 20:20:13 on 2026-09-24.
  Run key: `5cedef7de1c036f49a2c33acfeaa64198a67b31bed1c1109c6b34004faf6c044`.
  Supervisor session 54398 returned CLASSIFY_RUN_EXIT_CODE=0 and
  CLASSIFY_VERIFY_EXIT_CODE=0 (retrieved at the 20:48 status check).
  Summary digest:
  `24bfce9f2b7661ab5c4c9193d5d1200a9416df6d1704d8b80eadd7b91636c4e2`.
  Verified compact:
  `65d67d4c4dac2ff53893d3d23b3f308e5008c436b684a4247c8e927b662de3ac`.
  Post-run WSL regression: 155 passed, 11 upstream warnings, 107.59s.
  All 8900 output rows independently checked against unchanged input fields,
  per-detector thresholds and expected labels; exact Git/source/file hashes
  and seals pass. No failure artifact; both stderr logs empty.
  H1: 2291 ROBUST, 263 AMBIGUOUS, 1070 BACKGROUND (3624 total).
  L1: 3559 ROBUST, 295 AMBIGUOUS, 1422 BACKGROUND (5276 total).
  Total: 5850 ROBUST, 558 AMBIGUOUS, 2492 BACKGROUND (8900 seeds).
  These classes are not global significance or astrophysical detections.
  Classification execution is complete; its monitor was suspended at that
  checkpoint. TAXONOMY source/contract freeze was committed in 76a3552 before
  real execution, including the pre-registered dominant-family expectation.
  Standalone --run and --verify exited 0 under run key
  `f475a46f829c9afd78994898f6be5f9499483e401152e0f5f148a11f00b0c629`.
  The verified compact receipt digest is
  `9f947eeca4d8609f2ae96659d6364cf6a303d4ab411121f74c84e4332e287b41`.
  All 8900 O3a rows retain their native scores/classes; taxonomy has one
  8899-member family and one singleton, confirming the pre-registered
  single-linkage chaining expectation. Independent row, vector-hash and graph
  connectivity checks passed; post-run WSL suite: 170 passed, 11 upstream
  warnings. No active scientific worker and no coincidence/PEM stage started.

## Preserved completed evidence
- Multiscale efficiency v2 phases 6.1-6.4 remain complete and independently
  verified. Their canonical run and artifact identities remain in the phase
  verification records and are not modified by O3a work.
- O3a uses fresh run-specific populations. O4a scientific rows and outputs
  are not imported.

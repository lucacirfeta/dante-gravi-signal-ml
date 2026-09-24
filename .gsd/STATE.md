## Current Position
- **Milestone**: O3a transfer readiness
- **Phase**: 7.17 Native classification frozen/tested; execution pending
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
  scientific score shards. No class, taxonomy or scientific interpretation
  has been computed. All 15 frozen source hashes match; six
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
  The hourly monitor remains active. The user's latest
  authorization permits CLASSIFY as the next separate increment, following
  the frozen stage-contract rule and passing tests/provenance first.
  Taxonomy, coincidence and PEM remain closed.
  The classification adapter now has 33 passing targeted tests and 155
  passing full O3a/PatchProducer tests (11 upstream warnings, 99.32s).
  Contract digest:
  `9aaeff60fd078538355d724f4102b39886dca97fef7474d394e2ee4109f5f1a2`.
  No real classification outcome has been opened before this source freeze.
  Next: commit/push source, then --run followed by --verify only on exit0.

## Preserved completed evidence
- Multiscale efficiency v2 phases 6.1-6.4 remain complete and independently
  verified. Their canonical run and artifact identities remain in the phase
  verification records and are not modified by O3a work.
- O3a uses fresh run-specific populations. O4a scientific rows and outputs
  are not imported.

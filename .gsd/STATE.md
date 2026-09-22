## Current Position
- **Milestone**: O3a transfer readiness
- **Phase**: 7.12 O3a detector-aware native cohort preflight passed
- **Status**: The canonical primary scan
  `8f0424e5f3ea2b94449eaddb0e1ccf61c5fd7ba91d54c839bfa89d0e26efad35`
  passed with exactly 349,925 H1 and 372,986 L1 windows, 722,911 total,
  zero invalid or silent drops, an exact 6,313-frame provenance ledger, and
  an empty transient raw cache. The database SHA-256 is
  `1f222dfbc4066abf8fe2b2f3a09edb4a7ccbc83f79aac94ba9a54aa6b0844699`.
  The independent verifier passed; after adding the native-cohort gates, the
  focused O3a suites passed 79 tests on Windows and 79 tests on WSL. Native
  cohort selection, index construction,
  native calibration, classification, taxonomy, coincidence, PEM, and
  comparison remain closed. The native-cohort contract is frozen with digest
  `4601b2e1ffeb6ef78ab68fd2eb206c9aacfb94a19e2adf7d9444959ae6c1e299`;
  its no-strain preflight passed under run key
  `876508390ba7f1eddf2c50342870e7e8880048b243f545487039974b51df9a2c`.
  The prior run key `29a410a80c546b2ab2d7ad1ab14e842182379e76fbce6663aba34add3c35da5b`
  is preserved FAILED after an execution-only frame-list shadowing defect was
  caught before the first quality shard.  The corrected source resolver and
  direct regression test changed no scientific rule.  The quality freeze has
  not yet restarted.

## Preserved completed evidence
- Multiscale efficiency v2 phases 6.1-6.4 remain complete and independently
  verified. Their canonical run and artifact identities remain in the phase
  verification records and are not modified by O3a work.
- O3a uses fresh run-specific populations. O4a scientific rows and outputs
  are not imported.

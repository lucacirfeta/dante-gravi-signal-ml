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
  focused O3a suites passed 78 tests on Windows and 78 tests on WSL. Native
  cohort selection, index construction,
  native calibration, classification, taxonomy, coincidence, PEM, and
  comparison remain closed. The native-cohort contract is frozen with digest
  `7c8696aa313c9f06226e375e766fabd68b72c615a6e28e4542633c0b9ee79fd5`;
  its no-strain preflight passed under run key
  `29a410a80c546b2ab2d7ad1ab14e842182379e76fbce6663aba34add3c35da5b`.
  The quality freeze has not yet started.

## Preserved completed evidence
- Multiscale efficiency v2 phases 6.1-6.4 remain complete and independently
  verified. Their canonical run and artifact identities remain in the phase
  verification records and are not modified by O3a work.
- O3a uses fresh run-specific populations. O4a scientific rows and outputs
  are not imported.

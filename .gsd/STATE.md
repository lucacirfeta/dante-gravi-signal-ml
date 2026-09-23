## Current Position
- **Milestone**: O3a transfer readiness
- **Phase**: 7.13 O3a-only detector-aware native index
- **Status**: The O3a-only native INDEX completed under run key
  `8b6d6cc706973bc512a9c1f76f9693c232d2c8161e47a285d563b7b3ab351e75`.
  Its independent technical verifier passed 1,294 retained-context/hash replays,
  1,771,486 tokens, K=1,216, and 50,000 raw-sample vectors; the WSL O3a,
  PatchProducer, and native-index suite passed 87 tests. Artifact digest:
  `8ce38ae0ee85a2c45c01b592daab29a9beca52fa735815f1519c0603806041f0`.
  **Scientific review is required before adopting this output:** GWPy truncates
  the requested O3a Q-transform 20-2,048 Hz band at the 4,096 Hz sample rate to
  an effective upper edge of 1,291.053 Hz; the O4a 16,384 Hz method retains
  2,048 Hz. This changes the measured spectral support despite exact requested
  parameter parity. Native calibration and later scientific outputs remain
  unopened. See plan 07-13 for the explicit gate.

## Preserved completed evidence
- Multiscale efficiency v2 phases 6.1-6.4 remain complete and independently
  verified. Their canonical run and artifact identities remain in the phase
  verification records and are not modified by O3a work.
- O3a uses fresh run-specific populations. O4a scientific rows and outputs
  are not imported.

# O3a/O4a common-PEM background strain binding — 2026-09-29

This is a transport-only increment of execution gate 3. It does not evaluate
the five-channel null, PEM verdicts, candidates, or global significance.

The versioned background-input contract pins the independently verified
77-span numerical replay and its 325-frame acquisition parent. The public
comparative measurement entry point now constructs a `VerifiedSpanReader`
for the exact run, detector and target. It accepts only that target's sealed
four-hour interval; it checks parent plan/summary seals, frozen source bytes,
the published strain manifest, the per-span receipt, and a new numerical
replay against the frozen receipt. A missing local frame fails closed: this
entry point cannot download a replacement while measuring PEM.

The official background reader's prior download-enabled behavior remains
available to the separate acquisition workflow; the comparative entry point
explicitly disables it. Historical strain assembly, coherence, auxiliary
resampling and block-bootstrap calculations are unchanged.

A read-only real-source constructor check bound one target in each run to its
sealed span; both exited 0. Synthetic tests exercised exact-interval acceptance,
wrong-interval rejection, changed receipt/parent seals, and no-download
behavior. The WSL common-PEM/native-PEM/PatchProducer regression passed
102 tests with 11 upstream warnings; Ruff lint and format passed. This is
not a new full-span numerical verification run or an outcome replay.

Gate 3 remains open: the productive runner still needs exact event-strain
binding, independent target/full-exclusion/CAT1 and historical-artifact
checks, deterministic synthetic replay, and source freeze before opening
either run's comparative PEM outcomes. No significance or astrophysical
interpretation follows from this input binding.

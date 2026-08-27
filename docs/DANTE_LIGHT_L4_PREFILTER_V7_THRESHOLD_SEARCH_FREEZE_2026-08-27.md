# DANTE-Light L4 prefilter v7: threshold-search execution freeze

Status: authorized and frozen before outcome access; execution not yet started.

The user instruction `procedi` authorizes one opening of `threshold_search` for
the unchanged five-member ensemble. It does not authorize `risk_calibration`,
confirmation, O4b, routing, model/member selection, retuning, or a fallback
threshold.

For each detector, the search uses the ensemble mean-sigmoid `defer_score`.
Candidate thresholds are the unique observed scores plus the always-discard
endpoint. Deferral is `score >= threshold`. The selected threshold maximizes
the discard fraction in the 60 natural-background identities while satisfying,
on the frozen catalog-conditioned identities that the current exact teacher
actually retains, both point retention at least 0.90 and Wilson-95 lower bound
at least 0.80. Safety is evaluated before the deterministic audit stream. Ties
use the lower numerical threshold.

This interpretation follows the already frozen endpoint
`P(Light defers | exact DANTE retains, frozen O4a candidate catalog)`: the
historical `teacher_positive` role is a sampling source, not automatically a
current positive label. Any change in the realized positive denominator is
reported rather than hidden.

Before the first threshold-search row is read, the full exact-teacher
fingerprint and eight training-only canaries must pass and produce a
stage-specific receipt. A mismatch gives `STOP_NO_ACCESS_NO_RETUNE`. The
threshold-search result is then written once, replayed from its compact ledger,
and bound into a separate threshold contract before any calibration access.

The implementation is resumable only under the same authorization, teacher
receipt, checkpoints and run key. Resumption may complete an infrastructure-
interrupted ledger; it may not change the threshold rule or create a second
scientific attempt.

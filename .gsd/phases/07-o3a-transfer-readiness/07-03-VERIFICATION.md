---
phase: 07-o3a-transfer-readiness
verified: 2026-09-18
status: passed
score: 7/7 must-haves verified
is_re_verification: false
gaps:
  - five stage-level scientific decisions require author approval
---

# Phase 07 O3a DQ snapshot and stage gate verification

## Must-haves

| Truth | Status | Evidence |
|---|---|---|
| Snapshot is O3a-only | VERIFIED | Bounds `[1238166018, 1253977218)`, run `O3A`, detectors H1/L1. |
| DQ semantics are exact | VERIFIED | Only `H1_CBC_CAT1` and `L1_CBC_CAT1` were queried. |
| Snapshot is metadata-only | VERIFIED | Both strain and outcome access fields are false; implementation calls only `gwosc.timeline.get_segments`. |
| Segment geometry is validated | VERIFIED | Nonempty, integral, sorted, non-overlapping, positive segments constrained to official bounds. |
| Counts and livetimes are reproducible | VERIFIED | H1 545/11,218,675 s; L1 535/11,956,179 s; summaries are recomputed during validation. |
| Scope contract binds exact evidence | VERIFIED | File SHA, snapshot digest, counts, and livetimes are part of scope digest `a18dabf24f8143e6d5842379561ef2c6a58d93a573dbcc7ef8f82a0ee49eaa20`. |
| Remaining choices fail closed | VERIFIED | Five decisions are null, `execution_allowed=false`, and the preparation contract still has `pipeline_execution_allowed=false`. |

## Scientific review

The recommendation preserves corrected methodology while using fresh O3a
populations and outputs. It explicitly forbids imported O4a rows, embeddings,
indices, scores, thresholds, classes, or candidate outcomes. Block bootstrap,
detector-specific thresholds, population guards, null separation, and the
diagnostic-only coincidence/global-claim boundary are retained. An O3a-adaptive
hyperparameter path is documented as a separate, more expensive alternative.

## Empirical evidence

- Windows targeted/regression suite: `77 passed`.
- WSL targeted/regression suite: `77 passed` with 11 upstream deprecation
  warnings.
- WSL Ruff: all changed Python files passed.
- Live snapshot verifier: PASS.
- Live runtime/scope verifier: PASS.
- `git diff --check`: passed with Windows line-ending advisories only.

## Verdict

**PASSED for metadata freeze and decision preparation.** No scientific stage
may execute until the author resolves all five decision fields.

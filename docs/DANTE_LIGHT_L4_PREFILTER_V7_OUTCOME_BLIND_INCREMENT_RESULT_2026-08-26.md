# DANTE-Light L4 v7 outcome-blind increment result

Status: **COMPLETE; ARTIFACT INTEGRITY PASS; NO TRAINING OR PROTECTED ACCESS**

## Frozen interpretation

The deployable v7 candidate is one fixed ensemble of five
`Raw1DTeacherAlignedStudent` members. Every window executes all five forwards
and the routing score is the arithmetic mean of their sigmoid outputs. The
members are neither screened to retain a favourable seed nor distilled into a
sixth model. The output is an uncalibrated bounded `defer_score`, not a natural
population probability.

The frozen contract digest is
`03c75c99fc2c3a930601727d49e7dee29284782e3edc263384ad6ee064c9d8f1`.
It binds five unique seeds, 3,665 parameters per member (18,325 total),
teacher-aligned Top-13 pooling, unweighted BCE, the unchanged AdamW contract,
and a 600-row outcome-blind internal split. Each detector/sampling-role cell
contains 120 fit and 30 internal-validation blocks, with no block overlap.

## Full-candidate compute measurement

The authoritative CPU batch-one measurement covers conversion of an already
whitened float32 subwindow to a tensor view, all five member forwards, sigmoid
mean aggregation, the routing comparison, and the deterministic audit hash
decision. It uses one PyTorch CPU thread, 50 warm-up calls and 300 timed calls.

| Quantity | Result |
|---|---:|
| complete five-member mean | 6.067697 ms |
| complete five-member median | 5.991600 ms |
| complete five-member p95 | 6.510265 ms |
| complete five-member maximum | 8.052700 ms |
| single-member mean, diagnostic only | 1.211531 ms |
| measured full/single mean ratio | 5.0083 |
| historical avoidable exact-path mean | 481.609437 ms |
| full-ensemble mean / historical exact mean | 1.2599% |
| graph-construction startup, excluded from steady state | 33.936100 ms |

These numbers establish the cost of the random-weight graph and routing path,
not scientific or operational readiness. No compute PASS threshold was added
after observing the result. Net saving still depends on the future frozen
discard coverage, realized audit fraction, and paired per-window exact cost.

Artifact digest:
`448bdba6cbd257a823538757617774cb7734a301e97edf8174efa5914c625f9f`.

## Verification boundary

- v7 freeze and training verifier: PASS;
- targeted v7 tests: 19 passed;
- independent clean-checkout v7 verifiers and targeted tests: PASS;
- complete repository suite: 570 passed, 1 skipped;
- training strain and teacher labels accessed: none;
- `threshold_search`, `risk_calibration`, confirmation and O4b accessed: none;
- candidate promoted or routing enabled: no.

The clean-checkout audit initially exposed one pre-existing Windows line-ending
provenance defect in the v7 identity header. Repository references now use the
canonical Git blob for tracked clean files, while accepting equivalent working
tree bytes during verification. The 4,380 frozen identities did not change;
only portable provenance hashes, the dependent header/seal digests, and the
still-outcome-blind training split were regenerated.

The next permitted action requires a separate scientific checkpoint to open
the training partition. `threshold_search` remains forbidden even after that
training step until a training-only result has been reviewed.

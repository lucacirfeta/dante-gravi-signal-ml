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
`8c44916302511fab6de079521f5eaed0e4ad873ec9bbe7841d358da0df92a27c`.
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
| complete five-member mean | 5.940646 ms |
| complete five-member median | 5.930350 ms |
| complete five-member p95 | 6.139135 ms |
| complete five-member maximum | 6.570500 ms |
| single-member mean, diagnostic only | 1.206095 ms |
| measured full/single mean ratio | 4.9255 |
| historical avoidable exact-path mean | 481.609437 ms |
| full-ensemble mean / historical exact mean | 1.2335% |
| graph-construction startup, excluded from steady state | 12.093000 ms |

These numbers establish the cost of the random-weight graph and routing path,
not scientific or operational readiness. No compute PASS threshold was added
after observing the result. Net saving still depends on the future frozen
discard coverage, realized audit fraction, and paired per-window exact cost.

Artifact digest:
`f966e422eab31605a7d304faf2fa49e4af967f25426ed56e9423cae174ba4582`.

## Verification boundary

- v7 freeze and training verifier: PASS;
- targeted v7 tests: 18 passed;
- complete repository suite: 569 passed, 1 skipped;
- training strain and teacher labels accessed: none;
- `threshold_search`, `risk_calibration`, confirmation and O4b accessed: none;
- candidate promoted or routing enabled: no.

The next permitted action requires a separate scientific checkpoint to open
the training partition. `threshold_search` remains forbidden even after that
training step until a training-only result has been reviewed.

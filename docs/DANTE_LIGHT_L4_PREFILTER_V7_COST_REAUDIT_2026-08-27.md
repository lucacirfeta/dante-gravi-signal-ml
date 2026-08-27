# DANTE-Light L4 prefilter v7: cost-accounting erratum and re-audit

## Erratum

The v7 risk-calibration safety result and all frozen routing decisions remain
immutable. The original operational cost value of `0.731394 s` per window is
reclassified as **`INDETERMINATE_COST_ACCOUNTING`** because it combined:

- per-item Q-transform and rendering wall times measured concurrently inside
  a four-worker thread pool; and
- exact-teacher latency measured serially outside that pool.

The concurrent wall intervals overlap and are inflated by contention. Adding
them row by row does not estimate either isolated service time or batch
throughput. Data read and whitening were already excluded and did not cause
the discrepancy. The original artifact and digest are retained unchanged as
an audit record; its cost PASS is superseded, not silently rewritten.

## Frozen cost-only protocol

The contract was frozen before remeasurement with digest
`6fe64f7a0398d6590f5f427ed2fb8de168ba96d4cdf88bf2cd2dfebeb63ee77a`.
It binds the same 300 already-open O4a background identities and their frozen
post-audit routing decisions. No score, label, threshold, ensemble member or
protected outcome was changed or selected. Confirmation and O4b remained
unaccessed.

Two non-mixed estimands were measured:

1. **Isolated sequential service time.** For each window, Q-transform,
   rendering and single-window exact-teacher latency were measured serially;
   the five-member Light ensemble was measured separately on one CPU thread.
   Net saving remained paired by window and its uncertainty used the frozen
   detector/GPS-4096-s block bootstrap.
2. **Batch throughput.** Fixed batches of eight used four preprocessing
   workers followed by serial, batch-size-one teacher scoring. The measured
   baseline exact makespan was compared with the full Light makespan plus the
   exact makespan of the 20 non-discarded windows. This is a throughput point
   estimate and batch diagnostic; no invalid i.i.d. bootstrap was applied.

Both estimands exclude data reading, whitening and model startup. Environment:
Windows 10 build 26200, 16 logical CPUs, one PyTorch CPU thread, NVIDIA RTX
5070, Python 3.11.5, NumPy 2.4.5 and PyTorch 2.12.0.dev20260408+cu128.

## Results

| Estimand | Exact baseline | Light cost | Residual exact cost | Net saving/window | Uncertainty | Result |
|---|---:|---:|---:|---:|---|---|
| isolated sequential | 0.401153 s/window | 0.006897 s/window | paired by frozen route | 0.368600 s | block-bootstrap 95%: [0.355203, 0.381854] s | positive |
| batch throughput | 106.355367 s total | 1.517167 s total | 7.983556 s total | 0.322849 s | point/batch diagnostic | positive |

The re-audit therefore supports positive compute saving for this frozen cohort
on the measured hardware. It does **not** rescue v7: the candidate remains
`V7_NOT_READY_RISK_CALIBRATION` because the independent teacher-positive and
protected-morphology safety gates fail. `candidate_promoted=false`,
`routing_enabled=false`, and the confirmation and O4b access lists remain
empty.

## Cross-version scientific boundary

Across v2--v7, no evaluated low-cost path satisfied the joint fidelity,
morphology-safety and operational contract. Direct negative NSBH evidence was
obtained in v2, v3, v4 and v7; the mini-bank showed inadequate coverage,
scattering was excluded on feasibility grounds, and v5--v6 failed upstream
teacher-fidelity requirements. This bounded statement does not claim six
independent NSBH retention failures and does not generalize beyond the tested
candidate families.

## Reproduction

```text
python scripts/verify_dante_light_prefilter_v7_cost_reaudit.py
pytest tests/test_dante_light_prefilter_v7_cost_reaudit.py -q
```

Evidence:

- `config/dante_light_prefilter_v7_cost_reaudit.json`;
- `artifacts/dante_light/prefilter_l4_v7_risk_calibration/cost_reaudit_summary_v7.json`;
- `artifacts/dante_light/prefilter_l4_v7_risk_calibration/cost_reaudit_timings_v7.jsonl`.

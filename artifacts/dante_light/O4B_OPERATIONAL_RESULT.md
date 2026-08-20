# DANTE-Light O4b v2 prospective shadow result

Run date: 2026-08-20. Locked code commit:
`780831b6f9afb579d58758020747c8ee0abe930e`. The machine-readable authority is
`artifacts/dante_light/prospective_validation_v1.json`; this note does not
replace its hashes or verifier.

## Registered endpoints

- Public GWOSC O4b holdout: 768 windows, 384 H1 and 384 L1, with 128 per
  detector in each of three temporally separated CAT1 blocks.
- Coverage: 768 submitted and durably written; zero drops, duplicate
  identities, DEFERs, and execution failures.
- Exactness: canonical and shared-encoder score-only engines have maximum
  absolute score difference 0 and zero disposition mismatches.
- Shared latency from task submission through durable record write:
  p50 29.04 s, p95 35.40 s, p99 37.01 s. The frozen 60 s p99 endpoint passes.
- Canonical latency: p50 28.44 s, p95 34.64 s, p99 36.44 s.
- GWOSC staging is reported separately. Canonical staging p99 was 31.25 s
  (maximum 77.14 s); shared staging p99 was 5.32 s (maximum 6.11 s). These two
  acquisition distributions must not be interpreted as an engine comparison:
  the shared run benefited from data cached by the earlier canonical run.

## Escalation outcome

The frozen detector-specific O4a thresholds produced 18 `ESCALATE` and 750
`NOT_ESCALATED` records: an overall escalation fraction of 2.344% (Wilson 95%
CI 1.488--3.674%). `NOT_ESCALATED` is a triage result, not an offline
`BACKGROUND` classification.

| Detector | Block 1 | Block 2 | Block 3 | Total |
|---|---:|---:|---:|---:|
| H1 | 1/128 (0.781%) | 3/128 (2.344%) | 4/128 (3.125%) | 8/384 (2.083%) |
| L1 | 0/128 (0.000%) | 6/128 (4.688%) | 4/128 (3.125%) | 10/384 (2.604%) |
| Combined | 1/256 (0.391%) | 9/256 (3.516%) | 8/256 (3.125%) | 18/768 (2.344%) |

These strata are descriptive. No post-hoc stability threshold or significance
claim is introduced after observing the holdout.

## Scientific boundary and next validation

This result validates exact later-epoch shadow execution, causal calibration
provenance, public-data reproducibility, durable accounting, and the registered
latency endpoint on the recorded Windows/CUDA workstation. It does not yet
validate unattended online acquisition, public alerts, automatic calibration,
a lossy prefilter, or the offline physical interpretation of the 18 escalated
windows.

The next scientific task is a frozen, detector-aware offline follow-up of all
18 escalations using the existing DANTE characterization gates, with outcomes
reported for every window. That analysis must not change this holdout manifest,
the detector thresholds, or the completed shadow evidence.

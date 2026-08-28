# DANTE-Light v8.1 Phase 0: exact-path profile and capacity audit

Date: 2026-08-28

Status: **engineering audit PASS; no engine promotion and no prioritization
gate frozen**

Machine-readable result:
`artifacts/dante_light/v8_1_phase0/phase0_summary_v8_1.json`.

Frozen audit contract:
`config/dante_light_v8_1_phase0_audit.json`.

## What was changed before profiling

The active scorer constructors in `src/dante_light/runner_v8_1.py` obtain Top-k
from the versioned representation contract instead of repeating the literal
value. The frozen v5--v7 `runner.py` source remains byte-stable so its historical
provenance contracts remain verifiable; the CLI now enters through the
versioned v8.1 runner. The frozen Top-k value remains 68. A detector-balanced
replay of four H1 and
four L1 threshold-boundary windows produced byte-identical float32 native and
primary scores, identical strain/image/Top-k/MIL hashes, identical Top-k
identities, and zero disposition or DEFER mismatches between the canonical and
shared-encoder engines.

The preflight run also exposed an unrelated CLI defect: the default global
`--limit 8` made an explicit `--limit-per-detector` request fail the documented
mutual-exclusion check. The parser now represents the two options as a true
mutually exclusive group and applies the replay default only when neither is
specified. This changes selection plumbing, not the scientific population or
scoring rule.

## Exact-path profile

The most stable bottleneck estimate remains the previously frozen v7 isolated
cost ledger (300 already-open O4a windows), now rebound into the v8.1 audit:

| measured stage | mean (s/window) | median | p95 | mean fraction |
|---|---:|---:|---:|---:|
| Q-transform | 0.284438 | 0.278113 | 0.336187 | 70.91% |
| rendering | 0.001217 | 0.001137 | 0.001542 | 0.30% |
| exact scoring total | 0.115498 | 0.113851 | 0.138431 | 28.79% |
| avoidable exact path | 0.401153 | 0.397055 | 0.465328 | 100% |

Thus the Q-transform, not rendering or index lookup alone, is the dominant
measured cost. The current evidence does not yet separate DINO forward, index
scoring, result materialization, cold model start, peak CPU/GPU memory or cache
disk I/O within a common benchmark. Those quantities remain explicit open
profiling items; they are not inferred from the aggregate score time.

On the new eight-window engineering profile, the shared-encoder path completed
in 5.641 s versus 6.055 s for canonical. That small corpus is useful for exact
equivalence, not for a speed claim. On the already-open 768-window O4b executor
run, shared took 1132.503 s versus 1111.507 s for canonical, a throughput ratio
of 0.9815. Therefore **an end-to-end shared-engine speedup is not demonstrated**
and the shared engine is not promoted to the default.

## Capacity audit

For two detectors and non-overlapping 32 s windows, the nominal full-cadence
arrival rate is 0.0625 windows/s. The isolated compute-only exact mean implies
2.493 windows/s, about 39.89 times that nominal rate, but excludes data read,
whitening and model startup. The already-open cached O4b shared executor wrote
768 windows in 1132.503 s (0.678 windows/s, about 10.85 times nominal), with no
drops or DEFERs. Acquisition was staged separately, so this is not an
arrival-process stress test or an end-to-end capacity guarantee.

The same O4b corpus contains 18 exact escalations among 768 windows (2.34375%).
It does **not** contain review-start/review-completion timestamps, operator
service times, staffing availability, a review deadline or a measured review
backlog. Consequently the post-exact prioritizer's relevant capacity remains
unmeasured even though exact compute capacity is observed to exceed nominal
window cadence on this hardware.

Phase 0 verdict:
`EXACT_COMPUTE_CAPACITY_OBSERVED_OPERATOR_REVIEW_CAPACITY_UNMEASURED`.

## Decision boundary

This checkpoint establishes engineering equivalence on the balanced profile,
rebinds the 300-window isolated bottleneck evidence, and demonstrates that the
repository currently lacks the human-review telemetry needed to choose a
defensible top-X budget or deadline. It does not establish a general speedup, a
useful prioritizer, an age override, a per-morphology success bound or
permission to promote the shared engine.

The next scientific/structural checkpoint is therefore not threshold tuning.
It is a choice between collecting outcome-blind operator-capacity telemetry or
defining a separately justified simulated operational contract. No ranking
implementation should begin until that choice and its measurement boundary are
frozen.

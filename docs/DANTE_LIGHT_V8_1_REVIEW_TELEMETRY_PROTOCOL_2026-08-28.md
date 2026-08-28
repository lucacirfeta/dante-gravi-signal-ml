# DANTE-Light v8.1: outcome-blind human-review telemetry protocol

Date: 2026-08-28

Status: **telemetry infrastructure frozen; no operational budget, deadline,
age override, ranking rule or sufficiency gate is authorized**

Versioned contract:
`config/dante_light_v8_1_review_telemetry_contract.json`.

Implementation:
`src/dante_light/review_telemetry_v8_1.py` and
`scripts/manage_dante_light_v8_1_review_telemetry.py`.

## Purpose and boundary

Phase 0 established that exact compute capacity exceeds the nominal two-detector
arrival rate on the measured hardware, but found no operator start/completion
timestamps. The 18 exact escalations among 768 frozen O4b windows are a real
scale anchor; they contain no information about how quickly a person starts or
finishes reviewing them.

This protocol therefore measures the actual workflow. It does not simulate a
human reviewer and does not infer a top-X budget or deadline from the historical
escalation count. A simulated queue may later be used only as an explicitly
labelled feasibility study and cannot authorize an operational setting.

The ledger permits only three events: `ENROLLED`, `STARTED`, and `COMPLETED`.
It stores source/window identities, detector, UTC timestamps and cryptographic
provenance. It forbids review outcomes, class/morphology labels, scientific
notes, teacher scores and priority scores. During measurement, the queue is
FIFO by enrollment sequence; no prioritizer is active.

The historical O4b escalations can be enrolled as a real backlog. Their
`ENROLLED` time is the time telemetry begins, **not** the unavailable time at
which DANTE originally produced them. Consequently their enrollment-to-start
and enrollment-to-completion intervals describe handling of a newly presented
historical backlog, not historical alert latency. Future `poll_observed` sources
measure delay from the observation/synchronization poll, with the same stated
limitation.

## Recorded quantities

For each escalation the ledger derives:

- observed wait: `ENROLLED -> STARTED`;
- operator service time: `STARTED -> COMPLETED`;
- observed cycle time: `ENROLLED -> COMPLETED`;
- backlog state reconstructed from the append-only event sequence.

Each line is SHA256 hash-chained to the preceding line, bound to a manifest and
flushed durably. Invalid transitions, modified records, divergent contract
hashes and provenance mismatches fail closed. The operator identifier is stored
only as a SHA256 pseudonym.

Until a separate sufficiency checkpoint is approved, the program reports only
descriptive counts, medians, p90 and maxima. It emits
`DESCRIPTIVE_ONLY_SUFFICIENCY_THRESHOLD_UNFROZEN`; it does not calculate an IID
confidence interval and cannot authorize a budget.

## Why a calendar duration is not a stopping rule

Operator work is plausibly clustered by review day or session: availability,
backlog size and batch-versus-continuous handling can make adjacent reviews
dependent. Inferential resampling must therefore use versioned review-day or
review-session blocks, never individual escalation events. This follows the
same dependence-aware principle as the pipeline's block bootstrap. The
stationary bootstrap is a standard block-resampling construction for dependent
observations ([Politis and Romano, 1994](https://www.tandfonline.com/doi/abs/10.1080/01621459.1994.10476870)).

For scale only, the distribution-free IID order-statistic identity

`P(max >= population p-quantile) = 1 - p^n`

gives the following mathematical floors:

| population quantile | confidence | minimum completed escalations if IID |
|---:|---:|---:|
| 0.90 | 0.90 | 22 |
| 0.90 | 0.95 | 29 |
| 0.95 | 0.90 | 45 |
| 0.95 | 0.95 | 59 |
| 0.99 | 0.95 | 299 |

These are **not readiness gates**: the IID assumption is not accepted for the
real operator stream, and observing a sample maximum is not the same as
estimating a capacity quantile with a chosen precision. NIST's distribution-free
tolerance-limit guidance provides the order-statistic basis and illustrates why
coverage and confidence must both be chosen explicitly
([NIST/SEMATECH Handbook](https://itl.nist.gov/div898/handbook/prc/section2/prc262.htm)).

Before any top-X budget, deadline or age override can be frozen, a separate
scientific checkpoint must choose and justify:

1. the capacity estimand (quantile, throughput, backlog-clearance probability,
   or another operational quantity);
2. confidence and acceptable precision;
3. the minimum number of independent review-day/session blocks;
4. stationarity/stratification rules for batch and continuous review;
5. a block-based analysis and a stopping rule based on realized completed
   escalations and blocks, not elapsed calendar time alone.

## Commands

The default ledger location is on `E:` so operational cache/state does not enter
Git. Initialize the known O4b backlog once:

```powershell
python scripts/manage_dante_light_v8_1_review_telemetry.py init `
  --operator-id "<private stable operator id>" `
  --require-historical-anchor
```

Inspect the next FIFO item, mark its actual start, and mark completion:

```powershell
python scripts/manage_dante_light_v8_1_review_telemetry.py next
python scripts/manage_dante_light_v8_1_review_telemetry.py start --record-id <dlr1-id>
python scripts/manage_dante_light_v8_1_review_telemetry.py complete --record-id <dlr1-id>
```

For a future exact-run queue, synchronize only when it is actually observed:

```powershell
python scripts/manage_dante_light_v8_1_review_telemetry.py sync `
  --source-dir <exact-run-output-directory> `
  --source-semantics poll_observed_enrollment
```

Integrity and descriptive status checks are:

```powershell
python scripts/manage_dante_light_v8_1_review_telemetry.py verify
python scripts/manage_dante_light_v8_1_review_telemetry.py status
python scripts/manage_dante_light_v8_1_review_telemetry.py sufficiency-scenarios
```

No command records the scientific outcome of a review. That separation is
intentional: this ledger measures operator capacity without using the result to
design the later ranking rule.

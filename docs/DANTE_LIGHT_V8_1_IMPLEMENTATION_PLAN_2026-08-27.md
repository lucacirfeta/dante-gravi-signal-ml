# DANTE-Light v8.1 implementation plan

Status: **Phase 0 complete with operator capacity unmeasured; stopped before
the Phase 3 scientific gate freeze**

Parent design:
`docs/DANTE_LIGHT_V8_1_DESIGN_PROPOSAL_2026-08-27.md`.

## Goal

Deliver two independently auditable results:

- an exact-path candidate that is measurably cheaper and scientifically
  equivalent to the canonical scorer; and
- a non-destructive review queue whose top-of-queue behaviour is demonstrably
  safe for each protected detector/morphology cell under a real operational
  budget.

Neither result is required to promote the other.

## Phase 0 — baseline and feasibility audits

### 0A. Repository and evidence baseline

Result: **complete** in
`artifacts/dante_light/v8_1_phase0/phase0_summary_v8_1.json`.

- Bind the v8.1 work to the merged v7 main ancestry and current reference
  artifacts.
- Re-run the existing teacher-stability verifier and release/evidence verifiers.
- Record current canonical/shared engine code hashes, `SCORE_ATOL`, canary
  digest, O4a replay digest and the already-open O4b shadow digest.

Exit: a compact baseline manifest reproduces with no protected access.

### 0B. Exact-path profile

Result: **bounded profile complete**. The 300-window isolated ledger identifies
Q-transform as 70.91% of measured avoidable exact cost. The eight-window
balanced replay establishes exact equivalence but is not a performance claim.
Fine-grained DINO/index/materialization and memory profiling remains an
engineering follow-up before any new optimization is promoted.

- Profile canonical and shared engines on the same deterministic, already-open
  corpus.
- Separate acquisition, whitening, Q-transform, rendering, DINO forward, index
  scoring, materialization, durable write and queue delay.
- Report isolated service time, cold batch throughput, warm replay throughput
  and peak CPU/GPU/disk memory separately.

Exit: one bottleneck table justifies the first optimization increment. No code
optimization begins from intuition alone.

### 0C. Queue-capacity audit

Result: **capacity boundary established, operational review capacity
unmeasured**. Exact compute exceeds nominal two-detector window cadence in both
the isolated and cached staged point estimates, but no operator service-time or
review-completion trace exists. Verdict:
`EXACT_COMPUTE_CAPACITY_OBSERVED_OPERATOR_REVIEW_CAPACITY_UNMEASURED`.

- Specify whether the use case is exact-processing order, human-review order or
  both.
- Measure/freeze arrival traces, exact service traces, operator capacity,
  backlog episodes and review deadlines from existing logs or a declared
  simulation contract.
- Determine whether nominal operation has enough backlog for prioritization to
  provide measurable value.

Exit: either `PRIORITIZATION_FEASIBLE` with a defensible budget/deadline proposal
or `NO_OPERATIONAL_BACKLOG/INSUFFICIENT_WORKLOAD_EVIDENCE`. Stop for scientific
confirmation before freezing a ranking gate.

## Phase 1 — exact equivalence harness

Implement a versioned comparator around the canonical and candidate engines.
For every window it must compare:

- all source and intermediate hashes;
- float32 score bytes and absolute deltas;
- Top-k identities and MIL-vector bytes;
- disposition, epoch and DEFER reason;
- input/output order and durable record identity.

Add negative tests for a stale fingerprint, wrong raw hash, wrong image hash,
wrong shape/dtype, reordered batch, corrupted cache payload and score within the
numeric tolerance but across a decision boundary.

Exit: the harness fails closed and reproduces the existing v7 canary and frozen
replay evidence. This phase does not promote an engine.

## Phase 2 — exact optimization increments

Execute one candidate at a time in the order frozen in the design proposal:

1. resolve the runner's `k=68` literal through `representation.top_k`, with no
   value or output change;
2. full-corpus audit of existing `shared_encoder_score_only`;
3. minimal evidence materialization;
4. frozen batch-size candidate;
5. prepared-image cache;
6. patch-token cache, only if still justified.

For every candidate:

- run unit/regression tests before performance tests;
- run v7 canaries and the frozen O4a/O4b engineering corpus;
- reject on any unexplained hash, score, order, evidence or disposition change;
- benchmark on the same hardware and measurement definitions;
- archive failed evidence rather than overwriting it.

Exit: a candidate may be labelled `EQUIVALENT_AND_FASTER` only when equivalence
passes before a predeclared performance endpoint. Making it the default engine
is a separate structural checkpoint requiring human review.

## Phase 3 — ranking protocol freeze

Only after Phase 0C and a separate decision on real telemetry versus a frozen
simulation contract:

- freeze the queue placement and its feature source;
- freeze one primary review budget or deadline;
- freeze the age override/maximum-delay rule;
- freeze detector-by-morphology cells, teacher-positive arm, block definition,
  power target, minimum effective blocks, confidence construction and
  multiplicity handling;
- freeze FIFO and exact-native-score baselines;
- seal any fresh evaluation partition before inspecting outcomes.

Spearman, NDCG and full risk-coverage curves may be reported descriptively but
cannot replace the protected top-of-queue gate.

Exit: dedicated reviewed commit containing only the ranking protocol and seals.
Do not combine it with model code or observed results.

## Phase 4 — prioritizer implementation

Recommended primary implementation: deterministic post-exact review priority
with an age override. Preserve the append-only `ReviewQueue` record as the
scientific source of truth; maintain ordering metadata in a separate,
digest-bound queue artifact so reprioritization cannot mutate exact records.

Required tests:

- every valid record appears exactly once;
- no record can be removed through reprioritization;
- restart/resume preserves order under the same frozen inputs;
- age override prevents starvation under adversarial priority scores;
- H1/L1 identities never collide;
- equal priorities use a frozen deterministic tie-break;
- missing/nonfinite priority becomes FIFO/DEFER according to the frozen rule,
  never a silent drop.

Exit: implementation tests pass without opening the sealed evaluation outcome.

## Phase 5 — one-shot evaluation

- Select/freeze the queue rule on the permitted search partition only.
- Apply it once to the independent evaluation partition.
- Evaluate protected recall within budget/deadline separately for every
  detector and morphology with detector/GPS-block bootstrap uncertainty.
- Evaluate the independent exact-teacher-positive arm.
- Report worst-cell rank percentile, time-to-review, starvation count, FIFO
  delta, operator workload and aggregate rank metrics.
- Do not pool a failing or underpowered cell into PASS and do not retune after
  the one-shot result.

Exit: `V8_1_PRIORITY_PASS`, `NOT_READY`, or `UNDERPOWERED`, with immutable
machine-readable evidence.

## Phase 6 — verification and release boundary

- Run both v8.1 verifiers, all pertinent DANTE-Light tests and the full suite.
- Repeat the equivalence audit from a clean clone using the public reference
  bundle and E: only as a verified cache.
- Verify compact artifact hashes, lineage, documentation, commands and no
  unintended protected access.
- Update the lab notebook/claim ledger only with bounded results and exact
  artifact paths.

Stop before merging or promoting either engine. Merge, default-engine promotion
and publication are distinct user-controlled decisions.

## Verification matrix

| Risk | Required evidence | Failure state |
|---|---|---|
| scientific score drift | float32 bytes plus existing tolerance audit | `NOT_PROMOTED` |
| decision drift | zero disposition/DEFER mismatches | `NOT_PROMOTED` |
| cache poisoning | full-key digest, dtype/shape and payload hash | cache rejected |
| misleading speed claim | separate cold/warm/service/throughput estimands | `INDETERMINATE_COST_ACCOUNTING` |
| rare morphology buried | detector-by-morphology recall within budget/deadline | `NOT_READY` |
| weak cell hidden by pooling | per-cell block-bootstrap and power audit | `UNDERPOWERED` or FAIL |
| starvation | age/deadline invariant under adversarial queue tests | `NOT_READY` |
| retrospective evidence overstated | explicit O4a/O4b engineering label | claim rejected |

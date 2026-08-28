# DANTE-Light v8.1: safe exact-path optimization and non-destructive prioritization

Date: 2026-08-27

Status: **post-exact primary confirmed; Phase 0 audit authorized; scientific
gates and production promotion not frozen**

Machine-readable companion:
`config/dante_light_v8_1_design_proposal.json`.

## Executive decision

v8.1 must not be another lossy prefilter experiment. The v2--v7 evidence does
not support irreversible suppression by any tested low-cost candidate. The two
new workstreams are therefore independent:

1. make the current exact DANTE path cheaper without changing its scientific
   function; and
2. prioritize work without deleting it or allowing rare protected
   morphologies to disappear in an aggregate ranking metric.

The first workstream is authorized for immediate engineering audit. For the
second, the confirmed primary scope is **post-exact human-review prioritization**.
A pre-exact queue ranker remains research-only until a workload audit proves a
real backlog and an independent safety protocol shows that it does not create
practical starvation.

## What the repository already proves

This design starts from code and saved evidence rather than from a hypothetical
pipeline:

- `src/dante_light/runner.py` already contains the canonical double-forward
  engine and the exact `shared_encoder_score_only` engine. The latter encodes
  the image once and scores both frozen indices through
  `PatchScorer.score_multi_index`.
- `artifacts/dante_light/prospective_validation_v1.json` records 768 already
  opened O4b shadow windows with zero score delta and zero disposition
  mismatches between those engines under the existing `2e-7` tolerance.
- `config/dante_light_prefilter_v7_teacher_stability.json` binds the reference
  indices, DINOv2 source and weights, representation, exact-path source files,
  runtime and eight training-only canaries. The canaries bind raw, whitened and
  rendered inputs plus the float32 teacher-score bytes.
- `src/dante_light/evidence.py` already freezes the maximum admissible score
  tolerance as `SCORE_ATOL`; v8.1 must reference it, not invent a new value.
- The active `src/dante_light/runner_v8_1.py::run_replay` reads
  `representation.top_k`. The frozen v5--v7 `runner.py` stays byte-stable for
  historical provenance verification. The frozen value remains unchanged and
  the v8.1 Phase-0 detector-balanced equivalence profile found zero score,
  evidence or disposition mismatches.
- `docs/DANTE_LIGHT_L4_PREFILTER_V7_COST_REAUDIT_2026-08-27.md` separates
  isolated service time from batch throughput. v8.1 must preserve that
  separation and must also report cold and warm-cache measurements separately.

The O4b result is retrospective engineering regression evidence in v8.1. It is
not a fresh prospective validation and may not be relabelled as one.

## Workstream E: optimize the exact path

### Invariant

The optimized path is accepted only if it remains the same scientific function.
Performance is inspected **after** provenance, numerical output, decisions and
saved evidence pass.

Within the frozen runtime used for a comparison, the target is bitwise equality
for input hashes, float32 native and primary scores, primary Top-k identities,
the primary MIL vector, disposition and DEFER reason. Cross-engine comparisons
also retain the existing repository bound `SCORE_ATOL` and require zero
disposition mismatches. That tolerance is a pre-existing compatibility bound,
not permission to relax equality after seeing results.

The acceptance corpus must be layered:

1. unit and synthetic fixtures for corruption, reorder and cache-key failures;
2. the eight v7 training-only canaries;
3. the already-frozen O4a replay, including the threshold-boundary role and all
   protected morphologies separately;
4. the already-open O4b shadow corpus, explicitly labelled retrospective.

No new confirmation or later-epoch holdout is opened for an engineering
equivalence check.

### Increment order

1. Replace the runner's literal Top-k value with `representation.top_k` and
   prove unchanged output on the frozen equivalence corpus.
2. Audit the already-implemented `shared_encoder_score_only` path over the full
   frozen equivalence corpus. This is the lowest-risk candidate and must be
   evaluated before adding new machinery.
3. Remove only result materialization that the durable record does not consume.
   The primary score, Top-k indices and MIL vector must remain identical.
4. Benchmark versioned batch sizes without changing them during an outcome run.
5. Add an optional prepared-image cache for replay/resume.
6. Add an optional normalized patch-token cache only if the image-cache result
   leaves a measured bottleneck worth addressing.

Each increment is implemented and tested alone. A failure archives that
candidate as `NOT_PROMOTED`; it does not trigger tolerance widening or a change
to the canonical reference.

### Cache contract

Large cache data belong under `E:/dante_cache/dante_light/v8_1_exact_path`.
Git stores only compact manifests and hashes. A cache key must bind at least the
window identity, raw and relevant intermediate hashes, representation contract,
complete teacher fingerprint, artifact schema, dtype and shape. A missing key
is a cache miss. A digest, shape or identity mismatch is never silently reused.

Cold first-pass, warm replay and restart/resume measurements answer different
questions and must be reported separately. A warm-cache saving may not be
presented as a reduction of first-pass production cost.

## Workstream P: non-destructive prioritization

### Scope comes before a model

There are two materially different placements:

- **post-exact review priority** reorders records after the exact score exists;
  it cannot change the exact decision and is the recommended v8.1 primary;
- **pre-exact processing priority** uses a cheap proxy to decide which exact
  jobs run first. It is useful only under a demonstrated backlog and can still
  create practical omission through delay. It remains research-only in this
  proposal.

Before selecting either, a capacity audit must freeze the real arrival process,
service process, batching, operator-review budget and maximum tolerable delay.
The repository uses non-overlapping 32-second detector windows, while the saved
cost and shadow evidence were produced under different measurement semantics.
Those facts are insufficient by themselves to invent a useful top-X percent.

### Why aggregate Spearman is not a safety gate

An aggregate rank correlation can be acceptable while a rare morphology sits
systematically at the bottom of the queue. v8.1 therefore treats Spearman as
descriptive only. The primary safety endpoint is:

> protected recall within one pre-frozen review budget or time deadline,
> evaluated separately for every detector and every protected morphology.

The budget or deadline must come from the workload/capacity audit, not from the
ranking result. If several budgets are scientifically primary, a simultaneous
confidence band or a predeclared multiplicity correction is required; selecting
the best-looking point on a curve is forbidden.

All uncertainty resampling is by detector/GPS block. Known glitches and every
injection morphology remain separate cells. An underpowered cell is
`UNDERPOWERED`, never PASS through pooling. The exact-teacher-positive cohort is
an additional independent safety arm because it can contain cases outside the
named protected catalogue.

### Starvation prevention

"Non-destructive" means more than retaining a row on disk. Every valid window
must receive eventual exact service and every exact escalation must remain
available for review. The queue policy therefore needs a frozen age override or
maximum-delay rule. Its value is deliberately unresolved until the capacity
audit defines the operating regime.

The minimum comparator set is FIFO, exact-native-score priority with the same
age override, and the candidate priority with the same age override. A
candidate cannot claim value merely by outperforming random order while
degrading FIFO on NSBH or another protected cell.

## Evidence hierarchy and claim boundary

The two workstreams may not rescue one another:

- exact numerical equivalence does not establish a useful prioritizer;
- a useful queue order does not establish lower exact-path cost;
- warm-cache throughput does not establish cold first-pass speed;
- a ranking PASS does not authorize discarding any window;
- retrospective O4a/O4b replay does not constitute a new prospective claim.

The design is consistent with ranking literature that evaluates scarce
relevant cases at the top of a list rather than relying only on global rank
quality, and with work on prefix-level protected-group representation. These
are methodological analogies, not evidence about LIGO data: see
[Kar et al., 2015](https://proceedings.mlr.press/v37/kar15.html) and
[Zehlike et al., 2017](https://arxiv.org/abs/1706.06368).

## Decisions deliberately left open

The following are scientific or structural choices and require a separate
freeze before implementation that observes outcomes:

1. define the operational review budget or maximum delay from a capacity audit;
2. define the per-cell success bound and minimum effective block count through
   a power analysis;
3. decide whether bitwise equality is mandatory across every supported runtime
   or only inside the frozen acceptance environment, while retaining the
   existing cross-engine `SCORE_ATOL` ceiling;
4. define the promotion boundary from experimental engine to default engine.

Until these are frozen, both workstreams remain non-production proposals.

## Phase-0 result

The Phase-0 audit is recorded in
`docs/DANTE_LIGHT_V8_1_PHASE0_RESULT_2026-08-28.md`. Q-transform accounts for
70.91% of the measured isolated avoidable exact path. Exact compute capacity is
observed above nominal window cadence, but operator review capacity is
unmeasured; therefore no review budget/deadline or ranking gate is frozen. The
shared engine remains opt-in because the full 768-window cached O4b executor did
not demonstrate an end-to-end speedup despite exact numerical equivalence.

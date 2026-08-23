# DANTE-Light L4 prefilter v4: phase-aware freeze proposal

Date: 2026-08-23

Status: **PROPOSAL; NOT FROZEN; NO PROTECTED OUTCOMES OPENED**

Boundary: **routing disabled; O4b sealed; confirmation feature values uncomputed**

Increment 1 infrastructure was authorized on 2026-08-23. That authorization
covers generic identity-only schemas, seal/access/unlock guards, and synthetic
tests. It does not resolve or freeze the sample-size decisions below, so no
final cohort identity manifest may be generated yet.

## Decision requested

This document proposes a confirmatory path for a phase-aware DANTE-Light L4
prefilter. It does not freeze a protocol, select an operating threshold, or
authorize feature extraction on a reserved confirmation cohort. The proposed
primary is the analytic-phase representation already tested only on synthetic,
label-blind feasibility inputs. The earlier v1--v3 cohorts and results become
design evidence only and are ineligible for v4 fitting, threshold selection,
PASS/FAIL gates, or confirmation.

The author must explicitly approve the choices in the final checkpoint table
before implementation can change any scientific config.

## Scientific question and claim boundary

The primary question is whether phase-ordering summaries computed upstream of
the Q-transform/DINO path can reject at least the already-frozen product target
of O4a development traffic while retaining each protected detector/morphology
stratum. A PASS would establish only performance on the locked populations and
implementation. It would not establish:

- coverage outside the locked mass, spin, distance, glitch, and candidate scope;
- robustness to waveform-systematic error or to arbitrary non-CBC signals;
- astrophysical sensitivity, discovery significance, FAR, or FAP;
- O4b prospective performance;
- readiness to enable operational routing.

Known glitches, CBC injections, and DANTE ROBUST candidates remain separate
protected populations. No pooled positive-class result can replace their
per-detector and per-morphology gates.

## Why a new cohort is mandatory

The v2 diagnostics exposed weak NSBH separation and motivated the v3 and v4
feature designs. Reusing those same development outcomes to validate the new
phase-aware representation would be circular. Therefore:

1. all v1--v3 feature ledgers, ablations, diagnostics, and thresholds are
   labelled `EXPLORATORY_FOR_V4`;
2. no v4 row may share a detector/window identity, source identity, injection
   trial, or detector-specific 4096 s GPS block with any v1--v3 row;
3. v4 development and v4 confirmation must also be disjoint under all four
   identities;
4. the selection algorithm, source hashes, seed derivation, feature formula,
   preprocessing, model, and gates are frozen before any v4 development feature
   is extracted;
5. confirmation features are not extracted until development has independently
   produced `READY_FOR_CONFIRMATION` under the frozen verifier.

Freshness is therefore stronger than a new random assignment of the old rows.
The existing injection table is exhausted by the prior split; v4 requires a new
injection table with new O4a GPS blocks and independently drawn extrinsic
parameters.

## Proposed populations

The primary base is O4a for clean background, DANTE ROBUST candidates, and
software injections. O3b remains only the external labelled known-glitch
control. GWOSC provides public O4a strain and data-quality segments, but no
combined high-confidence O4a Gravity Spy catalogue equivalent to the O3b
catalogue used here. The public volunteer-classification release through July
2024 contains individual votes, not an interchangeable consensus/ML control
catalogue. Substituting it silently would change the measured population.

| Role | Run/source | Development | Sealed confirmation | Selection rule |
|---|---|---:|---:|---|
| clean background | O4a CBC_CAT1 | **300/detector proposed** | none | availability-screened, one 32 s window per detector/4096 s block, hash priority only |
| ROBUST candidate | frozen detector-aware O4a taxonomy | 25/detector | **60/detector proposed after power review** | class membership fixed first; one row per detector/4096 s block; no score ranking |
| known glitch | O3b Gravity Spy | 25/detector/morphology | **60/detector/morphology proposed after power review** | confidence and SNR rules inherited from v3; unused IDs and unused 4096 s blocks only |
| CBC injection | new O4a software-injection table | 35/detector/system | 90/detector/system | seven development and eighteen confirmation trials per distance; new GPS and extrinsics |

The protected known-glitch morphologies remain Blip, Koi Fish, and Scattered
Light. The protected injection systems remain BBH 30+30, BBH 10+10, and NSBH
10+1.4 solar masses at 100, 200, 400, 800, and 1600 Mpc. These populations and
development counts inherit the v3 contract. The confirmation recommendations
for ROBUST and known glitches are increased after the power analysis below. The
50% compute-reduction target is inherited as a product requirement, not
presented as a scientific constant.

Feasibility audit before freeze:

- after excluding previously used identities and 4096 s blocks, each required
  O3b detector/morphology pool still contains at least 951 distinct eligible
  blocks;
- the detector-aware O4a taxonomy retains 1,237 H1 and 1,539 L1 blocks with at
  least one ROBUST row outside prior blocks;
- the ROBUST population is dominated by `Family_01`; its gate therefore
  protects the frozen DANTE ROBUST decision population, not broad glitch-family
  coverage. The independent known-glitch and injection gates remain essential.

Hardware-injection intervals, CAT1 failures, unavailable padded windows, and
all prior cohort blocks are exclusion masks applied before hash-priority
selection. Availability screening may inspect only strain availability and
data-quality state, never phase features, DANTE scores, or target outcomes.

## Sample-size and power analysis

The confirmation endpoint is fixed-operating-point retention. AUC measures
ranking over positive and background populations; it cannot override a failed
retention safety gate. The proposed confirmation contains no background, so a
confirmation AUC is not identifiable without changing the endpoint and adding
another sealed population. Per-stratum development AUC remains useful as a
non-gating diagnostic: high AUC plus failed confirmation retention means that a
representation contains ranking signal but is not safe at the frozen operating
point. It must not be described as absence of morphological signal.

The power calculation uses the inherited gate: observed retention at least
0.90 and a two-sided 95% Wilson lower bound at least 0.80. The design
alternative is true retention 0.95 and the proposed target is at least 90%
probability of passing the gate. Both are explicit scientific assumptions, not
facts inferred from opened outcomes.

| n per stratum | minimum retained | observed retention at boundary | P(PASS | true retention=0.95) |
|---:|---:|---:|---:|
| 18 | 18 | 1.000 | 0.397 |
| 20 | 20 | 1.000 | 0.358 |
| 25 | 24 | 0.960 | 0.642 |
| 47 | 43 | 0.915 | 0.915 |
| 60 | 55 | 0.917 | **0.921** |
| 90 | 81 | 0.900 | **0.985** |

The old n=18 and n=20 confirmation strata are therefore substantially
underpowered even when true retention is 0.95. The smallest integer n reaching
the proposed 90% power target is 47, but binomial/Wilson gates have discrete
sample-size steps and power is not monotone at every adjacent n. Sixty is the
recommended round count: it clears the target with margin and is feasible in
both fresh ROBUST and O3b known-glitch pools. The injection n=90 already exceeds
the target and need not increase. At true retention exactly 0.90, pass
probability cannot be expected to approach 90%; that is the decision boundary,
not a high-power alternative.

The background n=300 now has a quantitative precision basis. At the worst-case
reduction fraction 0.5, the smallest even n with a 95% Wilson half-width no
larger than 0.06 is 264 per detector. Rounding to 300 gives half-width 0.0562;
n=250 gives 0.0615 and misses the declared precision target, while n=400 gives
0.0488 at additional data cost. Thus 300 is a predeclared precision compromise,
not an arbitrary preference.

The versioned recomputation contract is
`config/dante_light_prefilter_v4_power_analysis.json`; its compact result is
`artifacts/dante_light/prefilter_l4_v4_design/confirmation_power_analysis_v4.json`.
Both are explicitly `ANALYSIS_ONLY_NOT_FROZEN` and access no cohort outcomes.

## Proposed primary representation

The recommended primary is the full six-feature analytic-phase set already
defined before any fresh outcomes are viewed:

1. frequency--time Spearman correlation;
2. positive instantaneous-frequency step fraction;
3. weighted residual in the inspiral coordinate f^(-8/3);
4. weighted cubic circular-phase residual;
5. valid-frame fraction;
6. accumulated phase cycles.

The production extractor must use the canonical sequence:

`fetch padded strain -> whiten_context(pad=4 s) -> clean 32 s crop -> phase extractor`.

Its band, filter order, hop, smoothing, envelope gate, numerical fallback, and
feature order must be frozen in versioned config. Failure to obtain enough valid
frames must escalate that window to the exact path; it must never be imputed,
dropped, or treated as background. The v2 spectral features and v3 A+B features
may be reported as fixed descriptive comparators, but they are ineligible for
feature or operating-point selection.

Freezing all six features is recommended over post-hoc subset selection because
only synthetic feasibility data have informed them. Any future feature removal
after opening v4 development would create a v5 hypothesis, not a v4 retry.

## Model, gates, and uncertainty

To isolate the representation change, the proposal inherits the frozen v3
model and decision rules without modification:

- five-fold shuffled group cross-validation grouped by detector and 4096 s GPS
  block;
- L2 logistic regression with the versioned v3 regularization and equal
  background/positive-stratum weighting;
- a single primary feature set fixed before development;
- at least 50% effective O4a development call reduction;
- retention at least 0.90 and 95% Wilson lower bound at least 0.80 for every
  required detector/role/morphology stratum;
- confirmation endpoint limited to protected-stratum retention using the
  development-frozen model and operating threshold;
- detector/GPS-block bootstrap only, with the v3 number of resamples and
  confidence level, and informational rather than gate-setting intervals.

Known-glitch and injection strata are never aggregated for gate decisions.
Within-detector and cross-detector null statistics are not compared. Cost
accounting is paired per window: prefilter cost is paid on every row and exact
path cost is avoided only on rejected rows. Mean compute and tail latency are
reported separately; marginal percentiles are not subtracted.

No hyperparameter, regularization, feature subset, retention rule, or threshold
may be changed after development is opened. A failed primary becomes
`V4_NOT_READY`; it does not authorize tuning on the same cohort.

## Seed and partition rule

A new seed is mandatory. To avoid an arbitrary remembered integer, the
recommended rule is to derive separate cohort, injection, audit, and bootstrap
seeds from the first 64 bits of SHA256 over

`protocol_id + purpose + frozen parent digests`.

The exact protocol ID and resulting values must be written into config and
reviewed before cohort generation. Sorting is by the resulting SHA256 priority,
never by phase features, DANTE score, SNR beyond the pre-existing control
eligibility floor, or observed model outcome.

## Sealed-confirmation contract

"Never inspected" cannot be proven for undeclared private copies. It can be
made reproducible and fail-closed within a declared storage boundary. The
freeze must create:

1. `splits_v4.jsonl`, containing development and confirmation identities but no
   phase values, exact-path scores, classifier outputs, or thresholds;
2. `confirmation_seal_v4.json`, binding the confirmation identity digest,
   source hashes, selection-code hash, protocol hash, freeze commit, declared
   cache roots, and an empty access-log digest;
3. an append-only `confirmation_access_v4.jsonl`, initially empty;
4. a verifier proving, at freeze time, zero overlap with v1--v3 and v4
   development, zero confirmation records in all declared feature/cache roots,
   zero access-log entries, and absence of outcome fields from the split;
5. an extractor guard that rejects `partition=confirmation` unless supplied an
   unlock receipt generated from a `READY_FOR_CONFIRMATION` development result
   with exactly matching protocol, code, split, model, and threshold hashes.

The honest claim before opening is: "no confirmation feature or model outcome
exists in the repository, access ledger, or declared artifact roots, and the
confirmation identities were cryptographically sealed before development."
The project must not claim metaphysical proof that no unreported copy exists.

Confirmation is a one-shot evaluation. Missing data do not permit replacement
rows after outcomes are seen. A predeclared availability failure may invalidate
the cohort before any confirmation outcome is computed; otherwise the result is
reported as observed. A confirmation failure cannot be used to retune v4.

## Execution state machine

1. `PROPOSAL`: this document only; no scientific config change.
2. `FROZEN`: author-approved config, sources, hashes, seed derivation, feature
   order, cohorts, gates, and seal verifier committed.
3. `DEVELOPMENT_OPEN`: build phase features for development rows only.
4. `V4_NOT_READY`: any development gate fails; stop with confirmation and O4b
   sealed.
5. `READY_FOR_CONFIRMATION`: every development gate and provenance verifier
   passes; no parameters may change.
6. `CONFIRMATION_OPEN_ONCE`: create the unlock receipt, extract the sealed
   positive controls, and evaluate retention once.
7. `CONFIRMED_METHOD_CANDIDATE`: all confirmation strata pass. This still does
   not authorize routing.
8. `O4B_PROSPECTIVE_EVALUATION`: separate future checkpoint, only after author
   approval; one-shot operational endpoint with the v4 state frozen.

## Implementation plan after approval

### Increment 1: freeze machinery, no outcomes

- add the v4 protocol schema and explicit parent hashes;
- implement deterministic fresh-cohort construction and all prior-block
  exclusions;
- generate the new injection trial manifest without extracting features;
- implement the confirmation seal, access ledger, unlock guard, and verifier;
- add regression tests for determinism, disjointness, outcome-blind manifests,
  O4b denial, and clean-clone portability.

Checkpoint: review the full config and identity-only cohort diff. Do not proceed
if any confirmation feature artifact exists.

### Increment 2: production phase extractor, synthetic tests only

- promote the feasibility formula into a versioned production extractor;
- bind canonical padded whitening and fail-to-exact behavior;
- test deterministic output, numerical finiteness, phase scrambling,
  time/frequency ordering, invalid-frame escalation, and cost instrumentation;
- verify that no data loader can request confirmation or O4b in this increment.

Checkpoint: code and config hashes are frozen before any v4 development row is
processed.

### Increment 3: development-only experiment

- extract development features and paired timings;
- fit only the predeclared primary under grouped cross-validation;
- report every detector/morphology retention gate, Wilson interval, reduction,
  paired compute balance, failures, and provenance;
- run the independent verifier and full relevant suite from a clean clone.

Checkpoint: stop at `V4_NOT_READY` or ask for explicit authorization to open
confirmation after presenting the sealed-state audit.

### Increment 4: one-shot confirmation, conditional

- generate a hash-bound unlock receipt from the immutable development PASS;
- extract confirmation features once;
- evaluate protected-stratum retention only, with no refit or threshold change;
- publish PASS or FAIL plus all denominators and provenance.

### Increment 5: O4b, separately authorized

Only a confirmed method candidate may be proposed for locked O4b prospective
evaluation. O4b outcomes, operational routing, and merge into the active DANTE
path remain outside this freeze.

## Required author checkpoint before freeze

| Decision | Recommendation | Alternative and consequence |
|---|---|---|
| primary representation | all six phase-aware features, fixed a priori | a smaller set must be chosen now; it cannot be selected from fresh outcomes |
| O4a development background | 300 independent blocks per detector; 95% Wilson half-width 0.0562 at p=0.5 | 250 misses the 0.06 precision target; 400 improves it to 0.0488 at higher cost |
| confirmation power | n=60 for each ROBUST detector and known-glitch detector/morphology; retain n=90 for each injection detector/system | v3 n=18/20 has only 0.397/0.358 pass probability at true retention 0.95; approving n=60 also approves p1=0.95 and 90% target power as design assumptions |
| ROBUST source | frozen detector-aware taxonomy, hash-priority block sample | only unused legacy candidate list; too small for the proposed development plus powered confirmation counts |
| ROBUST scope limitation | the sample is dominated by `Family_01`; gate claim is limited to the frozen DANTE ROBUST decision population | broader family coverage requires a separately designed population and cannot be inferred from this gate |
| known-glitch controls | fresh unused O3b Gravity Spy rows | O4a volunteer votes change the label definition and require a new validation study |
| injections | new O4a GPS/extrinsic table, same systems/distances/counts | reusing prior trials is exploratory and cannot support confirmation |
| seeds | deterministic SHA256 derivation by purpose | explicit integers are acceptable only if frozen before generation |
| v3 gates/model | inherit unchanged | any change creates a broader statistical-design decision requiring separate justification |
| confirmation proof | cryptographic seal plus declared-root/access-ledger audit | absolute proof outside declared storage is impossible and must not be claimed |

Approval of this table authorizes implementation of the frozen protocol and
identity-only cohort machinery. It does not authorize opening development,
confirmation, O4b, or operational routing; those remain separate checkpoints.

## Public data references

- [GWOSC O4a data release](https://gwosc.org/O4/O4a/) documents public strain,
  CBC_CAT1/data-quality segments, hardware-injection intervals, and the O4a data
  DOI.
- [Gravity Spy volunteer classifications through July 2024](https://zenodo.org/records/13904422)
  documents individual volunteer classifications and explicitly distinguishes
  them from the earlier combined ML/volunteer O1--O3b catalogues.

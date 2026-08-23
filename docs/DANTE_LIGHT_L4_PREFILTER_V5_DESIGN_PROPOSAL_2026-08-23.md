# DANTE-Light L4 prefilter v5: learned-surrogate design proposal

Date: 2026-08-23

Status: **DESIGN ONLY; SCIENTIFIC CHECKPOINT REQUIRED**

Boundary: **no v5 protocol is frozen; no protected outcome has been opened;
routing remains disabled**

## Executive decision proposal

V4 is closed as `V4_NOT_READY`. Its ideal synthetic phase response did not
translate to useful discrimination on real detector strain: overall OOF AUC
was 0.634 and the constrained effective reduction was 0.67%. The result does
not justify another post-hoc variation of the same global analytic-phase
summaries.

The recommended v5 direction is a **small learned surrogate upstream of the
expensive Q-transform/DINO path**, trained to approximate the continuous exact
DANTE routing score from the canonical whitened 1-D subwindow. The primary
input arm should be a raw 1-D depthwise CNN. A compact complex-STFT CNN should
be the sole preregistered learned comparator. A fixed wavelet-scattering arm
may enter only a label-blind cost and dimensionality feasibility study; it is
not yet a v5 candidate.

This proposal deliberately stops before the decisions that would change what
is measured or how it is validated. Freezing the teacher target, cohort
identities, architecture family, thresholds, and promotion gates requires the
author's explicit scientific approval.

## What v4 established

The negative result has three distinct implications.

1. The six frozen summaries responded to phase ordering in an ideal,
   monocomponent synthetic chirp, so the implementation was not trivially
   insensitive to its intended construct.
2. On the closed real-strain development cohort, protected and background
   windows both resembled the phase-scrambled synthetic controls under those
   summaries. This is a synthetic-to-real construct-validity failure.
3. The canonical data path was inspected and no preprocessing-order defect was
   found: padded fetch, contextual whitening, clean 32 s extraction, and phase
   extraction occurred in the contracted order.

A plausible, explicitly post-hoc explanation is that a global analytic phase
over a broad 20--1024 Hz, 32 s, multicomponent window is unstable or diluted by
non-Gaussian and non-stationary detector noise. The evidence falsifies the six
global summaries, not all phase-sensitive representations. It nevertheless
makes another hand-designed global-phase variant a poor next primary.

The cross-protocol comparison must retain its comparability qualification:
v2 and v3 used the same 962-window cohort and can be compared directly;
v4 used a fresh 1,010-window cohort and its difference is descriptive rather
than a controlled representation-only effect.

| Development representation | Cohort size | Overall OOF AUC | Constrained effective reduction |
|---|---:|---:|---:|
| v2 spectral-evolution baseline | 962 | 0.8052 | 8.70% |
| v3 signed-ordering plus ridge primary | 962 | 0.7179 | 3.08% |
| v4 analytic-phase primary | 1,010 | 0.6341 | 0.67% |

The 0.805 value reproduced in the v3 dossier is the v2 control, not the v3
primary.

## V5 scientific question

The primary question is narrower than “can a neural network classify
glitches?”:

> Can a compact model operating before Q-transform/DINO reproduce enough of
> the exact DANTE routing statistic to avoid a material fraction of exact-path
> calls while preserving every separately protected detector/morphology
> stratum on independent data?

The proposed experiment measures **surrogate fidelity and safe computational
routing**. It does not independently validate an astrophysical signal
classifier. The teacher is the existing exact DANTE path, not physical truth;
agreement with it is therefore circular evidence for exact-path behavior and
must never be described as independent physical discovery evidence.

## Candidate representations

### A. Raw 1-D depthwise student — recommended primary

Input is the canonical whitened 32 s strain subwindow already required by the
pipeline. The feasibility proxy had 3,665 parameters and mean CPU batch-1
inference of 0.941 ms, with no additional representation cost. Those numbers
establish compute plausibility only: the proxy had random weights and gives no
evidence of learnability, calibration, fidelity, or retention.

Why it is primary:

- it is upstream of Q-transform and DINO, so a rejection can avoid their cost;
- local convolution can learn transient ordering without requiring a single
  global phase estimate;
- it has the largest measured compute margin of the two student shapes;
- it leaves the exact DANTE path unchanged for every escalated or audited
  window.

### B. Complex-STFT compact student — fixed comparator

This arm uses a cheap complex STFT and a compact 2-D CNN. The random-weight
feasibility proxy had 1,369 parameters, mean inference of 0.468 ms, and mean
STFT preprocessing of 1.977 ms. Its total measured proxy cost was therefore
about 2.45 ms per window.

It is a useful comparator because it exposes local time-frequency phase and
amplitude without the full Q-transform/DINO cost. It must not become an
open-ended family of hand-selected STFT statistics: window, hop, frequency
range, normalization, architecture, and training schedule must be frozen
before development outcomes are inspected.

### C. Wavelet scattering — feasibility only

Wavelet scattering is mathematically attractive because it builds
translation-invariant representations stable to small deformations and can
retain higher-order information beyond the power spectrum. A recent
gravitational-wave study reports that it can complement the Q-transform for
glitch characterization and permit efficient downstream architectures.

That literature does not demonstrate suitability for this routing endpoint,
this cost budget, or these protected strata. Before it can enter a protocol,
a label-blind benchmark must fix the transform order/scales, measure CPU
batch-1 preprocessing cost and output dimension on the release environment,
and test numerical determinism. No outcome labels, v4 development outcomes,
confirmation, or O4b may be used in that feasibility step.

### Excluded from v5 primary selection

- further variants of the v4 global analytic-phase summaries;
- a targeted NSBH mini-bank: the best 32-template feasibility bank had minimum
  match 0.413 against the subsequently frozen 0.97 safety threshold and about
  40 ms p95 kernel cost;
- a student whose input is a DINO/Q-transform product, because it retains the
  dominant computation the prefilter is meant to avoid;
- an unconstrained architecture or feature search over development outcomes;
- morphology-dependent runtime routing based on a known injection label.

## Teacher target: decision required before freeze

Two targets are scientifically different and must not be blended silently.

### Option 1: continuous exact-DANTE score distillation — recommended

Train the student on a frozen transform of the continuous exact DANTE score,
then calibrate detector-specific routing thresholds using only the designated
development/calibration partition. Ranking and calibration diagnostics remain
available without reducing the teacher to one historical threshold.

Advantages: preserves more teacher information; permits fidelity analysis
away from the routing boundary; allows threshold changes to remain a separate,
versioned calibration decision.

Risk: high global score agreement can conceal unsafe local errors in rare
protected strata. Promotion must therefore depend on the independent
per-detector/per-morphology retention gates, not on mean regression loss or
aggregate AUC.

### Option 2: direct exact-call decision imitation

Train directly on the binary exact-path escalation decision frozen at one
teacher threshold.

Advantage: optimizes the operational action directly. Disadvantages: discards
ranking information, entangles the model with one threshold, and can hide
poor calibration or brittleness close to the boundary.

Recommendation: Option 1 is the primary target. A binary decision head may be
reported as a prespecified ablation, but must not replace continuous fidelity
evidence.

No protected morphology label should enter the primary training loss. Those
labels define safety strata for threshold selection and validation. Adding a
supervised protected-role auxiliary loss would change the scientific object
from teacher distillation to a hybrid classifier and would require a separate
protocol and claim boundary.

## Anti-circular data architecture

V5 is a learned model and therefore needs more separation than the fixed
feature screens in v1--v4.

1. **Identity-only inventory.** Before labels or teacher outputs are read,
   enumerate detector/GPS/4096-s blocks already consumed by v1--v4 and verify
   how many untouched O4a blocks remain in the E: raw-data mirror. This audit
   may inspect identities and file integrity only.
2. **Training partition.** Fresh O4a blocks used to fit weights. Repeated
   windows from the same 4096-s block must never cross a split.
3. **Calibration/development partition.** Fresh, disjoint blocks used for
   architecture selection among the two frozen arms and for detector-specific
   threshold calibration. It must not reuse v4 development outcomes.
4. **One-shot confirmation partition.** Fresh identities sealed before any
   train/development outcomes are opened. Its manifest, access ledger and
   unlock receipt follow the v4 cryptographic boundary.
5. **O4b prospective partition.** Remains untouched until a v5 confirmation
   PASS and a separate authorization. O4b is not a source of model selection,
   threshold tuning, or debugging examples.

Known glitches and injections remain separate per detector and morphology.
No aggregate gate may compensate a weak morphology. Bootstrap uncertainty is
block-based, never i.i.d. All numerical constants and cohort counts must come
from a versioned config after the identity/power audits; none are to be copied
from this narrative.

The legacy `IMRPhenomD` NSBH point-particle control is insufficient as the only
NSBH safety evidence for a new learned model. V5 should preserve it as a
comparability control and add a separately named, physically broader NSBH
stress population only after waveform family, masses, spins, tides and
precession scope are preregistered. Results for the two populations must not be
pooled.

## Preregistered evaluation families

Exact numbers belong in the future frozen config. The protocol should include
the following families before any promotable run.

### Surrogate fidelity

- detector-specific and combined teacher-score rank correlation;
- absolute/calibration error, including error versus teacher-score quantile;
- false-negative routing against high-score teacher cases;
- fidelity by detector, GPS block and protected morphology;
- reliability near the eventual routing threshold.

These establish imitation fidelity only.

### Protected retention

- separate point retention and Wilson lower-bound gates for every
  detector/morphology stratum;
- frozen minimum sample sizes justified by a prospective power calculation;
- no averaging across BBH, NSBH, known-glitch morphology or DANTE-ROBUST;
- explicit worst-stratum decision rule.

### Compute and routing value

- paired per-window prefilter cost, routing decision and avoidable exact-path
  cost;
- mean expected net saving compared with mean expected saving;
- separately reported tail latency using paired observations, never a mix of
  medians and p95 values;
- the 50% effective-reduction target, if retained, identified explicitly as a
  product requirement rather than a scientific significance threshold;
- deterministic audit-stream cost included in effective reduction.

### Stability and shortcut controls

- multiple frozen training seeds, with promotion based on the worst replicate
  or another rule fixed in advance;
- detector and 4096-s block leakage tests;
- detector/run shortcut probes from learned representations;
- sensitivity to PSD/whitening perturbations and the versioned contextual-pad
  variants already used by DANTE validation;
- calibration drift across causal time blocks;
- failure analysis locked to aggregate categories before confirmation is
  opened, to prevent example-driven repair.

## Evidence hierarchy and allowed claims

| Evidence | Allowed conclusion | Forbidden conclusion |
|---|---|---|
| random-weight timing | architecture shape is computationally plausible | learned model is useful |
| train/internal validation | optimization is feasible | independent generalization |
| fresh development | candidate may be frozen for confirmation | operational validation |
| sealed one-shot confirmation | prespecified O4a endpoint generalized once | O4b/prospective readiness |
| later O4b locked evaluation | later-epoch evidence within its declared scope | physical discovery or universal run transfer |

Knowledge distillation is a model-compression strategy, not an independent
physical label. A v5 PASS would mean that the surrogate safely approximates
the exact DANTE routing role under the frozen cohorts and gates. Exact DANTE
remains authoritative for escalated and audit-stream windows.

## Falsification and stop rules

V5 must stop as `NOT_READY`, with confirmation still sealed, if any of the
following occurs in development:

- any protected detector/morphology gate fails;
- the prespecified effective-reduction product target fails;
- the paired expected net compute saving is non-positive or too unstable under
  the frozen uncertainty rule;
- replicate variability exceeds its frozen limit;
- shortcut probes show material detector/run discrimination unexplained by the
  target;
- a candidate requires post-hoc architecture, loss, threshold, or cohort
  changes after its outcomes are seen;
- exact recomputation/provenance verification fails.

If both learned arms fail, the result is evidence against these compact
surrogates under the chosen input and capacity. It is not authorization to
open confirmation, add a third arm post-hoc, or weaken retention gates.

## Incremental implementation plan

The plans below are intentionally small. Each later plan begins only after the
previous regression gate passes.

### Plan 1 — identity and feasibility foundation

**Objective:** establish whether a genuinely fresh v5 experiment is possible
without reading protected outcomes.

Task 1.1 — identity-only capacity audit

- Files: `config/dante_light_prefilter_v5_identity_audit.json`,
  `src/dante_light/prefilter_v5_identity.py`,
  `scripts/audit_dante_light_prefilter_v5_identities.py`,
  `artifacts/dante_light/prefilter_l4_v5_design/identity_audit_v5.json`, and
  `tests/test_dante_light_prefilter_v5_identity.py`.
- Action: enumerate v1--v4 detector/GPS/4096-s exclusions; inventory valid O4a
  files in the E: raw-data mirror; report capacity for disjoint train,
  calibration/development and confirmation identities. Read identities and
  integrity metadata only, never labels, teacher outputs, confirmation
  outcomes or O4b.
- Verify: exact detector+GPS uniqueness, 4096-s block disjointness, input-file
  hashes, an empty outcome-access ledger, Windows/WSL deterministic replay and
  the targeted regression tests.
- Done: fresh capacity is known and no outcome-bearing partition has been
  opened.

Task 1.2 — optional scattering feasibility

- Files: `config/dante_light_prefilter_v5_scattering_feasibility.json`,
  `src/dante_light/prefilter_v5_scattering.py`,
  `scripts/run_dante_light_prefilter_v5_scattering_feasibility.py`,
  `artifacts/dante_light/prefilter_l4_v5_design/scattering_feasibility_v5.json`,
  and `tests/test_dante_light_prefilter_v5_scattering.py`.
- Action: after an explicit dependency/license check, freeze one transform
  family and benchmark only output dimension, determinism and paired CPU
  batch-1 cost on outcome-blind inputs. Do not add a library silently and do
  not screen transform parameters against labels.
- Verify: pinned dependency provenance, exact config/source hashes, repeated
  output equality within a frozen tolerance, paired timing ledger and targeted
  tests on Windows and WSL.
- Done: scattering is either excluded on prespecified feasibility grounds or
  eligible to be proposed at a later checkpoint; it is not selected for v5 by
  this task.

### Plan 2 — scientific freeze checkpoint

**Objective:** convert the approved choices into an immutable protocol before
training.

Task 2.1 — protocol and power contract

- Files: `config/dante_light_prefilter_protocol_v5.json`,
  `config/dante_light_prefilter_v5_power_analysis.json`,
  `src/dante_light/prefilter_v5_protocol.py`,
  `src/dante_light/prefilter_v5_power.py`, and
  `tests/test_dante_light_prefilter_v5_protocol.py`.
- Action: freeze the approved teacher target, arms, architecture bounds,
  replicate seeds, loss, selection rule, cohort counts, per-stratum gates,
  paired-compute gate and shortcut controls. Every numerical constant must
  come from versioned config.
- Verify: exact power recomputation, protocol self-digest, schema validation,
  absence of hardcoded scientific constants and targeted tests.
- Done: the scientific object and complete decision rule are immutable before
  training.

Task 2.2 — split manifest and confirmation seal

- Files: `config/dante_light_prefilter_splits_v5.json`,
  `config/dante_light_prefilter_splits_v5.jsonl`,
  `config/dante_light_prefilter_v5_confirmation_seal.json`,
  `src/dante_light/prefilter_v5_seal.py`,
  `scripts/build_dante_light_prefilter_v5_freeze.py`, and
  `tests/test_dante_light_prefilter_v5_seal.py`.
- Action: materialize only the approved identities, derive deterministic seeds
  from parent digests, create the append-only access contract and seal the
  confirmation identities without outcomes.
- Verify: canonical Git-blob references, no detector+GPS/block overlap,
  identity-only confirmation seal, parent-hash closure and clean-clone replay.
- Done: train/development/confirmation identities are immutable and the
  confirmation cannot be opened without a valid unlock receipt.

This is a **human scientific-decision checkpoint**. Plan 2 cannot start from
this proposal alone.

### Plan 3 — training and internal calibration

**Objective:** train only the frozen arms without spending development or
confirmation outcomes on iterative design.

Task 3.1 — deterministic teacher ledger

- Files: `src/dante_light/prefilter_v5_teacher.py`,
  `scripts/build_dante_light_prefilter_v5_teacher_ledger.py`,
  `scripts/verify_dante_light_prefilter_v5_teacher_ledger.py`, and
  `tests/test_dante_light_prefilter_v5_teacher.py`; large ledgers remain in the
  versioned E: cache with compact hashes under
  `artifacts/dante_light/prefilter_l4_v5_training/`.
- Action: compute the frozen exact-DANTE continuous target once for training
  identities, recording detector+GPS, source hash, exact-path config hash and
  code reference. Never recompute a changed teacher into the same cache key.
- Verify: row identity, source/config/code hashes, exact replay sample, no
  development/confirmation/O4b access and targeted tests.
- Done: every training row has one provenance-closed teacher target.

Task 3.2 — frozen-arm replicate training

- Files: `src/dante_light/prefilter_v5_student.py`,
  `src/dante_light/prefilter_v5_training.py`,
  `scripts/train_dante_light_prefilter_v5.py`,
  `scripts/verify_dante_light_prefilter_v5_training.py`, and
  `tests/test_dante_light_prefilter_v5_training.py`; checkpoints and full
  ledgers remain in the E: cache with compact manifests in Git.
- Action: train every frozen arm and seed; fit normalization inside training
  folds; preserve failed replicates and prohibit favorable-seed selection.
- Verify: deterministic data identity, block isolation, checkpoint hashes,
  reproducible inference, complete replicate matrix and full regression suite.
- Done: every frozen replicate has an auditable record while development,
  confirmation and O4b access lists remain empty.

### Plan 4 — one-shot development decision

**Objective:** apply the frozen decision rule once on development.

Task 4.1 — frozen development evaluation

- Files: `src/dante_light/prefilter_v5_development.py`,
  `scripts/run_dante_light_prefilter_v5_development.py`,
  `artifacts/dante_light/prefilter_l4_v5_development/development_result_v5.json`,
  and `tests/test_dante_light_prefilter_v5_development.py`; full ledgers remain
  in the E: cache.
- Action: evaluate all arms and replicates once, recording score fidelity,
  per-stratum retention, shortcut controls and paired per-window timing.
- Verify: detector/GPS-block bootstrap recomputation, Wilson/power checks,
  paired compute identities, provenance hashes and targeted tests.
- Done: the complete frozen development matrix exists with no confirmation or
  O4b access.

Task 4.2 — fail-closed promotion decision

- Files: `src/dante_light/prefilter_v5_screening.py`,
  `scripts/verify_dante_light_prefilter_v5_development.py`, and
  `artifacts/dante_light/prefilter_l4_v5_development/screening_summary_v5.json`.
- Action: apply the prespecified worst-stratum, replicate-stability, compute and
  selection rules; select at most one immutable candidate only if every gate
  passes.
- Verify: independent summary rebuild, access audit, clean-clone verifier and
  full regression suite.
- Done: either `V5_NOT_READY` with confirmation still sealed, or one frozen
  candidate eligible for a separate unlock checkpoint.

### Plan 5 — confirmation and prospective boundary

**Objective:** use the sealed confirmation once, only after a verified
development PASS and explicit authorization.

Task 5.1 — authorized one-shot confirmation

- Files: `config/dante_light_prefilter_v5_confirmation_unlock.json`,
  `scripts/run_dante_light_prefilter_v5_confirmation.py`,
  `scripts/verify_dante_light_prefilter_v5_confirmation.py`, and
  `artifacts/dante_light/prefilter_l4_v5_confirmation/confirmation_result_v5.json`.
- Action: after explicit authorization, validate every protocol/code/split/model
  parent hash, open only the sealed confirmation identities and execute without
  tuning. Stop on the first provenance failure.
- Verify: signed unlock receipt, one-shot access ledger, exact artifact
  recomputation, clean-clone replay and full regression suite.
- Done: `V5_CONFIRMED` or `V5_NOT_READY`, with no threshold/model repair on
  confirmation outcomes.

Task 5.2 — retain the O4b boundary

- Files: the confirmation result's access section and the existing operational
  release-gate documentation; no O4b result file is created by this task.
- Action: record that confirmation does not authorize O4b access or routing;
  require a new explicit prospective-evaluation decision.
- Verify: O4b access ledger remains empty and the release gate remains
  fail-closed.
- Done: neither confirmation status silently becomes an operational claim.

## Plan-check result

The five-plan dependency chain is acyclic and each executable increment has a
bounded artifact set, an explicit verification path, and a measurable stop
condition. Requirement coverage includes construct validity, anti-circular
splits, surrogate fidelity, per-morphology safety, compute accounting,
stochastic stability, provenance and prospective boundaries.

One blocker is intentionally retained: the scientific freeze cannot proceed
until the author approves the teacher target and candidate ordering. No code
implementation should precede that decision except the outcome-blind identity
and optional scattering feasibility audit in Plan 1.

## Recommended checkpoint decision

Approve the following as the basis for Plan 1 and the later freeze proposal:

1. raw 1-D depthwise student as primary;
2. complex-STFT compact student as the only learned comparator;
3. continuous exact-DANTE score as primary teacher target;
4. no protected morphology labels in the primary training loss;
5. wavelet scattering limited to label-blind feasibility until cost and
   determinism are known;
6. entirely fresh, block-disjoint O4a train/development/confirmation identities,
   with O4b still prospective and sealed.

## Primary references

- Hinton, Vinyals and Dean,
  [Distilling the Knowledge in a Neural Network](https://arxiv.org/abs/1503.02531),
  for teacher-student model compression.
- Mallat,
  [Group Invariant Scattering](https://arxiv.org/abs/1101.2286), for
  translation invariance and stability to deformations.
- Licciardi et al.,
  [Wavelet Scattering Transform for Gravitational Waves Analysis](https://arxiv.org/abs/2411.19122),
  for a gravitational-wave glitch-characterization application and its
  complementarity with Q-transform representations.
- Fernandes et al.,
  [Convolutional Neural Networks for the classification of glitches in
  gravitational-wave data streams](https://arxiv.org/abs/2303.13917), for
  learned glitch representations and the importance of cross-run evaluation.

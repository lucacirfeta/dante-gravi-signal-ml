# DANTE-Light L4 v7 training-freeze proposal

Status: **SCIENTIFIC CHECKPOINT PROPOSAL; NO TRAINING OR PROTECTED ACCESS**

## Objective

Version 7 tests a selective-deferral task, not continuous-score distillation.
The only promotable candidate must learn a cheap score that orders windows from
safe-to-discard to must-defer. Detector-specific thresholds are selected once
on `threshold_search`; the fixed thresholds are then evaluated once on
`risk_calibration`. Confirmation and O4b remain sealed.

This proposal freezes the smallest experiment capable of answering that
question without reintroducing architecture search or favourable-seed
selection.

## Repository evidence checked

The proposal was cross-checked against these exact repository inputs:

| Evidence | Repository path | SHA256 |
|---|---|---|
| approved v7 outcome-blind contract | `config/dante_light_prefilter_v7_outcome_blind_contract.json` | `57ea8a6d8c6d779dda85821d54f977261c4665f9748cc280e258b687012f696f` |
| background teacher-prevalence audit | `artifacts/dante_light/prefilter_l4_v7_design/background_teacher_prevalence_audit_v7.json` | `6c9dab3f0d96b0751adbc9d45954a702fc31c52fdddb03014ac303b700cf1498` |
| v6 architecture/cost feasibility | `artifacts/dante_light/prefilter_l4_v6_design/phase_a_compute_feasibility_v6.json` | `84c6a41fc8de6cd39ca37509cb531053cbc64e468f6e68799508bb2d9b00c174` |
| v6 student implementation | `src/dante_light/prefilter_v6_phase_a.py` | `83a1776fbaef43da3342478fb88e96d5813681e73d6df954e4f8b4014fe9b0e8` |

The numerical checks reproduce H1 `23/1440`, L1 `49/1440`, Top-13 from
`round(256 * 68/1369)`, 3,665 trainable parameters per member, the prior
single-member CPU mean of `1.164515 ms`, the five-member estimate of
`5.822575 ms`, and the nominal-coverage design value
`0.5/(1-0.05) = 0.526315789`. The last two remain estimates, not promotion
evidence.

## Required correction to the current v7 wording

The current outcome-blind contract calls the student output an "estimated
probability" of deferral. That wording is not defensible under the frozen
case-control training design: the sample deliberately contains roughly equal
numbers of catalogued teacher positives and natural-background identities,
whereas the retrospective natural prevalence is only 1.60% in H1 and 3.40% in
L1. Under outcome-dependent sampling, a sigmoid trained with binary
cross-entropy is not automatically a calibrated population probability; in
particular, the population intercept is not identified without prevalence
correction or representative calibration data.

The contract should therefore be amended before training:

- output name: `defer_score`;
- semantics: bounded ranking score in `[0,1]`, not a natural-population
  posterior probability;
- no Platt, isotonic, temperature or prior-shift calibration in v7;
- threshold selection and every claim depend only on frozen retention and
  coverage, never on interpreting the numerical score as a probability.

The limited number of natural teacher positives in `threshold_search` and
`risk_calibration` is insufficient to add a reliable probability-calibration
stage without weakening the four-way split. This correction changes wording
and score interpretation, not the already approved safety endpoint.

## Recommended promotable model

Use one fixed five-member ensemble of the v6
`Raw1DTeacherAlignedStudent` architecture:

- canonical input: float32 whitened 1-D strain after context padding and clean
  32-s cropping;
- local encoder: unchanged v6 depthwise raw-strain encoder;
- pooling: exact teacher-aligned top fraction, `68/1369`; for 256 student
  instances this remains Top-13;
- binary head: one logit per member;
- ensemble score: arithmetic mean of the five sigmoid outputs;
- detector identity is not provided as a model input;
- detector-specific routing thresholds remain downstream;
- no STFT, morphology input, score-regression target or rank loss.

The architecture is selected from already-open v6 evidence, not from v7
outcomes. It has 3,665 parameters per member and an audited v6 CPU batch-one
mean inference time of 1.1645 ms per member. Five sequential forwards would be
approximately 5.8 ms before a fresh full-path benchmark, still far below the
historical paired avoidable exact-path mean of 481.6 ms. The actual ensemble
cost must nevertheless be measured outcome-blind; this estimate is not a PASS.

The ensemble is one candidate, not five candidates. Every member and its seed
are frozen before training. A nonfinite or irrecoverably divergent member
marks the ensemble `FAILED_NUMERICAL`; it may not be replaced by a sixth seed.
This avoids both best-seed selection and the very low familywise power that
would result from requiring five separate operating points to pass every
sample-level retention gate. Individual-member metrics remain descriptive
diagnostics only.

### Rejected alternatives for this increment

- **Single favourable replicate:** cheaper, but reopens seed selection or
  makes the result depend strongly on one initialization.
- **Worst-replicate operational promotion:** appropriate for the previous
  architecture-screening question, but inefficient here because v7 has one
  frozen deployed candidate and finite calibration strata.
- **Complex STFT:** more variable and more expensive in v5, without evidence
  that it repairs the relevant task.
- **Attention MIL or larger encoder:** both would mix a new task with another
  architecture search; v6 already found no score-fidelity rescue.

## Labels and training population

The binary teacher label is defined by the strict production rule:

`defer = native exact-DANTE score > historical detector threshold`.

The training partition contains, per detector, 150 catalogued teacher-positive
identities and 150 natural-shadow-traffic identities. "Background" is a
sampling role, not an assumed negative label: exact DANTE assigns its binary
label only when training is legitimately opened. No morphology, ROBUST,
Gravity Spy or injection label enters the loss.

Freeze an 80/20 internal split before teacher-label extraction, stratified by
detector and sampling role and grouped by detector/GPS-4096-s block. This gives
120 fit and 30 internal-validation blocks per detector/role. The previous 90/10
ratio would leave only 15 validation blocks per detector/role in this smaller
v7 training set. The internal validation set selects epochs only; it makes no
safety or promotion claim.

## Loss, batching and optimization

Recommended frozen contract:

- loss: unweighted `BCEWithLogitsLoss`, mean reduction;
- no focal term, label smoothing, asymmetric penalty or morphology weights;
- batch size 64, with 16 rows from each detector x sampling-role cell whenever
  a full batch is available;
- deterministic without-replacement reshuffle within each cell per epoch;
- final partial batch retained; no synthetic oversampling;
- equal mean contribution from H1 and L1;
- AdamW, learning rate `1e-3`, weight decay `1e-4`, betas `(0.9, 0.999)`,
  epsilon `1e-8`;
- no scheduler, no gradient clipping, float32, maximum 100 epochs;
- no augmentation beyond the canonical whitening/cropping path;
- member checkpoint: minimum equal-detector internal-validation BCE, ties to
  the earliest epoch.

Unweighted BCE is intentional. The sampling design already balances detector
and case-control roles, while the routing threshold implements the asymmetric
safety cost explicitly. Adding a positive weight or focal-loss gamma would add
an unvalidated degree of freedom and conflate representation learning with the
operating-point decision. Focal loss is classification-calibrated but is not a
strictly proper estimator of the class posterior without an additional
transformation; that extra calibration problem is unnecessary here.

Training completion requires finite inputs, logits, loss, gradients and
parameters; nonzero score variance in both detectors; and five complete frozen
members. AUROC, AUPRC, BCE, score histograms and member dispersion are reported
on internal validation but are not used to choose an architecture, seed, loss
or hyperparameter. There is no training-performance threshold that can be
retuned after inspection.

## Threshold-search and calibration score

For each detector, use the ensemble `defer_score` directly. Candidate
thresholds are the unique search scores plus the two endpoint rules
always-defer and always-discard. Select the threshold that maximizes natural
background discard fraction while the catalogued teacher-positive retention
gate passes for that detector. If tied, select the lower threshold, which is
more conservative because deferral is `score >= threshold`.

The selected H1/L1 thresholds and all model/checkpoint hashes are frozen before
opening any `risk_calibration` output. Calibration is evaluated once. Failure
of any primary, protected or operational gate gives `V7_NOT_READY`; no
threshold fallback, recalibration or member replacement is allowed.

Spearman correlation may be reported only as a historical diagnostic. It is
not a v7 gate and cannot block or rescue the selective-deferral candidate.

## Retention and deterministic audit stream

Retain the already versioned audit fraction `0.05`. The audit seed is derived
from the training/threshold contract digests and window identity. Each window
that the model would discard is sent to exact DANTE when the frozen hash-based
rule falls below `0.05`. The rule has a nominal 5% inclusion fraction; it does
not force exactly 5% in a finite cohort, so every result must report the
realized audited count and fraction.

Two quantities must remain distinct:

1. **Pre-audit model retention** is the primary and protected safety endpoint.
   Audit rescue cannot make an unsafe classifier pass.
2. **Post-audit exact-call reduction** is the operational endpoint and includes
   the exact calls caused by the audit stream.

In expectation under the frozen audit hash, nominal discard coverage `c` and
audit fraction `a=0.05` give effective call reduction `c(1-a)`. Thus 50%
effective reduction corresponds to a design target of at least
`0.5/0.95 = 0.526315789` nominal discard coverage. This algebra is not the
gate: the gate uses the realized post-audit exact-call reduction on the frozen
cohort.

Audit outcomes are logged for future drift monitoring but cannot change a v7
threshold or gate.

## Cost accounting

Measure on CPU batch size one using the same machine and timing boundary as the
paired exact-path ledger. Include:

- canonical input preparation not shared with the exact path;
- all five member forwards and ensemble aggregation;
- routing and deterministic audit decision;
- exact-DANTE cost for audited would-be discards;
- paired avoidable exact-path cost for genuinely avoided calls.

For window `i`, the steady-state net saving is

`I(model discards and not audited) * avoidable_exact_cost_i - light_cost_i`.

Use whole detector/GPS-block bootstrap with the frozen 2,000 resamples. Report
startup/model-load latency separately; do not mix it into the steady-state
per-window mean. The 50% call-reduction requirement and positive lower bound on
mean net saving remain separate gates.

## Baselines

The promotable decision concerns only the frozen ensemble. Report two analytic
sanity baselines:

- always defer: 100% retention, 0% reduction;
- always discard: 0% pre-audit retention, 95% post-audit reduction.

Optionally include the already implemented v2 `spectral_evolution` logistic
representation as a pre-registered, non-promotable diagnostic comparator on
training/search/calibration only. It must have its own independently frozen
threshold and may neither enter confirmation nor rescue a failed primary
candidate. This comparator is scientifically useful but not required to start
the primary experiment; excluding it keeps the increment smaller.

## Evidence hierarchy and limits

A v7 calibration PASS would establish only that the frozen ensemble and fixed
thresholds satisfy the retrospective O4a teacher-retention, protected-control
and compute gates on the independent calibration identities. It would not
establish:

- a calibrated probability of physical or instrumental novelty;
- independence from exact DANTE;
- safety for unseen morphology families, particularly given Family_01
  dominance;
- O4b, causal, online or operational readiness;
- permission to open confirmation automatically.

Confirmation remains a separate one-shot checkpoint. O4b remains sealed until
after successful confirmation and a further explicit decision.

## Execution plan after approval

### Increment 1 — training contract and mechanical benchmark

- Files: new v7 student, training-contract builder/verifier, tests and compact
  compute artifact.
- Action: amend `estimated_probability` to `defer_score`; freeze ensemble,
  seeds, 80/20 block split, BCE, optimizer, audit semantics and cost boundary;
  benchmark random-weight five-member inference without teacher outcomes.
- Verify: contract/hash verifier PASS, no protected access, full suite green.
- Done: one immutable training contract exists and no score/label has been
  opened.

### Increment 2 — training-only teacher labels and ensemble fit

- Files: training label ledger, five member checkpoints, compact training
  summary and verifier.
- Action: open training identities only, score exact labels, fit all five
  members under the frozen contract and build the ensemble artifact.
- Verify: all labels and checkpoints bind to identity/code/config hashes;
  search/calibration/confirmation/O4b access lists remain empty.
- Done: training is complete or fail-closed; no operating threshold exists.

### Increment 3 — scientific checkpoint before threshold search

- Files: training-only report and proposed one-shot search authorization.
- Action: report numerical health, internal diagnostics and measured ensemble
  cost without changing architecture or hyperparameters.
- Verify: no search or protected outcome was accessed.
- Done: a human decision either authorizes the already frozen one-shot search
  or closes v7 without spending calibration/confirmation.

## References used for the design choice

- El-Yaniv and Wiener, *On the Foundations of Noise-free Selective
  Classification*, JMLR 2010: risk/coverage formulation.
  https://jmlr.csail.mit.edu/papers/v11/el-yaniv10a.html
- Geifman and El-Yaniv, *Selective Classification for Deep Neural Networks*,
  NeurIPS 2017: selective prediction and risk-coverage motivation.
  https://proceedings.neurips.cc/paper/2017/file/4a8423d5e91fda00bb7e46540e2b0cf1-Paper.pdf
- Huang et al., *Assessing Risk Prediction Models in Case-Control Studies*,
  2010: population-risk calibration is not identified directly by fixed
  case-control sampling without prevalence/intercept correction.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC3045657/
- Charoenphakdee et al., *On Focal Loss for Class-Posterior Probability
  Estimation*, CVPR 2021: focal loss is classification-calibrated but not
  strictly proper for posterior probability estimation.
  https://openaccess.thecvf.com/content/CVPR2021/papers/Charoenphakdee_On_Focal_Loss_for_Class-Posterior_Probability_Estimation_A_Theoretical_Perspective_CVPR_2021_paper.pdf

## Decisions requested

Before any implementation or training, confirm or amend these six items:

1. replace probability semantics with an uncalibrated `defer_score`;
2. make the five-member mean-score ensemble the only promotable candidate;
3. use unweighted BCE with detector/sampling-role-balanced batches;
4. use the frozen 80/20 block split and unchanged AdamW optimization;
5. keep audit fraction 5%, with all safety gates measured pre-audit;
6. omit the v2 spectral comparator from the primary increment, or authorize it
   explicitly as non-promotable diagnostic only.

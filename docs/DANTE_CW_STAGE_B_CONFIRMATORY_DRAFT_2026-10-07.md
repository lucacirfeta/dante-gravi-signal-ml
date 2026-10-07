# CW Stage B: confirmatory protocol checkpoint

Status: DOCUMENTATION_DRAFT_NOT_PREREGISTERED. No active scientific config,
strain acquisition, score, population selection or execution is authorized by
this document. Stage A remains complete and descriptive; no repeat is needed.

## Author decisions and remaining numerical choices

The author selected the confirmatory path: nominal physically anchored
injection, paired flag-rate ratio as primary endpoint, reciprocal bounds
`[1/delta, delta]`, and paired discordance as secondary endpoint. Report the
two L1 CW-off epochs separately. Reserve a temporally disjoint CW-off pilot
for discordance and sample-size planning, not effect-driven endpoint selection.
No automatic transfer to H1 or reuse of H1/L1 nulls for V1 follows.

The suggested margin convention, maximum CW bias no greater than half the
one-sigma uncertainty of the real-population flag rate, is a candidate rule.
Its reporting population, uncertainty construction and numerical delta are
not all frozen. The latest author `procedi`, responding to the population
checkpoint, approves eventual admitted L1 O4b reporting data per declared
epoch, including CW-on with annotation, as the margin's target population.
It does not select GPS rows, epoch boundaries, DQ cuts or a numerical margin.
Secondary discordance limit, block scheme, pilot allocation,
power target, minimum tail support, confidence level/multiplicity and
step-zero spectral tolerance also remain author checkpoints.

## Verified planning inputs, not admitted populations

Read-only source: E:/dante_cache/dante_workflow/o4b_metadata_proposal_20261007/
snapshot_v1/proposal.json, SHA256
5233f7567afaaa354115f2178f30da39e69b8af1ea55901d23e8dc795d7dfc0e.
This inventory intersects DATA with all published NO-injection masks.
It remains immutable; adopting CW annotation does not rewrite it or admit
its rows to reference, calibration, pilot or evaluation.

Geometry for this capacity calculation comes from the approved synthetic
[Stage A contract](../config/dante_cw_stage_a_v1.json): analysis 32 seconds,
padding 4 seconds on each side. It is an illustrative capacity calculation,
not a Stage B grid, stride or population approval. For an interval of length D,
analysis-disjoint capacity is `max(0, floor((D - 8)/32))`; completely disjoint
40-second contexts have capacity `floor(D/40)`. Grid alignment and additional
context/split/DQ requirements can only reduce these ceilings.

| UTC epoch | Continuous intervals | Seconds | Analysis-disjoint capacity | Context-disjoint capacity |
| --- | ---: | ---: | ---: | ---: |
| August-September 2024 | 24 | 787923 | 24607 | 19689 |
| January 2025 | 29 | 285099 | 8887 | 7114 |
| November 2024 | 1 | 64 | 1 | 1 |

These are not independent-window counts. Adjacent analysis-disjoint contexts
overlap; even disjoint contexts can have correlated flags and noise states.
Continuous intervals are not automatically independent clusters. Effective
independent N is unknown. A pilot and context guards reduce usable capacity.
November cannot support an epoch-level experiment of useful power; omitting
it is a proposed scope decision, not a claim that padding leaves zero windows.

The inherited [point-p99 rule](../config/dante_o4a_corrected_protocol_v4.json)
uses `numpy.percentile(scores, 99.0)` and `score > session p99`. It supplies
a nominal one-percent reference tail, not a measured L1 O4b CW-off rate or
a qualified new 16k threshold. Do not transplant historical numeric thresholds.
The ROBUST classification above a threshold confidence limit is a different
decision rule; its rate cannot silently replace point-p99 exceedance.

## Approved reporting scope: population anchoring the scientific margin

Approved in principle: use the eventual admitted L1 O4b reporting population,
including CW-on data under the approved annotation policy, separately for each
predeclared reporting epoch. Freeze release/GPS/DQ, complete context, geometry,
reference/calibration exclusions and denominator before computing uncertainty.
The CW-off paired experiment is the validation sample, not automatically the
denominator of the paper's real-population flag rate. This proposal selects no
GPS rows or extra DQ veto and does not yet define the reporting epoch boundaries.

The narrower CW-off-only reporting alternative was not selected. Approval of
the reporting scope is not evidence that effects on CW-off noise transport
unchanged to every CW-on detector state. That limitation and the secondary
observational control remain explicit. If the publication reports selected
candidate counts rather than an all-window flag rate, its intended denominator
and consequential bias must be specified before adopting the proposed rule.

For the proposed rule, let p_pub and sigma_pub be the independently justified
planning rate and one-sigma uncertainty for that fixed reporting population.
The largest absolute change inside reciprocal bounds is
`p_pub * (delta - 1)`. Thus the candidate half-sigma convention gives
`delta <= 1 + sigma_pub/(2*p_pub)` for positive p_pub. This is arithmetic,
not an accepted numerical margin or an independence-based uncertainty estimate.
Neither quantity may be learned from confirmatory injection outcomes.

Do not recompute delta as confirmatory N grows: tightening the margin with the
same accumulating sample changes the target and can negate the expected power
gain. Freeze the planning inputs, uncertainty procedure and margin first.
Worse reporting precision must not silently justify a scientifically larger
acceptable bias; any additional scientific cap requires author approval.

## Pilot and confirmatory analysis skeleton

Freeze a metadata-defined pilot/confirmation allocation by temporal blocks
before scores. Do not random-split neighboring windows with shared whitening
contexts. Keep reference, threshold calibration, amplitude-validation, pilot
and confirmation inputs explicitly identified and context-disjoint wherever
required. Declare reference CW state. Pilot results may estimate discordance,
temporal dependence and feasibility only; no post-hoc dose, endpoint, margin,
favorable epoch or population changes.

For each confirmation epoch and the single primary nominal injection arm,
retain paired baseline/injected flags, both switching directions, rate ratio
and secondary discordance fraction. Keep the same independently calibrated
threshold and frozen pipeline in both arms. Recalibrating a threshold per arm
would change the question. The primary estimand is epoch-specific and includes
both score-increasing and score-decreasing CW effects.

Use a declared block-based paired uncertainty procedure, never an i.i.d.
bootstrap or independent-arm confidence interval. Paired power depends on
discordance and temporal dependence, not just the nominal rate and window
count. Freeze zero-flag handling: no added epsilon/pseudocount after observing
outcomes. Insufficient tail support, failed anchoring or inadequate power is
not evidence of equivalence. No numeric CI level, power target, resample count,
block length or multiplicity correction is chosen in this draft.

## Dose screening and step zero before any score

Stage A probes stationary tones in design noise and has no calibrated flag
endpoint or preregistered response-onset threshold. Therefore it cannot define
a post-hoc onset that makes Stage B an expected null. A public O4 PSD and
published amplitudes can inform a separately frozen feasibility screen;
antenna response, phase evolution/Doppler, binaries, hardware actuation and
amplitude history remain necessary for physical anchoring. The Stage A dose
definition is not automatically a real-detector calibration.

Step zero must validate simulated nominal narrowband power against real L1
CW-on measurements with declared calibration/actuation/history uncertainty,
without reading scores. Its data and tolerance need approval before strain
access. Failure prevents the primary experiment; correction requires a new
approved simulator freeze. Higher doses and the observational CW-on/CW-off
placebo are secondary/descriptive with predeclared multiplicity as appropriate.
No pooling of epochs, automatic H1 equivalence, relaxed failed margin or
undeclared band-excluded production method is allowed.

## Preparation verification

Read-only WSL arithmetic returned actual OS exit 0: three epoch groups,
54 intervals, 1073086 seconds and every capacity in the table reconciled.
The nominal tail was parsed from the versioned percentile estimator, not an
active new constant. These checks are metadata/arithmetic evidence only,
not numerical scientific regressions, independence, power or readiness PASS.
No strain, PSD from measured data, encoder or score was accessed.

## Proposed preregistration package -- not approved numerical settings

These recommendations are bundled for author review, not adopted runtime
constants. The final approved values must live in an isolated versioned
scientific contract before implementation/tests/freeze or real-data access.

| Field | Proposed rule | Still required before execution |
| --- | --- | --- |
| Primary flag | Same point-p99 exceedance in both arms; fresh independent 16k calibration, never historical numeric threshold | Author approval of flag definition and reference/calibration allocation |
| Primary family | Two epoch-specific nominal-amplitude rate ratios; no epoch pooling | Exact epoch boundaries and physically anchored primary waveform |
| Error control | Family alpha 0.05; Bonferroni epoch alpha 0.025; corresponding two-sided 95% paired intervals for equivalence | Qualified block-based interval procedure, not a t test copied onto rare flags |
| Power | At least 95% per epoch under no effect, giving at least 90% for both by a union bound | Pilot-based conservative dependence/discordance model and feasible sample size |
| Pilot | Target 20% of eligible CW-off duration per epoch, metadata-stratified and temporally separated; confirmation never recycled into pilot | Deterministic allocation and guards, approved before any score; actual capacity after all exclusions |
| Primary margin | Freeze delta from the approved reporting population's independent planning uncertainty using the candidate half-sigma rule | Reporting effective N, planning rate/uncertainty and any scientific cap; no plug-in from confirmation |
| Secondary discordance | Propose q_limit = p_pub * (delta - 1), sharing the primary absolute bias budget | Approval of this conservative identity-change budget; secondary reporting does not create another primary equivalence claim |
| Remaining doses | Descriptive only, no dose or favorable epoch selected from scores | Frozen noise-relative dose mapping and scope |

The confidence-level relation follows the two-one-sided-test construction:
an epoch alpha of 0.025 corresponds to a 95% interval. This specifies a proposed
decision rule, not coverage proof for a block-bootstrap estimator. See
[Lakens 2017](https://pmc.ncbi.nlm.nih.gov/articles/PMC5502906/).
Bonferroni here controls the family of equivalence claims; two marginal 95%
intervals are not asserted to have simultaneous 95% coverage.
No resample count, block length or minimum tail-count constant is borrowed
from historical calibration. Those require a qualified planning procedure.
Zero pilot discordance must not be interpreted as known zero variance;
zero bootstrap changes cannot by themselves certify equivalence. Block
coverage and rare/zero-flag behavior must be tested before the final freeze.
The pilot cannot relax the margin if the design is underpowered.

### Why the pilot matters: analytic sensitivity check only

For independent paired Bernoulli flags at a common rate p and true rate
ratio one, let q be the discordance probability. A delta-method planning
approximation gives `Var(log(rate_ratio)) = q/(N*p*p)`. With half-width
`m = log(delta)`, a normal confidence interval and known standard error,
the no-effect planning power is `2*Phi(m/SE - z_(1-alpha_epoch)) - 1`.
Thus the proposed 95% per-epoch power requires approximately
`N >= (z_(1-alpha_epoch) + z_((1+power_epoch)/2))^2 * q/(p*p*m*m)`.
This is an optimistic independent-pair sensitivity calculation, not an i.i.d.
bootstrap, a selected model, or empirical power for the actual detector data.

Using only the inherited nominal p99 tail for illustrative p=0.01:

| Illustrative delta, not the chosen margin | Illustrative discordance q | Required independent pairs, rounded up |
| --- | ---: | ---: |
| 1.03 | 0.0001 | 17587 |
| 1.03 | 0.001 | 175867 |
| 1.05 | 0.0001 | 6455 |
| 1.05 | 0.001 | 64550 |

Even before dependence, calibration/reference exclusions or a pilot, January
has only 8887 analysis-disjoint geometric slots. This comparison demonstrates
that feasibility can change drastically with discordance; it does not assert
the true q, certify adequate power or justify choosing a looser delta.
Failure of power/tail/coverage qualification leaves the confirmatory claim
INCONCLUSIVE rather than converting the study to evidence of no effect.

### Public parameter-history limitation found during preparation

The official [T2500198 v3 table](https://dcc.ligo.org/public/0200/T2500198/003/O4_injection_params.html)
lists an approximate O4 injection epoch stop at GPS 1420815618, converted
read-only to 2025-01-13 15:00:00 UTC. All 29 January CW-off intervals in the
retained inventory follow it: 2025-01-18 15:23:31 through
2025-01-24 15:11:56 UTC. This is not proof that parameters or realized
amplitudes changed, nor a reason to delete January from the study.

However, that summary alone does not establish the realized amplitude history
or a contemporaneous CW-on anchor for January. The
[GWOSC injection page](https://gwosc.org/O4/o4_inj/) identifies CW status masks
but does not supply the missing realization/history uncertainty budget.
Do not silently propagate nominal amplitudes beyond the listed epoch or infer
that all 18 listed pulsars were simultaneously realized at every GPS.
Confirm the history and supported nominal waveform with official documentation
or an author-authorized expert query before freezing step zero. No external
message has been sent. Published phase evolution and binary parameters must
be distinguished from independently verified hardware realization.

Step-zero spectral tolerance and public O4 PSD selection cannot be filled
with arbitrary percentages or the Stage A design PSD. They remain separate
prerequisites; no real strain or score is used to make this draft executable.

### Additional preparation checks

Read-only WSL UTC conversion returned actual OS exit 0 and confirmed all 29
January intervals lie after the approximate published stop. Separate analytic
planning arithmetic returned actual OS exit 0; all four sample-size scenarios
meet the proposed normal-approximation target after rounding. No measurement,
simulation of detector outcomes, bootstrap, scientific regression suite or
Stage B/O4b execution was performed.

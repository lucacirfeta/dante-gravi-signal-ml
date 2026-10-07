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
not frozen. Secondary discordance limit, block scheme, pilot allocation,
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

## First author choice: population anchoring the scientific margin

Recommended proposal: use the eventual admitted L1 O4b reporting population,
including CW-on data under the approved annotation policy, separately for each
predeclared reporting epoch. Freeze release/GPS/DQ, complete context, geometry,
reference/calibration exclusions and denominator before computing uncertainty.
The CW-off paired experiment is the validation sample, not automatically the
denominator of the paper's real-population flag rate. This proposal selects no
GPS rows or extra DQ veto and does not yet define the reporting epoch boundaries.

Alternative: anchor the margin and scientific claim to CW-off data alone.
That is narrower and does not establish robustness of the CW-on population
that motivates this experiment. If the publication instead reports selected
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

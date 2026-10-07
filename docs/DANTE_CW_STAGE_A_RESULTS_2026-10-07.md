# Synthetic CW preprocessing Stage A results

The approved synthetic experiment completed on7October2026 with actual run
OSexit0. All3280 contexts are retained and passed the complete artifact
integrity check. This measures descriptive preprocessing response to stationary
tones in Gaussian design noise; it does not establish real CW equivalence,
decision-level robustness, detector safety or O4b readiness.

## Execution and tests

Implementation freeze: local commitb7f2df4. Source/config/CLI copied byte-exact
into `/home/atafe/dante_bench/cw_stage_a_20261007/execution_v1`. Run output:
`/home/atafe/dante_bench/cw_stage_a_20261007/run_v1` on Linuxext4. One supervisor
and controller,13spawned CPU workers with one thread each. No GPU/DINO inference.
Completion12:30:08UTC (14:30Rome). Durable parent run_v1.supervisor.log records
`SUPERVISOR_PID=310`, `CONTROLLER_PID=420`, `RUN_EXIT_CODE=0`; interactive
session97566 also completed with actual OSexit0. Separate stdout/stderr logs;
stderr empty at the final observation.

Before freeze, WSL targeted regression suite:101passed,14upstream warnings,
16.51s, actualOS0; Ruff3newfilesPASS. A real spawned synthetic1991Hz fixture
exactly matches the inherited PatchProducer uint8RGB image. These are pre-run
tests, not a separately repeated post-run numerical scientific suite.
Existing scientific source/config.yaml rawSHA pins remained unchanged.

## Retained measurements

16independent PCG64 child noises are shared across2880singleton injections,
16baseline contexts and384two-tone contexts. Frequencies and doses are from
the approved isolated [contract](../config/dante_cw_stage_a_v1.json).
The18probe frequencies use the official
[T2500198v3 epoch-start column](https://dcc.ligo.org/public/0200/T2500198/003/O4_injection_params.html),
not time-dependent detector-frame waveforms or hardware amplitude calibration.
The [LALSimulation design PSD](https://lscsoft.docs.ligo.org/lalsuite/7.26/lalsimulation/group___l_a_l_sim_noise_p_s_d__c.html)
is not a measuredL1/O4b PSD.

All3280NPZ files retain full temporal PSDs, uint8RGB images and scalarQmaps,
plus native/resized Q frequency profiles and coordinates. All3280JSON receipts
bind the paired input noise and baseline bytes. Every injected arm independently
re-estimates the inherited whitening ASD. One-Hz tone-only Hann-periodogram
power sets the input dose relative to the known synthesis PSD.

The native Q array is time by frequency. Its returned coordinates are retained
per arm; winning native grids are not assumed equal. Resized coordinates describe
the inherited image interpolation, not new physical spectral resolution.
Two-tone component bands overlap at small separations; their responses include
the whole paired injection and cannot be attributed independently to one tone.
No resolved/unresolved criterion is fitted or claimed.

## Selected descriptive responses

The following are medians across16noises at input power ratioR=1 and phase0.
Full median/minimum/maximum summaries remain separate by frequency,dose and
phase in verification.json. Extrema are descriptive ranges, not confidence
intervals. Selecting these examples does not make them primary acceptance tests.

| Probe frequency Hz | Signed excess power after whitening | Noise-relative G | Mean absolute RGB difference divided by255 |
| --- | --- | --- | --- |
| 12.425616 outside analysis band | 6.00355e-13 | 0.162176 | 4.58761e-7 |
| 26.321649 low band | 1.31510e-5 | 0.236751 | 0.00236326 |
| 265.574543 interior | 1.43186e-5 | 0.0918262 | 0.000575895 |
| 1991.092162 near upper filter edge | 1.05393e-5 | 0.157504 | 0.000119318 |
| 2991.092162 outside analysis band | 5.94913e-13 | 0.153369 | 0 |

G alone is not filter gain: attenuation of both the line and local noise can
cancel in this ratio, particularly outside the passband where absolute excess
is tiny. Negative responses also occur and are retained. The RGB observable
has no physical power units and does not measure encoder score or flag changes.
The observed nonzero image responses establish neither scientific significance
nor acceptable decision impact, because StageA has no equivalence margin.

## Integrity and limits

Summary status: `COMPLETE_DESCRIPTIVE_SYNTHETIC_STAGE_A_ONLY`.
Verification: `PASS_RETAINED_ARTIFACT_INTEGRITY_ONLY`.
Actual cardinalities:3280receipts,3280NPZ,16noiseNPY; no failure,tmp,partial or
controller.lock. Verification hashes every artifact, checks identity/count and
finiteness, and reconstructs all retained paired diagnostic metrics. It does
not repeat the numerical preprocessing chain or validate real injections.

- summarySHA200003323561d2e39183d8373e704bc3019b9dfbbc78ad6f2cd4548b93868cb2
- verificationSHAbbd5f69b03a606034169b02334af6fcfdd2b5802f1bcf77b58fce7c830b32e8f
- freezeSHA5c9307aafbb0ed74c90aa4bd020d0750e2d1f687f7d4228a62f2538c36aec360

## Next author checkpoint

Before StageB uses any real strain, approve its step-zero spectral amplitude
anchoring and uncertainty/history checks, detector/epoch-disjoint inputs,
reference CW state, one decision-unit primary endpoint, bilateral scientific
margin, independent block/power/tail support and multiplicity rule. The paired
experiment is primary; observational placebo is secondary and cannot supply
its equivalence margin. No automatic H1transfer or V1null reuse.

StageA completion does not authorize acquisition/scoring of O4b, StageB,
production activation or reopening the author-interrupted old verifier.
Monitor remains paused. No StageA controller or worker remains active.

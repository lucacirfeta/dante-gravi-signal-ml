# CW preprocessing qualification draft

## Approved scope and execution boundary

The author approved `aLIGOZeroDetHighPower` as the public design-noise
benchmark for synthetic Stage A on 7 October 2026. This is not a measured
Livingston PSD and cannot establish robustness on L1 O4b strain. Native
16,384 Hz processing with the requested Q-transform band 20..2048 Hz is
approved in principle; the production configuration remains 4096 Hz.

The author first approved the dimensionless dose definition, then approved
the full bounded numeric package below with the latest `procedi`. Its settings
are versioned in the isolated `config/dante_cw_stage_a_v1.json`; they are not
active in production configuration.

Implementation is frozen in local commitb7f2df4 after101 targeted WSL tests
and exact inherited uint8RGB fixture equality. One synthetic StageA run is
tracked in08.49; its outcome is separate from the pre-run implementation tests.
No acceptance margin or production promotion follows this approval. StageB,
O4b execution and any new strain acquisition remain separately gated.
Automation stays paused; historical calibration and its author-interrupted
verifier remain unchanged.

CW status is to be annotated rather than globally vetoed, following the
author's confirmed option 1. The original metadata snapshot and its strict
all-NO-mask inventory remain intact; they are not admitted populations.

## Public inputs and available runtime

The PSD implementation is
`lalsimulation.SimNoisePSDaLIGOZeroDetHighPower`, documented in
[LALSimulation](https://lscsoft.docs.ligo.org/lalsuite/7.26/lalsimulation/group___l_a_l_sim_noise_p_s_d__c.html).
Its existing mention in `config/dante_light_prefilter_v4_feasibility.json`
belongs to a separate, inactive feasibility study and supplies neither the
new study's settings nor an L1 reference population.

Frequencies for the stationary-tone diagnostics must come from the versioned
[O4 pulsar parameter publication T2500198 v3](https://dcc.ligo.org/T2500198/public).
The eventual contract must distinguish reference-epoch frequencies from
epoch-dependent frequencies. A stationary tone at a published frequency is
a preprocessing probe, not a reproduction of detector antenna response,
spin-down, Doppler modulation, binary motion or hardware actuation.

A read-only import check on 7 October returned OS exit 0: Python 3.11.15,
LALSuite 7.26.15, GWpy 4.0.1, SciPy 1.17.1 and NumPy 2.4.6; the PSD callable
is available. No PSD values, synthetic noise, strain or scores were generated.
This is availability evidence, not a frozen runtime or qualification PASS.

## Stage A paired synthetic characterization

Generate Gaussian colored noise from the approved design PSD. Each baseline
and injected arm must share the exact noise realization and complete padded
context. Add the tone before whitening, over that full context; recompute the
whitening PSD independently in each arm. Keep the approved per-image min-max
normalization. A line becoming the image maximum and compressing other
features is a preregistered possible mechanism, not an observed result.

Measure two distinct outputs:

- Temporal output after whitening, bandpass and cropping: empirical excess
  narrowband power relative to local noise. The estimator, integration band,
  local-noise definition and normalization are still pending approval.
- Final Q-transform image: change in representation after Q normalization,
  resize, min-max and Cividis mapping. RGB values are not physical power;
  image contrast changes must not be labelled spectral gain.

Whitening and min-max make the response dependent on the noise realization
and injection amplitude. Report a response surface with paired replicates,
not a universal linear transfer function or an assumed monotonic curve.
Apparent image saturation alone is not evidence of strain saturation.

Two-tone or frequency-sweep probes assess resolution separately in the
temporal diagnostic and final image. Frequency spacing and the observable
criterion for resolving two lines must be specified before measurement;
neither FFT spacing nor image pixel spacing alone establishes resolution.

Stage A contains no encoder, reference index, calibrated threshold or flag
claim. Its conclusions are restricted to the tested preprocessing,
frequencies, dose range and synthetic noise model. A change of library or
configuration requires renewed qualification even if endpoints stay fixed.

## Implementation evidence to preserve

The current `whiten_context` crops the padded raw context, calls `whiten()`,
then bandpasses it; the analysis crop follows. A 32-second analysis window
with complete 4-second padding on each side uses a 40-second PSD context,
not an entire session or external ASD. In the inspected runtime, whitening
defaults use median Welch PSD, 2-second Hann FFTs, zero overlap and a
2-second whitening FIR. These are implementation observations, not measured
CW attenuation or acceptance criteria.

The runtime bandpass is Chebyshev I, in second-order sections, applied
forward-backward. The local Butterworth docstring does not describe that
runtime behavior. Its order is chosen automatically: the inspected 4k
configuration and a diagnostic 16k design with the same limits both have
prototype order 5 and bandpass order 10 per pass. No filter was applied to
strain in that diagnostic, and frozen sources were not corrected or changed.

At 4096 Hz the requested Q upper bound equals Nyquist, 2048 Hz, but the
actual bandpass upper pass edge is clamped to 1843.2 Hz with stop edge
2027.52 Hz. At 16384 Hz the same code would use 2000 Hz and 3000 Hz. This is
not historical high-band equivalence; the 16k chain still needs measurement.
The design-noise synthesis also needs an explicit valid frequency domain,
low-frequency/DC handling and out-of-analysis-band prescription. The
20..2048 Hz analysis band does not itself specify a full synthesis PSD.

## Stage B and real amplitude anchoring

The author approves preserving normalization, beginning the paired real
experiment in L1, and the extended fallback rules. L1 CW-off epochs must be
reported separately, without automatic transfer to H1. The reference's CW
state must be explicit and reference, calibration and test contexts
temporally disjoint. A CW-on reference is a possibility, not a selected
population; a CW-off baseline relative to that reference is not an
injection-free-reference comparison.

Before any Stage B score, step zero must compare real CW-on narrowband power
with CW-off strain plus a physically modelled software injection. Declare
calibration, actuation and amplitude-history uncertainties, and check whether
published amplitudes changed during the relevant epochs. T2500198 alone is
not treated as proof of realized amplitudes or their temporal constancy.
[GWOSC injection documentation](https://gwosc.org/O4/o4_inj/) establishes CW
presence in LIGO, not the simulation's spectral agreement with L1 strain.
Failure of step zero prevents the primary experiment: correct the simulator
under a new approved freeze or abandon that design.

The primary real-data endpoint must be in decision units, not mean score:
choose flag-rate change at an independently calibrated threshold or a
specified percentile endpoint. Nominal anchored amplitude is primary,
epoch by epoch; other doses/endpoints are descriptive or have an explicit
multiplicity procedure. The paired equivalence margin must derive from a
scientifically consequential change independently of data, not a placebo.

The observational CW-on/CW-off comparison is secondary. Account for epoch,
noise state and time from the continuous DATA-segment boundary; that boundary
is a metadata proxy, not verified physical lock-acquisition time. CW-on/CW-on
placebos may inform this secondary comparison, not the paired margin. Power,
effective independent blocks and minimum tail support must be fixed before
scores. Any bootstrap remains block-based, never i.i.d.

Failed or inconclusive equivalence does not permit relaxed margins. Sensitivity
that lowers scores matters as well as sensitivity that raises them. Equivalence
only near nominal amplitude supports only the tested noise-relative range.
A band-excluded robustness arm requires its own declared contract and compatible
reference/calibration; it cannot silently become the production method.

## Minimum decisions before measurements

| Field | Status and proposed next choice |
| --- | --- |
| Stage A design PSD | Approved: aLIGOZeroDetHighPower, not measured L1 noise |
| Noise-relative dose | Approved: integrated line power divided by known model noise power in the same one-Hz band |
| Stage A spectral and image observables | Approved: the full package below; descriptive two-tone profiles, no binary resolution criterion |
| Stage A grid and reproducibility | Approved: doses, frequencies, phases, spacings,16 child noises and seed policy below; descriptive median/min/max only |
| Native 16k configuration | Tested isolated contract and source freeze08.49; unchanged production configuration |
| Stage B primary endpoint | Author selected confirmatory paired flag-rate ratio with reciprocal bounds; secondary paired discordance |
| Stage B acceptance and power | Pending bilateral margin, block scheme, tail support, power target and multiplicity across epochs |
| Stage B real inputs and anchoring | Pending disjoint populations, reference CW state, amplitude history and step-zero spectral agreement criterion |

StageA definitions have been approved, tested and frozen separately in08.49.
StageB definitions still need approval before any real-data implementation.
StageA is descriptive qualification, not an O4b readiness or CW immunity certificate.

The later [Stage B confirmatory draft](DANTE_CW_STAGE_B_CONFIRMATORY_DRAFT_2026-10-07.md)
supersedes the earlier endpoint-choice language above. The reporting population,
numeric margin, pilot/power/block scheme and real anchoring remain checkpoints;
confirmatory direction is not permission to infer those parameters or launch.

## Approved first descriptive package

The author's latest `procedi` approves **the complete numeric package** below,
following its proposal in546d07d. It is now represented by the isolated
`config/dante_cw_stage_a_v1.json`, with tests and source freeze before execution.
This approval supersedes StageA pending/proposed language in the preceding
historical preparation sections; StageB decisions remain pending. Existing
production configuration and historical scientific sources remain unchanged.

### Synthetic noise and paired inputs

Propose 16 independent Gaussian noise realizations at 16384 Hz, each generated
over 128 seconds, taking the central 40 seconds for the unchanged 32-second
analysis with four seconds of padding on each side. The longer generation
avoids equating the analysed context with the complete periodic FFT synthesis
interval; it does not make the noise representative of a real detector.
Use NumPy PCG64 with SeedSequence master seed 20261007 and 16 child streams,
shared across frequencies and doses. Different phases and doses on the same
noise are not extra independent realizations.

Use the approved PSD from 10 Hz to Nyquist; below 10 Hz propose a constant
extension at S_h(10 Hz), with zero DC and Nyquist Fourier components. This
is an explicit synthetic boundary convention, not physical detector noise.
The [LALSimulation model](https://lscsoft.docs.ligo.org/lalsuite/7.26/lalsimulation/group___l_a_l_sim_noise_p_s_d__c.html)
includes only thermal and quantum noise and is documented as valid above
approximately 9 Hz. Do not extrapolate its formula to zero. Test one-sided
noise synthesis normalization separately from whitening PSD estimation.

### Frequencies and doses

Use all 18 `f0 (epoch start)` values in the
[T2500198 v3 table](https://dcc.ligo.org/public/0200/T2500198/003/O4_injection_params.html),
one stationary tone at a time, preserving pulsar IDs. This is a diagnostic
column choice, not the detector-frame frequency at every O4b GPS. Retain the
two out-of-analysis-band tones as labelled controls, not silently excluded
trials or evidence of in-band validation. No hardware amplitude is inferred.

Propose a one-Hz band B centered on each tone and doses R = 0.01, 0.1, 1,
10, 100, plus a shared no-injection baseline. Noise power is the integral of
the known synthesis PSD over B, not estimated from injected data. Scale each
tone so its tone-only Hann-periodogram power integrated over B, on the central
32 seconds, equals R times that noise power. Use the estimator defined below
for this construction, accounting for off-bin leakage rather than substituting
total sample mean square for in-band power. Inject over all 40 seconds,
with phases 0 and pi/2 at
analysis start. R is model-relative power, not a nominal hardware multiplier.
This four-decade power sweep is descriptive, not a statistical power guarantee.

The singleton workload is 2880 injected contexts: 18 frequencies x 5 doses x
16 noise realizations x 2 phases, plus 16 baselines. Reuse a baseline only
for its exact identical noise input; every injected arm recomputes whitening
PSD. Baseline images are not reference-index or threshold-calibration inputs.

### Spectral and image responses

For temporal output after whitening, bandpass and crop, propose a one-sided
full-32-second Hann periodogram, constant detrending, no zero-padding and
`scaling='density'`; see [SciPy periodogram](https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.signal.periodogram.html).
This diagnostic estimator is separate from the inherited whitening estimator.
Integrate bin powers with bin-width overlap over B. Retain P_base(B),
P_injected(B), their signed difference, E = (P_injected - P_base) / P_base,
and G = E / R. G is empirical response, not a linear filter gain. Keep negative
E; a nonpositive/nonfinite denominator is a diagnostic failure, never fixed
with an epsilon or clipping.

For final uint8 RGB images propose full-image mean absolute paired pixel
difference divided by 255. Keep images and resized min-max scalar Q maps for
interpretation. Neither has physical power units. Record Q frequency grids
when the optimizer chooses different Q values; do not assume native bins
match between arms. Keep inherited 256 x 256 geometry and Cividis mapping.
No encoder, reference index, calibrated threshold or flag is computed.

Retain every pair; report median/minimum/maximum over the 16 noise realizations
separately by phase, frequency and dose. These are descriptive summaries, not
confidence intervals or equivalence tests. No bootstrap or success threshold
is introduced in this first package.

G is specifically a noise-relative response. A linear filter attenuating
both a tone and local noise can cancel in that ratio; G alone cannot establish
bandpass attenuation. The absolute signed excess P_injected - P_base must also
be shown in post-whitening units, not physical input-strain power. Together
these characterize the whole chain without attributing a measured change to
one component or assuming the filter's nominal pass edge predicts it.

### Resolution probes and workload

Propose tone pairs centered on published pulsars 10, 0 and 14, covering low
band, interior and high edge. Separations are 0.03125, 0.0625, 0.125, 0.25,
0.5, 1, 2 and 4 Hz. Each component has R = 1 in its own one-Hz band and
phase 0; overlapping bands are not independent power measurements. Reusing
the same 16 noise realizations gives 384 pair contexts. Total proposed
workload: **3280 contexts**, not 3280 independent experiments.

Keep full temporal spectral profiles, final images and native/resized scalar
Q profiles with frequency coordinates. Do not infer minimum resolved
separation from FFT spacing or add a post-hoc peak/valley threshold. This
first package characterizes profiles; a binary resolution endpoint requires
a separately approved criterion before becoming an acceptance rule.

### Isolated implementation after approval

Use the existing scientific primitives in a synthetic worker with explicit
16384 Hz input; assert rate preservation through whitening and crop. Do not
use the default 4096 Hz resampling route or modify frozen production sources.
Freeze runtime/filter settings and fixture equality with inherited primitives.
This qualifies an isolated call chain, not installed production 16k routing.

Tests must cover paired identity, exact dose construction, complete context,
noise normalization, probe counts, estimator units, invalid denominator
rejection, source/config boundaries and absence of real-strain/encoder access.
Fixtures precede source freeze; only then launch one fresh Stage A run on
Linux ext4, with CPU workers bounded by memory. GPU inference is absent by
design. No execution-time promise or automated Stage B/O4b/monitor follows.

## Preparation verification

Documentation-only scope; numerical regression suites are not rerun or
claimed as new evidence. The availability check above passed with observed
OS exit 0. Nine required boundary markers and five local references passed
the documentation check. The staged diff contains only five documentation
files and `git diff --cached --check` passed, with observed OS exit 0.
These historical checks validate scope, not the eventual numerical method.
Those preparation checks did not run or numerically qualify the package.
Implementation and measurement evidence is tracked separately in08.49.

Package revision checks returned OS exit 0: twelve approval/boundary markers
passed, and 18 x 5 x 16 x 2 + 16 + 3 x 8 x 16 = 3280 workload contexts
reconciled. These are document/arithmetic checks, not numerical experiment
tests or a qualified implementation.

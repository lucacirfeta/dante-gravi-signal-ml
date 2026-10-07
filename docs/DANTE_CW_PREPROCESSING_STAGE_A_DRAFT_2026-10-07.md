# CW preprocessing qualification draft

## Approved scope and execution boundary

The author approved `aLIGOZeroDetHighPower` as the public design-noise
benchmark for synthetic Stage A on 7 October 2026. This is not a measured
Livingston PSD and cannot establish robustness on L1 O4b strain. Native
16,384 Hz processing with the requested Q-transform band 20..2048 Hz is
approved in principle; the production configuration remains 4096 Hz.

This document prepares the protocol, not an executable scientific contract.
No numerical grid, estimator, acceptance margin or production promotion is
implicitly approved. Stage A has not run. Stage B, O4b execution and any
new strain acquisition remain separately gated. Automation stays paused;
historical calibration and its author-interrupted verifier remain unchanged.

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
| Noise-relative dose | Pending: prefer integrated line power divided by noise power in the same declared band; amplitude/PSD alone is dimensionally ambiguous |
| Stage A spectral and image observables | Pending: exact estimator, bands, image metric and two-tone resolution criterion |
| Stage A grid and reproducibility | Pending: doses, frequency and phase conventions, spacings, independent realizations, seed policy and uncertainty reporting |
| Native 16k configuration | Pending executable isolated contract: preserve scientific primitives, no hidden 4k resampling, explicit synthesis domain and runtime freeze |
| Stage B primary endpoint | Pending choice: calibrated flag-rate change versus a specified percentile endpoint |
| Stage B acceptance and power | Pending bilateral margin, block scheme, tail support, power target and multiplicity across epochs |
| Stage B real inputs and anchoring | Pending disjoint populations, reference CW state, amplitude history and step-zero spectral agreement criterion |

Approve these definitions before creating the versioned executable contract,
then test the isolated implementation and freeze it before any run. Stage A
is descriptive qualification, not an O4b readiness or CW immunity certificate.

## Preparation verification

Documentation-only scope; numerical regression suites are not rerun or
claimed as new evidence. The availability check above passed with observed
OS exit 0. Nine required boundary markers and five local references passed
the documentation check. The staged diff contains only five documentation
files and `git diff --cached --check` passed, with observed OS exit 0.
These checks validate preparation scope, not the eventual numerical method.

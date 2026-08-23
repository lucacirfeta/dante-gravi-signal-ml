# DANTE-Light L4 v4 development result (2026-08-23)

## Decision

**`V4_NOT_READY`**. The frozen six-feature phase-aware primary does not meet
the predeclared 50% effective background-call reduction requirement. The
one-shot confirmation cohort remains sealed, no unlock receipt was created,
O4b was not accessed, and routing remains disabled.

This is a valid negative development result. It must not be converted into a
PASS by selecting a feature subset, weakening a protected-stratum gate, or
retuning on the same development cohort.

## Frozen scope and provenance

- Protocol: `dante-light-l4-prefilter-v4-phase-primary`
- Protocol digest: `b9e43801f091413a13b45cda40f39c0e3b070385bb3ec12d2cca2137167fef61`
- Protocol file SHA256: `9e6b89146e63cd7717e1fcd56c6bddb6f5337ca739863f5b3bfae9e5a8ae7f42`
- Identity-manifest digest: `9b0cafdb49d954c0399a4f45a47b785b1f59e10b6e4ce390c40c6a9ce1478363`
- Confirmation-seal digest: `430074c23d0952cf0b8506f05f7d72d0070a16b5db01bb81205eb803d6a6755e`
- Code freeze commit: `2d3538cfa38d1b49d49235ed681dc66e8a4ad160`
- Development-result digest: `b6c0e75d61ed3d84475d511ff915057de3c4ff2a08e3c1010a1f208b43c65058`
- Frozen audit seed: `15621696242067692811`; scikit-learn uint32
  adapter seed: `25156875` (`uint64 modulo 2^32`)

The complete development evidence contains 1,010 windows: 600 O4a
background, 50 O4a DANTE-ROBUST candidates, 150 O3b Gravity Spy controls,
and 210 O4a software injections. All four ledgers contain development rows
only and record empty confirmation/O4b access lists.

## Predeclared endpoint

The operating threshold is selected separately for H1 and L1. Every protected
role/morphology stratum must simultaneously satisfy point retention >= 0.90,
Wilson lower bound >= 0.80, and the frozen minimum sample size. Effective
background-call reduction, including the 5% deterministic audit stream, must
then be >= 0.50.

The primary met the protected-stratum constraints only at thresholds that call
almost all background windows:

| Detector | Threshold | Background called | Background n | Effective reduction |
|---|---:|---:|---:|---:|
| H1 | 0.138398795701520 | 300 | 300 | 0.0000 |
| L1 | 0.228727875101887 | 296 | 300 | 0.0133 |
| Combined | -- | 596 | 600 | **0.0067** |

The combined reduction is therefore 0.67%, far below the frozen 50% product
requirement. At these low thresholds, ROBUST retention was 24/25 (0.96) in
each detector, while every known-glitch and injection stratum retained all its
development examples. This does not rescue the design: the primary purpose of
the prefilter is to avoid exact-path calls while retaining protected inputs,
and the avoided-call endpoint failed by a wide margin.

## Informative, non-gating discrimination

The detector/GPS-block bootstrap AUC is diagnostic only. Overall OOF AUC was
0.634 (95% block-bootstrap interval 0.595--0.670). The per-stratum results show
strong heterogeneity:

| Protected stratum | H1 AUC (95% CI) | L1 AUC (95% CI) |
|---|---:|---:|
| BBH 30+30 | 0.709 (0.598--0.815) | 0.677 (0.569--0.781) |
| BBH 10+10 | 0.580 (0.468--0.689) | 0.630 (0.524--0.732) |
| NSBH 10+1.4 | 0.530 (0.420--0.636) | 0.507 (0.417--0.607) |
| Blip | 0.520 (0.404--0.652) | 0.489 (0.375--0.604) |
| Koi Fish | 0.821 (0.729--0.901) | 0.859 (0.782--0.927) |
| Scattered Light | 0.659 (0.518--0.795) | 0.644 (0.524--0.771) |
| DANTE-ROBUST | 0.580 (0.422--0.734) | 0.767 (0.622--0.894) |

Thus the representation contains useful morphology-specific information,
especially for Koi Fish, but it is not a uniformly safe routing statistic.
The near-random NSBH AUC in both detectors is evidence against this particular
six-summary representation as the solution to the previously observed NSBH
weakness; it is not evidence that phase information in general is useless.

## Synthetic-to-real translation failure

The label-blind feasibility probe established construct validity only on an
ideal monocomponent signal. Its ordered quadratic chirp had frequency--time
Spearman 0.839 and cubic circular-phase residual 0.0058; 64 phase-scrambled
controls had Spearman p95 0.208 and median residual 0.926. Those clean
synthetic contrasts did not survive contact with real detector strain. Across
the closed development cohort, median frequency--time Spearman was 0.0109 for
background and -0.0177 for protected windows, while median cubic residual was
0.9241 and 0.9189, respectively. Under these summaries, both real populations
therefore look much closer to the phase-scrambled controls than to the ideal
ordered chirp.

The post-hoc univariate diagnostics reinforce this interpretation. The frozen
`phase_valid_frame_fraction` is effectively constant (median 0.5 and IQR 0 in
both populations; orientation-free AUC 0.501), and the positive-step fraction
is also near chance (AUC 0.508). The strongest individual summary is the
inspiral-coordinate residual (orientation-free AUC 0.638), but it is not a
uniform morphology discriminator and is correlated with measured injection
SNR for BBH 10+10 (Spearman -0.466) and BBH 30+30 (-0.622). SNR was not used
for fitting or gating; these correlations are diagnostic evidence that part of
the response may track signal strength rather than a robust phase morphology.

A plausible mechanism is that analytic instantaneous phase is well behaved
for the ideal narrow, monocomponent chirp used in feasibility, but becomes
unstable or diluted when computed globally over a whitened 20--1024 Hz,
32-second window containing broadband, non-Gaussian and non-stationary detector
noise or multiple transient components. This is a post-hoc explanation, not a
demonstrated causal mechanism. The result falsifies these six global summaries,
not phase-aware representations in general.

The complete recomputable diagnostic is
`artifacts/dante_light/prefilter_l4_v4_development/diagnostics_v4.json`. It is
explicitly ineligible for PASS/FAIL, does not update the frozen screen, and
records empty confirmation and O4b access lists.

## Descriptive cross-protocol comparison

| Development representation | Windows | Overall OOF AUC | Constrained effective reduction |
|---|---:|---:|---:|
| v2 spectral evolution baseline | 962 | 0.8052 | 8.70% |
| v3 signed + ridge primary | 962 | 0.7179 | 3.08% |
| v4 analytic-phase primary | 1,010 | 0.6341 | 0.67% |

The 0.805 value reproduced in the v3 dossier belongs to the frozen v2 spectral
control, not to the v3 A+B primary. V2 and v3 share the same 962-window cohort,
so that pair is a direct representation comparison. V4 deliberately uses a
fresh cohort with 600 rather than 552 background windows; its differences are
therefore descriptive and cannot be attributed only to representation.
Nevertheless, v4 is not merely below the 50% product target: on its own frozen
real-strain development test it provides less aggregate ranking and almost no
safe call reduction, despite the strong ideal-synthetic phase response.

## NSBH scientific boundary

For comparability with v1--v3, development injections use the legacy
`IMRPhenomD` generator. The NSBH 10+1.4 benchmark is therefore a point-particle
control with no neutron-star tidal effects. This result neither establishes
nor rejects sensitivity to physically realistic tidal, precessing, or
higher-mode NSBH waveforms. Measured injection SNR was diagnostic only and did
not enter selection, training labels, thresholds, or gates.

## Runtime observation

Across the 1,010 development windows, phase-feature extraction alone had mean
15.87 ms, median 15.83 ms, p95 25.65 ms, and maximum 41.86 ms. These timings
exclude data access and whitening and were collected during concurrent cohort
construction. They are observational provenance, not a controlled paired
benchmark and not part of the PASS/FAIL gate.

## Reproduction

From the repository root:

```text
python scripts/verify_dante_light_prefilter_v4_freeze.py
python scripts/verify_dante_light_prefilter_v4_development.py \
  --artifact-dir artifacts/dante_light/prefilter_l4_v4_development
python scripts/analyze_dante_light_prefilter_v4_diagnostics.py --verify
```

The exact recomputation verifier passed on both the Windows environment that
produced the result and the independent WSL LALSuite environment. Serialized
floating-point outputs are canonicalized to 15 significant digits only after
the unrounded gate evaluation, eliminating platform-level one-ULP drift without
changing the decision.

## Closed and open checkpoints

- Development v4 is closed as `V4_NOT_READY`.
- Confirmation remains sealed and must not be opened for this design.
- O4b remains untouched.
- Any new representation is a new protocol/version with a fresh development
  cohort; it cannot be presented as a retune of v4 on these same outcomes.
- A v5 feasibility study should not assume that another global analytic-phase
  summary repairs v4. It must first demonstrate real-strain construct validity
  or pursue a representation that does not depend on global phase estimation;
  any development and confirmation cohorts must remain new and independently
  sealed.

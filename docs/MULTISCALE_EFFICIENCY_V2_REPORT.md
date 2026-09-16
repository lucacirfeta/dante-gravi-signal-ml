# Multiscale efficiency v2: verified analysis report

Run key: `27199d657f5a8e0ba5e6dd50754a51c3eb0b22817393a754e4569b3be470fbdb`

## Scope

This report measures simulation-specific recovery in the frozen paired O4a injection study. The primary endpoint is the detector-native 32 s decision. Short-scale responses are conditional diagnostics only; no scale OR fusion, astrophysical population efficiency, rate upper limit, global significance, or O3 transfer claim is made.

## Conditional response pattern

Of 276 conditional cells with at least one primary recovery, 250 (90.6%) lie at an observed endpoint: 140 have no observed short-scale response and 110 respond for every eligible trial. Only 26 cells are intermediate. In this finite, paired simulation grid, the conditional multiscale response is therefore predominantly endpoint-like (always present or never present) rather than gradual. This is an empirical description, not evidence that the underlying response probability is exactly zero or one, and not proof of a particular mechanism.

Endpoint cells retain their observed point value but have a null confidence interval. Interior conditional cells receive a 95% raw-source-block bootstrap interval only when all 2,000 shared bootstrap replicates retain a non-zero eligible denominator.

Status counts by short scale:

| Scale (s) | Undefined (no primary) | Observed 0 | Observed 1 | Interior CI | Interior CI null |
|---:|---:|---:|---:|---:|---:|
| 0.5 | 27 | 37 | 23 | 6 | 3 |
| 1 | 27 | 34 | 25 | 7 | 3 |
| 2 | 27 | 33 | 32 | 3 | 1 |
| 4 | 27 | 36 | 30 | 2 | 1 |

## Primary end-to-end recovery

Each entry is recovered/total for SNR 8, 12, 16, 24, 32, and 48. Full point estimates, confidence intervals, and boundary states are in `primary_efficiency.jsonl`.

| Detector | Population role | Morphology | 8 | 12 | 16 | 24 | 32 | 48 |
|:--|:--|:--|--:|--:|--:|--:|--:|--:|
| H1 | primary_injection | Blip | 1/100 | 1/100 | 1/100 | 1/100 | 2/100 | 6/100 |
| H1 | primary_injection | NarrowChirp | 1/100 | 1/100 | 1/100 | 1/100 | 29/100 | 97/100 |
| H1 | primary_injection | NoiseBlob | 1/100 | 1/100 | 1/100 | 1/100 | 1/100 | 1/100 |
| H1 | primary_injection | ScatteredLight | 1/100 | 1/100 | 2/100 | 10/100 | 38/100 | 76/100 |
| H1 | primary_injection | Whistle | 1/100 | 1/100 | 1/100 | 1/100 | 1/100 | 1/100 |
| H1 | secondary_dsd_control | HarmonicComb | 0/40 | 0/40 | 0/40 | 0/40 | 12/40 | 33/40 |
| H1 | secondary_dsd_control | KoiFish | 0/40 | 0/40 | 0/40 | 2/40 | 2/40 | 6/40 |
| H1 | secondary_dsd_control | WallOfLines | 0/40 | 0/40 | 0/40 | 0/40 | 0/40 | 0/40 |
| L1 | primary_injection | Blip | 2/100 | 2/100 | 2/100 | 2/100 | 2/100 | 6/100 |
| L1 | primary_injection | NarrowChirp | 2/100 | 2/100 | 2/100 | 3/100 | 33/100 | 99/100 |
| L1 | primary_injection | NoiseBlob | 2/100 | 2/100 | 2/100 | 2/100 | 2/100 | 2/100 |
| L1 | primary_injection | ScatteredLight | 2/100 | 2/100 | 2/100 | 6/100 | 22/100 | 38/100 |
| L1 | primary_injection | Whistle | 2/100 | 2/100 | 2/100 | 2/100 | 2/100 | 4/100 |
| L1 | secondary_dsd_control | HarmonicComb | 0/40 | 0/40 | 0/40 | 0/40 | 7/40 | 37/40 |
| L1 | secondary_dsd_control | KoiFish | 0/40 | 0/40 | 0/40 | 0/40 | 2/40 | 5/40 |
| L1 | secondary_dsd_control | WallOfLines | 0/40 | 0/40 | 0/40 | 0/40 | 0/40 | 0/40 |

## WallOfLines limitation

- H1 at SNR 32: primary recovery 0/40; maximum primary score 0.101625 versus threshold 0.212159; non-gating short-scale threshold exceedances 0.5s=0/40, 1s=1/40, 2s=0/40, 4s=0/40.
- L1 at SNR 32: primary recovery 0/40; maximum primary score 0.116335 versus threshold 0.220344; non-gating short-scale threshold exceedances 0.5s=2/40, 1s=1/40, 2s=2/40, 4s=1/40.
- H1 at SNR 48: primary recovery 0/40; maximum primary score 0.122647 versus threshold 0.212159; non-gating short-scale threshold exceedances 0.5s=0/40, 1s=1/40, 2s=0/40, 4s=0/40.
- L1 at SNR 48: primary recovery 0/40; maximum primary score 0.180129 versus threshold 0.220344; non-gating short-scale threshold exceedances 0.5s=2/40, 1s=1/40, 2s=1/40, 4s=1/40.

`WallOfLines` is thus characterized as systematically unrecovered by the primary endpoint at the tested high SNR values. A plausible hypothesis is that the Q-transform/DINO/VQ representation, designed around localized transient structure, can treat persistent or quasi-stationary spectral lines as background-like. The experiment does not establish that mechanism as the cause.

## Uncertainty and audit boundary

All intervals use complete raw-source-block resampling, separately by detector and population role, with shared draws across morphology, SNR, and scale. Detectors and morphology tiers are never pooled. A missing interval is an explicit fail-closed boundary state, not a numerical zero-width confidence claim.

# DANTE-Light L4 prefilter v3: development result

Date: 2026-08-22
Status: **NOT_READY; do not open the reserved confirmation cohort or O4b**

## Frozen question and anti-circularity boundary

The v3 experiment tested the predeclared `signed_plus_ridge` feature set after
the v2 development diagnostic had exposed weak NSBH separation. Consequently,
all A/B results on the same O4a development partition are explicitly
hypothesis-generating rather than confirmatory. The already frozen and disjoint
evaluation partition was reserved as the first positive-control confirmation,
and O4b remained sealed for the later operational endpoint. Neither partition
was opened because the predeclared development criterion failed.

The feature alternatives and falsification criteria were frozen before v3
feature extraction in
`config/dante_light_prefilter_protocol_v3.json` (protocol digest
`8c40fa2d7054afdf434a848b1964d325ce38ce941819d4748879490f1925c748`).
The development cohort contains 962 windows: 552 background, 50 robust
candidates, 150 known glitches, and 210 CBC injections. Cross-validation uses
detector/GPS 4096-s groups. AUC intervals use the predeclared detector/GPS
block bootstrap with 2,000 resamples and are informational only.

## Result

| Feature set | Role | OOF constrained reduction | Overall AUC (95% block-bootstrap CI) | NSBH AUC H1 / L1 |
|---|---|---:|---:|---:|
| signed ordering (A) | ablation | 0.36% | 0.513 (0.478--0.550) | 0.477 / 0.434 |
| ridge consistency (B) | ablation | 1.63% | 0.711 (0.675--0.746) | 0.557 / 0.474 |
| signed + ridge (A+B) | **predeclared primary** | **3.08%** | 0.718 (0.683--0.752) | **0.548 / 0.476** |
| frozen v2 spectral baseline | ablation | 8.70% | 0.805 (0.775--0.834) | 0.533 / 0.556 |

The product requirement is at least 50% fewer exact DINO calls while retaining
every protected detector/morphology stratum at its frozen rate and Wilson lower
bound. A+B misses this requirement by a large margin and performs worse than
the frozen spectral baseline under the constrained reduction metric. No model
or threshold was promoted, and routing remains disabled.

The distinction between the two scientific questions is now concrete:

- B and A+B contain aggregate discriminative signal, driven mainly by several
  known-glitch and robust-candidate strata.
- They do **not** show useful NSBH-specific separation on this development
  cohort. Both NSBH AUC confidence intervals include 0.5, and the weak NSBH
  stratum forces a low retention-compatible threshold that removes almost no
  background.

Thus the result is not merely an underpowered constrained gate hiding a strong
NSBH representation. For the tested STFT summaries, the NSBH morphology itself
remains close to chance. This falsifies A+B as the proposed inexpensive v3
solution; it does not prove that no cheap representation can work.

## Code and numerical cross-checks

The exact verifier recomputed the complete screen and matched artifact digest
`de2509b74ec230328f2ca44f5a2c7e2fdb47a75761efdcbcbb702ae8a07fc1f1`.
The v3 spectral control reproduces the v2 constrained reduction, overall AUC,
and all 14 protected-stratum AUC values exactly. This is a strong end-to-end
check of cohort selection, whitening/cropping, folds, weighting, and scoring.

For 752 real-strain development rows the six shared spectral features match v2
bit-for-bit. The 210 injections were independently reconstructed in the pinned
WSL LALSuite environment: raw-strain hashes and published SNR checks pass, while
the generated waveform byte hashes differ from the earlier environment and the
largest shared-feature difference is only `1.44e-12`. Despite that numerical
round-off difference, the complete v2 spectral metrics listed above reproduce
exactly. The Windows and WSL environments are recorded beside the external
ledgers.

The compact result and hashes are stored in
`artifacts/dante_light/prefilter_l4_v3/screening_summary_v3.json`; the large
ledgers and full screening artifact remain under
`E:/dante_cache/dante_light_prefilter_l4_v3_development`.

## Decision

Do not run the reserved positive-control confirmation and do not inspect O4b
for this design. Any further experiment is a new design cycle, not a rescue of
the frozen v3 gate. A scientifically defensible next candidate should be
specified and frozen before evaluating it; plausible directions include a
genuinely phase-aware low-cost representation or distillation from exact DINO,
with explicit protection against non-CBC morphologies and no change to the
current operational path until independent confirmation succeeds.

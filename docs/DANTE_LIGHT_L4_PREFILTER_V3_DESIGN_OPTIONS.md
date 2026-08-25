# DANTE-Light L4 prefilter v3: design options

Date: 2026-08-22
Status: design only; no v3 protocol is frozen and no routing is enabled

## Decision boundary

The frozen v2 screen remains `NOT_READY` and immutable. This document does not
change its feature schema, cohorts, thresholds, retention gates, model,
evaluation epoch, or result. It defines candidate experiments for a new v3
protocol; choosing one changes what is measured and therefore requires an
explicit scientific decision before implementation.

The diagnostic evidence separates two questions that should not be conflated:

- The v2 representations contain aggregate ranking information: overall OOF
  ROC-AUC is 0.8052 for `spectral_evolution` and 0.8027 for `all`.
- They do not demonstrate useful NSBH ranking under the frozen model and
  cohort. For `NSBH_10_1.4`, `spectral_evolution` gives OOF ROC-AUC 0.5327
  (H1) and 0.5564 (L1), while `all` gives 0.5533 and 0.5860. Each detector has
  35 positive NSBH development examples, against 274 H1 or 278 L1 background
  examples.

These post-hoc per-stratum AUCs have no pre-registered uncertainty interval or
confirmatory test. They do not prove that NSBH morphology has no exploitable
signal. They show that v2 does not expose enough useful separation, and that
increasing the cohort can improve precision but cannot be assumed to improve
the point separation.

## Relevant architecture map

```text
canonical padded strain preparation
  -> whiten full context, then crop the clean subwindow
  -> extract_prefilter_v2_features(whitened)
       -> temporal energy summaries
       -> one STFT shared by TF clusters and spectral evolution
       -> dyadic wavelet summaries
  -> detector-specific standardized logistic model
  -> detector-specific threshold constrained independently by every
     role/detector/morphology stratum
  -> exact-path call or deterministic 5% audit
```

The implementation points that a v3 design would extend are:

- `src/dante_light/prefilter_v2.py`: feature schema and extraction. The current
  STFT is already computed once. Its spectral centroid slope is stored as an
  absolute value, so upward and downward evolution are deliberately collapsed.
- `src/dante_light/prefilter_v2_screening.py`: detector-specific grouped OOF
  fitting, morphology-stratified retention, and operating-point selection.
- `src/dante_light/prefilter_v2_protocol.py`: fail-closed protocol loading and
  digest binding.
- `config/dante_light_prefilter_protocol_v2.json`: frozen O4a/O3b development
  boundary and unopened O4b evaluation boundary.

No candidate below requires a change to canonical whitening. The implementation
must continue to whiten padded context before cropping.

## Runtime stack and constraints

The relevant installed stack is NumPy, SciPy signal processing, and
scikit-learn. PyTorch is available but is not required by the engineered
candidate families. A valid Light prefilter must be materially cheaper than an
exact DANTE call on the same hardware, run on CPU, expose deterministic
provenance, and fail open to the exact path when its own contract cannot be
verified.

## Candidate A: signed spectrotemporal ordering

**Hypothesis.** The strongest v2 family retains spectral variation but discards
the direction and ordering of that variation. CBC inspirals have increasing
frequency structure, so signed ordering may separate NSBH injections from
stationary or non-chirping background more effectively than absolute centroid
range/slope.

Candidate observables, computed from the existing STFT, are signed centroid
slope, rank correlation between time and centroid, low/mid/high-band energy
arrival quantiles, high-minus-low arrival delay, and the fraction of adjacent
frames with increasing energy-weighted frequency.

- Incremental cost: low; reuse the existing STFT.
- Main risk: PSD lines and weak signals can make centroid estimates unstable.
- Leakage control: band edges and summaries must be frozen from O4a only; no
  O4b outcome inspection.
- Falsification: no repeatable improvement in detector-specific NSBH OOF AUC
  and no improvement in the constrained development reduction.

## Candidate B: coarse ridge or chirplet consistency

**Hypothesis.** A few global moments are insufficient when the discriminating
information is a connected rising track. Chirplet analyses explicitly model
frequency evolution and have historically reduced mismatch for lower-mass CBC
signals compared with stationary sine-Gaussian atoms.

Candidate observables, still using the existing coarse STFT, are ridge
continuity, positive-slope fraction, energy captured by the best monotone
ridge, residual from a robust linear ridge fit, and residual from a coarse
inspiral-like transform such as linearity of `f^(-8/3)` versus time. This is a
small descriptive bank, not a matched-filter search and not an astrophysical
detection statistic.

- Incremental cost: low to medium; one dynamic-programming or robust-fit pass
  over the existing time-frequency grid.
- Main risk: an overly specific chirp prior can retain NSBH while rejecting
  protected non-CBC morphologies, or can reproduce a more expensive search.
- Leakage control: candidate bank and ridge penalties frozen before grouped
  OOF scoring; every protected morphology keeps its own retention gate.
- Falsification: NSBH separation improves but another protected stratum loses
  retention, or measured feature cost removes the intended compute saving.

## Candidate C: multiscale band-envelope dynamics

**Hypothesis.** The current dyadic family compresses each scale to sparsity and
entropy, losing when energy occurs and how it moves between scales. A small
fixed filter bank with envelope sequencing could preserve that information
without learning a representation.

Candidate observables are per-band envelope peak time, duration above a robust
within-window baseline, adjacent-band peak delay, cross-band order violations,
and low-to-high cumulative-energy transport. Frequencies and scales must be
defined in a new frozen config rather than hardcoded in the extractor.

- Incremental cost: medium; several fixed filters plus envelope summaries.
- Main risk: overlap with Candidate A without enough independent information.
- Leakage control: detector-specific scaling remains inside grouped folds;
  filter definitions are fixed before scoring.
- Falsification: an ablation shows no gain beyond Candidate A at comparable
  cost, or gains are confined to one detector.

## Candidate D: compact learned student

**Hypothesis.** If fixed summaries continue to erase weak NSBH morphology, a
small 1-D convolutional student may learn useful local ordering directly from
the canonical whitened subwindow while remaining cheaper than exact DANTE.

Two targets must be kept conceptually separate: protected-role classification
and distillation of the exact-path escalation decision. The latter can improve
routing fidelity but is circular evidence for physical signal recognition; it
cannot be reported as independent astrophysical discrimination.

- Incremental cost: highest design and validation burden; inference cost can
  still be low but must be benchmarked on the release hardware.
- Main risks: temporal leakage, detector/run shortcut learning, calibration
  drift, stochastic training, and loss of interpretability.
- Leakage control: detector-and-4096-s grouped splits, preprocessing fitted
  only inside folds, fixed seeds, architecture and training protocol frozen,
  and untouched O4b outcomes.
- Falsification: unstable replicate performance, detector shortcut evidence,
  failure of any protected-stratum retention gate, or insufficient measured
  end-to-end compute reduction.

## Comparison and recommended order

| Candidate | Reuses v2 STFT | Expected NSBH relevance | Added complexity | First role |
|---|---:|---:|---:|---|
| A: signed ordering | yes | medium-high | low | first diagnostic |
| B: ridge/chirplet consistency | yes | high | low-medium | first diagnostic |
| C: band-envelope dynamics | partly | medium | medium | ablation if A/B fail |
| D: compact learned student | no | potentially high | high | fallback protocol |

The lowest-risk next experiment is a **joint A/B diagnostic screen**, with A
and B also evaluated separately so their contributions are identifiable. This
is a recommendation, not authorization to freeze the protocol. Candidate C is
useful only if it adds information beyond A/B. Candidate D should be considered
only after engineered, morphology-sensitive features fail, because its
validation burden is substantially larger.

A true morphology-aware cascade must not use the known injection label at
runtime. It would require a separately validated first-stage routing score and
must preserve the same per-morphology retention guarantees. It is therefore
not the first v3 implementation step.

## Required v3 experiment contract

Before code that can produce a promotable result, freeze a new versioned
protocol containing:

1. exact candidate feature names, formulas, and config-derived parameters;
2. unchanged or explicitly revised development/evaluation populations;
3. grouped split and detector-specific preprocessing rules;
4. primary selection metric and protected per-morphology retention gates;
5. informational metrics, including per-stratum AUC with detector/GPS-block
   bootstrap uncertainty (never i.i.d. resampling);
6. an ablation matrix for A, B, A+B, and the v2 spectral baseline, subject to
   the anti-circularity clause below;
7. a measured CPU cost and end-to-end call-reduction contract;
8. untouched O4b outcome rules and a one-shot evaluation decision;
9. provenance hashes, deterministic seeds, and fail-closed verification.

### Anti-circularity clause for the A/B ablation

A and B were proposed after inspecting the post-hoc v2 development diagnostic,
including the weak NSBH separation. Their ablation on those same development
rows is therefore hypothesis-generating and **exploratory only**: it cannot
confirm NSBH discrimination or authorize a PASS.

The first confirmatory NSBH endpoint must instead use the previously frozen,
unused evaluation partition in `config/dante_light_prefilter_splits_v2.json`:
90 NSBH injection windows per detector (18 at each of the five frozen
distances), disjoint in window identity from the 35 development windows per
detector. The v2 screening and diagnostic implementations consume only rows
whose partition is `development`; the confirmatory identities must be bound by
their existing split hash and checked again for zero overlap before use.

The A/B formulas, combination rule, fitted-model procedure, calibration rule,
and all decision criteria must be frozen before extracting or scoring A/B on
that evaluation partition. Its confirmatory endpoint is protected-stratum
retention, not background reduction and not operational PASS. End-to-end
compute reduction and operational promotion remain reserved for the one-shot,
outcome-blind O4b shadow evaluation. If any A/B value from the reserved
partition is inspected before the v3 freeze, that partition is invalidated and
a newly seeded, disjoint injection cohort is required.

The 50% reduction target is a product/scientific requirement, not a quantity
derived from the v2 data. It must either remain unchanged with an explicit
justification or be revised as a new scientific decision; it must not be tuned
after seeing v3 results.

## Primary scientific basis

- Mohapatra et al., *Performance of a Chirplet-based analysis for gravitational
  waves from binary black hole mergers*, arXiv:1111.3621,
  https://arxiv.org/abs/1111.3621.
- Henshaw et al., *Visualization of frequency structures in gravitational wave
  signals*, arXiv:2402.16533, https://arxiv.org/abs/2402.16533.
- Mukund et al., *Transient Classification in LIGO data using Difference
  Boosting Neural Network*, arXiv:1609.07259,
  https://arxiv.org/abs/1609.07259.
- Qiu et al., *Deep Learning Detection and Classification of Gravitational
  Waves from Neutron Star-Black Hole Mergers*, arXiv:2210.15888,
  https://arxiv.org/abs/2210.15888.
- Skliris et al., *Real-Time Detection of Unmodelled Gravitational-Wave
  Transients Using Convolutional Neural Networks*, arXiv:2009.14611,
  https://arxiv.org/abs/2009.14611.

These works motivate the candidate inductive biases. They do not establish that
any candidate will pass DANTE-Light's frozen retention and compute gates; that
claim requires the experiment above.

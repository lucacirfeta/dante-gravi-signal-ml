# Multiscale efficiency v2: causal stage trace

**Status:** `PASS_MULTISCALE_EFFICIENCY_V2_CAUSAL_DIAGNOSTIC`

**Run key:** `b16e8d81f9f141566c56b7ceeceb1c8f1c6a5ad8b7948cfaa3426cbd61b8eba2`

**Contract:** `a4aeb9cdfc9a418786b555c21329c79ee0d85a3167b67edfa137d8d8aaba0fc9`

## Question and boundary

The frozen efficiency study showed weak or absent primary recovery for several
morphologies.  This diagnostic asks where the injected and paired-clean paths
stop producing an anomaly response along the existing production chain:

`whitened strain -> resized Q-transform -> per-image normalization/RGB -> DINOv2 patch tokens -> VQ anomaly -> top-k score -> detector p99`.

It does **not** change the production index, thresholds, populations, scoring,
or scale-fusion policy.  It does not assign a causal mechanism automatically.
The result is a stage-localization diagnostic, not a new efficiency estimate or
an O3 transfer claim.

## Frozen design

- Outcome-blind selection: the lowest 20 frozen `role_index` values for each
  detector and population role.
- Primary morphologies: `Blip`, `NarrowChirp`, `Whistle`, `NoiseBlob`.
- Secondary control: `WallOfLines`.
- SNR grid: 8, 12, 16, 24, 32, 48.
- Cardinality: 80 paired-clean controls and 1,200 injected trials in 60
  detector-morphology-SNR cells, 20 independent raw source blocks per cell.
- Uncertainty: paired raw-source-block bootstrap, 2,000 resamples, 95% CI,
  with shared draws across metrics within each cell.  Detectors and
  morphologies are never pooled.

The diagnostic exactly replayed all 1,200 frozen primary images, scores, and
decisions.  The maximum absolute score delta was `1.1920928955078125e-07`,
below the frozen tolerance `2e-07`.

## Stage trace at SNR 48

The table reports cell means. `wRMS` is the RMS of the injected-minus-clean
whitened series divided by clean RMS; `Q rel-L2` is the relative L2 change in
the resized Q-transform before per-image normalization; `token d` is the mean
same-position DINOv2 patch cosine distance; `VQ changed` is the fraction of
patches changing nearest centroid; `delta score` is injected minus paired-clean
top-68 score; `margin` is injected score minus the frozen detector p99.

| Detector | Morphology | recovered/20 | wRMS | Q rel-L2 | token d | VQ changed | delta score | margin |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| H1 | NarrowChirp | 18 | 0.1409 | 1.1521 | 0.2638 | 0.9040 | 0.1586 | +0.0331 |
| H1 | Blip | 1 | 0.1369 | 0.4837 | 0.1305 | 0.7624 | 0.0187 | -0.1068 |
| H1 | Whistle | 1 | 0.1431 | 0.6359 | 0.2185 | 0.8647 | 0.0681 | -0.0574 |
| H1 | NoiseBlob | 1 | 0.0348 | 0.0406 | 0.00110 | 0.1150 | 0.00019 | -0.1253 |
| H1 | WallOfLines | 0 | 0.1342 | 0.1566 | 0.0255 | 0.2382 | 0.00477 | -0.1403 |
| L1 | NarrowChirp | 19 | 0.1498 | 1.2044 | 0.2554 | 0.9507 | 0.1757 | +0.0266 |
| L1 | Blip | 2 | 0.1441 | 0.4589 | 0.1454 | 0.6814 | 0.0154 | -0.1336 |
| L1 | Whistle | 2 | 0.1502 | 0.5279 | 0.1616 | 0.8978 | 0.0801 | -0.0689 |
| L1 | NoiseBlob | 1 | 0.0332 | 0.0607 | 0.00491 | 0.1609 | 0.00111 | -0.1479 |
| L1 | WallOfLines | 0 | 0.1290 | 0.2132 | 0.0591 | 0.3389 | 0.00659 | -0.1460 |

These recovery counts describe only the frozen diagnostic subset.  The full
efficiency estimates remain those in `MULTISCALE_EFFICIENCY_V2_REPORT.md`.

## What the trace establishes

### Positive control: NarrowChirp

`NarrowChirp` propagates progressively through every measured stage.  At SNR
48, the Q-transform relative change is greater than one, more than 90% of VQ
assignments change on average, and the mean score margin is positive in both
detectors.  This shows that the replay and metric chain can expose a
morphology that becomes anomalous under the frozen representation.

### NoiseBlob: attenuation is already strong at the 32 s Q representation

The injected-minus-clean whitened response increases monotonically with target
SNR, so the injection is present after whitening.  Nevertheless, even at SNR
48 the mean pre-normalization Q relative change is only 0.041 (H1) and 0.061
(L1), followed by mean patch-token distances of 0.0011 and 0.0049 and score
changes consistent with nearly zero at this scale.  The earliest strong
attenuation visible in this trace is therefore at or before the 32 s
Q-transform representation; downstream stages preserve little separation to
amplify.  This localizes the behavior but does not by itself identify whether
window duration, time-frequency tiling, or another representation detail is
the mechanism.

### WallOfLines: attenuation is distributed across representation and VQ score

At SNR 48, `WallOfLines` has a whitened response comparable in scale to the
positive control, but much smaller Q and token changes.  The encoder is not
strictly invariant—the VQ assignment-change fraction reaches 0.238 (H1) and
0.339 (L1)—yet the mean score increase remains only 0.0048 and 0.0066, leaving
large negative threshold margins.  Thus the data reject the narrow statement
that the injection disappears before whitening or that the encoder sees no
change at all.  The observed attenuation spans the 32 s time-frequency
representation and the mapping of changed tokens to the frozen background VQ
score.  A physical or architectural cause is not proven.

### Whistle: visible representation response, insufficient anomaly score

`Whistle` shows substantial Q, token, and assignment changes by SNR 48.  The
score also rises strongly (`+0.068` H1, `+0.080` L1), but not enough to close
the paired-clean-to-p99 gap for most selected backgrounds.  Its weak recovery
is therefore not explained by absence from the Q image or DINO representation;
the limiting part of the frozen chain lies downstream in how the altered
tokens map to VQ anomaly score and the detector-specific threshold.

### Blip: representation changes are compressed by the VQ/top-k endpoint

`Blip` changes the Q image and many patch assignments, but its mean score gain
at SNR 48 is only `0.019` (H1) and `0.015` (L1).  The trace therefore places
the dominant observed compression after token formation, in the frozen
nearest-centroid/top-k endpoint.  This does not imply that the VQ index is
incorrect; it says that the tested Blip perturbations often remain close to
background structure according to that endpoint.

## Scientific interpretation

The flat or weak efficiency curves do not share one universal failure stage:

- `NoiseBlob` is strongly attenuated by the 32 s time-frequency
  representation before DINO/VQ scoring.
- `Blip` and `Whistle` remain visible to the representation, but their token
  changes translate into insufficient anomaly-score margin.
- `WallOfLines` shows both early representation attenuation and further weak
  conversion into VQ/top-k score.
- `NarrowChirp` is a working positive control for the whole chain.

These are empirical stage-localization statements for the frozen O4a
simulation design. They do not establish a unique mechanism, justify an
automatic production redesign, or support an astrophysical sensitivity claim.
A redesign must be posed as a new, separately frozen experiment and compared
on the same paired blocks without changing the current result.

## Evidence

- External summary SHA-256:
  `d451e59125c313872af6387adf947ab28a90fd024f2c89d9a0dc9c08d90d76fd`
- External artifact digest:
  `3a64d685d3240f9a0afd1581cca351af6f720578fab93394a2c9024deab0e57a`
- Trace rows: 1,200, SHA-256
  `b935ec96465915c0e2a73e77c1ca76dd14535956f6ad2619de12557199ffe053`
- Trace cells: 60, SHA-256
  `1ef239f652df5ec87db797f6eb342078d38f8c4dcc295646a967a320c26007b0`

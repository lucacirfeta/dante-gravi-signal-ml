# Multiscale efficiency v2: unconditional paired short-scale diagnostic

**Status:** `PASS_MULTISCALE_EFFICIENCY_V2_SCALE_DIAGNOSTIC`

**Run key:** `10acd141618494ce87d26df5eb203378d8c5b96404681759833732c7adc05d99`

**Contract:** `4ce74a1ea447f99eb157e55fb1c65a099ba92da8d73e07c5fff30273d422e63c`

## Question and boundary

The frozen 32 s primary endpoint was weak or flat for several injected
morphologies. This diagnostic asks whether the already-computed 0.5, 1, 2,
and 4 s scores respond to the same paired injections. It consumes the complete
frozen injection ledger and does not generate new injections.

Every scale is evaluated only against its own frozen detector-specific p99.
Raw scores are not compared across scales. No scale is OR-fused with the 32 s
primary endpoint, no best scale is selected, and no production decision,
threshold, index, or population is changed. The results are descriptive and
simulation-specific; they are not a multiple-testing-corrected detection rule
and do not establish transfer to O3.

## Frozen design

- Detectors: H1 and L1, analyzed separately.
- Primary morphologies: `Blip`, `NarrowChirp`, `Whistle`, and `NoiseBlob`.
- Secondary control: `WallOfLines`.
- Target SNR: 8, 12, 16, 24, 32, and 48.
- Diagnostic scales: 0.5, 1, 2, and 4 s.
- Population: all 5,280 eligible rows from the frozen paired ledger, producing
  240 detector-morphology-SNR-scale cells and 40 scale trajectories.
- Uncertainty: 2,000 paired raw-source-block bootstrap resamples at 95%, with
  shared draws across morphology, SNR, scale, and metric within each
  detector/population-role group. Detectors, morphologies, and scales are
  never pooled.
- Metrics within each scale: injected-minus-clean score change, injected and
  clean margin to that scale's p99, paired threshold-exceedance gain, and the
  within-block Spearman association between target SNR and paired score change.

The standalone verifier replayed the complete tables and report and reproduced
the evidence digest exactly.

## SNR 48 result

The table aggregates the eight detector-scale cells for each primary
morphology and the eight secondary-control cells for `WallOfLines`. A positive
CI cell has a 95% block-bootstrap interval for the mean paired score change
strictly above zero. These counts are descriptive summaries of the frozen
cells, not a post-hoc decision rule.

| Morphology | Injected p99 exceeds | Paired-clean p99 exceeds | Trials | Mean delta range | Positive-CI cells | Negative-CI cells |
|---|---:|---:|---:|---:|---:|---:|
| Blip | 800 | 6 | 800 | 0.1667 to 0.2367 | 8/8 | 0/8 |
| NarrowChirp | 800 | 6 | 800 | 0.2585 to 0.3255 | 8/8 | 0/8 |
| Whistle | 800 | 6 | 800 | 0.2432 to 0.2741 | 8/8 | 0/8 |
| NoiseBlob | 5 | 6 | 800 | -0.00279 to 0.00172 | 1/8 | 2/8 |
| WallOfLines | 6 | 6 | 320 | -0.00171 to 0.00213 | 0/8 | 0/8 |

The six paired-clean exceedances repeated within a morphology reflect the
scale-specific clean controls and are retained explicitly; they are not
subtracted from the population before analysis.

## Within-block SNR response

`Blip` and `NarrowChirp` have median within-block Spearman correlations of
approximately 1 at every tested short scale in both detectors. `Whistle` has a
median correlation of approximately 0.943 at every scale in both detectors.
At SNR 48, all three morphologies exceed the corresponding scale-specific p99
in every injected trial at every short scale.

`NoiseBlob` has no consistent positive SNR trajectory. Its detector-scale
median correlations range from -0.457 to 0.086, and seven of eight SNR 48
mean-delta intervals either include zero or lie below it. The 5 injected and 6
paired-clean p99 exceedances at SNR 48 provide no excess response.

`WallOfLines` also has no detector-consistent short-scale response. Seven of
eight trajectory intervals include zero; the L1 0.5 s trajectory is the lone
positive interval, but its SNR 48 mean-delta interval includes zero. Across all
eight detector-scale cells, injected and paired-clean exceedances are equal
(6 versus 6). This isolated trajectory is insufficient to infer recovery or
to select 0.5 s.

Empirical block-bootstrap intervals equal to `[1, 1]` occur where every frozen
source block has the same perfect rank ordering. They describe the resampled
finite population and must not be read as certainty about an underlying true
correlation.

## Relationship to the causal trace

The short-scale result refines, rather than replaces, the 32 s causal trace:

- `Blip` and `Whistle` are strongly visible to the existing short-scale
  endpoints. Their weak 32 s primary recovery is therefore scale-specific and
  is not evidence that the injected structures are absent from all existing
  representations.
- `NoiseBlob` remains effectively absent at every tested short scale, which is
  consistent with the earlier localization of strong attenuation at or before
  the Q-transform representation.
- `WallOfLines` remains indistinguishable from paired background at the tested
  short scales, consistent with attenuation distributed across the
  representation and VQ/top-k score.
- `NarrowChirp` remains the positive control and responds monotonically across
  the full chain.

## Consequence for the next experiment

The evidence supports testing a separately calibrated multiscale decision
design for `Blip` and `Whistle`; it does not justify activating one now. Such a
design requires a new frozen contract, held-out calibration, explicit control
of scale-selection multiplicity, and comparison on the same paired blocks.

The same change is not expected to repair `NoiseBlob` or `WallOfLines`.
Those morphologies require a representation-level experiment rather than a
different fusion of the current scale scores. O3 transfer remains deferred
until the intended production endpoint is selected and frozen.

## Evidence

- External summary SHA-256:
  `289629e2a86d02ad048866282e7e1cbdc958c51e08383c836f8c05cf98a7db54`
- External artifact digest:
  `36f301f87160e300c48e53198f6e1290ce0f2648e33d1dbf97a3392433eadde1`
- Scale cells: 240, SHA-256
  `5cfa1b573b1d9dc3b813c024b65f1c3043a3161f2ff3332ad4d4436ec4793978`
- Scale trajectories: 40, SHA-256
  `1430e9a9f5b9a98a4514f0a2a20ecab70ac9c52cb84fdea41c126722f430d21a`
- External generated report SHA-256:
  `dba741bd58d0f5f5e6e0943c4015040bb2865c63835d9d66d536934394d952dd`

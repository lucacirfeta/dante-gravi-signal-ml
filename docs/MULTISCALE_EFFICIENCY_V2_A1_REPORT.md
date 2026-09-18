# Multiscale efficiency v2 A1: confirmatory result and direction

## Decision

A1 is a genuine scientific advance within the frozen O4a simulation experiment, but it is not a universal replacement for the detector-native 32 s endpoint and is not ready for automatic production promotion.

The advance is supported by a frozen joint maximum null, an independent held-out raw-block cohort, 2,280 clean controls, 7,440 paired injections, detector-separated inference, raw-source-block bootstrap intervals, and multiplicity-adjusted confirmatory tests. The held-out result is `PASS_A1_CONFIRMATORY_EVIDENCE`.

## Confirmatory findings

The A1 false-positive rate does not show a significant excess over the frozen 1% null in either detector:

| Detector | A1 | 32 s baseline | Holm-adjusted p | Excess detected |
|:--|--:|--:|--:|:--|
| H1 | 11/1000 (1.1%) | 10/1000 (1.0%) | 0.833918 | no |
| L1 | 9/1000 (0.9%) | 14/1000 (1.4%) | 0.833918 | no |

All four preregistered detector-by-morphology hypotheses improve after Holm correction:

| Detector | Morphology | Paired curve gain | 95% block-bootstrap CI | Holm-adjusted p |
|:--|:--|--:|:--|--:|
| H1 | Blip | +0.6133 | [0.5933, 0.6350] | 0.001999 |
| L1 | Blip | +0.5983 | [0.5733, 0.6217] | 0.001999 |
| H1 | Whistle | +0.4250 | [0.4050, 0.4467] | 0.001999 |
| L1 | Whistle | +0.4083 | [0.3900, 0.4267] | 0.001999 |

These are large, repeatable, detector-consistent gains. They are not merely engineering progress: the held-out experiment establishes that short-scale endpoints recover transient morphologies that the 32 s representation largely misses while retaining the calibrated background rate.

## Descriptive morphology audit

The non-confirmatory morphologies were inspected descriptively without adding hypotheses or changing the frozen gate.

- `NarrowChirp` improves by +0.3600 in H1 and +0.3500 in L1 across the six equally weighted SNR cells.
- `ScatteredLight` improves by +0.2167 in H1 and +0.2800 in L1.
- `KoiFish` improves by +0.4708 in H1 and +0.5167 in L1.
- `NoiseBlob` remains essentially unseen: 0/600 A1 recoveries in H1 and the same six recurring background exceedances in L1 as the 32 s baseline.
- `WallOfLines` remains unseen by A1: 0/240 in each detector.
- `HarmonicComb` regresses: A1 recovers 6/240 in H1 and 0/240 in L1, versus 46/240 for the 32 s baseline in each detector. There are 45 H1 and 46 L1 baseline-only recoveries.

Endpoint attribution is coherent with duration: `Blip` and `Whistle` recoveries are driven mainly by 0.5 s and 1 s endpoints; `ScatteredLight` is driven mainly by 2 s and 4 s endpoints. The same audit shows why A1 is not a drop-in replacement: the multiplicity-controlled joint maximum does not preserve the long-window `HarmonicComb` sensitivity.

The `HarmonicComb` regression is now causally localized to the multiplicity penalty rather than removal of the native representation. The 32 s endpoint is still part of A1. In the 45 H1 baseline-only cases, the smallest endpoint tail probability ranges from 0.00380 to 0.00720, while the joint maximum requires 0.00260. In the 46 L1 baseline-only cases, the corresponding range is 0.00660 to 0.01500 against a joint requirement of 0.00300. Thus these events retain their native 32 s response but do not clear the stricter family-wise joint threshold.

## What was discovered

1. The earlier weak `Blip` and `Whistle` efficiency was substantially a scale mismatch, not a universal failure of the DANTE representation.
2. The useful scale is morphology-dependent and physically interpretable across both detectors.
3. Short scales do not solve every representation failure: `NoiseBlob` and `WallOfLines` remain blind spots.
4. A jointly calibrated multiscale maximum has a real tradeoff: it gains short transient sensitivity but can reject native 32 s responses through its stricter multiplicity correction.

The experiment therefore changed what is known about the system. It did not merely reproduce old results or add workflow machinery.

## Direction

Continue the research direction, but do not promote A1 to the production pipeline and do not transfer the result to O3 yet. The causal endpoint audit is complete: it identifies the frozen family-wise multiplicity penalty as the source of the `HarmonicComb` regression. Selecting a remedy is now a new scientific-design decision rather than a debugging task.

Any new fusion or gate designed to preserve native 32 s sensitivity while retaining A1 gains changes how the scientific decision is made. It requires an explicit, separately frozen choice before implementation and a new independent validation; it must not be selected by optimizing on this held-out cohort.

## Provenance

- Contract digest: `3efb58ae6c15590d74170cef619f88345d1e3edd55f7e3b0c149decb46d8cdb5`
- Joint-null run: `joint_null_50dfe6fa0751019105d0ab3f194cd5fb6b2b16667d7f516443769dce11bddd6c`
- Joint-null artifact: `58439373d5005794f3967b605acc1ca9dec9218432b205182429ae0b2478e66d`
- Held-out run: `heldout_795421d5a276b56fc64254e355a00f1c8edbc45e5469e5c560104beef5655f38`
- Held-out artifact: `3db030229c570d1f9c001c4cec7a0846f41a11ab6a8061760c6c1b9ecc1d6074`
- Versioned evidence: `artifacts/dante_light/multiscale_efficiency_v2_a1/analysis_summary.json`

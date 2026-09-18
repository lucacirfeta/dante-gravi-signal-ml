# Multiscale efficiency v2 A2: design gate

## Outcome-blind feasibility result

The proposed A2 cannot simultaneously satisfy all three initially desired properties:

1. keep the canonical detector-native 32 s threshold unchanged;
2. add a multiscale rescue decision with non-zero acceptance probability;
3. retain a detector-wise global false-positive target of 1%.

This conclusion uses only the frozen A1 joint-null calibration background. No held-out injection outcome was used to choose or tune an A2 rule.

Applying the canonical native p99 thresholds to the 5,000 independent A1 calibration rows per detector gives:

| Detector | Native threshold | Exceedances | Realized fraction | Nominal 1% slots remaining |
|:--|--:|--:|--:|--:|
| H1 | 0.212159 | 35/5000 | 0.7% | 15 |
| L1 | 0.220344 | 75/5000 | 1.5% | -25 |

The transferred L1 native gate already exceeds 1% on this background population. Therefore a positive rescue path cannot be added in both detectors while preserving the old threshold and still claiming a unified 1% false-positive rate. The difference is a calibration-population transfer effect, not evidence that either original threshold computation was invalid.

These direct counts are a design-feasibility diagnostic only. A final A2 threshold would require complete-rule calibration with raw-source-block bootstrap and an independent validation cohort.

## Scientifically valid options

### A. Separate diagnostic channels — recommended now

Keep the canonical native 32 s production decision unchanged. Report the multiplicity-controlled multiscale response as a separate diagnostic/follow-up channel. Do not combine the two into a single 1% detection claim.

This preserves the established pipeline, retains the A1 scientific result, and avoids selecting a new alpha allocation from the observed held-out efficiencies.

### B. Unified 1% A2 gate

Freeze an explicit division or joint allocation of the 1% detector-wise error budget, then recalibrate both native and rescue components from scratch. This cannot guarantee that the canonical native threshold remains unchanged and requires a new independent validation cohort.

### C. Preserve the native threshold and raise the global target

Keep the canonical native threshold and add a rescue gate only after explicitly authorizing a detector-wise global false-positive target above 1%. The complete union must then be calibrated and reported at that new target.

## Gate status

`A2_SCIENTIFIC_DECISION_REQUIRED`

No A2 decision logic should be implemented until one option is authorized. The recommended path is option A for the current release and evidence base. Option B is the appropriate later experiment if a single production decision is required and a fresh held-out cohort can be reserved.

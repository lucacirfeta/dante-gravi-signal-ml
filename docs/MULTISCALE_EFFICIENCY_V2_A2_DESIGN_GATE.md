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

## Authorized decision

On 2026-09-18 the author selected option A: `separate_diagnostic_channels`.
The canonical detector-native 32 s decision remains the only production
decision. The frozen A1 joint-max result is exposed only as a diagnostic
follow-up field. It cannot override or promote a production candidate, and no
OR-combined or unified 1% false-positive claim is emitted.

Gate status: `APPROVED_SEPARATE_DIAGNOSTIC_CHANNELS`.

Option B remains the appropriate later experiment if a single production
decision is required and a fresh held-out cohort can be reserved.

## Verified implementation

The frozen option-A projection completed with status
`PASS_A2_SEPARATE_DIAGNOSTIC_CHANNELS` over all 7,440 paired injection rows.
The production field is replayed exclusively from the detector-native 32 s
decision; the diagnostic field is replayed independently from the verified A1
joint maximum. No combined decision field is emitted.

- Contract digest: `f14188a7e57d0914f5fb48b896fbe4ebe1a57e1b3febccfe79b478b6999c6d36`
- Run key: `490f45d17c1699ecbde7685218f69a7737ae1140b8ef62c5cb7516f697d478a2`
- Artifact digest: `fd12093c7209eba0392780b6c08aa9959ad317d6931b126f9d56a4a319115539`
- Ledger SHA-256: `c85e3d67c07320da36966f65c7a6a568bb71e197c2c3aaef16cce6467383fd06`

Across the simulation ledger, 596 trials satisfy the unchanged native
production decision and 2,695 trigger the separate diagnostic channel. Their
overlap is 499; 97 are production-only and 2,196 diagnostic-only. The latter
remain follow-up evidence only and are not promoted to production candidates.

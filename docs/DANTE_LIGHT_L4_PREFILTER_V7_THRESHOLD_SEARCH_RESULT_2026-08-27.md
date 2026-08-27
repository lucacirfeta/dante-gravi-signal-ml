# DANTE-Light L4 prefilter v7: threshold-search result

## Decision

The one-shot `threshold_search` stage is complete and the detector-specific
thresholds are frozen **before risk calibration**. This is a successful
selection checkpoint, not evidence that DANTE-Light v7 is safe, operationally
beneficial, or ready for routing. The fixed thresholds must next pass the
independent `risk_calibration` gates without retuning; confirmation and O4b
remain sealed.

## Frozen result

The current exact teacher retained 58 of the 60 H1 identities sampled from the
historical teacher-positive catalog and all 60 L1 identities. The two H1
catalog identities that are not current positives were reported and excluded
from the conditioning denominator, exactly as specified before access; the
sampling role was not treated as a teacher label.

| Detector | Frozen defer threshold | Current teacher positives | Retained | Point retention | Wilson-95 lower | Natural background discarded |
|---|---:|---:|---:|---:|---:|---:|
| H1 | 0.9937049746513367 | 58 | 53 | 0.9138 | 0.8136 | 60/60 (1.000) |
| L1 | 1.0000000000000000 | 60 | 55 | 0.9167 | 0.8193 | 60/60 (1.000) |

Both selected operating points satisfy the frozen search constraints: point
retention at least 0.90 and Wilson-95 lower bound at least 0.80. The apparent
100% background discard is measured on only 60 search backgrounds per
detector, after explicitly optimizing the threshold on this partition. It is
therefore selection evidence and must not be reported as an unbiased
background-reduction estimate. The L1 score of exactly 1.0 is the observed
float output of the frozen mean-sigmoid ensemble and is preserved bitwise; it
is not interpreted as a calibrated probability.

## Provenance and access boundary

- teacher fingerprint:
  `bf1426fcba39672de67ef9c2b2f85fdb21aa4b64d4715ed893e44ce933682deb`;
- stage-specific teacher-stability receipt SHA256:
  `f7b78e6bc1d4349f3e95319f5d9581b9b34ba9fe38a7d9161aa438b87a607839`;
- threshold-search result digest:
  `2116ec0462d4d518b45c321e349dfa2a3fa17fd7b9485f3c34f506de19d9485c`;
- compact-ledger records digest:
  `3c2e48ca8bb79dc14ad3dd937a8acf5e124f3843ee0bd1fb4f7e9e7d84e0bac6`;
- threshold-contract digest:
  `4d7a3449daff3f80eef51df286a10636de904354b8d6ae340371085d2a093c57`;
- run key:
  `53fcb2b69a3621e0f73ed8456fde22514e6455b5200701637d8ea45d025c5444`.

The compact ledger contains 240 rows: 60 background and 60
teacher-positive sampling identities for each detector. The full cache is on
the E: evidence volume. The access lists for `risk_calibration`, confirmation,
and O4b are empty. `candidate_promoted` and `routing_enabled` are both false.

## Scientific boundary and next checkpoint

This result establishes only that a feasible threshold exists on the frozen
search sample for each detector. It does not establish retention on DANTE
ROBUST candidates, known-glitch morphologies, injections, unseen exact-teacher
positives, or a positive net compute saving. It also does not validate the
search background discard estimate out of sample.

Before any `risk_calibration` row is read, its identity and gate contract must
remain unchanged and the exact-teacher fingerprint plus training-only canaries
must pass again. The H1/L1 thresholds above are then evaluated once on the
independent risk-calibration partition, with no fallback, threshold adjustment,
member replacement, or second attempt. Confirmation may be considered only
after that independent checkpoint passes every predeclared safety, protected-
morphology, and operational gate.

## Reproduction

From the repository root:

```text
python scripts/verify_dante_light_prefilter_v7_threshold_search.py \
  --require-cache \
  --cache-root E:/dante_cache/dante_light/prefilter_l4_v7_threshold_search
pytest tests/test_dante_light_prefilter_v7_*.py -q
pytest tests/ -q
```

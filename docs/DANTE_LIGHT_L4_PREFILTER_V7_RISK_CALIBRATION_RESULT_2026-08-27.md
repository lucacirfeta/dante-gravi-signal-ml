# DANTE-Light L4 prefilter v7: risk-calibration result

## Decision

The one-shot `risk_calibration` stage is complete. The frozen selective-
deferral candidate is **not ready** and the experiment stops with
`V7_NOT_READY_RISK_CALIBRATION`. The operational cost gates pass, but the L1
primary teacher-positive gate and 15 of the 16 separately protected
detector/role/morphology cells fail. Confirmation, O4b and routing remain
sealed; no threshold, ensemble member or fallback was changed after access.

## Primary teacher-positive retention

The primary endpoint conditions on the frozen catalog-sampled identities that
the current exact teacher still retains. The H1 count happens to equal the
threshold-search count, but the partitions are independent: the compact
ledgers have zero overlapping identity IDs and zero overlapping
detector/window IDs for this role.

| Detector | Frozen threshold | Current positives | Light deferred | Point retention | Wilson-95 lower | Gate |
|---|---:|---:|---:|---:|---:|---|
| H1 | 0.9937049746513367 | 58 | 53 | 0.9138 | 0.8136 | PASS |
| L1 | 1.0000000000000000 | 60 | 51 | 0.8500 | 0.7389 | FAIL |

The primary gate therefore fails. As a secondary descriptive check on the
150 natural backgrounds per detector, the current exact teacher retained 3
H1 and 7 L1 windows; Light deferred 2 and 4 of them, respectively. Those small
counts were predeclared as descriptive and are not substituted for the
case-control primary endpoint.

## Protected morphology gates

Every cell below is evaluated separately, with point retention at least 0.90
and Wilson-95 lower bound at least 0.80 required. Audit rescue does not enter
these safety results.

| Detector | Protected role/morphology | Retained | Total | Point retention | Wilson-95 lower | Gate |
|---|---|---:|---:|---:|---:|---|
| H1 | DANTE-ROBUST | 57 | 60 | 0.9500 | 0.8630 | PASS |
| L1 | DANTE-ROBUST | 52 | 60 | 0.8667 | 0.7583 | FAIL |
| H1 | Blip | 2 | 60 | 0.0333 | 0.0092 | FAIL |
| L1 | Blip | 2 | 60 | 0.0333 | 0.0092 | FAIL |
| H1 | KoiFish | 53 | 60 | 0.8833 | 0.7782 | FAIL |
| L1 | KoiFish | 38 | 60 | 0.6333 | 0.5068 | FAIL |
| H1 | ScatteredLight | 14 | 60 | 0.2333 | 0.1444 | FAIL |
| L1 | ScatteredLight | 8 | 60 | 0.1333 | 0.0691 | FAIL |
| H1 | BBH 10+10 | 7 | 90 | 0.0778 | 0.0382 | FAIL |
| L1 | BBH 10+10 | 4 | 90 | 0.0444 | 0.0174 | FAIL |
| H1 | BBH 30+30 | 26 | 90 | 0.2889 | 0.2054 | FAIL |
| L1 | BBH 30+30 | 18 | 90 | 0.2000 | 0.1304 | FAIL |
| H1 | legacy NSBH 10+1.4 | 0 | 90 | 0.0000 | 0.0000 | FAIL |
| L1 | legacy NSBH 10+1.4 | 2 | 90 | 0.0222 | 0.0061 | FAIL |
| H1 | aligned tidal NSBH stress | 2 | 90 | 0.0222 | 0.0061 | FAIL |
| L1 | aligned tidal NSBH stress | 2 | 90 | 0.0222 | 0.0061 | FAIL |

The result is not a marginal miss. Except for H1 DANTE-ROBUST and, less
closely, H1 KoiFish, the frozen selective score discards most protected
morphologies. In particular, retaining catalog-sampled exact-teacher
positives is not an adequate surrogate for protecting the independent CBC and
NSBH controls. This falsifies this candidate and operating point; it does not
falsify selective deferral in general.

## Operational endpoint

The independent background endpoint passes but cannot override either safety
gate.

| Detector | Avoided exact calls | Total | Post-audit reduction | Gate |
|---|---:|---:|---:|---|
| H1 | 140 | 150 | 0.9333 | PASS |
| L1 | 140 | 150 | 0.9333 | PASS |

The combined detector/GPS-4096-s block bootstrap gives a mean net saving of
0.731394 s per window with a 95% interval of [0.699985, 0.761905] s over 300
blocks and 2,000 frozen-seed resamples. The lower bound is positive. Separate
diagnostics are also positive: H1 mean 0.705366 s, lower 0.660604 s; L1 mean
0.757421 s, lower 0.711784 s. These measurements establish that the frozen
candidate is computationally useful on background, not that it is safe.

## Provenance and access boundary

- teacher-stability receipt digest:
  `58f2fc04280dfa1216f483ea0d536bbd04f2ffd2e75b130bcd88ced352814ce5`;
- risk-calibration result digest:
  `96ee7626f3c6ee57333110eda4c776f490e0ddd87a7240fde766b6446fcafd43`;
- compact-ledger SHA256:
  `eb5dc946d2acea9d396dd8d2730ffba85e42047e95fd32524c95321a7b25b42d`;
- compact-ledger records digest:
  `6101a17a5e67c7e2ff2744a354da4dbbf9d8e250f03253e431f863a236a5fad3`;
- authorization digest:
  `0795eae5ee1c89b4a27f6b3a84de421f942ef72ef6bc5d307413746717d67433`;
- threshold-contract digest:
  `4d7a3449daff3f80eef51df286a10636de904354b8d6ae340371085d2a093c57`;
- waveform artifact digest:
  `1a7a8a0aa631f4ee78b6b83421fa64f616e348fb5811bbdd04547ccdde5f8e90`;
- run key:
  `533f9e86d4b0c8233cedad29cee3b504dd072d96d8cca34112885ddab5b98df3`.

The compact ledger contains all 1,620 predeclared rows. The full raw and batch
cache remains on the E: evidence volume. Confirmation and O4b access lists are
empty, and both `candidate_promoted` and `routing_enabled` are false.

## Scientific consequence

No confirmation run is scientifically justified for v7. The useful lesson is
the separation between economic and safety performance: the model can identify
many cheap-to-discard backgrounds, yet its learned defer score does not provide
the morphology-independent protection required for LIGO triage. A future
increment must start from a new outcome-blind design checkpoint and cannot
retune these thresholds, reuse risk calibration as confirmation, or reinterpret
the passing operational endpoint as evidence of readiness.

## Reproduction

From the repository root:

```text
python scripts/verify_dante_light_prefilter_v7_risk_calibration.py \
  --require-cache \
  --cache-root E:/dante_cache/dante_light/prefilter_l4_v7_risk_calibration
pytest tests/test_dante_light_prefilter_v7_*.py -q
pytest tests/ -q
```

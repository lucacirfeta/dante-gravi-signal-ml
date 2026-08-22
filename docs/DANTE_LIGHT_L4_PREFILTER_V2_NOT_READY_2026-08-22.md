# DANTE-Light L4 v2: frozen development result

Date: 2026-08-22

Status: `NOT_READY`. Routing remains disabled. The frozen O4b outcomes and
v2 feature ledger were not opened or built.

## Why O4a was used

O4a is the primary development base because the exact DANTE pipeline and its
ROBUST taxonomy are already reproducible there. O4b remains the independent,
later-run test and therefore cannot be used for model or threshold selection.
The known-glitch controls use released O3b Gravity Spy labels because there is
no equivalent released O4a labelled control catalogue in this repository.
This mixed-run development design tests run-generic features while preserving
O4b for a prospective one-shot evaluation.

## Frozen design

- Protocol: `config/dante_light_prefilter_protocol_v2.json`
- Protocol digest:
  `a7f94ba384e670654002db711b8c7d8d8b18e83d26603e23f14599004030b1e4`
- Split artifact: `config/dante_light_prefilter_splits_v2.json`
- Split artifact digest:
  `3067fd4595ddf1c03b44f09f19c698ca522d728c644f45cfd6929bf20e6280c4`
- Compact result:
  `artifacts/dante_light/prefilter_l4_v2/screening_summary_v2.json`
- Full external result SHA256:
  `9817377d05ee30cf9c6a5a72c33cecd6fdd2e8bc55f0031a2113412cd7063991`

Availability was checked before feature extraction without reading feature
values or exact scores. Six unavailable known-glitch reserve rows were
replaced deterministically before the split was frozen. The completed source
ledgers contain 552 background, 90 ROBUST, 258 known-glitch and 750 injection
rows. Development uses 962 rows: 552 background, 50 ROBUST, 150 known-glitch
and 210 injection rows. The original v1 evaluation partitions are unchanged.

Development and evaluation use the same point-retention requirement (at least
0.90), Wilson 95% lower bound (at least 0.80), and detector/morphology-specific
gates. The different minimum sample sizes are now explicit rather than hidden:
development uses 25 ROBUST and known-glitch examples per stratum and 35
injections; evaluation retains the original 20, 18 and 90. Consequently, the
small held-out ROBUST and known-glitch strata require zero misses to satisfy
both the point and Wilson gates. The evaluation thresholds were not changed
after observing v1.

## Result

Five pre-registered candidates were screened with shuffled five-fold grouped
cross-validation, using detector-specific logistic models and GPS blocks of
4096 s. The effective development call reduction includes the frozen 5%
rejected-window audit, matching the accounting later used on realistic O4b
traffic.

| Candidate | OOF effective call reduction | Status |
|---|---:|---|
| temporal energy | 0.18% | `NOT_READY` |
| coarse time-frequency clusters | 0.00% | `NOT_READY` |
| spectral evolution | 8.70% | `NOT_READY` |
| dyadic wavelet sparsity | 6.16% | `NOT_READY` |
| all families | 6.88% | `NOT_READY` |

The frozen minimum is 50%. The operating points shown above satisfy the
per-detector/per-morphology development retention constraints; they fail
because too many development background windows still require the exact path.
The best candidate is therefore not close to the compute gate. Feature-only
cost was 16.0 ms median and 26.3 ms at the 95th percentile over 962 development
rows, excluding data access and whitening.

## Interpretation and boundary

This is evidence that these four cheap hand-engineered representations do not
separate the protected positive controls from realistic O4a background well
enough for the requested 50% reduction. It is not evidence against the exact
DANTE-Light pipeline and introduces no regression because routing was never
enabled. No O4b threshold, retention result or compute claim exists for v2.

A further attempt would be a new scientific protocol, not a bug fix. It would
need an independently justified representation (for example a compact model
distilled from exact-path intermediate representations), new frozen
development rules and an untouched evaluation epoch. Such a change requires
an explicit scientific decision before implementation.

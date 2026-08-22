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
- Full result: `artifacts/dante_light/prefilter_l4_v2/screening_result_v2.json`
- Full result SHA256:
  `9817377d05ee30cf9c6a5a72c33cecd6fdd2e8bc55f0031a2113412cd7063991`
- Post-hoc diagnostic result:
  `artifacts/dante_light/prefilter_l4_v2/diagnostics_v2.json`
- Diagnostic result SHA256:
  `5536d195d72099dfe0495356dcbb64c473115dbf087e27631a3bcf726054131a`

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

The frozen minimum is 50%. This is a predeclared engineering-utility target
for deciding whether the added prefilter complexity is worthwhile, not a
universal scientific boundary between useful and useless representations.
The operating points shown above satisfy the
per-detector/per-morphology development retention constraints; they fail
because too many development background windows still require the exact path.
The best candidate is therefore not close to the compute gate. Feature-only
cost was 16.0 ms median and 26.3 ms at the 95th percentile over 962 development
rows, excluding data access and whitening.

## Interpretation and boundary

This is evidence that these four cheap hand-engineered representations cannot
meet the joint protected-stratum retention constraints and requested 50%
reduction under this frozen model and cohort. It is not evidence that every
representation lacks ranking signal, nor evidence against the exact
DANTE-Light pipeline. It introduces no regression because routing was never
enabled. No O4b threshold, retention result or compute claim exists for v2.

## Post-hoc diagnostic-only analysis

The diagnostic protocol was frozen separately after the negative screen. It
reuses the exact grouped OOF predictions, never reads O4b outcomes, cannot
change `screening_result_v2.json`, and is explicitly ineligible for PASS/FAIL.

| Candidate | Overall OOF ROC-AUC | H1 | L1 |
|---|---:|---:|---:|
| temporal energy | 0.7172 | 0.7158 | 0.7190 |
| coarse time-frequency clusters | 0.5597 | 0.5370 | 0.5812 |
| spectral evolution | 0.8052 | 0.7942 | 0.8169 |
| dyadic wavelet sparsity | 0.7578 | 0.7388 | 0.7843 |
| all families | 0.8027 | 0.7887 | 0.8188 |

Aggregate AUC therefore shows real ranking information, especially for the
spectral family. It does not imply that the frozen retention gate is merely
underpowered: for the strongest aggregate candidate, the same-detector OOF
AUC for `NSBH_10_1.4` is only 0.5327 in H1 and 0.5564 in L1. The protected
strata are heterogeneous, and these near-chance hard strata force permissive
thresholds even though easier morphologies separate well. Increasing sample
size would improve precision but would not by itself guarantee the missing
separation.

For `all`, the offline C sweep gives overall AUC 0.8050, 0.8027 and 0.8057 for
`C = 0.1, 1, 10`; the corresponding constrained reductions are 2.90%, 6.88%
and 7.07%. Fixed regularization therefore does not explain why `all`
underperforms the 8.70% spectral-only operating point.

## Independent verification material

The complete screen and diagnostics are tracked because they are only 35 kB
and 25 kB. A deterministic development bundle containing the four complete
ledgers, frozen configs, split, results, hashes and POSIX ZIP paths was also
built twice byte-for-byte identically. Its size and SHA256 are recorded in
`artifacts/dante_light/prefilter_l4_v2/bundle_manifest_v2.json`. The
publication URL/DOI is intentionally still empty there; until the ZIP
is published, an external reviewer can inspect all result fields and hashes
from Git but cannot recompute the percentages without the external ledgers.

On Windows with Python 3.11.5 and pytest 9.0.3, the pre-diagnostic checkout
reproduced the reported 361 passed and one skip. After adding the three
diagnostic/bundle regression tests documented here, `python -m pytest tests/
-q -rs` produced 364 passed and one skip. The only skip was
`tests/test_smoke.py:247` because `nds2` was not importable. The five named
release-gate, manuscript-contract and reproducibility-bundle tests were rerun
individually and all passed. A result of 349 passed, six skipped and seven
failed therefore comes from a different checkout, dependency set, or private
ignored manuscript/artifact state and is not reproduced by this working tree.

A further attempt would be a new scientific protocol, not a bug fix. The
stratum-level diagnostics argue for first targeting the hard injection
morphologies or a morphology-aware cascade, rather than assuming that more
samples or a different logistic C will solve the gate. Any new representation,
cohort expansion or gate change requires an explicit scientific decision,
new frozen development rules and an untouched evaluation epoch.

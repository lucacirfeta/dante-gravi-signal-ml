# DANTE-Light L4 v6 outcome-blind partition freeze

Date: 2026-08-25

Status: **FROZEN; DOWNLOADS ALLOWED ONLY FROM THE COMMITTED LIST; TRAINING NOT YET AUTHORIZED**

## Frozen population

The official GWOSC O4a CBC_CAT1 snapshot is the population source. Hardware,
CBC, and burst injection overlaps are removed. Every detector/4,096 s block
used by v1--v5 is excluded before assignment. Local cache availability is
recorded only after selection and cannot influence which scientific identity
enters a partition.

Per detector, the frozen allocation is:

| Partition | Blocks | Windows/block | Status |
|---|---:|---:|---|
| Phase B fit | 144 | 8 | training-only, still unopened |
| Phase B internal validation | 36 | 8 | selection-only, still unopened |
| Phase C | 60 | 1 | sealed fidelity confirmation |
| Phase D development | 150 | 1 | identity reserve only |
| Phase D confirmation | 150 | 1 | sealed identity reserve only |

This is 540 blocks per detector. The 60-block Phase-C count is not inherited
from a retention calculation: it is justified by the separately frozen
Spearman power contract. Phase C uses one observation per block so the
statistical observation and independence unit coincide.

## Deterministic selection

Eligible blocks are ranked within detector by available valid-start span and
split into five equal-count rank strata. Within each stratum, ordering is
derived from SHA256 of the frozen contract digest, purpose, detector, and
block. Round-robin interleaving of the five strata gives exact balance:
Phase B has 36 blocks per stratum, Phase C 12, and each Phase-D reserve 30.
The Phase-B 144/36 internal split is independently hash-ordered and
span-stratified.

The eight Phase-B starts are evenly index-spaced over the official maximal
set of disjoint padded windows. Single-window partitions use a separate
hash-priority start. Whitening context remains 4 s on both sides of each 32 s
window. No local-file property enters either operation.

The recomputed eligible-pool digests exactly match the prior planning audit:

- H1: `2920ab25b9be9ef508011d342fd281bd6a77a392b88a5f9742e3b7fd5bf10ef2`;
- L1: `1a8cbb14b382938e5b03ee6eeee19b11b9a224f8b06bf1e889447b17ed4d86a0`.

## Frozen cache work

After selection, 228 H1 blocks and 212 L1 blocks contain at least one selected
padded window absent from the pre-freeze raw manifest. The download manifest
contains only those missing 40 s padded intervals: 681 H1 intervals (27,240 s)
and 588 L1 intervals (23,520 s). This avoids fetching 440 complete 4,096 s
blocks while preserving exactly the same frozen identities.

Downloads may be written only to the v6 cache alias `DANTE_V6_RAW_CACHE_ROOT`
(default `E:/dante_cache/dante_light/prefilter_l4_v6_raw`) and only after this
manifest is committed and verified. Download success is infrastructure
provenance, not a scientific eligibility criterion.

## Reproducibility anchors

- partition contract digest:
  `b7dc762509309efcff3b7ad196965fea9abd8408df38409e01a77b62e65e5e3b`;
- complete manifest digest:
  `0fd88e515aba719ceee286461cc51c61d687a48f388e3e153f98eb19d1268384`;
- public header: `config/dante_light_prefilter_v6_partitions.json`;
- block entries: `config/dante_light_prefilter_v6_partitions.jsonl`;
- exact cache list: `config/dante_light_prefilter_v6_download_manifest.jsonl`;
- compact summary:
  `artifacts/dante_light/prefilter_l4_v6_design/partition_freeze_summary_v6.json`;
- verifier: `scripts/verify_dante_light_prefilter_v6_partitions.py`.

No teacher score, student output, morphology label, development result,
confirmation result, or O4b datum was accessed. This freeze authorizes only
cache acquisition from the exact committed list. Phase-B training remains
blocked until the objective and five-arm matrix are frozen separately.

# DANTE-Light L4 v6 pre-Phase-B audit (2026-08-25)

Status: **DIAGNOSTIC COMPLETE; PHASE B, LAMBDA, AND PARTIAL-BLOCK ADMISSION NOT FROZEN**

Artifact:
`artifacts/dante_light/prefilter_l4_v6_design/pre_phase_b_audit_v6.json`
(digest `c532891d014feb1720210072fe1302a69bb6f3c4a346d0509927c7370a918073`).

No teacher target value enters the audit computation, and no morphology label,
development, confirmation, or O4b outcome is accessed. Its gradient input
consists only of already-open, canonically whitened v5 fit strain. Target
vectors are deterministic synthetic standard normal values, standardized
independently per detector. The raw-capacity
audit uses the frozen GWOSC API segment snapshot, local raw-file identities,
and prior block identities without reading strain values.

## Gradient-scale result

The agreed RankNet construction uses all 28 unordered pairs among the eight
windows in each detector/GPS block. Pair losses are averaged within block,
then across blocks, then equally across H1 and L1. There are no cross-block or
cross-detector pairs, no margin, and only exact target ties are omitted.

At five deterministic random initializations, the SmoothL1-to-RankNet gradient
norm ratio with `lambda = 1` was:

| Gradient space | Minimum | Median | Maximum |
|---|---:|---:|---:|
| prediction vector | 1.047 | 1.050 | 1.053 |
| trainable parameters | 15.1 | 178.1 | 316.8 |

The two losses have similar derivatives with respect to the prediction vector,
but RankNet's parameter gradient nearly cancels through the initially almost
constant student mapping (initial prediction standard deviation approximately
`1.0e-4` to `1.3e-4`). Consequently, `lambda = 1` would make the rank term
structurally weak at initialization for this graph. Target standardization is
not an adequate justification for that value.

This audit does not imply that `lambda` should be set to the median ratio:
the ratio varies by more than a factor of twenty across initializations, so a
large fixed multiplier could instead destabilize some replicas. A warm-up,
gradient-normalized objective, or explicitly frozen fixed multiplier are new
optimization decisions requiring a separate checkpoint.

## Why remaining O4a blocks are partial

After excluding every prior and v5-assigned 4,096 s block, the local mirror
touches 585 H1 and 505 L1 blocks. Only 133 H1 and 200 L1 blocks have complete
local raw coverage. Requiring local raw coverage, CBC_CAT1, injection-clear
padding, and eight non-overlapping 32 s windows with 4 s context on each side
gives mechanical capacity in 475 H1 and 422 L1 blocks.

Among the mechanically capable blocks with partial local coverage:

| Detector | Partial capable | CBC_CAT1 itself partial | CBC_CAT1 full but local mirror incomplete |
|---|---:|---:|---:|
| H1 | 379 | 365 | 14 |
| L1 | 246 | 241 | 5 |

Thus most partial coverage coincides with official observing/CBC_CAT1 segment
boundaries or gaps, while a small, separately identifiable subset is caused
by local-mirror incompleteness despite full official CAT1. Raw-file existence
alone is not admissibility evidence: across the remaining blocks, the mirror
also contains 447,325 H1 and 349,500 L1 seconds outside CBC_CAT1, and misses
328,558 H1 and 194,878 L1 seconds that are in CBC_CAT1.

## Independence consequence

The 4,096 s grouping remains the only admissible resampling unit, so a
block-bootstrap that resamples whole blocks is structurally unchanged. The
within-block sampling geometry is not unchanged:

| Population | H1 median eight-window start span | L1 median |
|---|---:|---:|
| v5 training | 3,200 s | 3,200 s |
| capable partial blocks, deterministic diagnostic selection | 1,200 s | 1,180 s |

The partial-block windows are therefore materially more clustered. The audit
does not establish window-level independence, and the Wilson calculations or
power assumptions based only on a count of windows cannot be inherited from
v5. Any future protocol admitting these blocks must base uncertainty and
power on independent block counts, preserve whole-block bootstrap resampling,
and pre-register a spacing/coverage rule. No partial block is admitted by the
present artifact.

## Decision boundary

Before Phase B can be frozen, two decisions remain scientific rather than
implementation details:

1. objective scaling: fixed multiplier, warm-up, or a predeclared adaptive
   gradient-normalization rule;
2. population design: whether partial CAT1 blocks are admitted, with a new
   block-based power analysis and disjoint reserves for all later stages.

# DANTE-Light L4 prefilter evaluation protocol

Status: **implementation in progress; routing disabled**
Scientific mode: **research-only, outcome-blind evaluation**

## Question and fixed boundary

The L4 experiment asks whether the deterministic excess-energy prefilter can
avoid at least 50% of DINOv2 calls, after rejected-window auditing, without
removing exact DANTE escalations or materially reducing coverage of robust
candidates, known glitch morphologies, or injections. It does not test a new
anomaly score and it cannot change the canonical no-prefilter path.

The only allowed feature source is the clean 32 s strain returned by
`whiten_context(pad=4.0) -> extract_clean_subwindow`. Features must be computed
before reading the exact DANTE disposition. Threshold selection and final
evaluation use disjoint GPS epochs or independent simulation seeds.

## Data partitions

1. **Development only:** O4a CAT1 background plus an explicitly frozen subset
   of O4a robust candidates, O3b known-glitch controls and injection trials.
   It may choose the two feature thresholds but contributes no final metric.
2. **Later shadow evaluation:** all 768 locked O4b-v2 windows, including all 18
   exact Light escalations. No O4b outcome may enter threshold selection.
3. **Scientific retention evaluation:** held-out robust candidates, at least 18
   reference-positive examples per required known-glitch stratum, and at least
   18 reference-positive examples per required injection stratum. These
   examples must not have selected the thresholds. Existing rows may be reused
   only when their raw strain or
   deterministic injection recipe can regenerate the canonical feature input.

The current published score tables do not contain prefilter features and cannot
be used as a substitute for raw/whitened strain. A missing raw segment,
unreproducible injection, detector mismatch, hash mismatch or insufficient
stratum produces `NOT_READY`.

## Locked operating point

The development search may examine only `crest_factor` and
`peak_band_fraction`. It selects one OR threshold pair and freezes:

- threshold-tuning row identities and SHA256;
- threshold grid and deterministic tie-breaking rule;
- rejected-window audit fraction and seed;
- detector-specific final evaluation start GPS;
- required strata and their minimum sample sizes;
- point-retention and Wilson-lower-bound requirements.

The promotion-grade minima are fixed in code: effective DINO-call reduction
at least 0.50, non-zero rejected-window audit, at least 18 examples per required
group, point retention at least 0.90, Wilson 95% lower bound at least 0.80, and
zero missed exact O4b escalations. The contract must gate robust candidates,
known glitches and injections explicitly. Retention gates are separate for
each detector and, for known glitches and injections, for each pre-registered
morphology or source system; an aggregate mean cannot hide a failed stratum.
Retention is conditional on a frozen positive decision from the exact
reference scorer (`retention_target=true`). Requiring the cheap filter to select
examples that exact DANTE itself rejects would test a different detector and is
not the L4 non-regression estimand. Cells with fewer than 18 reference-positive
examples remain unmeasured and cannot contribute to promotion.

## Effective compute and miss accounting

An expensive call is counted whenever a window crosses the prefilter or is
selected for the deterministic audit. Therefore

`reduction = 1 - (crossing + audited rejected) / all evaluated windows`.

The full evaluation still runs exact DANTE for every row so the true prefilter
miss count is observable. The audit subset is reported separately; it is a
simulation of the estimate available after deployment, not a replacement for
the full held-out comparison.

## Fail-closed decision

`scripts/evaluate_dante_light_prefilter.py` returns:

- exit 0 and `PASS` only if every locked group, compute and exact-escalate gate
  passes;
- exit 1 and `NOT_READY` for a valid but insufficient result;
- exit 2 and `NOT_READY` for an invalid, incomplete or non-reproducible input.

Even `PASS` writes `routing_enabled=false`. A separate reviewed promotion
artifact and a complete parallel shadow epoch are required before
`PrefilterContract.status="promoted"` can enter any runner configuration.

## Required execution order

1. freeze development/evaluation identities;
2. extract canonical feature ledgers and verify raw strain hashes;
3. tune thresholds on development rows and freeze the tuning artifact;
4. build the evaluation ledger without consulting O4b outcomes;
5. evaluate and archive negative as well as positive results;
6. run the complete DANTE-Light and repository regression gates;
7. only then decide whether a separate promotion experiment is justified.

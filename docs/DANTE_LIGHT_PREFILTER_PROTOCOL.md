# DANTE-Light L4 prefilter research protocol

Status: **v1 and v2 development complete, both NOT_READY; routing disabled**
Scientific mode: **research-only, outcome-blind evaluation**

V1 is preserved as the immutable two-feature negative result documented in
`DANTE_LIGHT_L4_PREFILTER_NOT_READY_2026-08-22.md`. V2 is a separate,
prospectively frozen attempt documented in
`DANTE_LIGHT_L4_PREFILTER_V2_NOT_READY_2026-08-22.md`. V2 added four
pre-registered feature families and grouped cross-validation; it did not
replace or rewrite v1. Neither result authorizes routing or an O4b performance
claim.

## Question and fixed boundary

The L4 experiments ask whether a deterministic cheap prefilter can
avoid at least 50% of DINOv2 calls, after rejected-window auditing, without
removing exact DANTE escalations or materially reducing coverage of robust
candidates, known glitch morphologies, or injections. It does not test a new
anomaly score and it cannot change the canonical no-prefilter path.

The only allowed input is the clean 32 s strain returned by
`whiten_context(pad=4.0) -> extract_clean_subwindow`. Features must be computed
before reading the exact DANTE disposition. Threshold selection and final
evaluation use disjoint GPS epochs or independent simulation seeds.

## Data partitions

1. **Development only:** O4a CAT1 background plus an explicitly frozen subset
   of O4a robust candidates, O3b known-glitch controls and injection trials.
   It may choose the two feature thresholds but contributes no final metric.
2. **Later shadow evaluation:** all 768 locked O4b-v2 windows, including all 18
   exact Light escalations. No O4b outcome may enter threshold selection.
3. **Scientific retention evaluation:** 20 held-out ROBUST candidates per
   detector, 18 reference-positive examples per required known-glitch stratum,
   and 90 reference-positive examples per required injection stratum. These
   examples must not have selected the thresholds. Existing rows may be reused
   only when their raw strain or
   deterministic injection recipe can regenerate the canonical feature input.

The current published score tables do not contain prefilter features and cannot
be used as a substitute for raw/whitened strain. A missing raw segment,
unreproducible injection, detector mismatch, hash mismatch or insufficient
stratum produces `NOT_READY`.

## V1 locked operating point

The development search may examine only `crest_factor` and
`peak_band_fraction`. It selects one OR threshold pair and freezes:

- threshold-tuning row identities and SHA256;
- threshold grid and deterministic tie-breaking rule;
- rejected-window audit fraction and seed;
- detector-specific final evaluation start GPS;
- required strata and their minimum sample sizes;
- point-retention and Wilson-lower-bound requirements.

The promotion-grade minima are read from the versioned protocol config:
effective DINO-call reduction at least 0.50, non-zero rejected-window audit,
the role-specific sample sizes
above, point retention at least 0.90, Wilson 95% lower bound at least 0.80, and
zero missed exact O4b escalations. The contract must gate robust candidates,
known glitches and injections explicitly. Retention gates are separate for
each detector and, for known glitches and injections, for each pre-registered
morphology or source system; an aggregate mean cannot hide a failed stratum.
Retention is conditional on a frozen cohort-specific positive endpoint
(`retention_target=true`): the exact Light disposition for O4b shadow rows, the
released robustness class for robust candidates, the external quality-screened
label for known glitches, and membership in a pre-registered injection cell for
simulations. These endpoints and their split hashes are fixed before feature
evaluation. Cells below their role-specific frozen minimum remain unmeasured
and cannot contribute to promotion. Exact-score non-regression is
reported separately on all 18 O4b escalations.

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

## V2 frozen extension

V2 keeps the same scientific gates and audit accounting but removes the
development/evaluation sample-size ambiguity. Development contains 25 ROBUST
examples per detector, 25 known glitches per detector and morphology, and 35
injections per detector and source system. Evaluation remains the untouched v1
partition: 20, 18 and 90 respectively. Point-retention and Wilson requirements
are identical in both stages. At n=18 and n=20 those combined gates imply zero
held-out misses; the smaller evaluation counts are not treated as equivalent
statistical power to the development counts.

The candidate representations are temporal-energy concentration, coarse
time-frequency cluster topology, spectral evolution and dyadic wavelet
sparsity. Detector-specific L2 logistic models are screened with shuffled
five-fold grouped cross-validation; groups are detector-specific 4096 s GPS
blocks. The selection objective is effective development call reduction after
the same 5% deterministic audit used by evaluation. This quantity is measured
on O4a development background, whereas final effective compute reduction would
be measured on the differently composed O4b shadow stream. The final gate is
therefore not inferred from the development metric.

The frozen v2 screening result is `NOT_READY`: the best candidate reached
8.70% rather than 50%. Under the protocol, this forbids O4b feature extraction
and evaluation. Any further representation or model is v3 work requiring a new
scientific decision and a new protocol, not an in-place v2 optimization.

## V1 reproducibility commands

The frozen v1 split artifact is generated deterministically from the released P5,
known-glitch and injection ledgers:

```bash
python scripts/build_dante_light_prefilter_splits.py
```

Real-strain features use the same canonical preparation function as the Light
runner. Long extractions are resumable through a `.partial.jsonl` ledger; a
limited run is marked `smoke_only` and cannot satisfy a final gate:

```bash
python scripts/build_dante_light_prefilter_features.py \
  --manifest config/dante_light_o4b_shadow_v2.json \
  --records runs/dante_light/o4b_v2/shared/records.jsonl \
  --output-dir /external/cache/l4_o4b --strain-source gwosc-only

python scripts/build_dante_light_prefilter_cohort_features.py \
  --split config/dante_light_prefilter_splits_v1.json \
  --role robust_candidate --output-dir /external/cache/l4_robust \
  --strain-source local-only

python scripts/build_dante_light_prefilter_cohort_features.py \
  --split config/dante_light_prefilter_splits_v1.json \
  --role background --output-dir /external/cache/l4_background \
  --strain-source auto
```

The known-glitch command is identical with `--role known_glitch` and normally
uses `--strain-source gwosc-only` unless a verified O3b mirror is configured.
Injection rows require deterministic reconstruction in raw strain and are not
accepted by the real-strain cohort command. In the pinned WSL/LALSuite
environment, reconstruct them with:

```bash
python scripts/build_dante_light_prefilter_injection_features.py \
  --split config/dante_light_prefilter_splits_v1.json \
  --trials data/production/aggregated/astrophysical_injection_trials_o4a_idxq4-64_queryq4-64.csv \
  --output-dir /external/cache/l4_injection
```

Every reconstructed row must reproduce its published detector SNR before the
injected-strain hash and cheap features are accepted.

Thresholds are then chosen strictly from the frozen development partitions.
The tuner verifies every source-ledger SHA256, role split, detector and
morphology cell before searching the two-dimensional operating-point grid:

```bash
python scripts/tune_dante_light_prefilter.py \
  --background /external/cache/l4_background/background_feature_ledger_v1.json \
  --robust /external/cache/l4_robust/robust_candidate_feature_ledger_v1.json \
  --known /external/cache/l4_known/known_glitch_feature_ledger_v1.json \
  --injection /external/cache/l4_injection/injection_feature_ledger_v1.json \
  --output /external/cache/l4_final/threshold_tuning_v1.json
```

If and only if tuning returns `PASS`, assemble the later shadow rows and the
held-out control partitions. Assembly copies the tuning artifact beside the
contract, binds every source and split hash, and never enables routing:

```bash
python scripts/assemble_dante_light_prefilter_evaluation.py \
  --background /external/cache/l4_background/background_feature_ledger_v1.json \
  --shadow /external/cache/l4_o4b/shadow_feature_ledger_v1.json \
  --robust /external/cache/l4_robust/robust_candidate_feature_ledger_v1.json \
  --known /external/cache/l4_known/known_glitch_feature_ledger_v1.json \
  --injection /external/cache/l4_injection/injection_feature_ledger_v1.json \
  --tuning /external/cache/l4_final/threshold_tuning_v1.json \
  --output-dir /external/cache/l4_final

python scripts/evaluate_dante_light_prefilter.py \
  --contract /external/cache/l4_final/evaluation_contract_v1.json \
  --ledger /external/cache/l4_final/evaluation_feature_ledger_v1.json \
  --output /external/cache/l4_final/evaluation_result_v1.json
```

These large, regenerable experiment products belong in the chosen external
cache (for this project, normally `E:\\dante_cache`), not in
`data/production`. The compact JSON result is the machine-readable final
report; a `PASS` means the research experiment met its preregistered gates,
not that the prefilter has been promoted into DANTE-Light.

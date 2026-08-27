# DANTE-Light L4 prefilter v7: outcome-blind selective-deferral freeze

Status: **FROZEN IDENTITY-ONLY; CONFIRMATION SEALED; NO ROUTING**

## Scientific question

Versions v5 and v6 asked a small student to reproduce the continuous ordering
of exact DANTE. The best v6 Phase-B arm reached a worst detector/replicate
Spearman coefficient of only `0.383779623757681`, far below the frozen `0.90`
gate. Version v7 does not reinterpret that failure and does not reopen v6. It
asks a different, narrower question: can a cheap model identify only the
windows that are safe to omit while conservatively deferring all uncertain
windows to exact DANTE?

The primary endpoint is

`P(Light defers | exact DANTE retains, frozen O4a candidate catalog)`.

Equivalently, the unsafe-discard rate on catalogued teacher positives is one
minus this retention. This orientation is essential. A direct recomputation
from the v6 native-score ledger corrected the earlier `0/1440` statement: 23
of 1,440 H1 windows (`0.0159722`) and 49 of 1,440 L1 windows (`0.0340278`)
exceeded the historical detector threshold. The population is rare, not empty.
On a 150-block calibration sample, the expected positive count would still be
only a few cases, making the natural-traffic conditional error rate unsuitable
as the primary safety endpoint. A curated teacher-positive cohort is therefore
used for powered safety inference; the natural-traffic false-omission rate is
secondary when its observed denominator is adequate.

The exact-DANTE label is teacher behaviour, not physical truth. The primary
positive cohort is conditioned on the retrospective O4a candidate catalog; it
is not a sample of all continuous detector traffic.

## Why the primary and protected gates both remain

The primary gate covers any catalogued case retained by exact DANTE, including
cases that are not one of the enumerated protected controls. The protected gate
independently tests DANTE ROBUST candidates, each Gravity Spy morphology, and
each injection system. It is never pooled across detector or morphology.

This distinction is useful but limited in the current data. Of the 660 selected
primary-positive identities, 659 are `Family_01`; the remaining identity is
the H1 case `Singleton_1369305276`. H1 contains 307 ROBUST and 23 AMBIGUOUS
cases, while L1 contains 313 ROBUST and 17 AMBIGUOUS cases. A PASS would
therefore establish retention for this frozen historical population, not
general safety for unseen glitch families. The selected singleton is an
individual catalog case, not a statistically validated morphology stratum;
the L1 singleton was not forced into the cohort after sampling.

## Independent threshold procedure

The threshold is selected once on `threshold_search` as the maximum natural
background discard fraction compatible with the teacher-positive retention
gate separately in H1 and L1. It is then frozen before any
`risk_calibration` student output is opened. The fixed threshold is evaluated
once on `risk_calibration`; failure stops the experiment with no retuning,
fallback threshold, or second attempt. Confirmation can be opened only if all
calibration gates pass.

The student score is defined as an estimated probability of deferral: a window
is deferred when `score >= detector threshold` and discarded otherwise. If
multiple thresholds produce the same frozen objective and gate outcome, the
lower numerical threshold wins because it is the more conservative rule.

This construction avoids using a pointwise confidence interval after searching
the same sample over many thresholds. It also avoids relying on an i.i.d.
selective-risk guarantee for temporally dependent LIGO data. All resampling for
cost and traffic endpoints remains detector/GPS-4096-s block based.

## Frozen identities

Per detector:

| Partition | Natural background | Exact-teacher positives | Purpose |
|---|---:|---:|---|
| training | 150 | 150 | balanced case-control training; no inference claim |
| threshold search | 60 | 60 | one-time threshold selection |
| risk calibration | 150 | 60 | fixed-threshold one-shot gate |
| confirmation | 300 | 60 | independent sealed confirmation |

Risk calibration and confirmation each additionally contain, per detector:

- 60 DANTE ROBUST candidates;
- 60 examples for each of Blip, KoiFish, and ScatteredLight;
- 90 injections for each of BBH 30+30, BBH 10+10, legacy point-particle NSBH
  10+1.4, and the aligned-spin tidal NSBH stress population.

Each gated detector/morphology stratum uses at most one case per 4096-s block.
Different injection morphologies may share a base noise block, but no single
morphology repeats a block; their gates are separate.

The natural-background identities are recoverable transfers of previously
frozen, unopened reserves:

- v6 `phase_d_development` -> v7 `training`;
- v6 `phase_c` -> v7 `threshold_search`;
- v6 `phase_d_confirmation` -> v7 `risk_calibration`;
- v5 sealed confirmation -> v7 confirmation.

The v5 confirmation protected controls are transferred with the same frozen
identities. The transfer contract retires these identities from further use
under their prior protocols. All v6 Phase-C/Phase-D and v5 confirmation
student-output access lists were empty at transfer.

Natural-background is a sampling role, not an assumed negative label. Exact
DANTE will assign the binary teacher label only when the corresponding
training or evaluation partition is legitimately opened.

## Power and uncertainty

The numerical retention rule is inherited unchanged from the versioned v5
contract: point retention at least `0.90` **and** the 95% Wilson lower bound at
least `0.80`. At true retention `0.95`, `n=60` requires 55 retained cases and
has exact binomial pass probability `0.9212807354233151`. Injection strata
retain `n=90`, requiring 81 successes with pass probability
`0.985480633688403`.

The 300-block confirmation background has worst-case 95% Wilson half-width
`0.05622048386608308`. The 150-block risk-calibration background has half-width
`0.07900987971145856`; it is an intermediate one-shot gate, not a replacement
for the higher-precision sealed confirmation. No prospective power claim is
made for the net-saving endpoint because no outcome-blind effect size and
block-dependence distribution are available.

The 50% background-call reduction remains explicitly a product requirement,
not a statistical discovery threshold. The paired mean net-saving lower bound
must remain positive using whole-block bootstrap resampling.

## Reproducibility and seal

The authoritative files are:

- `config/dante_light_prefilter_v7_outcome_blind_contract.json`;
- `config/dante_light_prefilter_v7_identities.json` and `.jsonl`;
- `config/dante_light_prefilter_v7_identity_transfer.json`;
- `config/dante_light_prefilter_v7_injection_trials.jsonl`;
- `config/dante_light_prefilter_v7_confirmation_seal.json`;
- `artifacts/dante_light/prefilter_l4_v7_design/selective_deferral_power_v7.json`.
- `artifacts/dante_light/prefilter_l4_v7_design/background_teacher_prevalence_audit_v7.json`
  and its compact row ledger.

Run:

```text
python scripts/verify_dante_light_prefilter_v7.py
pytest tests/test_dante_light_prefilter_v7_freeze.py -q
```

At freeze, all v7 student-output lists are empty, confirmation is
`SEALED_NOT_OPENED`, O4b is unopened, and production routing remains disabled.

## Next scientific checkpoint

This freeze authorizes no training run by itself. Before training is opened,
the classifier architecture, loss, calibration score, class weighting,
replicate rule, and deterministic audit-sampling cost must be frozen in a
separate training contract. Those choices change what is learned and require
an explicit scientific checkpoint rather than an implementation default.

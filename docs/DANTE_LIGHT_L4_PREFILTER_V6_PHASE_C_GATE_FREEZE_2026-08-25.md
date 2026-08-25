# DANTE-Light L4 v6 Phase-C fidelity gate freeze

Date: 2026-08-25

Status: **FROZEN OUTCOME-BLIND; PHASE C REMAINS SEALED**

## Decision

Phase C is a one-shot training-only confirmation of the arm selected in Phase
B. It is not a development, routing, protected-morphology, cost-benefit, O4b,
or discovery test. The freeze does not authorize Phase-B scoring or Phase-C
access.

The gate is applied separately to H1 and L1 and to every one of the five
frozen training replicas. All ten detector/replica cells must pass:

1. point Spearman correlation with the native O4a teacher at least 0.90; and
2. one-sided 95% Bonett--Wright lower confidence bound at least 0.85.

There is no favorable-seed selection and no aggregation across detectors. The
one-sided interval is intentional because the prespecified decision concerns
only whether fidelity exceeds a lower safety boundary. Requiring every cell
to pass is conservative; no multiplicity adjustment is used to rescue a
failing cell.

## Independence and sample size

Phase C uses 60 fresh detector/4,096 s blocks per detector and exactly one
paired teacher/student observation per block. The valid 32 s start will be
selected deterministically by the future frozen split manifest. This replaces
the earlier planning-only suggestion of eight windows per Phase-C block.

The one-window rule makes the statistical observation identical to the
declared independence unit. It therefore avoids treating temporally adjacent
windows as independent and avoids requiring an unverified within-block
effective-sample-size model. Any later bootstrap sensitivity calculation may
resample only detector/4,096 s blocks and is explicitly non-gating.

The confidence interval uses the Fisher transform and the improved Spearman
variance `(1 + rho_s^2/2)/(n - 3)` described by Bonett and Wright
([Psychometrika 65, 23--28](https://doi.org/10.1007/BF02294183)). This is an
asymptotic model, not a guarantee about the unknown empirical teacher/student
score distribution.

Under the preregistered planning alternative `rho_s=0.95`, the frozen
single-cell model-based pass probability is 0.976428. The lower bound evaluated
at that alternative is 0.916918. Historical counts of 18, 20, 25, 35, and 40
blocks miss the 0.90 power target under the same model; 60 provides margin and
retains the planning allocation without borrowing from later partitions.

This power statement is deliberately cell-wise. Because dependence among the
five replicas is not assumed prospectively, no familywise probability that all
ten cells pass is claimed.

## Reproducibility anchors

- contract:
  `config/dante_light_prefilter_v6_phase_c_power.json`;
- contract digest:
  `6dd4c08fcfa1e74804a4679e3faef9523f3b02e33bc21232a39a09021d2bdc81`;
- compact power artifact:
  `artifacts/dante_light/prefilter_l4_v6_design/phase_c_fidelity_power_v6.json`;
- artifact digest:
  `c968e467c1090151c1068662c20bbebca093d3efcc61455b7d489f0872fbf12e`;
- verifier:
  `scripts/verify_dante_light_prefilter_v6_phase_c_power.py`.

## Boundary

A later Phase-C PASS would establish only that the Phase-B-selected student
reproduces the native O4a teacher ordering on the frozen Phase-C block
population at the declared detector/replica gate. It would not establish safe
retention of any protected morphology, positive compute saving, operational
routing readiness, O4b generalization, astrophysical sensitivity, or physical
novelty.

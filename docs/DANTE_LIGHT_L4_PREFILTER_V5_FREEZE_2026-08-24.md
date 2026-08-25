# DANTE-Light L4 prefilter v5 outcome-blind freeze

Date: 2026-08-24

Status: **FROZEN IDENTITY-ONLY; CONFIRMATION SEALED; NO ROUTING**

## Scientific object

V5 tests whether either of two compact students can safely approximate the
continuous exact-DANTE novelty score before the expensive Q-transform/DINO
path. The raw 1-D depthwise architecture is primary and the complex-STFT
architecture is the sole comparator. Both reuse the exact proxy shapes already
benchmarked in v4; wavelet scattering is excluded after its negative cost and
maintenance feasibility result.

The target is a per-detector standardized continuous teacher score, with the
standardization fitted on training only. One H1/L1 model is trained without a
detector indicator; final routing thresholds are detector-specific. Five
deterministic replicates are required and every promotion gate is applied to
the worst replicate. A PASS is evidence of surrogate fidelity and safe routing
within this contract, not independent physical classification.

## Frozen identities

Per detector, the O4a raw-block allocation is:

| partition | detector/GPS blocks | background windows per block |
|---|---:|---:|
| training | 1,200 | 8 |
| development | 300 | 1 |
| confirmation | 300 | 1 |

This yields 19,200 training background windows and 600 background windows in
each of development and confirmation. The latter are realistic CBC-CAT1 shadow
traffic, not a claim of morphology-clean noise.

Every development and confirmation detector stratum contains 60 DANTE-ROBUST
examples, 60 examples for each of Blip, Koi Fish and Scattered Light, and 90
injections for each of three legacy systems plus the new aligned-tidal NSBH
stress population. No detector/GPS block crosses train, development and
confirmation. The DANTE-ROBUST cohort remains entirely `Family_01`; therefore
a later PASS would not establish safety for other DANTE taxonomy families.

The manifest contains 22,800 identity-only rows. Its digest is
`bd3f5acec8d992e878581928aabf51df2303dc2c476fb330d6606d33969cfd85`.

## NSBH scope

The legacy `IMRPhenomD` 10+1.4 solar-mass point-particle control is retained
without pooling it with the new population. The new control uses
`IMRPhenomNSBH` over the preregistered aligned-spin tidal box:

- black-hole mass 5--20 solar masses;
- neutron-star mass 1.2--2.0 solar masses;
- black-hole aligned spin -0.5--0.75;
- neutron-star aligned spin **fixed to zero**;
- neutron-star tidal deformability 100--1,000;
- five distance strata, with 18 Latin-hypercube trials per distance,
  detector and partition.

The injection ledger contains 1,440 trials and verifies one Latin-hypercube
occupancy per intrinsic dimension and cell. Precession and waveform-systematic
robustness outside this box are explicitly out of scope.

## Gates and confirmation seal

Each protected detector/morphology stratum must satisfy point retention at
least 0.90 **and** a 95% Wilson lower bound at least 0.80. At true retention
0.95, 60 examples give a gate-pass probability of 0.9213 and 90 examples give
0.9855. The 300-block confirmation background has worst-case Wilson half-width
0.05622; the minimum even count meeting the 0.06 target is 264.

Operational gates are background-call reduction at least 50% (a product
requirement), detector-specific Spearman correlation at least 0.90 with
block-bootstrap lower bound at least 0.85, and a strictly positive lower 95%
block-bootstrap bound for mean paired net compute saving. No prospective power
is claimed for the net-saving gate because no outcome-blind effect-size and
block-dependence distribution was assumed.

Unlike v4, confirmation therefore protects not only retention but also teacher
scores, student outputs, background routing decisions, paired prefilter and
avoidable exact-path costs, fidelity, and the block-bootstrap cost-benefit
endpoint. The access ledger has zero entries. Opening requires a receipt bound
to the protocol, manifest, model and model code, thresholds, teacher contract,
paired-cost contract, injection generator, replicate selection and verifier.
Confirmation cannot authorize O4b access or runtime routing.

## Reproducibility anchors

- power artifact digest:
  `777414a7f0ecff120617002569d273e08f5a1f69958c0f6f2de2c708c432b5f7`;
- protocol digest:
  `b30a60b06c3c7b7efd3a08a8fd738b3459e64ba7d39cda46a686e8486a8af47f`;
- seal digest:
  `30710d617c5c5ae25b243d406704cced2860dd36d2f262d6fef42b914cca81cd`;
- code freeze commit:
  `377f8388877e50720d7cf179965be8d398f74879`.

The next increment may create training targets and fit the frozen arms only
after binding the deterministic training implementation and injection
generator digests. Development, confirmation and O4b outcomes remain unopened
at this checkpoint.

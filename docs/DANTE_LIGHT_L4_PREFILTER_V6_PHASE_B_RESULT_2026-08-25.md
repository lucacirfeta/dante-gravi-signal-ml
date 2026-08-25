# DANTE-Light L4 v6 Phase-B screening result (2026-08-25)

Status: **PHASE B COMPLETE; PHASE C LOCKED; V6 NOT READY**

## Decision

The frozen five-arm Phase-B matrix completed for all five replicates without a
numerical failure.  The selected screening arm is
`teacher_top_fraction_equal_gradient_ranknet`, but its worst
detector-by-replicate internal-validation Spearman correlation is only
`0.383779623757681`, below the pre-registered `0.90` Phase-C unlock gate.
Consequently:

- `phase_c_unlock_allowed` is `false`;
- Phase C, Phase D, morphology labels, and O4b remain unopened;
- no arm is confirmed and no routing component is promoted;
- the bounded result is `V6_NOT_READY`, not a relaxed PASS.

The verified compact result is
`artifacts/dante_light/prefilter_l4_v6_training/phase_b_screening_summary_v6.json`
with artifact digest
`65c564b7ea6ed3caff0e4f7d39ee73e4099f097b1b273858117f79263274d6c8`.

## Frozen population and provenance

Phase B used 180 fresh O4a background blocks per detector, split before
outcome access into 144 fit and 36 internal-validation blocks per detector.
Each block contributed eight windows.  The teacher ledger contains 2,880
native-O4a scores and has digest
`dd5e701b0b562484cec37e0f8f14272fe2ce992fbaa3bed6aabb8dbc50627db3`.
The training contract digest is
`d6115051eff7b0f446956a78649fcb5893a3e9ac217df70461e175e74a5b2a79`.
The exact teacher replay check reproduced one hash-selected H1 and one L1
sample bit-for-bit in the serialized float32 score, image hash, clean-strain
hash, and raw-strain hash.

No Phase-C, Phase-D, O4b, or morphology-label row was accessed by the raw
cache, teacher, contract freeze, training, selection, or verification stages.

## Results

All values below are internal-validation results.  The primary screening
quantity is the minimum Spearman correlation over both detectors and all five
replicates.

| Arm | Worst Spearman | H1 range | L1 range | Worst SmoothL1 |
|---|---:|---:|---:|---:|
| global average + SmoothL1 | 0.358742 | 0.358742--0.379242 | 0.370454--0.406772 | 0.137024 |
| teacher top fraction + SmoothL1 | 0.362540 | 0.373293--0.393082 | 0.362540--0.425060 | 0.134069 |
| attention MIL + SmoothL1 | 0.325629 | 0.325629--0.399058 | 0.327516--0.382094 | 0.075391 |
| teacher top fraction x2 + SmoothL1 | 0.357519 | 0.388286--0.398625 | 0.357519--0.401190 | 0.117803 |
| teacher top fraction + equal-gradient RankNet | **0.383780** | 0.383780--0.408867 | 0.394544--0.471011 | 0.211207 |

The equal-gradient arm improves the frozen worst-cell rank endpoint by about
0.025 absolute over the unchanged global-average control, but remains more
than 0.51 below the unlock threshold.  This is not a marginal gate miss.

The attention-MIL arm obtains the smallest pointwise SmoothL1 error while
having the lowest worst-cell Spearman correlation.  This independently
reproduces the v5 diagnosis that pointwise score accuracy and ordering
fidelity are not interchangeable endpoints.

For the equal-gradient arm, every replicate completed all 3,600 frozen
training steps.  The median detached value-to-rank gradient-norm ratio ranges
from 13.11 to 16.84 across replicates, while the mean component-gradient cosine
ranges from -0.0031 to 0.0068.  Thus the pre-Phase-B decision not to use a
fixed `lambda=1` was justified mechanically: the two unbalanced gradients
have very different scales and are nearly orthogonal on average.  Equal
gradient normalization made the rank component operative, but it did not
recover the required teacher ordering.

## Scientific interpretation

Phase B falsifies the narrow successor hypothesis tested here: matching the
teacher's top-fraction aggregation, doubling this small encoder's width,
adding attention MIL, or combining SmoothL1 with within-block RankNet under
the frozen equal-gradient rule is insufficient to distill the native DANTE
score ordering into these cheap raw-strain students.

It does **not** establish that all knowledge distillation, all rank-aware
learning, or all cheap cascades are impossible.  In particular, it does not
test a substantially larger temporal representation, intermediate teacher
representations, a separately frozen selective-deferral task, or a student
with access to the teacher's time-frequency representation.  It also does not
measure protected-morphology retention or operational compute saving, because
the prerequisite fidelity gate failed before those stages were opened.

The absence of numerical failures and the consistency of low Spearman values
across detectors and replicates make an infrastructure or favorable-seed
explanation implausible.  The negative result is therefore scientifically
informative: within the audited compute budget, architecture/pooling changes
and a mechanically balanced rank loss do not bridge the representation gap
between whitened 1-D strain and the DINOv2/VQ/MIL teacher.

## Next checkpoint

Do not unlock Phase C or retune these five arms on the same Phase-B outcomes.
Any successor requires a new, outcome-blind design and fresh training
identities.  The technically defensible options are:

1. stop score imitation and formulate selective deferral as a separate task,
   with its own label boundary and independent confirmation;
2. test a materially richer but still cost-audited student representation,
   rather than another small pooling or loss variant;
3. distill intermediate teacher structure only if the expensive upstream
   representation is not required at inference, otherwise the cascade loses
   its compute rationale.

Choosing among these changes what is measured and how it is validated.  It is
a new scientific checkpoint, not an implementation continuation of Phase B.

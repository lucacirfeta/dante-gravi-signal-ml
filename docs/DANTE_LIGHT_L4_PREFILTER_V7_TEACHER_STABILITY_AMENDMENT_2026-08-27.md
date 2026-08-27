# DANTE-Light L4 prefilter v7: exact-teacher stability amendment

Date: 2026-08-27

Status: frozen and verified before `threshold_search`

Decision on `threshold_search`: not authorized

## Why the amendment is required

Four identities sampled historically as native-O4a positives changed score when
recomputed by the current fail-closed exact path. The native O4a reference-index
SHA256 is unchanged, so reference-index drift is excluded. The available
historical evidence does not preserve the complete raw/context input and full
teacher identity needed to prove one exact cause. The historical candidate path
also permitted incomplete whitening context within an edge tolerance, whereas
the current exact path rejects incomplete context. A July transition audit
reproduced 58 of 60 retained cases within `4.4e-7`; the two failures were tied to
refetched/incomplete local blocks. These facts support a raw/context and
fail-closed-path explanation, but do not prove it for the four v7 identities.

The methodological consequence is independent of that root-cause attribution:
every protected v7 partition must be scored against the same fully identified
teacher function used at training.

## Frozen contract

The contract is
`config/dante_light_prefilter_v7_teacher_stability.json`. It binds:

- both primary and native reference indices, including SHA256 and array shapes;
- DINOv2 repository revision, local source-tree digest, weight-file SHA256 and
  byte size;
- the representation/preprocessing contract and the exact scorer, patch scorer,
  data-loader and preprocessor source references;
- Python, NumPy, PyTorch, SciPy, GWPy, Matplotlib, Pillow, CUDA runtime, GPU
  identity/capability, float precision and deterministic-algorithm policy;
- the existing v7 training ledger, compact targets, identity manifest,
  confirmation seal and training summary.

The training-only canary contains eight deterministic identities: two from each
detector by sampling role (`background`, `teacher_positive`). Selection uses a
SHA256 priority fixed by the contract. For each identity the guard requires exact
equality of raw-strain, clean-strain and rendered-image SHA256 values and of the
float32 teacher-score byte representation. No search, calibration, confirmation
or O4b identity contributes to this canary.

## Baseline verification

The saved receipt is
`artifacts/dante_light/prefilter_l4_v7_stability/teacher_stability_baseline_v7.json`.
The full GPU canary passed on all eight identities with zero protected rows
accessed. The structural verifier also validates the saved receipt on a normal
checkout.

- contract digest:
  `52adb081e73c384e831c7988513b900da3e934189553402e8fdcc871d96c6934`
- exact-teacher fingerprint digest:
  `bf1426fcba39672de67ef9c2b2f85fdb21aa4b64d4715ed893e44ce933682deb`
- baseline receipt digest:
  `15059ee970147dbf2cb54fa371557a1c0ce7da1277888dc732a396da306f53aa`

These digests must be regenerated together if an explicitly reviewed teacher
contract changes; changing one is not a repair for a mismatch.

## Protected-stage rule

Immediately before the first row of each of `threshold_search`,
`risk_calibration` and `confirmation` is read, the guard must:

1. verify the frozen fingerprint and all source/data references;
2. recompute the training-only canary;
3. write a stage-specific digest-closed receipt with zero prior partition rows;
4. bind the receipt digest into the protected-stage audit trail.

Any mismatch or any evidence that the partition was read before the check gives
`STOP_NO_ACCESS_NO_RETUNE`. The partition remains closed; no alternate teacher,
threshold adjustment, canary replacement or retuning is allowed. Confirmation
unlock additionally requires the complete receipt chain for search, calibration
and confirmation.

## Scientific boundary

This amendment establishes reproducible identity and stability of the exact
teacher within the declared runtime and training-only canary. It does not explain
the four historical discrepancies with certainty, validate the student,
authorize `threshold_search`, select a routing threshold, establish safe
retention or compute saving, or open calibration, confirmation or O4b.

# Fresh bounded scoring runtime: decision required

## Observed blocker

After08.29 the author requested bounded integration of the verified context
provider with the existing encoder/index/scorer. The strict preflight of the
profile's unchanged O4a protocol/runtime stopped before any score calculation:

`STOP_ENVIRONMENT_MISMATCH: corrected O4a scoring requires the frozen WSL runtime`.

Correct API invocation with `require_current=True`: observed OSexit1.
An initial wrong keyword `require_current_environment` raised TypeError before
validation; corrected to the declared existing API, no code modification.

Independent read-only field comparison: observed OSexit0.

| Field | Frozen | Current |
|---|---|---|
| `cuda_device.driver_version` |610.74 |617.14 |
| `environment_digest` (derived) |48c20ee7ffe39f4cab10e959865691ca2afb65225344fa105d186acf491ff77a |1712a646ca3d1e58aa8fe77799ba2a70d8f98593a94847587ece8a53928d29e9 |

Every other field in the captured runtime matches. This comparison does not
prove numerical driver equivalence. The original runtime file remains SHA
`a28adee4850a288ab5e532bb1ba48d5efe5fc3a50493320934c793f1190f6cb2`,
and the protocol remains SHA
`d88535676a73301c329e3f942a140b6557c6499a6fb2fc66eb966f4a7bb875dc`.

The existing canonical provenance amendment uses driver616.92, not today's
617.14. The unmodified five-test O4a runtime suite returned **4 PASS/1 FAIL**,
OSexit1,10.52s: the host/amendment test fails during current-runtime validation.
No test was skipped, weakened or edited to hide the drift. This is a specific
environment-sensitive failure, not a failure of the preceding28-context
preprocessing/installation receipt.

## Offline inputs verified without inference

Artifact-only inspection completed OSexit0. An initial missing artifact-id
argument raised TypeError before inspection; rerun uses the ID from the parent
representation, not an invented model choice. Verified:

- Weights: `/home/atafe/.cache/torch/hub/checkpoints/dinov2_vits14_reg4_pretrain.pth`,
  SHA `f433177089a681826f849f194ece3bb48f4d63fb38d32fc837e3dc7a4e5641fb`.
- Source tree: pinned local DINOv2 revision7b187bd4df8efce2cbcbbb67bd01532c19bf4c9c,
  Python tree SHA `ca377bf21900d316a2c17dbff04b0e01d44770fe2706becb94a79ac3b60b74ef`.
- Primary index: `E:\dante_cache\dante_light\reference_artifacts\v1\data\reference\patch_compressed_index_o3b.npz`,
  SHA `9053477ed2f30ed866fc42ff32265957e6a0eb93238032359f5e45e2f032bb7c`.

No download, model load/forward, patch token calculation, score, threshold,
candidate label or scientific outcome was generated. No productive factory,
original runtime contract, driver, dependency or historical artifact changed.

## Why the existing waiver does not resolve this gate

`config/dante_workflow_o3a_retained_driver_waiver_v1.json` records the author's
`lascia perdere la versione nvidia` decision with scope
`explicit_opt_in_read_only_retained_O3a_evidence`. Its boundary explicitly says
`fresh_scoring_authorized=false` and `numerical_driver_equivalence_proved=false`.
Extending that waiver to fresh encoder/scorer measurement is a new validation
decision; neither `require_current=False` nor a silently overwritten fingerprint
is an acceptable substitute.

## Alternatives for the author

**A (recommended):** authorize a separate versioned qualification of today's
runtime for this NEW bounded numerical integration gate. Freeze the actual
fingerprint, weights/index/source/input receipts before measurement; test
independent scoring algebra and replay. Preserve every historical contract and
result. No claim of driver equivalence, no historical threshold/shard transplant,
no productive calibration or O4b launch. Further productive/multi-run runtime
acceptance remains a separate gate.

**B:** restore the exact environment named by the selected frozen contract,
then repeat its existing strict preflight. No rollback or driver installation
is performed without explicit direction.

Executor stops at this decision; verifier marks the gate blocked, not PASS.
Only plan/checkpoint/STATE/JOURNAL documentation changed, local commit only.

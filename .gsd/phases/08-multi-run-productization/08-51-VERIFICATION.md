# 08.51 Verification evidence

## Pre-run

- Final new fixture suite: WSL Ubuntu dante_env, `pytest tests/test_cw_stage_c.py -q`,
  actual OS exit0, **16 passed in1.83s**. No real strain/model inference in tests.
- Ruff lint on new module/CLI/tests: actual OS exit0, All checks passed.
- Format corrections and reviewer fixes preceded final tests and source freeze.
- No real-run exit or scientific PASS is asserted at this checkpoint.

## Scope

Existing Stage A synthetic paired uint8 RGB, all16baseline+2880single arms.
Unchanged DINO/index/scorer diagnostic; retained tokens and observed metrics.
Parent summary/verifier hash pins protect historical metadata; new pre-forward
inputs.json explicitly records newly observed receipt bindings, not an old seal.
Dedicated ext4 output, offline cached model, no flags/thresholds/equivalence,
real-dose anchoring, StageB/O4b or 16k/reference production qualification.
Native calibration verifier exit254 is preserved, not retried or called PASS.

## Actual execution and post-run evidence

- Freeze commit5b16082b96cbd3493e7668bb67329d501801c25f before one launch.
- Terminal49628 final object exit_code0; durable supervisor CONTROLLER_PID411,
  RUN_EXIT_CODE0. Summary COMPLETE_DESCRIPTIVE_SYNTHETIC_INFERENCE_ONLY.
- Output /home/atafe/dante_bench/cw_stage_c_20261007/run_v1, Linux ext4.
  SummarySHA6ffb8ad691e16c8862c5112aed1c91eae9b00e2c9cb374e3415f4017ccf61aac.
- Main2896inputs/2880pairedarms/16baselines,120baselinepairs,9re-encodes,
  2905tokenfiles. Progress2896/2896. No failure/partial/tmp/lock or activecontroller.
- Read-only retained artifact check, terminal97358 actualOS0:
  RETAINED_ARTIFACT_CHECK_OK counts=2896/2880/16/120/9 token_files=2905
  sampled_metric_recomputations=6 no_second_inference.
  Six summary-linked artifact SHA and all token SHA verified; all main token
  float32/1369x384/finiteness checked. Newconfig/module/script, pinnedfiles,
  eighteen inherited scientificpins and parent summary/verification unchanged.
  Six token metric roundtrips use recorded norm/bound relation, not an
  independent scientific oracle or a second numerical model replay.
- Separate descriptive arithmetic inspection actualOS0: 512/512 inbanddose0.01
  nonzero and above observed three-baseline repeatmax2.682209e-7;
  medianabs1.5534460544586182e-4, maxabs2.9364824295043945e-3.
  All2880arithmeticboundexcess0. No statistical acceptance or flag applied.
- Final standalone post-run pytest newfixture16passed/1.81s/actualOS0;
  Ruff3filesPASS/actualOS0. Earlier combined post-run invocation16passed/1.86s;
  final standalone terminal object confirms pytest exit independently.
  No previously closed large suite repeated. Stderr three upstreamxFormers
  warnings only. Full measured runtime and source/model provenance in summary.
- Result limitations/selected phase tables recorded in
  docs/DANTE_CW_STAGE_C_RESULTS_2026-10-07.md.

## Parallel report

docs/DANTE_O4B_READINESS_CHECKPOINT_2026-10-07.md, read-only evidence inventory.
No execution or approval of its open scientific choices.

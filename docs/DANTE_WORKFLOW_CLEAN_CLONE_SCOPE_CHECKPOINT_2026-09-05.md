# Clean-clone scope checkpoint — 2026-09-05

Status: decision required before implementing the bounded scientific smoke.
This is an intermediate checkpoint, not the final productization report.

## Observed evidence

A fresh local Git clone of branch `codex/dante-workflow-productization-v1`
at `8c5c2ee` was created with `--no-hardlinks --single-branch`. No raw data,
reference NPZ files, or private caches were copied into it. Validation paths
were outside the clone. The existing Windows Python environment was used;
this was **not** a fresh dependency installation or remote-download test.

- `run_dante_workflow.py plan`: PASS; all 15 stages planned.
- `preflight`: PASS, stage `VERIFIED`.
- repeated `preflight`: PASS, `SKIPPED_VERIFIED`, unchanged run key.
- `verify`: expected refusal, exit 1, `required stage is not verified: ACQUIRE`.
- clone Git status remained clean. No scientific stage was launched.

Local evidence directory:
`C:/Users/atafe/AppData/Local/Temp/dante-workflow-clean-15fd508199cc41ff95fe3be208a1513b-validation/`.
Run key: `404d2268ae9d52222b253e93c39ec8d4a1877f7ae84e14c859987076c16fff60`.

## What the current adapter actually supports

- `PREFLIGHT` delegates to `verify_dante_light_release.py --stage operational`.
  Its PASS verifies repository release evidence, not readiness of an arbitrary
  machine/data directory for corrected O4a scientific execution.
- `ACQUIRE` delegates to `acquire_missing_calibration_inputs`: it downloads
  frozen missing calibration intervals, not the entire base O4a raw archive.
- The context reader separately consumes the frozen raw manifest under
  `raw_root`; that archive remains an external prerequisite.
- `SCAN` and its verifier require the complete frozen population: 401,442 H1
  and 409,809 L1 identities. The CLI has no bounded subset switch.
- Scientific execution is bound to the canonical WSL/CUDA runtime. A CPU
  smoke cannot be described as equivalent scientific reproduction without
  separately defined validation.

Sources: `src/dante_workflow/adapters/o4a_corrected.py`,
`src/dante_light/o4a_corrected_execution.py`,
`config/dante_o4a_corrected_protocol_v4.json`,
`config/dante_o4a_corrected_runtime_v1.json`.

## Decision needed

The P5 phrase "bounded public smoke" does not yet define a smaller scientific
population or a separate adapter. Quietly reducing counts or treating a
synthetic full-DAG test as complete O4a reproduction would violate the plan.

Recommended: separately freeze a public technical smoke scope with deterministic
outcome-blind input selection and existing reference/scoring components; no
new threshold estimation, native cohort construction, or scientific conclusions.
Retain full-DAG orchestration/recovery tests as explicitly synthetic evidence.
Document that this combination is not a real-data end-to-end verification of
all 15 scientific stages. Release acceptance must retain that limitation.

Alternative: reproduce the entire frozen O4a chain in a fresh installation,
including provisioning all required raw inputs and the canonical runtime.
This preserves the complete scientific scope but is not a short smoke test.

No smaller population, new smoke adapter, altered gate, or release acceptance
change has been implemented. P5.1 and P6 remain open pending this scope choice.

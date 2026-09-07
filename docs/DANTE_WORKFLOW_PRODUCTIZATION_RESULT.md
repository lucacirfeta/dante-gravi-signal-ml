# DANTE workflow productization v1 — release result

Status: **P6.1 machine verification PASS; human usability acceptance pending**.

This checkpoint productizes the already frozen corrected-O4a analysis. It does
not recompute adopted scientific stages, change any scientific configuration,
or create a discovery or real-time alerting claim.

## Release identity

- Workflow: `dante-o4a-corrected-productization-v1`
- Run key: `3c9ad0765b4d1f9f9a49cf105ca223058aafdba42ac25793d0ecff1d1d384e94`
- Source commit used to derive the run identity:
  `b14f4384e00338ecaf3335926018f07b5b40de48`
- Contract digest:
  `1d7270c0bcd15b3c344f94bb37fe82033b67bf4ad12615bb50b5efab43422cdd`
- Artifact graph digest:
  `188a93c5b73cac50987e208f289729f4b17650e7f82fd0d91ecb1b7a736049fa`
- Receipt self-digest:
  `3b062e473e70e348ba5f39cbca17676cf63eaa575ea1d95639280bd664440aa4`
- Receipt file SHA-256 (runtime and versioned bytes are identical):
  `a2061ffbd96a25421968bfc0fd14798a72e31152e50e4481aa7f1c6a825d9d86`
- Derived report SHA-256:
  `3711b278b974cf0da2206b0136d5b26250e61c6492e2a562f66dbabf2298d9e2`

The versioned receipt is
[`artifacts/dante_workflow/productization_v1_release.json`](../artifacts/dante_workflow/productization_v1_release.json).

## Acceptance evidence

- Receipt self-verification: `PASS_VERIFIED_WORKFLOW`.
- Frozen graph: 15/15 stages `VERIFIED`; no incomplete stage and no recorded
  workflow failure.
- All scientific stage modes are `ADOPTED_VERIFIED_EXISTING`: the existing
  stage verifiers were replayed, while scientific calculation commands were
  not rerun.
- Index-consumption manifest: exact match.
- CLI and the actual Waitress UI resolved the identical content-addressed run
  key above after the UI was launched from a separate UI-only Python
  environment and the worker was bound to the scientific Python environment.
- UI API: worker `IDLE`, next stage `COMPLETE`, 15 stages visible and verified.
- HTTP checks: dashboard `/` returned 200; bound `/report` returned 200 and
  contained the exact run key.
- Browser inspection confirmed the human-facing dashboard, path selection,
  launcher preflight, immutable scientific contracts, verified logs and
  artifacts, and the complete 15-stage DAG.
- The temporary UI process and browser tab used for acceptance were stopped
  after validation.

Installation, startup, clean-clone CPU smoke, CLI/UI byte parity, detached
worker survival, interruption/recovery behavior, and failure injection were
already accepted in the preceding P5 checkpoints:

- [`DANTE_WORKFLOW_FRESH_INSTALL_RESULT_2026-09-06.md`](DANTE_WORKFLOW_FRESH_INSTALL_RESULT_2026-09-06.md)
- [`DANTE_WORKFLOW_UI_CHECKPOINT_2026-09-05.md`](DANTE_WORKFLOW_UI_CHECKPOINT_2026-09-05.md)
- [`DANTE_WORKFLOW_QUICKSTART.md`](DANTE_WORKFLOW_QUICKSTART.md)
- [`public_smoke_ui_checkpoint_2026-09-06.json`](../artifacts/dante_workflow/public_smoke_ui_checkpoint_2026-09-06.json)

## Scientific boundary

- No score, class, population, threshold, null construction, detector
  semantics, or scientific metric was changed by this checkpoint.
- No metric was manually transcribed into the release receipt and no outcome
  was interpreted by the productization verifier.
- Coincidence and PEM outputs remain diagnostic follow-up products.
- No global-significance, discovery, public real-time, or operational alerting
  claim is authorized.
- Historical, failed, and superseded runs remain preserved.

## Remaining gate

The automated portion of P6.1 is complete. A human must still confirm that the
bounded workflow can be operated from the documented UI/quickstart without an
undocumented expert-only choice. Until that acceptance is recorded, the plan
remains `IN_PROGRESS` and P6.2—the separate architecture-paper branch—must not
start.

### Human usability attempt — 2026-09-07

The first human attempt is `FAIL_USABILITY_GATE`. The user could not determine
which action started work, whether CPU or CUDA was appropriate, the current
phase or process state, how to resume, where detailed logs lived, or what the
receipt and report represented. The shared `/mnt/c` checkout also surfaced its
tracked-clean requirement as an HTTP exception instead of an actionable setup
page. No scientific worker was launched; the UI server was stopped and ports
8765/8766 were verified free.

P6.1 remains open while the public-smoke UI and quickstart add a guided device
recommendation, explicit start/resume action, durable phase progress, bounded
ETA, live and detailed logs, explained report/receipt links, and actionable
clean-checkout recovery. A new human attempt is required after automated and
visual verification of that revision.

The remediation revision was subsequently verified with all 120
`test_dante_workflow_*` tests passing, Ruff passing on the changed Python, a
successful JavaScript syntax check, and browser inspection of both the initial
and completed guided states. The visual check covered device recommendation,
the explicit start action, phase progress, completion, log links, and the
separate readable-report and technical-receipt actions. These checks validate
the implementation; they do not replace the outstanding human usability
retest, so P6.1 remains open.

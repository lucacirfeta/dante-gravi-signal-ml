# Public technical smoke result — 2026-09-05

**PASS for the approved technical smoke only.** No corrected O4a rerun,
recalibration, scientific promotion, or complete product-release claim.

## Observed run

Fresh HTTPS clone, separate empty Torch cache, no copied raw/reference cache.
The reference bundle and pinned model were downloaded; strain and CAT1 used
GWOSC. Python/dependencies came from the existing isolated WSL UI-validation
environment backed by the scientific environment, not a fresh pip installation.

- Tested checkout: `639b918423ff96153820e4fed641aaa4ee60837f`, tracked-clean.
- Device: WSL CUDA; CPU execution was not tested.
- Two windows: first background identity per H1/L1 in existing detector/GPS order.
- Existing canonical/shared-engine comparison: **max score delta 0.0**,
  within the unchanged `2e-7` bound; zero disposition mismatches, drops or failures.
- Separate `--mode verify` and repeated `--mode local` both returned
  `SKIPPED_VERIFIED_TECHNICAL_SMOKE`, with the same run key and no scoring rerun.
- Full local receipt hash and path are versioned in
  `artifacts/dante_workflow/public_smoke_checkpoint_2026-09-05.json`.

The receipt binds the pair evidence, report, bundle, engine checkpoints, logs,
manifests and records. Failed/incomplete attempts are retained separately; retry
reuses complete hash-verified engine attempts, but reruns incomplete engines.
This is not evidence of per-window crash resume for the legacy replay runner.

## Defect caught before acquisition

The first smoke config in `a7a8ff8` pinned the local CRLF bytes of
`config/reference_artifacts.json`; Git stores LF bytes. The fresh clone correctly
refused it before scientific execution. `639b918` pins the canonical Git digest
already used by the corrected protocol. A regression test compares every smoke
reference pin with its actual Git blob. The main working copy was normalized
to its existing LF attributes; no versioned scientific content changed.

The failed first launch is not a successful reproduction. No verifier bypass
or change to numerical tolerance was used to obtain the later PASS.

## Remaining work

Regression evidence: Windows **96 passed** (21.30 s); WSL **95 passed,
1 Windows-only skip** (48.94 s), all `test_dante_workflow*.py`.
The targeted WSL smoke/recovery/state/orchestrator suite passed all 39 tests.
Ruff and `git diff --check` passed.

- Packaged UI/CLI acceptance, with the technical smoke clearly distinguished
  from the full scientific O4a adapter.
- Human acceptance and final resoconto. No paper work starts from this checkpoint.

Fresh CPU installation and the expanded storage-boundary recovery matrix passed
on 2026-09-06. Their separate evidence is recorded in
`DANTE_WORKFLOW_FRESH_INSTALL_RESULT_2026-09-06.md` and the updated recovery
checkpoint; they do not alter or broaden this CUDA smoke claim.

The technical smoke uses historical reference indices/epochs and the existing
paired replay. Its decisions are not corrected O4a classifications, and this
two-window exercise establishes neither performance generalization nor global
statistical significance.

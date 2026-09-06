# Technical public smoke (not full corrected O4a)

Scope approved 2026-09-05: test public acquisition and existing scoring without
recalibration. The immutable smoke config selects the earliest background replay
identity per detector using the existing detector/GPS ordering. It does not
select on scores. This uses the legacy paired Light replay, **not** the corrected
15-stage O4a scientific chain. Historical replay decisions must not be presented
as corrected O4a classifications.

## Prepare a separate checkout

Clone branch `codex/dante-workflow-productization-v1` from
`https://github.com/lucacirfeta/dante-gravi-signal-ml.git` into a new directory.
Do not copy local raw data or reference caches. Keep tracked files unchanged.
Use Python 3.11 with the portable CPU lock (`requirements-cpu.txt`) for the
documented CPU path. The optional UI uses `requirements-ui.txt` in addition and
is not needed for this CLI smoke. The CPU lock is an installation/replay
environment, not a promise of exact historical CUDA environment reproduction.

## Run

From that checkout, with its chosen Python environment:

```shell
python scripts/run_dante_workflow_clean_clone.py --mode plan --device cpu
python scripts/run_dante_workflow_clean_clone.py --mode local --device cpu
python scripts/run_dante_workflow_clean_clone.py --mode verify --device cpu
```

For a CUDA-capable environment, replace `cpu` with `cuda` in all three commands.
Each device/environment has its own identity. CPU/CUDA equivalence is not claimed.
The canonical and shared-engine runs must satisfy the **existing** paired replay
verifier; its tolerance is not changed for this smoke.

The published reference bundle is downloaded with its frozen SHA-256 and installed
without overwriting divergent files. Model source/weights use the existing pinned
loader. Strain and CAT1 checks use GWOSC; no local raw mirror fallback is allowed.
First-run downloads and scoring may take minutes; each engine subprocess has a
config-defined timeout, not a performance guarantee for the complete workflow.

## Outputs and retry

Outputs are isolated under `artifacts/dante_workflow/public_smoke_v1/<identity>/`.
Success creates `technical_receipt.json`, `paired_replay_evidence.json`, and
`report.md`. A live OS lock prevents concurrent duplicate smoke executions.

Repeat `--mode local` to retry. Verified engine attempts are hash-checked and
reused. Incomplete/failed attempts remain in unique directories; an incomplete
engine is rerun in a new attempt, **not resumed per window**. Completed smoke
receipts are rechecked before returning `SKIPPED_VERIFIED_TECHNICAL_SMOKE`.
Changed artifacts fail closed; do not delete or hand-edit receipts to bypass it.
Failure details are in the attempt's `failure.json`, `stdout.log`, and `stderr.log`.

## Optional local UI for the same smoke

Install the optional UI lock into the same isolated environment, then launch:

```shell
python -m pip install -r requirements-ui.txt
python scripts/run_dante_workflow_ui.py --public-smoke
```

Open `http://127.0.0.1:8765`, select CPU or CUDA, and use **Run or resume**.
The web handler starts the exact CLI command above as a detached worker; closing
the browser or UI server does not terminate it. Reloading only reads and
hash-verifies the receipt. The smoke UI does not request private raw/cache paths
and cannot edit scientific configuration. Use the default UI launcher without
`--public-smoke` only for the full frozen 15-stage O4a workflow.

This PASS is not a product release receipt, global significance test, full raw
archive acquisition test, or packaged CLI/UI parity acceptance. The corrected
O4a adapter still requires the full frozen raw archive and canonical runtime.

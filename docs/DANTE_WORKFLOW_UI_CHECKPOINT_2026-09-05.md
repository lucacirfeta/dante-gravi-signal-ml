# DANTE local workflow UI — implementation checkpoint

Status: IMPLEMENTED_COMPONENT_VALIDATION; not a product release.

## Why execution appeared to stop

The failing UI launch test used the pytest process PID as an inert fake
worker. The liveness probe called `os.kill(pid, 0)`. On Windows that operation
terminates the target process, rather than performing the Unix existence
probe. Consequently pytest disappeared without a traceback (`aborted`).
The same idiom also existed in the workflow ledger's process probe.

`5ad5d44` replaces both probes with one shared platform-aware implementation.
Windows uses `OpenProcess(SYNCHRONIZE)`, `WaitForSingleObject(handle, 0)`, and
`CloseHandle`, without signals or termination rights. Unix retains signal 0.
Regression evidence includes a real child which survives repeated probes and
then exits normally. No scientific setting or artifact was changed.

Python reference: https://docs.python.org/3/library/os.html#os.kill

## Implemented surface

- Optional Flask/Waitress loopback launcher: `scripts/run_dante_workflow_ui.py`.
- Allowlisted project, raw, cache, and ledger selection; scientific configs
  are read-only hashes. Native calibration still depends on INDEX's consumed
  window manifest, as specified by the frozen workflow.
- Fifteen-stage status/DAG, launcher checks, and a separate scientific
  preflight action. Launcher READY is not scientific PREFLIGHT PASS.
- Detached CLI worker for start, resume, preflight, and final verification/
  report refresh. The UI never runs scientific stage code inside HTTP handlers.
- Cooperative stop after the current atomic run+verification stage, without
  attempting an incomplete report. Run-key checks prevent stale-page actions
  or a worker silently launching against changed source/path identity.
- A launch reservation remains visible through final report generation.
  Ambiguous parent death before child-PID recording fails closed as
  STALE_LAUNCH, rather than allowing an automatic duplicate.
- CSRF and trusted-host checks, content-security headers, administrative-only
  live logs, and verified-only artifact/log downloads.
- Derived report text is hash-bound to its verified release receipt; HTTP
  access checks the binding, current recorded artifacts, and source logs,
  without replaying scientific commands in the UI process.
- Status polling explicitly marks a lost connection; verified links/logs can
  be refreshed using the visible reload link.

## Verification

Windows command:

```powershell
python -m pytest -q (Get-ChildItem tests/test_dante_workflow*.py).FullName
```

Result: **78 passed in 18.18s** (final regression).

WSL equivalent: **77 passed, 1 skipped in 43.88s** (final regression; the
Windows-only probe test is intentionally skipped). Optional UI dependencies
are isolated in `/home/atafe/.cache/dante-ui-validation-20260905`, outside the
scientific environment. An earlier temporary validation environment under
`/tmp` disappeared after WSL restarted; the final check used the persistent
cache path instead. Both platforms passed the real detached-child/reconnect
test. The scientific environment was not modified.

This includes real process survival after the launcher exits and reconnection
from a new application instance; the child in that test is deliberately inert,
not a scientific O4a job. A separate synthetic 15-stage workflow verifies that
the HTTP report matches the CLI-produced bytes, and that altering the report
removes access. Injected failed-stage outcome strings remain absent from all
public status/log/page responses. Stale forms and untrusted hosts are rejected.

Ruff: **All checks passed**, using the existing WSL lint installation.
`compileall` and `git diff --check`: PASS.

Browser evidence: the actual Waitress server was opened on loopback port 8766
with empty isolated temporary raw/cache roots. AX inspection confirmed all 15
stages and controls. Screenshot at 1265 x 713 showed the dashboard, readable
path selectors, status cards, and the expected fail-closed error. Resume with
no evidence and final verification before completion were refused. No Start
or scientific preflight was executed in this browser check. Test server and
browser tab were then closed.

## Scope still open

1. P5: bounded public clean-clone workflow, installation/quickstart, full
   failure-recovery matrix (network, disk, CUDA/dependencies, worker death).
2. P5/P6: integrated packaged CLI/UI artifact equality on public inputs. The
   inert-worker and synthetic-graph tests above do not establish that claim.
3. P6: release receipt and human usability acceptance, then a separate paper
   branch. No new paper or publication is authorized by this checkpoint.

The older `run_dante_light_clean_clone.py` exercises a paired primary replay,
not the new corrected 15-stage workflow; it must not be relabeled as proof of
full productized O4a reproducibility.

## Development launch

Use a Python environment containing the optional `requirements-ui.txt`
dependencies. Launch inside the chosen OS environment; do not point a Windows
launcher at a Linux executable or reuse a WSL run identity as a Windows run.

```powershell
python scripts/run_dante_workflow_ui.py --raw-root E:/o4a --cache-root E:/dante_cache/dante_light
```

Open `http://127.0.0.1:8765`. `--worker-python` selects an executable available
inside that same OS environment. The default is the UI interpreter. Its
scientific dependency gate must pass before the workflow proceeds. Do not
start a full run just to inspect the dashboard. Do not edit code/config during
an active scientific run. Historical and user-owned `output/` remain untouched.

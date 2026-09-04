# DANTE workflow local UI decision

Status: **APPROVED_AND_FROZEN**

Date: 2026-09-04

Scope: productization only; no scientific computation or validation semantics

## Decision proposed

Use a **local server-rendered web UI built with Flask 3.1.3 and served by
Waitress 3.0.2**, bound to `127.0.0.1` by default. Keep both packages in the
optional `requirements-ui.txt`, outside the frozen scientific runtime.

The UI is a disposable reader/controller over the existing content-addressed
orchestrator. The append-only ledger and worker lease remain the source of
truth. Closing or restarting the browser or UI server must not interrupt,
replace, or acquire the worker lease.

The architectural checkpoint was approved on 2026-09-04. This selection is
frozen for productization v1.

## Frozen boundaries for implementation

- The UI does not import or execute a scientific stage implementation.
- Scientific configs are displayed as read-only paths and digests.
- The UI uses the existing orchestrator and stage verifiers; it does not
  reproduce their logic.
- Outcome-bearing fields stay hidden until the corresponding receipt is
  verified.
- Worker launch/resume occurs in an independent process. The UI can disappear
  while that process continues.
- The HTTP listener binds to loopback only. Remote access, authentication, and
  multi-user operation are outside this release.
- Browser file inputs are not used as arbitrary path selectors. P4.2 will use
  a server-side, allowlisted local path chooser rooted in explicit user
  locations.

## Runnable spike

Install only the optional UI environment:

```powershell
python -m venv .venv-ui
.\.venv-ui\Scripts\python -m pip install -r requirements-ui.txt
```

Run the read-only spike:

```powershell
.\.venv-ui\Scripts\python scripts\spike_dante_workflow_ui.py `
  --raw-root E:\o4a `
  --cache-root E:\dante_cache\dante_light
```

Open `http://127.0.0.1:8765`. The page exposes infrastructure status only.
It reads all 15 stages from the same persisted workflow run used by the CLI.

The benchmark is also runnable on Windows or WSL from any environment that has
the optional requirements installed:

```powershell
.\.venv-ui\Scripts\python scripts\benchmark_dante_workflow_ui_spike.py `
  --raw-root E:\ui-spike\raw `
  --cache-root E:\ui-spike\cache `
  --workflow-root E:\ui-spike\workflow
```

The benchmark acquires a synthetic worker lease, starts and stops the UI twice,
and fails unless both UI instances resolve the same run identity and both UI
exits leave the worker lease intact. It executes no workflow stage.

## Measurements

All measurements are bounded engineering observations, not performance claims.
Each value is one clean-environment observation on the development host.

### Candidate dependency footprint on Windows, Python 3.11.5

| Candidate | Direct packages | Fresh install | Cold process import | Fresh environment | Installed distributions |
|---|---|---:|---:|---:|---:|
| Flask + Waitress | Flask 3.1.3, Waitress 3.0.2 | 3.119 s | 0.280 s | 27.4 MiB | 8 |
| Streamlit | Streamlit 1.63.0 | 32.999 s | 0.473 s | 351.7 MiB | 37 |
| PySide6 | PySide6 6.11.2 | 10.985 s | 0.138 s | 660.3 MiB | 4 |

The environment size includes the fresh virtual environment itself, so only
the between-candidate comparison is meaningful.

### Selected spike behavior

| Runtime | First health response | Reconnect health response | Same run key/directory | 15 stages | Worker lease survived both UI exits |
|---|---:|---:|---|---|---|
| Windows 11, Python 3.11.5 | 537.8 ms | 539.1 ms | PASS | PASS | PASS |
| WSL Linux, Python 3.11.15 | 4687.4 ms | 4661.0 ms | PASS | PASS | PASS |

The WSL run used the repository and optional packages from the mounted Windows
filesystem. The slower observation therefore includes mounted-filesystem Git
identity and import overhead. It is evidence of functional startup and
reconnection, not a cross-platform speed comparison.

Visual inspection in the in-app browser confirmed a semantic heading, run key,
next-stage label, captioned table, and all 15 stage rows. The spike deliberately
has no production styling or controls.

## Comparison

| Criterion | Flask + Waitress | Streamlit | PySide6 |
|---|---|---|---|
| Windows and WSL | PASS in the measured spike | Supported as a browser/server app, not measured here | Cross-platform desktop framework; WSL needs a graphical display path |
| Worker independence | Natural separate HTTP process; measured lease survival | Possible only with strict external-ledger discipline | Possible with a separate worker, but easy to couple to the GUI process |
| Resume/reconnect | Stateless HTTP reads reconstruct from the ledger; measured | Session state is browser-session scoped and scripts rerun on interaction | Must implement persistence and refresh explicitly |
| Packaging | Small optional Python layer; Waitress supports Windows and Unix | Larger transitive environment | Largest binary/runtime footprint and platform-specific packaging |
| Local path selection | Requires a server-side allowlisted chooser | Browser constraints still apply | Best native file dialogs |
| Log/status updates | Polling or server-sent events without changing worker state | Fragment reruns can poll, with framework-specific rerun semantics | Signals/timers plus thread/process coordination |
| Accessibility | Semantic HTML and normal browser tooling | Framework-generated browser UI | Native Qt accessibility, with platform-specific verification |
| Testability | Flask test client plus normal HTTP/browser tests | AppTest plus Streamlit execution model | Headless Qt GUI tests and platform plugins |

## Rejected alternatives

### Streamlit 1.63.0

Rejected for the product UI, while remaining acceptable for disposable
scientific dashboards. Streamlit documents that interaction reruns the script
and that Session State is scoped to each browser session. DANTE already has a
durable, cross-session ledger; adding a second session-state model increases
the risk of accidental ownership or stale controls. Its measured optional
environment was also substantially larger than the Flask spike.

References:

- https://docs.streamlit.io/develop/concepts/architecture/session-state
- https://docs.streamlit.io/develop/api-reference/execution-flow

### PySide6 6.11.2

Rejected for this release despite excellent native file dialogs. Qt for Python
supports desktop deployment, but packaging requires platform-specific freezing
and its measured environment was the largest. A native GUI also adds a second
desktop compatibility surface while the worker already runs across Windows and
WSL. This cost is not justified for a single-user local controller.

References:

- https://doc.qt.io/qtforpython-6/deployment/index.html
- https://doc.qt.io/qtforpython-6/overviews/qtdoc-supported-platforms.html

## Why Flask and Waitress

Flask provides a small, explicit request boundary and a first-party test client.
Waitress is a pure-Python WSGI server documented for both Windows and Unix.
Flask's own documentation requires a production WSGI server even for a private
local deployment, so the development server is not part of the proposed path.

References:

- https://flask.palletsprojects.com/en/stable/testing/
- https://flask.palletsprojects.com/en/stable/deploying/
- https://docs.pylonsproject.org/projects/waitress/en/stable/

## Remaining P4.2 work

1. Move the spike into `src/dante_workflow/ui/` with templates and static
   assets.
2. Add a separate worker-launch/control boundary for `run`, `resume`, and
   controlled stop; never call long scientific work in a request handler.
3. Add allowlisted path selection and preflight feedback.
4. Add stage DAG, verified artifact browser, safe logs, and final-report access.
5. Add outcome-redaction tests, HTTP tests, browser tests, and disconnect/
   reconnect tests.
6. Package a one-command launcher while preserving the separate optional UI
   environment.

## Approval gate

Approval was recorded on 2026-09-04. Flask 3.1.3 + Waitress 3.0.2 are frozen
for productization v1, and P4.2 implementation is authorized. This decision
does not alter the completed CLI, workflow ledger, or scientific artifacts.

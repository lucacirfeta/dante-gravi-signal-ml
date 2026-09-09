# Optional external reproduction checklist

This optional checklist can be used by a future contributor or community
reviewer to validate the bounded public CPU smoke. It is not completed J3
evidence, does not rerun corrected O4a, and must not be interpreted as a
scientific result.

## Requirements

- a person who did not implement the release-candidate changes;
- a WSL/Linux filesystem path outside `/mnt/c`;
- Python 3.11, Git, network access, and sufficient space for the pinned CPU
  dependencies;
- no copied DANTE raw-data mirror, result directory, or reference cache.

## Fresh installation

```shell
cd ~
git clone --branch release/dante-joss-readiness-v1 --single-branch \
  https://github.com/lucacirfeta/dante-gravi-signal-ml.git \
  dante-joss-external-review
cd dante-joss-external-review
git status --short
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-cpu.txt
python -m pip install ".[ui]"
dante-workflow --help
dante-workflow-ui --help
```

`git status --short` must print nothing before execution. If `python3.11` is
not the local executable name, using another command that reports Python
3.11.x is acceptable and must be recorded.

## Plan and guided UI run

First inspect the bounded plan:

```shell
python scripts/run_dante_workflow_clean_clone.py --mode plan --device cpu
```

It must report `SMOKE_PLAN` and
`technical_public_replay_not_corrected_o4a_release`.

Launch the installed UI:

```shell
dante-workflow-ui --repository-root . --public-smoke
```

Open <http://127.0.0.1:8765> and use **Start test**. Confirm without consulting
the implementer that:

- CPU is presented as the portable route and any CUDA recommendation is
  explained;
- the current phase, percentage, approximate ETA, and worker state are visible;
- live output and detailed log links are discoverable;
- the page explains how **Resume test** is used after interruption;
- the final verification result opens separately;
- the readable report and technical receipt are distinguishable and easy to
  locate;
- no scientific threshold, population, score, raw path, or cache path must be
  invented.

Do not deliberately corrupt or delete evidence to test recovery. Stop the UI
server with `Ctrl+C` only after the worker has completed or failed.

## CLI verification and reuse

```shell
python scripts/run_dante_workflow_clean_clone.py --mode verify --device cpu
python scripts/run_dante_workflow_clean_clone.py --mode local --device cpu
```

After a successful UI run, both commands should return
`SKIPPED_VERIFIED_TECHNICAL_SMOKE` for the same run key. A failure is also a
valid review finding; preserve its message and linked `failure.json` rather
than editing the evidence.

## Result to return

Return this small record; do not attach downloaded data or complete logs unless
diagnosis is required:

```text
Commit:
Python version:
Final status:
Run key:
Receipt SHA-256:
Report SHA-256:
Start/resume explanation clear: yes/no
Progress and ETA clear: yes/no
Logs discoverable: yes/no
Report and receipt discoverable: yes/no
Undocumented choice required: yes/no (explain if yes)
Unexpected failure or ambiguity: none/details
```

An external reproduction passes only if the execution verifies and the
reviewer reports no undocumented scientific or path choice. Cosmetic
suggestions may be recorded separately and do not override a failed
reproducibility finding.

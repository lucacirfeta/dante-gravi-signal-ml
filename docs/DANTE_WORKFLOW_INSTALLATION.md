# Installing the DANTE workflow controller

## Scope

The installable `dante-workflow` distribution contains the content-addressed
orchestration library and its CLI/UI controllers. A complete DANTE source
checkout remains required because scientific stage commands, frozen contracts,
and the bounded public replay live under root `scripts/`, `config/`, and
`main.py`.

The wheel does not contain strain data, reference indices, model weights,
corrected-O4a artifacts, or the historical CUDA environment. Installing the
controller is therefore not a scientific recomputation or verification result.

## Base controller

Use Python 3.11 in an isolated environment:

```shell
git clone https://github.com/lucacirfeta/dante-gravi-signal-ml.git
cd dante-gravi-signal-ml
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
dante-workflow --help
```

The base package has no third-party runtime dependencies. It supports schema,
state, planning, status, verification, and orchestration APIs. Commands that
execute scientific stages require the corresponding scientific environment.

Always identify the checkout explicitly when invoking an installed controller
from another directory:

```shell
dante-workflow plan \
  --repository-root /path/to/dante-gravi-signal-ml \
  --raw-root /path/to/o4a \
  --cache-root /path/to/dante-cache
```

Run keys include the selected checkout, its Git state, the workflow contract,
environment-dependent worker command, and configured paths. Changing those
inputs is expected to produce a different identity.

## Portable CPU replay and optional UI

For the bounded public technical smoke, install the pinned CPU environment and
the UI extra into the same environment:

```shell
python -m pip install -r requirements-cpu.txt
python -m pip install ".[ui]"
dante-workflow-ui --repository-root . --public-smoke
```

Open <http://127.0.0.1:8765>. The checkout must be tracked-clean; otherwise the
smoke fails closed because its evidence binds to Git source identity. Detailed
operation, retry, log, receipt, and report instructions are in
[`DANTE_WORKFLOW_QUICKSTART.md`](DANTE_WORKFLOW_QUICKSTART.md).

The source compatibility command remains available:

```shell
python scripts/run_dante_workflow_ui.py --public-smoke
```

Both UI launchers use the same package controller. The UI launches the
checkout's exact worker script and does not translate scientific parameters.

## Full corrected-O4a workflow

The complete 15-stage workflow additionally requires the frozen scientific
runtime, full raw archive, reference artifacts, and cache roots documented by
the workflow contract. It is not a portable demonstration command. Use the
installed controller or compatibility script with the same explicit paths:

```shell
dante-workflow plan --repository-root . --raw-root <raw-root> --cache-root <cache-root>
python scripts/run_dante_workflow.py plan --raw-root <raw-root> --cache-root <cache-root>
```

With the same Python executable and arguments, these two forms must emit the
same plan and run key. Do not proceed from `plan` to execution unless the
required scientific inputs and environment are available and verified.

## Development installation

Contributors may use an editable installation:

```shell
python -m pip install -e .
python -m pytest -q tests/test_dante_workflow_packaging.py
```

The package metadata is prepared for release `3.8.0`. The immutable tag,
GitHub Release, and Zenodo archive must be created only from the final verified
commit at the explicit release checkpoint. The reserved 3.8.0 version DOI is
`10.5281/zenodo.22681395`; it becomes registered only when Zenodo publishes
the archive. Version 3.8.0 must not inherit the historical 3.7.0 DOI.

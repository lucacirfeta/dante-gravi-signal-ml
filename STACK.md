# Technology stack

> Repository map updated 2026-09-09. Exact portable versions are defined by
> `requirements-cpu.txt`; broader historical ranges remain in
> `requirements.txt`.

## Runtime

| Technology | Supported reference | Purpose |
|---|---|---|
| Python | 3.11 | Portable CPU workflow and clean-clone smoke. |
| WSL/Linux | WSL-native checkout recommended | Avoids cross-filesystem line-ending and process-identity ambiguity. |
| Windows | Tested controller/runtime surface | Development and selected workflow regression support. |
| CUDA | Optional, separately identified | Accelerated scientific execution; not assumed equivalent to CPU. |
| Docker | `python:3.11-slim` | Reproducible CPU smoke/test container. |

## Portable CPU dependencies

The lock includes PyTorch 2.12.1 CPU, torchvision 0.27.1 CPU, NumPy 2.4.5,
SciPy 1.17.1, pandas 3.0.3, GWpy 4.0.1, GWOSC 0.8.2, h5py 3.16.0,
Astropy 7.2.0, Matplotlib 3.10.9, seaborn 0.13.2, Pillow 12.2.0,
scikit-image 0.25.2, scikit-learn 1.8.0, UMAP 0.5.12, PyYAML 6.0.3,
tqdm 4.67.1, python-dotenv 1.1.1, SQLAlchemy 2.0.43,
psycopg2-binary 2.9.10, requests 2.32.5, tenacity 9.1.2, and pytest 8.4.1.

`requirements-cpu.txt` is the authoritative machine-readable source; this
summary must not be used as an independent lock.

## Optional UI

| Package | Version | Purpose |
|---|---:|---|
| Flask | 3.1.3 | Loopback-only browser application. |
| Waitress | 3.0.2 | Local WSGI server. |

The UI calls the same workflow/public-smoke controllers used by the CLI. It is
not a separate scientific engine.

## Development tooling

The broader `requirements.txt` declares pytest, Ruff, mypy, and pre-commit in
addition to scientific dependencies. GitHub Actions currently runs the CPU
smoke and immutable-artifact regression checks on Python 3.11/Ubuntu.

## Storage and artifacts

| Technology or format | Use |
|---|---|
| JSON/JSONL | Contracts, manifests, ledgers, progress, receipts, and evidence. |
| SQLite/WAL | Primary scan and selected corrected-O4a stage data. |
| HDF5 | Public/local strain data. |
| NPZ | Frozen reference and index artifacts. |
| Markdown/HTML | Human reports and local UI views. |
| SHA-256 | File identity, contract closure, and content-derived run keys. |

## External services

- GWOSC for public strain and segment metadata;
- pinned DINOv2 source and weights for representation extraction;
- GitHub Releases for the public reference bundle and release source;
- Zenodo for immutable archives and DOI assignment;
- optional NDS2 access for workflows that require auxiliary channels.

## Configuration hierarchy

| File | Role |
|---|---|
| `requirements-cpu.txt` | Portable, pinned CPU environment. |
| `requirements-ui.txt` | Optional UI-only dependencies. |
| `environment.yml` | Conda environment including optional NDS2 clients. |
| `requirements.txt` | Broad historical/development dependency ranges. |
| `config/dante_workflow_productization_v1.json` | Frozen 15-stage productized workflow. |
| `config/dante_workflow_public_smoke_v1.json` | Bounded public technical smoke. |
| `config/reference_artifacts.json` | Hash-pinned public reference asset metadata. |

## Current installation model

The supported workflow is installed as a source checkout: create an isolated
Python 3.11 environment, install a requirements lock, and run the repository
scripts. It is not currently distributed as an importable wheel. Converting it
to a wheel requires an explicit decision about package scope, root-relative
scientific resources, and console entry-point guarantees.

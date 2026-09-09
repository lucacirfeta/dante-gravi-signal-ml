# Architecture

> Repository map updated 2026-09-09. This document separates the bounded
> productized workflow from the historical and experimental analysis code that
> remains in the same repository.

## Overview

DANTE is a repository-oriented Python research application. It contains shared
signal-processing and representation code, several generations of analysis
pipelines, and a productized orchestration layer for the frozen corrected-O4a
workflow. The productized layer records content-derived run identity, durable
stage state, verification receipts, and human-readable reports; it delegates
scientific calculations to versioned stage scripts rather than reimplementing
them.

## System diagram

```text
                         config/*.json
                              |
                              v
CLI scripts ----------> dante_workflow <---------- local Flask UI
                              |
                    schema + orchestrator
                    state + verification
                    adapter + reporting
                              |
                              v
                    versioned stage scripts
                              |
          +-------------------+-------------------+
          v                   v                   v
      src/core          src/dante_light    pipeline generations
          |                   |                   |
          +-------------------+-------------------+
                              v
                external data and local artifacts
```

## Productized workflow

The authoritative graph is
`config/dante_workflow_productization_v1.json`:

```text
PREFLIGHT -> ACQUIRE -> CALIBRATE -> SCAN -> COHORT -> INDEX
                                                   |       |
                                                   +-------v
                                              NATIVE_CALIBRATION
                                                       |
                                                       v
RESCORE -> THRESHOLDS -> CLASSIFY -> TAXONOMY -> COINCIDENCE
                                                       |
                                                       v
                                               PEM -> COMPARE -> REPORT
```

`NATIVE_CALIBRATION` depends on both `COHORT` and `INDEX`; the index dependency
exposes the consumed-window manifest used by the calibration exclusion guard.

### Components

| Component | Location | Responsibility |
|---|---|---|
| Schema | `src/dante_workflow/schema.py` | Validates the exact stage graph, contracts, file references, and policies. |
| Orchestrator | `src/dante_workflow/orchestrator.py` | Computes run identity and executes, resumes, adopts, or verifies stages. |
| Durable state | `src/dante_workflow/state.py` | Append-only attempts, leases, transitions, hashes, and receipts. |
| Corrected-O4a adapter | `src/dante_workflow/adapters/` | Maps workflow stages to existing scientific run and verification commands. |
| Verification | `src/dante_workflow/verification.py` | Replays verifier commands and checks receipt/artifact closure. |
| Reporting | `src/dante_workflow/reporting.py` | Builds the bounded workflow report and release receipt. |
| Local UI | `src/dante_workflow/ui/` | Controls the same CLI semantics and exposes progress, logs, reports, and receipts. |
| CLI launchers | `scripts/run_dante_workflow*.py` | Repository-level plan/run/resume/verify and public-smoke entry points. |

## Other code families

| Area | Purpose | Status relative to productized workflow |
|---|---|---|
| `src/core/` | Data access, preprocessing, model loading, encoding, patch production, and shared utilities. | Shared implementation dependency. |
| `src/dante_light/` | DANTE-Light execution, evidence, corrected-O4a reconstruction, and experimental prefilter work. | Mixed validated and experimental modules; activation is contract-specific. |
| `src/pipeline_v1_legacy/` | Historical analysis pipeline. | Preserved for compatibility and comparison. |
| `src/pipeline_v2_production/` | Production analyses and scientific validation utilities. | Scientific implementation used by selected commands. |
| `src/pipeline_v3_multiscale/` | Multiscale and normalization-leakage experiments. | Separate experimental/research scope. |
| `main.py` | Large historical command dispatcher, including the bounded public replay command. | Repository entry point, not the productized workflow controller. |

## Data and control flow

1. A versioned JSON contract defines stages, dependencies, policies, and
   scientific file hashes.
2. The adapter resolves each stage to an exact run command and verifier command.
3. Repository identity, contract identity, environment, and paths determine the
   workflow run key.
4. The ledger records attempts and permits reuse only after artifact and receipt
   verification.
5. The CLI and UI call the same controller semantics. The UI launches detached
   workers but does not alter scientific configuration.
6. The final report distinguishes executed stages from adopted-and-reverified
   artifacts and keeps claim scope explicit.

The bounded public smoke is a separate two-window technical replay. It downloads
a hash-pinned reference bundle, uses GWOSC-only strain access, and must not be
interpreted as a full corrected-O4a recomputation or release receipt.

## Integration points

| External system | Type | Purpose |
|---|---|---|
| GWOSC | HTTPS/API via `gwosc` and `gwpy` | Public strain and data-quality access. |
| DINOv2 upstream | Git/HTTPS through the pinned model loader | Frozen model source and weights. |
| GitHub Releases | HTTPS | Versioned public reference bundle and software releases. |
| Zenodo | Archival service | Immutable software/evidence records and DOIs. |
| NDS2 | Optional network client | Selected historical or PEM auxiliary-channel workflows. |
| SQLite | Local database | Durable scan and analysis data for corrected-O4a stages. |

## Conventions and boundaries

- Scientific configuration lives in versioned files under `config/`; constants
  are not inferred by the orchestrator or UI.
- Whitening precedes Q-transform cropping and retains the required context.
- Detector-specific statistics and cross-detector statistics remain distinct.
- Failed and superseded scientific attempts are preserved.
- The supported portable surface is Python 3.11 plus the CPU lock; CUDA has a
  distinct recorded environment and run identity.
- Generated runs, raw data, caches, and local output are not source artifacts.

## Packaging debt

- The repository has no `pyproject.toml`, wheel metadata, or console entry
  points. Current launchers intentionally add the repository root to
  `sys.path` and import `src.*`.
- Workflow commands depend on root-relative `config/`, `scripts/`, and `main.py`
  files. A wheel containing only `src/dante_workflow` would therefore be
  incomplete.
- Flask templates and static assets require explicit package-data handling if a
  wheel is introduced.
- `main.py` and the scientific script surface are broader than the bounded JOSS
  workflow; packaging all of them would create a large accidental public API.
- The exact CPU environment includes test tooling because the public acceptance
  path is itself a verified smoke workflow.

These are release-design constraints, not evidence that the current
repository-based installation is scientifically invalid.

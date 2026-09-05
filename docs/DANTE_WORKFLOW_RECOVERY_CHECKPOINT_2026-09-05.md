# Workflow recovery checkpoint — 2026-09-05

Status: initial P5.2 recovery coverage implemented; P5/P6 remain incomplete.

## Defect and correction

An isolated fault-injection test changed a previously verified receipt. Resume
trusted historical `VERIFIED` status and attempted the next stage without
rechecking the predecessor's bytes. This was an administrative integrity defect,
not an observed corruption of a scientific run.

The orchestrator now checks every expected output before skipping a verified
stage. The ledger also checks verified-stage dependency outputs before starting
an attempt, including direct Repair. Both use the existing artifact hash gate;
no scientific contract, score, population, threshold, or verifier is changed.
Changed artifacts are retained and execution stops rather than overwriting them.

## Evidence

`tests/test_dante_workflow_recovery.py` adds eight cases:

- five synthetic stage-runner failures: network timeout, CUDA error, dependency
  error, ENOSPC, and verifier failure; retry preserves run identity, previous
  attempt evidence, and append-only history;
- two changed-receipt cases, for Resume and Repair: no downstream runner call;
- one real inert subprocess termination: stale lease recovery marks the old
  attempt `INTERRUPTED`, then permits a new attempt without deleting history.

The subprocess test terminates only its own recorded child. It does not launch
or interrupt scientific work. CUDA/dependency failures are injected runner
results, not actual device removal or package uninstallation. ENOSPC is injected
at the stage-runner boundary, not a real full disk or a ledger-write failure.

Validation:

- targeted recovery/state/orchestrator suite: **29 passed**;
- all `tests/test_dante_workflow*.py`, Windows: **86 passed**, 22.06 s;
- same suite, isolated WSL validation environment: **85 passed, 1 skipped**,
  49.09 s; the skipped test is Windows-specific;
- Ruff on changed Python files: **PASS**; `git diff --check`: **PASS**.

## Remaining acceptance

This does not close P5.1 public clean-clone smoke, packaged CLI/UI artifact
parity, full failure coverage (including ledger/storage-boundary failures), or
P6 human acceptance. No release-ready, real-time, or discovery claim follows
from these component/recovery tests. Existing scientific artifacts are untouched.

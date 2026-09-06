# Workflow recovery checkpoint — 2026-09-05

Status: P5.2 recovery coverage complete; P6 remains incomplete.

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
results, not actual device removal or package uninstallation. The initial
ENOSPC case is injected at the stage-runner boundary. The completed matrix
additionally injects a failed lease `fsync`, an ENOSPC terminal-ledger append,
and a failed orphan-recovery append. Partial/new leases are removed, active
evidence remains append-only, and the next successful lease records the
orphaned attempt as `INTERRUPTED` before retrying the same run identity.

Validation:

- completed recovery/state/orchestrator/UI/CLI subset, Windows: **48 passed**;
- all `tests/test_dante_workflow*.py`, Windows: **101 passed**, 20.39 s;
- same suite, isolated WSL Python 3.11 environment: **100 passed, 1 skipped**,
  49.91 s; the skipped test is Windows-specific;
- Ruff on changed Python files: **PASS**; `git diff --check`: **PASS**.

## Remaining acceptance

P5.1 public smoke and P5.2 failure coverage are complete. Packaged CLI/UI
artifact parity and P6 human acceptance remain open. No release-ready,
real-time, or discovery claim follows from these recovery tests. Existing
scientific artifacts are untouched.

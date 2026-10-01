---
phase: 08-multi-run-productization
plan: 08
completed_at: 2026-10-01
scope: existing_native_index_read_only
overall_multi_run_productization_complete: false
---

# Summary 08.08: stored INDEX validation, not encoder/clustering replay

| Task | Result | Local commit |
| --- | --- | --- |
| Separate INDEX verifier, CLI, tests and source freeze | VERIFIED | b6b9d2c |
| Scope/platform/latency checkpoint and handoff | VERIFIED | Documentation checkpoint |

Approved A continues with a separate INDEX module/CLI and 72 tests. The unchanged
08.07 immutable SCAN/COHORT chain is reused with explicit parent roots. No old
verifier or `_expected_run`, productive writer, encoder, preprocessing, fit or
fetch is called. Scientific contract/runtime loaders and pure preflight/token
validators retain their existing gates. Counts and numeric constraints are read
from versioned gates, not hardcoded from the conversation.

Sealed summary, every retained token/manifest/replay identity, exact NPZ schema,
shape/dtype/labels/provenance/file/value SHA and finite/L2 normalization gates
remain enforced. Paths, locks/failures/partials, SQL sidecars and changing inputs
fail closed without repair. Eighteen executed local helper/wrapper source pins;
sealed scoped stdout receipt explicitly denies full-workflow/numerical replay.
No public adapter/profile/registry changes or historical invocation.

Real temporary SQLite/NPY/NPZ files; scaled contract/runtime fixture substitutions.
Full frozen-cardinality synthetic INDEX parity compares the full legacy returned
summary with the new gate; that test alone isolates the already-tested parent
and keeps arrays small. It is not production encoder/clustering validation.
Success/failure bytes/mtimes/inventory snapshots and fixture-only resealed
negatives; actual local contract/source tests without historical run access.

Windows's real legacy contract loader rejects two host-Path-reconstructed WSL
storage paths. All other fields agree; refusal is explicitly tested, not bypassed.
The actual contract loads unchanged in WSL. Native Windows production verification
support is not claimed. Initial fixture import and mock-runtime test setup were
corrected without modifying any frozen source or contract.

Final Windows workflow: **490 PASS**, observed OS exit 0, 125.45s. Final WSL
workflow plus primary scan/native cohort/INDEX/PatchProducer: **523 PASS, one
Windows-only skip, 11 upstream warnings**, observed OS exit 0, 178.93s. Ruff
lint across workflow/test modules and new CLI, and new-file format PASS. Local
source freeze **b6b9d2c**; all three new Python files match Git blobs byte-exactly
without filters. Post-freeze target result is recorded in VERIFICATION.

The first full WSL run had an
unrelated 15-second UI launcher timeout: 522 PASS/one FAIL/one skip/11 warnings,
203.13s, exit 1. Isolated failure reproduced, then passed unchanged after a
read-only Git source-identity timing probe (24.697s); isolated PASS exit 0, 9.15s.
No test exclusion, timeout increase or UI patch. Cold-start reliability remains
an administrative qualification even if final rerun passes.

No scientific source/config/artifact rewrite, dependency install, normalization,
push, release or public action. User untracked files and O3a diagnostic closure
remain intact. Next: native calibration/rescore read-only gates, remaining native
chain, full profile/preflight adoption and quiescent bounded real clean-install
replay. Multi-run/Virgo readiness is not established by this bounded increment.

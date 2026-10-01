---
phase: 08-multi-run-productization
plan: 07
completed_at: 2026-10-01
scope: existing_scan_cohort_gate_read_only
overall_multi_run_productization_complete: false
---

# Summary 08.07: immutable scan/cohort reads, not new scoring

| Task | Result | Local commit |
| --- | --- | --- |
| 1: separate scan/cohort verifier, CLI, synthetic parity and negatives | VERIFIED | 57a99dc |
| 2: finding, scope/test checkpoint and handoff | VERIFIED | Documentation checkpoint |

Continues author-approved A without another architecture decision: separate,
source-frozen read-only gates. Bounded to primary scan plus native cohort; public
factory/registry and all scientific sources/configuration/evidence remain intact.

Source inspection and a temporary SQLite probe found that legacy mode=ro can
create WAL/SHM files. New readers require a SHA-bound standalone database,
reject transaction sidecars, use mode=ro&immutable=1/query_only, and detect input
changes. No transaction repair/checkpoint/deletion or old verifier invocation.
The explicit reproduction and immutable SQL-write rejection are tested.

Scan preserves current-runtime/identity/population/stored-score/candidate-tensor/
frame-ledger gates and full exact summary reconstruction. Cohort uses the new
scan parent reader, retains inclusive cross-detector guard and detector-local
separation, exact ledger/shard/context provenance and finite float64 samples,
sealed summary and transient-cache checks. It does not claim full reconstruction
of every descriptive cohort-summary field beyond the existing verifier.
Fourteen source bindings and explicit input hashes accompany a sealed stdout
receipt. No candidate count or score values emitted; raw scoring, encoder,
threshold fitting, fetch and full scientific workflow flags are false.

Final Windows workflow regression: **418 PASS**, observed OS exit 0, 83.01s.
Final WSL workflow plus existing primary-scan/native-cohort/PatchProducer:
**448 PASS, one Windows-only skip, 11 upstream warnings**, observed OS exit 0,
170.29s. Final pre-freeze Windows targeted suite **89 PASS**, observed exit 0,
27.47s. Ruff lint across workflow modules/tests/new CLI and new-file format PASS.
Post-freeze targeted and byte audit are recorded in VERIFICATION.

Temporary real WAL-mode databases/NPY contexts; fixture loaders/runtime capture
explicitly scaled/substituted, inherited validators remain real. Legacy-result
parity runs only on temporary evidence; their WAL/SHM are fixture-only. Success
and failure preserve fixture bytes/mtimes/file inventories. Semantic negatives
are repinned/resealed only in tests. Actual local contract/source loaders pass
without opening history. Initial fixture INSERT placeholder and journal-mode
assertion errors were fixed; immutable connection reports delete mode internally
while the persistent WAL header remains byte-identical. Native Windows Python
lacks Ruff; the existing WSL Ruff was used, with no dependency installation.

No historical/database verifier run, scientific outcome, old-source normalization,
productive run, push, release or external communication. User untracked artifacts
and output remain untouched. O3a diagnostic closure unchanged. Next: readonly
INDEX, then native calibration/rescore and later gates; full profile/preflight
adoption, quiescence and bounded real clean-install replay remain open.

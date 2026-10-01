---
phase: 08-multi-run-productization
plan: 11
scope: native_taxonomy_read_only
status: passed_with_platform_and_fixture_qualifications
completed: 2026-10-01
source_freeze: 6b0f5a5
overall_multi_run_productization_complete: false
---

# Summary 08.11: exact retained taxonomy replay, no history writes

Separate module/CLI and 78 new synthetic tests. Original scientific sources,
contracts, earlier read-only gates and public dispatch unchanged. Immutable DB
reader reproduces original SELECT/order/joins/vector checks, avoids original
mode=ro-only sidecar behavior, uses unchanged original build_taxonomy_rows for
cosine/single-linkage/naming. Entire JSONL bytes, metrics, summary and verified
compact reconstructed read-only; no hash-only substitute for numerical replay.

Actual 08.10 classification/threshold gates with explicit upstream roots, existing
persistent lock exclusion throughout replay/rehash, 32 executed source bindings,
all reference/input/source hashes tracked. No old productive verifier/writer,
fetch, encoder, new score, prior-taxonomy clustering input or method change.
Stdout-only receipt reports limited retained numerical replay and denies full
workflow/global-quiescence verification; no score/outcome counts emitted.

## Empirical evidence and fixture qualifications

- Initial WSL new/old taxonomy suite: 44 PASS/one skip/47 setup errors,
  observed OS exit 1/65.52s. Old verify correctly rejected absent artifacts;
  corrected fixture now invokes old run then verify, only on disposable storage.
- Intermediate new WSL suite: 61 PASS/one FAIL, OS exit 1/23.09s. Resealed parent
  changes run key; negative fixture moved to its contract-derived directory to
  reach intended parent semantic refusal, not bypass a gate.
- Corrected new WSL suite before linked test: 76 PASS/one Windows-only skip,
  11 upstream warnings, OS exit 0/48.24s.
- Initial Windows target before linked test: 30 PASS/47 POSIX-only skips,
  OS exit 0/19.93s; pure tests do not certify POSIX/platform science.
- Linked fixture initially used guessed classification ledger name: one FAIL,
  OS exit 1/6.21s. Reads exact frozen fixture contract output instead; isolated
  linked replay then one PASS/11 warnings, OS exit 0/6.30s.
- Ruff full workflow/tests/new CLI lint and three-file format PASS, exit 0.
- Full final Windows workflow: 609 PASS/114 POSIX-only skips,
  observed OS exit 0/194.09s.
- Full final WSL workflow plus retained scientific taxonomy/parent/PatchProducer
  suites: 844 PASS/three Windows-only skips/11 upstream warnings, observed OS
  exit 0/397.99s. Prior disposable E: lock contention fixture explicitly enabled.
- Source freeze 6b0f5a5: three new Python files byte-identical to Git without
  normalization; original O3a/O4a taxonomy helpers also exactly match Git blobs.
  Freeze diff contains only new module/CLI/tests/PLAN. Upstream EOL qualifications
  remain unchanged, no blanket all-source identity claim.
- Post-freeze WSL target: 77 PASS/one Windows-only skip/11 upstream warnings,
  observed OS exit 0/48.94s; all 78 new tests collected, no post-freeze source edit.

Main fixtures isolate classification parent. Additional linked fixture executes
actual threshold bootstrap per detector and classification, isolates only RESCORE
ancestry. Its absent-image/SQL-NULL scaled join is explicitly not real primary
image provenance. Original taxonomy execute creates fixture expected artifacts
with substituted parent inputs only; new path forbids productive entry points.
Whole snapshots and resealed semantic negatives are fixture evidence, not real
historical adoption, fresh raw/encoder scoring or clean-install validation.

No old file normalization, historical mutation, installation, push/merge/release,
public activation or user untracked edits. Next: coincidence/PEM read-only gates,
full profile/preflight adoption, global quiescence and bounded real scientific
clean-install replay; full multi-run/Virgo readiness remains open.

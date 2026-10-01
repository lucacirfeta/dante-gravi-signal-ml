---
phase: 08-multi-run-productization
plan: 10
verified: 2026-10-01
scope: threshold_classification_read_only_replay
status: passed_with_platform_and_fixture_qualifications
score: 5/5
source_freeze: 8da8f7b
overall_multi_run_productization_complete: false
---

# Verification 08.10: frozen numerical replay with approved persistent locks

| Required truth | Evidence |
| --- | --- |
| Read-only persistent lock, no mutation | O_RDONLY descriptor flags asserted; original producer subprocess contention/reacquisition, snapshots, exceptions/replacement/unsafe/missing/refusal checks; explicit disposable Linux/E: fixtures |
| Original threshold statistics | Actual validate_score_rows/compute_threshold/block_bootstrap helper; exact legacy _calculate result parity with isolated fixture parent; complete summary/compact and detector-local vector assertions |
| Original classification | Actual classify_rows, exact lower/upper equality AMBIGUOUS; original execute summary parity on separate disposable verified-input fixture; exact canonical JSONL SHA/rows/summary/compact |
| Explicit parents and integrity | 08.09 read-only RESCORE entry wired with explicit roots; 28 helper/wrapper pins, tracked references, exact compacts, input/source rehash; no original productive entry point |
| Bounded safe interface | CLI stdout-only fixture success/refusal; mutation options exit 2; snapshot preservation and semantic negatives; Windows early POSIX refusal, public registry untouched |

## Observed runs

- Initial WSL fixture run: 1 failed, 47 setup errors, 71 passed, one skip,
  OS exit 1/72.58s. All fixture errors share unchanged original interval refusal
  because point-only-tail extremes placed p99 outside CI. Investigated without
  changing scientific code; valid fixture adjusted and explicit refusal retained.
- Intermediate WSL new target: 67 PASS, one Windows-only skip, exit 0/52.49s;
  superseded by expanded 78-test coverage.
- Expanded WSL target plus unchanged thresholds/classification: **129 PASS,
  one Windows-only skip**, observed OS exit 0/76.99s, disposable E: test enabled.
- Expanded Windows target: **12 PASS, 66 POSIX-only skips**, exit 0/14.53s.
- Full Windows workflow: **579 PASS, 66 POSIX-only skips**, exit 0/180.18s.
- Full WSL workflow plus retained primary/cohort/INDEX/calibration/rescore/
  thresholds/classification/PatchProducer: **747 PASS, two Windows-only skips,
  11 upstream warnings**, observed OS exit 0/308.84s. Disposable E: test enabled.
- Whole workflow/test/new-CLI Ruff lint and new-file format PASS, exit 0.
- Local source freeze **8da8f7b**. All three new Python files byte-identical to
  Git (`hash-object --no-filters` equals frozen blob); diff from def71fa contains
  only those files and the approved 08-10 PLAN. No old source normalization.
- Post-freeze WSL target: **77 PASS, one Windows-only skip**, observed OS exit
  0/55.34s; all 78 new tests collected, disposable E: contention test enabled.

## Scope qualifications

Existing producer uses persistent run.lock. Author approved stage-specific
read-only original flock, not deletion, marker ignoring or an alteration to earlier
generic guards. Opens safe existing regular single-link inode with no create or
write flag; path/descriptor signatures and lifetime checked. Stage-only exclusion
does not prove upstream global quiescence or protect against noncooperating
writers. Linux/E: tests are disposable configurations, not historical adoption
or general cross-filesystem certification. Native Windows is fail-closed, not
declared scientifically supported because pure/administrative tests pass.

RESCORE alone is isolated in new fixtures. Prior retained dependency chain runs
in unchanged regression suites; new fixtures do not prove real full-chain
adoption. Original numerical helpers and descriptor protocol are actual, not
synthetic replacements. Contract/runtime populations/replicates are fixture-scaled.
Legacy numerical parity uses isolated parent; original classification execute
writes only a separate fixture with verified inputs substituted in that test.
New implementation never monkeypatches scientific code or calls productive
execute/_calculate/_verified_inputs/parent verifier/writer/fetch/encoder paths.

Negative inputs are resealed/repinned only in fixtures. Success/refusal snapshots
preserve bytes/mtime/inventory. Unchanged actual scientific contract loaders pass
in WSL without history; Windows loader refusal inherited from WSL root syntax is
preserved. No real full-replicate historical/bootstrap/score replay was executed.
Stored calibration numerical bootstrap replay is stated distinctly from fresh
raw-score evidence. No scores, interval values, class counts or outcomes emitted.

No old scientific source/config/artifact, earlier readonly source or user file
changed; no install/push/merge/release/activation or other-run/Virgo certification.
Remaining native gates, full profile/preflight binding, global quiescence and
bounded real clean-install scientific replay remain open.

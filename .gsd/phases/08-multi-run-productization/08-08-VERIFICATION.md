---
phase: 08-multi-run-productization
plan: 08
verified: 2026-10-01
status: passed_with_platform_and_latency_qualifications
scope: existing_native_index_read_only
score: 5/5
overall_multi_run_productization_complete: false
---

# Verification 08.08: retained INDEX gate only

| Required truth | Empirical evidence |
| --- | --- |
| Explicit safe parent chain | Actual 08.07 read-only COHORT/SCAN fixture chain and immutable SQLite; old parent/verifier/default helper calls forbidden; upstream lock/failure/sidecar negatives |
| Preserved INDEX gate | Complete stored summary parity with original INDEX verifier on full frozen-cardinality synthetic token evidence; only parity parent isolated, arrays scaled; pure shard/preflight validators unchanged |
| Retained numerical/provenance checks | Every NPY shard, replay identity, file/value SHA; exact NPZ schema/shapes/dtypes/labels/meta, finite arrays and existing norm tolerance; fixture-only repinned/resealed negatives |
| Sources/inputs and limited claim | Eighteen explicit local source bindings, guarded input paths, sealed stdout receipt and final rehash; no encoder, preprocessing, fit, fetch, raw-score replay or full-workflow claim |
| History/source/public dispatch preserved | Success/failure fixture file-byte/mtime/inventory snapshots; real CLI entry calls, mutation-flag rejection; source freeze/Git byte audit, no old source/config edits or historical invocation |

## Observed successful runs

- Initial WSL new INDEX plus old INDEX tests: 64 PASS, exit 0, 22.35s;
  superseded by final expanded 72-test coverage in the regressions below.
- Final Windows complete workflow: **490 PASS**, OS exit 0, 125.45s.
- Final WSL workflow plus primary scan/native cohort/INDEX/PatchProducer:
  **523 PASS, one Windows-only skip, 11 upstream warnings**, OS exit 0, 178.93s.
- Ruff lint across workflow modules/tests/new CLI and new-file format PASS.
- Local source freeze **b6b9d2c**. New module/CLI/test bytes match committed
  blobs without filters. Scientific source/config/old runner and 08.07 source
  paths show no tracked diff; upstream EOL qualifications are not normalized.
- Post-freeze Windows target: **72 PASS**, observed OS exit 0, 47.97s.

## Preserved refusals and failed invocations

Native Windows's actual historical contract loader raises `ContractError`:
two reconstructed WSL storage paths use backslashes and thus alter the contract
digest. Read-only comparison showed every other field identical. The test asserts
that refusal on Windows and actual unchanged contract acceptance on WSL. No
normalization, new scientific source, contract rewrite or hash exception exists.
Windows unit PASS is not Windows production verification certification.

The first full WSL regression returned exit 1: 522 PASS, one FAIL, one skip,
11 warnings in 203.13s. Only the detached UI launcher test failed its existing
15-second timeout. The isolated failure reproduced (exit 1, 16.25s). A read-only
Git source-identity probe took 24.697s; after that read completed, the unchanged
isolated test passed (exit 0, 9.15s). Full unchanged rerun then passed above.
No UI/process/timeout patch or skipped failure. Git/launcher cold-start latency
remains an observed administrative limitation, not guaranteed resolved.

Initial fixture import/collection and a fixture runtime-mock invocation error
were corrected only in the new tests. The first native Windows contract failure
triggered diagnosis before further execution; it was not silently accepted.

## Evidence boundary and open overall gates

Fixtures use real SQLite/NPY/NPZ with explicitly substituted/scaled contract and
runtime loaders. Full-cardinality parity isolates the already-tested parent only
in that test and is not full-sized encoder/clustering replay. Actual scientific
contract/source checks do not open history. CLI success is in-process fixture
execution; mutation options have observed subprocess exit 2. The new read-only
gate was not invoked against any historical run or clean-install acceptance.

Native calibration/rescore and later read-only gates, complete profile/preflight
adoption, quiescence and bounded real clean-install scientific replay remain
open. No public registration, outcome promotion, push, release or other-run/V1
certification. O3a diagnostic closure and user untracked files remain unchanged.

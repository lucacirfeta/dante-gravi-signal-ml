# O3a verification boundary: source audit and decision

Date: 2026-10-01. Baseline: local interface `138ed7c`, checkpoint `2ea91ad`.
Status: audit completed; implementation awaiting a structural decision.

## Findings from primary source, not historical execution

The initial acquisition and acceptance CLIs have no autonomous verification
selector. Reinvoking their productive entry points is not a read-only replay.

- `scripts/run_dante_o3a_raw_download.py:main` always calls `write_preflight`.
  `o3a_raw_download.execute_download` writes progress, verified ledger,
  manifest and summary, even when final files already exist.
- `o3a_raw_download.validate_hdf5_metadata` checks the strain dataset's shape
  and sample spacing; its own return explicitly says metadata-only validation.
  `file_sha256` and `build_raw_manifest_rows` are available for a local byte and
  inventory check. These do not establish a new independent source fetch or
  recompute strain-derived science.
- `o3a_initial_calibration_acceptance.validate_block_shard` checks shard seal,
  run/block identity, ordered row identities, finite scores, float32 encoding
  and failures. `execute_acceptance` reconstructs the accepted ledger from
  these shards, but writes ledger, summary and progress. Reusing existing
  valid shards does not rerun the raw preprocessing, encoder or score model.
- `o3a_initial_thresholds._validate_acceptance_summary` checks summary status,
  seal, cardinalities and ledger SHA. It does not replay the score calculation.

The future gate must distinguish **integrity of historical evidence**,
**deterministic reconstruction from stored evidence**, and **numerical replay
from raw**. A new wrapper must not label the first two as the third. This audit
neither invalidates the historical verification nor newly re-verifies it.

## Positive side-effect findings, expanded since 08.04

| Invoked path | Source evidence of mutation |
| --- | --- |
| RESCORE --verify | `verify_native_rescore` calls `preflight_rescore`, which unconditionally writes work_manifest.jsonl and preflight.json. The CLI additionally writes the compact through `write_compact_rescore_artifact`. Calling the core verifier alone is therefore insufficient. |
| THRESHOLDS verify | `execute_thresholds` opens/creates run.lock, calls `_calculate` -> rescore verification (above), writes compact on success and failure.json on exceptions within its try block. |
| CLASSIFY verify | `execute` opens the threshold-style lock; `_verified_inputs` calls threshold verification; summary and compact are written, and exceptions can write failure.json. |
| TAXONOMY verify | `execute` opens the same lock pattern and writes summary/compact; exceptions can write failure.json. |
| COINCIDENCE verify | `verify_native_coincidence` unconditionally writes root/COMPACT_REL after rebuilding ledgers from shards. Its `_pin_new_frames(..., allow_download=False)` rejects a missing receipt instead of downloading. |
| PEM verify | `verify_native_pem` validates an existing compact, but creates it when absent. |

The rescore-preflight and coincidence-compact findings extend the prior audit.
Transitive parent writes matter even if the immediate wrapper has no writer.
This is a list of confirmed write paths, NOT exhaustive proof that all remaining
helpers, locks, imported libraries or error paths are non-mutating. No listed
scientific verifier was executed in this audit.

## Decision required before implementation

**Recommended: separate, read-only verification entry points.** Preserve frozen
scientific sources and contracts; reuse their deterministic helpers where they
are actually pure. Version/source-freeze the new verification layer and bind its
receipt to exact old sources, inputs and configuration. Isolate emission of new
workflow evidence from historical evidence. Missing data or mismatches fail
closed, with errors recorded only in the new workflow area. Do not replace
existing numerical checks with hashes, retune criteria or conceal weaker claims.

The first implementation should expose the existing initial integrity and
stored-evidence checks with their explicit scope. Full raw numerical replay and
complete scientific activation remain separate gates. If exposing these checks
would change the mathematical validation itself, stop for a further scientific
decision rather than including it in this structural authorization.

**Alternative: a verified isolated replica for unchanged legacy verifiers.**
This minimizes verifier code changes but is not a simple cwd switch: the scripts
derive ROOT from their own location and contracts bind absolute parent paths,
file hashes and source/runtime identities. The replica must contain all writes,
including failure/lock/preflight writes, and preserve those identities. Hardlinks
or symbolic links to writable historical evidence do not establish isolation.
No silent contract-path rewriting or bypass of provenance is acceptable.

Neither option is implemented or presumed approved. No adapter factory/registry,
production graph or scientific method changed. Exact full-stage applicability,
preflight inputs and clean-install bounded replay still remain after this gate.

## Current evidence and handoff

- Fresh Windows native-adapter tests: **45 PASS**, observed OS exit 0, 2.01s.
  These are synthetic interface regressions, not numerical O3a verification.
- No code changes in this turn. Previous complete-controller results remain
  269 Windows PASS / 268 WSL PASS plus one skip; not rerun or presented as fresh.
- No scientific command, download, raw/score outcome inspection, historical
  rewrite, push, release, new-run/V1 validation or automation started here.
- User untracked paths preserved. Existing historical EOL qualifications remain.
- Next: author chooses the verification architecture; then prepare and implement
  its bounded, source-frozen verification plan before public O3a dispatch.

## Resolution after this checkpoint (2026-10-01)

The author's subsequent "procedi" approves the recommended separate read-only
entry points (option A). Original findings and alternatives above are preserved
as the checkpoint record. Plan 08-06 implements only the initial evidence scope
in source freeze 9d8a51a: raw integrity and stored acceptance reconstruction,
not raw score replay, full native verification or public workflow activation.
See 08-06-SUMMARY/VERIFICATION and the initial read-only documentation checkpoint.

# O3a INDEX: separate retained-evidence verification

## Scope and preserved method

Phase 08.08 continues approved option A. A separate module and CLI verify the
existing native INDEX through explicit read-only COHORT and primary-SCAN parents.
The historical `_expected_run` calls COHORT with its default parent location;
the new interface does not call or patch that helper or any old verifier.
Scientific sources, configurations, completed O3a conclusions and the public
adapter factory/registry remain unchanged. This is not public multi-run readiness.

New files:

- `src/dante_workflow/o3a_index_verification.py`
- `scripts/verify_dante_o3a_index_evidence.py`
- `tests/test_dante_workflow_o3a_index_verification.py`

Existing validated contract/runtime loaders, preflight reader and token-shard
validator remain authoritative. Detector counts, token totals, NPZ shapes and
normalization tolerance come from the versioned contract, never the conversation.
The verified contract enforces the same frozen cardinalities as the legacy gate.
Each replay row must match its position, frozen COHORT identity, detector/context
provenance and retained token value hash. Every token file/manifest is checked.
The retained NPZ must have exactly the existing keys, shapes, float32 dtypes,
labels, metadata, file/value SHA and finite normalized vectors. These checks
validate retained numerical arrays, not newly computed embeddings or centroids.

Unsafe paths, missing/changed files, invalid seals, locks, failures, partials and
SQLite sidecars fail closed without repair. The 08.07 immutable SQLite dependency
chain remains frozen and is reused with explicitly supplied parent roots. Inputs
are rehashed and source bindings checked again before returning a sealed stdout
receipt. Eighteen explicit local helper/wrapper bindings accompany the receipt;
scientific contract source pins remain enforced by their inherited loaders.
This is not a claim of full imported-dependency source closure or exclusive
access against a concurrent writer. Real adoption still requires quiescence.

## Interface and intentionally limited receipt

Repository-bound scientific-environment command, not an installed-wheel or
enabled public adapter capability:

```text
python -B scripts/verify_dante_o3a_index_evidence.py --external-root <existing-index-cache-parent> --cohort-external-root <existing-cohort-cache-parent> --primary-external-root <existing-primary-cache-parent>
```

The CLI disables bytecode writes and emits JSON only on stdout. Run directories
are derived from validated contracts; no run/repair/resume/freeze/output-file
option exists. Failure returns exit 1 without writing a historical failure file.
There was no invocation against any historical INDEX/COHORT/SCAN run here.

Status `PASS_O3A_READ_ONLY_INDEX_STORED_VALIDATION_ONLY` identifies
`EXISTING_FROZEN_INDEX_GATE_VALIDATION`. Stored patch tokens and NPZ numerical
validation are true; raw-score replay, preprocessing, encoder, clustering refit,
threshold fit, source fetch, historical mutation and full-workflow verification
are false. No candidate counts or scores are emitted. A stored-index receipt
cannot be relabeled as a fresh scientific replay or a full workflow PASS.

## Platform finding: preserved fail-closed behavior

The real legacy INDEX contract loader rejects this checkout under native Windows.
Diagnosis found only two reconstructed WSL storage paths changing from `/mnt/e/...`
to backslash syntax through the historical host-Path conversion; consequently
the reconstructed contract digest differs. No source/config normalization,
contract rewrite or gate bypass was applied. The Windows test asserts exact
equality of all other contract fields and the loader's refusal. The actual
unchanged contract loader passes in WSL. This increment does not claim native
Windows production verification support for the frozen WSL scientific contract.

## Test interpretation and next gates

Tests compose the frozen 08.07 synthetic fixture with real SQLite, NPY and NPZ
files. Contract loaders/runtime capture are scaled/substituted only in fixtures.
The separate legacy INDEX parity test uses the full frozen detector cardinality
with tiny arrays and isolates the already-tested parent only in that test; its
complete returned summary agrees with the new gate. It is not production-sized
encoder/clustering replay. Negative evidence is resealed/repinned only in tests
to reach identity, numerical, normalization and provenance rejection paths.
Success/failure snapshots check file bytes, mtimes and inventory. CLI success is
an actual entry-function call on fixtures; unsupported mutation flags are tested
in subprocesses. Fixture helpers are loaded by explicit file path because the
test directory is not importable as a top-level module in this pytest setup.

The first complete WSL regression had one unrelated detached-UI launcher timeout,
also reproduced in isolation. A read-only timing probe measured the controller's
Git source-identity read at 24.697 seconds, beyond that test's 15-second launcher
limit. After the same Git read had completed, the unchanged isolated test passed
in 9.15 seconds. No timeout increase, UI/process/source-identity patch or test
exclusion was made. This observed latency sensitivity must not be hidden by a
later green run or interpreted as demonstrated cold-start reliability.

Observed final test counts, OS exits, source freeze and byte audit are recorded
in 08-08-SUMMARY/VERIFICATION. No history mutation, scientific outcome, dependency
installation, push, release or public dispatch occurred; user files are preserved.
Next: separate native calibration/rescore gates, then the remaining native chain,
complete profile/preflight adoption and quiescent bounded real clean-install
replay. Other observing runs and V1 require their own validated contracts.

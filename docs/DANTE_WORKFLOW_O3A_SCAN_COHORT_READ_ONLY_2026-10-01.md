# O3a scan and native cohort: separate read-only gates

## Approved scope, not full scientific readiness

This is the next bounded implementation of author-approved option A: separate,
source-frozen non-mutating verification entry points. Only the primary scan and
its native cohort dependency chain are supported here. Neither the existing
scientific sources/configurations nor the public adapter factory/registry change.
The completed O3a diagnostic study and its conclusions remain unchanged.

New module, CLI and tests:

- `src/dante_workflow/o3a_native_verification.py`
- `scripts/verify_dante_o3a_native_evidence.py`
- `tests/test_dante_workflow_o3a_native_verification.py`

## SQLite finding and protected boundary

The historical scan verifier and the cohort's parent query helpers use SQLite
`mode=ro`. That prevents SQL changes but does **not** prevent SQLite from creating
`-wal` and `-shm` files for a standalone database with a persistent WAL-mode
header. The behavior was reproduced on a temporary checkpointed database, then
covered by an explicit test. No historical database was opened for this finding.

The new readers use `mode=ro&immutable=1` and `PRAGMA query_only=ON`. They require
an existing standalone database with its SHA pinned to the sealed scan summary
and reject any existing `-wal`, `-shm` or `-journal`, including an empty sidecar.
They do not ignore, checkpoint, remove or repair a transaction. Sidecars and file
signatures are checked before/after queries; input hashes are checked again
before the receipt. The on-disk WAL header bytes do not change. SQL writes fail.

This is an I/O-only replacement for a sealed quiescent database, not a change to
scientific arithmetic or to the historical database. It does not prove exclusive
access against another writer; actual adoption still needs a process/quiescence
gate. It is not a current remote fetch or a persistent snapshot service.

## Preserved scientific checks

| Selector | Preserved checks | Deliberately excluded scope |
| --- | --- | --- |
| `scan` | Current frozen runtime gate; existing contracts, geometry, run/preflight/database identity; complete sorted population; finite stored score and float32 encoding; detector-specific strict candidate comparison; candidate tensor byte shapes and background tensor absence; existing raw-frame ledger/coverage validator; exact stored summary reconstruction; empty transient cache | Fresh raw/encoder/scoring replay, threshold fit, remote raw validation, downstream gates |
| `cohort` | Same scan parent gate using the supplied primary root; exact target identities/cardinality; inclusive cross-detector candidate guard and within-detector separation; sealed summary, proposal/ledger/shard hashes and equality; retained finite float64 context shape and value SHA; existing context-source coverage/provenance calculation; empty transient cache | Fresh quality/veto measurement, embedding/index construction, native calibration or scoring, later native verification |

The scan's complete summary is reconstructed and compared byte-value-exactly
as a JSON object. The cohort retains the historical verifier's sealed summary
header and ledger/shard/context/selection gates; it does not claim a stronger
reconstruction of every descriptive summary field. Parameter values come from
the validated versioned contracts. Existing pure validators and current-runtime
checks are reused; no legacy verifier, productive scorer or writer is called.

The receipt statuses are:

- `PASS_O3A_READ_ONLY_SCAN_RECONSTRUCTION_ONLY`
- `PASS_O3A_READ_ONLY_COHORT_RECONSTRUCTION_ONLY`

Both identify `EXISTING_FROZEN_GATE_RECONSTRUCTION`, bind all explicit inputs and
fourteen executed local helper/wrapper sources, and deny full-workflow scientific
verification, raw-score replay, encoder execution, threshold fitting, source
fetch and historical mutation. Stored primary scores are read; cohort context
samples are checked. No candidate counts or score values are emitted. None of
these receipts is a substitute for fresh numerical replay or complete adoption.

## Repository-bound interface and failure behavior

This is a scientific-environment repository CLI, not an enabled installed-wheel
or public workflow capability. The existing dependencies/checkpoint checkout
are required. The CLI disables Python bytecode generation before helper imports.

```text
python -B scripts/verify_dante_o3a_native_evidence.py --stage scan --external-root <existing-primary-cache-parent>
python -B scripts/verify_dante_o3a_native_evidence.py --stage cohort --external-root <existing-native-cache-parent> --primary-external-root <existing-primary-cache-parent>
```

No command was executed against historical scan/cohort evidence in this increment.
The exact run directories are derived from validated contracts, not overridden
or rebased. JSON output is stdout only. A future controller may capture it only
in a new evidence area, never over historical inputs. There is no run/freeze,
repair/resume, output-dir or compact-generation option. Unsupported native stages
fail closed. Missing or altered evidence, unsafe paths, active locks/failures,
partials or transaction sidecars are preserved and rejected without a new
historical failure file. No transaction files are removed by the implementation.

## Empirical evidence and remaining work

Tests use real temporary checkpointed WAL-mode databases and NPY contexts.
Explicitly scaled fixture loaders substitute production contracts, geometry and
runtime capture; existing identity, frame/coverage, shard and preflight validators
remain real. A separate test loads actual local contracts/source bindings without
opening historical outcomes. Exact legacy-result parity is tested on temporary
evidence only; legacy-created sidecars belong only to those fixtures. Synthetic
negative evidence is deliberately resealed/repinned to reach the semantic gates;
production contracts are never altered. Success/failure snapshots preserve every
fixture file's bytes, modification time and file inventory. CLI success is
in-process fixture execution; mutation flags are rejected in subprocess tests.
This is not an end-to-end historical or clean-install scientific replay.

Final test counts, observed OS exits and local source freeze are recorded in
08-07-SUMMARY/VERIFICATION. Public dispatch remains blocked. Subsequent increments
must add read-only index/calibration/rescore and later native gates, bind the
complete profile/preflight graph, and perform bounded real clean-install replay.
Other observing runs and V1 still need their own validated scientific/network
contracts; these O3a unit tests do not certify them. No push, release, new science
outcome, source/config normalization or historical artifact rewrite occurred.

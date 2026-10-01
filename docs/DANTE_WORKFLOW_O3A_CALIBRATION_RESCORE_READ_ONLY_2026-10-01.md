# O3a calibration/rescore: retained-evidence read-only gates

## Scope

Phase 08.09 continues author-approved A with a separate verifier and repository
CLI. Scientific sources/configurations, earlier read-only verifiers, historical
runs, O3a diagnostic conclusions and public adapter registration stay unchanged.
Calibrating identities is distinct from fitting score thresholds: this increment
does not perform a fit, bootstrap, encoder replay or fresh scoring.

New files:

- `src/dante_workflow/o3a_score_verification.py`
- `scripts/verify_dante_o3a_score_evidence.py`
- `tests/test_dante_workflow_o3a_score_verification.py`

## Preserved gates and removed write boundary

The existing calibration verifier delegates to historical SCAN/COHORT/INDEX
verifiers. The existing RESCORE verifier calls productive `preflight_rescore`,
which writes `work_manifest.jsonl` and `preflight.json`. The new implementation
does not call or monkeypatch these entry points. It uses the frozen 08.08 INDEX
gate with explicitly supplied parent roots and the 08.07 immutable SQLite chain.

Calibration recomputes the frozen selector's ledger and audit from identities,
candidate flags, index-training identities and validated frame geometry. The
actual pure selector retains full-block priority, evenly spaced indices/context
fallback, candidate/index guards, detector-local bootstrap blocks and point-only
tail semantics. Every parameter is read from the validated versioned contract.
Existing sealed-header/count/bootstrap/outcome-field gates remain enforced.

RESCORE reconstructs the exact ordered work population and full preflight object
in memory with the existing pure work assembler, comparing every stored row,
parent digest, audit and manifest binding. It checks the retained CUDA-preflight
receipt without rerunning CUDA. Every retained score shard passes the unchanged
identity/context/image/finite-score/float32-hex validator; grouped output ledgers
must match those rows exactly, with file SHA, row digest and cardinality checks.
The existing summary gates and empty transient cache requirement remain.

Locks, failures, partials, transaction sidecars, unsafe paths, missing evidence,
bad seals and changed inputs fail closed without repair. Input hashes and 23
explicit local helper/wrapper bindings are checked before receipt. Inherited
scientific contract-source bindings also remain authoritative. The immutable
reads do not prove exclusive access against another writer; quiescence still
requires an adoption gate. No historical verifier was invoked here.

## Interface and receipt interpretation

Repository-bound scientific-environment interface, not public dispatch or
installed-wheel scientific readiness:

```text
python -B scripts/verify_dante_o3a_score_evidence.py --stage calibration --external-root <calibration-cache-parent> --index-external-root <index-cache-parent> --cohort-external-root <cohort-cache-parent> --primary-external-root <primary-cache-parent>
python -B scripts/verify_dante_o3a_score_evidence.py --stage rescore --external-root <rescore-cache-parent> --calibration-external-root <calibration-cache-parent> --index-external-root <index-cache-parent> --cohort-external-root <cohort-cache-parent> --primary-external-root <primary-cache-parent>
```

Run directories are contract-derived. Bytecode writes are disabled before
scientific imports; JSON is stdout only. There is no run/freeze/repair/resume or
output-file option. Unsupported/incomplete scopes are refused before input reads.
Missing/altered evidence is preserved, with no new historical failure artifact.

Receipts identify `PASS_O3A_READ_ONLY_CALIBRATION_STORED_VALIDATION_ONLY` or
`PASS_O3A_READ_ONLY_RESCORE_STORED_VALIDATION_ONLY`. Selection reconstruction is
true; work-manifest, stored score-shard and stored CUDA-preflight checks apply
only to RESCORE. Fresh raw-score/preprocessing/encoder/fetch/threshold-fit,
historical mutation and full-workflow flags are false. No score or candidate
outcome is emitted. Retained CUDA receipts are not current CUDA measurements;
retained score validation is not an independent fresh score replay.

## Platform and test qualifications

The real legacy calibration loader also refuses native Windows reconstruction:
only `execution/root_wsl` changes from `/mnt/e/...` to backslash syntax, changing
the digest. Comparison of every other field is exact. The unchanged refusal is
tested, not normalized or bypassed. RESCORE inherits the earlier INDEX Windows
path refusal. Both actual scientific contracts load in WSL. Windows unit PASS
does not certify native Windows production verification for WSL-frozen contracts.

Tests use real temporary checkpointed WAL-mode SQLite and pure frozen selectors,
context-source builders, work assembler and shard validators. Contract/runtime
loaders are scaled/substituted only in fixtures. The upstream INDEX gate alone
is isolated in this new suite; its explicit-root wiring and tracked parent
references are asserted. The unchanged earlier INDEX/COHORT/SCAN integration
suite remains in the regression. These tests do not prove real end-to-end adoption.

Legacy calibration parity uses its original selection code with immutable query
accessors and isolated parent verification only in that test. Legacy productive
rescore preflight writes only to a temporary fixture, with already-verified work
assembly substituted in that parity invocation; its complete reconstructed
preflight agrees. Legacy retained RESCORE validation then runs with that stored
preflight substituted to prevent fixture rewrites. Actual new entry functions
never use these production monkeypatches. Success/failure byte/mtime/inventory
snapshots, mid-read mutation, unsafe path, identity/manifest/score/CUDA/source
negatives and CLI stdout/error/flag tests are covered. Negative inputs are
resealed or repinned only in fixtures, never in historical scientific evidence.

Local source freeze: `2a15b32`; new module/CLI/test bytes match Git without filters.
Windows workflow 567 PASS (exit 0, 168.88s); WSL workflow plus existing scientific
regressions 618 PASS, one Windows-only skip, 11 upstream warnings (exit 0, 237.09s).
Post-freeze Windows target 77 PASS (exit 0, 27.38s); Ruff lint/format PASS.
Details and qualifications are recorded in 08-09-SUMMARY/VERIFICATION.
No history invocation, scientific outcome, source
normalization, dependency install, public activation, push or release occurred.
User untracked files stay untouched. Next: thresholds/classification and remaining
read-only chain, full profile/preflight adoption and quiescent bounded real
clean-install replay. Other-run/Virgo scientific readiness remains unestablished.

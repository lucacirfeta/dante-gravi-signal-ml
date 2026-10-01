# Initial O3a evidence: separate read-only verification

## Approved boundary

The author approved option A after the phase 08.05 architectural checkpoint:
separate, source-frozen read-only entry points, preserving historical sources,
contracts and evidence. This increment implements the initial evidence portion
of that choice. It does not complete native-stage adoption or public O3a dispatch.
The completed O3a diagnostic study and its results are unchanged.

New files:

- `src/dante_workflow/o3a_initial_verification.py`
- `scripts/verify_dante_o3a_initial_evidence.py`
- `tests/test_dante_workflow_o3a_initial_verification.py`

## Two deliberately distinct receipt scopes

| Selector | Successful receipt status | What is checked | What is NOT checked |
| --- | --- | --- | --- |
| `raw` | `PASS_O3A_INITIAL_RAW_INTEGRITY_ONLY` | Frozen acquisition inventory; acceptance contract's exact raw parent; preflight, ledger and manifest identities/seals; actual local HDF5 metadata, size and streamed file SHA; exact manifest/summary reconstruction | Numerical strain quality, preprocessing, encoder output, fresh scores, thresholds or current remote source |
| `acceptance` | `PASS_O3A_INITIAL_ACCEPTANCE_RECONSTRUCTION_ONLY` | Threshold contract's exact historical acceptance parent; every planned sealed block with the existing block validator; exact accepted-ledger bytes and bootstrap/tail flags; exact summary reconstruction | Raw-file-byte replay, raw/encoder score recalculation, new calibration or threshold fitting |

Raw HDF5 metadata validation means the inherited one-dimensional dataset shape
and Xspacing checks, not a new calibration/version or numerical strain-quality
certification.

Acceptance **reads stored score values** to validate finite values, their existing
float32 encoding and exact ledger reconstruction. It does not recompute them.
Its raw-parent evidence checks do not imply that actual HDF5 files were rehashed:
the separate `raw` check does that. Neither receipt may substitute for numerical
replay or be reported as `PASS_VERIFIED` for a complete scientific workflow.

Both receipts state `full_workflow_verified=false`,
`raw_score_replay_executed=false`, `encoder_executed=false`,
`threshold_fit_executed=false`, `source_fetch_executed=false` and
`historical_evidence_mutated=false`. They contain a canonical receipt digest,
exact input byte hashes and eleven source bindings: nine inherited local helper
modules, the new verification module and its CLI. Inherited contract loaders
retain their existing source/config/parent checks and EOL qualifications.
This is not a current-runtime/GPU validation or a second source fetch.

Population sizes, selection stride and bootstrap/tail geometry come from the
versioned contracts/plans. No selector, score rule or production number is newly
chosen. Initial-calibration hash stratification and native evenly spaced/context
fallback calibration remain different, unchanged historical phases.

## Execution and failure behavior

This is a repository-bound scientific-environment CLI, not a standalone installed
workflow-wheel capability. Existing scientific dependencies and frozen checkout
inputs are required. Scientific imports are lazy; the CLI disables bytecode
generation before importing the helpers. No dependency was installed here.

The interface is:

```text
python -B scripts/verify_dante_o3a_initial_evidence.py --stage raw --raw-root <existing-raw-root>
python -B scripts/verify_dante_o3a_initial_evidence.py --stage acceptance --raw-root <existing-raw-root> --external-root <existing-acceptance-cache>
```

These commands were not run against historical evidence in this increment.
The code derives the exact run directories from their existing contracts.
Windows drive and WSL mount notation are translated for path identity only;
sealed paths are not rebased to an arbitrary replacement cache or rewritten.

Output is sealed JSON on stdout only. A caller may save that output only in a
**new workflow evidence area**, never over an input or a historical receipt.
There is no output-dir, repair, freeze, resume, archive or productive execution
option. Detected failures return nonzero without creating a historical failure
file, lock, preflight, manifest, summary or compact. Missing/altered files,
duplicate identities, inconsistent metadata, partials, run failures/locks,
ambiguous JSON and escaping relative/symlink paths are rejected. Small evidence
inputs are rehashed before receipt emission to detect mid-check changes.

Read-only describes this implementation's behavior; it does not grant exclusive
access or protect inputs from another writer. Any eventual adoption must also
establish quiescent, unchanged historical evidence. No persistent snapshot or
raw numerical replay is claimed by this increment.

## Empirical coverage and remaining gates

Tests use real temporary HDF5 files, actual inherited metadata/block validators
and exact seals/hash serialization. Only validated-contract loaders are replaced
for explicitly scaled synthetic population geometry. Productive writers,
scoring and network hooks are forbidden. Success and failure tests compare all
fixture file bytes and modification times. A separate test exercises the real
local contract loaders/source pins without opening historical raw/outcome data.

Semantic negative fixtures are deliberately resealed/repinned **in tests only**
to reach reconstruction checks behind the immutable hash gate. Production
contracts and history are never repinned or modified by the implementation.
Synthetic CLI success invokes the real scoped functions in-process; subprocess
checks exercise argument rejection with observed OS return codes. This is not
an end-to-end real historical CLI replay.

Observed counts, OS exits and local source freeze are recorded in phase
08-06-SUMMARY/VERIFICATION. Full controller and existing initial-stage WSL
regressions are required, as are Ruff lint/format checks. Synthetic success does
not certify historical data availability, a clean-install full scientific run,
sensor safety or an astrophysical interpretation.

Remaining work, in order:

1. Extend separate non-mutating verification to the native stages and transitive
   parent checks, preserving their existing numerical verification.
2. Bind the complete approved O3a stage graph, preflight inputs and distinct
   receipt levels in the common controller. Keep public factory/registry gated
   until all prerequisites are met; no hash-only substitute scientific PASS.
3. Perform bounded real verification/replay and clean-install acceptance before
   declaring O3a workflow activation ready. Other runs and Virgo require their
   separate scientific/applicability/network contracts.

No historical scientific source/config/artifact was changed, no productive run
or source download was launched, and no push, release or external communication
is part of this checkpoint.

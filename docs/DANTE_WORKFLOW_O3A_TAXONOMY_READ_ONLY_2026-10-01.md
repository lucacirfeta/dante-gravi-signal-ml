# O3a retained taxonomy: exact numerical replay without history writes

## Scope and changed files

Phase 08.11 follows approved read-only architecture A and 08.10. Separate module
`src/dante_workflow/o3a_taxonomy_verification.py`, stdout-only repository CLI
`scripts/verify_dante_o3a_taxonomy_evidence.py`, 78 synthetic tests, PLAN/SUMMARY/
VERIFICATION and STATE/JOURNAL. No old scientific source/config/runner, earlier
read-only guard, historical artifact or public adapter registry is changed.

The original taxonomy execute path rewrites summary, verified compact or failure
and uses the productive primary verifier. It is never called here. The original
O4a MIL reader opens SQLite mode=ro, which alone can create WAL/SHM. The separate
reader reuses the approved standalone immutable database gate (no repair, refuse
sidecars) with the original exact SELECT, order, identity/image/vector joins and
validation. Positive and 17 corrupt fixture variants compare it with the original
reader; WAL-mode fixture proves no new sidecar creation. No scientific monkeypatch
or changed clustering input rule in the implementation.

## Frozen numerical method and parents

Only primary-scan MIL vectors enter morphology, not native INDEX embeddings or
scores. The unchanged original `build_taxonomy_rows` supplies normalization,
cosine distance, single-linkage, flat-cluster threshold and historical family
naming. All settings come from the exact original versioned contract. Every
frozen candidate enters, including BACKGROUND and AMBIGUOUS; scores/classes are
preserved but scores do not influence clustering. Original singleton ID collision
refusal remains. No retuning, new method, physical morphology assignment,
coincidence, PEM, promotion or global significance claim.

Taxonomy lock reuses the author-approved 08.10 existing-file O_RDONLY exclusive
nonblocking flock, never creating/deleting/rewriting a marker. Then the actual
08.10 read-only classification gate holds its classification/threshold locks,
replays original detector-local block-bootstrap and exact classification. Primary
summary and immutable standalone database have already been reconstructed by
the explicit upstream chain. Exact contract-declared primary/classification
metadata, seals, summary/file SHA and row digest are required.

Full canonical taxonomy JSONL bytes/SHA, labels/vector hashes, naming, metrics,
class/detector counts, entire summary and existing verified compact must equal
numerical reconstruction. They are never rewritten. The preregistered chaining
expectation and all scientific boundary fields remain exact. Thirty two executed
helper/wrapper source bindings and original reference/source files are pinned,
all inputs/sources rehashed and prior-stage guards/SQLite sidecars rechecked
before a stdout-only scoped receipt. Locks remain held through those checks
and are released before the caller receives a result. Failure/busy/partial/
unsafe/replaced evidence is refused without cleanup or repair.

## Interface

```text
python -B scripts/verify_dante_o3a_taxonomy_evidence.py --external-root <taxonomy-cache-parent> --classification-external-root <classification-cache-parent> --threshold-external-root <threshold-cache-parent> --rescore-external-root <rescore-cache-parent> --calibration-external-root <calibration-cache-parent> --index-external-root <index-cache-parent> --cohort-external-root <cohort-cache-parent> --primary-external-root <primary-cache-parent>
```

Run key derives from the original validated contract. Every parent root is
explicit; bytecode is disabled before scientific imports. No run/freeze/repair/
resume/output-file options, productive entry point, fetch or encoder operation.
The receipt states retained numerical bootstrap/classification/taxonomy replay,
not fresh raw/preprocessing/encoder score replay. It emits no score, family
metrics/counts or outcome; full-workflow and global-upstream-quiescence flags
remain false. Native Windows refuses POSIX locks before source/evidence reads.
Administrative/pure Windows tests are not native Windows scientific support.

## Empirical qualifications

New fixtures normally isolate the classification parent; a linked fixture also
executes the actual 08.10 bootstrap twice (separate detectors) and actual classify
rows before taxonomy, with RESCORE ancestry alone isolated. Its scaled decision
fixture has no image field, matched to SQL NULL under the unchanged legacy join;
it is not realistic primary image-provenance evidence. Existing unchanged upstream
gate regressions remain covered separately. Legacy taxonomy execute writes only
disposable fixture runs with parent inputs substituted, producing the expected
whole summary/compact. Exact numerical reader/builder are not substituted.

Fixtures prove preserved byte/mtime/inventory on success and refusal, original
chaining/name parity, mixed-class inclusion and score independence, corruption,
sidecar and semantic reseal refusals, lock lifetime/contention/release/replacement,
source drift, mid-read change, CLI refusal and actual frozen contract metadata
loading. Negative builder mutation/collision injection is test-only. No real
historical invocation, full-population clustering or clean-install scientific
replay was executed. Stage-local exclusion does not prove all upstream writers
quiescent or arbitrary filesystem portability; prior disposable Linux/E: lock
tests and qualifications remain unchanged.

Initial fixture corrections are recorded rather than hidden: verify-before-run
was correctly refused by the old routine; parent resealing changed run key and
initially hit missing-directory before the intended semantic check; linked fixture
initially guessed a ledger filename instead of reading its contract. Only fixture
setup changed, never old gates or production scientific parameters.

Source freeze **6b0f5a5**: three new Python files and both original taxonomy
helpers byte-identical to Git; earlier upstream EOL qualifications unchanged.
Full Windows workflow **609 PASS/114 POSIX-only skips**, OS exit 0; full WSL
workflow and original scientific/PatchProducer suites **844 PASS/three Windows-
only skips/11 upstream warnings**, OS exit 0. Ruff lint/format PASS. Timings,
fixture failures and post-freeze checks are in 08-11 SUMMARY/VERIFICATION.
User untracked artifacts/output and O3a diagnostic closure
are preserved. No installation, public activation, push, merge or release.
Next: coincidence/PEM read-only chain, then complete profile/preflight adoption,
global quiescence and bounded real clean-install replay. Full multi-run/Virgo
scientific readiness remains open.

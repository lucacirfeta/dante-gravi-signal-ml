# O3a read-only thresholds/classification: approved persistent-lock policy A

## Scope and files

Phase 08.10 implements the author's A confirmation after checkpoint def71fa.
New separate module `src/dante_workflow/o3a_decision_verification.py`, repository
CLI `scripts/verify_dante_o3a_decision_evidence.py` and synthetic regression tests.
No old scientific source/config/runner, earlier read-only guard, historical data
or public adapter registry is changed. O3a's diagnostic closure is unaffected.

## Why a stage-specific lock policy is necessary

The original threshold `_lock` creates `run.lock` and unlocks but does not unlink
it; classification shares that context manager. Presence alone does not indicate
active work. Generic earlier `_clean` continues to reject it and is not patched.
The new two-stage path instead requires the existing marker to be a safe regular
single-link file, opens it O_RDONLY/O_NOFOLLOW/O_NONBLOCK/O_CLOEXEC and holds the
original nonblocking exclusive flock for the whole verification scope. It never
creates, truncates, appends, rewrites or removes a lock. Busy, missing, unsupported,
symlink/hardlink/nonregular or replaced evidence fails closed.

Descriptor/path device, inode, size, mtime and ctime are checked before/after
acquisition and before release, including exceptions/partial acquisition cleanup.
Threshold replay holds its threshold lock throughout parent validation, numerical
replay and final rehash. Classification holds its own lock and the threshold lock
in the original order, releasing both before returning the scoped receipt.
Failure/controller markers and partial files remain refused. Stage-local flock
does not certify global upstream quiescence, exclude a noncooperating writer or
prove shared-lock semantics for arbitrary filesystems/platforms.

Disposable subprocess tests on Linux temporary storage and explicitly selected
E: DrvFS exercise contention against the original producer, release/reacquisition
and unchanged lock bytes/mtime. Target-FS files are unique temporary fixtures, not
historical lock files. Results cover this tested WSL/filesystem configuration
only, not general portability or permission to force any historical stale lock.
Native Windows lacks fcntl and is refused before sources/evidence are read.

## Exact frozen numerical verification

The threshold contract/runtime/source loaders stay unchanged. Explicit RESCORE,
calibration, INDEX, COHORT and primary roots enter the frozen 08.09 read-only
dependency gate, not old productive verifier entry points. Parent run/contract/
artifact and calibration file bindings are compared. The original pure score-row
validator checks detector-local identities/order/finite/float32-hex and complete
blocks. The original `compute_threshold` and `block_bootstrap_p99_ci` replay the
contract's block length, replicate count, seed and chunk size on calibration only.
Candidate rows can be checked by parent integrity but never enter threshold fit.
Point estimate uses all rows; bootstrap uses complete leading blocks as frozen.
Entire saved summary and verified compact must equal reconstruction, including
input/vector digests, interval, widths, population/method and scientific boundary.

Classification requires the independently replayed threshold parent and exact
original candidate-ledger hash. Original `classify_rows` reproduces every seed,
score and detector-local boundary: equality with either CI bound stays AMBIGUOUS.
Exact canonical JSONL bytes/SHA, row digest, per-detector counts, complete saved
summary and compact are reconstructed, never rewritten. No new threshold,
population, pooling, class, parameter tuning, candidate promotion or interpretation.

Twenty eight local source bindings extend the frozen chain with the original
threshold/classification/bootstrap helpers and new wrapper/CLI. Contract source/
reference hashes are tracked too; all inputs/sources are rehashed before receipt.
Pure deterministic bootstrap replay is expressly different from fresh raw strain,
preprocessing, encoder or score replay. No weaker hash-only numerical PASS.

## Interface and limited receipts

```text
python -B scripts/verify_dante_o3a_decision_evidence.py --stage thresholds --external-root <threshold-cache-parent> --rescore-external-root <rescore-cache-parent> --calibration-external-root <calibration-cache-parent> --index-external-root <index-cache-parent> --cohort-external-root <cohort-cache-parent> --primary-external-root <primary-cache-parent>
python -B scripts/verify_dante_o3a_decision_evidence.py --stage classification --external-root <classification-cache-parent> --threshold-external-root <threshold-cache-parent> --rescore-external-root <rescore-cache-parent> --calibration-external-root <calibration-cache-parent> --index-external-root <index-cache-parent> --cohort-external-root <cohort-cache-parent> --primary-external-root <primary-cache-parent>
```

Run keys derive from validated contracts. Stdout-only JSON; bytecode disabled
before scientific imports. No run/freeze/repair/resume/output-file option.
Receipts report deterministic bootstrap replay and classification replay when
applicable, deny historical mutation, raw-score/encoder/preprocessing/fetch/full
workflow and global upstream quiescence. They expose no scores, threshold values,
classes or counts. No public dispatch or installed-wheel scientific adoption.

## Test qualifications and remaining gates

New fixtures use actual temporary files/locks, real unchanged numerical helpers
and scaled contract/runtime inputs. RESCORE alone is isolated in the new suite;
explicit dependency roots and tracked input bindings are asserted. Its existing
full read-only chain remains in unchanged regression suites. Legacy `_calculate`
parity uses a fixture parent only; original classification `execute` writes only
to a separate disposable fixture with already verified inputs substituted. New
implementation never invokes or monkeypatches those productive entry points.
Snapshots cover success and failure; semantic negatives are resealed only in
fixtures. Lock replacement, platform refusal, descriptor flags, contention,
exceptions, lifetime and exact boundary rules are tested.

The first fixture put larger values in the point-only tail, causing the existing
scientific gate to reject point p99 outside its CI. It was not bypassed: that
counterexample is retained as an explicit refusal test, while the valid fixture
now meets the unchanged interval constraint. No real population was touched.

Source freeze **8da8f7b**, three new Python files byte-identical to Git. Full
Windows workflow: **579 PASS, 66 POSIX-only skips**, OS exit 0. Full WSL workflow
and retained scientific/PatchProducer regressions: **747 PASS, two Windows-only
skips, 11 upstream warnings**, OS exit 0. Ruff lint/format PASS. Exact timings,
fixture counterexample and post-freeze target appear in 08-10 SUMMARY/VERIFICATION.
Actual unchanged scientific contracts load in WSL; inherited
Windows WSL-path reconstruction refuses them. Windows administrative/pure-test
PASS does not certify POSIX locking or native Windows scientific execution.
No historical invocation, fresh score, scientific outcome, install, push, release
or user-file mutation. Next: remaining taxonomy/coincidence/PEM read-only gates,
full profile/preflight adoption and quiescent bounded real clean-install replay.
Full multi-run/Virgo scientific readiness remains open.

# Discovery 08.10: persistent lock policy requires author choice

Date: 2026-10-01. Branch: science/o3-transfer-readiness. Starting checkpoint
f6d032a; prior score-gate source freeze 2a15b32. No implementation is adopted.

## Source evidence

- `src/dante_light/o3a_native_thresholds.py`, `_lock`: `mkdir`, `run.lock` open
  `a+b`, `fcntl.flock(LOCK_EX | LOCK_NB)`, finally `LOCK_UN`; no unlink.
- Same file, `execute_thresholds`: uses `_lock` in productive and verify modes;
  parent verification rewrites RESCORE preflight, verify writes threshold compact
  and exceptions write failure. Existing entry point must not be called here.
- `src/dante_light/o3a_native_classification.py`, `execute`: same `_lock`,
  transitive threshold verification, output/summary/compact/failure writes.
- `src/dante_workflow/o3a_initial_verification.py`, `_clean`: refuses any
  `run.lock` file by existence, alongside failure/controller markers and partials.

This is a structural difference from earlier retained gates, not a scientific
threshold discrepancy. The old guard cannot distinguish an unlocked persistent
marker from active work. No guard, original runner, source, contract or artifact
was changed, no stale lock forced, and no historical outcome was opened.

## Temporary empirical probe

Command in Ubuntu WSL /home/atafe/miniconda/envs/dante_env/bin/python:

```text
python -B .gsd/phases/08-multi-run-productization/08-10-lock-probe.py
```

Observed OS exit 0. Original legacy context exits with marker still present;
existing `_clean` refuses `failure/lock evidence present: run.lock`. Opening that
temporary marker `rb` supports nonblocking exclusive flock. A separate process
using the original producer context refuses `native threshold run already active`
with exit 1; after release the producer reacquires. Lock bytes, mtime and inode
are unchanged. Temporary directory is removed by its scoped cleanup.

The subprocess's expected contention exit 1 is a diagnostic success, not a run
failure. This test uses temporary Linux filesystem storage, not E: DrvFS.
Filesystem-specific behavior and complete lifetime/path/inode tests are required
before implementing or adopting recommended A. No historical files were read.

Existing WSL threshold/classification regression: 52 PASS, observed OS exit 0,
23.99s. No production evidence or full workflow was exercised. Probe lint first
reported E402 from imports after sys.path setup; imports moved into main only,
without a lint waiver or old source edit. Final lint/format and repeated probe
results are recorded in JOURNAL.

## Decision and limitations

Recommended A is stage-specific read-only, nonblocking exclusive flock on the
existing marker for the whole verification scope, without creation/deletion or
metadata normalization. Preserve generic `_clean` for earlier stages. Refuse
busy/unsafe/replaced/unverifiable locks and test producer conflict plus release.
Alternative B retains blanket refusal and leaves historical adoption blocked.
The broader upstream quiescence/replay gate remains open in either case.

Executor/AGENTS stop-and-ask applies because validation of active versus retained
lock state is a structural safety policy, not an incidental coding convenience.
No new adapter is implemented before author choice. Threshold/bootstrap and
classification numerical methods remain exactly the frozen contracts.

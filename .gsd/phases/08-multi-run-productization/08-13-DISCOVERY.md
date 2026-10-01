# Discovery 08.13: native PEM writer exclusion is not inherited

Date: 2026-10-01. Branch: science/o3-transfer-readiness. Starting checkpoint
8608bda. Audit only; no new PEM adapter or safety policy is adopted.

## Source evidence

- `src/dante_light/o3a_native_pem.py`, `run_native_pem` (line 542): creates the
  run directory and writes targets, event/calibration evidence, output ledgers
  and summary; purges transient strain files. There is no surrounding lock.
- `scripts/run_dante_o3a_native_pem.py`: invokes the original functions directly;
  no wrapper-level locking protocol.
- Targeted search for `fcntl`, `flock`, `run.lock`, `controller.lock` and
  `filelock` in those two sources returned no matches. Atomic JSON publication
  is not a cooperative writer-exclusion protocol.
- `verify_native_pem` (line 621) validates retained event/calibration evidence
  and reconstructs the verified compact. If the compact is missing, it writes
  it. It is therefore not an acceptable read-only entry point for this adapter.
- `_verify_event` checks retained calibration thresholds, channel/coherence
  ledgers and the unchanged tier decision helper. It does not independently
  recompute coherence or the null distribution from raw sensor samples.

The approved 08.10 persistent-lock policy is effective against producers that
consult the same lock. Creating or holding a new PEM lock that the historical
producer does not consult would not establish writer exclusion. A final hash
comparison is a mutation check, not proof that concurrent writers were excluded.
Process absence at a single instant is not exclusion across an entire replay.
Do not silently reuse A, invent a lock, delete markers or change frozen sources.

## Checks performed

Original WSL native PEM regression:

```text
python -B -m pytest -q --tb=short tests/test_dante_o3a_native_pem.py
7 passed, 11 upstream warnings in 7.47s; observed OS exit 0
```

The suite includes an optional real-parent metadata preflight when the external
root is present. This must not be described as wholly synthetic or as reading
no historical metadata: its selection checks read frozen classification and
coincidence ledgers. It does not open PEM outcomes or strain for that preflight.
Numerical raw-context tests use temporary fixtures. No productive historical
PEM execution, download, new measurement or original verifier was invoked by
the audit. Test success does not certify full workflow readiness or quiescence.

## Author decision required

Recommended A: design a separate, sealed evidence-snapshot verification mode.
Specify capture quiescence, complete parent/source bindings, isolation from the
original producer, read-only enforcement, mutation/refusal tests and the exact
scope of its receipt before implementation. A copied directory or its seal
alone is insufficient. Preserve original scientific contracts and historical
evidence. This would certify retained-evidence consistency in the isolated
snapshot, not fresh sensor/null replay or live historical writer exclusion.

Alternative B: leave PEM adoption blocked until a separately versioned producer
and verifier share an approved exclusion protocol. Do not retroactively patch
the frozen producer or reinterpret existing runs under that new protocol.

Neither option changes thresholds, channels, target population or scientific
interpretation. Neither is implemented without author approval. Generic guards
and the completed 08.10-08.12 gates remain unchanged. Full multi-run/Virgo
scientific readiness, global quiescence and clean-install replay remain open.

Executor Rule 4 and AGENTS stop-and-ask apply: this changes validation of the
evidence lifetime, not merely implementation detail. Next step is the author's
quiescence choice, followed by a checked plan and synthetic tests before any
historical PEM evidence replay.

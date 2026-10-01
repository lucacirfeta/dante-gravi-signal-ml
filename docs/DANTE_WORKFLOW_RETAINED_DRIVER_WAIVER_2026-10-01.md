# Explicit driver-metadata waiver for retained O3a replay

## Author decision and scope

After the 08.15 refusal on NVIDIA driver 616.92 versus 617.14, the author said
`lascia perdere la versione nvidia` on 2026-10-01. This is implemented as an
explicit opt-in for read-only retained O3a evidence, not acceptance of a new
productive runtime or a driver numerical-equivalence claim.

Versioned policy:
`config/dante_workflow_o3a_retained_driver_waiver_v1.json`.
Separate helper: `src/dante_workflow/o3a_retained_runtime.py`.
Only the coincidence and PEM-snapshot independent CLI/API expose
`--allow-retained-driver-drift` / `allow_retained_driver_drift=True`.
Absent the flag, the original strict current-runtime comparison still runs.
There is no implicit global environment setting or productive option.

## Exact validation change

The shared per-invocation evidence object carries the qualification through the
seven existing read-only runtime checks: scan, cohort, INDEX, calibration,
RESCORE, thresholds and coincidence. Existing original loaders still validate
all static frozen runtime/encoder/authorization contracts. For the explicit
opt-in only, the separate helper compares the current captured environment.

Both environment digests must be valid. The comparison normalizes exactly
`cuda_device.driver_version` to the historical value, then recomputes the derived
digest; every remaining field and JSON type must match exactly. Python binary,
packages, OS, Torch settings, CUDA runtime, device capability/name/count and
device request are NOT waived. Missing/invalid driver metadata is not accepted.

The original frozen object is returned for old run keys and parent identities;
neither frozen environment nor original scientific artifacts are rewritten.
The actual driver and digest are reported separately in the new receipt, along
with policy SHA256, the explicit waiver and false equivalence/production/fresh
measurement/full-workflow flags. During one replay the entire observed runtime
must remain unchanged, including driver metadata, at all parent/final checks.
The policy file is hash-bound and rechecked with other inputs.

## Unchanged scientific boundary

No original `src/dante_light` source or scientific runtime config is changed.
Productive loaders continue to reject driver drift. No raw/encoder scoring,
sensor coherence, fresh PEM null calibration, channel expansion, threshold
tuning, population change, historical repair or downloader is authorized by
this waiver. Existing retained parent checks, including deterministic threshold
bootstrap from retained scores, remain the already approved read-only method.
No monkeypatch of original scientific globals is used in implementation.

The source inventory now also binds the executed runtime-capture implementation
`src/dante_light/o4a_corrected_runtime.py` and the new retained helper, yielding
46 source bindings in the PEM-snapshot adapter (39 in coincidence). This does
not imply that historical EOL-qualified source bytes equal Git blobs verbatim.
Original LF-to-CRLF qualifications remain; no normalization is performed.

## Live runtime-only observation

The new helper was exercised in the real existing WSL Python environment and
returned OS exit 0 / `PASS_RETAINED_RUNTIME_QUALIFICATION_ONLY`:

- frozen driver 616.92 / observed driver 617.14;
- frozen environment 582a9b99f689d36f126b75f95dd31763c2b399aab03180f06c9838eb1f8f1b58;
- observed environment ebeae01fdbad49d252555e354daba1e69282ddfcdd89ee386ceeb3c184fb474f;
- policy file SHA256 a1a8b5ea12ba3cba6a9d5b7ccd8577db79adb995f27fc9eb8c89dde7f28b504e;
- other runtime fields match; numerical equivalence and full-workflow proof false.

This runtime-only check is not a complete parent-chain replay. Tests, source
freeze and the subsequent real parent-preflight outcome are recorded below when
observed. The missing actual real PEM snapshot remains a separate next gate.

## Validation and source freeze

Source freeze **e9a256a**. New helper/policy/30-test file, opt-in wiring in the
separate readers/CLIs, source-binding count updates in seven existing test files,
and exact LF attributes for the two new policy/test files only. The 20 files in
that source commit are byte-identical to their Git blobs after freeze.

WSL workflow + original O3a contract/native PEM/PatchProducer suites:
**992 PASS, 7 skips, 11 upstream warnings, OS exit 0, 534.76s**.
Windows workflow + original O3a contract suites:
**758 PASS, 220 platform skips, OS exit 0, 330.87s**.
Post-freeze qualification + original contract: **40 PASS**, WSL OS exit 0/5.10s,
Windows OS exit 0/5.60s. Ruff lint and four-file format checks PASS.

Synthetic qualification tests prove rejection of non-driver changes, corrupt
digests, absent metadata, changed policy, mid-replay runtime drift and nonboolean
opt-in. Original productive runtime rejection is exercised, not merely assumed.
AST wiring and synthetic CLI argument tests are not a complete scientific parent
certificate; existing default read-only fixtures retain their isolation limits.

Original contracts.py, coincidence_physical.py and pem_coherence_analysis.py
still require their documented exact Git LF-to-CRLF reconstruction qualification.
Original runtime-capture implementation and O3a native contract equal Git bytes;
the frozen runtime file remains SHA256
3b00a0bf258cc96870971481138e10e7e85deb97a1c3c49c470626e3153d0ef2.
No normalization, productive source edit, runtime refreeze or push performed.

## Actual parent retry and next independent blocker

After source freeze the actual coincidence CLI was invoked once in canonical
WSL Python with all nine explicit native external roots and
`--allow-retained-driver-drift`. A read-only supervisor captured its stdout and
propagated the observed CLI OS exit **1** (session 84328):

```json
{"error":"failure/lock evidence present: run.lock","error_type":"InitialEvidenceError","observed_cli_os_exit_code":1,"status":"FAIL_CLOSED_O3A_COINCIDENCE_EVIDENCE"}
```

The driver check is no longer the refusal. The actual nested gate order reaches
COHORT before its SCAN parent. A read-only contract-derived path probe confirms
the earliest cohort directory:
`E:/dante_cache/dante_light/o3a_native_v1/native_cohort_876508390ba7f1eddf2c50342870e7e8880048b243f545487039974b51df9a2c`.
It has a safe nonsymlink 4-byte run.lock, no failure/failures/controller marker.
The original producer uses flock, then releases it without unlinking this file.
The earlier generic reader rejects mere file presence. Other original native
producers (SCAN, INDEX, RESCORE) likewise have persistent cooperative locks.

A **diagnostic only** invocation of the already-tested read-only lock helper on
this real cohort file acquired/released an exclusive nonblocking flock with OS
exit 0. Bytes, size, inode and mtime were unchanged. This demonstrates that this
file was lockable at that moment, not ongoing/global producer exclusion or a
successful whole-chain replay. It does not adopt a new cohort reader policy.

08.10 author approval was explicitly stage-local to thresholds/classification;
taxonomy/coincidence later reused it in their own increments. Extending that
validation policy to earlier native parents is a separate structural decision.
No old lock/guard was deleted, ignored, rewritten or automatically widened here.
Recommend the same read-only held-flock protocol, tested against the respective
producer and E: filesystem, through the whole ancestor scope. Await author
confirmation before that implementation. No real capture plan/archive or
complete PEM parent-chain certificate exists yet; all-run/Virgo readiness open.

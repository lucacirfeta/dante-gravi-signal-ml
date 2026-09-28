# O3a/O4a common PEM: frozen background-span replay

Status: **source frozen; real plan preflight running; no full-span PASS or
comparative PEM outcome claimed**.

The prior transport-only frame gate is `PASS_VERIFIED_BACKGROUND_FRAME_BYTES_V2_ONLY`:
47 O3a and 278 O4a public HDF5 frames, 325 sealed receipts, standalone
verifier exit 0. The v1 frame-start-probe failure remains preserved.

The next gate is a separate full numerical replay of the already frozen 12
O3a and 65 O4a historical four-hour background spans. It uses only the
previously acquired frame bytes and the published manifest metadata; its
producer refuses missing or changed files and never downloads. Each span
gets a sealed sample digest and frame-identity receipt. The independent
verifier rereads the complete used intervals and checks those digests,
source metadata and parent frame SHA-256 bindings. Target identities,
span selection, detector split and scientific method are unchanged.

The versioned contract, runner, streaming producer and synthetic tests were
frozen in commit `97b30b2` on `science/o3-transfer-readiness` before the
real plan. WSL O3a/O4a PEM/provenance regression: **72 passed**, 11 upstream
GWPy/Matplotlib warnings; Ruff lint/format passed. The tests include
cross-frame digest agreement with the separate historical reader, missing
or altered frame rejection, out-of-span nonfinite samples, target identity
and parent-SHA mismatch rejection.

The real `--stage plan` is running under one WSL controller invocation. It
first independently replays the parent frame verifier and will fail closed
if any source, receipt, selector or hash differs. Only after a plan PASS may
the separate `--stage run` start under that exact new run key. Long-running
work is monitored hourly; no duplicate controller is permitted.

This gate covers background **strain samples only**. Event/background
auxiliary-channel receipts, the five-channel null, paired PEM verdicts,
global significance and astrophysical interpretation remain unopened.

# O3a/O4a common PEM: frozen background-span replay

Status: **full background-strain span replay PASS_VERIFIED; no comparative PEM
outcome opened**.

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

The real `--stage plan` completed with exit 0 and
`PASS_BACKGROUND_SPAN_PLAN_ONLY`, after independently replaying the 325-frame
parent verifier. Its sealed run key is
`034102715295eec0a8937fb67233d7515933addeb98bee35fbe9d3aac3566c0d`;
the external run directory is
`E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/background_span_replay/background_spans_034102715295eec0a8937fb67233d7515933addeb98bee35fbe9d3aac3566c0d`.
The separate `--stage run` wrote 77 sealed span receipts and a
`PASS_BACKGROUND_SPAN_REPLAY_COMPLETE_ONLY` summary with receipt digest
`0139a9963ca5ff5a2f35ca34435f2dab6ee35ef62b44ea9bb2303a4870534661`.
Its launcher did not retain the OS exit code; no such code is claimed.

The first standalone verifier wrote `PASS_VERIFIED_BACKGROUND_SPANS_ONLY` for
77 spans but its supervisor did not retain the OS exit code. A second,
read-only invocation of the same frozen verifier was therefore performed:
it returned **exit 0** and the same `PASS_VERIFIED_BACKGROUND_SPANS_ONLY`
with `span_count=77`. Both verifier stderr logs are empty. There are exactly
12 O3a and 65 O4a receipts, no failure artifact, lock or partial file, and
all three new source SHA-256s match the sealed plan. Post-run WSL
O3a/O4a PEM/provenance regression: **72 passed**, 11 upstream warnings;
Ruff lint and format passed. Tracked Git files are clean.

This gate covers background **strain samples only**. Event/background
auxiliary-channel receipts, the five-channel null, paired PEM verdicts,
global significance and astrophysical interpretation remain unopened.

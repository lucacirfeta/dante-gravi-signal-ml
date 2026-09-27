# O3a/O4a common-five-channel PEM: background frame acquisition

Status: **transport-only acquisition in progress; no paired PEM measurement or outcome opened**.

The source-frozen acquisition adapter is committed as `5922fac` on
`science/o3-transfer-readiness`. Its plan independently replays the frozen
historical four-hour span selection using each run's complete candidate
exclusion ledger, checks the bound public manifest SHA-256s, and deduplicates
the required official frames. The live plan completed with 47 O3a and 278
O4a unique frames, matching the prior coverage preflight. Its sealed run key is
`5308cec1e4d935cdd5b7c93b4df60369e9814fc2a63fe0741c8208abb40edb9e`;
the external run directory is
`E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/background_acquisition/background_acquisition_5308cec1e4d935cdd5b7c93b4df60369e9814fc2a63fe0741c8208abb40edb9e`.

For each frame, the transport stage requires the published MD5, frozen HDF5
detector/calibration metadata and geometry, SHA-256 of the file bytes, and an
independently replayed one-second numerical probe before writing a sealed
per-frame receipt. Existing receipts are reverified before reuse; a second
controller is refused. Infrastructure failures must be classified and archived
before same-run-key continuation. Structural/provenance failures stop the run.

The stage's eventual `PASS_VERIFIED_BACKGROUND_FRAME_BYTES_ONLY` will establish
official frame-byte provenance, **not** full four-hour numerical-span replay,
auxiliary-channel provenance, a five-channel null, a PEM verdict, global
significance, or astrophysical interpretation. Those are separate open gates.

Pre-run verification: 41 combined targeted O3a/O4a common-PEM tests passed in
WSL, with 11 upstream GWPy/Matplotlib warnings; Ruff lint and format passed.
The source-frozen `--stage plan` exited 0. The `--stage run` worker was started
once at 01:15 Europe/Rome on 2026-09-28; it remains subject to the hourly
health monitor and an independent standalone `--stage verify` after completion.

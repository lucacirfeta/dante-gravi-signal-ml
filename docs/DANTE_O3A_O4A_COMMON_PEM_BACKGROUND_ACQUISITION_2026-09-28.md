# O3a/O4a common-five-channel PEM: background frame acquisition

Status: **v1 FAILED_STRUCTURAL and preserved; v2 transport-only acquisition
running, with no paired PEM measurement or outcome opened**.

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
once at 01:15 Europe/Rome on 2026-09-28. It stopped after 14 sealed frame
receipts with `FAILED_STRUCTURAL`: its one-second numerical probe was fixed at
the official **frame start**, but the next O3a L1 frame starts at GPS
1238540288, outside its earliest selected background span, which starts at
1238542865. The published frame MD5 and the numerical second *inside* that
span were checked separately; the frame-start second was nonfinite. This is a
validation-location defect, not a PEM outcome. The v1 failure, plan, frame
bytes, receipts and logs remain unchanged and must not be resumed.

The separately versioned v2 contract
`config/dante_o3a_o4a_common_pem_background_acquisition_v2.json` changes only
the transport probe location: for each required official frame, use the first
one-second overlap with any frozen selected span of the same detector, choosing
the earliest overlap if several spans use the frame. The location depends on
the frozen span plan, **not** on the samples or a search for finite values.
It still checks the public MD5, HDF5 metadata, full-file SHA-256 and independent
numerical replay of that second. It does not change the 77 background spans,
325 frames, exclusion populations, PEM statistic, channel set or any
scientific output. The new run key is distinct; the original failure is
preserved. Before real execution, the v2 and adjacent common-PEM synthetic
suite passed 43 tests (11 upstream warnings), including a frame whose first
second is invalid but selected-span probe is valid. Full-span and downstream
gates remain open.

The v2 source freeze is commit `ad9373f`, pushed to
`science/o3-transfer-readiness` before productive execution. The real
`--stage plan` exited 0 and bound 47 O3a plus 278 O4a frames under new run key
`7d21f9c38e8b29a5029d604528b78e1f5f7e30c48bf3870a414890dd7aa29e95`.
The formerly failing L1 frame now probes `[1238542865, 1238542866)`, inside
the frozen span; all plan source hashes match current bytes. An initial WSL
launcher used `/mnt/e/...` for the CLI `--run-dir`, which the existing
Windows-path converter rejects before acquiring a lock, frame or receipt; its
stderr is retained. The corrected launcher uses `E:/...` and has one live WSL
process. The hourly monitor is active. Neither launch is evidence of a PASS
until the standalone full-frame verifier succeeds.

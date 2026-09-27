# O4a PEM raw replay: GWOSC URL correction (2026-09-27)

The approved O3a/O4a five-common-channel comparison remains diagnostic-only.
No paired PEM measurement or new candidate verdict has been opened.

The input-only v1 freeze in `config/dante_o3a_o4a_common_pem_v1.json` remains
unchanged. Its first official-frame acquisition attempt is preserved at
`E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/raw_replay/raw_replay_4b72598116a88db262762a48fd11135f00ad0ede8968f7ec0dae116e038084be`.
The launcher stderr is
`E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/raw_replay.worker.stderr.log`.
It stopped on HTTP 404 before any frame or target was verified: no
`progress.json` or `summary.json` exists and the frame count is zero. The
manifest snapshot is retained. Do not resume or modify this v1 run.

The published checksum manifest uses `H1/epoch/file.hdf5` or
`L1/epoch/file.hdf5`, while the public GWOSC download URL uses
`epoch/file.hdf5`. A direct HEAD check of a representative manifest entry
returned 404 for the detector-prefixed URL and 200 after removing exactly
that leading component. This is a transport mapping error, not a missing
strain interval or a revised scientific population. The v2 preflight checks
the first required H1 and L1 archive URLs independently.

The new `config/dante_o3a_o4a_pem_raw_replay_v2.json` has digest
`8d8708ce5a809ee3259dfff4d14222a67ecfac5d5b2f59fb2bcfbd2c81690df0`.
Its validator requires every v1 scientific/source/provenance/output field to
remain identical, with only the explicit
`REMOVE_LEADING_DETECTOR_DIRECTORY` URL policy added. The v2 comparative
addendum `config/dante_o3a_o4a_common_pem_v2.json`, digest
`76bf71c828afbc79da2864fa7f3d7dc8ea805057a6e4e8173b6c89634bbb203e`,
binds the unchanged v1 input freeze, v2 contract, source bytes and this exact
change scope. The v1 adapter, CLI, contracts and failed run remain untouched.
The v2 run key includes its new contract digest, so the failed v1 directory
cannot be reused.

The local receipt still stores the complete manifest relative path; only
the public fetch URL omits the detector component. The same published MD5,
recorded SHA-256, HDF5 release/calibration metadata, gap-free GPS coverage
and exact 40-second float64 context hash for **every** historical target are
required before PASS. The historical local HDF5 whole-file SHA is recorded
but not asserted equal to a newly acquired official file.

Before full acquisition, WSL `dante_env` checks:

- Full v2/v1 raw replay, comparative-input, O3a/O4a PEM and provenance
  regression suite: **43 passed**, 11 upstream deprecation warnings;
  malformed URLs and re-signed scientific changes fail.
- Ruff lint and format: PASS on the three new Python sources and v2 test.
- `--stage preflight`: exit 0,
  `PASS_O4A_PEM_RAW_REPLAY_V2_PREFLIGHT`, 65 target contexts / 64 frames,
  published manifest SHA-256
  `531912260ea45cd5265198f7a1990a8a89f69ffa98abca8a21930140e332b7ba`,
  and HTTP HEAD 200 for one required H1 and one required L1 frame; neither
  strain nor PEM outcomes was opened.

Complete 65-target numerical replay, independent `--stage verify`, and the
paired five-channel PEM runs remain separate downstream gates. No global
significance or astrophysical claim follows from this URL correction.

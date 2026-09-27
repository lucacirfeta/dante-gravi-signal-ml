# O4a PEM numerical-context replay verified — 2026-09-27

The versioned O4a raw-replay v2 run is complete and independently verified.
Its canonical external directory is
`E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/raw_replay/raw_replay_fb2af10f4feff811cd624526444d6890c610e5bf5a1c23bc4fc4d25bd16eb457`.
The source freeze is commit `d0951fa`; comparative input-addendum digest
`76bf71c828afbc79da2864fa7f3d7dc8ea805057a6e4e8173b6c89634bbb203e`
and raw-replay contract digest
`8d8708ce5a809ee3259dfff4d14222a67ecfac5d5b2f59fb2bcfbd2c81690df0`
match the versioned contracts. The former v1 HTTP-404 run remains preserved
and was not resumed.

The producer summary is `PASS_COMPLETE_O4A_PEM_RAW_REPLAY_V2`: 64 official
O4a 4 kHz R1 frames and all 65 historical PEM target contexts accounted for.
Its frame and target receipts have SHA-256
`9ea51b3547d77870677e37c1079d39ceecb1e81ae927f2ffd8a8790647668d88`
and
`2a5f5bca0ebb458a65885e207273b447bfcfee20f81bb69b4fb5534cf23c5213`,
respectively; the published checksum-manifest snapshot has SHA-256
`531912260ea45cd5265198f7a1990a8a89f69ffa98abca8a21930140e332b7ba`.
The v2 producer log has empty stderr. The producer launcher did not retain an
independent OS exit-code receipt, so no such code is claimed.

The separate WSL `--stage verify` invocation exited **0** with
`PASS_VERIFIED_O4A_PEM_RAW_REPLAY_V2`. It revalidated each official-frame
MD5 against the frozen manifest, HDF5 release/calibration metadata and
recorded SHA-256, then recomputed all 65 exact 40-second float64 context
hashes against the immutable historical target ledger. One mismatch would
have failed closed. This is numerical equality of the measured contexts,
**not** byte identity of the historical local HDF5 containers.

Post-run checks: combined v2/v1 raw replay, comparative-input, O3a/O4a PEM
and provenance suite **43 passed**, 11 upstream deprecation warnings, exit
0; Ruff lint and format PASS on all v2 Python sources/tests. Runtime source
and contract files remain byte-identical to commit `d0951fa`.

This closes the numerical-context portion of execution gate 2. It does not
calculate a new PEM coherence, null, verdict, O3a/O4a comparison or global
significance. Before any real paired result, independent O3a/O4a adapters
must be tested against the same five-channel measurement core and the gate-3
checks in `07-20-PLAN.md` must pass. Historical O4a PEM verdicts are not
reinterpreted or overwritten. No astrophysical candidate is promoted.

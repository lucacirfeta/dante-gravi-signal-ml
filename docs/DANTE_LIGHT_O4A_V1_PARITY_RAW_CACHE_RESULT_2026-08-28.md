# O4a v1 parity raw-cache result

Status: **COMPLETE**.

The frozen parity manifest identifies 169 padded 40 s inputs that are not
contained in any single HDF5 file of the immutable O4a mirror. All 169 are now
available in the separate parity cache:

- 162 were reconstructed from two adjacent, content-hashed local HDF5 files;
- 7 were fetched from GWOSC open data;
- 0 failed CAT1, hardware-injection, sample-rate, finite-value, coverage, or
  content-integrity validation;
- the resulting cache contains 169 HDF5 files (213,619,098 bytes).

The external complete summary has SHA256
`7bbe9501042564e870d0fa13304d799c8532870ad23574fecaca9dad513abb79`
and run key
`2ea63d5ac8ee9fb80f8c4465421caf425db6f84a97940cdd7c0c9450c589f004`.
The portable compact record is
`artifacts/dante_light/o4a_v1_parity/raw_cache_summary.json`.

Three valid files downloaded during the initial pre-stitch smoke/interrupted
run were moved, with their records, to the recoverable external directory
`archive/pre_stitch_provenance`. They were rebuilt from the verified local
mirror so the final origin ledger is unambiguous: 162 local stitches and seven
GWOSC fetches.

This closes input availability only. It does not constitute a score, taxonomy,
or scientific-result PASS.

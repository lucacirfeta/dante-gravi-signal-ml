# Changelog

All notable changes to DANTE are documented in this file. Historical releases
remain available through their immutable Git tags and archived records.

## [3.8.0] - 2026-09-09

### Added

- Installable `dante-workflow` orchestration package with shared CLI and
  browser controllers.
- Content-derived workflow identity, durable leases and attempts, hash-checked
  resume, fail-closed stage verification, and readable aggregate receipts.
- A bounded public CPU smoke workflow that downloads two public GWOSC windows
  and explicitly does not represent a corrected-O4a recomputation.
- Public installation, quickstart, contribution, governance, support, conduct,
  and clean-environment reproduction documentation.

### Changed

- Adopted and re-verified the existing corrected-O4a 15-stage workflow
  artifacts without changing their scientific scores, populations, thresholds,
  null constructions, detector semantics, or conclusions.
- Updated repository licensing from Apache-2.0 to GPL-3.0-only. Historical
  archives retain the license metadata shipped in those immutable versions.
- Prepared package and citation metadata for the `v3.8.0` archival release.
  The 3.7.0 version DOI remains historical and is not assigned to 3.8.0.

### Verification

- 126 workflow tests passed on Windows.
- 125 workflow tests passed on WSL, with one expected Windows-only skip.
- A public HTTPS clean clone completed isolated installation, CPU smoke,
  explicit verification, idempotent reuse, UI discovery, and 14 focused tests.
- GitHub-hosted CPU smoke and artifact-contract CI passed.

## [3.7.0] - 2026-08-13

- Archived scientific software baseline: <https://doi.org/10.5281/zenodo.21912589>.

[3.8.0]: https://github.com/lucacirfeta/dante-gravi-signal-ml/compare/3.7.0...v3.8.0
[3.7.0]: https://github.com/lucacirfeta/dante-gravi-signal-ml/tree/3.7.0

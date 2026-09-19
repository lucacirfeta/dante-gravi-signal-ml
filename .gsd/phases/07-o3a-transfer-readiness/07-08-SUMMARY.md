---
phase: 07-o3a-transfer-readiness
plan: 08
completed_at: 2026-09-19
---

# Summary: O3a atomic raw downloader

## Results

- Downloaded and verified all 726 frozen GWOSC O3a 4 kHz HDF5 source frames:
  365 H1 and 361 L1, totaling 91,020,453,453 bytes.
- Published a 726-row PatchProducer-compatible raw manifest only after all
  source frames passed size, HDF5 metadata, and SHA-256 verification.
- Replayed the complete verification twice with zero network bytes and
  identical run, preflight, ledger, manifest, and artifact digests.
- No strain values, scores, classes, thresholds, or outcomes were inspected.

## Canonical evidence

- Run key:
  `b6f43f84cde717eed478947ac4fccaa0f6fd5f5b16fc2740521fcca5f94b9f9f`
- Status: `PASS_VERIFIED_RAW_DOWNLOAD`
- Acquisition digest:
  `25b68454e191bc45ec55a7edef65a586d73258f6654523b6eeedb4488d0b103d`
- Preflight digest:
  `78c662f33bb0c87820762b6e22b9cd082fc2e731038921102ce2ba7317e4e79a`
- Verified-ledger SHA-256:
  `6dfc1ae7b0b6889c819c97ce623434abaf115190a4b709dce3e6510194ef3690`
- Raw-manifest SHA-256:
  `9a60a2990cdee999e48d919bf20adf2ae5c5decd5a954440bd682c2ced7a6926`
- Artifact digest:
  `fbbf97bb9a4a38d0fce18cea8c2799f1b292bfb744e1d607206d7e3c8a17d0a1`
- Failures and residual `.part` files: zero.

## Deviations applied

- [Rule 1 - Bug] A post-completion replay exposed that the initial
  implementation could overwrite attempt-local preflight and transport
  metadata under the same run key. Raw bytes and the scientific raw manifest
  remained identical. The affected historical run directories were retained.
- Preflight evidence is now immutable for a run identity, and the canonical
  verified ledger excludes attempt-local transport labels. The implementation
  change produced a fresh content-derived run key and was committed and pushed
  before the canonical verification run.

## Verification

- First canonical run: 726/726 verified, zero failures, zero network bytes.
- Immediate full replay: byte-identical digests for preflight, ledger,
  manifest, and summary artifact.
- Windows focused O3a/PatchProducer suite: 52 passed.
- WSL focused O3a/PatchProducer suite: 52 passed, 11 upstream warnings.
- WSL Ruff: passed.
- Git whitespace check: passed.

## Next gate

Perform block-atomic raw acceptance for the 590 provisionally selected O3a
initial-calibration blocks. This next gate may open only the named raw blocks
and must remain upstream of threshold fitting, classification, and candidate
review. Native-index selection remains a later, separate gate.

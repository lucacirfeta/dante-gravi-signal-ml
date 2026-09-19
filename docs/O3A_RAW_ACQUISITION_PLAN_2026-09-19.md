# O3a raw-source inventory and acquisition plan

Date: 2026-09-19

## Result

The public GWOSC O3a 4 kHz HDF5 file inventory and the exact source files
needed by the provisional initial-calibration blocks are frozen and verified.
This checkpoint used file metadata only: it downloaded no HDF5 bytes, opened
no strain file, and inspected no score, class, or scientific outcome.

## Frozen source inventory

- Provider/API: `GWOSC`, `gwosc.locate.get_urls`.
- Dataset: `O3a`.
- Detectors: `H1`, `L1`.
- Sample rate/format: 4096 Hz HDF5.
- Query bounds: the detector-specific first-to-last extent of the frozen
  public `CBC_CAT1` segments.
- H1 inventory: 3,051 source frames.
- L1 inventory: 3,266 source frames.
- Inventory digest:
  `7ea4fb89cdc71f02f6cb00dc09ffb0bfcc4270ffed94649c96af95fc646ddf36`.

The checked-in inventory stores the normalized public URL for every source
frame; filename, GPS interval, and duration are deterministically parsed from
that URL and verified by the loader. It does not claim a content hash: that
hash can only be assigned after the exact file has been downloaded and
verified.

## Initial acquisition scope

The acquisition plan covers the 295 provisional rank-zero blocks per
detector frozen by the initial-calibration selector. For each 17-window block,
coverage extends from four seconds before the first 32 s analysis window to
four seconds after the last one. The minimum covering GWOSC frame set is:

- H1: 365 unique source frames.
- L1: 361 unique source frames.
- Total: 726 detector-specific source frames for 590 provisional blocks.
- Acquisition-plan digest:
  `25b68454e191bc45ec55a7edef65a586d73258f6654523b6eeedb4488d0b103d`.

The planned raw root is `E:\o3a` (`/mnt/e/o3a` in WSL). Downloads must use a
`.part` file and an atomic final rename. Reuse of an existing file is allowed
only after its final SHA-256 matches the eventual verified raw manifest.

## Fail-closed boundary

This freeze does **not** authorize download or raw execution. It includes only
the provisional rank-zero blocks. If block-atomic validation rejects one of
them, the already frozen selector still requires the next hash-ranked block
from the same stratum. The additional source files must be named in a
versioned acquisition-plan extension before they are downloaded; no
cross-stratum replacement is permitted.

The next increment is an operational downloader and disk-space preflight that
preserves this plan, verifies every completed file, and writes the final raw
manifest atomically. Raw acceptance and scoring remain separate later gates.

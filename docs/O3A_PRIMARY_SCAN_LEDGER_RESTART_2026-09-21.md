# O3a primary-scan ledger correction and clean restart

Date: 2026-09-21

## Trigger and preserved evidence

The host powering off interrupted primary-scan run
`primary_scan_9c7a7790a3952e12975deee884497b4747018cac896cb4eb3ab94d9836b90e54`
after 263,168 of 722,911 window rows had been committed. SQLite passed its
integrity check and no transient raw file remained. The interrupted run is
preserved in place and is not reused by the replacement run.

The first resume attempt stopped fail-closed before committing another window.
Its verified failure artifact has digest
`ee709fa7663c6bf46e0364c54b7aa32bcfa376e4ae3d5bfbd234ecfc05e5f46d`
and records `STRUCTURAL_OR_SCIENTIFIC_FAILURE` caused by a duplicate
`raw_frames` primary key.

## Root cause and scope

`_insert_frame` used a positional `INSERT INTO raw_frames VALUES(...)` while
the tuple was ordered as detector, filename, GPS start, GPS end, and remaining
provenance fields. The table schema ordered GPS start and GPS end before the
filename. SQLite accepted the shifted values because of dynamic typing; a
resume then tried to insert a frame whose malformed primary key was already
present.

The defect affected the raw-frame provenance ledger. It did not alter the
window identity, preprocessing, encoder, score, threshold, or candidate-row
write path. Nevertheless, no partial scientific row is adopted because the
selected remediation is a complete clean rerun under a new provenance-bound
contract and run key.

## Correction and verification boundary

- Raw-frame inserts name every destination column explicitly.
- Resume remains idempotent and rejects changed frame provenance.
- Final verification now reconstructs the exact required frame population and
  checks detector, GPS interval, filename, URL, SHA-256 form, positive size,
  and retained-raw flag for every ledger row. A count-only ledger can no longer
  pass.
- Regression tests reproduce the shifted positional ledger and require the
  verifier to reject it.
- Scientific populations, detector-specific p99 thresholds, preprocessing,
  scoring, CUDA execution parameters, and visibility gates are unchanged.

The replacement frozen contract digest is
`e069c93b89498e2375144ace1285d5a68c21cba4fb0acf56dbbb6ae2b653d1e5`.
Its real HDF5 plus CUDA preflight passed under run key
`8f0424e5f3ea2b94449eaddb0e1ccf61c5fd7ba91d54c839bfa89d0e26efad35`.

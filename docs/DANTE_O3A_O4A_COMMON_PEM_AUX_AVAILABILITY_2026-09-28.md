# O3a/O4a common PEM: auxiliary metadata preflight

Status: **NDS2 event/background availability metadata PASS_VERIFIED; no
auxiliary sample or PEM outcome verified**.

The verified full-background-strain parent is
`E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/background_span_replay/background_spans_034102715295eec0a8937fb67233d7515933addeb98bee35fbe9d3aac3566c0d`.
Its standalone verifier returned exit 0 and
`PASS_VERIFIED_BACKGROUND_SPANS_ONLY` for 12 O3a and 65 O4a frozen spans.

This next, independent gate queries only NDS2 **availability metadata** at
`nds.gwosc.org`. For every frozen target it checks the exact five
detector-local channels in the versioned common-PEM contract over both the
event interval and its already selected four-hour background interval. The
event duration is read from that contract. An omitted, renamed, duplicate or
partially covered channel fails closed. The plan replays the strain parent
verifier; the final verifier independently queries the same metadata again.

Success requires the exact frozen 77 target identities, a sealed receipt per
target containing both intervals, no failure/partial/lock, and standalone
verification with exit 0. The source and contract must be frozen before the
first full metadata query. Synthetic guards and the O3a/O4a PEM regression
suite must pass first.

This is **not** an auxiliary-sample receipt. Availability metadata cannot
prove that the fetched samples are complete, finite, byte-stable, correctly
resampled or identical to those later used by the five-channel null. A
separate source-bound auxiliary sample acquisition/replay gate must close
those properties before any comparative PEM measurement. No outcome,
candidate promotion, global significance or astrophysical claim follows
from this preflight.

## Real preflight and independent replay

The source freeze is commit `904d8f9`. Pre-run WSL regression: 77 passed,
11 upstream warnings; Ruff lint and format passed. The plan reran the
77-span background-strain verifier and exited 0 with
`PASS_AUX_AVAILABILITY_PLAN_ONLY`. Its run directory is
`E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/aux_availability/aux_availability_1e81576f90061f4a50648e1b1aea2871d99e5f2e8bf43016d486804a1bc52cb2`.

The single controller exited 0 and wrote 77 sealed receipts, each covering
both the frozen event and background intervals for all five frozen channels,
with summary `PASS_AUX_METADATA_COVERAGE_COMPLETE_ONLY` and receipt digest
`1b37f9238661619b3d320049a75e947524c01f9712f7bb5f4ba36bd797e70cf5`.
The independent verifier queried NDS2 again and exited 0 with
`PASS_VERIFIED_AUX_METADATA_COVERAGE_ONLY` (`count=77`). Both stderr logs
are empty; there are zero failure artifacts, partial files or controller
locks. The three plan source SHA-256s match the frozen files. Post-run WSL
regression: 77 passed, 11 upstream warnings; Ruff passed.

The metadata gate does **not** establish sample-level provenance or a PEM
null. The next gate must acquire and independently replay the actual
detector-local auxiliary time series, preserving the historical native-rate
semantics (including the 512 Hz line channels), and bind precisely those
verified samples to the event and background readers. Its source/receipt
policy and resource preflight must be reviewed before a bulk fetch.

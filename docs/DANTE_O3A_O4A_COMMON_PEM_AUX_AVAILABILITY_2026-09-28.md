# O3a/O4a common PEM: auxiliary metadata preflight

Status: **source prepared; no real auxiliary metadata run or PEM outcome yet**.

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

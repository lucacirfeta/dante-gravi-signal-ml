# O3a/O4a common-PEM auxiliary native sample gate — 2026-09-28

## Preregistered scope

This gate retains the exact NDS2 native-rate float32 auxiliary samples for
the five detector-specific channels and the event/background intervals in the
already verified 77-target metadata plan. Repeated uses of a background span
share one series file but retain every target identity in its sealed plan.
It does not select new targets, change channel lists, resample data, calculate
coherence, build a null, issue a PEM verdict, or claim significance.

The author approved one bounded NDS2 acquisition and a second, independent
**local** numerical replay of the retained sample files. Local replay is not
represented as a second source fetch. The source host, channel, interval,
native rate, unit, numerical SHA-256, complete NPY file SHA-256 and target
uses are bound in receipts. NDS2 does not provide the official-frame MD5
manifest used by the strain gate; these receipts establish the precise
sample sequence used here, not byte identity to a separately published NDS2
archive.

The versioned contract is
`config/dante_o3a_o4a_common_pem_aux_samples_v1.json`. The verified parent
is the metadata-only gate `aux_availability_1e81576f90061f4a50648e1b1aea2871d99e5f2e8bf43016d486804a1bc52cb2`.
The expected plan comprises 750 distinct channel/interval series, binding
770 target-channel-role uses, and 84,158,251,008 native float32 sample bytes
before NPY headers. At least twice the remaining expected size must be free
on the run volume before acquisition. Fetches are bounded to 1024-second
chunks, with three transport attempts per chunk; a failed acquisition keeps
completed sealed receipts and the partial file for explicit diagnosis.

## Gate sequence

1. Re-verify the 77-target parent metadata against NDS2, check parent seals,
   complete channel/interval coverage, source hashes, disk headroom, and
   freeze a content-addressed plan. No auxiliary samples are fetched here.
2. Acquire each distinct native series once and atomically publish its NPY
   file and sealed receipt. A singleton controller rejects duplicates. A
   transport-only failure may be archived *explicitly* after completed
   receipts pass local replay; only the same run key may resume.
3. After a complete summary and no failure, lock or partial files, run a
   standalone verifier. It checks the exact receipt/file sets and replays all
   retained samples without NDS2 access. A separate exit-zero verifier is
   required for `PASS_VERIFIED_AUX_NATIVE_SAMPLES_ONLY`.

This checkpoint records the frozen protocol and pre-run checks only. The
five-channel null, event measurement, outcome comparison and any scientific
interpretation remain closed until their own contract, tests and gate pass.

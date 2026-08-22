# Frequency-band audit correction (2026-08-07)

## Outcome

The earlier conclusion that the 4096 Hz GWOSC product invalidated the DANTE
representation above about 1700 Hz was incorrect.  It resulted from swapping
the time and frequency axes of the 37 by 37 DINO patch grid.  That conclusion
is retracted; it is not a submission blocker.

## Code evidence

- `src/core/preprocessor.py::generate_qtransform` passes the requested
  `qrange` and `frange` to `TimeSeries.q_transform`, converts
  `q_gram.value` directly to a NumPy array, and resizes it without a
  transpose.
- GWpy returns `Spectrogram.value` as `(n_times, n_frequencies)` for this
  calculation.  Therefore patch index `p` maps as `p // 37 -> time` and
  `p % 37 -> frequency`.
- `src/pipeline_v2_production/saliency_map.py` preserves that mapping and
  transposes only for conventional display.
- `src/pipeline_v2_production/coincidence_physical.py::_patch_time_band` uses
  the same mapping and the effective frequency range.
- `tests/test_patch_axis_mapping.py` exercises the mapping with independent
  late/low-frequency and early/high-frequency cases.

## Runtime evidence on raw O4a data

The production Q-transform was executed on a readable raw file in the local
`E:` O4a mirror.  The observed values were:

| quantity | observed value |
|---|---:|
| raw sample rate | 4096 Hz |
| raw Q-transform shape | `(1000, 500)` |
| time bins | 1000 |
| frequency bins | 500 |
| requested range | 20--2048 Hz |
| effective range | 20--1291.053052 Hz |

GWpy emitted its documented runtime warning that 2048 Hz is too high for the
given Q range and reset the upper frequency to 1291.053052 Hz.  Consequently
the image ingested by DINO contains no samples from the GWOSC 4096 Hz region
above roughly 1700 Hz discussed in the O4 release note.

## Raw-store coverage inventory

The `E:` inventory contained 7,184 HDF5 paths.  Of these, 7,174 were readable,
all with a one-dimensional 4096 Hz `Strain` data set; 10 had unreadable HDF5
object headers, including two already under `.corrupt`.  These files are a
coverage/provenance issue, not a frequency-band issue.  They reinforce the
manuscript's fail-closed statement that the historic scan lacks an exact
successful-window ledger and that calendar span is not searched livetime.
`logs/production_full.log` records the same ten exclusions during the primary
production scan: nine H1 blocks in session 1375712512 and one L1 block in
session 1376230912.  The match between the current inventory and historical
log makes the exclusion explicit; it does not recover the missing livetime.

## Manuscript consequence

The Methods section must distinguish configured from effective preprocessing:
the 4096 Hz bandpass request is capped below Nyquist, and the production
Q-transform request of 20--2048 Hz is effectively 20--1291.05 Hz for the
declared 32 s, Q=4--64 configuration.  No 16384 Hz rebuild is required by this
audit.

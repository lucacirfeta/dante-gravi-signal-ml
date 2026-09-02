# DANTE-Light O4a corrected PEM checkpoint v1

## Frozen purpose

This stage performs an environmental/auxiliary-channel diagnostic follow-up
of the corrected O4a physical-coincidence shortlist. It does not establish
global statistical significance and it is not an astrophysical confirmation
or veto.

The frozen populations are kept separate:

- primary diagnostic: 9 `ROBUST` pooled-null-threshold exceeders;
- separate diagnostic: 56 `AMBIGUOUS` pooled-null-threshold exceeders;
- excluded: every `BACKGROUND` candidate and all candidates selected only by
  the per-event individual-null test.

The exact permitted description is **"pooled-null-threshold exceeders selected for PEM follow-up"**. They must not be described as globally significant physical coincidences.

## Why the individual-null population is excluded

The individual criterion compares one on-source statistic with at most eight
time shifts. Under an exchangeable null, the probability that the on-source
value is the largest of nine values is approximately 1/9 (11.1%). The observed
rates are 525/4,109 (12.8%) for measurable `ROBUST` seeds and 190/1,700
(11.2%) for measurable `AMBIGUOUS` seeds. These populations are therefore
compatible with the selection mechanism's uncorrected null rate and are not a
defensible expansion of the PEM shortlist.

## PEM measurement boundary

The follow-up inherits the existing O4a family-wise empirical PEM design:
the event statistic is the maximum coherence over the tested public auxiliary
channels and 20--500 Hz. Its time-shift null uses candidate-free 32 s windows
on a 96 s stride inside a 4 h CAT1-clean background block, with a 64 s
surrogate guard and a 96 s exclusion around all 10,942 corrected native
candidates. The threshold is the 99th percentile and its uncertainty is
estimated by bootstrapping background-window indices. A quiet-background
zero-lag q99 is the primary tiering endpoint; missing calibration is never a
negative result.

`L1:PEM-EX_VMON_ETMX_ESDPOWER24_DQ` and
`L1:PEM-EY_MAINSMON_EBAY_1_DQ` remain excluded. The public auxiliary subset is
not the complete detector sensor network, so `NO_CORRELATION` bounds only the
channels actually tested.

## Required future work before any significance claim

A global null for the complete selection pipeline remains mandatory. It must
repeat the full frozen pipeline over many detector time slides and calibrate
either the global maximum statistic or the total exceedance count. The current
pooled p99 shortlist and the eight per-event shifts do not control the
look-elsewhere effect over the full candidate search.

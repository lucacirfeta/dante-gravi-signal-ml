# DANTE-Light O4a v1 retrospective parity protocol

Status: **frozen before rescoring**.

## Question

Does the current canonical DANTE-Light implementation reproduce, from the same
O4a strain windows, the native scores and detector-aware DSD classifications
published by the v1 production analysis?

This is a candidate-conditioned non-regression audit. The 10,429 identities are
taken from the published detector-aware taxonomy, so a PASS cannot establish
full-run discovery sensitivity or independent prospective validation.

## Frozen baseline and population

- Git tag `3.7.0`, commit `67fc8b610277bea79f02757277d19696eee94b62`;
- software DOI `10.5281/zenodo.21912589`;
- evidence DOI `10.5281/zenodo.21925453`;
- all 10,429 unique `detector + catalog GPS` rows in the frozen O4a taxonomy;
- analysis window starts at `catalog GPS + 4 s`, as declared by the threshold
  artifact; preprocessing remains 32 s at 4096 Hz with 4 s whitening context;
- representation parameters, indices, model revision, Top-k and thresholds are
  loaded from versioned repository artifacts, never re-entered as runtime
  constants.

The immutable machine-readable contract is
`config/dante_light_o4a_v1_parity_contract.json`. The full identity ledger and
the missing-local-data subset are referenced by
`config/dante_light_o4a_v1_parity_manifest.json`.

## Raw-strain coverage

The existing `E:/o4a` mirror is addressed by a logical identifier and is never
modified by this audit. Its previously content-hashed manifest covers 10,260 of
10,429 required padded intervals. The 169 missing intervals are class-dependent
(108 ROBUST and 61 AMBIGUOUS across H1/L1), so they may not be dropped. They are
fetched fail-closed into the separate logical cache
`E:/dante_cache/dante_light/o4a_v1_comparison`, with CAT1 status and content
hashes recorded before scoring.

CAT1 coverage and the absence of hardware/CBC/burst injection overlap are
verified for every padded interval against the frozen O4a DQ snapshot before
any download or score is admitted.

Of the 169 intervals not covered by one local file, 162 are covered exactly by
two adjacent, content-hashed files in the immutable mirror. They are stitched
locally and cached as one 40 s input. Only the remaining seven intervals require
a GWOSC fetch; this distinction changes data acquisition only, not preprocessing
or scoring.

## Primary gates

1. all 10,429 detector+GPS identities are present exactly once;
2. every score is finite and differs from its published native score by at most
   the existing exact-replay tolerance `2e-7`;
3. recomputation using the frozen detector-specific CI bounds reproduces every
   published DSD class;
4. all 6,365 published ROBUST rows are escalated by the historical Light p99
   threshold;
5. none of the 2,789 BACKGROUND rows is escalated;
6. AMBIGUOUS routing follows the detector-specific p99 threshold exactly.

`ESCALATE` is intentionally not equated with `ROBUST`: the historical p99 rule
also escalates 619 AMBIGUOUS rows.

## Failure handling and later increments

A mismatch is repeated on the current implementation, decomposed through raw,
whitening, Q-transform, rendering, encoder and Top-k/native-score hashes, and
then compared in an isolated `3.7.0` worktree. Thresholds and tolerances are not
changed after outcomes are visible.

Only after the score/class/routing gates pass may the audit open the separate
taxonomy/family comparison (permutation-invariant), followed by coincidence,
PEM and report-level comparisons. A full CAT1 scan of all O4a strain is a
different, substantially larger experiment and is outside this protocol.

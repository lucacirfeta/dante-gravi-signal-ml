# O3a L1 residuals: localized follow-up decision draft

Status: **draft for author review; not a frozen contract or permission to run**.
Update 30 September: the author approved the narrow five-channel scope.
The concrete numerical candidate and its metadata feasibility limitation are
recorded in `docs/DANTE_O3A_L1_LOCAL_FOLLOWUP_GATE_B_2026-09-30.md`; the
real measurement gate remains disabled.
The O3a diagnostic checkpoint remains closed. This document proposes a
bounded, exploratory detector-characterization follow-up; it does not reopen
the frozen scan, population, scores, classification, coincidence or PEM verdicts.

## Question and existing evidence

Can a *time-localized, physically plausible instrumental association* be
established for the frozen Top-k structures of L1 GPS 1238508320 and
L1 GPS 1241808544? The endpoint is instrumental characterization, **not**
astrophysical origin or global false-alarm probability.

Both records are CBC/BURST CAT2/3-clean in their reviewed windows and exceed
their existing local diagnostic null. The `Scattered_Light` catalogue triggers
in those windows are away from the selected Top-k structures. Their completed
O3a-only and common five-public-channel PEM receipts report `NO_CORRELATION`;
those tests use full-window spectral coherence and do not clear untested
channels or identify a cause. See the verified diagnostic closure, 12-target
visual review and common-PEM result. The two records were selected *after*
inspection of the 12-target review, so this follow-up cannot be presented as
an independent confirmation of a preselected discovery candidate.

## Boundary before any real measurement

1. Freeze the exact two target identities, their source and context receipts,
   and the time-frequency support derived from the already sealed Top-k ledger.
   Record the rule that maps that support to a test region **before** reading
   new auxiliary outcomes. Do not shift or widen regions to improve a result.
2. Audit O3a-era L1 auxiliary-channel availability, naming, calibration,
   sample coverage and veto safety. Treat a missing channel as *untested*, not
   as negative. Keep `PEM-EX_VMON` and `PEM-EY_MAINSMON` out of coherence, per
   the existing high-FPR exclusion. Freeze the eligible set before testing;
   do not select channels by inspecting event correlations.
3. Make an explicit scientific choice of the localized statistic, its
   time/frequency support, lag policy, matched off-source controls, dependence-
   preserving null, multiplicity family across targets/channels/regions, and
   decision rule. All numerical parameters belong in a new versioned config,
   not this draft or the chat. Do not compare this null with the existing
   intra-detector or cross-detector thresholds: they answer different questions.
4. Bind all parent artifact digests, code hashes, run identity, exclusions,
   DQ annotations and verifier expectations in a new contract. Reject changed
   parents or missing coverage; preserve previous runs unchanged. Synthetic
   tests must establish exact-boundary behavior, wrong-detector rejection,
   missing-channel handling, hash failures, and the complete trial count
   before any real outcomes are opened.

## Proposed execution sequence (only after the scientific decision)

| Gate | Action | Acceptance evidence |
| --- | --- | --- |
| A: inputs | Read-only identity, DQ, coverage and channel-safety preflight | Both frozen structures and all eligible controls covered; missing/unsafe channels explicitly reported |
| B: method | Author-approved versioned contract and synthetic tests | Statistic, null, multiplicity and interpretation limits frozen; tests and source hashes pass |
| C: measurement | Run only the two L1 targets and their preregistered controls | Sealed outputs, zero silent drops, no post-hoc retuning |
| D: independent check | Replay inputs and recompute decisions under the frozen contract | Standalone verifier passes; discrepancies stop the analysis |

Interpretation is limited to (a) evidence consistent with a specific
instrumental coupling that also survives timing, frequency, control and
veto-safety checks; (b) no detected association in the *tested* channels;
or (c) inconclusive coverage/control quality. A coupling statistic alone
does not establish causality, and a negative result does not establish an
astrophysical source. No retrospective CAT2/3 veto of the CBC_CAT1 scan and
no A2 promotion follow from this exploratory follow-up.

## Decision required before Gate B

The recommended choice is a **narrow localization-only study** using the
five already frozen public L1 channels: measure association within the frozen
Top-k support, compare against preregistered matched off-source periods from
the same detector/observing state with dependence preserved, and control the
maximum over the complete frozen family of target/channel/region/lag tests.
This isolates localization from a simultaneous change of channel set. Before
implementation the author must still approve the precise statistic, region
construction, control eligibility, null generator, multiplicity family and
decision rule in a new versioned config. The feasibility preflight may reveal
that usable controls or time resolution are insufficient; that outcome is
`INCONCLUSIVE`, not permission to relax criteria after seeing the events.

Alternatives are to leave the two residuals at the verified diagnostic
closure, or to open a **separate** broader-channel study after auditing other
safe, publicly available O3a-era L1 channels. Do not mix either alternative
into the narrow study. A five-channel null result remains bounded to those
channels; it is not a reason to tune the test or silently expand coverage.

No global-significance protocol is proposed here. Such a claim would need a
separate null for the *whole selection path*, including the primary scan and
post-hoc selection of these two records, with trials and detector validation
specified in advance. The existing eight-shift follow-up rule is insufficient
for that purpose.

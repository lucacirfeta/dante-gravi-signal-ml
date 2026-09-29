# O3a diagnostic closure — 29 September 2026

Status: the approved O3a diagnostic pipeline and the separate five-public-
channel O3a/O4a PEM comparison are complete and independently verified.
This closes the present diagnostic checkpoint, not the question of physical
origin or discovery. It does not cover O3b.

## Findings in brief

- The frozen CBC_CAT1 O3a primary scan covered exactly 349,925 H1 and
  372,986 L1 windows (722,911 total), with zero invalid or silently dropped
  windows and a validated 6,313-frame source ledger.
- Native scoring/classification retained 8,900 frozen seeds: 2,492
  BACKGROUND, 558 AMBIGUOUS and 5,850 ROBUST. These detector-local labels
  are not detections. The strict O4a-parity single-linkage taxonomy joined
  8,899 rows into one component and left one singleton: the pre-registered
  chaining limitation, not evidence of one physical glitch family.
- The O3a coincidence diagnostic selected 11 ROBUST primary targets and one
  AMBIGUOUS diagnostic target for PEM follow-up. Its eight-shift pooled null
  is a follow-up rule, not a globally trial-corrected significance estimate.
- All 12 O3a targets have verified O3a-only PEM and five-common-channel
  comparison. The latter also verified 65 separate O4a target receipts.
  O3a primary verdicts are H1 one COUPLED and one NO_CORRELATION, L1 nine
  NO_CORRELATION; the single H1 diagnostic target is NO_CORRELATION. Different
  frozen target populations prohibit an O3a/O4a coupling-prevalence claim.
- Target review found eight full O3a windows with BURST_CAT2/3 quality
  failures, but only three frozen Top-k subwindows overlapping those failures;
  these are diagnostic annotations, not retrospective vetoes. The H1/L1
  GPS 1243231936 structures both overlap a BURST quality warning, without
  proving one shared instrumental cause.
- L1 GPS 1238508320 and 1241808544 remain CAT2/3-clean descriptive
  residuals above their local null, with no verified causal explanation.
  Both were actually measured in the completed common-channel PEM and both
  returned NO_CORRELATION for the five tested public channels. This does not
  clear untested channels or establish an astrophysical origin.

## Boundary and disposition

No target is promoted as a discovery. No independent globally calibrated
significance, time-localized instrumental attribution or run-to-run rate
comparison has been established. The author elected to close this checkpoint
without a new dedicated protocol; any such future analysis requires a
separate pre-registered scientific decision. No O3b or full-O3 claim follows.

Evidence: `.gsd/phases/07-o3a-transfer-readiness/07-11-SUMMARY.md`,
`07-17-SUMMARY.md`, `07-18-SUMMARY.md`, `07-19-SUMMARY.md`,
`07-21-SUMMARY.md`, `docs/DANTE_O3A_TWELVE_TARGET_VISUAL_REVIEW_2026-09-27.md`,
and `docs/DANTE_O3A_O4A_COMMON_PEM_RESULT_2026-09-29.md`. Later verified
checkpoint records supersede historical "pending" statements in earlier
stage notes; the underlying run artifacts remain unchanged.

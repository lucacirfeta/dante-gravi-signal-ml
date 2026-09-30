# O3a final diagnostic report — author review

Date: 2026-09-30. Scope: the frozen public H1/L1 O3a population, not O3b
or all O3. The approved pipeline, common-channel PEM comparison and bounded
local L1 follow-up are complete and verified. No astrophysical event has
been identified by these analyses; neither residual is promoted.

This report consolidates the checkpoints without changing historical
artifacts. It supersedes the **current disposition**, not the evidence, of
the 29 September closure: the subsequently approved local study is now
complete. Human scientific review and any external publication remain
separate from this local documentation increment.

## What was measured

| Stage | Verified accounting | Interpretation |
| --- | --- | --- |
| CBC_CAT1 primary scan | H1 349,925; L1 372,986; total 722,911 windows; 6,313 source frames; zero invalid/silently dropped windows | Frozen scan universe, not a detection count |
| Native reference/index | 647 H1 + 647 L1 windows; 1,771,486 patch tokens; 1,216 centroids; 50,000 reference sample rows | Fresh O3a reference, not imported O4a scientific rows |
| Native calibration/rescore | 5,000 calibration scores per detector; all 8,900 frozen seeds rescored | Detector-local calibration, no pooling or candidate-based threshold fitting |
| Classification | H1 3,624; L1 5,276 identities | Relative anomaly labels, not astrophysical classifications |
| Taxonomy | 8,899 rows in one component, one singleton | Preregistered single-linkage chaining limitation, not one physical morphology |
| Coincidence | 5,850 ROBUST primary + 558 AMBIGUOUS diagnostic identities accounted | 6,408 is the combined population, not 6,408 ROBUST seeds |
| O3a PEM | 11 ROBUST primary + one AMBIGUOUS diagnostic target | Twelve records in eleven distinct windows; two records share GPS 1243231936 |
| Common-channel comparison | 12 O3a + 65 O4a target receipts | Five public common channels per detector, same diagnostic method |
| Local L1 follow-up | Two target identities; 426 measured reference blocks for the eligible target | Bounded post-hoc diagnostic study; no discovery confirmation |

Native calibration used the approved **equispaced complete-block selector
with context fallback**, matching corrected O4a native calibration. The
initial calibration used hash-stratified selection: these are distinct
stages. Parity is not evidence that either selector is statistically optimal.
The exact amendment is
`config/dante_o3a_native_calibration_selector_amendment_v1.json`.

The native p99 point estimate uses all 5,000 calibration rows per detector;
its block bootstrap uses 294 complete blocks of 17 rows (4,998 rows), with
two point-only rows, 1,000,000 replicates and seed 42.

| Detector | Native p99 | Bootstrap 95% interval | Absolute width | Width / p99 |
| --- | ---: | --- | ---: | ---: |
| H1 | 0.4057316655 | [0.4015953541, 0.4096414447] | 0.0080460906 | 1.9831% |
| L1 | 0.4168393409 | [0.4129760563, 0.4202978295] | 0.0073217732 | 1.7565% |

Values above are rounded for reading; exact values remain in
`artifacts/dante_light/o3a_native_v1/native_thresholds.json`. No post-hoc
width cutoff is applied. BACKGROUND is strictly below the detector's lower
interval bound; ROBUST strictly above its upper bound; equality and the
interior are AMBIGUOUS.

| Detector | BACKGROUND | AMBIGUOUS | ROBUST | Total |
| --- | ---: | ---: | ---: | ---: |
| H1 | 1,070 | 263 | 2,291 | 3,624 |
| L1 | 1,422 | 295 | 3,559 | 5,276 |
| Total | 2,492 | 558 | 5,850 | 8,900 |

Coincidence measured 4,607 primary and 445 diagnostic seeds; respectively
1,243 and 113 had partner data unavailable and were explicitly accounted,
**not converted to negative measurements**. Eleven primary and one
diagnostic seed exceeded the frozen pooled follow-up threshold. Its null
uses one maximum per measured ROBUST seed, with at most eight shifts per
seed. It is not a formal look-elsewhere correction or global significance.

## The twelve target records

These are annotations of the frozen outputs, not new vetoes or rankings.
CBC_CAT1 defined the population. A CAT2/3 warning elsewhere in a window
does not explain the selected structure. Eight windows have BURST_CAT2/3
warnings, but only three selected subwindows overlap them.

| Record | Relevant diagnostic evidence | Remaining limitation |
| --- | --- | --- |
| L1 1238507872 | CBC/BURST CAT2/3 warning overlaps the selected structure; low arches | Physical cause not identified |
| L1 1238508320 | Full-window CAT2/3 clean; low arches; historical per-event null exceeded | Scattered-light trigger is far from the selected patch; new local test INCONCLUSIVE |
| L1 1238515136 | DQ warning occurs after the selected structure; historical per-event null not exceeded | Nearby DQ is not causal attribution |
| L1 1239175264 | BURST warnings elsewhere; historical per-event null not exceeded | Selected arch has no verified cause |
| L1 1239628448 | Early loud impulse overlaps BURST warning; only three low-ranked Top-k patches lie there | Does not explain the later median Top-k structure |
| L1 1241808544 | Full-window CAT2/3 clean; low arches; historical per-event null exceeded | New local five-channel screen found no association; cause unknown |
| H1 1243231936 | Impulse and selected subwindow overlap BURST warning | Strong instrumental/DQ caution, not proof of shared cause |
| L1 1243231936 | Impulse and selected subwindow overlap BURST warning | Same caution; the two records are not independent discovery evidence |
| H1 1245414400 | AMBIGUOUS diagnostic only; selected subwindow fails CBC_CAT2/3 | Nearby scattered-light label is not a physical attribution |
| L1 1247267872 | CAT2/3 clean, but historical per-event null not exceeded | Pooled follow-up selection alone is weaker evidence |
| L1 1253362624 | CAT2/3 clean; nearby scattered-light trigger; historical per-event null not exceeded | Morphological label does not prove cause |
| H1 1253581920 | Full-window PEM COUPLED at 390.5 Hz | Does not localize or explain the selected low-frequency arch |

The common-channel O3a PEM has one COUPLED and one NO_CORRELATION H1
primary record, nine NO_CORRELATION L1 primary records, and one
NO_CORRELATION H1 diagnostic record. Both residuals were actually measured
in this completed comparison, not inferred from an unfinished adapter.
The verified O4a breakdown remains in the
[common-PEM result](DANTE_O3A_O4A_COMMON_PEM_RESULT_2026-09-29.md).
Different target populations prohibit a coupling-prevalence comparison.
NO_CORRELATION concerns the tested channels, not all possible instruments.

## What the two L1 GPS records actually are

The GPS numbers identify **starts of 32-second strain windows**, not exact
transient times or named astronomical objects. DANTE found their selected
patch patterns anomalous relative to its reference. Visual review shows
repeated low-frequency arches, compatible with glitch/scattered-light
morphology, but no physical cause has been verified at the selected patch.
Gravity Spy triggers elsewhere in the same window are not identification
of that patch or independent confirmation.

| L1 window start | Frozen selected region, relative to start | Latest local result |
| --- | --- | --- |
| 1238508320 | [16.364864864864863, 17.364864864864863) s; 20–54.49751041053439 Hz | INCONCLUSIVE: at most 31 candidate-clean reference blocks, below the fixed minimum 199. No new local event/null measurement performed. |
| 1241808544 | [17.66216216216216, 18.66216216216216) s; 20–58.968209801245216 Hz | NO_LOCALIZED_ASSOCIATION_DETECTED_IN_TESTED_CHANNELS: T=0.6729808428996378, 68/426 block exceedances, D=0.3231850117096019 > fixed 0.01. |

The two windows are 3,300,224 seconds apart, in distinct CBC_CAT1 segments;
their shared L1 detector and arch-like morphology do not establish a common
instrumental state or cause. They are not a demonstrated two-detector event.

The local rule is D=min(1, 2*(1+r)/(1+B)), with conservative >= ties and
a fixed two-target family even when one target is INCONCLUSIVE. All 426
eligible paired 96-second reference blocks (1,278 contexts) were measured;
11 other blocks were excluded by preregistered local DQ, with zero additional
numerically unavailable blocks. The 2,000 whole-block bootstrap replicates
are descriptive, not extra observations or a new decision criterion.

The second result means its measured coherence was not sufficiently unusual
under this frozen diagnostic screen, **not** zero coherence, instrument
safety, or exclusion of untested channels. The first result is not negative.
The targets were selected after inspection of the twelve-target review;
this follow-up cannot be independent confirmation of a preselected discovery.
No formal p/FWER, global significance, physical attribution or A2 promotion
follows. In plain terms: **two unexplained diagnostic anomalies, not two
identified astrophysical events**.

## Verification and handoff

The final local measurement and standalone verifier had observed OS exits 0.
The verifier requires exact producer replay plus independent FFT/Welch,
block, decision and bootstrap replay. Summary seal:
`b08b443bee62154e4500ffbef876ac60e79b8ef2389c9b7fe3439220b12eef3e`;
verification seal:
`fc91e4860f0de76d4767123bd0377d497122f6fe46c54ae5905c267ffd108ecd`.
Post-run regression already completed: **210 PASS, 11 upstream warnings**;
Ruff lint/format PASS. Those are the measurement checkpoint's tests, not
a newly rerun suite for this documentation-only increment.

Current documentation audit: **170 checks PASS, observed OS exit 0**.
It checks report arithmetic/identities/links against the compact outputs,
local seals and verifier summary binding, all 77 common-PEM event seals,
and all 25 frozen local source hashes/Git qualifications (23 exact bytes,
two exact LF-to-CRLF reconstructions). No source normalization or new
scientific measurement. `git diff --check` PASS.

Raw/large evidence is under `E:/dante_cache/dante_light/`; compact native
receipts are under `artifacts/dante_light/o3a_native_v1/`. The exact local
run is recorded in the
[Gate C result](DANTE_O3A_L1_GATE_C_RESULT_2026-09-30.md). Offline numerical
replay is not a second fetch from NDS2/GWOSC. Historical failures and EOL
provenance qualifications remain preserved.

Review sources: [initial closure](DANTE_O3A_DIAGNOSTIC_CLOSURE_2026-09-29.md),
[twelve-record ledger](DANTE_O3A_TWELVE_TARGET_LEDGER_REVIEW_2026-09-27.md),
[visual/DQ review](DANTE_O3A_TWELVE_TARGET_VISUAL_REVIEW_2026-09-27.md),
[common PEM](DANTE_O3A_O4A_COMMON_PEM_RESULT_2026-09-29.md), and
[local result](DANTE_O3A_L1_GATE_C_RESULT_2026-09-30.md).

Next step is author/scientific review of this report and the local branch
diff, then a separate decision about push or public diagnostic reporting.
No discovery communication is justified. No additional protocol, expanded
channels, selector experiment, taxonomy retuning, O3b work or source change
is opened here. The monitor remains paused. Physical attribution and
independent significance remain unresolved scientific questions, not
unfinished tasks within the completed diagnostic scope.

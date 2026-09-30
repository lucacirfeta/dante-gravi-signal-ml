# Local L1 Gate C — diagnostic result checkpoint

Status: **PASS_VERIFIED_LOCAL_L1_DIAGNOSTIC_ONLY**, observed run/verifier OS
exits 0. Both target identities are accounted; no discovery claim.

## Preregistered method and approved clarifications

The unchanged Gate B method is
`config/dante_o3a_l1_local_followup_v1.json`, SHA
`2625867ba9eb904fe99c7185ffd1c2fc059632172dcdb8bd0bcf6b7e3be3b241`.
Separate execution contract `config/dante_o3a_l1_local_measurement_v1.json`
records the author's 2026-09-30 approval of exact relative half-open selection
and historical preprocessing, without changing the method or old runs.
Execution contract file SHA:
`4da9fe1e7c20523ff8b686f836d9eb470be1dd50680567739e1f71717598617d`;
canonical digest:
`10e57d52225b7175a42d33664ad36aa656c87e2cfa142797dc246af68cbc9671`.

Historical parity means the native-rate strain-only parent highpass is applied
on each full individual context, then all faster streams are antialias-resampled
to the Gate B common rate, then the exact local region is selected. Auxiliaries
receive no extra highpass. The antialias resampler, not highpass alone, provides
alias rejection. Transport containers are never used as filter contexts.
This is not optimization for either selected target.

The contract cites/hash-binds `o3a_native_pem.py:_event_strain`,
`o3a_o4a_common_pem_strain.py:o4a_event_strain`,
`o3a_o4a_common_pem_measurement.py:_measure_event` and
`pem_coherence_analysis.py:calculate_coherence_and_plot`. Only stream/filter
placement and ordering inherit parity: local Welch geometry, fixed region and
the exploratory reference-tail screen are the separately approved Gate B study.

The decision threshold remains **D <= 0.01**, conservative ties included, with
the family fixed at two targets even when one is INCONCLUSIVE. Reference units
are whole paired 96-second blocks, not individual contexts/channels. The
2000-replicate seed-42 whole-block bootstrap is descriptive only; all replicate
exceedance counts are stored, with no new confidence level or extra reference
observations. No comparison with historical intra/cross-detector null thresholds.

## Frozen implementation and input gate

Source freeze: local commit `6db397ff5c1ecb83aba3caa0b9d7c81d823441f2`.
Pre-run WSL regression: `210 passed, 11 warnings in 46.43s`, OS exit 0;
Ruff lint/format PASS. Includes 42 new synthetic tests covering exact boundaries,
historical preprocessing, alias rejection, independent FFT/Welch agreement,
event/control equality, whole-block exclusions, cutoff equality, ties,
two-target accounting, bootstrap, tamper detection and preserved failures.

Plan OS exit 0, digest:
`831b9072f06c40aafc0004bc5ed631ca940d1011205163e541d80516a0568195`.
Canonical run:
`E:/dante_cache/dante_light/o3a_l1_local_followup_v1/local_measurement/local_831b9072f06c40aafc0004bc5ed631ca940d1011205163e541d80516a0568195`.
The matched-sample parent was independently replayed offline before the plan:
20 official strain frames, 54 full-span receipts, 265 native control auxiliary
series and five unchanged historical event series. No new download.

Twenty-five source hashes match: 23 exact Git bytes; `contracts.py` and the
historical `pem_coherence_analysis.py` are exact Git LF->CRLF reconstructions.
Both qualifications are retained, not normalized away. Runtime versions and
five numeric implementation hashes are also sealed in the plan.

## Execution / verification

One productive WSL invocation completed, supervised by exec session 52329.
Logs: `worker.stdout.log`, `worker.stderr.log`. No automatic failure resume.
The independently verified metadata population is 426 eligible blocks,
1278 paired contexts; 11 additional candidate-clean blocks fail local DQ.
The first target remains metadata-INCONCLUSIVE (at most 31 controls versus 199
required). No insufficient population is promoted or enlarged after outcomes.

Productive run observed OS exit 0 (session 52329), summary
PASS_LOCAL_L1_MEASUREMENT_COMPLETE_DIAGNOSTIC_ONLY, seal
`b08b443bee62154e4500ffbef876ac60e79b8ef2389c9b7fe3439220b12eef3e`.
Exactly 426 block receipts/1278 contexts; no failure/partial/lock, stderr empty.
ONE standalone verifier completed (session 55441), with distinct
`worker.verify.stdout.log` and `worker.verify.stderr.log`.
Observed verifier OS exit 0, PASS_VERIFIED_LOCAL_L1_DIAGNOSTIC_ONLY.
Verification seal:
`fc91e4860f0de76d4767123bd0377d497122f6fe46c54ae5905c267ffd108ecd`.
Verified summary file SHA:
`1ad0780f5bfc78c192284c647b27edd8c450a5616bffb5634bb63217454c3a43`.
Verifier stderr empty, zero failure/partial/lock and no controller remaining.
The verifier
reopens native inputs, reconstructs spectra from demeaned periodic-Hann FFT
segments without scipy.coherence/csd, also requires exact producer/provenance
replay, and independently recalculates ties, decision and block bootstrap.
All 25 source hashes and Git qualifications were rechecked after verification.
Post-run WSL regression: `210 passed, 11 warnings in 43.10s`, OS exit 0;
Ruff `All checks passed!`, `3 files already formatted`. No source changed
between freeze, productive measurement and standalone verification.

## Verified diagnostic results

| L1 target GPS | Result | Frozen-rule evidence |
| --- | --- | --- |
| 1238508320 | INCONCLUSIVE | At most 31 candidate-clean whole blocks, below the preregistered minimum 199. No new local event/null measurement was performed; the family remains two. |
| 1241808544 | NO_LOCALIZED_ASSOCIATION_DETECTED_IN_TESTED_CHANNELS | Event local coherence maximum T=0.6729808428996378; 68 of 426 reference block maxima are >= T. D=2*(1+68)/(1+426)=0.3231850117096019, above the fixed 0.01 screen cutoff. |

For the second target all 426 eligible blocks/1278 contexts were measured;
zero additional numerically unavailable blocks. The 11 metadata-DQ exclusions
remain separately accounted, not substituted after inspection. The unchanged
five-channel event arrays are verified references, not a second acquisition.

All 2000 whole-block bootstrap exceedance counts replay identically (observed
range 41–92). They are retained as a descriptive distribution, not a newly
chosen confidence interval, extra independent observations, formal p-value or
criterion used to tune the decision. The point screen alone determines the
registered label. Its negative label is not zero measured coherence: the
observed maximum is not sufficiently unusual relative to the frozen controls.

No localized instrumental association was detected for the measurable target
under this specific screen. This does not identify its cause, establish an
astrophysical origin, exclude untested channels, or turn the first target's
INCONCLUSIVE outcome into a negative. Neither residual is promoted. The
authorized bounded follow-up is complete; any different control population,
channel expansion or significance protocol requires a separate author decision.
Checkpoint commits stay local; the monitor is suspended after reporting.

## Interpretation limits

The targets were selected after inspection of the 12-target review. This study
is not independent confirmation of a preselected discovery candidate. Neither
same-CAT1 membership nor this replay establishes stationarity, exchangeability,
sensor veto safety, physical cause, formal p/FWER or global significance.
A positive local screen requires separate detector-expert/coupling review;
a negative only concerns these five tested channels. No astrophysical claim,
A2 promotion, new channels, historical changes, push or external communication.

The crop is timestamp membership, not nearest-boundary rounding: indices
`[9044,9556)` for the measurable target, at 512 Hz. The first included sample
is at 17.6640625 s; the last included timestamp is 18.662109375 s, inside the
frozen continuous region `[17.66216216216216,18.66216216216216)`. The saved
grid end is the first excluded timestamp, not an extra included sample or a
redefined physical-region endpoint. Provenance seals raw, full-preprocessed
and selected numerical arrays for every event/control context.

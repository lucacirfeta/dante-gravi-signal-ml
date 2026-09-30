# O3a two-residual localization: concrete Gate B candidate

Status: method candidate tested on synthetic arrays; real measurement gate
disabled. On 30 September the author approved the narrow five-channel scope
and requested an explicit numerical decision threshold before measurement.
The approved O3a diagnostic checkpoint remains complete.

## Statistic, region and decision

The machine-readable candidate is
`config/dante_o3a_l1_local_followup_v1.json`. All new numerical choices are
explicit there. None has been selected from a new event outcome.

The region is the already sealed coincidence interval centered on the native
Top-k median, with the half-width from its versioned contract; its frequency
bounds also come from that sealed ledger. Each region is one second long:

| L1 seed GPS | Offset interval (s) | Frozen band (Hz) |
| --- | --- | --- |
| 1238508320 | 16.364864864864863–17.364864864864863 | 20–54.49751041053439 |
| 1241808544 | 17.66216216216216–18.66216216216216 | 20–58.968209801245216 |

The proposed statistic T is the maximum magnitude-squared Welch coherence
over all parent-frozen five L1 channels and all Fourier bins in the respective
band. There is one fixed region and zero lag; no time, band or lag optimization
is allowed. After filtering/resampling the full context, the local kernel uses
512 Hz, periodic Hann, 0.25-second FFT segments and 0.125-second overlap. A
one-second region contains seven Welch segments, with 4 Hz Fourier spacing;
this avoids a single-periodogram coherence that would be identically one.
The same kernel and preprocessing must be applied to controls. Short,
nonfinite, constant or missing series are unavailable, never negative.

## Controls and numerical reading rule

Controls are chronological complete 96-second blocks inside the *same*
frozen contiguous CBC_CAT1 L1 segment. Each block contains three 32-second
contexts, each measured at the same frozen offset and band as its target.
Its reference value is the maximum of those three local T values. This is a
conservative reference relative to a single event region. The full classified
seed ledger, regardless of detector/class, excludes each candidate's 32-second
context plus the inherited 96-second guard on each side. No block is stitched
across exclusions or quality gaps. Local CBC/BURST CAT2/3 coverage and all
five native series still require an input gate.

For B complete reference blocks, let r be the number of block maxima greater
than or equal to the event T. The corrected reference-tail score is

`D = min(1, 2 * (1 + r) / (1 + B))`.

The proposed cutoff is explicitly **D <= 0.01**, including equality. Ties in
the null count against the event. The multiplier two remains even when one
target is inconclusive. At least 199 usable blocks are required to resolve
this cutoff even when r is zero. Bootstrap uses whole 96-second blocks,
2,000 replicates and seed 42 for descriptive uncertainty only; replicates do
not increase the number of acquired reference blocks.

This is an exploratory screening rule. Between-block exchangeability and
instrumental stationarity have not been established, so D is not claimed as
a formally calibrated p-value or FWER guarantee. The same segment alone does
not prove the same instrumental state. A positive screen is labelled
`LOCALIZED_ASSOCIATION_REQUIRES_DETCHAR_REVIEW`; instrumental attribution
additionally needs timing/frequency correspondence, channel safety and a
physically supported coupling mechanism. A covered negative applies only to
the tested channels. Insufficient coverage or tail resolution is
`INCONCLUSIVE`. Post-hoc selection of these two targets remains declared.

## Metadata-only feasibility evidence

`scripts/preflight_dante_o3a_l1_local_followup.py` checks parent file hashes,
the complete classification/coincidence ledger byte hashes and the sealed
auxiliary plan. It reads no strain/auxiliary sample arrays and computes no new
event statistic. The counts below precede CAT2/3 and live-channel checks and
are therefore upper bounds, not claims that all controls are usable.

| Target GPS | Same segment | Blocks before exclusions | After frozen candidate exclusions | Required | Tail resolution possible |
| --- | --- | ---: | ---: | ---: | --- |
| 1238508320 | [1238500421, 1238517740) | 180 | 31 | 199 | No |
| 1241808544 | [1241731918, 1241818103) | 897 | 437 | 199 | Potentially |

For the first target the best possible D is 2/32 = **0.0625**, even before
additional quality losses. Its same segment cannot meet the 199-block rule
even with no candidate exclusions. Thus this design guarantees an
`INCONCLUSIVE` first target without needing a new measurement.

Both previously acquired comparative backgrounds are in other CAT1 segments:
[1238542865, 1238557265) and [1241833950, 1241848350). They do not satisfy
the new same-segment control policy. Five event series per target exist in
the historical plan, but this metadata check does not revalidate their
sample bytes or establish their veto safety.

## Disposition before Gate C

No real runner, fetch or outcome is opened. The candidate provides a concrete
scientific choice for review: retain D <= 0.01 and the two-target family,
account for the first target as inconclusive, and develop verified matched
controls for the second target. Expanding to other observing segments,
shortening statistical blocks, reducing the exclusion guard or changing the
cutoff would change the control/validation design and needs a separate author
decision. More bootstrap replicates cannot solve missing reference blocks.

The 96-second grouping is a conservative proposed design parameter, informed
by the existing control stride/guard; it is **not** an empirically measured
decorrelation time. Its feasibility failure must not be described as an
intrinsic impossibility of every localized follow-up method.

Before productive implementation, freeze the final contract and source,
audit CAT2/3 and native channel coverage/safety, verify the matched control
bytes, test complete trial accounting, and prepare an independent verifier.
The current code is a synthetic measurement kernel plus metadata preflight;
it does not provide a real execution or independent measurement verifier.

Method reference: SciPy's [Welch documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html)
describes averaging overlapping periodograms. Numerical resolution was checked
against the installed WSL SciPy 1.17.1 and the fixed region geometry.

## Verification and review status

- WSL command: `python -m pytest -q tests/test_dante_o3a_l1_local_followup.py
  tests/test_dante_o3a_o4a_common_pem*.py tests/test_dante_o3a_native_pem.py
  tests/test_patch_producer_context.py`: **124 passed, 11 upstream warnings**,
  OS exit 0. New tests cover cutoff equality, conservative ties, insufficient
  reference size, invalid inputs, detector/channel identity, parent hashes,
  complete block/exclusion geometry and synthetic local coherence resolution.
- Ruff lint and format checks pass for the new module, CLI and tests.
- Metadata preflight exits 0 with `CANDIDATE_METADATA_PREFLIGHT_ONLY`;
  design digest `93dd3dab6c82fb279d0a33d72ef77c366c086e2632dc10732e35718c2649a756`,
  metadata receipt digest
  `3d22ff49bba6542d5a24f5819b6730e81c487b519b6a2510f5dc9813f7e55319`.
- Plan review: the requested numerical rule is concrete and synthetic checks
  pass; Gate C is **not ready** because control coverage/safety are not yet
  verified and the first target cannot resolve the proposed tail cutoff.
  No new localized real outcome, productive run key or source-frozen active
  contract is claimed.

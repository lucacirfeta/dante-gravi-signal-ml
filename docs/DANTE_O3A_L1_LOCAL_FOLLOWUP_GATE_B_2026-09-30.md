# O3a two-residual localization: concrete Gate B candidate

Status: numerical method approved and frozen on 30 September; real
measurement gate remains disabled pending verified matched sample inputs.
The author approved the narrow five-channel scope, then explicitly approved
the concrete D <= 0.01 candidate and the first target's INCONCLUSIVE disposition.
The approved O3a diagnostic checkpoint remains complete.

The candidate discussion and original metadata-only evidence below are kept
as the decision history. The subsequent input gate does not change the
statistic, region, block geometry, guard, multiplicity family or cutoff.

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

## Approved method and matched-input metadata gate

The contract status is now `FROZEN_GATE_B_METHOD_INPUTS_NOT_YET_VERIFIED`.
Both author scope and numeric-rule approvals are dated 30 September. Gate C,
sample downloading and new auxiliary outcomes remain disabled in this
contract. A new outcome-blind preflight is implemented in
`src/dante_light/o3a_l1_local_inputs.py` and
`scripts/preflight_dante_o3a_l1_local_inputs.py`.

Its plan binds source SHA256 values, the approved method and both target
identities. No network/sample queries are made for the already unresolvable
first target. For the second, public GWOSC CBC_CAT1/2/3 and BURST_CAT2/3 pass
segments and NDS2 metadata for the exact five channels are snapshotted over
the same frozen contiguous segment. Live CBC_CAT1 must equal that frozen
segment. Each of the 437 candidate-clean blocks is independently accounted
as eligible or excluded. A quality gap only excludes a block when a tested
local region overlaps it; an auxiliary gap anywhere in a full 32-second
context excludes the whole block. Nothing is stitched across gaps and no
block is selected by a coherence result.

Standalone verification replays the saved metadata and eligibility locally,
requiring unchanged plan/source/parent and snapshot hashes. It is **not** a
second NDS2 query, a sample-byte verification, an independent physical
measurement or evidence that a sensor is veto-safe. Native sample hashes,
matched strain coverage and positive-result channel safety remain later
gates. Missing coverage is not a negative result. The family remains two.

Plan check: requirements, dependency ordering and complete block accounting
are covered. This increment is limited to the input metadata gate; it cannot
produce a real local T, reference-tail score, physical attribution or discovery.

Preflight source-freeze regression: **143 passed, 11 upstream warnings in
41.15 seconds**, OS exit 0; Ruff lint/format PASS. The new input-gate tests
cover fractional-second DQ overlap, no veto for a gap elsewhere in the
context, full-context native-channel gaps, complete block rejection,
inconclusive event coverage, metadata identity/geometry errors, offline
standalone replay and refusal to repeat a terminal run. Two test-fixture
failures (temporary path outside the repository sandbox and missing fixture
status) were corrected; neither reached a live query or scientific run.

## Real input metadata result (30 September)

Source freeze: `775ca7e`. Approved design digest:
`2cd634e601e9c1ec0fdf4d091d205f1e0bf21c6bba50729af095e83f04831ae6`.
The real outcome-blind plan, acquisition and separate offline verifier each
finished with OS exit 0. Verifier status:
`PASS_VERIFIED_LOCAL_INPUT_METADATA_ONLY`. The snapshot is retained under:

`E:/dante_cache/dante_light/o3a_l1_local_followup_v1/input_preflight/inputs_18a26a658d12f510c1b77697e74faabef5e45ff36d7facdae2d3d4972c61cdc2`.

Summary seal:
`c8373038cf651baeffff651c5fb89358a0ae05ddb45b6c63431dba3ed2c01ea2`;
summary file SHA256:
`fddeaf1073a1c3ef751c6b364a95fcb4e60d2a3be36091a2b161e04100c8fe84`.

- GPS 1238508320: INCONCLUSIVE from the 31-block upper bound alone. No new
  source query or local event statistic was needed for this target.
- GPS 1241808544: all 437 candidate-clean blocks accounted. Eleven are
  excluded by local-region BURST_CAT2 **and** BURST_CAT3 coverage; **426**
  remain. No additional CBC_CAT2/3 or native-channel metadata gap rejects a
  block. The target event has complete tested DQ and channel metadata coverage.
  All five exact channels have full native-context coverage for retained blocks.
- No failure, partial file or controller lock; both stderr files are empty.
  All nine sealed source hashes match current bytes, and the four new method/
  input files are byte-identical to their Git source freeze. Historical EOL
  provenance qualifications are unchanged; no shared source was normalized.
- Post-final-CLI targeted suite: **19 PASS**, 11 upstream warnings, exit 0.
  The full pre-run suite remains **143 PASS**, 11 upstream warnings. Ruff PASS.

This is a **metadata** result, not a new PEM result or proof of native sample
integrity. It establishes that the second target's approved reference-tail
resolution is feasible before numerical sample acquisition. No local T,
reference-tail score or bootstrap result has been computed on real arrays.

## Next authorized implementation increment

1. Freeze a transport-only acquisition plan from precisely these 426 eligible
   blocks, preserving all block identities and all five native channel rates.
   Adjacent contexts may share a download container, but not a statistical
   block: this is byte transport only. The exact 1,278 control contexts form
   53 contiguous transport intervals and require **3,266,445,312 auxiliary
   sample bytes** before NPY headers. No rejected gap may be filled or tested.
   Reuse event input only after its historical receipt/sample verification.
2. Bind official O3a_4KHZ_R1 strain frames for every complete matched context;
   require published manifest checksums, exact metadata/rate and independent
   local numerical replay, then standalone native auxiliary file verification.
   Preserve all previous run directories. Do not interpret partial acquisition.
3. Implement and test identical full-context preprocessing/local sampling,
   whole-block maxima and descriptive block bootstrap, plus a standalone
   measurement verifier. Freeze sources and the exact verified input receipt
   before opening Gate C. Keep the first target INCONCLUSIVE and family size
   two. A positive exploratory screen still requires a separate channel-safety
   and physical-coupling review before any causal interpretation.

Acceptance: complete, hash-verified matched sample inputs and green tests before
real local measurement; no change to the already approved scientific rule.
No control-sample download or productive local measurement has yet started.

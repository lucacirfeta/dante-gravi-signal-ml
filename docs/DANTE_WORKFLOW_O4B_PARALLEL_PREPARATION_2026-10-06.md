# Parallel O4b preparation: H1/L1 and separate Virgo

## Latest author choice and storage request

Author `ok` after native16k recommendation approves native16384Hz processing
while retaining20..2048Hz band. Source/band alternatives below are historical,
not still unanswered. This does not authorize reuse of old representations/
thresholds or any additional release/GPS/DQ/population/null choice; new method
must be versioned and qualified before execution, with dedicated V1 artifacts.

Author later clarified `volevo dire E`: E: is approved for future raw/backups.
The following D: inventory is historical, not an unresolved destination choice.
No disk relettering or WSL relocation is authorized. Keep active data on native
Linuxext4 and schedule heavy E: copies outside numerical processing.

Author originally permitted D: for future raw/backups. Windows read-only inventory
Get-Volume/Get-Disk/Get-Partition and Test-Path D:/ found noD: drive. OnlyC:
NVMe and E:SATA data volumes are currently exposed. E:remaining515687866368B,
C:320902696960B at observation. No data partition awaiting a letter was found.
No format/reletter, archive, migration, backup write or raw download performed.
The destination correction to E: is now explicit. Keep active computation on native
Linuxext4; raw/archive storage may be an NTFS data disk. Copies on the same
physical disk do not protect against physical disk failure.


Latest author `procediamo in parallelo` authorizes two preparation strands.
Read-only V1 audit delegated in parallel; root audits H1/L1 and writes shared
state. No strain download, numerical stage, O4b launch, network-statistic
change or production promotion. Scientific choices remain author checkpoints.
Source checkout beff119491a621f1b3cbc30e1ba0e222c87b04e1 before this documentation.

## Current prerequisites

H1/L1: native calibration run completed; independent full verifier explicitly
interrupted by author and remains incomplete. Administrative installed CLI/UI
boundary qualified separately. Local registry config/dante_workflow_runs_v1.json
O4b has null method_contract/workflow_contract. Existing O4b shadow_v2 selects
768 H1/L1 windows across three fixed blocks and old epoch_v2 is O4a-calibrated;
neither is silently adopted for this new workflow. Their scores/outcomes were
not opened. New O4b release/GPS/DQ/reference/calibration/evaluation choices remain
pending; historical source outputs and all failures stay immutable.

V1: GWOSC publishes O4b strain at4096Hz and16384Hz. The generic preprocessing
interface documents V1, but frozen production admission is not V1-qualified.
src/core/patch_producer.py:80 rejects detectors outside H1/L1 in
load_frozen_raw_manifest. src/pipeline_v2_production/build_native_index.py:206
allows only H1/L1/both. Broadening these would require detector-specific
contracts and tests, not just removing guards. Dedicated V1 reference/index,
calibration/null/population/validation are not provided by the current O4b
registry. No H1/L1 index, null or threshold reuse for V1 is authorized.

## Shared scientific source/band checkpoint

Frozen config/dante_o4a_corrected_protocol_v4.json:472 and490 specifies
frequency_range_hz20..2048 and sample_rate_hz4096. config.yaml:71/75 agrees
with that sample rate and Q-transform range. The O4b shadow metadata uses the
same representation. Official GWOSC technical notes state that the4096Hz
release is affected by its anti-aliasing filter near Nyquist and recommend
16384Hz data for studies at around1700Hz or higher:
[GWOSC O4 technical details](https://gwosc.org/O4/o4_details/).

This is a new-contract scientific compatibility issue, NOT a numerical mismatch
or automatic invalidation/reopening of historical runs. No values are changed.
Q-transform frange is not proof of physically usable input bandwidth. Current
bandpass clips f_high to0.9Nyquist (preprocessor.py:88-103); this does not remove
the entire GWOSC-affected high-frequency region or resolve the source contract.

Merely fetching16k data is insufficient: PatchProducer resamples input to its
configured self.sample_rate (patch_producer.py:585-586); multi-block consumer
resamples to configured sample_rate_hz (232-233). Leaving4096Hz unchanged
would therefore not implement a native16k scientific representation.

Author alternatives, neither implemented:

1. Native16384Hz source/processing, retain intended frequency coverage only
   after review; version new representation and qualify compatible reference,
   calibration and null. More samples/I/O; no guarantee of numerical identity
   to old4k artifacts and no old score/threshold transplant.
2. Retain4096Hz processing with explicitly approved scientifically usable
   upper frequency below the affected region; new representation and matching
   reference/calibration/null. Smaller data volume but less frequency coverage.
   No exact cutoff silently chosen from the approximate1700Hz documentation.

Both require author scientific approval before configuration/source changes,
test/freeze/execution. V1 remains detector-separate; no three-detector coherence.
Next checkpoint also fixes release, GPS/DQ and disjoint score-blind populations.
The earlier1–3day V1 estimate was preliminary, not a benchmark or guarantee;
this representation decision changes the work and excludes waiting for approval.

## Sources and verification boundary

- [GWOSC O4b release](https://gwosc.org/O4/O4b/): public detectors, sampling,
  channels and availability, not exact selected-GPS coverage or local DQ proof.
- Archive4k URL could not be opened by the web tool; no coverage inferred.
- Local direct file reads confirmed registry/representation/resampling/guard
  evidence. Documentation-only preparation, no new numerical testPASS claim.
- Plans08.44/08.45 define independent read-only strands and shared author gate.
  Root is the sole writer of shared docs/state. No duplicate scientific stages.

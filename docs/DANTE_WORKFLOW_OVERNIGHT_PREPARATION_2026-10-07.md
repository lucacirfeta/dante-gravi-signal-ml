# Bounded overnight technical preparation

Author requests autonomy until tomorrow, after approval of native16384Hz /
20..2048Hz and correction of raw/backup disk from D: to E:. Provisional deadline
7October2026 08:00Europe/Rome (06:00UTC), explicitly communicated pending an
optional hour reply. No authority to launch O4b or choose pending scientific
release/GPS/DQ/populations/null/tolerances/promotions. Plans08.44/45 remain open.

## Task1 complete: fresh tracked-history backup

Observed2026-10-06T21:47:31.1234004Z:

- New file: `E:\dante_cache\dante_workflow\overnight_preparation_20261007\git_backup_v1\science-o3-transfer-readiness.bundle`.
- `git bundle create`, `verify`, `list-heads`: each observed exit0; terminalexit0.
- Complete history of `refs/heads/science/o3-transfer-readiness` through
  `bfdd18305d9d860c90a4238eb9f7cf893ab3aa11`; no prerequisites needed.
- Bytes40,180,949; SHA256
  `429fa4a550b6b26a56bcf2c567459e03a8479b988139aede3f14f4228036abd8`.
- E:free before515,687,866,368B; existing destination refused, no overwrite.

This is a Git-history backup, not a raw dataset or full workspace backup.
Untracked `output/` and `artifacts/dante_workflow/public_smoke_v1/`, external
cache/raw/artifacts and documentation edits pending at bundle creation are
excluded and remain in their original locations. No original moved/deleted.
No restore trial claimed: Git bundle verification confirms structural integrity
and SHA records bytes, not full scientific recovery. No new numerical tests.

## Task2 complete: author decision packet

Prepared7October2026 shortly after00:45Europe/Rome from official metadata and
checkouta2a80a5. This is a proposal, not an executable scientific contract.
No strain, scores or outcomes were inspected; no selected-GPS coverage asserted.

### What the current release actually contains

[GWOSC O4b](https://gwosc.org/O4/O4b/) distinguishes official observing interval
GPS1396796418..1422118818 from the larger released interval beginning1396417050,
which includes earlier supernova-analysis data. H1/L1/V1 are published at4k/16k.
The final underlying channels are H1/L1 DCS-CALIB_STRAIN_CLEAN_AR01 and V1
Hrec_hoftRepro1AR_16384Hz. These boundaries describe catalog scope, not continuous
per-detector coverage and not approved analysis selection.

[16k archive](https://gwosc.org/archive/O4b_16KHZ_R1/) and its
[dataset definition](https://gwosc.org/archive/dataset/O4b_16KHZ_R1/) identify
O4b_16KHZ_R1. The definition describes release1/internalversion1 and also contains
the literal label "test run". Record that metadata wording without interpreting
it as certification or evidence that O4b science is a test. Each file has4096s,
with DATA/CBC/BURST/STOCH/CW flags and separate no-hardware-injection masks.

[Timeline](https://gwosc.org/timeline/query/Run/O4b_16KHZ_R1/) exposes H1/L1/V1
DATA, BURST_CAT1/2/3 and injection flags. No segment-list query for a proposed
selection was executed. This page proves the metadata interface exists, not
which selected windows pass or that all whitening context is available.

[Technical notes](https://gwosc.org/O4/o4_details/) explain why native16k avoids
the4k anti-aliasing issue near1700Hz and distinguish DATA availability from
analysis-specific DQ. Hardware injections remain in released strain, and DQ
above2k is less studied. Native16k/20..2048 approval does not certify physical
DQ/sensor safety or authorize an injection/DQ veto.

[Alternate release](https://gwosc.org/O4/o4b_alternate/) documents different
calibration/cleaning products: final LIGO AR01 incorporates offline recalibration
where available, while Virgo has its own reprocessed product. Gated channels
replace loud glitches, so choosing one would alter a glitch population. No
alternate, gated or uncleaned channel is adopted by this proposal.

### Minimum decisions before implementation

All recommendations below are unapproved. No numeric split sizes, gaps,
thresholds, bootstrap parameters or tolerances have been invented.

| Decision | Proposed starting option | Alternative and consequence |
| --- | --- | --- |
| Release and GPS scope | Final O4b_16KHZ_R1, restricted to the official observing interval; initially qualify a bounded score-blind subset | Include the earlier released days as an explicitly separate epoch, or cover the full official run immediately; this changes population/I/O scope |
| DQ and injections | For glitch research, decide explicitly whether DATA availability is the admission floor; keep known glitches/injections in separately defined morphology-specific validation cohorts | Apply approved BURST category and injection exclusions; this can remove precisely the glitches being studied and changes the scientific target |
| Reference/calibration/evaluation split | Freeze dedicated temporally disjoint lists per detector using metadata only, then review their exact membership before any scoring | Prespecified multi-epoch blocks can address changing detector conditions but require an explicit allocation and aggregation protocol |
| Null and validation scope | Keep H1/L1 network treatment separate; approve a dedicated V1 within-detector null and fresh compatible reference/calibration, with block-based validation | New three-detector coherence is a different scientific/structural project; not covered by separate V1 preparation |

Recommended next author authorization is **metadata-only construction of a
reviewable proposed selection**, after choosing release/scope and DQ/injection
policy. It is not approval to download strain, score, fit, calibrate or run O4b.
Exact interval membership, reference/calibration/evaluation allocation, context
separation and null/validation parameters still require a versioned proposal and
author approval. Changing filters to make a population convenient is prohibited.

### Contract fields that remain unfilled

The future method needs explicit release/revision, detector/channel/sampling,
analysis interval list, DQ/injection semantics, whitening/context geometry,
reference/calibration/evaluation membership and ordering, dedicated reference/
index/calibration/null identities, statistic/estimator/bootstrap parameters,
validation scope and acceptance rules. This is a requirements list, not a new
JSON schema. Existing versioned config remains the source of any inherited
numeric constants; author-approved differences must be versioned separately.

The approved20..2048 Q-transform extent is not the same thing as the filter
passband: currentconfig.yaml has f_high2000 and preprocessor.py:93 clamps it
against Nyquist. Native16k changes that effective boundary. A future contract
must state the actual intended filter and Q-transform representation explicitly;
do not claim byte equality with old4k references or transplant their thresholds.

Registryconfig/dante_workflow_runs_v1.json:71-75 still binds O4b to the4k catalog
URL and leaves method_contract/workflow_contract null. run_profiles.py:109-153
requires path/contract_digest/detectors and explicit methoddetector_scope_path.
Its readiness at206-238 does not certify science, even when binding succeeds.
The single workflow binding also requires exact detector selection: parallel
preparation does not authorize silently replacing H1/L1 with H1/L1/V1 or
redesigning registry dispatch. SeparateV1 active integration needs an explicit
structural plan; its current isolated preparation can remain a draft.

### Qualification map after author approval, not launched tonight

1. Freeze the new method/selection before scientific work; retain old guards and
   historical runs. Add isolated16k config-driven path tests showing no hidden
   resample to4096, full-context whitening before crop, boundary/gap failure and
   supported/rejected detector contracts. Use source/rate pins, not tolerances
   invented for convenience. Encoder tensor code can be reused, not old outputs.
2. Build new compatible references and fresh calibration in detector-specific
   namespaces, preserve approved population/order/batch geometry, and qualify
   frozen scientific primitives and runtime. Compare a new run to its matching
   verifier, not new16k images to historical4k images as an equivalence target.
3. Verify clean-installed scientific end-to-end and CLI/UI boundary against the
   new contract. Independent full verification remains required according to
   the approved scope; the author-stopped old replay is not converted to PASS.
4. Present the completed checklist and request separate authorization before
   O4b execution. No three-detector coherence or V1 reuse of H1/L1 null/index.

No source/config changes or new numerical regression suite are needed to
validate this documentation-only packet. Existing489postrun/100admin/installed
checks are historical evidence, not fresh16k/V1/full-calibration qualification.

## Scheduling evidence

Existing `monitor-o3a-native-cohort` updated via app automation tool, returned
ACTIVE; persistedstatusACTIVE checked. Hourly recurrence retained, same thread,
new bounded preparation prompt replacing stale original calibration monitoring.
No new scientific/controller/test process launched. With both safe tasks complete,
pause and verify PAUSED now rather than spending the night past the scientific
checkpoint. Existing jobs are never force-killed. Actual pause/verification
receipt is recorded in08-46SUMMARY and JOURNAL after tool observation.

Observed toolupdate returned PAUSED and persistedstatusPAUSED was confirmed at
2026-10-06T22:48:26.2818404Z (7October00:48Europe/Rome), before the deadline.
Fresh sourcepincheck18/18PASS; separate documentationdiffcheckexit0/terminal0.
Windowsmatching scientific-controller candidates0 excluding the diagnostic
shell; Linuxpython-name query had no matches (ps exit1 means empty selection).
No signals, controller/verifier/test launches or source changes. This is an
operational/documentation completion, not scientific readinessPASS.

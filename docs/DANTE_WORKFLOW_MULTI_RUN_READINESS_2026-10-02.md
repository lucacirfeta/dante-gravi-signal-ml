# Multi-run scientific readiness: remaining gates

Date:2026-10-02. Internal readiness evidence, not an external LIGO/Virgo certification.
The completed diagnostic O3a H1/L1 analysis is not being reopened.

## Verified foundations
-08.24 `coverage-readiness` checks the approved profile's exact primary GPS/
  context against pinned manifest metadata and original full identities.
  Unchanged corrected-O4a selector, no added CBC/DQ filter: one real WSL replay
  OSexit0/PASS,811251 identities. Windows318/WSL317+one skip/post-freeze80 PASS.
  This is NOT raw/sample/calibration/live/DQ/runtime or all-run certification.
  Details: docs/DANTE_WORKFLOW_GPS_COVERAGE_2026-10-02.md.
-08.23 common `input-readiness` binds adapter-selected frozen declarations and
  metadata file SHA/seals without state creation or raw reads. It is NOT exact
  GPS/DQ coverage or scientific preflight PASS; productive PREFLIGHT unchanged.
  Details: docs/DANTE_WORKFLOW_INPUT_READINESS_2026-10-02.md.
-08.22 common operation boundary distinguishes retained-only verification from
  productive execution in sealed profile policies, controller, CLI, report and
  UI. Synthetic O3a/O4a fixtures exercise it; no real profile is newly activated.
  Details: docs/DANTE_WORKFLOW_OPERATION_MODES_2026-10-02.md.
- Versioned public-run/detector catalogue and explicit CLI selection already exist.
- Schema-v2 per-profile graph boundary and separate O3a stage interfaces/read-only
  readers exist; original O4a graph and scientific contracts remain intact.
- Actual retained O3a coincidence ancestry passed08.20 with the explicitly
  qualified driver metadata and isolated pinned SCAN copy. It is not raw replay.
-08.21 actual owned historical PEM retained-decision verification is PASS,
  observed OSexit0. All94 capture members match,51 source bindings and12 unchanged
  lock markers; actual read-only coincidence ancestry executed. This closes the
  retained reader chain, not raw numerical replay or full-workflow readiness.

## Concrete remaining sequence
Current blocker08.25: calibration input software is implemented/tested, but
all28 retained acquired raw supplements are absent. Historical84 GPS-source
HDF5 restored byte-exact from the existing archive;39971 identities accounted.
No real input PASS, refetch, new receipt or scientific execution authorization.
See docs/DANTE_WORKFLOW_CALIBRATION_INPUTS_2026-10-02.md for the recovery decision.

1. Integrate individually approved stage/receipt mappings into explicit frozen
   workflow profile and common adapter/dispatcher. The current build_adapter
   enables only o4a_corrected; O3a workflow_contract is null. The shared retained
   versus productive operation policy now exists; actual mappings remain. Connect the UI
   selector to actual supported profiles, without an O4a fallback or no-op gates.
2. Complete profile-specific exact-GPS data/DQ/context/source/runtime preflight
   and explicit stage applicability/reporting. Initial acquisition, reference,
   calibration and scan must be bound; comparative and post-hoc follow-up stages
   are not automatically required for every future execution.
   Primary manifest GPS/context coverage now passes08.24 for the existing
   corrected-O4a profile only; calibration, physical raw/sample and current
   runtime proof remain. Preserve each profile's original DQ selection, rather
   than imposing a new universal flag policy.
3. Prove clean-install reproducibility with bounded real raw-to-result execution
   and an independent verifier, beyond retained hashes/ledgers. Record runtime,
   source/EOL identity, detached-launch/recovery behaviour, resource requirements
   and exclusions. Existing retained driver metadata waiver does not establish
   numerical GPU equivalence or authorize fresh measurement.
4. Qualify each additional observing-run/detector profile scientifically before
   activation: frozen population, reference/index, calibration/thresholds, DQ,
   morphology-separated controls and applicable downstream contracts. A single
   common engine need not have identical reference data or thresholds across runs.
   S5/S6/O1/O2/O3b/O4b currently have no method/workflow binding in the registry.
5. Validate V1 separately where public strain exists: its own reference/calibration,
   detector-local controls and author-approved pairwise/network null. Never
   transplant bipartite H1/L1 thresholds or infer global significance by pooling.
   O4a has no public V1 scope in this profile. Availability is not certification.
6. Activate/release only profiles whose complete gates pass, with reproducible
   operator documentation and human scientific review. Unsupported profiles must
   remain visibly blocked. No push/merge/publication is implied here.

Steps1-3 are principally integration/reproducibility work; steps4-5 require
explicit author decisions whenever population, scoring, statistics or validation
changes. Full readiness need not hold back use of an individually verified profile.

## Current source evidence
config/dante_workflow_runs_v1.json: existing catalogue and profile bindings.
src/dante_workflow/cli.py: explicit observing-run/detectors/catalogue/readiness CLI.
src/dante_workflow/run_profiles.py: remaining gates and scientific_execution_ready=false.
src/dante_workflow/adapters/__init__.py: implemented dispatch is O4a-only.
.gsd/ROADMAP.md,Phase8: all-run software milestone remains in progress.

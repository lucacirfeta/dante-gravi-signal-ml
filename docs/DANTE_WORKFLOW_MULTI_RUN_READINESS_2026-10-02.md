# Multi-run scientific readiness: remaining gates

Date:2026-10-02. Internal readiness evidence, not an external LIGO/Virgo certification.
The completed diagnostic O3a H1/L1 analysis is not being reopened.

## Verified foundations
- Versioned public-run/detector catalogue and explicit CLI selection already exist.
- Schema-v2 per-profile graph boundary and separate O3a stage interfaces/read-only
  readers exist; original O4a graph and scientific contracts remain intact.
- Actual retained O3a coincidence ancestry passed08.20 with the explicitly
  qualified driver metadata and isolated pinned SCAN copy. It is not raw replay.
-08.21 closes only owned historical PEM byte/retained-decision verification when
  its actual invocation passes; tests and the capture plan alone are not PASS.

## Concrete remaining sequence
1. Finish exact historical PEM snapshot capture and retained full-parent replay.
2. Integrate the verified O3a stage/receipt mapping into an explicit frozen
   workflow profile and common adapter/dispatcher. The current build_adapter
   enables only o4a_corrected; O3a workflow_contract is null. Connect the UI
   selector to actual supported profiles, without an O4a fallback or no-op gates.
3. Complete profile-specific exact-GPS data/DQ/context/source/runtime preflight
   and explicit stage applicability/reporting. Initial acquisition, reference,
   calibration and scan must be bound; comparative and post-hoc follow-up stages
   are not automatically required for every future execution.
4. Prove clean-install reproducibility with bounded real raw-to-result execution
   and an independent verifier, beyond retained hashes/ledgers. Record runtime,
   source/EOL identity, detached-launch/recovery behaviour, resource requirements
   and exclusions. Existing retained driver metadata waiver does not establish
   numerical GPU equivalence or authorize fresh measurement.
5. Qualify each additional observing-run/detector profile scientifically before
   activation: frozen population, reference/index, calibration/thresholds, DQ,
   morphology-separated controls and applicable downstream contracts. A single
   common engine need not have identical reference data or thresholds across runs.
   S5/S6/O1/O2/O3b/O4b currently have no method/workflow binding in the registry.
6. Validate V1 separately where public strain exists: its own reference/calibration,
   detector-local controls and author-approved pairwise/network null. Never
   transplant bipartite H1/L1 thresholds or infer global significance by pooling.
   O4a has no public V1 scope in this profile. Availability is not certification.
7. Activate/release only profiles whose complete gates pass, with reproducible
   operator documentation and human scientific review. Unsupported profiles must
   remain visibly blocked. No push/merge/publication is implied here.

Steps2-4 are principally integration/reproducibility work; steps5-6 require
explicit author decisions whenever population, scoring, statistics or validation
changes. Full readiness need not hold back use of an individually verified profile.

## Current source evidence
config/dante_workflow_runs_v1.json: existing catalogue and profile bindings.
src/dante_workflow/cli.py: explicit observing-run/detectors/catalogue/readiness CLI.
src/dante_workflow/run_profiles.py: remaining gates and scientific_execution_ready=false.
src/dante_workflow/adapters/__init__.py: implemented dispatch is O4a-only.
.gsd/ROADMAP.md,Phase8: all-run software milestone remains in progress.


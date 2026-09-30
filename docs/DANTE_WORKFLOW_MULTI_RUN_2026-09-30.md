# Multi-run workflow: scope and administrative foundation

Author: Luca Cirfeta. Checkpoint: 2026-09-30.

## Approved destination, not a completed support claim

One DANTE workflow must eventually support all public observing/science runs
for H1/L1, and V1 where public strain exists. H2/G1/K1 were not included in
this authorization. This extends software scope; it does not retrospectively
add Virgo to the O4a study or authorize new scientific parameters.

The first increment implements a strict run catalogue, explicit selection and
adapter dispatch. It does **not** deliver full multi-run scientific execution,
a multi-run GUI, new detector calibration, or a new network null.

Official availability snapshot: [GWOSC data releases](https://gwosc.org/data/),
checked 2026-09-30. Membership in a release is not continuous GPS coverage or
proof of data quality, auxiliary availability, calibration validity or sensor
safety. Do not equate a published detector with an executable DANTE profile.

## Capability matrix at this checkpoint

| Run | Public strain detectors in approved scope | Bound DANTE method | Productized scientific workflow |
| --- | --- | --- | --- |
| S5 | H1, L1 | Not registered | Blocked |
| S6 | H1, L1 | Not registered | Blocked |
| O1 | H1, L1 | Not registered | Blocked |
| O2 | H1, L1, V1 | Not registered | Blocked |
| O3a | H1, L1, V1 | Existing frozen H1/L1 method | O3a stage adapter pending; V1 method pending |
| O3b | H1, L1, V1 | Not registered | Blocked |
| O4a | H1, L1 | Existing frozen H1/L1 method | Existing corrected-O4a workflow only |
| O4b | H1, L1, V1 | Not registered | Blocked |

"Not registered" describes this new complete-workflow registry, not absence
of historical experiments, reference indices or scripts in the repository.
Existing O3a numerical analyses remain verified: the missing item is their
integration into the common productized controller, not a rerun of that study.
S5 includes public H2 data but H2 is deliberately outside the approved scope.
O3GK has G1/K1 rather than any approved detector and is outside this matrix.
The historical network timeline alone is not a public strain release.

## Read-only commands

From a source checkout:

```shell
python scripts/run_dante_workflow.py runs
python scripts/run_dante_workflow.py run-readiness --observing-run O3a --detectors H1 L1
python scripts/run_dante_workflow.py run-readiness --observing-run O3a --detectors V1
python scripts/run_dante_workflow.py run-readiness --observing-run O4a --detectors H1 L1
```

An installed controller rebuilt from this checkout has the identical commands:

```shell
dante-workflow runs --repository-root /path/to/dante-gravi-signal-ml
dante-workflow run-readiness --repository-root /path/to/dante-gravi-signal-ml --observing-run O3a --detectors V1
```

The already published 3.8.1 wheel does not contain this new increment. No
release version, existing DOI, immutable release or scientific result is
relabelled by these changes.

These commands read versioned metadata/contracts only: no ledger, cache,
network request, download, worker, score or outcome access. Exit codes:

- `0`: valid catalogue, or `PASS_RUN_PROFILE_BINDING_ONLY`.
- `2`: `BLOCKED_RUN_PROFILE`; a scientific method or adapter is missing, or
  detector selection differs from the complete frozen workflow.
- `1`: malformed/unavailable selection, registry/parent drift or another error.

Even `PASS_RUN_PROFILE_BINDING_ONLY` sets `scientific_execution_ready=false`:
exact GPS/DQ coverage, population/reference/calibration receipts, runtime,
execution and independent verifiers remain necessary. The command does not
run those checks or assert their result. Data availability is a dated official
catalogue snapshot, not a fresh source query on every invocation.

O4a/V1 is rejected as unavailable. O3a/V1 and O4b/V1 are recognized as public
but blocked for measurement. Missing/unrecognized detectors are never dropped
silently; "Virgo" is not silently translated to V1. An unknown future release
needs a reviewed registry update, not a fallback to O4a.

## Execution selection and preserved behavior

The legacy corrected-O4a CLI/UI keeps its exact workflow contract, stage graph,
commands and receipt rules. An explicit equivalent selection is:

```shell
python scripts/run_dante_workflow.py plan --observing-run O4a --detectors H1 L1 --raw-root /path/to/o4a --cache-root /path/to/cache
```

Unlike `runs`/`run-readiness`, the existing `plan` command creates an
administrative ledger. Profile selection is checked **before** constructing
that ledger: a blocked O3a/V1 or unknown-run plan creates no fallback O4a state.
Selecting just H1 cannot silently reduce the frozen two-detector workflow.
`--config` cannot override a selected profile, and `--detectors` or
`--run-registry` without an observing run is rejected for execution commands.

The registry binds canonical parent contract digests; the workflow schema also
checks its existing byte-level scientific references. Scientific contracts are
read-only. Registered adapter identity, detector scope and the method's
explicit detector list must agree. Receipt hooks remain abstract in the common
adapter boundary: a future adapter must implement them rather than inherit
O4a-specific artifact interpretation.

The full UI constructs through this same adapter factory, so an unknown
workflow adapter cannot be treated as O4a. This is not yet a multi-run selector
in the GUI. The public bounded-smoke interface remains separate and unchanged.

## Next increments and scientific gates

1. Bind the existing frozen O3a stage CLIs, receipts and independent verifiers
   to a common workflow profile. Preserve exact numerical results; explicitly
   distinguish applicable stages from historical O4a comparison/report stages.
   A profile-dependent stage graph must be separately versioned, not grafted
   onto the frozen O4a 15-stage schema or old run identities.
2. Add actual CLI/UI run/detector selection and exact-interval data/DQ/context
   preflight. Do not guess quality flags, sample rate or whitening context for
   new detector/run profiles. Test clean installation and bounded real replays.
3. Freeze per-run/detector reference and calibration population contracts before
   enabling previously unvalidated runs or V1 measurement. Preserve candidate,
   index and calibration disjointness, detector-local thresholds and block
   bootstrap; unavailable auxiliary channels remain explicitly untested.
4. Separately approve Virgo's cross-detector scope: adding V1 to a bipartite
   H1/L1 null is a new scientific construction. Pairwise versus network-level
   aggregation, multiplicity, background and decision rules cannot be inferred
   from the software-scope authorization. No old threshold or significance
   claim transfers implicitly.
5. Publish only after the actual support matrix, package/GUI, input access and
   reproducibility gates pass. No all-run readiness, low-latency, discovery,
   sensor-safety or globally calibrated significance claim at this checkpoint.

No production run, acquisition, outcome inspection or external publication is
performed by this increment. Historical artifacts and user untracked files
remain untouched. Test evidence is recorded in the phase-08 verification.

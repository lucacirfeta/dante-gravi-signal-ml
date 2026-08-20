# DANTE-Light O4b later-epoch shadow-validation protocol

Status: **V2 HOLDOUT LOCKED; FINAL EVALUATION NOT YET EXECUTED**. The O4a
calibration gates and detector-specific causal epochs pass. A four-window v1
infrastructure preflight reported a 65.22 s canonical cold-path p99 because the
implementation incorrectly included the first GWOSC acquisition inside the
executor clock. That value is not comparable to the registered executor-latency
endpoint. The defect was corrected before v2 evaluation by an explicit,
outcome-blind staging phase; acquisition is reported separately and the entire
observed first O4b block remains tuning-only and excluded from v2.
This document and the v2 manifest define required evidence; they are not an
operational PASS.

## Locked O4b corpus

O4a remains immutable on the external raw-data disk. O4b is a separate public
holdout (official GPS bounds 1396796418--1422118818). The outcome-blind DQ
snapshot is `config/dante_light_o4b_cat1_segments_v1.json`; the v2 manifest is
`config/dante_light_o4b_shadow_v2.json` with 768 windows: 384 H1 and 384 L1,
128 per detector in each of three fixed later blocks. Selection used only
GWOSC `H1_CBC_CAT1` and `L1_CBC_CAT1`, including the four-second whitening
context, and no DANTE score, event label or strain morphology.

The causal epochs in `config/dante_light_o4b_epochs_v2.json` retain the frozen
O4a thresholds and native index. Their cutoff is GPS 1389456018, before every
O4b evaluation window. Each promotion gate is bound to named, hashed evidence
in `artifacts/dante_light/o4b_epoch_gate_receipt_v2.json`.

## Scientific question

Can exact DANTE-Light nearline replay reduce wall-clock and operator latency on
a genuinely later detector epoch while preserving traceability, zero silent
drops, stable escalation behaviour and the full offline DANTE dispositions?

## Frozen design before evaluation

1. Use the locked O4b v2 manifest. Do not add, remove or reorder windows after
   inspecting scores. O4a supplies calibration; the excluded v1 block is
   tuning-only; the three v2 blocks are held-out evaluation.
2. Promote detector-specific causal epochs only through
   `src/dante_light/epoch.py`; all six promotion gates and artifact hashes must
   pass. No window at or before the epoch cutoff is a prospective trial.
3. Run `--prefilter none` with the canonical and exact shared engines on every
   held-out CAT1-complete window. The canonical path is the scientific
   reference and runs in parallel shadow mode.
4. If evaluating a prefilter, freeze its feature contract and threshold using
   only the tuning interval. Retain every rejected-window audit selected by the
   pre-registered deterministic sampler. Do not modify the operating point
   after held-out outcomes are visible.
5. Preserve all failures, DEFERs, gaps, late packets and negative results.

## Primary endpoints

- zero silent drops and duplicate detector/GPS identities;
- exact canonical/shared scores and dispositions within the frozen numerical
  tolerance;
- pipeline p50/p95/p99 latency from task submission through preparation,
  scoring, queue delay and completed durable persistence;
- detector-data acquisition/staging delay, reported separately because it
  precedes task submission; complete-window availability and the staged strain
  digest are rechecked fail-closed during canonical preparation;
- escalation rate and detector/session block stability;
- audit-estimated miss rate among non-escalated windows with confidence
  intervals;
- retention stratified by detector, session, DANTE score, duration, frequency,
  known-glitch morphology and injection family/SNR;
- time from Light record to completed offline validation and operator workload.

## Prefilter promotion boundary

A lossy prefilter remains rejected unless it retains every frozen O4a ROBUST
replay case, demonstrates non-inferiority with uncertainty on the locked
known-glitch and injection populations, and reduces DINO calls by at least 50%
on held-out data. Any unmeasured stratum is `DEFER`, not `NOT_ESCALATED`.

## Comparators

- exact canonical DANTE-Light (`prefilter none`);
- exact shared-encoder DANTE-Light;
- optional Omicron-conditioned arm, evaluated separately;
- a documented anomaly baseline such as GWAK only where its reproducible input
  and calibration contract can be matched without inventing equivalence.

## Decision rule

Operational usefulness may be claimed only when
`scripts/verify_dante_light_release.py --stage operational` passes and the
result artifact is deposited with code, model/index, epoch, corpus and source
hashes. Before then the allowed description is "experimental exact historical
replay with prospective gates open."

The machine-readable result is
`artifacts/dante_light/prospective_validation_v1.json`. Its schema is locked as
follows before outcomes are inspected:

```json
{
  "schema_version": 1,
  "status": "complete",
  "mode": "prospective_shadow",
  "public_sources_only": true,
  "strain_source": "gwosc-only",
  "prefilter": "none",
  "locked_protocol": {
    "path": "docs/DANTE_LIGHT_PROSPECTIVE_PROTOCOL.md",
    "sha256": "<sha256>"
  },
  "reference_bundle_sha256": "<sha256>",
  "bundle_source": {
    "url": "<public HTTPS URL>",
    "download_verified": true,
    "publication_status": "deposited"
  },
  "checkout": {
    "clean_clone": true,
    "tracked_dirty": false,
    "commit": "<40-character Git SHA>",
    "origin_url": "<public HTTPS Git URL>"
  },
  "run_commit": "<same 40-character Git SHA>",
  "pre_registered_latency_objective_s": "<positive number>",
  "latency_semantics": "task submission through completed durable record write",
  "data_availability": {
    "canonical": {"elapsed_s": 0, "p50_s": 0, "p95_s": 0, "p99_s": 0, "failures": 0},
    "shared": {"elapsed_s": 0, "p50_s": 0, "p95_s": 0, "p99_s": 0, "failures": 0}
  },
  "latency_s": {"p50": 0, "p95": 0, "p99": 0},
  "latency_objective_met": true,
  "coverage": {
    "windows": 2,
    "drops": 0,
    "duplicate_identities": 0,
    "deferred_windows": 0,
    "defer_rate": 0,
    "defer_reasons": {},
    "failures": []
  },
  "exact_replay": {
    "score_atol": 2e-7,
    "max_abs_score_delta": 0,
    "disposition_mismatches": 0
  },
  "detectors": {
    "H1": {
      "epoch_id": "<promoted epoch>",
      "evaluation_start_gps": 0,
      "evaluation_end_gps": 0,
      "windows": 1
    },
    "L1": {
      "epoch_id": "<promoted epoch>",
      "evaluation_start_gps": 0,
      "evaluation_end_gps": 0,
      "windows": 1
    }
  },
  "artifacts": [{"path": "<repository-relative path>", "sha256": "<sha256>"}]
}
```

The numerical latency objective must be passed to both shadow runs with
`--latency-objective-s` before evaluation begins; it is then immutable in both
run manifests. The evidence builder refuses a different after-the-fact value.
The measured latency starts when a task enters the executor and ends only after
its record write completes. Before task submission, every frozen window is
retrieved through the public GWOSC-only source, checked for full context and
finite samples, and bound to a SHA256 digest. Acquisition timings and failures
are preserved separately; a digest change at preparation becomes `DEFER`.
The verifier requires monotone p50/p95/p99 values,
p99 no larger than that objective, post-cutoff H1 and L1 intervals, exact score
and disposition equivalence, no failures, duplicates or drops, and hashes for
every supporting artifact. A file that merely declares `status: complete` is
not sufficient.

Build the result only from the paired run directories:

```bash
python scripts/build_dante_light_prospective_evidence.py operational \
  --canonical-run runs/dante_light/prospective_canonical \
  --shared-run runs/dante_light/prospective_shared \
  --epochs config/dante_light_epochs_v1.json \
  --bundle artifacts/dante_light/downloads/dante_reference_artifacts_v1.zip \
  --latency-objective-s <the value already frozen in both manifests>
```

The `preflight` builder mode is available for local schema testing, but emits
`prospective_shadow_preflight` and `public_sources_only: false`; it cannot pass
the operational verifier.

Before an operational build, reproduce the frozen contracts with:

```bash
python scripts/build_dante_light_o4b_manifest.py --check
python scripts/build_dante_light_o4b_epochs.py --check
```

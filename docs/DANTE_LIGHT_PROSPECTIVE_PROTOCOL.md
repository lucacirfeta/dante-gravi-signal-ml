# DANTE-Light prospective validation protocol (not yet executed)

Status: **LOCK BEFORE OUTCOME INSPECTION**. This document defines the evidence
needed for an operational claim; it is not evidence that those gates passed.

## Scientific question

Can exact DANTE-Light nearline replay reduce wall-clock and operator latency on
a genuinely later detector epoch while preserving traceability, zero silent
drops, stable escalation behaviour and the full offline DANTE dispositions?

## Frozen design before evaluation

1. Choose a later public/authorised epoch not used by the active reference or
   calibration. Record immutable GPS intervals separately for calibration,
   tuning and held-out evaluation for H1 and L1.
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
- detector-data availability delay, reported separately because it precedes
  task submission and is not measured by the current executor clock;
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
its record write completes; it does not include upstream GWOSC availability.
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

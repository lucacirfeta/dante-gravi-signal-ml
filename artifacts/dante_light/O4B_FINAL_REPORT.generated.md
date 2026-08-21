# DANTE-Light run report

> Generated from validated machine-readable evidence. The source JSON files and their hashes remain authoritative.

## Prospective shadow execution

- Status: **PASS** (768 durably accounted windows).
- Canonical/shared agreement: 0 disposition mismatches; maximum score delta 0 (tolerance 2e-07).
- Durable-write latency: p50 29.039 s, p95 35.398 s, p99 37.014 s; pre-registered p99 objective 60.000 s.
- Run commit: `780831b6f9afb579d58758020747c8ee0abe930e`.

| Detector | Windows | Evaluation GPS interval | Causal epoch |
|---|---:|---|---|
| H1 | 384 | 1404597088.000--1415055264.000 | `o4a-calibrated-o4b-causal-h1-v2` |
| L1 | 384 | 1404588832.000--1414952608.000 | `o4a-calibrated-o4b-causal-l1-v2` |

## Escalation follow-up

- ESCALATE cohort: 18/768 (2.344%).
- Physical measurements: 14; explicitly data-unavailable: 4.
- Catalog matches inside frozen windows: 0.
- Every gallery strain and image digest reproduces the frozen cohort.

`ESCALATE` is a routing decision, not a physical classification or a claim of novelty.

## Public auxiliary diagnostic

Diagnostic-only coverage: 18 events using 5 calibration epochs.

| Verdict | Count |
|---|---:|
| `NO_AUXILIARY_EXCESS` | 14 |
| `PERSISTENT_BASELINE_COMPATIBLE` | 4 |

The limited public witness set cannot veto, confirm, or physically classify a candidate.

## Scientific boundary

`NOT_ESCALATED` is a triage outcome and is not the offline `BACKGROUND` class. DANTE-Light does not establish astrophysical origin, instrumental origin, or a novel glitch morphology; those conclusions require the full offline validation chain and appropriately powered physical evidence.

## Source provenance

| Artifact | SHA-256 |
|---|---|
| `artifacts/dante_light/prospective_validation_v1.json` | `3be2b77f3254afacb896901d6a009354af9e6deaf8bd031972d720ce10046a83` |
| `artifacts/dante_light/o4b_followup/manifest_v1.json` | `12a487de3f69cd14105f0a656260d54745ae36050e771b0cd270e3eabf563199` |
| `artifacts/dante_light/o4b_followup/physical_v1.json` | `83238bae8ff60aef93aa09e6aaae12fa28a7bb1dce5b53460af74ee0501bf7ca` |
| `artifacts/dante_light/o4b_followup/catalog_v1.json` | `4072918cd045d1b706f2bea21ead9c1bf39b3c9bc47d772bfb8154046a20f285` |
| `artifacts/dante_light/o4b_followup/gallery_v1.json` | `92a9190e62a4f889b8b1fb6ff433b6624e0b6058a4745cb4adf5c82fc63b3069` |
| `artifacts/dante_light/o4b_auxiliary/result_v1.json` | `5caf0c126a0fbf986b1d345ceaf8444a2f96877e882d7b46f2fad9d7232036f3` |

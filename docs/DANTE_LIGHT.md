# DANTE-Light exact replay and shadow guide

DANTE-Light is an additive, experimental triage layer. Version 1 keeps the
validated 4096 Hz, 32 s, pad-4 whitening, Q=[4,64], cividis, 256x256, frozen
DINOv2 and Top-68 representation. It does not replace `patch-production`, the
detector-aware DSD, coincidence, PEM, or the offline paper artifacts.

## Current support boundary

- Historical exact replay: implemented and tested.
- Bounded preprocessing/scoring/writing with back-pressure: implemented.
- Canonical engine: default and permanent reference.
- Exact shared-encoder/native-score-only engine: opt-in; paired benchmarked.
- Prospective shadow scoring: fail-closed because the shipped completed-O4a
  BGV3 epoch is non-causal.
- Cheap excess-energy features: implemented only as a `research_only` arm;
  they are prohibited from routing scientific windows until promoted evidence
  exists.
- Lossy selection, automatic online adaptation, public real-time alerts and
  operational miss-rate claims: not enabled.

The Light dispositions are `ESCALATE`, `AUDIT_SAMPLE`, `NOT_ESCALATED`, and
`DEFER`. Only the full offline pipeline may emit `ROBUST`, `AMBIGUOUS`, or
`BACKGROUND`.

## Installation and artifacts

Use the pinned reference environment described in
`docs/REPRODUCIBILITY_LEVELS.md`, then verify the model and both dictionaries:

```bash
python scripts/manage_reference_artifacts.py acquire-model
python scripts/manage_reference_artifacts.py verify
python -m pytest tests/test_dante_light_contracts.py \
  tests/test_dante_light_replay.py tests/test_dante_light_executor.py \
  tests/test_dante_light_runner.py -q
```

The current public software/evidence Zenodo records do not yet contain
`dante_reference_artifacts_v1.zip`. Until its later deposit is configured in
`config/reference_artifacts.json`, a clean public clone cannot perform exact
scoring. Development may proceed with locally verified artifacts; this is not
equivalent to public reproducibility.

## Small historical replay

Public-strain/CAT1 mode (network access required):

```bash
python main.py dante-light-replay \
  --output-dir runs/dante_light/public_example \
  --role background_stratified --limit 2 \
  --device cpu --engine canonical --cat1-mode gwosc
```

GPU exact optimized mode:

```bash
python main.py dante-light-replay \
  --output-dir runs/dante_light/gpu_example \
  --role background_stratified --limit 8 \
  --device cuda --engine shared_encoder_score_only --cat1-mode gwosc
```

For an already validated local strain mirror, add `--local-only`. The explicit
`--cat1-mode frozen-replay-attestation` is restricted to historical corpus
replay and records that weaker provenance; it must not be used as evidence of
prospective DQ availability.

Expected output:

```text
runs/dante_light/<name>/
  run_manifest.json   immutable configuration, hashes, code and environment
  records.jsonl       append-only per-window evidence and disposition
  attempts.jsonl      every execution/resume attempt
  summary.json        most recent accounting, including drops and DEFERs
```

Re-run the identical command to resume. Completed detector/GPS identities are
not rescored or duplicated. Any change in code state, epoch, representation,
selection, CAT1 source, or engine requires a new output directory and fails
closed if mixed with an existing queue.

## Shadow gate

```bash
python main.py dante-light-shadow \
  --output-dir runs/dante_light/shadow_gate --limit 1
```

With the shipped epochs the expected disposition is
`DEFER/NON_CAUSAL_EPOCH`, and the summary is `complete_with_defer`. This proves
the look-ahead guard; it is not a successful prospective shadow run.

## Failure meanings

- `MISSING_CAT1`: the whole analysis window is not covered by the selected
  public CAT1 evidence.
- `INCOMPLETE_DATA`: the padded strain or clean 32 s subwindow is incomplete.
- `STALE_INDEX` / `UNKNOWN_REPRESENTATION`: artifact hashes or representation
  do not match the frozen contract.
- `MISSING_CALIBRATION`, `NON_CAUSAL_EPOCH`, or `CALIBRATION_LOOKAHEAD`: no
  scientifically valid threshold may be applied.
- `DEPENDENCY_UNAVAILABLE`: required strain/DQ service or local artifact is
  unavailable.
- `INTERNAL_ERROR`: preprocessing or scoring failed unexpectedly; scores are
  deliberately absent.

A writer failure is fatal and instructs the caller to retry from the last
durable checkpoint. Queue capacity never causes a scientific window to be
dropped.

## Escalation

`ESCALATE` means “send this detector/GPS window to the exact full offline
DANTE validation chain.” It is not a physical interpretation. Review records
carry strain/image hashes, both exact scores, epoch/threshold, Top-68 patch
evidence and MIL-vector hash. The downstream run must still perform the full
detector-aware DSD and, where applicable, coincidence, catalog, PEM and human
review. `NOT_ESCALATED` is never a substitute for offline `BACKGROUND`.

## Research-only and future adapters

`src/dante_light/prefilter.py` computes cheap deterministic excess-energy
features, but its current contract cannot call `route()`. Promotion requires a
temporally disjoint replay demonstrating robust-candidate retention, stratified
known-glitch/injection non-inferiority with intervals, at least 50% fewer DINO
calls, and an unbiased audit sample among rejected windows.

`src/dante_light/epoch.py` rejects promotion unless calibration ends before the
held-out evaluation begins, every required gate is `PASS`, and every evidence
artifact hash matches. `src/dante_light/drift.py` can freeze adaptation on an
alert or insufficient block; it never retrains or updates an index.

The file/replay source and transport-neutral one-second packet assembler accept
reordering and exact duplicates but fail closed on gaps, divergent duplicates,
uncalibrated samples or missing CAT1. No authenticated IGWN Kafka adapter is
claimed yet.

`src/dante_light/aux_cache.py` is a content-addressed, provenance-preserving
read-through cache primitive for auxiliary channels. It is not wired into the
current PEM endpoint or synchronous Light path. A future authorised NDS2
adapter must pass cold/warm equality and retain the exact detector, channel,
GPS interval, sample rate and source in the cache key before adoption.

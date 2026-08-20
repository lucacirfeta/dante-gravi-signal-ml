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
- Prospective shadow scoring: the O4a-calibrated causal O4b-v2 epochs and
  outcome-blind 768-window holdout are complete. Paired canonical/shared runs
  have zero drops, DEFERs and failures, exact scores/dispositions, and shared
  p99 task-to-durable-write latency 37.01 s against the frozen 60 s objective.
- Cheap excess-energy features: implemented only as a `research_only` arm;
  they are prohibited from routing scientific windows until promoted evidence
  exists.
- Lossy selection, automatic online adaptation, public real-time alerts and
  operational miss-rate claims: not enabled.

The Light dispositions are `ESCALATE`, `AUDIT_SAMPLE`, `NOT_ESCALATED`, and
`DEFER`. Only the full offline pipeline may emit `ROBUST`, `AMBIGUOUS`, or
`BACKGROUND`.

Do not replace `E:/o4a`: it is the historical v6 reproducibility corpus. Any
O4b mirror must use a separate directory such as `E:/o4b` and retain its GWOSC
source and checksum manifest.

Prospective shadow mode stages every locked GWOSC window before submitting it
to the timed executor. This is not an outcome cache: staging performs no
whitening, rendering, embedding or scoring. It verifies availability and a raw
strain digest, reports acquisition delay separately, and the timed preparation
must reproduce the digest or fail closed. `--strain-source gwosc-only` remains
mandatory for operational evidence, so a local mirror cannot silently replace
the public source.
The immutable run manifest also records executor concurrency, batch size,
requested device, Python and core package versions, CPU count, and CUDA device
identity so latency results are interpretable rather than hardware-free claims.

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

The public software/evidence Zenodo records do not contain the NPZ dictionaries.
The separate `dante_reference_artifacts_v1.zip` is instead a versioned GitHub
release asset whose URL and SHA-256 are frozen in
`config/reference_artifacts.json`. A clean clone can download, verify and
install it with `python scripts/manage_reference_artifacts.py download-bundle`.
To verify the committed O4b operational evidence from a clean clone, place the
same verified public bundle at the path attested by that evidence:

```bash
python scripts/manage_reference_artifacts.py download-bundle \
  --output artifacts/dante_light/downloads/dante_reference_artifacts_v1.zip
python scripts/verify_dante_light_release.py --stage operational
```

## Small historical replay

Public-strain/CAT1 mode (network access required):

```bash
python main.py dante-light-replay \
  --output-dir runs/dante_light/public_example \
  --role background_stratified --limit 2 \
  --device cpu --engine canonical --cat1-mode gwosc \
  --strain-source gwosc-only
```

GPU exact optimized mode:

```bash
python main.py dante-light-replay \
  --output-dir runs/dante_light/gpu_example \
  --role background_stratified --limit 8 \
  --device cuda --engine shared_encoder_score_only --cat1-mode gwosc \
  --strain-source gwosc-only
```

`--strain-source gwosc-only` deliberately bypasses every matching local mirror
and is required for public replay evidence. `--strain-source local-only` (or
the compatibility alias `--local-only`) forbids network fallback; `auto` may
use either source and is not proof of clean public reproducibility. The explicit
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

Release status is machine-checkable:

```bash
python scripts/verify_dante_light_release.py --stage development
python scripts/verify_dante_light_release.py --stage public-replay
python scripts/verify_dante_light_release.py --stage operational
```

At the public-replay checkpoint, `development` and `public-replay` pass. The
supporting clean-clone result is
`artifacts/dante_light/public_replay_validation_v1.json`: it self-downloaded the
GitHub asset, used GWOSC-only strain and whole-window CAT1, and obtained exact
canonical/shared scores and dispositions with no drops or failures. The
`operational` now passes on the locked O4b v2 evidence. This validates exact
later-epoch shadow execution under the stated protocol; it does not authorize
public real-time alerts, automatic adaptation, or a lossy prefilter.

## Release-evidence commands

Before publication, test the exact bundle from a clean HTTPS clone without
claiming the public gate:

```bash
python scripts/run_dante_light_clean_clone.py prepublish \
  --bundle /absolute/path/dante_reference_artifacts_v1.zip \
  --limit 2 --device cuda
```

To verify the published bundle, use `public` without `--bundle`; the script
downloads and verifies the configured archive itself:

```bash
python scripts/run_dante_light_clean_clone.py public --limit 2 --device cuda
python scripts/verify_dante_light_release.py --stage public-replay
```

A future causal epoch is assembled only from detector promotion payloads:

```bash
python scripts/promote_dante_light_epoch.py \
  --promotion artifacts/dante_light/h1_epoch_promotion.json \
  --promotion artifacts/dante_light/l1_epoch_promotion.json \
  --output config/dante_light_o4b_epochs_v2.json
```

Once paired canonical/shared shadow runs exist strictly after those cutoffs,
build their locked result. `preflight` writes a clearly non-operational mode;
only `operational` can satisfy the release verifier, and it requires the public
bundle contract:

```bash
python scripts/build_dante_light_prospective_evidence.py operational \
  --canonical-run runs/dante_light/o4b_v2/canonical \
  --shared-run runs/dante_light/o4b_v2/shared \
  --epochs config/dante_light_o4b_epochs_v2.json \
  --bundle artifacts/dante_light/downloads/dante_reference_artifacts_v1.zip \
  --latency-objective-s 60
python scripts/verify_dante_light_release.py --stage operational
```

The locked O4b run uses `config/dante_light_o4b_shadow_v2.json` and
`config/dante_light_o4b_epochs_v2.json`. For a tuning-only balanced smoke test,
use `--limit-per-detector N`; never use a limit for the final v2 evaluation.

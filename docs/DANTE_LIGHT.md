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

### Unified derived report

After prospective evidence and any optional offline follow-up have passed
their own gates, build one human-readable report without copying numbers by
hand:

```bash
python scripts/build_dante_light_report.py \
  --prospective artifacts/dante_light/prospective_validation_v1.json \
  --followup-dir artifacts/dante_light/o4b_followup \
  --auxiliary artifacts/dante_light/o4b_auxiliary/result_v1.json \
  --output artifacts/dante_light/O4B_FINAL_REPORT.generated.md \
  --receipt artifacts/dante_light/o4b_final_report_receipt_v1.json
python scripts/verify_dante_light_report.py \
  --receipt artifacts/dante_light/o4b_final_report_receipt_v1.json
```

`--followup-dir` and `--auxiliary` are optional, but auxiliary evidence is
accepted only when it can be linked to a complete follow-up cohort. The report
builder checks coverage accounting, exact canonical/shared agreement, latency,
cross-stage manifest links, gallery hashes and auxiliary self-hashes before it
writes anything. The receipt binds the rendered Markdown and every source JSON
by SHA-256. The generated Markdown is a triage report, not an authority that
replaces those machine-readable artifacts or the full offline
`Final_Discovery_Report.md`.
Within a supplied follow-up directory, manifest, physical and gallery evidence
are mandatory. `catalog_v1.json` is optional: when a validated catalog adapter
is not yet available, the generated report records `NOT_SUPPLIED` and makes no
zero-match inference.

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

### Preparing a new run without O4b hard-coding

The lower-level shadow runner accepts arbitrary frozen manifests and causal
epochs. For a new observing interval, first copy
`docs/dante_light_shadow_plan.example.json` to a new run-specific configuration
and edit the run bounds, HTTPS release URL, tuning interval and held-out blocks.
Do this before fetching DQ metadata or inspecting scores. Then lock the plan,
freeze only the public CAT1 segments and build the manifest:

```bash
RUN_TAG=o5_shadow_001
python scripts/build_dante_light_manifest.py lock-plan \
  --draft config/${RUN_TAG}_shadow_plan_draft.json \
  --output config/${RUN_TAG}_shadow_plan_v1.json
python scripts/build_dante_light_manifest.py snapshot-dq \
  --plan config/${RUN_TAG}_shadow_plan_v1.json \
  --output config/${RUN_TAG}_cat1_segments_v1.json
python scripts/build_dante_light_manifest.py build \
  --plan config/${RUN_TAG}_shadow_plan_v1.json \
  --snapshot config/${RUN_TAG}_cat1_segments_v1.json \
  --output config/${RUN_TAG}_shadow_v1.json
python scripts/build_dante_light_manifest.py check \
  --plan config/${RUN_TAG}_shadow_plan_v1.json \
  --snapshot config/${RUN_TAG}_cat1_segments_v1.json \
  --output config/${RUN_TAG}_shadow_v1.json
```

Every stage is immutable: rerunning identical inputs is idempotent, while a
different plan, DQ snapshot, reference contract or output fails closed. The
builder requires the tuning interval to end before the first held-out block,
whole-window CAT1 including whitening padding, empty outcome fields, unique
detector/GPS identities and the schema-1 32 s/pad-4 representation.
`uniform_cat1` is the recommended outcome-blind rule for a new run because it
spreads the fixed count across every eligible CAT1 window in each block.
`first_aligned` exists only to reproduce protocols such as the frozen O4b
selection; its more concentrated temporal sampling must be stated explicitly.
Schema 1 currently requires the paired H1/L1 detector set; Virgo/KAGRA support
would require new coincidence, epoch and validation contracts and is not
silently inferred by changing the detector list.

This prepares selection only. It does not create a scientifically valid epoch.
Detector promotion payloads must still demonstrate all six gates from earlier
calibration data; assemble them with `scripts/promote_dante_light_epoch.py`.
Do not copy the O4a thresholds into a later run without rerunning and binding
the required gate evidence.

Before spending time on strain acquisition or scoring, verify the locked
manifest and promoted epochs together:

```bash
python scripts/verify_dante_light_run_config.py \
  --manifest config/${RUN_TAG}_shadow_v1.json \
  --epochs config/${RUN_TAG}_epochs_v1.json
```

This preflight recomputes manifest and entry digests, rejects inspected outcome
fields or duplicate windows, verifies the exact representation contract and
requires one causal, past-only epoch for every selected detector.

Run the permanent canonical reference and exact shared-encoder arm into
different directories, with the same pre-registered latency objective:

```bash
LATENCY_OBJECTIVE_S=60
python main.py dante-light-shadow \
  --manifest config/${RUN_TAG}_shadow_v1.json \
  --epochs config/${RUN_TAG}_epochs_v1.json \
  --output-dir runs/dante_light/${RUN_TAG}/canonical \
  --engine canonical --cat1-mode gwosc --strain-source gwosc-only \
  --latency-objective-s ${LATENCY_OBJECTIVE_S}
python main.py dante-light-shadow \
  --manifest config/${RUN_TAG}_shadow_v1.json \
  --epochs config/${RUN_TAG}_epochs_v1.json \
  --output-dir runs/dante_light/${RUN_TAG}/shared \
  --engine shared_encoder_score_only --cat1-mode gwosc \
  --strain-source gwosc-only \
  --latency-objective-s ${LATENCY_OBJECTIVE_S}
python scripts/build_dante_light_prospective_evidence.py operational \
  --canonical-run runs/dante_light/${RUN_TAG}/canonical \
  --shared-run runs/dante_light/${RUN_TAG}/shared \
  --epochs config/${RUN_TAG}_epochs_v1.json \
  --bundle artifacts/dante_light/downloads/dante_reference_artifacts_v1.zip \
  --latency-objective-s ${LATENCY_OBJECTIVE_S} \
  --output artifacts/dante_light/${RUN_TAG}_prospective_v1.json
```

Do not use `--limit` or `--limit-per-detector` for the final held-out run.
Those switches are only for smoke/preflight execution.

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

### O4b frozen escalation follow-up

The locked O4b shadow produced 18 escalations. Their detector-aware offline
ledger is built separately so that follow-up cannot change the original
manifest, threshold, score, or disposition:

```bash
python scripts/build_dante_light_o4b_followup.py manifest
python scripts/build_dante_light_o4b_followup.py physical --device cuda
python scripts/build_dante_light_o4b_followup.py catalog
python scripts/snapshot_dante_light_o4b_partner_availability.py
python scripts/build_dante_light_o4b_followup.py gallery
python scripts/verify_dante_light_o4b_followup.py --stage all
```

The machine-readable results are under
`artifacts/dante_light/o4b_followup/`; the bounded scientific interpretation is
in `artifacts/dante_light/O4B_FOLLOWUP_RESULT.md`. A physical measurement may
be `PARTNER_DATA_UNAVAILABLE` when the other detector has no valid CAT1
context. No catalog match or historical-label match is equivalent to a claim
of a new glitch morphology.

For a new shadow run, use the generic wrapper and a fresh directory. It freezes
only the exact paired `ESCALATE` records and refuses later stages until that
manifest exists:

```bash
RUN_TAG=o5_shadow_001
python scripts/build_dante_light_followup.py manifest \
  --canonical-records runs/dante_light/${RUN_TAG}/canonical/records.jsonl \
  --shared-records runs/dante_light/${RUN_TAG}/shared/records.jsonl \
  --output-dir artifacts/dante_light/${RUN_TAG}_followup
python scripts/build_dante_light_followup.py physical \
  --output-dir artifacts/dante_light/${RUN_TAG}_followup --device cuda
python scripts/build_dante_light_followup.py gallery \
  --output-dir artifacts/dante_light/${RUN_TAG}_followup
```

The current catalog adapter is deliberately restricted to the official
GWTC-5.0 response contract and the O4b run. The generic wrapper fails closed if
its `catalog` stage is requested for a later run. A later catalog release
requires a separately implemented and validated adapter; changing
`--catalog-url` cannot relabel a different schema as GWTC-5.0. Until that
adapter exists, a new-run report must state that catalog follow-up is pending
rather than report a false zero-match result.

### Public O4b auxiliary diagnostic

GWOSC now publishes a limited O4 auxiliary inventory through NDS2 and OSDF
([release page](https://gwosc.org/O4/auxiliary/), DOI
`10.7935/kt51-6n86`). DANTE-Light freezes the exact upstream GitLab commit,
raw and LF-normalized CSV hashes, and all 25 published channel names in
`config/dante_light_o4b_aux_channels_v1.json`. Only the one H1 and two L1
channels classified as environmental monitors enter the frozen analysis.
Calibration, control and subtraction channels remain in the inventory for
auditability but do not enter this endpoint; 16 Hz state channels cannot reach
the frozen 20--500 Hz band.

This is an offline, diagnostic-only endpoint. Public availability is not a
channel-safety certificate, so its three possible measured outcomes are
`NO_AUXILIARY_EXCESS`, `PERSISTENT_BASELINE_COMPATIBLE`, and
`AUXILIARY_EXCESS`. None is a veto, a glitch label, or evidence of
astrophysical/instrumental origin. `AUXILIARY_EXCESS` requires the event-level
maximum to exceed both the max-over-channel time-shift null and the quiet
zero-lag null. The latter is essential for persistent lines: a high raw
coherence alone is not candidate-specific.

The final frozen cohort contains all 18 O4b escalations (8 H1, 10 L1) and five
local detector epochs. Each epoch uses 142--150 candidate-excluded 32 s CAT1
windows from a four-hour block; a calibration may be reused only within 12 h,
and the actual event-to-block distance is recorded. Results are 14
`NO_AUXILIARY_EXCESS`, four `PERSISTENT_BASELINE_COMPATIBLE`, zero
`AUXILIARY_EXCESS`, and zero unavailable events. This does not exclude an
instrumental origin because the public witness set is very limited.

NDS2 bindings are installed through Conda. For example, inside WSL:

```bash
micromamba create -p /path/to/gwosc-aux -f environment-o4b-aux.yml
```

Use an external cache (for example on `E:`) so reruns do not download the same
GPS/channel blocks again. The cache key includes detector, channel, exact GPS
interval, native and stored rates, and source; every object and value array is
SHA-256 checked. Reproduce the five frozen calibrations, then run the exact
event-to-epoch mapping:

```bash
bash scripts/run_dante_light_o4b_auxiliary_calibrations.sh \
  /path/to/gwosc-aux/bin/python /path/to/dante-light-o4b-aux-cache
bash scripts/run_dante_light_o4b_auxiliary_batch.sh \
  /path/to/gwosc-aux/bin/python /path/to/dante-light-o4b-aux-cache
python scripts/aggregate_dante_light_o4b_auxiliary.py
python scripts/verify_dante_light_o4b_auxiliary.py \
  --stage all --cache-dir /path/to/dante-light-o4b-aux-cache
```

The portable result is
`artifacts/dante_light/o4b_auxiliary/result_v1.json`; external cached samples
are not part of the Git repository. The verifier can check policy and result
artifacts without network access (`--stage policy` or `--stage artifacts`),
while `--stage cache` additionally validates every local cached byte.

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

`src/dante_light/aux_cache.py` remains the transport-neutral cache primitive
for future adapters. The O4b-only diagnostic uses the stricter float32 block
cache in `src/dante_light/o4b_auxiliary.py`; it passed exact cold/warm equality
and retains detector, channel, GPS interval, native/stored sample rates and
source. Neither cache is part of the synchronous Light scoring path.

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

# O3a native workflow interface: coverage and remaining activation gates

Author: Luca Cirfeta. Date: 2026-10-01. Local feature freeze: `138ed7c`.

## Delivered, without reopening the study

`src/dante_workflow/adapters/o3a_native.py` implements the existing native O3a
StageAdapter interface. It builds commands, pins each stage to its actual leaf
contract path and parses the actual nested cohort-verifier receipt. No numerical
parameter is chosen or supplied. The completed O3a H1/L1 diagnostic findings,
historical contracts and artifacts are unchanged.

This interface is **not registered** by the shared adapter factory. No production
profile/config/registry binding was created; public O3a selection remains blocked.
Direct construction is tested for development integration, not advertised as
a complete scientific workflow. A sealed full graph and its upstream/side-effect
gates are still required before activation.

## Primary-source command inventory

| Native stage | Script under scripts/ | Run selector | Verify selector | Leaf contract under config/ |
| --- | --- | --- | --- | --- |
| COHORT | run_dante_o3a_native_cohort.py | Default action | --verify | dante_o3a_native_cohort_v1.json |
| INDEX | run_dante_o3a_native_index.py | Default action | --verify | dante_o3a_native_index_v1.json |
| NATIVE_CALIBRATION | freeze_dante_o3a_native_calibration_cohort.py | Default freeze | --verify | dante_o3a_native_calibration_cohort_v1.json |
| RESCORE | run_dante_o3a_native_rescore.py | --run | --verify | dante_o3a_native_rescore_v3.json |
| THRESHOLDS | run_dante_o3a_native_thresholds.py | --run | --verify | dante_o3a_native_thresholds_v1.json |
| CLASSIFY | run_dante_o3a_native_classification.py | --run | --verify | dante_o3a_native_classification_v1.json |
| TAXONOMY | run_dante_o3a_native_taxonomy.py | --run | --verify | dante_o3a_native_taxonomy_v1.json |
| COINCIDENCE | run_dante_o3a_native_coincidence.py | --run | --verify | dante_o3a_native_coincidence_v2.json |
| PEM | run_dante_o3a_native_pem.py | --stage run | --stage verify | dante_o3a_native_pem_v1.json |

All commands receive only an explicit interpreter and path arguments. External
and primary roots share the existing `cache_root/o3a_native_v1` convention;
COHORT additionally receives raw_root. The adapter does not transplant O4a
arguments such as --stage run into scripts whose run action is implicit, add
runtime/scientific defaults, freeze new contracts, or archive failures.

Native calibration remains the separately approved evenly spaced complete-block
selector with context fallback from
`config/dante_o3a_native_calibration_selector_amendment_v1.json`, not the hash
stratification used for the distinct initial-calibration phase. Commands alone
do not replace their existing configuration/parent validation.

## Receipt boundary

The real cohort CLI prints `{summary, run_dir}`, not the flat O4a ledger receipt.
The adapter checks the nested summary's canonical artifact seal and PASS status,
requires a ledger basename, rejects traversal/drive/backslash paths and symlink
escape, then checks SHA-256 of the exact resolved ledger bytes. It hashes the
ledger without parsing scientific rows.

INDEX's workflow input manifest references those same cohort bytes. This is an
input binding, **not proof that INDEX consumed them**. That proof still depends
on the existing scientific INDEX verifier and its sealed cohort/replay parents.
The synthetic shared-controller test exercises receipt recording, adoption mode
and `verify_workflow`, but uses synthetic evidence and a fake runner exclusively.
Its PASS is not scientific O3a evidence.

## Gates discovered before public activation

1. Initial acquisition and initial-calibration acceptance CLIs expose execution,
   not autonomous --verify modes. `run_dante_o3a_raw_download.py` also writes a
   preflight. `freeze_dante_o3a_initial_calibration_acceptance.py` writes a
   contract, not a verification receipt. Existing parent/hash checks, such as
   `o3a_initial_thresholds._validate_acceptance_summary`, must not be described
   as a newly executed independent numerical calibration replay. The exact
   checks to expose and their claim boundary must be mapped first.
2. Existing verification is **not universally read-only**:
   - RESCORE CLI calls write_compact_rescore_artifact.
   - execute_thresholds(verify=True) writes a compact.
   - CLASSIFY and TAXONOMY verify branches write summary/compact; parent
     verification can have transitive writes as well.
   - verify_native_pem creates the compact if absent and checks it if present.
   - This is a positive finding of writes, not an exhaustive guarantee that
     all other verifiers have no side effects.
   No such command was run here. Before historical adoption, provide a binding
   that preserves original evidence; do not silently rewrite files merely
   because the numeric bytes would be equal or call these commands read-only.
3. Represent each existing preflight and its receipt dependencies in the exact
   production graph. Native INDEX already requires a stored preflight; rescore
   has input/CUDA preflight checks. Building run/verify argv is not sufficient
   to claim a clean fresh execution is runnable.
4. The full applicable-stage graph and transitive configuration/parent receipt
   bindings remain open. The test graph is a synthetic native subset using
   explicit external fixture parents, not an author-approved fresh-run graph.
   Comparative PEM and the post-hoc local study must not become universal stages
   just because they occurred in this O3a study.

These findings do not invalidate completed scientific O3a verification. They
define software productization work needed before offering an automated replay
or historical-adoption command. New scientific validation/applicability choices
still require the author's decision; no source-hash-only surrogate PASS.

## Observed tests and scope

- Windows complete controller: **269 PASS**, OS exit 0, 43.07s.
- WSL complete controller: **268 PASS, one Windows-only skip**, OS exit 0, 108.38s.
- Post-freeze native adapter suite: **45 PASS**, OS exit 0, 2.01s.
- Ruff lint/format for new module/tests: PASS, existing WSL tools.
- Scientific config/scripts/src/dante_light/data and public adapter factory:
  no diff. No dependencies installed, Git settings changed or files normalized.

Tests check actual source selectors/CONTRACT_REL paths, malformed scope/config,
nested seals/ledger hashes/path containment, unsupported actions and factory
blocking. Source inspection is not execution of argparse or scientific engines.
No strain download, productive job, numerical replay, real outcome inspection,
historical write, push, release or new Virgo/network method occurred. Existing
historical EOL/UI timing qualifications remain. Full multi-run readiness is open.

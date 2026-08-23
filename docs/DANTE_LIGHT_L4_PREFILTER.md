# DANTE-Light L4 prefilter research evaluations

L4 is a research-only cheap prefilter evaluated in front of the unchanged
DANTE-Light exact path. It is not active routing: every generated contract and
result records `routing_enabled: false`. All four completed development
protocols are negative: v1 reached 6.70% effective reduction, v2 reached at
most 8.70%, the predeclared v3 A+B primary reached 3.08%, and the v4
analytic-phase primary reached 0.67%, all below the frozen 50% gate. No
protocol opened its held-out confirmation or O4b outcomes. The exact
DANTE-Light path remains the supported path.

The scientific criteria live only in the versioned v1, v2, and v3 protocol JSON
files under `config/`. The protocol, split, screening result, evaluation
contract and feature ledgers are linked by SHA256 and canonical JSON digests.
Changing a criterion without freezing a new protocol fails closed.
The compact robust-candidate manifest allows split regeneration without the
312 MB P5 token cache while preserving its source SHA256 and candidate order.

V4 progressed from a label-blind feasibility probe to a frozen development
protocol on a fresh O4a cohort. Its primary returned `V4_NOT_READY`: overall
OOF AUC 0.634 and 0.67% constrained effective reduction. The synthetic
phase-ordering response did not translate into useful real-strain routing
separation; confirmation and O4b remain sealed. The frozen result and its
post-hoc, non-gating diagnostic are documented in
`docs/DANTE_LIGHT_L4_PREFILTER_V4_DEVELOPMENT_RESULT_2026-08-23.md` and
`artifacts/dante_light/prefilter_l4_v4_development/diagnostics_v4.json`.

The cross-version AUC values must be read carefully: v2 spectral evolution is
0.805, the v3 A+B primary is 0.718, and v4 is 0.634. The 0.805 value reproduced
inside the v3 dossier is the v2 control, not the v3 primary. V4 uses a fresh
1,010-window cohort rather than the shared 962-window v2/v3 cohort, so its
cross-version differences are descriptive rather than a controlled ablation.

## Output location

The scripts never write into historical `data/production` implicitly. Every
output directory is explicit. A recommended local layout is an external cache
such as `E:\dante_cache\dante_light_prefilter_l4_v2_*`. Large regenerable
ledgers stay outside Git; compact reviewed summaries and complete small result
JSONs belong under `artifacts/dante_light/`. A deterministic external bundle
can carry the ledgers needed for independent recalculation without placing
them in Git history.

Each cohort builder writes one `*_feature_ledger_v1.json` plus its JSONL rows.
The assembly step writes the locked contract, a combined evaluation ledger,
the copied protocol and the copied tuning artefact. The final evaluator writes
one machine-readable JSON report containing coverage, per-detector and
per-morphology retention intervals, compute reduction, exact-escalate coverage
and every PASS/FAIL gate.

## V3 A+B development commands and final status

V3 reuses the frozen v2 split but extracts only `development` rows. Its A/B
ablation on that cohort is hypothesis-generating because the v2 diagnostic
motivated the features. The untouched, disjoint `evaluation` rows were
reserved for confirmation and may be opened only after
`READY_FOR_CONFIRMATION`. The completed v3 run returned `NOT_READY`, so they
were not opened. See
`docs/DANTE_LIGHT_L4_PREFILTER_V3_NOT_READY_2026-08-22.md`.

Create the Linux/WSL LALSuite environment once for CBC reconstruction:

```bash
conda env create -f environment-dante-light-v3.yml
```

Then run from the repository root, replacing `<L4_V3>` with an external output
directory. The first three builders can use the regular Python environment;
the injection builder must use the pinned LALSuite environment.

```powershell
python scripts/build_dante_light_prefilter_v3_cohort_features.py --role background --output-dir <L4_V3>/background --strain-source auto --workers 4
python scripts/build_dante_light_prefilter_v3_cohort_features.py --role robust_candidate --output-dir <L4_V3>/robust --strain-source auto --workers 4
python scripts/build_dante_light_prefilter_v3_cohort_features.py --role known_glitch --output-dir <L4_V3>/known --strain-source auto --workers 4

conda run -n dante-light-v3 python scripts/build_dante_light_prefilter_v3_injection_features.py --output-dir <L4_V3>/injection --workers 4

python scripts/screen_dante_light_prefilter_v3.py --background <L4_V3>/background/background_feature_ledger_v3_development.json --robust <L4_V3>/robust/robust_candidate_feature_ledger_v3_development.json --known <L4_V3>/known/known_glitch_feature_ledger_v3_development.json --injection <L4_V3>/injection/injection_feature_ledger_v3_development.json --output <L4_V3>/final/screening_result_v3.json

python scripts/verify_dante_light_prefilter_v3_artifacts.py --background <L4_V3>/background/background_feature_ledger_v3_development.json --robust <L4_V3>/robust/robust_candidate_feature_ledger_v3_development.json --known <L4_V3>/known/known_glitch_feature_ledger_v3_development.json --injection <L4_V3>/injection/injection_feature_ledger_v3_development.json --screening <L4_V3>/final/screening_result_v3.json
```

The screening command intentionally exits 1 for a valid `NOT_READY` result;
the verifier exits 0 when that negative artifact is internally consistent and
exactly reproducible. Do not reinterpret verifier PASS as scientific PASS.

## V2 commands and mandatory stop gate

V2 uses O4a for primary development, O3b only for externally labelled
known-glitch controls, and reserves O4b for the one-shot later-run evaluation.
The following commands reproduce development without reading O4b outcomes:

```powershell
python scripts/build_dante_light_prefilter_v2_splits.py --output config/dante_light_prefilter_splits_v2.json --strain-source auto

python scripts/build_dante_light_prefilter_v2_cohort_features.py --role background --output-dir <L4_V2_BACKGROUND> --strain-source auto --workers 4
python scripts/build_dante_light_prefilter_v2_cohort_features.py --role robust_candidate --output-dir <L4_V2_ROBUST> --strain-source auto --workers 4
python scripts/build_dante_light_prefilter_v2_cohort_features.py --role known_glitch --output-dir <L4_V2_KNOWN> --strain-source auto --workers 4
python scripts/build_dante_light_prefilter_v2_injection_features.py --trials data/production/aggregated/astrophysical_injection_trials_o4a_idxq4-64_queryq4-64.csv --output-dir <L4_V2_INJECTION> --workers 4

python scripts/screen_dante_light_prefilter_v2.py --background <L4_V2_BACKGROUND>/background_feature_ledger_v2.json --robust <L4_V2_ROBUST>/robust_candidate_feature_ledger_v2.json --known <L4_V2_KNOWN>/known_glitch_feature_ledger_v2.json --injection <L4_V2_INJECTION>/injection_feature_ledger_v2.json --output <L4_V2_FINAL>/screening_result_v2.json

python scripts/verify_dante_light_prefilter_v2_artifacts.py --stage screening --background <L4_V2_BACKGROUND>/background_feature_ledger_v2.json --robust <L4_V2_ROBUST>/robust_candidate_feature_ledger_v2.json --known <L4_V2_KNOWN>/known_glitch_feature_ledger_v2.json --injection <L4_V2_INJECTION>/injection_feature_ledger_v2.json --screening <L4_V2_FINAL>/screening_result_v2.json
```

Exit 1 and `NOT_READY` is a scientifically valid negative result. Stop there:
do not build O4b features and do not tune again after seeing O4b. The frozen v2
run ended at this gate. Only a development `PASS` under a future, separately
frozen protocol would permit these conditional commands:

```powershell
python scripts/build_dante_light_prefilter_v2_shadow_features.py --records runs/dante_light/o4b_v2/shared/records.jsonl --screening <L4_V2_FINAL>/screening_result_v2.json --output-dir <L4_V2_SHADOW> --strain-source auto

python scripts/assemble_dante_light_prefilter_v2_evaluation.py --background <L4_V2_BACKGROUND>/background_feature_ledger_v2.json --shadow <L4_V2_SHADOW>/shadow_feature_ledger_v2.json --robust <L4_V2_ROBUST>/robust_candidate_feature_ledger_v2.json --known <L4_V2_KNOWN>/known_glitch_feature_ledger_v2.json --injection <L4_V2_INJECTION>/injection_feature_ledger_v2.json --screening <L4_V2_FINAL>/screening_result_v2.json --output-dir <L4_V2_FINAL>/evaluation

python scripts/evaluate_dante_light_prefilter_v2.py --contract <L4_V2_FINAL>/evaluation/evaluation_contract_v2.json --ledger <L4_V2_FINAL>/evaluation/evaluation_feature_ledger_v2.json --output <L4_V2_FINAL>/evaluation/prefilter_evaluation_result_v2.json
```

Development reduction is measured on frozen O4a background windows; final
effective compute reduction would be measured on all 768 realistic O4b shadow
windows. Both include deterministic rejected-window audit calls. They use the
same accounting but are deliberately different populations; only the held-out
quantity could support a later-run performance claim.

The optional post-hoc diagnostics are descriptive only. They cannot change
the frozen `NOT_READY` screen or authorize O4b evaluation:

```powershell
python scripts/diagnose_dante_light_prefilter_v2.py --background <L4_V2_BACKGROUND>/background_feature_ledger_v2.json --robust <L4_V2_ROBUST>/robust_candidate_feature_ledger_v2.json --known <L4_V2_KNOWN>/known_glitch_feature_ledger_v2.json --injection <L4_V2_INJECTION>/injection_feature_ledger_v2.json --screening artifacts/dante_light/prefilter_l4_v2/screening_result_v2.json --output <L4_V2_FINAL>/diagnostics_v2.json

python scripts/verify_dante_light_prefilter_v2_artifacts.py --stage diagnostics --background <L4_V2_BACKGROUND>/background_feature_ledger_v2.json --robust <L4_V2_ROBUST>/robust_candidate_feature_ledger_v2.json --known <L4_V2_KNOWN>/known_glitch_feature_ledger_v2.json --injection <L4_V2_INJECTION>/injection_feature_ledger_v2.json --screening artifacts/dante_light/prefilter_l4_v2/screening_result_v2.json --diagnostics artifacts/dante_light/prefilter_l4_v2/diagnostics_v2.json

python scripts/build_dante_light_prefilter_v2_bundle.py build --background <L4_V2_BACKGROUND>/background_feature_ledger_v2.json --robust <L4_V2_ROBUST>/robust_candidate_feature_ledger_v2.json --known-glitch <L4_V2_KNOWN>/known_glitch_feature_ledger_v2.json --injection <L4_V2_INJECTION>/injection_feature_ledger_v2.json --output <L4_V2_FINAL>/dante_light_prefilter_l4_v2_development_artifacts.zip

python scripts/build_dante_light_prefilter_v2_bundle.py check --bundle <L4_V2_FINAL>/dante_light_prefilter_l4_v2_development_artifacts.zip
```

## Historical v1 commands

The historical examples below use PowerShell from the repository root. Replace
`<L4_RUN>` with a local directory, for example
`data/runs/dante_light_l4_v1`. Raw public strain may be served from the local
mirror or GWOSC; `--strain-source auto` tries the supported normal path.

```powershell
python scripts/build_dante_light_prefilter_splits.py

python scripts/build_dante_light_prefilter_cohort_features.py --split config/dante_light_prefilter_splits_v1.json --role background --output-dir <L4_RUN>/background --strain-source auto --workers 4
python scripts/build_dante_light_prefilter_cohort_features.py --split config/dante_light_prefilter_splits_v1.json --role robust_candidate --output-dir <L4_RUN>/robust --strain-source auto --workers 4
python scripts/build_dante_light_prefilter_cohort_features.py --split config/dante_light_prefilter_splits_v1.json --role known_glitch --output-dir <L4_RUN>/known --strain-source auto --workers 4
python scripts/build_dante_light_prefilter_injection_features.py --split config/dante_light_prefilter_splits_v1.json --trials data/production/aggregated/astrophysical_injection_trials_o4a_idxq4-64_queryq4-64.csv --output-dir <L4_RUN>/injection --workers 4

python scripts/tune_dante_light_prefilter.py --background <L4_RUN>/background/background_feature_ledger_v1.json --robust <L4_RUN>/robust/robust_candidate_feature_ledger_v1.json --known <L4_RUN>/known/known_glitch_feature_ledger_v1.json --injection <L4_RUN>/injection/injection_feature_ledger_v1.json --output <L4_RUN>/threshold_tuning_v1.json

python scripts/build_dante_light_prefilter_features.py --manifest config/dante_light_o4b_shadow_v2.json --records config/dante_light_o4b_shadow_v2.jsonl --output-dir <L4_RUN>/shadow --strain-source auto

python scripts/assemble_dante_light_prefilter_evaluation.py --background <L4_RUN>/background/background_feature_ledger_v1.json --shadow <L4_RUN>/shadow/shadow_feature_ledger_v1.json --robust <L4_RUN>/robust/robust_candidate_feature_ledger_v1.json --known <L4_RUN>/known/known_glitch_feature_ledger_v1.json --injection <L4_RUN>/injection/injection_feature_ledger_v1.json --tuning <L4_RUN>/threshold_tuning_v1.json --output-dir <L4_RUN>/evaluation

python scripts/evaluate_dante_light_prefilter.py --contract <L4_RUN>/evaluation/evaluation_contract_v1.json --ledger <L4_RUN>/evaluation/evaluation_feature_ledger_v1.json --output <L4_RUN>/evaluation/prefilter_evaluation_result_v1.json
```

Do not use `--limit` for a scientific result; it produces an intentionally
incomplete development artefact. A `NOT_READY` exit must not be converted into
PASS by relaxing the protocol. L4 and the previous exact DANTE-Light path do
not produce identical compute traces: L4 measures whether expensive exact
evaluation could be avoided while retaining the frozen controls. Scientific
dispositions remain those of the unchanged exact path.

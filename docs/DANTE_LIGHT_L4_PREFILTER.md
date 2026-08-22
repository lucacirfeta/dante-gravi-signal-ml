# DANTE-Light L4 prefilter research evaluations

L4 is a research-only cheap prefilter evaluated in front of the unchanged
DANTE-Light exact path. It is not active routing: every generated contract and
result records `routing_enabled: false`. Both completed development protocols
are negative: v1 reached 6.70% effective reduction and v2 reached at most
8.70%, below the frozen 50% gate. Neither protocol opened its held-out O4b
outcomes. The exact DANTE-Light path remains the supported path.

The scientific criteria live only in the versioned v1 and v2 protocol JSON
files under `config/`. The protocol, split, screening result, evaluation
contract and feature ledgers are linked by SHA256 and canonical JSON digests.
Changing a criterion without freezing a new protocol fails closed.
The compact robust-candidate manifest allows split regeneration without the
312 MB P5 token cache while preserving its source SHA256 and candidate order.

## Output location

The scripts never write into historical `data/production` implicitly. Every
output directory is explicit. A recommended local layout is an external cache
such as `E:\dante_cache\dante_light_prefilter_l4_v2_*`. Large regenerable
ledgers stay outside Git; compact reviewed summaries belong under
`artifacts/dante_light/`.

Each cohort builder writes one `*_feature_ledger_v1.json` plus its JSONL rows.
The assembly step writes the locked contract, a combined evaluation ledger,
the copied protocol and the copied tuning artefact. The final evaluator writes
one machine-readable JSON report containing coverage, per-detector and
per-morphology retention intervals, compute reduction, exact-escalate coverage
and every PASS/FAIL gate.

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

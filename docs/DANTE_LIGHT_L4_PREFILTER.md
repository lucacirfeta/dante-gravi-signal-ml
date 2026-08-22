# DANTE-Light L4 prefilter evaluation

L4 is a research-only, cheap excess-energy prefilter evaluated in front of the
unchanged DANTE-Light exact path. It is not active routing: every generated
contract and result records `routing_enabled: false`. A PASS means that the
frozen held-out gates passed; it does not promote L4 into production.

The scientific criteria live only in
`config/dante_light_prefilter_protocol_v1.json`. The protocol, tuning result,
evaluation contract and feature ledger are linked by SHA256 and canonical JSON
digests. Changing a criterion without freezing a new protocol fails closed.
The compact robust-candidate manifest allows split regeneration without the
312 MB P5 token cache while preserving its source SHA256 and candidate order.

## Output location

The scripts never write into historical `data/production` implicitly. Every
output directory is explicit. A recommended local layout is
`data/runs/dante_light_l4_v1/`; it stays out of Git until an evaluation has
been reviewed and deliberately selected as a release artefact.

Each cohort builder writes one `*_feature_ledger_v1.json` plus its JSONL rows.
The assembly step writes the locked contract, a combined evaluation ledger,
the copied protocol and the copied tuning artefact. The final evaluator writes
one machine-readable JSON report containing coverage, per-detector and
per-morphology retention intervals, compute reduction, exact-escalate coverage
and every PASS/FAIL gate.

## End-to-end commands

The examples below use PowerShell from the repository root. Replace
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

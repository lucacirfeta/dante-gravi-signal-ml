# Architecture-paper claim ledger

Status values: `VERIFIED`, `TO_DRAFT`, `PROHIBITED`.

| ID | Status | Planned statement | Evidence |
|---|---|---|---|
| C01 | VERIFIED | The released workflow contains 15 ordered stages with an explicit DAG. | `config/dante_workflow_productization_v1.json`; `artifacts/dante_workflow/productization_v1_release.json` |
| C02 | VERIFIED | The release receipt reports `PASS_VERIFIED_WORKFLOW` and all 15 stages as verified. | `artifacts/dante_workflow/productization_v1_release.json`; `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md` |
| C03 | VERIFIED | CLI and UI resolve the same content-addressed run identity and artifact graph for the accepted release. | `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md`; `docs/DANTE_WORKFLOW_UI_CHECKPOINT_2026-09-05.md` |
| C04 | VERIFIED | Closing the UI does not terminate the independent workflow worker. | `docs/DANTE_WORKFLOW_UI_CHECKPOINT_2026-09-05.md`; `docs/DANTE_WORKFLOW_RECOVERY_CHECKPOINT_2026-09-05.md` |
| C05 | VERIFIED | Retry and resume preserve completed verified evidence and create new attempt directories for incomplete work. | `docs/DANTE_WORKFLOW_RECOVERY_CHECKPOINT_2026-09-05.md`; `docs/DANTE_WORKFLOW_QUICKSTART.md` |
| C06 | VERIFIED | Scientific configuration is read-only and digest-pinned at the orchestration boundary. | `config/dante_workflow_productization_v1.json`; `docs/DANTE_WORKFLOW_PRODUCTIZATION_IMPLEMENTATION_PLAN_2026-09-03.md` |
| C07 | VERIFIED | `NATIVE_CALIBRATION` consumes the index-window manifest so the frozen exclusion guard can reject overlap with the index population. | `config/dante_workflow_productization_v1.json`; `docs/DANTE_WORKFLOW_PRODUCTIZATION_IMPLEMENTATION_PLAN_2026-09-03.md` |
| C08 | VERIFIED | Adopted scientific stages were verified but not recomputed by the productization release. | `artifacts/dante_workflow/productization_v1_release.json`; `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md` |
| C09 | VERIFIED | The bounded public smoke has a documented clean-clone CPU path and an optional distinct CUDA identity. | `docs/DANTE_WORKFLOW_QUICKSTART.md`; `docs/DANTE_WORKFLOW_FRESH_INSTALL_RESULT_2026-09-06.md` |
| C10 | VERIFIED | Human usability acceptance passed after guided controls, progress, ETA, logs, recovery guidance, and a dedicated results view were added. | `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md`; commits `2b56eee`, `d816eab`, `15198f5`, `2277a58` |
| C11 | VERIFIED | The architecture reduces undocumented operator choices by expressing stage order, identities, and verification in one contract. | Derived narrowly from C01, C03, C05, C06, and C10 as a design outcome, not a comparative performance result. |
| C12 | VERIFIED | The separation of operational progress from immutable evidence supports interruption-safe local operation. | Derived narrowly from C04 and C05 without a universal fault-tolerance claim. |
| C13 | PROHIBITED | The productized workflow establishes globally significant coincidences or an astrophysical discovery. | Explicitly excluded by `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md`. |
| C14 | PROHIBITED | CPU and CUDA produce equivalent scientific outputs. | Explicitly not claimed by `docs/DANTE_WORKFLOW_QUICKSTART.md`. |
| C15 | PROHIBITED | The workflow is a public real-time alerting system. | Explicitly excluded by the frozen product contract and release result. |
| C16 | PROHIBITED | Productization itself independently reproduced all adopted O4a calculations. | Release execution mode is `ADOPTED_VERIFIED_EXISTING`; see C08. |
| C17 | VERIFIED | The paper DAG is generated from the frozen stage/dependency contract and includes the content-digested index-window manifest edge into native calibration. | `paper_draft/workflow_architecture_v1/generate_figures.py`; `config/dante_workflow_productization_v1.json` |
| C18 | VERIFIED | The UI is a loopback-only disposable controller and does not execute scientific stages in HTTP request handlers. | `docs/DANTE_WORKFLOW_UI_DECISION.md`; `src/dante_workflow/ui/controller.py`; `src/dante_workflow/ui/views.py` |
| C19 | VERIFIED | Divergent evidence is rejected rather than overwritten, while mutable progress is updated atomically as operational state. | `src/dante_workflow/state.py`; `src/dante_workflow/ui/smoke.py`; tests under `tests/test_dante_workflow_*` |
| C20 | VERIFIED | The run key hashes a canonical contract containing workflow, source, root paths, and concrete stage-command digests. | `src/dante_workflow/orchestrator.py`; `src/dante_workflow/schema.py` |
| C21 | VERIFIED | One durable worker lease owns a run identity; stale work is marked interrupted and retry receives a new attempt identity. | `src/dante_workflow/state.py`; `docs/DANTE_WORKFLOW_RECOVERY_CHECKPOINT_2026-09-05.md` |
| C22 | VERIFIED | The recovery matrix covers five injected runner failures, changed receipts, inert child termination, and durable-write failures without treating them as scientific-run observations. | `docs/DANTE_WORKFLOW_RECOVERY_CHECKPOINT_2026-09-05.md`; `tests/test_dante_workflow_recovery.py`; `tests/test_dante_workflow_state.py` |
| C23 | VERIFIED | The packaged public smoke used two H1/L1 windows and produced byte-identical CLI/UI receipts with zero recorded score delta under the existing tolerance and no disposition mismatch. | `artifacts/dante_workflow/public_smoke_ui_checkpoint_2026-09-06.json`; `docs/DANTE_WORKFLOW_FRESH_INSTALL_RESULT_2026-09-06.md` |
| C24 | VERIFIED | Release identifiers and SHA-256 values in Table 1 match the versioned release result and canonical Git receipt blob. | `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md`; `artifacts/dante_workflow/productization_v1_release.json` |
| C25 | VERIFIED | The human gate first failed, then passed after guided controls and a dedicated verification-results view were implemented and reverified. | `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md` |
| C26 | VERIFIED | The public CPU smoke is a bounded portability path; full corrected-O4a execution still requires the frozen archive and canonical scientific runtime. | `docs/DANTE_WORKFLOW_QUICKSTART.md`; `docs/DANTE_WORKFLOW_FRESH_INSTALL_RESULT_2026-09-06.md` |
| C27 | VERIFIED | A report can be produced only from a complete currently verified workflow and remains hash-bound to the release receipt and source evidence. | `src/dante_workflow/reporting.py`; `tests/test_dante_workflow_reporting.py` |
| C28 | VERIFIED | The recorded receipt-file SHA-256 identifies the canonical LF Git blob; a Windows checkout with text conversion can materialize different bytes while the parsed receipt still self-verifies. | `paper_draft/workflow_architecture_v1/EVIDENCE_AUDIT.md`; `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md`; `.gitattributes` |
| C29 | VERIFIED | Snakemake and Nextflow are general workflow systems that express dependencies and support reproducible execution; DANTE does not claim to replace them. | Koster and Rahmann (2012), DOI `10.1093/bioinformatics/bts480`; Di Tommaso et al. (2017), DOI `10.1038/nbt.3820`; bounded comparison in `main.tex` |
| C30 | VERIFIED | W3C PROV-DM provides a general provenance vocabulary; DANTE uses a narrower domain-specific receipt model and does not claim PROV conformance. | W3C Recommendation `https://www.w3.org/TR/2013/REC-prov-dm-20130430/`; `src/dante_workflow/state.py`; `src/dante_workflow/schema.py` |
| C31 | VERIFIED | FAIR applies high-level findability, accessibility, interoperability, and reusability principles to digital research objects, including workflows; the release does not claim FAIR compliance. | Wilkinson et al. (2016), DOI `10.1038/sdata.2016.18`; bounded comparison in `main.tex` |
| C32 | VERIFIED | GWOSC public strain and data-quality products enable independent detector-data analysis. | LIGO Scientific Collaboration and Virgo Collaboration (2021), DOI `10.1016/j.softx.2021.100658` |
| C33 | VERIFIED | The public smoke exercises only the public-data portability boundary, whereas full corrected-O4a reproduction also requires the frozen archive, runtime, contracts, and intermediate evidence. | `docs/DANTE_WORKFLOW_QUICKSTART.md`; `docs/DANTE_WORKFLOW_FRESH_INSTALL_RESULT_2026-09-06.md`; `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md` |

## Rules

1. Add a row before adding a new material claim to the manuscript.
2. Never cite chat text, memory, or an unversioned local path as evidence.
3. Quantitative values must be read from the cited artifact during drafting.
4. Engineering verification must not be restated as statistical significance.
5. Changes to a scientific population, threshold, score, or validation method
   require a separate scientific decision and are outside this paper branch.

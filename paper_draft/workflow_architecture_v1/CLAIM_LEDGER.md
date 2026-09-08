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
| C11 | TO_DRAFT | The architecture reduces undocumented operator choices by expressing stage order, identities, and verification in one contract. | Derive narrowly from C01, C03, C05, C06, and C10; describe as a design outcome, not a comparative performance result. |
| C12 | TO_DRAFT | The separation of operational progress from immutable evidence supports interruption-safe local operation. | Derive narrowly from C04 and C05; avoid universal fault-tolerance claims. |
| C13 | PROHIBITED | The productized workflow establishes globally significant coincidences or an astrophysical discovery. | Explicitly excluded by `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md`. |
| C14 | PROHIBITED | CPU and CUDA produce equivalent scientific outputs. | Explicitly not claimed by `docs/DANTE_WORKFLOW_QUICKSTART.md`. |
| C15 | PROHIBITED | The workflow is a public real-time alerting system. | Explicitly excluded by the frozen product contract and release result. |
| C16 | PROHIBITED | Productization itself independently reproduced all adopted O4a calculations. | Release execution mode is `ADOPTED_VERIFIED_EXISTING`; see C08. |

## Rules

1. Add a row before adding a new material claim to the manuscript.
2. Never cite chat text, memory, or an unversioned local path as evidence.
3. Quantitative values must be read from the cited artifact during drafting.
4. Engineering verification must not be restated as statistical significance.
5. Changes to a scientific population, threshold, score, or validation method
   require a separate scientific decision and are outside this paper branch.

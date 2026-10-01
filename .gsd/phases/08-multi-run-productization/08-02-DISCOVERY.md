# O3a controller integration: structural checkpoint

Date: 2026-10-01 Europe/Rome. Original checkpoint: awaiting author decision,
not implemented. Resolution the same day: author explicitly selected **A**.
See 08-03 for the implemented schema boundary; the original source inventory
below describes the pre-change state, not current schema-v2 support.

The author asked to proceed with productization after confirming closure of
the approved H1/L1 O3a diagnostic study. Integration must preserve that study,
not rerun it or claim V1/O3b has been scientifically validated.

## Primary evidence

| Boundary | Current source | Consequence |
| --- | --- | --- |
| Workflow schema | `src/dante_workflow/schema.py`: `SCHEMA_VERSION`, `REQUIRED_STAGE_NAMES`, `_validate_graph` | Schema v1 accepts exactly the frozen 15-stage graph, including COMPARE and REPORT; O3a cannot be represented by merely selecting a different run name. |
| Scientific parent gates | Same `_validate_graph`: NATIVE_CALIBRATION and RESCORE checks | Verified cohort, exact index-window consumption and parent-stage gates must remain mandatory, not disappear with graph generalization. |
| Adapter factory | `src/dante_workflow/adapters/__init__.py`: `build_adapter` | Only `o4a_corrected` is implemented; other adapters fail closed. |
| Cohort/index receipt recording | `src/dante_workflow/orchestrator.py`: `_record_index_window_manifest`, `_record_verified_outputs` | O3a needs its own exact receipt interpretation; stage-name parity alone does not prove matching bytes or consumption semantics. |
| Independent graph verification | `src/dante_workflow/verification.py`: `verify_workflow` | The full verifier replays each stage and checks exact cohort/index manifest identity. Do not bypass it to adopt historical results. |
| Profile readiness | `src/dante_workflow/run_profiles.py`: `readiness` | O3a H1/L1 has an existing method binding but no implemented workflow binding. Public V1 membership is not scientific execution permission. |

Existing O3a runners expose different CLIs, not a common O4a command template:

| Existing runner | Existing verification interface |
| --- | --- |
| `scripts/run_dante_o3a_native_cohort.py` | `--verify`, with raw/external roots |
| `scripts/run_dante_o3a_native_index.py` | `--verify`, with external root |
| `scripts/run_dante_o3a_native_rescore.py` | `--verify`, with external root |
| `scripts/run_dante_o3a_native_thresholds.py` | `--verify`, with external root |
| `scripts/run_dante_o3a_native_classification.py` | `--verify`, with external root |
| `scripts/run_dante_o3a_native_taxonomy.py` | `--verify`, with external root |
| `scripts/run_dante_o3a_native_coincidence.py` | `--verify`, with external root |
| `scripts/run_dante_o3a_native_pem.py` | `--stage verify`, with external root |

This is a source-interface inventory, not an executed verifier replay or a
complete fresh-run graph. Initial acquisition/calibration/scan, native
calibration selector, report generation, comparative PEM and bounded post-hoc
local follow-up still need explicit applicable-stage and artifact mapping.
Do not automatically make the paired O4a comparison or two-target post-hoc
study mandatory for every future O3a execution. Their inclusion cannot be
inferred from a graph label or the generic software-scope authorization.

## Decision requested before source changes

**A — recommended:** introduce a separate schema v2 for explicit per-profile
workflow graphs. Keep schema v1 validation and the frozen O4a contract intact.
The new graph must be validated against the named supported adapter/profile,
not accept arbitrary shortened graphs. Preserve verified dependencies,
content-hash gates, source identity, immutable run keys and hidden outcomes
until independent verification. Derive the O3a mapping from existing
versioned contracts, not chat constants. Adoption of existing artifacts must
run their verifiers, record adoption separately and never claim a new
productive run occurred.

**B — alternative:** retain the common O4a-only schema and build a separate
O3a controller. This avoids extending the common schema but duplicates
orchestration/GUI/recovery maintenance and does not fully meet the common
multi-run engine direction without later consolidation.

Neither choice changes scientific parameters. Removing v1's exact graph check,
using no-op successful stages, copying O4a receipts or auto-enabling V1 is not
an acceptable shortcut.

## Checks at this checkpoint

- Native profile regression: **42 PASS**, observed OS exit 0, 0.99 seconds.
- No adapter/schema/scientific-source/config patch; no production process,
  download, outcome inspection or historical artifact mutation.
- Earlier full-suite evidence is retained in 08-01-VERIFICATION; it was not
  rerun or presented as a new end-to-end scientific replay here.
- Planning changes are local and uncommitted; no push or publication.

Plan-check coverage: two tasks (discovery plus author checkpoint), dependency
08-01 exists, wave 2 follows wave 1, concrete files/verification/must-haves,
and no enabled adapter or missing runtime wiring is represented as complete.
Implementation must be split into later bounded plans after the decision.

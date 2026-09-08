# DANTE workflow architecture paper — implementation plan

Status: **IN_PROGRESS**

Branch: `paper/dante-workflow-architecture-v1`

Software baseline: annotated tag `dante-workflow-productization-v1`, merge
commit `e8f2098`

## Objective

Produce a standalone arXiv preprint describing the implemented and verified
DANTE workflow architecture. The paper documents how the scientific pipeline
is made reproducible and operable; it does not introduce a new candidate
catalogue, statistical population, threshold, or discovery claim.

## Frozen scope

The manuscript may claim only what can be traced to the tagged source tree,
the versioned release receipt, or an explicitly cited acceptance artifact.
The following boundaries are fixed:

- the 15-stage workflow and its dependency graph are reported as implemented;
- scientific stages and their existing verifiers remain authoritative;
- productization does not recompute or reinterpret adopted O4a results;
- mutable progress is operational state, while receipts and verified evidence
  remain immutable;
- CPU and CUDA are distinct run identities; equivalence is not claimed;
- coincidence and PEM remain diagnostic follow-up products;
- no global-significance, discovery, public real-time, or alerting claim is
  authorized;
- publication is a final human action and is outside autonomous execution.

## Evidence sources

| Source | Permitted use |
|---|---|
| `artifacts/dante_workflow/productization_v1_release.json` | Release identity, 15 verified stages, execution modes, graph and receipt digests |
| `docs/DANTE_WORKFLOW_PRODUCTIZATION_RESULT.md` | Acceptance summary and scientific boundary |
| `docs/DANTE_WORKFLOW_QUICKSTART.md` | Public reproduction path and operator semantics |
| `docs/DANTE_WORKFLOW_FRESH_INSTALL_RESULT_2026-09-06.md` | Fresh-install evidence and limitations |
| `docs/DANTE_WORKFLOW_RECOVERY_CHECKPOINT_2026-09-05.md` | Interruption, retry, and failure-injection evidence |
| `docs/DANTE_WORKFLOW_UI_CHECKPOINT_2026-09-05.md` | UI/CLI identity and process-separation evidence |
| `docs/DANTE_WORKFLOW_UI_DECISION.md` | Frozen local-UI choice and bounded measurements |
| `config/dante_workflow_productization_v1.json` | Versioned DAG and immutable contract references |

## Work packages

### A1 — Freeze the manuscript contract

Outputs:

- `paper_draft/workflow_architecture_v1/README.md`
- `paper_draft/workflow_architecture_v1/CLAIM_LEDGER.md`
- `paper_draft/workflow_architecture_v1/main.tex`

Done when the draft identifies the tagged baseline, receipt, scope, section
structure, and prohibited claims without importing numbers from memory or chat.

### A2 — Build the architecture and lifecycle figures

Create source-controlled figures for:

1. the 15-stage DAG, including the `INDEX` window-manifest dependency into
   `NATIVE_CALIBRATION`;
2. run identity, attempt directories, stage receipts, and final receipt;
3. UI/server/worker separation and interruption-resume behavior;
4. the fail-closed verification path from hidden outcomes to report release.

Figures must be generated from versioned source or checked manually against
the frozen config. They must not encode scientific thresholds or outcomes.

### A3 — Draft the evidence-backed manuscript

Complete introduction, design objectives, architecture, provenance model,
operator workflow, verification methodology, results, limitations,
reproducibility, and conclusion. Every quantitative or strong qualitative
statement must have a claim-ledger entry and a source path.

### A4 — Add literature and related-work context

Use primary sources for workflow provenance, reproducible computational
science, gravitational-wave data analysis, and the software components named
in the implementation. Verify bibliographic metadata before adding it. Keep
comparison claims narrower than the cited evidence.

### A5 — Verify consistency and build

Required gates:

- all claim-ledger entries resolve to versioned evidence;
- release identities and digests match the receipt byte-for-byte;
- the DAG in text and figures matches the frozen config;
- LaTeX and bibliography compile without errors or unresolved references;
- the PDF receives visual inspection for clipping, illegible figures, and
  broken links;
- a separate scientific review confirms that engineering evidence is not
  presented as discovery significance.

### A6 — Prepare the arXiv package

Build a minimal source bundle from the verified manuscript. Record its file
manifest and SHA-256 values. Do not submit it automatically.

## Completion criteria

The paper is ready for human review when its source and PDF build from the
tag-derived branch, every material claim is evidence-linked, the architecture
and reproduction path are complete, and all scientific limitations appear in
the abstract, main text, and conclusion where relevant.

---
phase: P6.2-A5
verified: 2026-09-08
status: passed
score: 7/7 must-haves verified
is_re_verification: false
gaps: []
---

# Architecture-paper verification

## Must-haves

| Truth | Status | Evidence |
|---|---|---|
| The manuscript is based on the released productization state. | VERIFIED | Annotated tag `dante-workflow-productization-v1` resolves to merge commit `e8f2098e99c9103514702ab680e9952333dc4eb7`; that commit is an ancestor of the paper branch. |
| Release identities are transcribed correctly. | VERIFIED | `scripts/verify_dante_workflow.py` returned `PASS_VERIFIED_WORKFLOW`; run, contract, graph, and receipt digests agree with the release object, while the report digest agrees with the versioned release result and Table I. |
| The architecture represents the frozen graph. | VERIFIED | Contract loader found 15 stages; `INDEX <- COHORT`, `NATIVE_CALIBRATION <- COHORT, INDEX`, and `RESCORE <- INDEX, NATIVE_CALIBRATION` match the text and generated DAG. |
| Material claims are evidence-linked and bounded. | VERIFIED | Claim ledger contains 33 unique entries: 29 `VERIFIED`, 4 `PROHIBITED`, and zero `TO_DRAFT`. All repository evidence paths checked during A5 exist. |
| Bibliographic comparisons use primary sources and avoid conformance claims. | VERIFIED | W3C PROV-DM, FAIR, Snakemake, Nextflow, and GWOSC metadata were checked against their publisher or standards pages; the manuscript explicitly denies PROV/FAIR/general-engine equivalence claims. |
| Source and bibliography compile cleanly. | VERIFIED | MiKTeX `pdflatex`, `bibtex`, `pdflatex`, `pdflatex` completed; no unresolved citation/reference, BibTeX warning, or overfull box was reported. |
| The rendered paper is readable. | VERIFIED | All six rendered pages were inspected; figures, table, bibliography, links, and two-column text were legible with no clipping. |

## Artifacts and wiring

| Artifact | Exists | Substantive | Wired |
|---|---:|---:|---:|
| `main.tex` | yes | yes | cites the bibliography and all three generated figures |
| `references.bib` | yes | yes | resolved by BibTeX |
| `CLAIM_LEDGER.md` | yes | yes | maps manuscript claims to versioned or primary evidence |
| `generate_figures.py` | yes | yes | loads and validates the frozen workflow config |
| `figures/fig_workflow_dag.pdf` | yes | yes | included as Fig. 1 |
| `figures/fig_evidence_lifecycle.pdf` | yes | yes | included as Fig. 2 |
| `figures/fig_runtime_boundary.pdf` | yes | yes | included as Fig. 3 |

## Empirical checks

- workflow regression suite: `120 passed, 1 skipped` in WSL;
- figure generator lint: Ruff PASS;
- release verifier: `PASS_VERIFIED_WORKFLOW`, 15/15 verifier statuses zero;
- DAG assertions: PASS for all 15 stages and the native-calibration guard edge;
- bibliography: five cited primary sources, zero unresolved citations;
- PDF: six pages, US Letter, visually inspected page by page.

## Anti-pattern scan

No placeholder claims, unresolved citations, discovery language, CPU/CUDA
equivalence claim, or assertion of a full O4a recomputation was found. The
manuscript states that the release adopts and verifies existing scientific
artifacts.

## Documented limitation

The receipt-file digest identifies the canonical LF Git blob. A Windows
checkout can materialize CRLF bytes because the tagged path has no explicit LF
attribute. Parsed receipt verification passes and the manuscript discloses the
distinction. Changing the released software or issuing a patch tag remains a
separate release decision; it is not silently folded into the paper branch.

## Human verification

The six-page PDF has received technical visual inspection. Authorial and
editorial approval before arXiv submission remains a human publication action,
not an A5 verification gap.

## Verdict

PASS for the bounded architecture-paper claims. No scientific population,
threshold, score, validation rule, or adopted artifact was changed.

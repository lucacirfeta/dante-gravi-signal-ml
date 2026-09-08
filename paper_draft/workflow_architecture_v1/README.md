# DANTE workflow architecture paper

This directory contains the architecture-paper source begun under P6.2.

## Reproducible baseline

- software tag: `dante-workflow-productization-v1`
- tagged commit: `e8f2098`
- workflow ID: `dante-o4a-corrected-productization-v1`
- run key: `3c9ad0765b4d1f9f9a49cf105ca223058aafdba42ac25793d0ecff1d1d384e94`
- release receipt: `../../artifacts/dante_workflow/productization_v1_release.json`
- operator guide: `../../docs/DANTE_WORKFLOW_QUICKSTART.md`

The source branch is `paper/dante-workflow-architecture-v1`, created directly
from the annotated tag. The paper may evolve on this branch; the software
baseline above does not.

## Current state

The manuscript has a compiled, evidence-backed seven-page draft,
contract-generated architecture figures, a primary-source bibliography, and a
completed A5 consistency/scientific review. A deterministic minimal arXiv
source bundle has passed clean-extraction compilation and remains unsubmitted.
The claim ledger remains the gate for introducing substantive statements; the
evidence audit records receipt, build, regression, and portability checks.

## Source inventory

- `main.tex`: manuscript source;
- `CLAIM_LEDGER.md`: permitted and prohibited claim map;
- `EVIDENCE_AUDIT.md`: read-only evidence checks;
- `VERIFICATION.md`: A5 implementation and build verification;
- `SCIENTIFIC_REVIEW.md`: bounded scientific and LIGO-specific review;
- `references.bib`: primary-source bibliography;
- `prepare_arxiv_bundle.py`: deterministic bundle builder and checker;
- `ARXIV_SOURCE_PREPARATION.md`: prepared-output identity and submission boundary;
- `release/`: source bundle and external SHA-256 manifest;
- `generate_figures.py`: contract-backed figure generator;
- `figures/`: generated PDF and PNG figures.

## Build

From this directory, using a TeX environment with REVTeX 4.2:

```shell
pdflatex -interaction=nonstopmode -halt-on-error main.tex
bibtex main
pdflatex -interaction=nonstopmode -halt-on-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error main.tex
```

No publication command is part of this directory.

Prepare and independently verify the minimal arXiv source bundle with:

```shell
python prepare_arxiv_bundle.py build
python prepare_arxiv_bundle.py check
```

The builder normalizes TeX and BibTeX line endings to LF, uses fixed ZIP
metadata, and writes a hash manifest beside the minimal archive. It does not
submit or upload the bundle.

Generate the contract-backed architecture figures with:

```shell
python generate_figures.py
```

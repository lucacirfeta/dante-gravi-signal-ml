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

The manuscript is a compilable structural draft. Evidence-backed prose,
figures, bibliography, consistency checks, and PDF review remain in the
implementation plan. The claim ledger is the gate for introducing substantive
statements.

## Build

From this directory, using a TeX environment with REVTeX 4.2:

```shell
pdflatex -interaction=nonstopmode -halt-on-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error main.tex
```

No publication command is part of this directory.

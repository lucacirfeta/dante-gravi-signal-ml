# Architecture-paper evidence audit

Date: 2026-09-08

Scope: read-only checks performed while drafting the architecture paper. No
scientific artifact, configuration, population, threshold, score, or class was
changed.

## Release receipt

`python scripts/verify_dante_workflow.py --release
artifacts/dante_workflow/productization_v1_release.json` returned
`PASS_VERIFIED_WORKFLOW` with 15 stages and verifier exit status zero for each
stage.

The release receipt identities read from the verified object are:

- run key:
  `3c9ad0765b4d1f9f9a49cf105ca223058aafdba42ac25793d0ecff1d1d384e94`;
- contract digest:
  `1d7270c0bcd15b3c344f94bb37fe82033b67bf4ad12615bb50b5efab43422cdd`;
- artifact-graph digest:
  `188a93c5b73cac50987e208f289729f4b17650e7f82fd0d91ecb1b7a736049fa`;
- receipt self-digest:
  `3b062e473e70e348ba5f39cbca17676cf63eaa575ea1d95639280bd664440aa4`.

## Serialized-byte portability observation

The release result records
`a2061ffbd96a25421968bfc0fd14798a72e31152e50e4481aa7f1c6a825d9d86`
as the SHA-256 of the runtime and versioned receipt bytes. A direct audit found:

```text
git ls-files --eol artifacts/dante_workflow/productization_v1_release.json
i/lf    w/crlf  attr/

working-tree SHA-256
f4936f867a90fa351aa5f8aed42985eeb1b9e366996efd1b2fb984cecd3dc238

canonical Git-blob SHA-256
a2061ffbd96a25421968bfc0fd14798a72e31152e50e4481aa7f1c6a825d9d86

working tree after CR removal
a2061ffbd96a25421968bfc0fd14798a72e31152e50e4481aa7f1c6a825d9d86
```

Thus the recorded digest is correct for the canonical LF Git blob and the
runtime serialization. The Windows checkout used for this audit materialized
CRLF bytes because the receipt path has no explicit LF rule. Parsed-object
self-verification still passes. The manuscript labels the value as the
canonical receipt-byte digest and reports working-tree newline translation as
a limitation; it does not claim that every checkout materializes identical
bytes.

Changing the released tag or defining a productization patch release is a
separate release decision and is not performed on the paper branch.

## A5 build and regression verification

The primary-source manuscript was compiled on 2026-09-08 with MiKTeX using
`pdflatex`, `bibtex`, `pdflatex`, and `pdflatex`. The result contains six pages.
The final log contains no unresolved citations or references, no BibTeX
warnings, and no overfull boxes. All six rendered pages were visually
inspected.

Additional checks:

- `tests/test_dante_workflow_*`: 120 passed and one Windows-only test skipped
  in WSL;
- Ruff on `generate_figures.py`: PASS;
- frozen DAG assertions: 15 stages and exact `COHORT -> INDEX`,
  `COHORT + INDEX -> NATIVE_CALIBRATION`, and
  `INDEX + NATIVE_CALIBRATION -> RESCORE` dependencies: PASS;
- claim ledger: 33 unique claims, 29 verified, four prohibited, zero pending;
- primary-source bibliography: five resolved citations.

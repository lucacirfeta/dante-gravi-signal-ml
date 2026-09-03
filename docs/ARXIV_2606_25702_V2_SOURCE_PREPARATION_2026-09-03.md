# arXiv:2606.25702 v2 source preparation

Status: **READY_FOR_HUMAN_REVIEW_NOT_SUBMITTED**

Prepared: 3 September 2026

Target: *DANTE: A Reference-Guided Unsupervised Pipeline for Extended-Transient Anomaly Characterization in LIGO O4a*

No arXiv submission, IGWN post, CQG change, Zenodo update, or other external
publication was made as part of this preparation.

## Source provenance

- official v1 source: `https://arxiv.org/src/2606.25702`;
- downloaded source archive SHA-256:
  `b41595aa4182bb5fe2e54f9775e5dd7183a4feb34919f1cdb3e5f9fdf7366e2d`;
- exact v1 `main.tex` SHA-256:
  `53e9706d749c9502301576c26e6394255fae875b9d22089a645467bd9c374539`;
- exact v1 `main.tex` size: 137,333 bytes.

The exact arXiv v1 source reports a historical 140-event workflow, three
families, and three singleton events. The completed corrected reconstruction
instead audits a later frozen catalogue of 10,429 detector--GPS identities and
produces 10,942 corrected candidates. Those are different populations. The v2
source therefore does **not** replace the historical 140-event tables or
figures with the 10,942-candidate reconstruction. It preserves them as
historical outputs, explicitly withdraws their use as corrected or discovery
claims, and inserts the bounded correction evidence separately.

## Manuscript changes

- inserted the dated v2 correction note immediately after `\maketitle`;
- documented the controlled padding result: 169/10,429 affected windows,
  120 class changes, and 97 routing reversals;
- separated controlled causal evidence from the joint representation and
  calibration rebuild: 10,022 shared identities, 407 historical-only, 920
  corrected-only, and 1,626 shared class changes;
- stated that 12/920 corrected-only candidates have historical right-edge
  geometry without establishing causality;
- stated that 2/9 primary pooled-null PEM targets are corrected-only, neither
  is an edge case, and both have `NO_CORRELATION` verdicts;
- corrected the preprocessing contract to whitening with symmetric context
  before cropping;
- bounded the pooled-null shortlist as diagnostic rather than globally
  trial-corrected;
- removed or qualified operational, discovery, physical-veto, native-purity,
  FPR-guarantee, and bitwise-reproducibility overclaims;
- retained historical results only for provenance and comparison;
- changed `main.tex` by 136 insertions and 66 deletions relative to the exact
  arXiv v1 source.

## Prepared outputs

Staging root:
`E:/dante_cache/publication_drafts/arxiv_2606_25702_v2_20260903`

- revised `main.tex`: 119,873 bytes; SHA-256
  `0713f01778eb5e70d0edad33c737c5234adab238569684a1d9dda18c5568847f`;
- compiled `main.pdf`: 19,097,642 bytes, 27 pages; SHA-256
  `dce8318de1615b5fd09eb17499723965270a1ebe0a79f269396da1d1cd7f6b1c`;
- submission bundle `arxiv_2606_25702_v2_source_2026-09-03.zip`:
  12,486,815 bytes; SHA-256
  `915a701e41260f86939f33fb39af0e6de296158ad7de85b707824836dd6ffced`.

The ZIP contains exactly 15 entries: `main.tex`, `00README.json`, and the 13
source images. It excludes the preserved v1 copy and all generated auxiliary,
log, bibliography-cache, and PDF files.

## Verification

- extracted the ZIP into a clean temporary directory;
- compiled the extracted source with two successful `pdflatex` passes;
- obtained a 27-page PDF with zero undefined citations and zero undefined
  references;
- retained one inherited overfull `\hbox` warning at `main.tex` line 1168;
- rendered all 27 PDF pages and visually checked layout, correction-note
  placement, edited sections, figures, tables, and final pages;
- visual QA result: `PASS`.

## Proposed arXiv Comments field

> v2: Corrects an HDF5-boundary whitening-context defect (169/10,429 windows; controlled replay changes 120 DSD classes and 97 routing decisions) and reports the completed provenance-locked reconstruction. Broader catalogue differences are not attributed solely to the defect because the representation and calibration were rebuilt.

## Publication boundary

The prepared source is a review artifact, not a submitted revision. A human
must review the rendered PDF and explicitly authorize any arXiv submission.
The IGWN closure draft remains separate, and CQG and Zenodo are untouched.

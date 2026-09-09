# DANTE 3.8.0 release notes

DANTE 3.8.0 packages the content-addressed workflow controller described in
[`arXiv:2609.08695`](https://arxiv.org/abs/2609.08695). It exposes the same
15-stage orchestration contract through an installable CLI and browser UI,
with durable resume state, immutable attempt history, fail-closed provenance
checks, and readable verification receipts.

This release adopts and re-verifies the existing corrected-O4a artifacts. It
does not recompute them and does not change any scientific score, population,
threshold, null construction, detector semantics, or conclusion. The bundled
public CPU smoke is a two-window technical replay, not a full corrected-O4a
release or a discovery claim.

## Highlights

- Install the controller from the repository with `python -m pip install .`.
- Add the guided local UI with `python -m pip install ".[ui]"`.
- Plan, run, resume, inspect, and verify through one shared controller.
- Verify a bounded public replay using only documented commands and public
  GWOSC data.
- Inspect progress, ETA, logs, verification results, report, and receipt in the
  browser UI.
- Reuse existing evidence only after its hashes and contracts verify.

## Evidence

- Windows workflow regression: 126 passed.
- WSL workflow regression: 125 passed, 1 expected Windows-only skip.
- Public GitHub HTTPS clean clone: isolated Python 3.11.15 CPU install, smoke,
  verification, reuse, UI discovery, and 14 focused tests passed.
- GitHub Actions CPU smoke and artifact-contract run:
  <https://github.com/lucacirfeta/dante-gravi-signal-ml/actions/runs/34375935061>.

No external colleague was available for a separate pre-release human
reproduction. The evidence is therefore described as verified public
clean-environment reproduction, not independent human reproduction. Formal
JOSS review will include independent installation and functional checks.

## Compatibility and licensing

The installable controller requires Python 3.11 or newer. The scientific
runtime remains governed by the versioned CPU/CUDA environment files in the
source checkout. Release 3.8.0 is licensed GPL-3.0-only.

The historical DANTE 3.7.0 archive remains available at
<https://doi.org/10.5281/zenodo.21912589>. That version DOI does not identify
3.8.0. The reserved 3.8.0 version DOI is
<https://doi.org/10.5281/zenodo.22681395>; it becomes registered when the
Zenodo record is published.

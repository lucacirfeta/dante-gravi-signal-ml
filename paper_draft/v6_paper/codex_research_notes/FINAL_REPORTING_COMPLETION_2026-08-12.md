# Final reporting completion audit — 2026-08-12

Scope: close the remaining reviewer-level reporting gaps without altering the
validated numerical experiments or their scientific interpretation.

## Code-to-manuscript findings

The manuscript descriptions were checked directly against the load-bearing
implementations and current artifacts.  Whitening/crop, Q64 rendering, Top-68
MIL scoring, chronological block bootstrap, physical coincidence, PEM
taxonomy rejoin, synthetic absorption, blind-map SNR scaling and CBC projection
were inspected in code before editing the papers.

One concrete text discrepancy was found and corrected: the final absorption
matrix uses duration 1.0 s for Blip and Koi Fish but 1.5 s for Scattered Light.
The previous generic statement "duration 1 s" was not true for all three
morphologies.  No artifact or result was changed.

## Reporting additions

Both papers now define the uncertainty protocols and endpoint hierarchy.  The
CQG paper additionally gives a self-contained statistical-analysis subsection.
The updated text records:

- DSD complete-block bootstrap, cross-run/known-glitch/robustness/absorption
  resampling units and replicate counts;
- primary versus diagnostic endpoints and the absence of a global multiplicity
  correction across exploratory failure-mode controls;
- PEM family-wise max-statistic construction, window-level bootstrap and quiet
  zero-lag control;
- absorption amplitude as a peak in whitened-strain units, not matched-filter
  SNR, plus held-out/index population separation;
- blind-map matched-filter SNR definition and PSD construction;
- CBC waveform assumptions, parameter draws, raw-strain injection, paired
  controls and the definition of a successful trial.

arXiv remains explicitly a v5 continuation/correction; CQG remains the
self-contained journal article.

## Verification checkpoint

Initial post-edit checks:

- manuscript claim checker with artifact hashes: PASS;
- arXiv compile: PASS, 12 pages;
- CQG compile: PASS, 25 pages;
- cover compile: PASS, 1 page;
- reproducibility bundle rebuild and round-trip: PASS; final file count and ZIP
  SHA256 are recorded in the delivery checkpoint outside the payload, avoiding
  a self-referential provenance record.

The final verifier, test, numerical-grep and visual-PDF results are recorded in
the LAB_NOTEBOOK entry created after completion of those gates.

## External gate closed (2026-08-14)

The frozen bundle was published as the Zenodo dataset
`10.5281/zenodo.21925453`.  The Zenodo API reports the exact deposited filename
`dante_v6_reproducibility.zip`, size 8,958,047 byte, and MD5
`2b84a96f557629a8a2805c3c08feede4`, matching the local frozen payload.  Its
SHA256 is `a04ef27a564ab356103eb1ae14031d14649359e884d571aa08a832bc822bd37c`.
The separate software release is DANTE 3.7.0,
`10.5281/zenodo.21912589`.

The deposited payload is intentionally not rebuilt after inserting its DOI in
the submission manuscripts: doing so would change the already published ZIP
and create a circular sequence of deposits.  Post-deposit manuscript and
notebook edits are verified separately from the immutable evidence payload.

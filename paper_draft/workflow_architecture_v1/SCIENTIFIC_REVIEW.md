# Scientific review of the architecture-paper draft

Review date: 2026-09-08

## Executive summary

The manuscript asks whether the operational contract of the existing DANTE
corrected-O4a analysis can be made explicit, content-addressed, recoverable,
and verifiable through one CLI/UI control path. Its evidence supports that
bounded engineering claim. It does not present a new anomaly-search result,
candidate population, statistical calibration, or astrophysical inference.

## Main strengths

- The paper distinguishes adopted-and-reverified artifacts from recomputation.
- Run identity, immutable evidence, mutable progress, interruption behavior,
  and report gating are described separately and tied to versioned evidence.
- The native-calibration exclusion dependency from the index-window manifest
  is explicit in the graph and prose.
- The adopted 10,942-row corrected catalogue is distinguished from the
  immutable 10,429-row historical v6 comparison baseline.
- The related-work section compares concrete reuse, retry, ownership, operator,
  and release-boundary semantics and acknowledges Git, Bazel, and Nix as direct
  content-addressing prior art.
- Limitations appear in the abstract, main text, dedicated limitations section,
  and conclusion.

## Critical issues

None within the frozen architecture-paper scope.

## Minor issue

Problem: the tagged JSON receipt has canonical LF bytes, while a Windows
checkout may materialize CRLF bytes.

Evidence: `EVIDENCE_AUDIT.md` records both byte hashes and shows that removing
CR restores the canonical digest.

Why it matters: a reader comparing raw working-tree bytes could otherwise
misinterpret newline conversion as scientific evidence drift.

Disposition: adequately disclosed in the limitations and verification report.
A software patch release with an explicit LF attribute would be a separate
release choice, not a manuscript-side scientific correction.

## Claim audit

| Claim | Category | Evidence | Status | Severity |
|---|---|---|---|---|
| The released workflow is a 15-stage content-addressed DAG. | reproducibility | frozen config, release receipt, generated figure | SUPPORTED | none |
| CLI and UI share one orchestrator and run identity. | reproducibility | UI decision/checkpoints, code paths, parity receipt | SUPPORTED | none |
| Retry preserves verified evidence and creates new attempts for incomplete work. | robustness | recovery checkpoint and regression tests | SUPPORTED | none |
| The release verifies rather than recomputes adopted O4a artifacts. | methodology | execution modes in the release receipt | SUPPORTED | none |
| Productization adopts the corrected 10,942-row catalogue, not the historical 10,429-row comparison baseline. | methodology | release receipt, native classification summary, final comparison summary | SUPPORTED | none |
| The public smoke supports portable local use. | generalization | two-window clean-clone CPU/UI evidence | PARTIALLY SUPPORTED and explicitly bounded | none |
| Productization establishes detection significance or discovery. | statistics/physics | no supporting experiment; prohibited by scope | NOT CLAIMED | none |

## Experimental assessment

The engineering checks cover schema validation, artifact identity, dependency
gating, controlled failure injection, recovery, interface parity, clean-clone
smoke execution, final receipt verification, and a human usability gate. They
do not cover a fresh full-archive scientific recomputation, arbitrary hardware,
distributed execution, or hostile multi-user operation. The manuscript states
all four exclusions.

## Statistical assessment

No new hypothesis test, bootstrap population, threshold, false-alarm rate, or
candidate significance is estimated. Engineering test counts are reported as
overlapping checkpoints and are not treated as independent statistical trials.
No comparison is made between intra-detector and cross-detector null
constructions. Coincidence and PEM remain diagnostic.

## LIGO-specific assessment

The architecture paper does not imply Virgo participation in O4a and does not
generalize the H1/L1 public smoke into an observing-run result. GWOSC is cited
only as the public strain and data-quality access boundary. The paper does not
alter whitening order, detector-specific gates, morphology-specific treatment,
or excluded PEM channels.

## Publication risk

LOW for the bounded architecture and reproducibility claims. Risk would become
HIGH if adopted-stage verification were restated as an independent full-O4a
recalculation, or if pooled diagnostic follow-up were restated as global
significance; both formulations are explicitly prohibited in the current text.

## Required experiments

None for the present engineering claim. A fresh full-archive run and a
separately frozen statistical design would be required for any stronger claim
about numerical portability, candidate significance, or astrophysical
discovery.

## Final recommendation

Accept for internal release-readiness review. Human editorial approval and the
manual arXiv submission decision remain outstanding.

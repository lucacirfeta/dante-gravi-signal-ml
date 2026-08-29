# O4a edge-padding correction plan

Status: **AUTHORIZED, EXECUTION IN PROGRESS**  
Scope: corrective O4a reconstruction; no arXiv/CQG/Zenodo publication in this increment.

## Scientific objective

Determine the effect of incomplete right-hand whitening context in the historical
v1 production scan, remove that failure mode from the executable pipeline, and
reconstruct the O4a result chain without overwriting the published baseline.

The historical catalogue remains immutable evidence.  Corrected outputs must use
new versioned paths and must not be promoted until every upstream dependency and
downstream claim has been reverified.

## Phase 1 — freeze and diagnose the failure

- Preserve the completed 10,429-window canonical replay and its hashes.
- Produce a machine-readable audit that separates ordinary windows from the
  169 file-edge windows and recomputes score, DSD-class and routing transitions.
- Demonstrate causality using the historical clipped-context path on a frozen
  example, without changing thresholds or tolerances.

Acceptance: 10,260 ordinary windows reproduce within the frozen `2e-7`
tolerance; every mismatch is accounted for by the frozen edge cohort; no partial
run is labelled PASS.

## Phase 2 — regression tests and production correction

- Add tests for complete 4 s left/right context, deterministic adjacent-file
  stitching and failure when either side is unavailable.
- Replace per-file edge clipping in the production producer with a continuous,
  provenance-checked source view.
- Keep canonical order `whiten_context -> extract_clean_subwindow`; do not weaken
  the padding check and do not restore `edge_tolerance=4` as a scientific path.

Acceptance: boundary windows built from adjacent local files equal a direct GWOSC
40 s fetch sample-for-sample; missing context fails closed; non-boundary output is
unchanged.

## Phase 3 — dependency impact audit

- Audit O3b primary-index construction, O4a native-index construction,
  background threshold calibration and every stored cohort for edge windows.
- Reuse an artifact only if its identities, preprocessing contract and source
  hashes prove it cannot contain incomplete-padding inputs.
- If an upstream artifact is affected, archive it and rebuild it before the O4a
  scan.  No post-hoc threshold adjustment is allowed.

Acceptance: each dependency has a machine-readable `UNAFFECTED`, `REBUILD`, or
`NOT_VERIFIABLE` disposition with evidence.

## Phase 4 — corrected O4a freeze and run

- Freeze the exact raw-file manifest, CAT1/HW-injection policy, software state,
  reference artifacts, thresholds or recalibration protocol, and output root.
- Use the existing `E:` raw mirror and cache; download only content-addressed
  gaps.  Do not mutate `E:/o4a` or historical `data/production` outputs.
- Run the complete O4a discovery path into a new versioned production root.

Acceptance: every submitted window has symmetric 4 s context and a provenance
record; zero silent drops; resumable failures remain fail-closed.

## Phase 5 — downstream reconstruction and comparison

- Rebuild candidate scores/classes, taxonomy/families, physical coincidence,
  PEM, figures, tables and final reports from the corrected catalogue.
- Compare v1 and corrected runs using detector+GPS identities: overlap, removed
  and new candidates, shared-score deltas, class transitions, permutation-
  invariant family agreement, coincidence and PEM changes.
- Recheck the two historical singleton candidates separately.

Acceptance: all claims have a number and an artifact path; no v1 downstream
artifact is silently rejoined to a changed taxonomy.

## Phase 6 — documentation and paper preparation

- Update `LAB_NOTEBOOK`, claim ledger, master numbers and reproducibility notes.
- Prepare corrected arXiv and CQG sources, but do not publish or submit them.
- Record a transparent technical erratum and create a new release/Zenodo version
  only after explicit user authorization.

Acceptance: complete pertinent and full test suites pass, both paper builds pass,
and a final fail-closed grep finds no superseded counts or claims.


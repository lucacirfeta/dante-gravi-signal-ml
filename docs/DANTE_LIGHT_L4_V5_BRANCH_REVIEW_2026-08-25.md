# DANTE-Light L4 v5 branch review (2026-08-25)

## Review target and decision boundary

- Branch: `codex/dante-light-prefilter-v3-design`
- Reviewed implementation head (before this report-only commit):
  `4eb192d67fb102cff71fa74385fb54995419a857`
- Base: `origin/main`
- Reviewed implementation difference from base: 73 commits, 159 files,
  137,585 insertions and 32 deletions.
- Human-readable comparison:
  <https://github.com/lucacirfeta/dante-gravi-signal-ml/compare/main...codex/dante-light-prefilter-v3-design>

The branch is technically eligible for human merge review. This does not make
the L4 prefilter operationally ready. It integrates the frozen v3--v5 research
protocols, negative results, provenance infrastructure, reproduction scripts,
and regression tests. `routing_enabled` remains false; v5 confirmation and O4b
remain sealed and were not accessed.

## Scientific result being integrated

The one-shot v5 development decision is `V5_NOT_READY` on 1,800 windows. Both
frozen student architectures were evaluated with all five frozen replicates.
All ten candidates failed detector-wise exact-teacher fidelity. Raw 1-D
Spearman correlations were 0.617--0.718 and complex-STFT correlations were
0.326--0.594; no replicate met the frozen lower-bound requirement of 0.90.

Every protected detector/morphology retention gate passed at the selected
thresholds, but the retention-compatible operating points avoided only
1.83--10.83% of background calls, below the frozen 50% product gate. The
negative result therefore concerns teacher fidelity and useful reduction, not
a morphology-specific retention failure. It falsifies these two architectures
under the frozen training contract; it does not establish that distillation in
general is impossible.

No candidate is eligible for confirmation. No unlock receipt may be issued,
no v5 threshold or replicate may be selected post hoc, and no O4b outcome may
be opened under this protocol.

## Implementation-plan audit

The five-plan design in
`docs/DANTE_LIGHT_L4_PREFILTER_V5_DESIGN_PROPOSAL_2026-08-23.md` was followed:

1. Identity audit and label-blind feasibility work completed.
2. Protocol, power contract, fresh train/development/confirmation identities,
   and confirmation seal completed before outcome access.
3. Native O4a teacher ledger and two-architecture, five-replicate training
   completed under the frozen optimizer contract.
4. Development opened once for both architectures and closed as
   `V5_NOT_READY`.
5. Conditional confirmation and prospective O4b stages were correctly not
   executed because Plan 4 did not pass.

## Independent checkout verification

Verification was run from a fresh clone at
`E:\dante_cache\clean_clone_v5_merge_review_4eb192d`, not from the producing
working tree. The clone head matched the reviewed implementation head and
remained clean.

The fail-closed v5 checks returned:

- freeze: `PASS_IDENTITY_ONLY_NOT_OPENED`, 22,800 split rows and 1,440 trials;
- teacher ledger: `PASS_COMPLETE`, 19,200 rows, 2,400 blocks, native O4a
  novelty-score target;
- training freeze: `PASS_TRAINING_FREEZE`, with development, confirmation and
  O4b access lists empty;
- training: `PASS_TRAINING_COMPLETE`, ten replicates;
- development: `PASS_VERIFIED_DEVELOPMENT`, scientific status
  `V5_NOT_READY`, routing disabled, confirmation and O4b access lists empty.

The complete independent-clone suite returned **495 passed, 5 skipped, 0
failed** in 178.09 s. The five skips are explicit missing optional resources:
the published reference-artifact bundle, production reference index,
calibrated thresholds, smoke-test reference index, and the `nds2` Python
client. None is a silent PASS or a v5 scientific gate.

## Portability defect found during review

The first clean clone exposed four deterministic provenance failures that the
producing checkout did not show. Global `core.autocrlf=true` converted
provenance-bound Python and Markdown sources to CRLF, while frozen contracts
contained SHA256 values for LF bytes. This invalidated the v3 design-basis hash
and v4 feasibility source hashes.

Commit `4eb192d` fixes the root cause in `.gitattributes` by freezing LF
checkout bytes for provenance-bound `scripts/*.py`, `src/**/*.py`, and
`docs/DANTE_LIGHT*.md`. A second fresh clone reproduced the expected SHA256
values and passed the complete suite. No scientific value, threshold, cohort,
or result artifact changed.

## Merge recommendation and successor boundary

Recommendation: merge only after a human reviews the comparison above and
confirms that the large frozen cohorts and compact evidence artifacts belong
in `main`. The merge should be understood as integration of reproducible
research infrastructure and a negative result, not activation of L4.

After merge, any successor must begin on a new branch. The next scientifically
valid increment is training-only diagnosis of the fidelity failure, followed
by a separately reviewed design proposal. Capacity, temporal aggregation,
rank-aware objectives, cohort identities, and promotion gates are scientific
choices and must be frozen before a new development outcome is opened.

# DANTE-Light L4 prefilter experiment lineage

This ledger prevents later experimental increments from being mistaken for
replacements of earlier negative results. Each version is an append-only
successor: its frozen contracts, evidence and bounded verdict remain part of
the repository history even when a later version changes the hypothesis.

| Version | Result checkpoint | Bounded result | Historical anchor |
|---|---|---|---|
| v3 | fixed STFT signed/ridge development | `NOT_READY`; weak NSBH separation | `8f9c7fa` |
| v4 | fixed phase-aware development | `V4_NOT_READY`; synthetic phase response did not transfer to real detector noise | `dedbc1e` |
| v5 | native-teacher student distillation | `V5_NOT_READY`; protected retention passed but teacher-rank fidelity failed | `37e7d32` |
| v6 | pooling/loss/capacity screening | `V6_NOT_READY`; fidelity failed before Phase C | `ad5d6e9` |
| v7 | selective-deferral risk calibration | `V7_NOT_READY_RISK_CALIBRATION`; safety failed, corrected cost-only evidence positive | `491ee04` plus the v7 cost erratum |

Repository ancestry was checked again on 2026-08-27 after PR #4:

- `main` at merge commit `43cc015` contains the complete v3, v4, v5, v6 and
  v7 history;
- v6 result commit `ad5d6e9` is an ancestor of the v7 branch;
- v7 result and cost-erratum commit `0e0a093` is a parent of merge commit
  `43cc015`;
- the proposed v8.1 design starts from `43cc015` on a separate branch and does
  not rewrite or replace any earlier experiment result.

The scientific synthesis is deliberately bounded. Across v2--v7, no evaluated
low-cost path satisfied the joint fidelity, morphology-safety and operational
contract. Direct negative NSBH evidence exists for v2, v3, v4 and v7;
mini-bank coverage was inadequate, scattering was excluded on feasibility
grounds, and v5--v6 stopped at upstream teacher-fidelity gates. These are not
six interchangeable NSBH retention experiments and must not be reported as
such.

v8.1 is intentionally outside the lossy-prefilter sequence: it proposes exact
path optimization under an equivalence gate and non-destructive review
prioritization under per-morphology top-of-queue gates. Its design proposal is
`docs/DANTE_LIGHT_V8_1_DESIGN_PROPOSAL_2026-08-27.md`; no v8.1 scientific gate
or production promotion is frozen by this lineage update.

The first v8.1 engineering checkpoint is
`docs/DANTE_LIGHT_V8_1_PHASE0_RESULT_2026-08-28.md`. It resolves the Top-k
source-of-truth defect without changing outputs, identifies Q-transform as the
dominant measured exact-path stage, and records that operator review capacity
is still unmeasured. It does not promote the shared engine or freeze a ranking
budget.

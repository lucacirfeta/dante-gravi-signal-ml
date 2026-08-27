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

Repository ancestry was checked on 2026-08-27:

- `main` at merge commit `9568430` contains the complete v3, v4 and v5
  history;
- v6 result commit `ad5d6e9` is an ancestor of the v7 branch;
- the v7 branch descends from `main` without dropped or rewritten experiment
  commits;
- merging the v7 branch therefore carries v6 and v7 forward together rather
  than replacing either one.

The scientific synthesis is deliberately bounded. Across v2--v7, no evaluated
low-cost path satisfied the joint fidelity, morphology-safety and operational
contract. Direct negative NSBH evidence exists for v2, v3, v4 and v7;
mini-bank coverage was inadequate, scattering was excluded on feasibility
grounds, and v5--v6 stopped at upstream teacher-fidelity gates. These are not
six interchangeable NSBH retention experiments and must not be reported as
such.

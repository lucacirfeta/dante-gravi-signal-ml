# DANTE-Light L4 prefilter v4: feasibility dossier

Date: 2026-08-23  
Status: **FEASIBILITY COMPLETE; AWAITING SCIENTIFIC DECISION**  
Boundary: **not a frozen v4 protocol; no candidate selected; routing disabled**

## Scope and anti-circularity boundary

This study answers three engineering questions before any v4 experimental
contract is frozen:

1. Can a genuinely phase-aware statistic distinguish an ideal ordered chirp
   from phase-destroyed and noise controls at low computational cost?
2. What parameter-space coverage and filtering-kernel cost result from an
   illustrative NSBH mini bank?
3. Are compact raw-strain and complex-STFT student shapes computationally
   plausible before spending a protected cohort on training or selection?

The versioned feasibility config explicitly forbids candidate selection,
protocol freeze, routing, development labels, the reserved confirmation
partition, and O4b outcomes. Inputs are deterministic synthetic signals,
unlabelled random arrays, the already-open v3 timing ledger, and a waveform
parameter grid without detector outcomes. Therefore these results cannot
support retention, false-dismissal, generalization, or operational claims.

## Correction to the v3 cost-benefit interpretation

The earlier qualitative comparison mixed the median prefilter cost with a p95
exact-path cost. That does not estimate either expected batch compute or tail
latency. For a rejection fraction (r), prefilter cost (C), and avoidable
exact-path cost (S), the identifiable expected saving from the available
marginal data is

\[
  E[\Delta] = r E[S] - E[C],
\]

only under the explicit assumption that rejection and (S) are independent.
The 962 frozen v3 development timing rows give:

| Quantity | Value |
|---|---:|
| v3 A+B rejection fraction | 3.0797% |
| mean prefilter cost, all windows | 6.454 ms |
| median prefilter cost (descriptive) | 5.385 ms |
| p95 prefilter cost (descriptive) | 13.344 ms |
| mean avoidable exact-path cost | 342.484 ms |
| expected gross saving | 10.548 ms/window |
| expected net saving | **+4.094 ms/window** |
| mean break-even rejection fraction | 1.884% |

Thus v3 is not mean-compute negative on this benchmark. It is modestly positive
under the independence assumption, but it still misses the frozen 50% product
requirement by a wide margin and the small net margin is environment-sensitive.
No net p95 can be inferred: it requires per-window paired prefilter timing,
routing decision, and exact-path timing. Marginal p95 values must not be added
or subtracted.

## Phase-aware analytic probe

The probe band-passes a 32 s whitened 1-D input, obtains analytic phase via the
Hilbert transform, unwraps it, estimates frame-level instantaneous frequency,
and measures ordered frequency evolution plus phase-fit residuals. This is a
phase-sensitive diagnostic rather than another magnitude-only STFT summary.

On one deterministic ideal quadratic chirp, 64 independent phase-scrambled
controls, and 64 Gaussian-noise controls:

| Diagnostic | Ordered chirp | Phase-scrambled controls |
|---|---:|---:|
| frequency-time Spearman | 0.839 | p95 0.208 |
| cubic circular-phase residual | 0.0058 | median 0.926 |

Mean CPU runtime is 12.386 ms/window on the recorded machine. This establishes
only that the implementation responds to phase ordering in an ideal synthetic
case. It does not show separability for realistic NSBH signals in detector
noise, robustness across masses/spins/SNR, or safe retention of non-CBC
morphologies.

## Illustrative NSBH mini-bank coverage

The study uses LALSimulation `IMRPhenomNSBH`, a single-spin non-precessing
frequency-domain NSBH model, with the aLIGO ZeroDetHighPower PSD. The 108-point
stress grid spans black-hole masses 5/10/20 solar masses, neutron-star masses
1/1.4/2/3 solar masses, aligned black-hole spins -0.5/0/0.5, and tidal
deformabilities 0/400/800. Matches maximize time and phase. This is deliberately
an easier in-family aligned-spin diagnostic, not a population prior.

| Bank size | minimum match | p05 match | median match | kernel p95 |
|---:|---:|---:|---:|---:|
| 1 | 0.034 | 0.035 | 0.066 | 1.254 ms |
| 4 | 0.068 | 0.070 | 0.120 | 5.086 ms |
| 8 | 0.120 | 0.134 | 0.210 | 9.867 ms |
| 16 | 0.198 | 0.205 | 0.506 | 19.742 ms |
| 32 | 0.413 | 0.495 | 1.000 | 39.647 ms |

No minimal-match acceptance threshold was defined, so this table is not a
PASS/FAIL gate. Nevertheless, 4--8 templates leave most of even this limited
grid poorly covered; 32 templates improve the median while the worst point
remains only 0.413 and the filtering kernel is already about 40 ms at p95.
For scale, the aligned-spin O4 GstLAL bank contains 1.8 million parameter sets
over a much broader compact-binary space. The comparison is contextual, not a
claim that this feasibility kernel implements GstLAL.

The mini bank also excludes precession, eccentricity, higher modes, waveform
systematics, PSD estimation, waveform generation, normalization, and I/O.
Narrowing it around the previously weak 10+1.4 solar-mass injection would lower
cost but would create the benchmark-overfitting risk this study was designed
to avoid.

## Random-weight student compute probe

Two untrained proxies were timed only to bound architecture cost:

| Proxy | Parameters | CPU batch-1 mean | Additional preprocessing |
|---|---:|---:|---:|
| raw 1-D depthwise CNN | 3,665 | 0.941 ms | none beyond the contracted input |
| complex-STFT 2-D CNN | 1,369 | 0.468 ms | 1.977 ms mean CPU STFT |

Random weights provide no evidence of learnability, calibration, teacher
fidelity, morphology retention, or useful rejection. A real distillation study
must put the student upstream of the expensive Q-transform/DINO path; using
DINO spectrograms as student input would retain the dominant cost that the
prefilter is meant to avoid. Knowledge distillation is a compression strategy,
not evidence that these particular proxies will preserve DANTE decisions.

## Feasibility interpretation, not a protocol decision

- The phase-aware path is computationally plausible and reacts correctly to
  an ideal phase-ordering falsification test. Whether its statistic and
  representation should become a frozen candidate remains a scientific choice.
- A tiny 4--8-template bank is not supported as broad NSBH protection by this
  in-family coverage curve. A narrower targeted bank would require an explicit
  scientific scope and independent generalization design.
- Compact students are computationally plausible, but there is currently zero
  empirical evidence of distilled fidelity or protected-stratum retention.
- The corrected v3 mean-compute balance is positive but small. Future cost
  decisions must use paired per-window measurements whenever routing is tested.

No ordering above selects a v4 primary. The next step is a human scientific
decision about which candidate(s), if any, deserve a new frozen O4a development
and sealed-confirmation contract. That freeze must specify fresh GPS blocks or
fresh injections, label the previous cohort exploratory, and verify that the
confirmation partition has never been inspected. Until then the exact
DANTE-Light path remains unchanged.

## Reproduction and verification

From the repository root:

```powershell
python scripts/audit_dante_light_prefilter_v3_cost.py --ledger-root E:\dante_cache\dante_light_prefilter_l4_v3_development
python scripts/run_dante_light_prefilter_v4_feasibility.py
```

Run the bank study in the pinned WSL LALSuite environment:

```bash
/home/atafe/miniforge3/envs/dante-lalsuite-v3/bin/python scripts/run_dante_light_prefilter_v4_bank_coverage.py
```

Then verify every compact artifact and rebuild the derived summary atomically:

```powershell
python scripts/verify_dante_light_prefilter_v4_feasibility.py --write-summary artifacts/dante_light/prefilter_l4_v4_feasibility/feasibility_summary_v4.json
```

The verifier checks config/source hashes, local cost-input provenance,
mean-accounting identities, matrix byte hash, match symmetry and diagonal,
coverage recomputation, monotonicity, synthetic phase controls, and the
feasibility-only access boundary. A verifier PASS means internal consistency,
not scientific or operational PASS.

## Primary technical references

- Allen et al., [FINDCHIRP](https://arxiv.org/abs/gr-qc/0509116), for the
  matched-filter context.
- Sakon et al., [O4 compact-binary template bank](https://arxiv.org/abs/2211.16674),
  for realistic bank scale and coverage context.
- [LALSimulation IMRPhenomNSBH documentation](https://lscsoft.docs.ligo.org/lalsuite/lalsimulation/_l_a_l_sim_i_m_r_phenom_n_s_b_h_8c.html),
  for the waveform model and its domain limitations.
- Hinton, Vinyals, and Dean,
  [Distilling the Knowledge in a Neural Network](https://arxiv.org/abs/1503.02531),
  for the teacher-student compression concept.

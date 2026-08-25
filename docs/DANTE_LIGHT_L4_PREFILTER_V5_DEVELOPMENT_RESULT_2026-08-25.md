# DANTE-Light L4 v5 development result (2026-08-25)

## Decision

**`V5_NOT_READY`**. Neither frozen student architecture satisfies the
predeclared development contract. All ten architecture/replicate candidates
fail the detector-wise exact-teacher fidelity gate, and none reaches the 50%
background-call reduction requirement after the protected-stratum constraints
and deterministic 5% audit stream are applied.

This is a valid negative one-shot development result. No architecture or seed
is selected, routing remains disabled, the confirmation partition remains
sealed, and O4b was not accessed. The result must not be converted into a PASS
by choosing the most favorable replicate, weakening a gate, or retuning on the
same development cohort.

## Frozen scope and provenance

- Development-contract digest:
  `003e83ead7d416f2fd6f6bfa010f65ddf4f180c6f0ba98b8f46a1e13062e5b48`
- Development-contract file SHA256:
  `e4c53644f051e662da0603f9a63b7d72d1a5ca49a5566ebb9c38e145a0cf935d`
- Code freeze commit: `c4b6202b689e990e18c55d3da9ad1447bdf8e917`
- Development-result digest:
  `9860d39b39355bde032d7526ba136edd65940741157a2f963d8e8badc42fe63b`
- Screening-summary digest:
  `4295ae5cae39dbc5a298b82f44f0dee30702a9c0fe9581596f7b249eae565bcb`
- Frozen audit seed: `4959280729208813634`
- Frozen block-bootstrap seed: `11343894472345246308`
- Audit fraction: `0.05`

The completed matrix contains 1,800 development windows: 600 O4a background
windows, 120 O4a DANTE-ROBUST candidates, 360 O3b Gravity Spy known-glitch
controls, and 720 O4a software injections. The known-glitch and injection
constraints are evaluated separately by detector and morphology. The access
ledger records one opening of the frozen development identities and empty
confirmation and O4b access lists.

The exact teacher is the frozen O4a `native` DANTE score. It is a target for
surrogate fidelity, not an independent physical label. The primary student is
the depthwise CNN on whitened one-dimensional strain; the only comparator is
the complex-STFT two-dimensional CNN. Each architecture is represented by all
five frozen training replicates, and promotion requires the worst replicate to
pass every gate.

## Predeclared endpoints

For every replicate, H1 and L1 must independently satisfy a block-bootstrap
lower bound of at least 0.90 for Spearman agreement with the exact teacher.
Operating thresholds are then selected separately by detector. Every
known-glitch, injection, and DANTE-ROBUST stratum must satisfy its frozen point
retention, Wilson lower-bound, and sample-size constraints. The resulting
background-call reduction, including the deterministic audit stream, must be
at least 0.50. Finally, the 95% detector/GPS-block-bootstrap lower bound on
mean net saving must be positive.

The failure hierarchy is important. Protected retention is not the failed
scientific endpoint: every detector/morphology retention gate passes at the
selected thresholds for all ten candidates. The primary failure is that no
student reproduces the continuous teacher ordering with the required
detector-wise fidelity. A separate operational failure then remains because
the retention-compatible thresholds avoid only 1.83--10.83% of background
calls, rather than the required 50%. This differs from interpreting the result
as a morphology-specific retention failure.

The fidelity gate fails decisively for every replicate:

| Architecture | Development Spearman range | Bootstrap lower-bound range | Replicates passing fidelity |
|---|---:|---:|---:|
| Raw 1-D depthwise | 0.617--0.718 | 0.562--0.677 | 0/5 |
| Complex STFT 2-D | 0.326--0.594 | 0.262--0.545 | 0/5 |

The ranges contain both detectors across all five replicates. The raw 1-D
student is consistently closer to the teacher than the complex-STFT
comparator, but its strongest observed point correlation is still 0.718 and
its strongest bootstrap lower bound is 0.677, far below the frozen 0.90 gate.
The wide complex-STFT replicate range is descriptive evidence of unstable or
seed-sensitive out-of-sample fidelity under the frozen optimization contract;
it is not a license to retain only its favorable replicate.

## Retention and operational result

At each frozen selected threshold, every protected detector/morphology stratum
passes its development retention constraints in all ten candidates. Safe
retention is achieved only by routing most background windows through the
exact path:

| Architecture | Effective reduction across replicates | Mean prefilter cost | Mean net saving | Replicates reaching 50% reduction |
|---|---:|---:|---:|---:|
| Raw 1-D depthwise | 1.83--5.17% | 0.69--1.24 ms | 8.12--23.77 ms/window | 0/5 |
| Complex STFT 2-D | 2.50--10.83% | 1.88--2.01 ms | 10.24--49.58 ms/window | 0/5 |

The paired avoidable exact-path cost on the 600 background windows is 481.61
ms/window on average. Consequently, all ten operating points have a positive
block-bootstrap lower bound on net saving despite their low reduction. This
does not satisfy the protocol: positive but small expected savings and the
50% product requirement are separate gates, and the exact-teacher fidelity
gate has already failed.

## Scientific interpretation

Training-only SmoothL1 favored the raw 1-D student, and the independent
development result confirms that it generalizes better than the STFT
comparator in rank agreement. The best internal validation SmoothL1 values
span 0.106--0.143 for raw 1-D and 0.142--0.182 for complex STFT, in
per-detector standardized target units. These values are neither training-set
Spearman coefficients nor a frozen fidelity gate. Their non-zero magnitude
therefore does not by itself establish that the student fails to rank the
teacher even on the fit identities, or that the approximation has reached an
irreducible structural limit. SmoothL1 error and rank agreement are related
but not interchangeable.

What the independent development result does establish is inadequate
out-of-sample distillation under the frozen contract: the raw model preserves
only moderate ordering agreement with exact DANTE, and that agreement is
weaker in L1 for four of five replicates. The complex-STFT representation does
not repair this deficit and is more variable across replicates.

The result establishes that these frozen architectures, training population,
loss, and optimization contract do not yield a safe operational surrogate of
the exact path. It does not establish that compact one-dimensional students
are impossible, that the teacher score is a physical truth label, or that the
models independently detect any astrophysical morphology. Protected retention
at a low routing threshold is also not evidence of useful discrimination: a
filter can retain nearly everything by calling the exact path nearly
everywhere.

No causal diagnosis is proven by this screen. In particular, v5 does not
distinguish among insufficient student capacity, an objective mismatch between
SmoothL1 and rank fidelity, inadequate teacher-score support in the training
identities, or detector-dependent generalization. Distinguishing those
mechanisms requires training-only fit/validation rank diagnostics, a
predeclared capacity scaling study, and a rank-aware objective comparator
before any fresh development cohort is opened. Those are hypotheses and
requirements for a new outcome-blind design, not post-hoc changes to v5 or a
reason to declare distillation in general closed.

## Reproduction

From the repository root:

```text
python scripts/verify_dante_light_prefilter_v5_development.py \
  --cache-root E:/dante_cache/dante_light/prefilter_l4_v5_development
pytest tests/test_dante_light_prefilter_v5_*.py -q
pytest tests/ -q
```

On the producing checkout, exact recomputation returned
`PASS_VERIFIED_DEVELOPMENT`; the targeted v5 suite returned 69 passed, and the
full repository suite returned 499 passed and 1 skipped. The complete ledger
and raw development cache remain on the E: evidence volume; the compact,
digest-bound result and screening summary are versioned in the repository.

## Closed and open checkpoints

- Development v5 is closed as `V5_NOT_READY`.
- No candidate is eligible for confirmation; no unlock receipt may be issued.
- Confirmation remains sealed and O4b remains untouched.
- Routing remains disabled.
- V5 must not be retuned on these development outcomes.
- Any successor requires a separately reviewed, frozen protocol and fresh
  train/development identities before outcome access.

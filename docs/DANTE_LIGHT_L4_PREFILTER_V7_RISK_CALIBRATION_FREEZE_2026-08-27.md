# DANTE-Light L4 prefilter v7: risk-calibration execution freeze

Status: authorized and frozen before risk-calibration strain, exact-teacher
outcomes, or student outputs are accessed.

The user instruction `procedi` authorizes one evaluation of the already frozen
H1/L1 thresholds on `risk_calibration`. It does not authorize threshold
adjustment, fallback thresholds, member replacement, confirmation, O4b,
routing, or production promotion.

The stage contains 1,620 identities: per detector, 150 natural backgrounds,
60 catalog-sampled teacher positives, 60 DANTE-ROBUST candidates, 60 examples
of each of Blip, KoiFish and ScatteredLight, and 90 injections for each of
BBH 10+10, BBH 30+30, the legacy point-particle NSBH control and the aligned
tidal NSBH stress population. Protected gates remain separate by detector,
role and morphology; audit rescue never enters a safety gate.

The fixed search thresholds are H1 `0.9937049746513367` and L1 `1.0`.
Primary retention conditions on the subset of the frozen catalog that the
current exact teacher actually retains. Every primary or protected cell must
have point retention at least 0.90 and Wilson-95 lower bound at least 0.80.
The realized post-audit background-call reduction must be at least 0.50 in
each detector. Mean net saving is evaluated once with a combined
detector/GPS-4096-s block bootstrap (2,000 resamples, 95% percentile interval,
NumPy `linear` quantile) whose frozen seed is
`13317784664095674177`; its lower bound must be strictly positive.
Per-detector net-saving intervals are diagnostics, not additional gates.

The waveform cache was built outcome-blind in the pinned WSL LALSuite
environment before authorization. It contains all 720 risk-calibration
injections and has artifact digest
`1a7a8a0aa631f4ee78b6b83421fa64f616e348fb5811bbdd04547ccdde5f8e90`.
No strain, teacher label, student output, confirmation row or O4b row was used
to build it.

Before the first risk-calibration row is read, the complete teacher
fingerprint and all eight training-only canaries must pass again and produce a
stage-specific receipt. Any mismatch gives `STOP_NO_ACCESS_NO_RETUNE`.
Failure of any calibration gate gives `V7_NOT_READY_RISK_CALIBRATION` and
closes the experiment without confirmation. A calibration PASS only makes a
separate confirmation checkpoint scientifically discussable; it does not
open confirmation automatically and does not establish operational readiness.

Frozen authorization digest:
`0795eae5ee1c89b4a27f6b3a84de421f942ef72ef6bc5d307413746717d67433`.

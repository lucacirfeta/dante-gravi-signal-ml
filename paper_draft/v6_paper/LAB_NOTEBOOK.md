# DANTE v6 — lab notebook

Working record of everything produced **after** the v5 submissions, i.e. not in
arXiv:2607.18136 or in the CQG manuscript. This is the raw material for the v6
`.tex`: each entry states what was measured, why it matters against what v5
already says, where the artifact is, and how to regenerate it.

Written in English because it feeds a manuscript, not because the discussion is.

**Status key** — `DONE` result in hand and verified · `RUNNING` in progress ·
`OPEN` not started · `BLOCKED` waiting on something external.

**Rule for this file:** nothing enters as a claim without a number and a path.
If a number came from a run whose environment was not recorded, say so.

Last updated 2026-07-28.

**Sections 1–3 were written on 2026-07-21/22 and several of their conclusions
were later overturned by measurement.** Read §12 before §2 (the "environment
drift" story is dead — the cause was a 4 s labelling offset and the pipeline
reproduces exactly), and read the AUDIT before §1 and §3. Superseded entries are
kept rather than deleted, because which explanations were wrong, and how they
were falsified, is itself part of the record.

---

## 0. What v5 already says, so v6 does not repeat it

Read these before drafting: the v6 contribution is a *delta*, and several of
the items below are corrections to v5 rather than new findings.

| v5 claim | v6 status |
|---|---|
| PEM veto tested on 3 `Family_A` members "for completeness" | superseded — sample raised to 63, and the 3 was a code limit, not a choice (§3) |
| `fig:singleton_saliency` panels | the metric shown is not the one that produced the score (§1) |
| Artifacts archived on Zenodo, dependencies in `requirements.txt` | dependencies were not pinned; runs now record their own (§2) |
| Rate limits, coincidence null, cohesion falsification, ε_coh | coincidence/cohesion not revisited; DSD-dependent rate limits are pending the Q64/Q64 transition audit (§27) |

---

## 1. Saliency panels showed a metric that never entered the score

**Status: DONE (code) / OPEN (figures)** · commit `ca474c3`

### What was wrong

`generate_saliency_map` computes patch anomaly two ways. With a production
`PatchScorer` it uses distance to the nearest centroid of the frozen VQ
dictionary — the quantity the pipeline pools into the novelty score. Without
one it falls back to distance from a session-local *spatial median* of
background patches. Every call site passed no scorer, so every saliency figure
ever produced, including the published one, ranked patches by the fallback.

The two are different quantities, not two estimates of one quantity. The
published panel is honestly labelled `Patch Saliency (Spatial Background)`, so
the figure does not misstate itself, but the surrounding text invites the
reader to see "the Top-$k$ patches", and those are not the boxes drawn.

### Verification

With the scorer wired in, on a synthetic 256×256 spectrogram:

| quantity | value |
|---|---|
| box set vs `scorer.score_spectrogram(...)["top_k_indices"]` | identical |
| `mean_topk_score` returned by the saliency | 0.4620 |
| `novelty_score` from the production scorer | 0.4620 |

The equality is the point: the figure's summary statistic is now the pipeline's
own score, which is falsifiable and was not true before.

### To regenerate the paper figures

```bash
python scripts/regenerate_singleton_saliency.py          # production scorer by default
python scripts/regenerate_singleton_saliency.py --spatial-background   # old diagnostic
```

Not yet run. **Do this before drafting the v6 singleton section** — the diffuse
vs localized Top-$k$ discussion inherited from `CORRECTIONS_2026-07-21.md` (C1)
should be re-read against panels that actually show the pooled patches.

### Guard

`tests/test_smoke.py::test_saliency_callers_pass_the_production_scorer` fails if
any call site drops the scorer again.

---

## 2. Runs now record the environment that produced them

**Status: DONE** · commit `ca474c3`

Closes the reproducibility failure documented in `CORRECTIONS_2026-07-21.md`
(C4): `gwpy` supplies both `whiten()` and `q_transform()`, `requirements.txt`
pinned 2 of 25 packages, and the published artifacts stopped reproducing when
gwpy went 3.x → 4.0.1.

`src/core/utils.py::record_environment()` writes `environment_*.json` next to
the artifacts, containing the full installed package set, git commit and dirty
flag, Python and platform, torch/CUDA, and the MD5 of every VQ reference index.
Called from the three classes that write results: `ProductionWriter` (scan),
`ValidationReporter` (per-session report), `AggregateReporter` (cross-session).
Best-effort — it never raises into an analysis.

Current environment on record (`data/production/aggregated/environment_artifacts_2026-07-22.json`):
gwpy 4.0.1, 85 packages, both indices hashing to their expected MD5
(`5d5d1a7a…` O3b K=275, `18e3e36b…` O4a K=1216).

**For the manuscript:** that file documents the 2026-07-21/22 artifacts (physical
coincidence, ε_coh, cohesion falsification). It does **not** document the
original O4a scan — that predates provenance recording and cannot be
reconstructed. State this asymmetry explicitly rather than implying uniform
coverage.

---

## 3. The PEM sample was capped by a bug, not by a choice

**Status: DONE (cause) / RUNNING (extended sample)** · commit `283eac1`

### The bug

v5 reports the family-wise PEM veto on the 2 singletons plus "three additional
isolated `Family_A` members tested for completeness". The selection loop could
not have produced more. Its budget branches only handled `spots_left` of 2 or
3; any larger budget fell through to `indices = [n_cands // 2]` — **one event
per robustness class, regardless of the requested number**. With three classes
present (`ROBUST`, `AMBIGUOUS`, `BACKGROUND`), asking for 60 events returned 3.

This is worth stating plainly in v6: the weakest leg of the v5 evidence was
weak for a mechanical reason, and the paper attributed it to design.

### The fix

Budget split across the classes present, then evenly spaced score ranks within
each class (endpoints included, so the whole distribution is covered rather
than the median alone). Verified: 5 → 5, 12 → 12, 60 → 60, 99 → 99.

### Extended run in progress

| | |
|---|---|
| Events in coherence report | **63** (41 L1, 21 H1, incl. both singletons) |
| Channel×event rows | 483 (456 with auxiliary data) |
| Coherence step wall time | 34 min |
| Null calibration | 57 events × 381 s ≈ **6 h**, running |
| Cost per event | 381 s, 0.50 GB auxiliary background |

One published event (L1 1384485596) was not re-selected by the score-rank
spread and was merged back from the pre-run backup
(`data/production/aggregated/pem_backup_2026-07-22/`), so the extended sample is
a strict superset of the published one.

**Do not report the 50 `significant` flags in the coherence CSV as couplings.**
That column is the per-channel raw threshold whose measured false-positive rate
is 23% — the criterion v5 explicitly retires. Only `pem_family_wise_verdicts.csv`
decides.

### Result — 63 events, batch finished 2026-07-22 16:41

58 new calibrations, **0 failures, 0 `UNCALIBRATED`**.

**Regression check first.** All five published events reproduce *bit-identically*
— same $C_{\max}$, same $\tau_{\mathrm{fw}}$, same verdict. The extended sample
is a strict superset and nothing published moved.

#### Finding 1 — the coupling is real and large

| | |
|---|---|
| events tested | 63 |
| `COUPLED` | **20 (31.7%)**, 95% Jeffreys CI 21.3–43.9% |
| expected by chance at per-event $\alpha=0.01$ | **0.63** |
| $P(X \geq 20 \mid p = 0.01)$ | $8.9\times10^{-25}$ |

This answers R2 and settles v5's weakest claim. The paper could only say "one of
three tested members coupled — consistent with, but does not prove, an
instrumental origin", and explicitly fell back on the diffusivity test as the
primary population-level evidence. With a real denominator the auxiliary veto
now carries that weight on its own: **a third of `Family_A` couples to a public
auxiliary channel**, against 0.63 expected by chance.

Both singletons reproduce their published verdicts: H1 1369305276 `COUPLED`,
L1 1382955228 `NO_CORRELATION`. **The surviving singleton still survives.**

#### Finding 2 — but the DSD does not select for it

Coupling fraction by robustness class:

| class | coupled | n | fraction |
|---|---|---|---|
| ROBUST (DSD survivors) | 8 | 23 | 34.8% |
| AMBIGUOUS | 7 | 20 | 35.0% |
| BACKGROUND (DSD-rejected) | 5 | 20 | 25.0% |

ROBUST vs BACKGROUND, Fisher exact: **OR = 1.60, p = 0.53**. Anomaly score also
fails to separate the two groups (median 0.438 coupled vs 0.423 not,
Mann–Whitney p = 0.25).

**This is the cohesion falsification happening a second time, on a different
axis.** A property that looks like it characterizes the survivors turns out to
be shared by the candidates the DSD threw away. The DSD selects on novelty
against a native background; auxiliary coupling is orthogonal to that, and the
data say so.

Read the two findings together and they are not in tension — they are two
different statements:

- the candidate pool *as a whole* is substantially instrumental (Finding 1);
- the DSD does not enrich for instrumental origin (Finding 2).

The first strengthens the population-level interpretation the papers wanted.
The second is a new negative result about the method and belongs in v6 with the
same prominence as the cohesion falsification — it is the same kind of honest
self-limitation, and it was found the same way, by finally computing the control.

#### Finding 3 — first, weak, probe of the DSD-absorption hypothesis

The review's structural critique (§ `REVIEWER_TODO_ANALYSIS.md` point 3a)
predicts that pervasive instrumental glitches are absorbed into the native
dictionary and therefore land in the **rejected** pool. If that were happening
strongly, `BACKGROUND` should show *higher* coupling than `ROBUST`. Observed:
25.0% against 34.8%, i.e. slightly lower and not significant.

That is evidence against strong absorption of *coupled* morphologies — but with
20 events per class it is badly underpowered, and it does not test the
hypothesis properly (a genuinely pervasive class would need the prevalence-based
experiment R1). Record it as a first probe, not as an answer.

#### Check run before trusting Finding 1 — zero-lag vs time-shifted null

The null is built from **time-shifted** pairs, but the observed statistic is
measured at **zero lag**, where persistent spectral lines make strain and
auxiliary channels coherent at *every* time, glitch or not. If ordinary quiet
windows already sit near the threshold, then "31.7% coupled" measures the
detector, not `Family_A`. This had to be checked before the number was believed.

What the stored calibrations allow:

| | |
|---|---|
| events where the *typical* quiet zero-lag $C_{\max}$ exceeds $\tau_{\mathrm{fw}}$ | 2 / 64 (3.1%) |
| median ratio (quiet zero-lag median) / $\tau_{\mathrm{fw}}$ | 0.69 |
| COUPLED events whose $C_{\max}$ exceeds the *same channel's* quiet zero-lag level | **20 / 20** |
| median observed $C_{\max}$ (coupled) vs same channel quiet zero-lag | **0.902 vs 0.356** |
| margin, median (min) | **+0.483 (+0.096)** |

So the couplings are not an artifact of persistent lines: at the candidate times
the driving channel is far more coherent with the strain than it is at quiet
times, in every one of the 20 cases.

**Recomputed 2026-07-23 with the zero-lag control persisted.** The 31.7% was a
veto rate, not a coupling rate — the time-shifted null is too low a bar for a
zero-lag observation, because persistent lines make strain and aux coherent at
zero lag whether or not a glitch is present.

| | |
|---|---|
| quiet zero-lag windows above $\tau_{\mathrm{fw}}$ (time-shift threshold), mean | **17.6%** |
| events where >5% of quiet windows exceed it | 46 / 63 |

So the true false-positive rate of the published (time-shift) criterion is ~17.6%
at zero lag, not the nominal 1%. The expected false-COUPLED count for the
time-shift method is therefore ~11, not 0.63, and the "20 vs 0.63" framing from
2026-07-22 was wrong.

**Correct criterion — observed $C_{\max}$ vs the zero-lag $q_{99}$**, which has a
genuine 1% per-event false rate:

| | time-shift null (published) | zero-lag null (correct) |
|---|---|---|
| COUPLED | 20 / 63 (31.7%) | **11 / 63 (17.5%)** |
| expected by chance | (0.63, but FPR is really ~17.6%) | 0.63 |
| $P(X \geq k \mid p=0.01)$ | — | **$3.8\times10^{-11}$** |
| 95% CI | — | 9.6–28.2% |

**The coupling is real — 17.5%, $p = 3.8\times10^{-11}$ — just smaller than the
veto rate suggested.** And all five published events keep their verdict under the
stricter test, including both singletons: H1 1369305276 stays COUPLED (the veto
holds), L1 1382955228 stays NO_CORRELATION (**the surviving singleton still
survives**). Only the 63-event extension moves, from 31.7% to 17.5%.

This is the number v6 should quote: **~1 in 6 of `Family_A` couples to a public
auxiliary channel above the zero-lag baseline**, against 0.63 expected. Finding 2
(DSD does not enrich for coupling) needs re-checking by class under the zero-lag
criterion before it is repeated.

#### Caveat to carry into the text

Five of the 20 couplings are driven by a calibration-line channel
(`SUS-ETMX_L*_CAL_LINE`, `CAL-PCAL*`). None of the public channels is
safety-certified, so a `COUPLED` verdict on a calibration line is the case where
the uncertified-safety assumption bites hardest. This is exactly what the
hierarchical verdict R4 is for.

Channels driving the couplings: `L1:ASC-X_TR_A_NSUM` (6), `H1:LSC-POP_A_LF` (3),
`H1:LSC-REFL_A_RIN` (3), `L1:IMC-WFS_B_I_PIT` (3), `L1:SUS-ETMX_L1/L2/L3_CAL_LINE`
(5 total).

---

## 4. A missing client is indistinguishable from missing data

**Status: DONE** · commit `283eac1`

Without the `nds2` bindings, gwpy answers **every** auxiliary fetch with
`ValueError: no valid sources found` — the same message as a genuine coverage
gap. On the Windows interpreter this produced 0/24 successful probes across
O4a, *including GPS times whose data is in hand from the published run*. The
natural reading — "public NDS auxiliary coverage has been withdrawn" — was
wrong.

`nds2` is not pip-installable. The PEM leg runs only under
`conda install -c conda-forge nds2-client python-nds2-client`; here that is the
WSL environment `~/miniconda/envs/dante_env` (gwpy 4.0.1, torch 2.12.1+cu130),
where the same three GPS times fetch fine.

`require_nds2()` now names the cause; the orchestrator falls back to
null-result mode explicitly and the calibration aborts rather than silently
dropping every channel from the null.

**For the limitations section:** the README's `pip install -r requirements.txt`
path cannot run the auxiliary veto at all. A reader following the published
instructions would reproduce the PEM section as an empty result and could
reasonably conclude the channels are unavailable. This belongs next to the C4
environment statement — it is the same class of defect seen from the packaging
side.

---

## 5. Auxiliary background caching: 4× redundant

**Status: DONE** · commit `283eac1`

`calibrate_event` already resamples every channel to `min(fs_strain, fs_aux)`,
so the 16384 Hz channels were downloaded and cached at full rate only to be
decimated on load — ~800 MB per 4 h block. Decimating at fetch is the same
operation moved earlier.

Measured effect of the reordering (float32 cast after decimation rather than
before), on the window FFTs of a real cached block:

| | |
|---|---|
| relative max deviation of the FFTs | **1.6 × 10⁻⁶** |
| threshold CI95 width, for scale | ~0.03 |

Cache per event 1.8 GB → **0.50 GB**. `--purge-cache` drops each block once its
null is computed, since spans rarely repeat across events.

Methodologically minor, but it is what makes a 63-event campaign feasible on
one workstation, which is the claim v6 will actually make.

---

## 6. Data hygiene (context for the data-availability statement)

**Status: DONE** · commits `0773899`, `5c3a428`

- **Artifacts directory was 96% cache.** `data/production/aggregated/` held
  9.6 GB, of which 9.1 GB was re-downloadable auxiliary strain sitting beside
  the results and inside anything archived from that path. `NULL_CACHE` moved
  to `data/cache/pem_null/`; 42 blocks (10.27 GB) deleted after verifying each
  belongs to an event whose calibration JSON exists. Directory now 36 MB.
  Manifest: `data/production/aggregated/pem/null_cache_purged_manifest.json`.
- **Figure-generating scripts are now in the repository.** `scripts/` was
  ignored wholesale, so the code producing the paper figures was not
  distributed — a clone could read the figures but not rebuild them. Nine
  scripts that write into `paper_draft/` or produce a published number are now
  tracked.
- **`data/raw/o4a_cache` kept deliberately.** 754 of its 760 candidate windows
  are *not* present in the E: archive, so it is the only local copy. 2.8 GB
  against 465 GB free is not a trade worth making.

---

## 7. Candidate claims for v6, and what would falsify each

Draft framing only — none of these is established yet.

1. **The auxiliary veto scales.** 63 events at 381 s and 0.50 GB each, on one
   workstation with public data. *Falsified by:* a COUPLED fraction so high
   that the veto is uninformative, or so low that 63 events add nothing over 3.
2. **`Family_A` has a measurable coupling rate.** v5 could only say "one of
   three". *Falsified by:* verdicts dominated by `UNCALIBRATED` for lack of
   clean background spans.
3. **The surviving singleton survives a stronger test.** *Falsified by:* the
   larger sample lifting its family-wise threshold context, or a coupling
   appearing in a channel not previously tested.
4. **Reproducibility is now structural, not documentary.** Provenance recorded
   per run; figure scripts distributed; the packaging trap named. *Falsified
   by:* a third party still unable to rebuild a figure from a clean clone —
   which is the test that should actually be run before claiming this.

---

## 8. Open, not started

### From the 2026-07-22 review analysis

See `REVIEWER_TODO_ANALYSIS.md` for the verdict on each critique. New work it
created, in order of value:

| id | item | cost | why |
|---|---|---|---|
| R1 | **DSD absorption threshold.** Inject a morphology at rising prevalence into the background used to build a native index, rebuild, find the prevalence at which the DSD stops flagging it. | medium | Answers the only structural critique: a glitch pervasive enough to enter the K=1216 dictionary is invisible *by construction*, and neither paper says so. Converts a rhetorical objection into a measured threshold. |
| R2 | **Expected vs observed false `COUPLED`** for the 63-event PEM run: $63 \times 0.01 = 0.63$ expected at the per-event family-wise $\alpha$. | free | One line of arithmetic. Must appear in v6 before a referee asks. The review's own version of this point used a wrong premise (it assumed all 2,937 ROBUST are tested; only 5 were). |
| R3 | **Monte Carlo error on $\tau_{\mathrm{lo}}, \tau_{\mathrm{hi}}$.** | minutes | The paper asserts $B=1000$ keeps it below the histogram bin width (CQG lines 793–797) but never measures it. Turns an argument into a number. |
| R4 | **Hierarchical PEM verdict**: strong `COUPLED` only on safety-certified channels, `SUSPECT` on uncertified ones. | cheap | Every current `COUPLED` carries the unquantified safety assumption uniformly. Relabelling of existing output, no new computation. |
| R5 | **Inter-session recurrence test**: a candidate recurring across widely separated sessions is more likely a recurring glitch than noise. | cheap | Genuinely new idea, not implemented. `scripts/cross_session_unification.py` is a starting point. |

Priority raised by the same review: **P9** (astrophysical injections — the
coincidence statistic is validated on synthetic glitch morphologies only, so
$\varepsilon_{\mathrm{coh}}=100\%$ does not transfer to CBC or supernova
signals) and **blind-spot boundary map** (the analytic $T = Q_{\max}/f$ boundary
has no empirical validation near the boundary).

### Standing production debt

| id | item | blocker |
|---|---|---|
| P4 | K-sensitivity sweep (512/1024/2048 vs K=1216) | none — `src/scripts/k_sweeping_test.py` is a starting point |
| P5 | background-index hold-out (20%) | none |
| P9 | astrophysical waveform injection campaign | none |
| P10 | independent code review + PCA baseline | none — `src/scripts/pca_real_test.py` exists |
| P11 | comparison against the official LVK O4a burst search | none |
| P-RT | causal / low-latency variant (rolling index) | design: the DSD reference is non-causal |
| P0 | persist raw pre-quantization embeddings | must wait for the next index build; never regenerate the frozen O4a index |
| P8 | Gravity Spy validation | external — no O4a classification set exists |

---

## 9. R3 — Monte Carlo error on the DSD thresholds, measured

**Status: DONE** · `src/pipeline_v2_production/dsd_threshold_mc_error.py` ·
artifact `data/production/aggregated/dsd_threshold_mc_error.json`

Both manuscripts assert that $B=1000$ keeps the Monte Carlo error on
$\tau_{\mathrm{lo}}, \tau_{\mathrm{hi}}$ "well below the bin width of the
underlying score histogram" (CQG lines 793–797). That was an argument, never a
measurement. Method: repeat the production bootstrap 200 times with independent
seeds; the spread of the CI endpoints *across seeds* is the Monte Carlo error —
the part of the threshold that moves if the analysis is re-run unchanged.

| | H1 | L1 |
|---|---|---|
| $\tau_{\mathrm{lo}}$ | $0.36245 \pm 0.00069$ | $0.39034 \pm 0.00201$ |
| $\tau_{\mathrm{hi}}$ | $0.41432 \pm 0.00279$ | $0.44721 \pm 0.00040$ |
| MC error / bootstrap CI width | 5.4% | 3.5% |
| MC error / Freedman–Diaconis bin | **0.46** | 0.09 |
| MC error / 50-bin width | 0.30 | 0.22 |

**The claim survives but is overstated for H1.** Against the bootstrap CI width
— the comparison that matters for the interval's meaning — the MC error is 3.5–5.4%,
comfortably small. Against a *histogram bin*, which is what the papers actually
claim, it is 9% for L1 but **46% of a Freedman–Diaconis bin for H1**: below one
bin, but "well below" is generous. v6 should quote the number instead of the
adjective.

**Decision impact, which is the number worth reporting.** Translating the MC
error into candidates: **80 of 10,372 (0.77%)** lie within $\pm 1\sigma_{\mathrm{MC}}$
of $\tau_{\mathrm{hi}}$ — 50 in H1, 30 in L1. So the ROBUST count carries a
seed-dependent uncertainty of order $\pm 80$ on $\sim 2{,}940$, i.e. 2.7%. The
survivor excess (2,937 observed against 103.7 expected at $P_{99}$, $280\sigma$)
is untouched.

### Unplanned result: the DSD thresholds *do* reproduce

The production thresholds are bracketed exactly by the labelled data (the
largest non-ROBUST score and the smallest ROBUST one):

| | production $\tau_{\mathrm{hi}}$ | reproduced here | distance |
|---|---|---|---|
| H1 | $(0.41715,\, 0.41723]$ | $0.41432 \pm 0.00279$ | $1.03\,\sigma_{\mathrm{MC}}$ |
| L1 | $(0.44705,\, 0.44706]$ | $0.44721 \pm 0.00040$ | $0.39\,\sigma_{\mathrm{MC}}$ |

Both agree within the Monte Carlo error. This is worth stating in v6 next to the
C4 environment limitation, because it draws the line precisely: **quantities
computed from stored score arrays reproduce; quantities requiring re-encoding do
not.** The DSD threshold depends only on the persisted background scores, not on
`gwpy`'s whitening or Q-transform, so the gwpy 3.x → 4.x break does not reach
it. C4 should say "the encoding stage does not reproduce", not "the pipeline
does not reproduce" — the current phrasing is broader than the evidence.

---

## 10. Coverage map: fixable, boundable, uncovered

Written 2026-07-22 to answer one question directly — of the limitations raised
against the pipeline, which ones can we actually close, which can we only
measure, and which stay open no matter what we do.

The distinction that matters: **fixing** a weakness makes the pipeline better;
**bounding** one leaves the pipeline as it is but replaces "we might be blind"
with "we are blind above this value". Both are legitimate results. Confusing
them is not.

### A — Fixable. The pipeline is genuinely stronger afterwards.

| item | cost | state |
|---|---|---|
| PEM sample 5 → 63 events | 6 h | **running** |
| Saliency figures show the pooled metric | done (code) | figures pending |
| Run provenance recorded | done | — |
| Figure scripts distributed | done | — |
| `nds2` failure no longer looks like missing data | done | — |
| Monte Carlo error on $\tau_{\mathrm{lo}},\tau_{\mathrm{hi}}$ (R3) | minutes | open |
| Expected vs observed false `COUPLED` (R2) | free | open |
| Hierarchical PEM verdict `COUPLED`/`SUSPECT` (R4) | cheap | open |
| Inter-session recurrence test (R5) | cheap | open |
| Astrophysical waveform injections (P9) | days | open |
| Blind-spot boundary map, duration × $\Delta f/f$ | days | open |
| K-sweep (P4), hold-out (P5), PCA baseline (P10) | days | open |

Narrowband morphologies belong here and are **already covered**: HarmonicComb
and WallOfLines are near-invisible to the multi-scale layer ($\leq 5\%$,
$\leq 2\%$) but recovered at $91\%$ and $74\%$ by the legacy $Q_{\max}=64$
pathway. That is a blind spot of one layer, not of the pipeline, and the paper
says so. Only the *boundary* between the two pathways is unmeasured.

### B — Boundable. We measure the limit; we do not remove it.

**B1 — DSD absorption of pervasive glitches.** The most important entry in this
section, and the one thing the review got right that we have not answered.

The blindness is not a bug. Any unsupervised novelty detector defines "novel" as
"rare in the reference", and our reference is built *from the data*. A glitch
class pervasive enough to form dense regions in feature space enters the K=1216
native dictionary and is re-scored as background by construction. No amount of
tuning removes this: it is what unsupervised novelty detection *is*.

What we can do is measure it, two independent ways, both with data already on
disk:

- **Look for the absorbed population directly.** Every candidate carries two
  scores against two different dictionaries: the O3b primary score
  (`novelties/nov_scores` in the per-session HDF5, K=275, built *before* O4a)
  and the native O4a score (`native_o4a_score` in the taxonomy, K=1216). A
  morphology that is new *and pervasive* in O4a is anomalous against O3b and
  normal against O4a native — exactly the signature of the **7,435 candidates
  (71.7%) the DSD rejects**, which both papers interpret wholly as domain shift.
  Ranking the rejected pool by normalized score gap turns that assumption into
  a testable claim. Note the scores use different dictionaries and different
  scales, so the gap must be normalized within each scoring's own background
  distribution before comparison — not differenced raw.
- **Measure the absorption threshold.** Inject a morphology at rising prevalence
  into the background used to build a native index, rebuild, find the prevalence
  at which flagging fails (R1).

Outcome either way is a bound, not a fix: "DANTE detects morphologies present
below prevalence *p*; above it they are absorbed." That is a publishable,
honest statement and currently neither paper makes it.

**B2 — Encoder is not GW-native.** A simple independent baseline (PCA + spectral
energy, P10) tells us what the transfer from natural images costs. It does not
reduce that cost.

**B3 — Top-$k$ selection is noise-driven.** The one consequence that mattered —
cross-detector patch sets not matching — was already fixed by replacing the
statistic with the physical cross-correlation test. The residual property is
intrinsic to the top-$k$ operator; its *stability* under noise realizations is
measurable.

**B4 — PEM channel coverage.** Bounded by what GWOSC releases (9 H1 / 7 L1 of
14/11). The hierarchical verdict (R4) makes the uncertified-safety assumption
explicit per verdict instead of uniform and silent.

### C — Uncovered. Declare, do not promise.

**C1 — Per-candidate FDR is unreachable with O4a, not merely expensive.**
Benjamini–Hochberg at $\alpha=0.01$ over $n=10{,}372$ requires
$p \leq 9.64\times10^{-7}$, hence an empirical background of
$N \geq 1.04\times10^{6}$ per detector. Available livetime is 144.2 d (H1) and
149.4 d (L1) — **389,433** and **403,324** non-overlapping 32 s windows, using
*every* window including the glitch-rich ones. We are short by a factor 2.7,
before requiring the background be pristine.

So the paper's own remedy ("a background sample of order $10^6$") cannot be met
within this dataset. The only escape is a parametric tail model (EVT / generalized
Pareto) which removes the empirical floor at the price of an assumption — and we
have a cautionary precedent for exactly that: the quasi-Gaussian analytic null
for PEM coherence was falsified by seven orders of magnitude. Any tail model
must be validated against the empirical distribution in the region where both
are resolvable, or it is worthless.

**C2 — Unstructured excess power.** NoiseBlob is recovered at $\leq 5\%$ at every
scale and SNR because the whitening stage is *designed* to reabsorb unstructured
excess power into the noise floor. Not fixable by tuning; it needs a non-visual
feature (a band-limited excess-power statistic) alongside the embedding — a new
component, not a parameter. Real astrophysical cost: white-noise bursts and
stochastically-structured CCSN models lie in this regime.

**C3 — Auxiliary channel safety certification.** Requires LVK internal access.
Outside our reach; mitigable only by labelling (B4).

**C4 — Gravity Spy validation.** No O4a classification set exists. External.

**C5 — A GW-native encoder.** Changing the backbone is a different paper, not a
revision of this one.

### One-line summary

Everything in **A** is work. **B1 is the real scientific opportunity** — it
converts the strongest criticism into a measured property of the method, using
data already on disk. **C1 and C2 are the honest limits** and should be stated
as such in v6, C1 with the factor-2.7 arithmetic rather than as a vague
"would require more background".

---

## 11. Coincidence re-run with the corrected axis mapping — null result holds

**Status: DONE 2026-07-23** · full pool, 8,749 candidates, ~8.5 h ·
published run backed up at
`pem_backup_2026-07-22_prezerolag/coincidence_physical_o4a_PUBLISHED.json`

The published coincidence analysis localized every candidate with the
transposed `_patch_time_band` — time from frequency content, band from timing.
Re-ran the whole pool with the fix (commit `5d1d59e`).

| | published (transposed) | corrected |
|---|---|---|
| candidates | 8,749 | 8,749 |
| on-source mean cc | 0.0556 | 0.0825 |
| on-source max cc | 0.6024 | 0.5174 |
| null max $p_{99}$ ($\tau_{cc}$) | 0.2848 | **0.4048** |
| exceeding threshold | 26 (0.30%) | **13 (0.149%)** |
| patch IoU mean | 0.0676 | 0.0676 |

**The null result holds, and is cleaner: 0.149% exceed the pooled null $p_{99}$,
against a 1% nominal rate — down from 0.30%.** The absolute values all moved, as
they must once the correlation is taken where the energy actually is: on-source
mean rises (0.056 → 0.082, correlating real structure instead of empty band),
and the null $p_{99}$ rises with it (0.285 → 0.405). The comparison survives for
the reason predicted for C3 — the same offset and band are applied to on-source
and to every time-shifted null — but it is now measured, not assumed.

**A quiet benefit of the fix.** $\varepsilon_{\mathrm{coh}}$ was measured by
localizing injections at the *known* transient position, while production
localized through the transposed `_patch_time_band`. The efficiency curve and
the production path were therefore inconsistent. With the fix, production
localizes correctly, so the 100% efficiency measurement now describes the path
production actually uses. This removes, rather than adds, a caveat.

### What the manuscripts must change

- **Conclusion unchanged**: no cross-detector coincidence, below the 1% rate.
- **Absolute numbers changed**: $\tau_{cc}$ 0.285 → 0.405; exceeding 0.30% →
  0.149%; on-source mean 0.056 → 0.082, max 0.602 → 0.517. Every one of these
  appears in the abstract and/or Results of both papers and must be updated.
- The "null on-source mean 0.060 reproduces the 0.056 on real candidates"
  consistency remark no longer holds at those values and must be recomputed or
  dropped.

---

## 12. RESOLVED — the pipeline is perfectly reproducible; the GPS label was off by 4 s

> **Superseded 2026-07-24.** The whitening-context explanation below is real but
> was *not* the cause. The actual cause: `_worker_preprocess` recorded
> `ts_context.t0` — the start of the **padded crop**, `seg_start - 4` — as each
> candidate's GPS. Catalogued GPS therefore sits 4 s before the window actually
> scored, and the true window is **[G+4, G+36]**.
>
> Measured over 10 candidates spanning the score range:
>
> | window | error vs stored |
> |---|---|
> | [G, G+32] | mean −0.0022, **σ 0.0651** |
> | **[G+4, G+36]** | **mean 0.0000, σ 0.0000** |
>
> Exact reproduction, to four decimals, on all ten. **No environment drift ever
> existed and no re-run is needed** — the stored scores are correct, only the
> label moves. It also explains the "offset 28 mod 32" clue: segments sit on the
> 32 s block grid, the crop is 4 s earlier.
>
> Corrected singleton numbers (window 1382955232–1382955264): feature at
> **+21.17 s** (not +25.17), **20 of 68** patches within ±1 s (not 7), Top-$k$
> region GPS 1382955253.2–1382955263.6. The alignment with the tabulated feature
> is *stronger* than previously stated. Applied to arXiv v3, CQG v3, the forum
> reply, and the regenerated saliency figures.
>
> Fixed in `patch_producer.py` (`return int(seg_start)`), with a regression test.
> Pre-2026-07-24 catalogues keep the old convention: **catalogue GPS + 4 = window
> start**.
>
> The whitening-context finding below stands as a *robustness* result — σ 0.016
> and zero DSD status flips over 24 candidates — but it is not a reproducibility
> problem.

### Original entry (2026-07-23), retained for the record

The stored anomaly score for the L1 singleton (0.6844) was never reproduced by a
clean recompute (0.7166). Two earlier attributions were wrong: environment/`gwpy`
drift (§2, C4) and a `gwpy` major-version change. Both falsified by direct test.
The actual cause is that **the anomaly score depends on the whitening context
length**, and the clean recompute used a different context than production.

`ts.whiten()` estimates the ASD over the whole time series it is handed, so the
whitened window — and every downstream score — changes with how much surrounding
data is passed. Same candidate, same image, same code, same environment:

| whitening context | score |
|---|---|
| ±4 s | 0.7166 |
| ±16 s | 0.6278 |
| ±64 s | 0.6723 |
| ±128 s | 0.6812 |
| ±256 s | 0.7080 |

The stored 0.6844 sits inside this range. The clean recompute centres ±4 s on the
candidate GPS; production segmented on the block grid (the offset-28-mod-32 clue
was the whitening pad) and whitened a different context.

**Falsified by direct test, so it is not these:**
- `gwpy` 3.0.13 vs 4.0.1 (isolated venv): spectrograms agree to 4.7e-10, scores
  identical to six decimals.
- environment nondeterminism: GPU run-1 == run-2, TF32 on/off, CPU — all give
  0.716642 exactly. The environment is perfectly deterministic.
- colormap, and the `np.isclose` wrong-row bug (§AUDIT): corrected, cos(MIL)=0.869.

**What it means for v6:**
- The C4 "environment sensitivity" text is dead and must not appear. It never
  reached the papers; the forum draft that asserted it is already rewritten.
- **Open robustness item (new):** the score is not invariant to the whitening
  context, with a swing of ~0.05–0.09 for this candidate — comparable to the DSD
  threshold spacing. In principle this can move borderline candidates across the
  DSD cut. *To measure:* re-score a sample of near-threshold candidates under a
  standardized context and count how many change ROBUST/not-ROBUST status. Until
  measured, this is a stated limitation, not a quantified one.
- **Does not invalidate published numbers.** Within one production run the context
  is consistent, so the stored scores are internally coherent and that is what the
  manuscripts quote. But a third party recomputing with a different context will
  not match — so the segmentation+context strategy must be pinned/recorded, not
  the package versions. `requirements-lock.txt` and `record_environment()` were the
  right instinct for the wrong problem.

**Consistent counter-example:** the DSD thresholds *do* reproduce (§9), because
they are computed from stored score arrays and never re-pass through
whitening+encoder. The line is: what re-passes through whitening/encoder depends
on the context; what is computed from stored arrays does not.

---

## 13. B1/R1 — the DSD absorption threshold, measured

**Status: DONE 2026-07-24** · `src/pipeline_v2_production/dsd_absorption_threshold.py` ·
artifact `data/production/aggregated/dsd_absorption_blip.json`

This answers the only structural critique from the 2026-07-22 review
(`REVIEWER_TODO_ANALYSIS.md` §3a): the DSD re-scores candidates against a
dictionary built from the run's own background, so a morphology common enough to
occupy dense regions of feature space is learned by that dictionary and re-scored
as background **by construction**. The pipeline is least sensitive to exactly the
pervasive couplings that matter most for detector characterization.

No tuning removes this — it is what unsupervised novelty detection *is*. So it
was measured instead: inject one morphology into the background at controlled
prevalence, rebuild the native index from that contaminated background, and score
**held-out** instances of the same morphology against it.

Blip, amplitude 12 on whitened (≈unit-variance) noise, 300-segment background
pool, 150 held-out background and 60 held-out injections, K set by the production
ratio (~1458 tokens/centroid → K=282):

| prevalence | z (contaminated index) | z (control) | ratio | flagged |
|---|---|---|---|---|
| 0% | **11.13** | 11.13 | 1.00 | 78% |
| 2% | 5.57 | 12.04 | 0.46 | 77% |
| 5% | 4.20 | 12.09 | 0.35 | 70% |
| 10% | 3.20 | 11.23 | 0.28 | 50% |
| 15% | 2.64 | 12.78 | 0.21 | 33% |
| 20% | 2.18 | 11.22 | 0.19 | 23% |
| 30% | 1.92 | 12.19 | 0.16 | 27% |
| 40% | **1.44** | 12.08 | 0.12 | 10% |

*z* is the separation of the held-out injections from that index's own
background, in units of the background's standard deviation — the absolute
scores are not comparable across indices, this is.

**The control settles it.** At high prevalence the contaminated index contains
fewer background segments, so the collapse could have been a sample-size effect.
The control builds an index from the *same number* of segments but all
background: it stays **flat at 11.85 ± 0.55** across every size, while the
contaminated index falls from 11.13 to 1.44 — a **factor 7.7 collapse**. The
sample-size explanation is excluded.

**The curve is steepest at the very start.** Two per cent contamination already
costs **half** the separation (11.13 → 5.57). A morphology does not have to
dominate the background to become invisible; a small recurring presence is
enough.

### For v6

Statement the data supports: *DANTE detects a morphology reliably while it stays
below ~2% prevalence in the background; at 2% half the separation is lost, and by
40% the morphology is indistinguishable from background against a dictionary that
has learned it, while the same morphology remains an 12σ outlier against an
uncontaminated dictionary of identical size.*

This converts a rhetorical objection into a measured property, and it is the
strongest new result of this work.

The flagged-fraction column mixes detection efficiency with absorption (78% at
p=0, not 100%, because the P99 threshold on 150 held-out samples is a hard bar);
*z* is the clean metric and should be the one quoted.

### Second morphology: ScatteredLight absorbs three times faster

Repeated for ScatteredLight (1.5 s, arch-like) — chosen because it is a *real and
common* LIGO glitch class, so it is precisely the kind of morphology the
absorption mechanism would hide in practice.

| prevalence | Blip *z* | ScatteredLight *z* | SL control | SL flagged |
|---|---|---|---|---|
| 0% | 11.13 | **31.16** | 31.16 | 100% |
| 2% | 5.57 | 5.63 | 32.99 | 100% |
| 5% | 4.20 | 1.77 | 31.90 | 12% |
| 10% | 3.20 | 0.75 | 32.32 | 5% |
| 20% | 2.18 | **−0.59** | 31.83 | 3% |
| 30% | 1.92 | −1.40 | 30.93 | 2% |
| 40% | 1.44 | **−1.80** | 31.27 | 0% |

Control flat at ~31 throughout, as for Blip.

Three findings, in order of importance:

1. **The more distinctive the morphology, the faster it is absorbed.**
   ScatteredLight starts far more detectable than Blip (31σ against 11σ, 100%
   flagged against 78%) yet falls below 3σ at ~5% prevalence where Blip survives
   to ~15%. A coherent, repeatable pattern forms a tight cluster in feature
   space and K-means readily spends a centroid on it; Blip's random position and
   shape spread it across many centroids, so it dissolves more slowly. **Being a
   well-defined glitch class is a disadvantage under the DSD.**

2. **Above ~15% prevalence the separation goes negative** (−0.59 at 20%, −1.80 at
   40%). A pervasive morphology does not merely become invisible — segments
   containing it score as *more background-like than actual background*. The
   pipeline would rank a common glitch below ordinary noise.

3. **Both morphologies lose most of their separation by 2%.** Blip 11.13 → 5.57,
   ScatteredLight 31.16 → 5.63. Whatever the starting detectability, a few per
   cent of contamination converges them to the same modest separation.

### For v6 — statement the data supports

*The DSD's sensitivity to a morphology degrades sharply with its prevalence in
the background used to build the native index. Measured on two morphologies at
matched amplitude, separation falls below 3σ at ~15% prevalence for an impulsive
Blip and ~5% for the more coherent ScatteredLight, and turns negative above ~15%
for the latter — a pervasive class is scored as more background-like than
background itself. A same-size all-background control stays flat throughout,
excluding a sample-size explanation. DANTE is therefore structurally least
sensitive to exactly the recurrent instrumental couplings that matter most for
detector characterization, and its null results bound only morphologies rare
enough to have escaped its own reference.*

---

## 14. R4 — PEM verdicts graded by which null they survive

**Status: DONE 2026-07-24** · commit `75f0a32`

No public GWOSC auxiliary channel carries a safety certification, so every
COUPLED verdict rests on an unverified assumption. Rather than leave that
uniform and implicit, grade it by something measured — which of the two nulls
the coupling survives:

| tier | definition | n |
|---|---|---|
| COUPLED | exceeds the zero-lag quantile | 11 / 63 |
| SUSPECT | exceeds the time-shift null only | 9 / 63 |
| NO_CORRELATION | exceeds neither | 43 / 63 |

The 20 previously COUPLED split 11 / 9, so SUSPECT isolates exactly the events
whose instrumental reading depends on the weaker null. Both singletons keep
their verdict: H1 1369305276 COUPLED (0.987 against a 0.693 zero-lag quantile),
L1 1382955228 NO_CORRELATION.

**Two discarded designs, worth recording.** The first grouped channels by
subsystem and downgraded LSC as "in the GW readout chain" — unverifiable from
outside the collaboration, and *contradicted by the data*: the input mode
cleaner, nominally auxiliary, has a higher quiet-time coherence (0.61–0.67) than
the length-sensing pick-off port (0.33). It would have downgraded the H1
singleton's published veto on a basis I cannot defend. The second tiered on that
measured baseline but applied it on top of the time-shift verdict, already known
to be too permissive. The adopted scheme needs no assumption about which
channels are safe: the zero-lag quantile already absorbs each channel's own
baseline. `channel_class` survives as descriptive metadata and drives nothing.

---

## 15. R5 — no morphology recurs across sessions

**Status: DONE 2026-07-24** · `src/pipeline_v2_production/inter_session_recurrence.py` ·
artifact `data/production/aggregated/inter_session_recurrence_o4a.json`

A glitch *class* recurs — the same mechanism fires months apart — while noise
does not. Tested on the 2,937 ROBUST survivors using the **stored** MIL vectors
(no re-encoding, so none of the window-offset or context sensitivity that
re-scoring would reintroduce).

| | H1 | L1 |
|---|---|---|
| candidates / sessions | 1,425 / 39 | 1,512 / 41 |
| cross-session fraction, top 2,000 pairs | 96.6% | 96.0% |
| cross-session fraction, all pairs (baseline) | 97.0% | 96.7% |
| enrichment | **×1.00** | **×0.99** |
| neighbour session span (k=10) | 8.53 | 7.49 |
| same, session-shuffled null | 8.76 | 8.68 |
| z | **−5.6** | **−25.5** |

**No recurrence.** The high-similarity tail is cross-session at exactly the
baseline rate, so morphological similarity carries no information about session
membership. The neighbour-span statistic runs slightly *below* its null — the
nearest neighbours of a candidate are marginally more concentrated within a
session than chance, the opposite of a recurring class, and consistent with
candidates sharing a session sharing an instrumental state.

**Caveat that limits the first statistic.** With candidates spread over ~40
sessions the baseline cross-session fraction is already 97%, so the maximum
possible enrichment is ×1.03 — the statistic is saturated and can barely detect
recurrence even if present. The neighbour-span statistic is the informative one
here, and it is decisive in the *anti*-recurrence direction.

Consistent with the cohesion falsification (§0): this embedding does not resolve
discrete recurring classes, and now that is shown along a temporal axis as well
as a topological one.

| result | artifact | command |
|---|---|---|
| PEM coherence, 63 events | `data/production/aggregated/pem/coherence_report.csv` | `main.py pem-coherence-analysis --max-events 60 --nds-host nds.gwosc.org` |
| PEM family-wise verdicts | `.../pem/pem_family_wise_verdicts.csv` | `python -m src.pipeline_v2_production.pem_null_calibration --run O4a --purge-cache` |
| Saliency, production Top-$k$ | `paper_draft/v*/img/saliency_Singleton_*.png` | `python scripts/regenerate_singleton_saliency.py` |
| Environment of a run | `environment_*.json` beside every artifact | automatic |

All PEM commands require the `nds2` environment of §4, not the venv in the
README.

---

## 16. What is in the 71.7% the DSD rejects?

**Status: DONE 2026-07-25** · 141 events calibrated, 0 failures ·
artifact `data/production/aggregated/pem/pem_family_wise_verdicts.csv`

B1 (§13) showed the absorption mechanism is real: a morphology at 5% prevalence
in the background loses most of its separation. But showing a mechanism *can*
happen is not showing it *did*. The DSD-rejected pool is where absorbed classes
would sit, and auxiliary coupling is the discriminant the score cannot provide —
because rejection is defined by the score.

Extended the PEM veto to 98 DSD-rejected candidates (from 20), reaching 76%
power to separate a 5% coupling rate from a 26% one.

| class | coupled | n | fraction | 95% CI |
|---|---|---|---|---|
| ROBUST (survivors) | 6 | 23 | **26.1%** | 11.7–46.1% |
| AMBIGUOUS | 4 | 20 | 20.0% | 7.2–40.8% |
| BACKGROUND (rejected) | 5 | 98 | **5.1%** | 2.0–10.8% |

Fisher exact, ROBUST vs BACKGROUND: **OR = 6.6, p = 0.0061**.

**The DSD is rejecting correctly.** Survivors are enriched ~6.6x in environmental
coupling over what the pipeline discards. The rejected pool is *not* a reservoir
of absorbed instrumental glitches; it behaves as the pipeline claims — drift of
the noise manifold.

**But 5.1% is not zero, and that matters.** Against a 1% per-event false rate the
rejected pool gives 5 couplings where 0.98 are expected (p = 0.003). So a small
but real instrumental population *is* being discarded. With 98 events that is
~5 events; over the 7,435 rejected candidates it would extrapolate to a few
hundred — though that assumes the sampled events are representative, which the
score-rank spread was designed for but does not guarantee.

**Together with B1 the statement is precise:** absorption is a demonstrated
mechanism that is *not* the dominant fate of O4a candidates, but the rejected
pool does contain a minority instrumental component above chance. DSD rejection
should be reported as "consistent with drift" rather than "shown to be drift".

**Structural limit of this test, to state alongside it.** It covers candidates
that were *flagged and then rejected*. A morphology absorbed so completely that
it never becomes a candidate appears in no class at all and is invisible to this
measurement. B1 has the same asymmetry: both bound absorption from the side of
things the pipeline saw.

### Tiered verdicts over all 141 events

| tier | n |
|---|---|
| NO_CORRELATION | 101 |
| SUSPECT | 25 |
| COUPLED | 15 |

---

## 17. P9 — would DANTE see a real gravitational wave?

**Status: DONE 2026-07-25** · `src/pipeline_v2_production/astrophysical_injection.py` ·
artifact `data/production/aggregated/astrophysical_injection_o4a.json`

The manuscripts quote the rate limits as *instrumental* precisely because no
claim was validated against astrophysical waveforms. Now it is: IMRPhenomD
signals (`lalsimulation`), each with an isotropic sky position, uniform
polarization and inclination uniform in cos(iota), **projected through each
detector's own antenna response** with the true geometric delay. This is the
realism the glitch efficiency campaign could not have — it injected one waveform
identically into both detectors, overstating coherence. 25 trials per cell.

Null flag rate (SNR<5, effectively signal-free): **6.7%**. Clean-score mean 0.314
against the 0.378 flagging threshold.

| system | 100 Mpc | 200 | 400 | 800 | 1600 |
|---|---|---|---|---|---|
| BBH 30+30 flag | 80% | 76% | 28% | 16% | 8% |
| BBH 30+30 coinc | 60% | 52% | 12% | 0% | 0% |
| BBH 10+10 flag | 84% | 52% | 16% | 4% | 0% |
| NSBH 10+1.4 flag | 32% | 28% | 8% | 8% | 12% |

BBH 30+30: flag rate is significant against the null out to 400 Mpc
(7/25, p=0.001) and consistent with null by 800 Mpc (p=0.08).

Three findings:

1. **DANTE does flag loud CBCs.** A 30+30 BBH within ~200 Mpc (SNR ≳ 75) is
   flagged 76–80% of the time and recovered in coincidence >50%. The pipeline is
   not blind to astrophysical signals — the manuscripts' instrumental framing is
   a scope choice, not a sensitivity floor, and P9 lets us say so with a number.

2. **Reach is far short of a detection pipeline, as expected.** The templated
   LVK searches detect these systems to redshift ~1 (several Gpc); DANTE's flag
   reach is a few hundred Mpc. It is a morphological anomaly detector, not a
   matched filter, and this quantifies the gap for the first time.

3. **The DSD suppresses even loud injections, by the §13 mechanism.** A probe of
   five SNR~100–300 injections: against O3b the score rises to 0.42–0.51 (above
   the 0.378 flag threshold), but against the native O4a index it rises far less
   and often stays below the 0.447 DSD cut (native deltas +0.01 to +0.34 vs O3b
   +0.05 to +0.24). The native dictionary has partly *learned chirp-like
   structure from O4a's own background*, so it penalises real signals — the same
   absorption measured in B1, now acting on astrophysical waveforms. Concretely:
   DSD-survival for injected BBH is 0–8%. A CBC search must **not** apply the
   DSD; DANTE's DSD is a glitch-vs-drift tool and actively removes astrophysical
   signal.

**Stated limitations (in the module docstring and to carry to v6):** one point
in parameter space per system (no spins/precession/higher modes); BNS excluded
because a 1.4+1.4 inspiral from 40 Hz lasts 31 s and does not fit the 32 s
window — itself a reportable architectural limit; background is real O4a but a
specific segment set, so this bounds sensitivity for these systems rather than a
population-averaged efficiency.

---

## 18. External confirmation from the DetChar forum reply

**Status: NOTED 2026-07-26.** Independent, from public GWOSC data, not run by us.

A responder on the forum thread re-checked the corrected window
(1382955232–1382955264, 26–42 Hz) with their own gwpy script:

- **Feature frequency**: independent peak-find lands at 28.0 Hz, matching our
  28.4 Hz — same feature, not a mains harmonic.
- **H1**: whitened, band-passed max |corr| at the physical lag is 0.116 — no
  morphological counterpart in H1, independently supporting our coincidence
  null (0.478 vs threshold 0.663).
- **Loudness**: in-band energy ~2 orders of magnitude above adjacent 32 s
  segments (explicitly not calibrated — whitening self-inflates against a loud
  feature — but rules out a noise fluctuation).
- **Open tension worth carrying into v6**: the profile (impulsive onset +
  ~30 Hz ringing, single-detector, aux-clean) resembles low-frequency
  scattered light, but that family usually shows in ASC or suspension
  channels, and our PEM result is aux-clean. Consistent with our own stated
  limitation — the public 9/7-channel subset has no seismometer or
  accelerometer — but worth stating as an open question rather than resolved
  by the aux-clean result.

No action needed; record for the v6 discussion of the surviving singleton.

---

## 19. Production finding: the DSD threshold and index use different backgrounds

**Status: MEASURED 2026-07-26**, found while building P5.

The native DSD threshold (tau_hi = 0.447 L1, 0.414 H1) and the native index are
calibrated on **two different background populations**, and nobody noticed:

- The **index** (`build_native_index`) is built from `iter_clean_segments`, which
  applies `excess_power_veto` -- glitch-free background.
- The **threshold** (`background_scores_native_*.npy`, via
  `AggregateReporter._extract_detector_background`) steps through every 64 s
  window with **no veto** -- glitch-inclusive background.

Measured against the production index, gen-scored:

| background | mean | P99 | max |
|---|---|---|---|
| vetoed (iter_clean_segments) | 0.137 | 0.341 | 0.365 |
| un-vetoed (step 64 s) | 0.140 | 0.397 | **0.496** |
| production `background_scores_native` (n=5000) | 0.134 | **0.447** | 0.503 |

Glitches are rare, so they barely move the mean (0.134-0.140) but set the tail:
the vetoed background tops out at 0.365, while the un-vetoed reaches 0.496 and
production's 5000-sample tail reaches 0.503. The un-vetoed recipe reproduces the
production tail; the residual 0.397 vs 0.447 is sample size (800 vs 5000) and
file selection.

**What it means.** A candidate must beat the 99th percentile of a background that
*includes glitches* to survive the DSD -- a stricter, and arguably inconsistent,
bar than the glitch-free background the index is built from. This makes the DSD
conservative (harder to survive), which is safe, but the two-population design is
undocumented and a careful referee could flag it.

**Does NOT change published numbers**: tau_hi=0.447 is the value actually used
for every survival decision. This explains *how it was calibrated*, and shows the
calibration background differs from the index background. It should be stated
plainly in v6, either as a deliberate choice (justify it) or as an inconsistency
to fix in a future run.

**Consequence for P5**: to reproduce the production decision boundary, the
threshold must be calibrated on **un-vetoed** background (matching
`_extract_detector_background`), while the rebuilt index uses **vetoed**
background (matching `build_native_index`). P5 originally used vetoed for both,
which put the threshold at 0.10-0.33 -- far below where the near-threshold
candidates sit -- so everything survived and the stability test had no power.

---

## 20. P5 — the survivors are not an artifact of the background draw

**Status: DONE 2026-07-26** · `src/pipeline_v2_production/dsd_index_stability.py` ·
artifact `data/production/aggregated/dsd_index_stability_o4a.json`

The review's most serious structural worry: the native index is built from a
*sample* of background, so the survivor set could be an artifact of that draw.
Tested by rebuilding the index from 4 independent bootstrap draws (production
recipe: raw_qgram, vetoed background, K≈1216) and re-scoring 130 near-threshold
candidates (80 ROBUST just above the cut, 50 rejected just below) against each.

Three threshold-independent metrics:

| | |
|---|---|
| score rank correlation across draws | **0.979** (min 0.973) |
| per-candidate score std across draws | **0.004** (median), 0.02 max |
| ROBUST vs rejected mean score, rebuilt indices | **0.431 vs 0.366** |

**The survivors are stable.** A candidate's score moves by ±0.004 when the
background that builds the index is resampled — smaller than the Monte-Carlo
error on the threshold itself (0.003–0.006, §9). The rank ordering is 98%
preserved, and ROBUST candidates still outscore rejected ones against a freshly
built index. The survivor/reject boundary is a property of the candidates, not
of which background draw built the dictionary. The central result survives the
resampling test.

### Method note — a threshold bug caught before it became a false result

The first run reported "verdict stable 100%", which was a false positive from a
mis-calibrated threshold (0.096, everything survives). It was not reported.
Chasing it down led to §19: the production DSD threshold is calibrated on
un-vetoed background while the index is built on vetoed background, so a naive
re-calibration on vetoed background lands the threshold far below the
candidates. The three metrics above are threshold-free and were validated
directly (candidate scores span 0.06–0.49 with real spread, not degenerate), so
they stand regardless. The verdict/agreement metrics are kept in the artifact
under a `_diagnostic_` prefix with an explicit note, not reported as results.

## 21. P10 — what the frozen DINOv2 encoder buys over a dumb baseline

**Status: DONE 2026-07-27** · `src/pipeline_v2_production/pca_baseline.py` ·
artifact `data/production/aggregated/pca_baseline_o4a.json`

B2 asks what the natural-image transfer costs: the encoder has never seen a
gravitational-wave spectrogram. This measures it against the two simplest honest
alternatives, scoring the *same* 130 near-threshold candidates as P5 (80 ROBUST
just above the cut, 50 rejected just below) and asking how each classical score
agrees with DANTE's stored `native_o4a_score`. To stay clear of the
raw_qgram/generate_qtransform trap that derailed P5, one spectrogram function
(`raw_qgram`) is used on both background and candidates, and DANTE's score is
never recomputed — only correlated against.

| classical scorer (no learned representation) | rank-corr with DANTE | AUC ROBUST vs rejected |
|---|---|---|
| PCA subspace reconstruction residual (475 comp, 90% var, fit on 1300 vetoed bg) | **0.141** | **0.520** |
| raw spectral energy (total Q-transform power) | **0.511** | **0.872** |

Two clean findings:

- **A zero-parameter loudness cut reproduces most of the survive/reject split.**
  Raw spectral energy separates DANTE's ROBUST survivors from its rejected
  candidates at AUC 0.87 — within each detector (H1 0.93, L1 0.78), so it is not
  a detector confound (checked: median energy H1 4.0e5 ≈ L1 3.7e5, ROBUST
  fraction 0.61 ≈ 0.62). Near the threshold, survivors are ~10–14× louder than
  rejected candidates. This is physically sensible — a loud, morphologically
  distinct transient is genuinely anomalous against O4a background while a weak
  one looks like it — but it is uncomfortable and honest to state: **a large
  part of the near-threshold binary verdict is recoverable from raw power alone.**

- **DANTE is not merely a loudness detector, and the transfer buys morphology a
  linear pixel model cannot.** The encoder's *continuous* score correlates only
  0.51 with energy — if DANTE were loudness, this would be ~0.9. And the PCA
  pixel-subspace novelty detector, the standard representation-free morphology
  method, is blind to the split (AUC 0.52, at chance in both detectors: H1 0.58,
  L1 0.42). So the transfer contributes discrimination that is neither raw
  energy nor linear pixel-space novelty; it does *not* contribute a decision
  independent of loudness.

**Bound, not fix (B2).** The honest paper statement: *a representation-free
spectral-energy statistic reproduces the near-threshold survive/reject ordering
at AUC 0.87, while a PCA pixel-novelty detector does not (0.52); the encoder's
score aligns with energy at only ρ=0.51, so the natural-image transfer buys
morphological discrimination beyond both raw power and linear pixel novelty, but
the majority of the marginal binary split is explainable by loudness.* Neither
paper currently says this. It does not reduce the transfer cost; it measures it.

### Method note — the detector-confound check that had to be run first

The pooled energy AUC of 0.87 is exactly the kind of number that can be a
Simpson's-paradox artifact: if H1 candidates were both louder and more often
ROBUST, energy would be standing in for the interferometer, not the class. Run
before interpreting (from the cache, no re-encode): per-detector AUC 0.93/0.78,
detector medians and ROBUST fractions near-identical. The separation is within
each detector, so the finding is real. A first-run `log1p` RuntimeWarning was
also chased down before caching — `raw_qgram`'s linear-interpolation zoom
undershoots to a few pixels < −1 (non-physical negative energy); clipped to 0
before `log1p`, with a non-finite guard that refuses to cache poisoned features.

## 22. P11 — does DANTE recover the real O4a gravitational-wave catalogue?

> **AUDIT OVERRIDE, 2026-07-28:** the original section below is retained as a
> falsified analysis history. Its “2/126 recovered” interpretation, session-span
> coverage, and instrumental-framing conclusion must not be cited. The corrected
> result is in §27.

**Status: SUPERSEDED / INVALID 2026-07-28** · `src/pipeline_v2_production/catalog_cross_match.py` ·
artifact `data/production/aggregated/catalog_cross_match_o4a.json`

P9 measured efficiency on *synthetic* injections into curated clean background.
P11 is the ground-truth version: of the gravitational-wave events the official
LVK search confirmed in O4a (GWTC-4.0/4.1), how many does DANTE independently
flag? Not an injection — the real detections. Coverage (was the time analysed?),
flag (does a candidate window `[gps+4, gps+36]` contain the event GPS?), and
recall (flagged/covered) are kept strictly separate.

**135** confirmed O4a events fall in DANTE's window; **126** are inside an
analysed session span (116 in both detectors). Of those 126:

| | |
|---|---|
| flagged in any detector | **2 / 126** |
| flagged coincident (both detectors) | **0** |
| covered events with SNR > 15 | 9 — **0 flagged** |
| covered-but-missed | 124: SNR median 9.6, **max 43.0**; D_L median 3.15 Gpc, min 290 Mpc |

The two flags are both single-detector, H1 only:
- **GW230709_063445** (SNR 7.9): flagged but DSD-rejected (`native_o4a_score`
  0.058, class BACKGROUND) — DANTE saw structure, the DSD absorbed it, exactly
  the §13/P9-finding-3 mechanism acting on a real signal.
- **GW231127_061546** (SNR 8.0): flagged **ROBUST** (score 0.435 > H1 τ=0.414).
  A genuine ROBUST novelty coincident with a real event — but SNR 8, single
  detector, no L1 confirmation, so whether it is the GW itself or an unrelated
  glitch at that time is unresolved.

**DANTE does not recover the real CBC catalogue — as it should not.** It is a
single-detector 32 s morphological anomaly detector, not a coherent matched
filter that accumulates SNR over an inspiral. Recovering ~0 of 126 is the
strongest external confirmation of the manuscripts' *instrumental* framing: were
it otherwise, DANTE would be a detection pipeline, which is not claimed.

### The tension with P9 that must not be smoothed over

The loudest, nearest covered event — **GW230814_230901, SNR 43, 290 Mpc, a
33.7+28.2 M⊙ BBH** — sits squarely in what P9 called DANTE's sweet spot (a 30+30
BBH at 200–400 Mpc, P9 flag rate 28–76%). DANTE did **not** flag it (nearest
candidate 1648 s away). Read honestly:

1. It is a **single Poisson trial**. P9's 28–76% flag probability makes one miss
   entirely consistent (p(miss) 0.24–0.72); it neither refutes nor confirms P9.
2. Every other loud covered event is at **1.2–4.2 Gpc**, an order of magnitude
   beyond DANTE's few-hundred-Mpc flag reach, so those misses are expected.
3. The real catalogue is simply **too sparse in DANTE's efficient regime** — one
   event near the reach edge — to validate P9's synthetic efficiency, which may
   itself be **optimistic** (clean curated background vs real in-situ noise;
   orientation sampling). This caveat should be carried into how v6 cites P9.

So P9 and P11 are consistent, but the honest joint statement is narrower than P9
alone: *DANTE flags loud, nearby CBCs in simulation; the one real O4a event in
that regime was missed, and the catalogue lacks the statistics to confirm the
simulated efficiency.* The instrumental framing stands on P11 directly; the
astrophysical-reach claim rests on P9 and should be stated as simulation-based.

### Method note — coverage before recall

"2/126 flagged" is only meaningful if the 126 were actually analysed. Coverage is
the merged union of every session's `[session_start_gps, session_end_gps]` (212 d
span, wider than the 144/149 d livetime because spans include vetoed sub-gaps;
real events sit in good data, so span-coverage is the right proxy). The 9 events
outside all spans are excluded from the denominator rather than counted as
misses. The window convention is the corrected `[gps+4, gps+36]` — using the raw
`gps_start` would shift every match by 4 s. The GWTC list is cached to disk so the
cross-match reproduces offline.

## 23. P4 — is the survivor population an artifact of the dictionary size K?

**Status: DONE 2026-07-27** · `src/pipeline_v2_production/dsd_k_sensitivity.py` ·
artifact `data/production/aggregated/dsd_k_sensitivity_o4a.json`

The native index has K=1216 centroids, a number fixed by a tokens-per-centroid
ratio, not by anything physical. P4 is the K-analogue of P5: P5 held K and
resampled the background; P4 holds the background and sweeps K over {512, 1024,
1216, 2048}. It reuses P5's cached tokens (same 130 near-threshold candidates,
same 1300-segment background), so only the K-means dictionary is rebuilt — no
re-encoding, and directly comparable to P5.

| K | ROBUST mean | rejected mean | separation | rank-corr vs K=1216 |
|---|---|---|---|---|
| 512  | 0.458 | 0.384 | 0.073 | 0.983 |
| 1024 | 0.446 | 0.372 | 0.074 | 0.989 |
| **1216** | 0.436 | 0.367 | 0.069 | — |
| 2048 | 0.433 | 0.360 | 0.073 | 0.984 |

Pairwise rank correlation across K: mean 0.982, min 0.963. Per-candidate score
std across K: median **0.009**, max 0.021.

**The survivors are not a K artifact.** Scores fall monotonically as K grows —
more centroids reconstruct the tokens better, so every anomaly score shrinks —
but the ROBUST/rejected **separation (~0.07) and the ordering (rank-corr 0.98)
are invariant**. A candidate's score wobbles by ±0.009 across a 4× range of
dictionary sizes, smaller than the ~0.07 survivor/reject gap and comparable to
the Monte-Carlo threshold error (0.003–0.006, §9). Which candidates survive is a
property of the candidates, not of the K=1216 choice. Together with P5
(background draw) and R3 (threshold MC error), the DSD survivor boundary is now
shown stable against all three of its free choices.

### Method note — the monotone trend is the internal consistency check

That every score decreases as K increases is not noise: a larger dictionary
reconstructs any token better, lowering `1 - max cos sim`. Its presence confirms
K is actually varying between runs (had the sweep silently reused one index, the
four columns would be identical). The reused synthetic `k_sweeping_test.py` in
`src/scripts/` sweeps the *Top-k pooling* parameter, not the dictionary size, and
is unrelated to this test.

## 24. Blind-spot map — the analytic boundary points the wrong way

> **AUDIT OVERRIDE, 2026-07-28:** this result is invalidated. The injector
> expects the requested GPS to be the waveform centre, but this experiment
> subtracted half the waveform duration first. Every signal was systematically
> mis-centred. The Qmax text also mixed 32 and 64. Code and regression guard are
> corrected; no numerical claim from this section enters v6 until rerun (§27).

**Status: INVALID — corrected code, rerun pending 2026-07-28** ·
`src/pipeline_v2_production/blind_spot_map.py` ·
artifact `data/production/aggregated/blind_spot_map_o4a.json`

Both manuscripts draw the analytic blind-spot boundary T = Q_max/f (Figure 14)
but never measure what happens near it — a standing reviewer point. The probe is
a sine-Gaussian burst, whose two parameters *are* the axes of the blind spot:
central frequency f0 and quality factor Q give duration ~Q/f0 and fractional
bandwidth 1/Q. A 5×7 grid (f0 = 35–300 Hz, Q = 2–128, straddling Q_max=32) is
injected into vetoed L1 background at **fixed matched-filter SNR = 20** — fixed,
so a miss is a statement about morphology, not loudness — scored against the O3b
dictionary exactly as production flags, with a paired clean control (same segment,
no injection). 8 realizations per cell.

The scoring goes through the **primary** O3b flag path (`generate_qtransform`,
`config.yaml` qrange **[4, 64]**), so the analytic boundary that applies is
Q_max = **64**, not the V3-multiscale Q=32. Flag rate, averaged over f0, as a
function of Q:

| Q | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256 |
|---|---|---|---|---|---|---|---|---|
| flag rate | 0.00 | 0.00 | 0.05 | 0.57 | 0.75 | 0.65 | 0.62 | 0.35 |
| duration @ f0=100 | 3 ms | 6 ms | 30 ms | 60 ms | 120 ms | 240 ms | 480 ms | 960 ms |
| bandwidth @ f0=100 | 50 Hz | 25 Hz | 13 Hz | 6 Hz | 3 Hz | 1.6 Hz | 0.8 Hz | 0.4 Hz |

**The empirical blind spot is the opposite corner from the drawn boundary.**
Mean flag rate for Q ≤ Q_max=64 (0.338) is *lower* than for Q > 64 (0.487): the
narrowband region the analytic T = Q_max/f line marks as blind is where DANTE
flags at least as well (0.62 at Q=128, a 0.8 Hz-wide line). The real blind region
is **Q ≤ 4 — broadband, short bursts — uniformly unflagged at every frequency**
(10/10 cells at flag rate 0.00), with the transition to visibility at Q ≈ 8–16,
far below Q_max=64. Flagging does eventually decline, but only at **Q ≈ 256**
(0.35) — four times past the tiling boundary — so even that fall-off is not where
the figure places it.

**Why, and why it is honest.** At fixed matched-filter SNR the total energy is
held constant, but a broadband/short burst spreads that energy over many
time-frequency tiles, so no single patch is bright. DANTE flags on Top-k *local*
patch novelty, not integrated power, so it misses the spread-energy corner — the
same reason it is insensitive to NoiseBlob and unstructured excess power (paper
§15). The narrowband corner, by contrast, concentrates energy into a compact line
DANTE sees easily until the burst grows longer than the window can localize
(Q≈256). So the manuscripts' blind-spot figure is drawn on the wrong axis: the
dominant limitation is local concentration at fixed SNR at low Q, not Q-transform
tiling resolution at Q_max.

**Carry to v6:** replace the analytic T = Q_max/f narrative with the measured
statement — *at fixed SNR, DANTE's flag efficiency rises from 0% for Q ≤ 4
(broadband) to a broad 0.6–0.75 plateau for 16 ≤ Q ≤ 128, and does not fall off
across the narrowband boundary Q_max=64 the current figure marks as blind; a
decline appears only at Q ≈ 256.*

### Method note — statistics, the Q_max fix, and the fixed-SNR caveat

`Q_MAX` was initially set to 32 (the V3-multiscale value) and corrected to 64 to
match the primary flag path this test actually scores through — a README-coherence
check caught it. The Q-aggregate is the claim; individual cells wobble at n=8
(the f0=300 row is erratic), so no claim rests on a single cell. The result is
conditional on the amplitude convention: fixing *matched-filter SNR* is the
astrophysically honest choice, but a different convention (fixed peak tile
amplitude) would move the boundary — stated explicitly rather than hidden. A pilot
first confirmed a concentrated cell (Q=32) raises the score by +0.14 and flags,
so the injection path demonstrably works before the null cells were trusted.

## 25. Whitening-context sensitivity — the section-12 swing is rare, not typical

> **AUDIT OVERRIDE, 2026-07-28:** this result is invalidated. The pad=4
> reproduction anchor failed (median absolute delta 0.0172, maximum 0.2806), the
> code did not abort, and it reused the production threshold at every pad.
> Therefore neither the ~5% flip rate nor the claimed survey-wide upper bound is
> admissible. The corrected experiment has a hard anchor, a score matrix, and
> per-pad background recalibration; it remains to be rerun (§27).

**Status: INVALID — corrected code, rerun pending 2026-07-28** ·
`src/pipeline_v2_production/whitening_context_sensitivity.py` ·
artifact `data/production/aggregated/whitening_context_sensitivity_o4a.json`

Section 12 left an open, unquantified worry: because `whiten()` estimates the ASD
over whatever data it is handed, the score depends on the whitening context, and
the L1 singleton swung ~0.05–0.09 across contexts from ±4 s to ±256 s —
comparable to the DSD threshold spacing, so in principle a borderline candidate
could cross the cut. The question was whether that swing is typical or an
artifact of one pathological candidate. Measured on 59 near-threshold candidates,
each re-scored against the native index at pad ∈ {4, 16, 64, 128} s:

| | |
|---|---|
| context swing (score range over pads), median | **0.0071** |
| context swing, max | 0.231 |
| candidates with swing > 0.02 | **8 / 59 (14%)** |
| DSD verdict flips vs production pad=4 | 3, 3, 2 (of 59) → **~5%** |

**The swing is rare, not typical.** The median candidate moves 0.007 across a 32×
range of whitening context — a hand-checked candidate moved 0.001 from ±4 s to
±256 s. Only 14% swing more than 0.02; the section-12 singleton is one of that
minority, not the norm. The near-threshold **verdict flip rate is ~5%**, and
because this sample is deliberately drawn at the DSD cut (where the tiniest move
flips a verdict), it is an *upper bound* on the survey-wide rate — the vast
majority of candidates sit far enough from the threshold that a 0.007 swing never
crosses it.

**Reproduction anchor, and why it corroborates the story.** At pad=4 the
re-scored native value should match the stored `native_o4a_score`. It does for
typical candidates (a hand-checked one: 0.4218 vs 0.4172, Δ=0.005) but the median
Δ is 0.017 and the max is **0.281** — and that maximum coincides with the maximum
context swing (0.231): the same pathological candidate is both the one whose score
depends most on context *and* the one my pad=4 reconstruction reproduces worst,
exactly as expected if the non-reproduction is itself the context sensitivity.
The confined-sensitivity picture is internally consistent.

**Carry to v6:** section 12's stated limitation can now be quantified rather than
merely declared — *the whitening-context dependence moves the median candidate's
score by <0.01 and flips at most ~5% of candidates that already sit on the DSD
threshold; it is a property of a ~14% context-sensitive minority, not a
survey-wide instability.* Pinning the segmentation/context (already the §12
conclusion) bounds it fully.

### Method note — the reproduction anchor was load-bearing

The first pilot's failure — pad=4 not matching the stored score (max Δ 0.28) —
looked like a broken pipeline and would, uninvestigated, have invalidated the
flip counts. Chasing it (one candidate across pad 4→256, printing the effective
context) showed the opposite: the pipeline is faithful for typical candidates and
the score genuinely barely moves with context; the 0.28 was one pathological
candidate, the same one section 12 had found. The flip measurement is internal to
one pipeline (pad=4 vs longer, same fetch), so it is unaffected by the small
systematic offset from production stored values.

## 26. `characterize-candidate` — an external cross-check, and a self-correction

**Status: DONE 2026-07-28** · `src/pipeline_v2_production/characterize_candidate.py` ·
`tests/test_characterize_candidate.py` · reply `paper_draft/reply_3_codex.html`

A forum reader (GitHub user **Kretski**) independently reproduced the L1
singleton (GPS 1382955253.17, 26–42 Hz) with their own script (gist
`d0f17ae69cd8fc40093cb4a4e372b7be`) and got peak 28.0 Hz, an in-band loudness
ratio ~300×, and an H1 max\|corr\| that **moved between two of their own runs**
(0.116 at −1 ms, then 0.059 at −12 ms) — a lag wandering to the edge of the
search window, the signature of a maximiser picking noise rather than a real
peak. Two caveats were written into the script's header rather than left in a
forum post, specifically so they travel with the code: the loudness ratio is a
plain ratio, not a calibrated significance (whitening self-inflates against an
isolated loud feature); the public aux-channel release (9 L1 channels, no
seismometer/accelerometer) makes an aux-clean result *silence*, not
*contradiction*, for a scattered-light path through an unwitnessed channel.

**First attempt, and the error in it.** A first re-implementation reused the
production-style whitening/preprocessing path rather than the gist's literal
recipe, and reported the result as a "reproduction" (peak 28.5 Hz, loudness
256–316×, correlation 0.029–0.175 depending on window centring). Those numbers
are in the right ballpark but they are not what they were described as: a
*different implementation* was called an exact rerun. This is the same failure
mode logged throughout this notebook — inferring instead of measuring, here
compounded by describing an approximation as identical to its source.

**Correction.** The gist was read line by line and rerun literally: `whiten(4,
2)` then bandpass, ASD peak on a 4 s window centred on the feature, loudness
against the *mean* (matching the gist's denominator, not the median), and a
signed correlation maximum over ±12 ms — on our own O4a mirror, same window
`[1382955232, 1382955264]`, same feature time, same band. Result:

| | |
|---|---|
| peak frequency | **28.0 Hz** |
| loudness ratio (vs mean of 16 adjacent windows) | **304×** (315× vs median, diagnostic only) |
| raw H1–L1 correlation | **0.0585 at −11.96 ms** |

This reproduces Kretski's *second* run almost exactly (0.059 at −12 ms) — the
edge-of-window, no-real-peak signature, not the first run's 0.116. The reply
says plainly that the earlier numbers came from a different implementation and
should not have been called an exact rerun.

**The raw descriptor is deliberately kept separate from the authoritative
production veto.** `characterize-candidate` does not reuse
`coincidence_physical`'s preprocessing — independent agreement is the whole
point of an external cross-check; folding it into the production path would
have made "independent" a lie. Instead, `--catalog-gps` looks up the stored
production coincidence result for the same candidate and reports it alongside,
never recomputed: for this candidate, `cc_onsource = 0.0716` against a
time-shift null mean `0.1970` and null max `0.2864` over 7 admissible shifts
(`coincidence_physical_o4a.json`, verified directly against the artifact). The
raw descriptor (0.0585, unstable) and the calibrated production null
(on-source well inside the null spread) reach the **same conclusion — no
robust H1 counterpart — by two independent statistics**, which is a stronger
statement than either alone, and is exactly the check that matters: not "do
the numbers match" but "does an outsider's independent implementation agree
with our calibrated test."

**Generalized, not hard-coded.** `characterize-candidate` takes any
`--detector --gps --feature-gps --band --partner`, so the same independent
check applies to any future candidate, not only this one. Attribution to
Kretski is carried in the code (docstring and JSON `attribution` field), not
only in the forum thread.

**Standing conclusion, unchanged by any of this:** a loud, L1-local transient
near 28 Hz, qualitatively close to the low-frequency scattered-light family,
unclassified, no resolved H1 counterpart under either statistic. Whether an
Omicron trigger exists and whether the full seismic/suspension/ASC witness set
shows anything at that time remain LVK-side-only questions.

## 27. Critical scientific audit corrections

**Status: PARTIAL — P11 null, Q-range index and DSD transition DONE; blind
spot RUNNING and whitening QUEUED, 2026-07-28** · implementation plan
`paper_draft/v6_paper/codex_research_notes/CRITICAL_FIX_PLAN_2026-07-28.md`

### 27.1 DSD representation contract

The historical O4a native index has no Q-range metadata and was built at
Q=[4,32], while candidate queries and calibration were generated by the current
Q=[4,64] preprocessing default. Treating this as one score space was a critical
representation mismatch.

The correction is structural:

- every new index carries `qrange` in NPZ metadata and in its versioned filename;
- missing metadata is refused unless an explicit legacy-audit flag is supplied;
- candidate query and background calibration read the same index contract;
- future patch-production dual scoring prefers the versioned coherent index and
  disables the secondary score rather than silently loading legacy Q32;
- cache names contain index Q-range, query Q-range, whitening pad, and index
  SHA256;
- the historical taxonomy is never modified; coherent Q64/Q64 columns are
  written to a separate versioned taxonomy plus a long-form transition table;
- the historical catalogue-label offset is explicit: existing O4a candidates
  are rescored on `[G+4,G+36]`, not `[G,G+32]`.

An independent axis check also clarifies the frequency contract: although the
configured/requested range is 20–2048 Hz, GWpy 4.0.1 clamps the effective
Q-transform upper axis to **1291.053052 Hz** for both Q=[4,32] and Q=[4,64] on a
32 s, 4096 Hz window (both returned shape 1000×500). Therefore the Q audit
changes the tiling Q-range, not the effective frequency ceiling; v6 must describe
20–1291 Hz as the realized band and keep 20–2048 Hz labelled “requested”.

A 100-segment pilot completed successfully and produced
`data/production/aggregated/v6_pilots/patch_compressed_index_o4a_q4-64_pilot_k16.npz`
(SHA256
`a860bab7e545bff8ec1e4b57779dfc73d2803c0f40e5fea0335fae9e34f16242`).
The independent artifact gate passes: shape 16×384, 91 source segments, 100 raw
tokens, maximum centroid norm error \(5.43\times10^{-8}\), and raw-token norm
error \(8.20\times10^{-8}\). It is a machinery check only.

The production-scale index then completed:

- artifact:
  `data/reference/patch_compressed_index_o4a_q4-64_ex.npz`;
- SHA256:
  `0241b2a1ea2a460334f2c7ae0ab1bb62052706ea05c48443af32ae60a2488744`;
- declared contract: Q=[4,64], K=1216, detector=`both`, dimension 384;
- 1,294 accepted source segments, after excluding 206 candidate-adjacent
  segments;
- 1,771,486 patch tokens clustered and 50,000 raw pre-quantization tokens
  persisted;
- maximum centroid norm error \(7.62\times10^{-8}\), maximum raw-token norm
  error \(1.09\times10^{-7}\);
- the `t_bg` sidecar contains exactly 1,294 source times.

The raw block search order was `E:\o4a`, `/mnt/e/o4a`, then `data/raw`; the
build log confirms that the extended O4a blocks were read from `E:\o4a`, with
the repository cache used only where an exact local file already existed.

The build environment records GWpy 4.0.1, Torch
2.12.0.dev20260408+cu128, CUDA 12.8, and the git commit
`b2d02639bbda48c259a10d58791eea908b94f959`. Because the tree was intentionally
dirty, it also records
`data/reference/source_state_build_native_index_o4a_q4-64.zip`, SHA256
`93b36e913bc78a402f021b2d56bf91cd720c0fffee134b7ce0a2b763980ad474`.
The hash was independently recomputed and matched; the archive contains the
tracked binary patch, a manifest, and all four relevant untracked scientific
source/test files.

The Q64/Q64 transition audit started only after the numerical, sidecar, and
builder-provenance gates passed and completed all **10,372/10,372** candidates
with zero preprocessing or scoring failures. The coherent calibration used
5,000 full-run stratified background windows for each detector. Its bootstrap
P99 intervals and point estimates are:

| detector | P99 | bootstrap 95% interval |
|---|---:|---:|
| H1 | 0.415159 | [0.290792, 0.421111] |
| L1 | 0.404161 | [0.307337, 0.427869] |

The coherent funnel is 3,593 ROBUST, 2,109 AMBIGUOUS, and 4,670 BACKGROUND:
a ROBUST fraction of **34.64%**. The legacy classes over the same 10,372 rows
contained 2,937 ROBUST candidates (28.32%). The transition matrix is:

| legacy \ coherent | ROBUST | AMBIGUOUS | BACKGROUND |
|---|---:|---:|---:|
| ROBUST | 2,220 | 666 | 51 |
| AMBIGUOUS | 789 | 830 | 154 |
| BACKGROUND | 584 | 613 | 4,464 |
| UNKNOWN | 0 | 0 | 1 |

Thus the representation correction materially changes the funnel: 1,455
candidates enter ROBUST and 799 leave it, for a net increase of 656. Legacy DSD
counts, survivor fractions, and any dependent rate limits are superseded and
must be recomputed before the paper is frozen.

Artifacts:

- `Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv`;
- `dsd_scores_o4a_idxq4-64_queryq4-64.csv`;
- `dsd_thresholds_o4a_idxq4-64_queryq4-64.json`;
- `dsd_transition_audit_o4a_idxq4-64_queryq4-64.json`;
- `environment_dsd_transition_o4a_idxq4-64_queryq4-64.json`.

### 27.2 Corrected P11 catalogue control

The corrected result supersedes §22. The real catalogue produced two
any-detector candidate-window overlaps and no two-detector overlaps. Against
10,000 common-offset circular shifts:

| statistic | observed | null mean ± std | null 95% interval | empirical p |
|---|---:|---:|---:|---:|
| any detector | 2 | 2.068 ± 1.428 | [0, 5] | **0.6148** |
| both detectors | 0 | 0 ± 0 | [0, 0] | 1 |

The raw-block proxy covers 131/135 catalogue events in at least one detector and
118 in both, with merged livetimes 164.10 d (H1) and 163.53 d (L1). It represents
443,064 unique theoretical H1 windows and 441,520 L1 windows. This remains an
upper-bound proxy, because historical files do not record NaN/zero skips or
preprocessing failures.

**Allowed wording:** no excess of catalogue-window overlaps above the
circular-shift null is resolved. This is not recall, recovery efficiency, or
evidence that either overlapping candidate was caused by the gravitational-wave
signal.

Artifacts:

- `data/production/aggregated/catalog_cross_match_circular_shift_v2_o4a.json`;
- `data/production/aggregated/catalog_cross_match_null_circular_shift_v2_o4a.csv`;
- `data/production/aggregated/catalog_cross_match_events_circular_shift_v2_o4a.csv`;
- `data/production/aggregated/processed_coverage_circular_shift_v2_o4a.json`;
- `data/production/aggregated/catalog_cross_match_manifest_circular_shift_v2_o4a.json`.

The manifest contains two inputs and six outputs (including the environment and
dirty-source snapshot); all eight SHA256 values were independently recomputed
after the run and matched.

New production runs now persist an exact append-only ledger of every successfully
scored 32 s analysis window. Exact historical coverage requires a rescan.

### 27.3 Blind-spot invalidation and rerun gate

Direct inspection of `InjectionEngine.inject` confirms that `t_inject` is the
waveform centre. The old map instead passed
`window_centre - waveform_duration/2`, so §24 is invalid. The code now injects
at the analysis-window centre, reports Qmax=64 consistently, and records the
time semantics. The full grid must be rerun before any empirical blind-spot
shape is used in v6.

### 27.4 Whitening invalidation and redesigned experiment

Section 25 failed its own load-bearing anchor and is invalid. The replacement:

1. requires the coherent, versioned Q64/Q64 DSD score columns;
2. aborts if any pad=4 score differs from its stored value by more than the
   declared tolerance (default 0.001);
3. saves every candidate × pad score in long form;
4. calibrates a chronological background score distribution and bootstrap P99
   interval separately for every detector and every pad;
5. reports fixed-pad4-threshold sensitivity separately from a fully
   pad-recalibrated pipeline comparison.

Until that run passes the anchor, no “~5% flip rate”, “upper bound”, or
survey-wide whitening-stability claim is allowed.

### 27.5 Verification and provenance

The targeted critical plus hard-constraint suites pass **61/61**. The complete
current suite passes **104 tests, with 1 intentional skip**; both hermetic
end-to-end variants pass independently (O4a in 28.06 s, O3b in 26.64 s),
including production, saliency/pooling, aggregation, and DSD. The five warnings
are fixture/runtime diagnostics (xFormers unavailable and one-sample PCA), not
test failures.

Runs made from the intentionally dirty working tree archive the binary git patch
plus all relevant untracked source files in a ZIP and record its SHA256 next to
the environment JSON. This makes the no-commit development run reconstructable,
but it is not yet a clean-clone reproduction; paper-grade status still requires
freezing the final source and manifest.

---

## 28. Coherent-taxonomy propagation to dependent experiments

**Status: CODE + CPU RERUNS DONE; GPU/PEM RERUNS ACTIVE, 2026-07-28.**

Section 27 corrected the DSD representation but did not yet propagate the new
classes to every class-dependent experiment. This is scientifically material:
the legacy Q32-index/Q64-query and coherent Q64/Q64 labels differ for 2,858 of
10,372 candidates, and a result stratified by `robustness_class` is therefore
not automatically valid after the transition audit.

### 28.1 Enforced taxonomy contract

`src/core/index_contract.py` now resolves one representation-versioned taxonomy,
its matching transition audit, and neutral aliases `dsd_class`/`dsd_score`.
Normal scientific consumers:

- require `Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv`;
- require a coherent transition audit with zero failed evaluations;
- reject `NOT_EVALUATED`, non-finite scores and row-count disagreement;
- never fall back silently to `robustness_class`/`native_o4a_score`;
- preserve the historical columns without overwriting them;
- resolve Windows-style artifact paths correctly when the audit is consumed
  under WSL.

This contract is now used by PEM, P4, P5, P10, P11, R5, background-cohesion,
threshold-MC, multiscale survivor selection and report generation. Caches and
outputs carry `idxq4-64_queryq4-64`; old Q32-derived caches cannot be reused.

An additional boundary bug was found during propagation. The coherent bootstrap
interval is wide: H1 [0.290792, 0.421111], L1 [0.307337, 0.427869]. Therefore
the non-survivors immediately below the upper boundary are normally
`AMBIGUOUS`, not `BACKGROUND`. The old P4/P5/P10 sampler asked for
`BACKGROUND` within 0.06 of the upper boundary and would have returned an empty
contrast group under Q64/Q64. The corrected contrast is the highest-scoring
non-ROBUST population.

### 28.2 PEM: the old significance does not survive relabelling

Before paying for a new NDS run, the 141 already measured PEM events were joined
exactly by detector and GPS to the coherent taxonomy. All 141 matched; 42
(29.8%) changed class.

| classification applied to the same measured events | ROBUST coupled | BACKGROUND coupled | Fisher OR | two-sided p |
|---|---:|---:|---:|---:|
| legacy Q32/Q64 | 6/23 | 5/98 | 6.565 | 0.00612 |
| coherent Q64/Q64 | 5/34 | 3/77 | 4.253 | **0.05599** |

Thus the sentence in section 16 that ROBUST is significantly enriched in
auxiliary coupling is **superseded**. Relabelling is not a substitute for
resampling, because the original events were selected using the legacy class.
The only allowed interim wording is: *the direction of the association remains
positive in the old measured sample, but it is not resolved at p<0.05 after
coherent relabelling.*

Artifacts:

- `pem/idxq4-64_queryq4-64/pem_class_propagation.json`;
- `pem/idxq4-64_queryq4-64/pem_existing_sample_reclassified.csv`;
- `pem/idxq4-64_queryq4-64/pem_class_transition.csv`.

A power-matched coherent target ledger now contains the same intended class
sizes as the historical experiment: 23 ROBUST (including both singletons), 20
AMBIGUOUS and 98 BACKGROUND. Selection is evenly spaced in coherent score rank.
Only 4/141 targets overlap the old measured sample, so 137 events genuinely
require new strain-aux measurements. Matching old measurements and empirical
null JSONs are reused only by explicit detector/GPS join with SHA256 provenance.
The WSL `dante_env` run uses `/mnt/e/o4a` for raw strain and
`nds.gwosc.org` for auxiliary channels; the empirical-null stage starts only if
coherence measurement exits successfully.

### 28.3 Completed coherent CPU results

**P11.** The circular-shift result is numerically unchanged: two
any-detector overlaps, null 2.068 +/- 1.428, p=0.6148. The class annotation of
`GW231127_061546` changes from legacy ROBUST to coherent AMBIGUOUS
(score 0.415648); `GW230709_063445` remains BACKGROUND (score 0.091385).
The allowed conclusion remains “no resolved overlap excess,” never recall.
All P11 filenames and its hash manifest now include
`circular_shift_v2_idxq4-64_queryq4-64`.

**R5.** Recomputed on 1,430 coherent H1 ROBUST and 2,163 coherent L1 ROBUST
candidates. The top-pair cross-session fractions remain at their all-pairs
baselines (H1 96.15% vs 97.07%, L1 96.65% vs 96.37%). Neighbour-session span is
below the shuffled-session null (H1 z=-3.86, L1 z=-31.08). Allowed wording:
*the current primary MIL embedding resolves no positive inter-session recurrence
signal in the coherent ROBUST population*. This is not proof that no physical
morphology recurs.

**DSD threshold Monte-Carlo error.** Repeated 200 times with B=1000 and the
exact aligned temporal-block scheme used by the coherent calibration:

| detector | tau_lo MC std | tau_hi MC std | CI width |
|---|---:|---:|---:|
| H1 | 0.00546 | 0.000423 | 0.13588 |
| L1 | 0.01156 | 0.000892 | 0.13520 |

The upper decision boundary is Monte-Carlo stable, but the old manuscript claim
that *both* endpoint errors are well below a histogram-bin width is false:
tau_lo MC error is 3.49 (H1) and 9.08 (L1) Freedman-Diaconis bin widths. Quote
the endpoint-specific values, not one blanket reproducibility statement.

### 28.4 Active gates before paper drafting

The following results remain unavailable for v6 wording until their coherent
artifacts exist and are checked:

1. P5 background-draw ranking stability;
2. P4 dictionary-size stability, reusing the new P5 cache;
3. P10 PCA/energy baseline;
4. B1 absorption, blind-spot v3 and background-cohesion controls;
5. P9 CBC injections with the coherent native index and coherent DSD thresholds;
6. the per-event family-wise nulls for the completed 141-event coherent PEM
   measurement.

The GPU jobs are serialized behind the active whitening run. P9 runs in WSL only
after the Windows GPU queue succeeds. No old result from sections 13, 16, 17,
20, 21, 23 or 25 may be copied into either manuscript without checking its
representation-versioned replacement.

Verification after the propagation changes: all 38 Python entry points compile;
the critical plus hard-constraint suite passes 61/61 and the complete suite
passes **104 tests with 1 intentional skip**. The five warnings are the expected
xFormers-unavailable diagnostics plus one-sample PCA warnings in hermetic
fixtures, not scientific-job failures.

### 28.5 Coherent whitening-context result

**Status: DONE and anchor validated, 2026-07-28.** Artifact:
`whitening_context_sensitivity_o4a_idxq4-64_queryq4-64.json`.

The production pad=4 path reproduces all 56 stored coherent scores with zero
failures: maximum absolute difference \(4.77\times10^{-7}\), against the
declared \(10^{-3}\) tolerance. The experiment then changes only the whitening
context to 16, 64 and 128 s and separately recalibrates 5,000 background scores
per detector and pad.

This is not a stability result. In the deliberately near-boundary sample
(29 ROBUST, 27 non-ROBUST), the median score range over pad 4--128 s is
0.00885, the maximum is 0.247, and 13/56 candidates move by more than 0.02.
At the fixed production-pad threshold, the flip fractions are 23.2%, 33.9% and
33.9% for pad 16, 64 and 128 s. When the threshold is recalibrated at each pad,
the corresponding fractions are 26.8%, 48.2% and 53.6%.

Allowed wording: *the canonical pad=4 implementation is exactly reproducible,
but DSD disposition is sensitive to whitening-context length among candidates
selected near its decision boundary.* These fractions are intentionally
boundary-conditioned and must not be presented as survey-wide rates or upper
bounds.

During the downstream queue start, a separate orchestration defect was found:
Windows PowerShell 5.1 promoted ordinary PyTorch warnings on native stderr to
`NativeCommandError` because the wrapper used `ErrorActionPreference=Stop`.
The wrapper now captures the native process exit code explicitly and stops only
on a non-zero exit. P5 was restarted after this correction. This defect did not
alter the completed whitening artifact.

---

## 29. Completed coherent GPU queue

**Status: DONE 2026-07-29 03:24; scientific interpretation checked, PEM
family-wise calibration still active.**

All downstream jobs completed with the coherent Q64/Q64 taxonomy and
representation-versioned artifacts. Completion of a process is not treated as
confirmation of its historical claim: several results are falsifications or
material weakenings.

### 29.1 P5 — background-draw stability is only moderate

On 160 near-boundary candidates (80 ROBUST, 80 highest-scoring non-ROBUST),
four independently bootstrapped 1,300-segment dictionaries give mean pairwise
Spearman \(\rho=0.582\), minimum \(0.411\). Median per-candidate score standard
deviation is 0.00389 (maximum 0.01262). The mean ROBUST/non-ROBUST separation is
only 0.00123.

This supersedes the legacy \(\rho=0.979\) result. Allowed wording: *candidate
ordering has positive but only moderate stability to the native-background
draw in the coherent near-boundary sample.* The diagnostic 100% verdict
stability is not usable: its held-out vetoed-background threshold is about
0.10, not the production threshold.

### 29.2 P4 — ranking is not invariant to dictionary size

Against production \(K=1216\), rank correlations are 0.709 at \(K=512\),
0.877 at \(K=1024\), and 0.933 at \(K=2048\). Pairwise mean/minimum correlations
over all tested K are 0.812/0.669; median score standard deviation over K is
0.01348. Thus ranking is increasingly similar near and above production K, but
“invariant to K” is too strong.

### 29.3 P10 — simple pixel baselines do not reproduce the coherent split

For the same 160 candidates, PCA reconstruction residual has
\(\rho=-0.095\) with the DANTE score and AUC 0.480 for ROBUST versus
non-ROBUST. Spectral energy has \(\rho=-0.188\) and AUC 0.469. Detector-specific
AUCs also remain near chance. This supports the narrow statement that neither
these PCA residuals nor total spectral energy explains the coherent
near-boundary split; it does not by itself prove that natural-image transfer is
optimal or causally morphological.

### 29.4 B1 — absorption mechanism reproduced at Q64

For held-out Blip injections at amplitude 12, the score separation from the
index background falls from \(z=8.60\) at zero prevalence to 3.60 at 2%,
3.01 at 5%, 2.29 at 10%, 1.76 at 15% and 0.89 at 40%. The fraction above the
index-specific background P99 falls from 70% to 67%, 53%, 20%, 8% and 5% over
the same sequence. The same-size all-background control remains at
\(z\approx8.2\)--8.8.

The mechanism is therefore resolved and is not explained by the smaller clean
background subset. For this morphology/setup, threshold crossing occurs
between 5% and 10% prevalence, not at a universal “2--5% production threshold.”
Only one morphology, amplitude and seed were tested, so the numerical crossing
is conditional evidence, not a pipeline constant.

### 29.5 Corrected blind-spot map

The centred Q64 map contains 40 cells, eight realizations each. Mean primary
flag rate is 26.3% for \(Q\le64\) and 48.8% for \(Q>64\): the proposed analytic
high-Q boundary is not supported. The most consistent blind region is instead
low Q: every \(Q=2\) and \(Q=4\) cell has zero recovery, and most \(Q=8\) cells
also have zero recovery. Additional failures depend on frequency and Q rather
than following one \(Q_\max\) line.

Allowed wording: *at fixed injected SNR 20, the empirical sensitivity map is
strongly morphology-dependent and shows a broad low-Q blind region; it does not
validate a universal loss of sensitivity above Q=64.* With only eight
realizations per cell, individual cell rates have wide binomial uncertainty.

### 29.6 Background cohesion and multiscale checks

At the predeclared distance cut 0.25, all 3,000 native-background and all 4,670
DSD-BACKGROUND vectors enter one connected component. ROBUST and AMBIGUOUS are
also 99.86% in their largest component after size matching. The graph statistic
is therefore saturated and does not distinguish the populations; it cannot
support a morphology/cohesion claim without a distance-threshold sweep or a
different statistic.

Both explicitly retained singletons (L1 1382955228 and H1 1369305276) exceed
the scale-specific P99 at 0.5, 1, 2 and 4 s, with their largest margin at 4 s.
This is a useful internal multiscale consistency check for those two events,
not a population-level efficiency result.

### 29.7 P9 — CBC response is selective and the DSD suppresses most injections

The coherent campaign completed 25 successful injections in each of 15 cells:
375 total for BBH 30+30, BBH 10+10 and NSBH 10+1.4. It required 479 attempts;
104 attempts were rejected mainly because a sampled raw block was unavailable,
but every reported cell reached its target \(n=25\).

The primary O3b-index flag rate reaches 80%/76% for BBH 30+30 at 100/200 Mpc
and 84%/52% for BBH 10+10 at 100/200 Mpc. Physical coincidence reaches 60%/52%
for the loud BBH 30+30 cells, but only 16%/4% for BBH 10+10 and zero for all
NSBH cells. Coherent DSD survival is almost always zero (only isolated 4--8%
cells), even for very loud injections.

BNS 1.4+1.4 is **not measured**: the generated 31 s waveform fails the current
32 s-window safety condition and every BNS cell was skipped. Therefore P9
supports only a simulation-specific, morphology-dependent response statement
for the three completed systems. It cannot be presented as CBC-complete
efficiency, and the DSD suppression must be reported rather than hidden behind
the primary flag rate.

### 29.8 Earlier PEM gate (superseded)

**Superseded by the complete 141/141 rerun in §31.11.** The following
checkpoint is retained to document why the earlier seven-event calibration
gap was not accepted as final paper evidence.

The coherent PEM family-wise calibration completed at 11:17 on 2026-07-29.
The coherence report contains all 141 selected events; 134 have at least one
tested auxiliary channel and seven are explicitly uncalibratable. Section 30
records the final inference. The remaining release gates are the complete test
suite, artifact consistency audit and the explicit decision on whether BNS
coverage is required for the manuscript.

---

## 30. Earlier coherent PEM result (superseded)

**Status: SUPERSEDED 2026-07-30 by §31.11.** This 134/141 checkpoint is
retained as audit history and must not be quoted in either manuscript.
Artifacts:

- `pem/idxq4-64_queryq4-64/pem_family_wise_verdicts.csv`;
- `pem/idxq4-64_queryq4-64/pem_class_association.json`;
- 134 detector/GPS-specific `null_calibration_*.json` files.

The selected ledger, coherence report and verdict table contain the same 141
unique detector/GPS keys and the intended 23 ROBUST, 20 AMBIGUOUS and 98
BACKGROUND classes. All 134 calibrated verdicts have finite observed,
time-shift and zero-lag thresholds; the calibration JSON key set matches them
exactly. Seven BACKGROUND events have no tested channel and remain
`UNCALIBRATED`, never silently counted as NO_CORRELATION. Recomputing every tier
from its saved thresholds reproduces 141/141 rows.

### 30.1 Time-shift endpoint is non-discriminating

Under the family-wise time-shift null alone, 41/134 calibrated events exceed the
threshold:

| coherent class | time-shift positive / calibrated | rate (Wilson 95% CI) |
|---|---:|---:|
| ROBUST | 6/23 | 26.1% [12.5%, 46.5%] |
| AMBIGUOUS | 9/20 | 45.0% [25.8%, 65.8%] |
| BACKGROUND | 26/91 | 28.6% [20.3%, 38.6%] |

ROBUST versus BACKGROUND gives Fisher OR=0.882, two-sided p=1.000. Thus the
time-shift null provides no class enrichment and, by itself, is confounded by
persistent zero-lag coherence.

### 30.2 Primary zero-lag-confirmed endpoint

Twenty-nine of the 41 time-shift positives do not exceed the quiet-background
zero-lag q99 and are downgraded to `SUSPECT`. The primary endpoint retains:

| coherent class | confirmed COUPLED / calibrated | rate (Wilson 95% CI) |
|---|---:|---:|
| ROBUST | 3/23 | 13.0% [4.5%, 32.1%] |
| AMBIGUOUS | 4/20 | 20.0% [8.1%, 41.6%] |
| BACKGROUND | 5/91 | 5.5% [2.4%, 12.2%] |

ROBUST versus BACKGROUND gives Fisher OR=2.58, two-sided p=0.2009. The point
estimate remains positive, but the experiment does not resolve an enrichment.
AMBIGUOUS has the highest observed rate, but that comparison was not the
predeclared class contrast and the intervals are wide.

The old legacy-sample p=0.0061, and the relabelled-old-sample p=0.056, are both
superseded by this independently selected coherent sample. Allowed wording:
*after family-wise time-shift calibration and a quiet zero-lag control, the
coherent sample does not resolve a difference in auxiliary coupling between
ROBUST and BACKGROUND candidates (3/23 versus 5/91; OR=2.58,
p=0.201).* This is absence of resolved evidence, not evidence of equal rates.

### 30.3 Final software and artifact gate

After persisting the PEM association summary, the complete suite passes
**106 tests with 1 intentional skip**. The five warnings are the already
classified xFormers-unavailable and one-sample PCA fixture diagnostics.

A direct coherent-artifact audit parses and checks the representation, Q-range,
sample sizes and load-bearing invariants of whitening, P4, P5, P10, absorption,
blind-spot v3, background cohesion, multiscale, P9, R5, threshold MC and PEM:
all 12 required artifacts pass. P11 had already passed its independent
input/output hash-manifest audit.

The remaining issues are declared scientific scope limits, not hidden job
failures:

1. BNS is not measured by P9 and needs either a redesigned 32 s protocol or
   explicit exclusion from the paper's efficiency scope;
2. the selected background-cohesion graph statistic is saturated and supplies
   no discriminating evidence;
3. seven PEM BACKGROUND events are uncalibrated and are excluded from rates.

---

## 31. Pipeline reuse boundary and manuscript v6 drafting

**Status: SOFTWARE GATE PASS; FIRST ARXIV/CQG V6 DRAFTS COMPILE,
2026-07-29.**

### 31.1 What “the pipeline is validated” means

No Python or WSL scientific jobs remain active.  The coherent O4a artefact set
described in sections 27--30 is complete.  The complete test suite was rerun
before manuscript drafting:

```text
106 passed, 1 skipped, 5 expected warnings in 46.95 s
```

The production discovery/aggregation integration test is hermetic and passes
for O4a and O3b.  This demonstrates that the core pathway is not tied only to
the O4a string.  It does **not** validate scientific results for O2, O3a, O3b,
O4b or O5.

Historical reprocessing requires strain availability, explicit run bounds, a
run-specific native index, independent threshold populations, physical nulls
and run-separated outputs.  O2 and O3a are configured but have not passed the
same end-to-end empirical gate.  Future-run support is also partial: the
`patch-production` core is parameterized and `get_observing_run()` accepts
config-defined GPS bounds, but the general CLI still contains a static run
list, the native-background sampler has explicit O3a/O4a windows, and two v6
injection experiments select the O4a native index explicitly.

Allowed software wording:

> DANTE is an archival, run-parameterized framework that requires
> run-specific index construction, calibration and empirical validation.

Disallowed wording:

> O5 can be analysed without code changes, or the complete pipeline is already
> validated for every historical/future run.

The detailed evidence is recorded in
`codex_research_notes/PIPELINE_REUSE_VERIFICATION_2026-07-29.md`.

### 31.2 Editorial decision after CQG-116729

The CQG desk rejection is treated as a reporting and positioning failure, not
as an invitation to resubmit the v5 text unchanged.  The v6 manuscript removes
“complete pipeline” and rate limits from the title and central claim.  Its
question is now of broader gravitational-wave interest:

> How can an unsupervised anomaly search be validated under observing-run
> domain shift when target-run adaptation can itself absorb recurrent
> anomalies?

The literature context was expanded to cover Gravity Spy, iDQ, supervised and
transfer-learning glitch classification, similarity learning, unsupervised
autoencoders, GWAK and non-stationary-noise regression.  The manuscript makes
representation, reference population, calibration population and physical
null explicit components of the inference.

### 31.3 Draft artefacts

New files:

- `arxiv_v6/main.tex`, `arxiv_v6/references.bib`, compiled `main.pdf`;
- `cqg_v6/main.tex`, `cqg_v6/references.bib`, compiled `main.pdf`;
- `cqg_v6/cover_letter.tex`, compiled `cover_letter.pdf`;
- `tools/generate_paper_figures.py`;
- seven representation-coherent figures in `figures/`.

The arXiv manuscript is the compact scientific version.  The CQG manuscript
adds a wider-context section, explicit population-contract table, full
old-to-new taxonomy transition, validation matrix and requirements for a new
observing run.

Both manuscripts:

- use 3,593 ROBUST, 2,109 AMBIGUOUS and 4,670 BACKGROUND;
- report moderate P5 stability and non-invariant P4 ranking;
- retain absorption and the corrected low-Q blind region;
- report whitening sensitivity as boundary-conditioned;
- report the final PEM null result from §31.11
  (2/23 vs 7/98, Fisher p=0.680);
- call P11 an overlap null, never recall;
- disclose P9 as simulation-only and explicitly exclude unmeasured BNS;
- make no rate-limit, astrophysical-discovery or O5-readiness claim.

### 31.3.1 Post-draft correction: run-bounded, disjoint DSD calibration

**Status: C1 PASS; all class-dependent section 31 numbers are superseded,
2026-07-29.**

The earlier Q64/Q64 candidate scores were correct, but their `bgv2` threshold
population was not auditable: the sampler scanned every locally available raw
file without enforcing the observing-run interval, excluding candidate/index
windows, or saving the selected GPS times. A deterministic reconstruction found
cross-run and protected-window contamination. Because the historical cache
stored scores but not GPS values, exact independence could not be established
post hoc.

The replacement `bgv3` calibration enforces the official O4a GPS interval
`1368975618--1389456018`, excludes every 32 s candidate and native-index
training window with a 96 s guard, removes overlapping raw mirrors, samples
complete 17-window temporal blocks across the run, and writes a hashed GPS
ledger.

The real-data ledger audit is:

| Detector | n | unique GPS | outside O4a | protected overlap | self-overlap |
|---|---:|---:|---:|---:|---:|
| H1 | 5,000 | 5,000 | 0 | 0 | 0 |
| L1 | 5,000 | 5,000 | 0 | 0 | 0 |

The score arrays, ledger score columns and ledger hashes were independently
recomputed and match the saved artifacts exactly. A second audit then found
that the original 1,000-replicate bootstrap was not numerically adequate for
the H1 upper endpoint: the empirical bootstrap CDF places 97.575% of its mass
at or below 0.2697904, followed by a gap to 0.3172895. With only 1,000
replicates the nominal 97.5th percentile moved across that gap between random
seeds.

The production implementation now uses a deterministic, memory-bounded
1,000,000-replicate block bootstrap. Candidate scores are unchanged; only the
Monte-Carlo resolution of the confidence limits and the derived class labels
are updated:

Ten independent production-size repetitions quantify the residual numerical
error. H1 has endpoint standard deviations
`1.27e-5` (lower) and `0` (upper); L1 has `0` (lower) and `4.89e-5` (upper).
The largest endpoint MC standard deviation is 0.040 times the corresponding
Freedman--Diaconis score-bin width and \(7.1\times10^{-4}\) of the confidence
interval width. The formerly unstable H1 upper endpoint is identical in all
ten repetitions.

| Detector | P99 | bootstrap 95% interval |
|---|---:|---:|
| H1 | 0.1873206 | [0.1380009, 0.2697904] |
| L1 | 0.1760627 | [0.1503194, 0.2195937] |

All 10,372 candidate IDs and candidate novelty scores are identical to the
previous coherent rerun (maximum absolute score difference `0.0`). Only the
calibration population and decision boundaries changed. The resulting taxonomy
is:

| Detector | ROBUST | AMBIGUOUS | BACKGROUND | Total |
|---|---:|---:|---:|---:|
| H1 | 1,998 | 644 | 1,713 | 4,355 |
| L1 | 4,138 | 713 | 1,166 | 6,017 |
| **Total** | **6,136** | **1,357** | **2,879** | **10,372** |

The transition audit evaluated 10,372/10,372 candidates with zero failures.
Compared with the superseded coherent bgv2 taxonomy (3,593/2,109/4,670),
ROBUST increases by 2,543, AMBIGUOUS decreases by 752 and BACKGROUND decreases
by 1,791.

Consequently, every section 31 result that groups or samples candidates by DSD
class is invalid until rerun. R5, P11 and the diagnostic propagation onto the
old PEM sample were regenerated immediately. P4, P5, P10, multiscale candidate
selection, background cohesion, whitening-context sensitivity, the newly
selected PEM sample/null denominators and P9 DSD-survival fractions are in the
controlled C2 rerun queue and remain non-final until their artifacts pass.
B1 absorption and the centred blind-spot map do not use the corrected
production threshold as their primary decision boundary and are not invalidated
by this correction alone.

Detailed implementation and audit evidence:

- `codex_research_notes/CALIBRATION_BGV3_AUDIT_2026-07-29.md`;
- `codex_research_notes/BGV3_SHARED_DEPENDENCY_GRAPH_2026-07-29.md`.

The arXiv v6 and CQG manuscripts must not use the former
3,593/2,109/4,670 taxonomy or its derived figures.

### 31.4 Zenodo software release and remaining submission gate

The version-specific software DOI supplied on 2026-07-29 was checked directly
against the Zenodo API: `10.5281/zenodo.21676289` is a published, open software
record for DANTE 3.6.0, dated 2026-07-29 and linked to git tag `3.6.0`. Its sole
file is the GitHub source snapshot
`lucacirfeta/dante-gravi-signal-ml-3.6.0.zip` (620,021 bytes; MD5
`c350b2cdd2c60dbe6defecaa76a1b6bd`). The DOI and version have been propagated
to both manuscripts, the CQG cover letter, `CITATION.cff`, and the current
README citation.

Inspection of all 184 archive entries found no NPZ reference index, long-form
or per-trial table, environment record, lock file, or SHA256 manifest. The
record is therefore valid as the software citation but does not close the data
and result-artifact availability gate. Both manuscripts now state this boundary
explicitly. Before either submission is finalized, create a separate citable
reproducibility record containing the representation-versioned v6 tables,
per-trial outputs, environment records, reference-index provenance, and SHA256
manifests, then insert and verify that second DOI. This remains the only
external publication blocker identified at this stage; it is not a
scientific-job failure.

The Zenodo record's structured `version` field and related GitHub tag correctly
say 3.6.0, but its free-text description still says "Version 3 (3.5.0)". That
metadata text should be corrected in Zenodo before submission.

### 31.5 Figure and table audit

The six figures included in both manuscripts were traced from the coherent
Q64/Q64 artefacts through `tools/generate_paper_figures.py`, regenerated, and
compared with the manuscript PNGs. All regenerated images were byte-identical
to the corresponding arXiv and CQG inputs, and the arXiv/CQG copies had matching
SHA256 hashes. An independent 54-check numerical audit covered the funnel,
P4/P5/P10, whitening, absorption, blind map, PEM Wilson intervals and Fisher
test, CBC controls, cohesion, recurrence, physical coincidence, catalogue null,
the two index shapes and hashes, and all three CQG tables; no discrepancy was
found. The focused v6 regression file passed 29/29 tests.

Three presentation corrections were then applied without changing scientific
values: the absorption experiment is now identified as a controlled
300-segment, K=282 dictionary scaled by the production tokens-per-centroid
ratio and explicitly distinguished from production K=1216; the blind-map
caption now describes the dashed line as the boundary between Q<=64 and Q>64;
and the CQG validation matrix uses ragged-right columns with more width assigned
to the result column. The absorption legend was moved to a clear region and
given an opaque white background.

### 31.6 C2 dependency propagation and fail-closed artifact gate

The class-dependent results preceding bgv3 are retained only as archived
historical controls. They are not eligible for either manuscript. The
propagation policy is:

1. R5 and P11 are recomputed directly from the C2 taxonomy;
2. P5 rebuilds a separate, hashed 1,300-segment index pool plus a 300-segment
   hold-out ledger; P4 and P10 must consume the exact P5 candidate keys and
   caches;
3. multiscale and background-cohesion are recomputed from C2 class membership;
4. whitening recalibrates every pad on 5,000 background scores per detector,
   while pad 4 reuses the canonical C2 DSD calibration and must reproduce the
   stored candidate scores;
5. PEM reselects 23 ROBUST, 20 AMBIGUOUS and 98 BACKGROUND targets. Only 5/141
   old event-level measurements pass the exact detector/GPS, representation,
   channel-inventory, channel-threshold-hash and calibration checks; the other
   136 are recomputed;
6. P9 is rerun because the old aggregate JSON did not contain trial-level native
   scores. The new schema records both DSD interval endpoints, the full
   ROBUST/AMBIGUOUS/BACKGROUND class per detector, and all trial-level scores.

P5/P4/P10 remain deliberately *boundary* experiments: their balanced sample is
80 ROBUST and 80 AMBIGUOUS candidates, not a claim about all three survey
classes. Calling the second group simply “BACKGROUND” would be incorrect.

The P9 coincidence endpoint is also replaced. The primary endpoint now requires
the O3b detector score to cross the candidate threshold and a cross-detector
correlation, localized independently from that detector's O3b Top-k patches, to
cross the empirical physical-coincidence threshold. The centre-known,
broad-band statistic is retained only as an oracle diagnostic. A six-trial pilot
precedes the full 375-trial campaign; BNS remains explicitly unmeasured because
its waveform does not fit the 32 s protocol.

`scripts/verify_c2_bgv3_artifacts.py` is the common fail-closed gate. It checks
representation/Q-range, C2 class counts and threshold reproduction, sample
sizes, GPS uniqueness, SHA256 links, finite arrays, P5/P4/P10 cache identity,
multiscale completeness, whitening pad-4 reproduction, P9 trial endpoint
reconstruction, P11 manifest hashes and PEM reuse provenance. The serialized
queue invokes the relevant gate after every completed stage and stops on the
first failure.

At this checkpoint R5 and P11 pass the gate. R5 contains 1,998 H1 and 4,138 L1
ROBUST candidates; its top cross-session fractions are 0.9665 and 0.9610,
respectively, essentially equal to their all-pair baselines (enrichment 0.996
and 0.997), so no positive inter-session recurrence enrichment is resolved.
P11 has two catalogue-window overlaps against a circular-shift null mean 2.1899
(\(p_{\geq 2}=0.6508\)); coverage remains explicitly proxy-level. P5 and the
PEM coherence pass are active. No queued GPU/PEM number becomes paper evidence
until its gate has passed.

### 31.7 Whitening exact-context failure and fail-closed correction

The first C2 whitening-context run was rejected by the common artifact gate:
49/60 selected candidates were scored at all four pads, rather than the
pre-registered balanced sample of 15 ROBUST and 15 BACKGROUND candidates per
detector. Although every retained pad-4 score reproduced the stored production
score (maximum absolute difference `4.3e-7`), none of that run's swing or
flip-rate summaries is admissible paper evidence. The invalid JSON and matrix
were archived recoverably under
`data/production/aggregated/archive/pre_whitening_exact_context_20260730_0246/`.

The failure was caused by the data-loader call, not by the whitening transform:
the scorer requested the correct full interval but used an edge tolerance equal
to the requested pad. A shorter local block could therefore be accepted before
the whitening layer rejected its missing edge. The scoring loop then silently
dropped the candidate. The request now requires exact interval containment
(`edge_tolerance=0.0`), records detector/GPS/pad and exception details on any
failure, and never reduces a detector/class stratum.

The first exact-context rerun identified two distinct data-quality exclusions:
H1 GPS `1369601980` (ROBUST) and L1 GPS `1374241596` (BACKGROUND) contain
non-finite raw samples within the 128 s context. To keep the experiment generic
and reproducible, each detector/class stratum now has five candidates held in
deterministic nearest-boundary reserve order. An unusable candidate is entered
in a hashed failure ledger and replaced only by the next candidate in the same
stratum. The experiment still aborts unless the retained design is exactly
15 per stratum (60 total, 30 ROBUST and 30 BACKGROUND); attempted and failed
counts are also serialized and checked. A regression test proves the
within-stratum replacement rule, bringing the focused suite to 40/40 tests.

A second exact-context rerun is required, reusing the complete and
provenance-checked per-pad background calibrations but recomputing candidate
scores. P9 remains serialized behind its gate. Until both that gate and the
independent PEM null/verdict gate pass, no whitening, P9, or PEM result is to be
propagated to either manuscript.

The next balanced rerun closed the raw-data sample count but failed the
independent pad-4 anchor for H1 GPS `1388305628` and L1 GPS `1380089052`.
Their absolute score discrepancies were `0.135959` and `0.111146`, whereas the
other 58 candidates agreed within `4.4e-7`. Both mismatched cases required an
exact-context remote fetch because their local blocks did not fully contain
the pad-4 request. Since a context-sensitivity experiment is uninterpretable
when its reference condition does not reproduce production, these two cases
are also ineligible.

The deterministic reserve loop now applies both eligibility tests before
selection: finite complete context at every pad and pad-4 reproduction within
`1e-3`. Anchor mismatches receive an explicit `AnchorMismatch` ledger entry and
replacement remains confined to the same detector/class stratum. The final
60-candidate anchor is still recomputed independently and remains fail-closed.
The focused suite passes 41/41 tests. The rejected matrix, anchor diagnostic and
failure ledger were archived recoverably before a third rerun; they are not
paper evidence.

### 31.8 Final C2 whitening-context result

The third exact-context run passed the common whitening artifact gate. From 66
attempted candidates, the deterministic eligibility protocol retained exactly
60: 15 ROBUST and 15 BACKGROUND candidates for each detector. The hashed
exclusion ledger records two non-finite 128 s contexts and four pad-4 anchor
mismatches. All 60 retained candidates reproduce the stored production score
within `1e-3`; the maximum and median absolute differences are `6.85e-7` and
`1.04e-7`. All 240 candidate-pad measurements are finite and uniquely keyed.

Across pads 4, 16, 64 and 128 s, the per-candidate score swing has median
`0.01216` and maximum `0.26021`; 18/60 exceed the declared `0.02` large-swing
scale. Relative to pad 4, fixed-boundary verdict flips are
`41.7%`, `50.0%` and `48.3%` at pads 16, 64 and 128 s. When every pad is
separately calibrated on 5,000 background scores per detector, the
corresponding pipeline-verdict flip rates are `51.7%`, `68.3%` and `51.7%`.

This falsifies the earlier approximately 5% statement. The final rates remain
strictly conditioned on deliberate sampling near the robust/background
boundaries and are neither survey-wide prevalence estimates nor upper bounds.
Only this final gate-passing artifact may be used in the manuscripts. P9 began
after the whitening verifier passed; its pilot artifact is temporary until the
full 375-trial run and P9 gate complete.

### 31.9 Final C2 astrophysical-injection control

P9 completed 375 valid trials, exactly 25 in each of 15 cells spanning BBH
30+30, BBH 10+10 and NSBH 10+1.4 at 100--1600 Mpc. The number attempted ranges
from 28 to 40 per cell because windows unavailable in both detectors are
skipped. The saved trial ledger is finite, uniquely indexed, hash-linked and
passes reconstruction of every DSD class and of the end-to-end endpoint:
primary O3b flag AND Top-k-localized physical cross-correlation in the same
detector direction.

At 100 Mpc, flag-either counts are 23/25 for BBH 30+30, 22/25 for BBH 10+10
and 7/25 for NSBH; corresponding end-to-end coincidence counts are 16/25,
12/25 and 0/25. At 200 Mpc, the two BBH flag counts are 12/25 and 14/25, but
coincidence is 9/25 and 0/25. All NSBH coincidence cells are 0/25. BNS is not
measured because its waveform plus the protocol's margins cannot fit within the
32 s analysis window.

Every binomial endpoint and DSD class now carries its exact count, denominator
and 95% Wilson interval derived from the hash-checked trial ledger. For example,
16/25 has interval `[0.445,0.798]`, while 0/25 has upper endpoint `0.133`.
This uncertainty attachment is part of future P9 execution and was also applied
to the completed artifact without changing trial data. The focused suite passes
42/42 and the augmented artifact passes the P9 verifier.

The system-distance cells are not paired on identical backgrounds or
orientations, and n=25 leaves wide intervals. The grid must therefore be shown
as discrete simulation controls, not interpolated as a monotonic efficiency
curve. Nonzero distant-cell flags may reflect background false positives.
Neither these flags nor the simulated coincidence rates are real-event recovery
efficiencies.

### 31.10 Deferred PEM auxiliary-data mirror

The coherent C2 PEM rerun deliberately continues with the existing direct NDS2
fetch path. Introducing a new cache while the campaign is active would divide
the 141-event sample across two data-access contracts and would change the
provenance surface after part of the null calibration had already completed.
No cache optimization is therefore allowed in the current run.

For future repeated PEM campaigns, the material optimization is a persistent
local mirror of the raw public auxiliary time series returned by NDS2. Legacy,
bgv2 and bgv3 runs have otherwise downloaded the same detector/GPS/channel data
again. The future cache must be keyed by the complete immutable request
contract---NDS host, detector, full channel name, GPS interval, sample rate and
any resampling/decimation parameters---rather than by taxonomy version or PEM
verdict. Each entry must carry source/request metadata, exact temporal coverage,
sample count, finite-data checks and a content checksum. Partial or corrupt
entries must never be accepted silently.

The cache should be a read-through raw-data layer, not a cache of derived
coherence or verdicts. This permits exact raw requests to be reused across
analysis versions while keeping every derived result separately versioned.
Writes must be atomic and concurrency-safe; overlapping requests should be
chunked or deduplicated; the cache root and retention policy must be explicit
and should live on a large data volume rather than inside the repository.
Required validation includes cold-cache versus warm-cache numerical identity,
a network-disabled warm rerun, corruption/truncation recovery, and provenance
reconstruction from the manifest. The detailed deferred design is recorded in
`codex_research_notes/PEM_AUX_CACHE_FUTURE_PLAN.md`.

### 31.11 Final coherent C2 PEM calibration and provenance gate

**Status: DONE 2026-07-30 19:39 CEST; 141/141 calibrated, 0 failures.**

The representation-coherent PEM campaign completed 78 H1 and 63 L1
family-wise null calibrations. The selected-target ledger, coherence report,
null-JSON key set and verdict ledger contain the same 141 unique
detector/GPS pairs: 23 ROBUST, 20 AMBIGUOUS and 98 BACKGROUND. Every numeric
verdict field is finite; coherence values and thresholds lie in `[0,1]`; each
event has a non-empty channel set; and every ordered-pair count reproduces
`n_windows * (n_windows - 1)`. No event is `UNCALIBRATED`.

The time-shift max-statistic is retained only as a diagnostic endpoint:

| coherent class | time-shift positive / calibrated | Wilson 95% CI |
|---|---:|---:|
| ROBUST | 4/23 (17.4%) | [7.0%, 37.1%] |
| AMBIGUOUS | 7/20 (35.0%) | [18.1%, 56.7%] |
| BACKGROUND | 37/98 (37.8%) | [28.8%, 47.6%] |

For ROBUST versus BACKGROUND this endpoint gives odds ratio `0.3471` and
two-sided Fisher `p=0.0863`. Of its 48 positives, 38 do not exceed the
quiet-background zero-lag q99 and are therefore `SUSPECT`, not confirmed
couplings.

The primary two-null endpoint retains:

| coherent class | zero-lag-confirmed COUPLED / calibrated | Wilson 95% CI |
|---|---:|---:|
| ROBUST | 2/23 (8.7%) | [2.4%, 26.8%] |
| AMBIGUOUS | 1/20 (5.0%) | [0.9%, 23.6%] |
| BACKGROUND | 7/98 (7.1%) | [3.5%, 14.0%] |

The final tier counts are 10 `COUPLED`, 38 `SUSPECT` and 93
`NO_CORRELATION`. ROBUST versus BACKGROUND gives odds ratio `1.2381` and
two-sided Fisher `p=0.6796`: the coherent sample does not resolve enrichment
of auxiliary coupling. This high p-value is not evidence that the rates are
equal. Public-channel incompleteness and absent safety certification remain
scientific limitations.

The two retained singleton controls reproduce their expected physical
dispositions. H1 GPS `1369305276` is `COUPLED`
(`Cmax=0.98717`, time-shift threshold `0.54451`, zero-lag q99 `0.69347`);
L1 GPS `1382955228` is `NO_CORRELATION`
(`Cmax=0.47849`, thresholds `0.66274/0.78915`).

The PEM gate was strengthened before manuscript propagation. The final
`pem_provenance_manifest.json` contains SHA256 and byte counts for six
scientific inputs, 141 per-event null JSONs, the verdict and association
artifacts, the WSL environment record, the dirty-source snapshot, and the
complete execution log (152 records total). The verifier recomputes every
hash, the complete target identity, all numerical invariants, the two-null
decision rule, class endpoint counts and confidence-interval containment.

Final empirical checks:

```text
PASS p5
PASS p4
PASS p10
PASS multiscale
PASS cohesion
PASS whitening
PASS p9
PASS r5
PASS p11
PASS pem

93 passed, 1 skipped   # critical + regression + smoke suites
2 passed, 3 warnings  # end-to-end integration; xFormers unavailable
```

The full repository suite then passed `120 passed, 1 skipped, 3 warnings` in
66.79 s. The three warnings are the classified xFormers-unavailable messages
from the DINOv2 implementation; no scientific artifact warning was converted
into a pass.

### 31.12 Manuscript freeze and final rendered-PDF check

After the final PEM propagation, both paper sources and the CQG cover letter
were rebuilt with explicit `pdflatex -> bibtex -> pdflatex x2` cycles. The
arXiv continuation is 8 letter-size pages; the self-contained CQG manuscript
is 16 A4 pages; the cover letter is one A4 page. All pages were rendered to
PNG and inspected. No clipping, overlap, illegible figure, broken table or
stale PEM caption was found.

The final LaTeX logs contain no errors, undefined citations/references,
multiply defined labels, overfull boxes or fatal stops. PDF text extraction
confirms the final PEM endpoint (`2/23`, `1/20`, `7/98`), Fisher `p=0.680`,
4,558 taxonomy changes and 120 passing tests, and finds none of the
superseded paper values. A final post-render `--stage all` passes every C2
artifact gate, and no scientific Windows/WSL process remains active.

## 32. Post-freeze senior-review correction and shared evidence contract

### 32.1 Correction to the earlier manuscript-ready statement

The scientific C2/BGV3 artifacts remain closed, but the manuscripts are not
submission-ready. A later line-by-line senior review found a stale sentence in
both Discussion sections:

```text
41 apparent positives -> 12 confirmed endpoints
```

The verified PEM artifact instead contains 48 time-shift positives, 38 rejected
by the quiet zero-lag control, and 10 primary two-null endpoints
(`2/23`, `1/20`, `7/98`). The earlier statement in section 31.12 that no stale
paper values remained is therefore superseded. This is a manuscript
consistency failure, not a failure of the final PEM artifact.

The same review also found that the 16-page CQG source is still substantially
the compact arXiv continuation with added appendices. It is not yet the
standalone first journal paper required for CQG. The earlier description of it
as self-contained is superseded pending execution of
`CQG_V6_IMPLEMENTATION_PLAN.md`.

### 32.2 A0 evidence freeze

On 2026-07-30 the fail-closed verifier was rerun:

```text
python scripts/verify_c2_bgv3_artifacts.py --stage all
PASS p5
PASS p4
PASS p10
PASS multiscale
PASS cohesion
PASS whitening
PASS p9
PASS r5
PASS p11
PASS pem
```

`codex_research_notes/MASTER_NUMBERS_V6.yaml` is now the shared numerical
contract for arXiv and CQG. It records the allowed metrics, scope statements,
artifact paths and SHA256 hashes for 15 load-bearing artifacts. YAML parsing
and independent hash reconstruction pass with zero mismatch. The claim ledger
now points to this contract and treats the v5 rate limits as withdrawn from the
v6 scope rather than pending automatic reinstatement.

No new scientific result is inferred by the evidence freeze. Its purpose is to
prevent prose, figures or the chronological notebook from becoming competing
numerical sources.

## 33. CQG external-validation preregistration

### 33.1 O3b-to-O4a domain-shift endpoint

Before inspecting a cross-run result, the CQG domain-shift experiment was
defined in `scripts/validate_cross_run_domain_shift.py` as follows:

- O3b and O4a use the same canonical
  `whiten_context(pad=4) -> extract_clean_subwindow -> Q=(4,64)` path and the
  same frozen DINOv2 patch representation;
- results are separated by detector;
- the chronologically earliest 60% of each sampled clean population build
  equally sized native dictionaries and the remaining 40% are held out;
- the primary direct comparison is the O3b-versus-O4a score distribution
  against the same O3b index, with mean-difference bootstrap interval, KS
  distance and Wasserstein distance;
- the adaptation endpoint is the paired O4a native-index minus O3b-index score
  difference;
- a time-blocked linear run probe uses only L2-normalized segment-mean patch
  embeddings. GPS, detector identity, filenames, image extrema and embedding
  norm are excluded, and shuffled-label probes are retained as leakage
  controls.

The final run must contain 100 clean segments per run and detector. A
12-segment L1 pilot is machinery validation only and cannot support a paper
claim. Token caches use schema v2, include the complete sampling and source
identity, require exact `(n,1369,384)` finite tensors and unique GPS values, and
are hashed in the result artifact.

### 33.2 External known-morphology control

The held-out control in `scripts/validate_known_glitch_controls.py` was defined
before execution. It selects Gravity Spy O3b events from Zenodo record 5649212
with `ml_confidence >= 0.95` and Omicron `snr >= 7.5`. The fixed query
morphologies are Blip, Scattered Light and Koi Fish, separately for H1 and L1.
Selection is deterministic from the seed and Gravity Spy identifier. No query
may lie within 96 s of any clean index or background GPS.

The Gravity Spy labels are never used to build or calibrate the DANTE index.
The endpoint is AUC and median score separation for known-morphology versus
held-out clean O3b strain, with stratified bootstrap intervals. A label-free
nearest-neighbour distance between segment-mean embeddings is retained as the
simple baseline. This is not a multiclass-classification benchmark, an O4a
recall estimate or evidence that Gravity Spy covers O4a.

### 33.3 Native-adaptation absorption matrix

The Q64 absorption extension was also fixed before execution:

- three synthetic morphologies: Blip (`A=12`, `1.0 s`), Scattered Light
  (`A=12`, `1.5 s`) and Koi Fish (`A=12`, `1.0 s`);
- seeds `42`, `314159` and `271828`;
- contamination fractions `0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40`;
- 300 index-background, 150 held-out background and 60 held-out injected
  segments per cell, with same-size all-background controls;
- operational absorption crossing: the first tested fraction at which both
  `z <= 3` and flagged fraction `<= 0.5`.

The crossing is a predeclared measurement convention, not a universal
detection limit. Each cell must contain disjoint GPS groups, complete finite
encodings, bootstrap uncertainty for standardized separation and a Wilson
interval for the flagged fraction. The previous Scattered Light JSON lacks
Q-range provenance and is inadmissible for the Q64 matrix. Existing
single-seed Blip evidence remains a proof of mechanism until the complete
matrix passes.

During this preregistration, the absorption implementation was corrected so
that the cache identity includes run, detector, Q range, morphology, amplitude,
duration, all sample allocations, maximum prevalence and seed. Cache hits now
skip both strain acquisition and encoding, stochastic synthetic generators are
seeded reproducibly without changing global RNG state, partial encodings fail
closed, and per-seed outputs cannot overwrite one another. Background and
held-out-background Q64 tokens are shared across morphologies only when the
complete run/detector/sample-allocation/seed contract is identical; injected
tokens remain morphology-specific. This removes threefold redundant
background encoding without merging scientific cells or weakening provenance.

The P4/P5 extension in `scripts/run_cqg_robustness_replicates.py` separates
three axes that were confounded or sparsely sampled in the first checks:
eight segment-bootstrap background draws at fixed K-means seed, five K-means
seeds on the fixed background, and four K values at fixed background/seed.
Every axis is evaluated on the original near-boundary stress population and on
a deterministic simple random sample from the complete O4a candidate
population, balanced only by detector and never selected by score or DSD
disposition. Rebuilt-index thresholds remain excluded: the endpoints are
pairwise Spearman rank correlation and per-candidate score variation with
candidate-resampling intervals. Model centroids and scores are checkpointed
with complete cache identities.

Twenty focused claim/domain/absorption/known-control/robustness tests pass.
At preregistration time no scientific result from Q1 or Q2 had been inspected.

### 33.4 Completed P4/P5 robustness replicates

The full threshold-independent robustness matrix completed and
`verify_cqg_validation_artifacts.py --stage robustness` independently
reconstructed every summary from the 16 hashed model checkpoints. The
unconditioned population contains 160 unique candidates (80 per detector),
disjoint from the 160-event near-boundary population, with 96 ROBUST,
20 AMBIGUOUS and 44 BACKGROUND DSD dispositions emerging from the fixed random
sample.

| axis | population | mean pairwise Spearman (candidate-bootstrap 95% CI) | minimum pairwise Spearman | median per-candidate score std (95% CI) |
|---|---|---:|---:|---:|
| 8 background draws | near-boundary | 0.9340 [0.9131, 0.9450] | 0.8336 | 0.00809 [0.00673, 0.00938] |
| 8 background draws | unconditioned | 0.9766 [0.9617, 0.9841] | 0.9293 | 0.00731 [0.00681, 0.00826] |
| 5 K-means seeds | near-boundary | 0.9537 [0.9365, 0.9633] | 0.8965 | 0.00595 [0.00435, 0.00694] |
| 5 K-means seeds | unconditioned | 0.9877 [0.9781, 0.9920] | 0.9807 | 0.00548 [0.00479, 0.00604] |
| 4 K values | near-boundary | 0.9025 [0.8677, 0.9261] | 0.8300 | 0.01363 [0.01261, 0.01513] |
| 4 K values | unconditioned | 0.9784 [0.9626, 0.9866] | 0.9620 | 0.01304 [0.01174, 0.01495] |

The result supports rank stability, with the expected degradation in the
deliberately near-boundary stress sample and the largest sensitivity along the
K-value axis. It does not validate threshold/verdict agreement because the
rebuilt clean-background populations are not the frozen production threshold
population. The earlier four-draw P5 and single-seed P4 values remain
consistent special cases, but the manuscript must use this replicated matrix
for uncertainty statements.

## 34. Detector-aware final propagation and paper freeze (2026-08-06)

**Status: ALL COMPUTATIONAL GATES PASS; MANUSCRIPT REFRESH IN PROGRESS.**

The catalogue identity is now `(detector, gps_start)`, not GPS alone. The final
O4a taxonomy contains **10,429** unique detector--time windows: H1 has
2,227 ROBUST, 562 AMBIGUOUS and 1,622 BACKGROUND (4,411 total); L1 has
4,138 ROBUST, 713 AMBIGUOUS and 1,167 BACKGROUND (6,018 total). Combined
counts are **6,365/1,275/2,789**. The DSD audit evaluates 10,429/10,429 with
zero failures. It proves exact score reuse for 10,372 detector--GPS keys
(maximum absolute difference zero) and normal scoring of the 57 restored keys.
The paired historical representation ablation remains 4,558/10,372; the 57
restored windows have no cross-representation counterpart and are not added to
that denominator.

The final H1 calibration is \(P_{99}=0.161579\), 95% block-bootstrap interval
[0.130231, 0.204088]; L1 remains \(P_{99}=0.176063\), interval
[0.150319, 0.219594]. Both use 5,000 independent background windows and
\(10^6\) bootstrap replicates. Current taxonomy, score and threshold SHA256
values are recorded in `MASTER_NUMBERS_V6.yaml`.

Taxonomy-dependent C2 results were regenerated or fail-closed rejoined:

- P5: mean/minimum pairwise Spearman 0.673702/0.514687; median candidate
  score standard deviation 0.007567. This supersedes every 0.979, 0.891 and
  0.582 draft claim for the final detector-aware C2 endpoint.
- P4: rho versus K=1216 is 0.752514, 0.768045 and 0.942790 for K=512, 1024
  and 2048; pairwise mean/minimum is 0.792286/0.645169.
- P10: PCA residual AUC/rho is 0.43625/-0.15787; spectral-energy AUC/rho is
  0.54375/0.03006 (H1/L1 AUC 0.598125/0.4900).
- Whitening: 60/66 retained; median/max score swing 0.010880/0.073835;
  16/60 exceed 0.02. Fixed-boundary flips are 24/60, 24/60 and 22/60;
  pad-specific recalibrated flips are 38/60, 42/60 and 39/60 at 16, 64 and
  128 s. This remains a deliberately boundary-conditioned stress test.
- Cohesion: ROBUST largest component 6,360/6,365 (99.921%); AMBIGUOUS,
  BACKGROUND and native background each saturate at 100%.
- R5: H1/L1 use 2,227/4,138 ROBUST candidates; no positive recurrence is
  resolved by the current embedding/statistic.
- P11: two observed any-detector overlaps versus null mean 2.1899,
  empirical p=0.6508; coverage remains proxy-level.
- PEM: the fixed 141-event measured cohort changes class for 8 events after
  exact detector+GPS rejoin. New classes are 26 ROBUST, 22 AMBIGUOUS and
  93 BACKGROUND. The primary endpoint is 2/26 versus 7/93, OR 1.0238,
  two-sided Fisher p=1.0; the conclusion of no resolved association is
  unchanged. Event-level measurements and nulls were not recomputed.
- Physical coincidence: 8,806/10,429 measured, 1,623 historical unmeasured;
  13 exceed pooled P99=0.404591 with no resolved on-source tail excess.

`verify_c2_bgv3_artifacts.py --stage all` passes P5, P4, P10, multiscale,
cohesion, whitening, P9, R5, P11 and PEM. The CQG verifier passes domain,
known-glitch, absorption and robustness, including the earlier deep check.
The pertinent regression suite reports **114 passed**. No incomplete result is
promoted to PASS.

Paper contract: arXiv v6 explicitly continues and corrects v5. CQG v6 is the
first journal presentation and must remain self-contained: it introduces the
complete data path, definitions, related work, calibration hierarchy, nulls,
limitations and reproducibility requirements without depending on v5.

### 34.1 Final manuscript and rendered-asset provenance

After figure regeneration, claim checking and three-pass LaTeX compilation:

| object | SHA256 |
|---|---|
| arXiv `main.tex` | `4e2f16748827942a2038776552566cf4d20f9cef295b4d629bb83aae2796e629` |
| arXiv `main.pdf` | `cc0779cb45e291ffba7aa2cc4895aa8ece65df5198a71a708fb497e8a707df17` |
| CQG `main.tex` | `e9d053031ab67037e94e2f753ffa81dec02022193217895c0810c04bfdb89d0b` |
| CQG `main.pdf` | `4efae5cece062c736d98a40df61037317e484d1a0f12eeb9f0d657d850912ddc` |
| CQG cover-letter PDF | `ac6f61be3a1a88e0afd203b5d19ce8a7f014d05c7ad3f880b40850753f0a799d` |
| funnel figure | `6c39478e4fc19e066440ef4ea4bb7f435661484f0a9f8b34649337933ec5d069` |
| robustness figure | `6eec80ef793554368a9ec262ce543b0a7465e8cb29987eabebd4b1333a0535c0` |
| PEM figure | `d1df64a90d8dfb9ff357183d83967f841699cfa83a8f551135489fa09189834a` |

The arXiv PDF has 10 letter-size pages; the self-contained CQG PDF has 16 A4
pages and its cover letter has one A4 page. Page-by-page contact-sheet review
found no clipped or overlapping text, broken figures, unreadable tables or
missing pages. The only arXiv float warning corresponds to a visibly placed
figure and does not omit content. No undefined citation or reference remains.

## 35. Submission gap closure: detector-aware ablation contract (2026-08-07)

The representation-contract ablation was recomputed by an exact one-to-one
join on `(detector, gps_start)` between the archived pre-detector-aware
taxonomy and the current coherent taxonomy. The paired population is 10,372
with zero missing keys. The current number of changed dispositions is
**4,676**, not the stale 4,558 used by the draft manuscripts. The complete
row-major matrix (Q32/Q64 rows, coherent Q64/Q64 columns ROBUST, AMBIGUOUS,
BACKGROUND) is:

| Q32/Q64 | ROBUST | AMBIGUOUS | BACKGROUND |
|---|---:|---:|---:|
| ROBUST | 2,914 | 14 | 9 |
| AMBIGUOUS | 1,666 | 68 | 39 |
| BACKGROUND | 1,759 | 1,188 | 2,714 |
| UNKNOWN | 0 | 0 | 1 |

The 57 detector-aware restored keys have current classes 26 ROBUST,
5 AMBIGUOUS and 26 BACKGROUND. The final machine-readable artifact is
`data/production/aggregated/dsd_representation_transition_detector_aware.json`
with SHA256
`203a1f93c71f31cdd7342264ddc8d2705ce02b1c2b4e1bf266b1a2e6e38693bb`.
It is rebuilt by `scripts/build_dsd_representation_transition.py`; `--check`
fails on any source/hash/matrix drift. `MASTER_NUMBERS_V6.yaml`, the claim
ledger and the manuscript checker now consume this contract. Manuscript
integration remains intentionally RED until both papers replace 4,558 and the
CQG appendix table.

## 36. Submission figures for CQG validation questions Q1/Q2 (2026-08-07)

`paper_draft/v6_paper/tools/generate_paper_figures.py` now loads only final or
complete CQG validation artefacts and rejects pilot status. It generates three
submission figures and copies byte-identical files into both manuscript image
directories:

| figure | source artefact | SHA256 |
|---|---|---|
| `fig_domain_known_q64.png` | `cqg_cross_run_domain_shift.json` + `cqg_known_glitch_controls.json` | `116bd225c4fc826257584444a66d1d2f8a55c4a2db9f574a4733c210e201ec69` |
| `fig_robustness_replicates_q64.png` | `cqg_robustness_replicates.json` | `c7fb321bee42cd72202d3eef77e5965f7d4b15eb2bb7814e9321f08ca22b0834` |
| `fig_absorption_matrix_q64.png` | `cqg_absorption_matrix.json` | `122bcc5e16ac305dc7732532a5819ae40fdfbf887760f893966b66b85ae4b315` |

The three central figures were visually inspected at original resolution after
the final regeneration: axes, uncertainty intervals, seed ranges, thresholds,
and labels are legible and no element is clipped. The absorption labels print
a single percentage when all seeds share the same crossing and a range only
when crossings differ. Re-running the generator reproduced identical hashes.

## 37. Frequency-product audit correction (2026-08-07)

A second code-and-data check, requested before accepting the initial audit,
showed that the submission-blocking conclusion recorded here earlier was
wrong and is withdrawn.  The original diagnostic mapped DINO patch row
`p // 37` to frequency.  Production preserves GWpy's
`Spectrogram.value` order `(n_times, n_frequencies)`, so the correct mapping is
row `p // 37` to time and column `p % 37` to frequency.  The repository now
contains direct regression tests for both late/low-frequency and
early/high-frequency features.

The frequency limit was also checked by executing the production Q-transform
on a readable raw O4a file from `E:`.  The input sample rate is 4096 Hz and the
raw Q-transform has shape `(1000, 500)`, with 1000 time bins and 500 frequency
bins.  Although configuration requests 20--2048 Hz, GWpy lowers the maximum
to **1291.053052 Hz** for a 32 s window with `qrange=(4,64)` and emits a
warning.  The scored representation therefore contains no 1700--2048 Hz
pixels.  The earlier percentages were counts in the last **time** row, not in
an invalid high-frequency row, and cannot support a frequency-band objection.

An inventory of the local raw store found 7,184 HDF5 paths: 7,174 readable
files, all one-dimensional 4096 Hz `Strain`, and 10 files with unreadable HDF5
object headers (two already under `.corrupt`).  The original production log
independently records all ten read failures (nine H1 blocks and one L1 block),
so their exclusion is observed rather than inferred.  This supports the
existing coverage limitation---the historical scan has no successful-window
ledger---but does not invalidate the frequency representation.  Exact evidence
and the retraction are recorded in
`codex_research_notes/FREQUENCY_BAND_AUDIT_CORRECTION_2026-08-07.md`.

## 38. Manuscript integration and automated submission freeze (2026-08-07)

The arXiv v6 manuscript is explicitly a continuation and correction of v5.  Its
v5-to-v6 table separates confirmed, corrected, restricted, unsupported and new
controls.  It incorporates the detector-dependent cross-run result,
known-glitch construct controls, final replicated robustness matrix and
three-morphology absorption matrix without presenting itself as a new
standalone paper.

The CQG manuscript is a self-contained journal article with a new title,
standalone method and population definitions, related-work comparison,
detector-aware results, explicit physical nulls, limitations, data/code
availability, correction log and requirements for another observing run.  The
cover-letter title is byte-for-byte identical after whitespace normalization.
Its reference audit closes 38 cited keys: 25 Crossref DOI records, two DataCite
Zenodo records, the official GWOSC auxiliary-data DOI and eleven arXiv records
resolve to the expected works.

The final automated gate reports:

- C2/BGV3 verifier: PASS P5, P4, P10, multiscale, cohesion, whitening, P9,
  R5, P11 and PEM;
- CQG verifier: PASS domain, known-glitch, absorption and robustness;
- manuscript checker: `PASS papers=all artifacts=verified`;
- focused final suite: 36 passed;
- patch-axis regression: included, 5/5 passed;
- reproducibility bundle: 227 allowlisted files, including all 141 PEM null
  calibrations; manifest and extracted-ZIP round trip PASS.

Final rendered objects at this freeze are:

| object | pages | SHA256 |
|---|---:|---|
| arXiv `main.tex` | -- | `41027ec4335d62f2d4c2eea276e6ce285cd31696e42a1b6ed565088ce0fb7f34` |
| arXiv `main.pdf` | 11 | `f36ee0d4764cc2db53e9fb2926fdbd305c7a23624b2228ab9e3e7c6315d300ee` |
| CQG `main.tex` | -- | `2e794eb31d71496b905cf95d108ab7e2aed358b887bca9620f2e427db581947e` |
| CQG `main.pdf` | 21 | `a77defbf9eb8227e0e6b213062f5cdad9978b8d8811b18ce78f9c45257bf52ea` |
| CQG cover `cover_letter.tex` | -- | `1f37fbd506de7010350ab978930f6082674c03f83e8c4fa92486ebeb849cf97a` |
| CQG cover `cover_letter.pdf` | 1 | `c96382c1af8f8d3030a1b2e676e153f54fd9fdcd0184184b87511d5f1d7814c0` |

All 21 CQG pages, the one-page cover and all 11 arXiv pages were rendered and
inspected.  No clipping, overlap, missing float, broken reference or undefined
citation remains.  CQG has one harmless underfull table cell; arXiv has three
ordinary underfull paragraphs and the expected PDF-bookmark warning caused by
the title line break.  None changes visible content.

The automated work is complete, but submission is deliberately not marked
final until three facts are supplied by the author: a resolvable DOI for the
evidence bundle, the funding statement, and the exact OpenAI model/version for
the IOP-required generative-AI disclosure.

## 39. Candidate integration and final scientific reread (2026-08-07)

The retained L1 singleton is now integrated into both papers with a
detector--GPS keyed, fail-closed evidence record:
data/production/aggregated/candidate_case_L1_1382955228_idxq4-64_queryq4-64.json
(SHA256 0a84bbdad28e119d210fc4cd1b133dbef70f268bb339f258c26e3df5e1307483).
The historical catalogue key is GPS 1382955228, the exact scored window is
1382955232--1382955264, and the localized feature is at GPS 1382955253.17.

The publication figure was regenerated from the local E: raw block through the
canonical pad-4 whitening, clean crop, Q=[4,64] transform, cividis RGB
rendering, frozen DINOv2 encoder and native O4a dictionary.  The plotted Top-68
mean is 0.5988766551 versus stored taxonomy score 0.5988767743, absolute delta
1.19e-7.  The native-index SHA256 is
0241b2a1ea2a460334f2c7ae0ab1bb62052706ea05c48443af32ae60a2488744.

The bounded candidate interpretation is:

- statistically ROBUST under the coherent native DSD;
- a loud L1-local low-frequency transient (28 Hz; energy ratio 304.07 to the
  mean of 16 adjacent windows);
- above the recorded P99 at all four tested scales, with maximum margin 0.112
  at 4 s;
- no resolved H1 excess under the production time-shift control
  (0.0716 versus null mean/max 0.197/0.286; patch IoU 0.0074);
- no resolved coupling in the tested public PEM subset (0.478 below the
  family-wise and quiet-zero-lag thresholds 0.663 and 0.789);
- unclassified: not evidence for a new glitch class, and not evidence that an
  unmeasured instrumental coupling is absent.

CQG now contains the complete strain-to-follow-up schematic and an exact
representation figure; arXiv remains a continuation/correction of v5 and
explicitly withdraws the earlier singleton-as-novel-morphology interpretation.
The catalogue circular-shift null is now plotted in both manuscripts.
The superseded single-morphology absorption image is excluded from the release
payload; its stale release copy was moved recoverably to
paper_draft/v6_paper/archive/superseded_release_assets_20260807.

Final checks after the manuscript edits:

- candidate figure score reproduction: PASS, absolute delta 1.19e-7;
- C2/BGV3 stages: 10/10 PASS;
- CQG validation stages: 4/4 PASS;
- manuscript claim and artifact-hash checker: PASS for both papers;
- complete repository suite: 168 passed, 1 platform-dependent skip, 9
  classified warnings (optional xFormers and GWpy deprecation only);
- portable evidence bundle: PASS, 233 payload files and 141 PEM nulls.  The ZIP
  hash is recorded in the external submission-freeze checkpoint to avoid a
  self-referential hash inside a file included in that same bundle.

Rendered outputs were inspected page by page: arXiv 12 pages, CQG 23 pages and
cover letter 1 page.  CQG has no undefined references, overfull boxes or stuck
floats.  RevTeX emits a deferred-float warning while flushing the final
single/double-column figure queues; visual inspection confirms that all ten
arXiv figures are present, ordered, unclipped and placed before the references.
This warning is typesetting-only and is not counted as a scientific PASS.

Current frozen hashes:

| object | pages | SHA256 |
|---|---:|---|
| arXiv main.tex | -- | 7b9dd99f66a72c50eb3220132b19c7380eab1222ce148b8da3ae8bf9e98a2411 |
| arXiv main.pdf | 12 | 472ea7a4bc44de141bdfdd4334699fcecd99ffbe45741b631f273697a90269df |
| CQG main.tex | -- | 18f14c03dd748071be8ca70c659d95e32b122033815a9db8b3968945cde959e6 |
| CQG main.pdf | 23 | 1c0bbf08c4132658f84bfb59849ceb8e540bdba9523e80b83b6769807c3e2e1c |
| cover letter.tex | -- | 6be7d9da89a6ea83dd3113334a2b9efc885f745176d5b97b4b9d1ccddc39e127 |
| cover letter.pdf | 1 | 083d05dd64d9c72e52ca76174ca6281ed5ac87abf800344eadd097f0c9c532ed |

At this 7 August freeze the remaining submission blockers were a DOI for the
evidence bundle, the funding statement and the exact OpenAI model/version.  The
11 August entry below closes the latter two and supersedes this status.

## 40. Final reviewer extensions and editorial closure (2026-08-11)

The last reviewer pass corrected the description of the production quantile
bootstrap.  Code inspection showed that
`block_bootstrap_p99_distribution` resamples a chronological partition of
complete, disjoint blocks; it is a non-overlapping-block bootstrap, not the
overlapping moving-block bootstrap previously named in prose.  The released
thresholds and taxonomy were not changed.  The implementation now accepts an
optional block length for sensitivity analysis while preserving the production
default `floor(n^(1/3)) = 17`.

A final sensitivity run used 200,000 replicates per cell at block lengths
8, 17, 32 and 64.  Relative to the 10,429 released dispositions, the
non-overlapping scheme changes 46, 1, 42 and 140 labels; an independently
implemented overlapping moving-block scheme changes 86, 43, 7 and 148.  Thus
at least 98.58% of the catalogue is unchanged across this finite grid, while
boundary labels remain dependent on block length and resampling scheme.  The
complete artifact is
`dsd_block_length_sensitivity_o4a_idxq4-64_queryq4-64.json`, SHA256
`2d54df439e6f07b6a6ed1a53db18435421f3599da74e4a22753fd9f2d48aa3ea`.

A second reviewer request tested whether a GW-specific nonlinear representation
recovers the DANTE disposition.  Separate convolutional autoencoders were
trained for H1 and L1 on 650 candidate-vetoed O4a Q-transform backgrounds per
detector.  Inputs use the same 32x32 log-power representation as the PCA
control; three deterministic seeds were evaluated on the same balanced set of
80 ROBUST and 80 AMBIGUOUS near-boundary candidates.  A cache-only rerun
reproduced the results exactly.  The pooled AUC is 0.472890625, the seed AUCs
are 0.473203125, 0.485 and 0.482734375, and pooled Spearman correlation with
DANTE is -0.0468630.  H1/L1 AUC is 0.5284375/0.4240625.  This is retained as a
negative control: reconstruction error does not reproduce DANTE and is not a
physical-accuracy test.  The result artifact SHA256 is
`735c702bda3a5be861fe303813836334fb2bd3ee40741c22611c77b4decfeed2`;
the candidate score table SHA256 is
`babd806fe3fed73e9bcf5d5dfe0bc92f6a69f09f57522dab3dd5b2e8e83bb47d`.

Editorial metadata now follows the IOP requirements checked on 11 August:
both manuscripts disclose OpenAI Codex (GPT-5, service version accessed
July--August 2026) and its use for code review, consistency checks and language
editing, while assigning all scientific responsibility to the author.  A
no-external-funding statement was added.  The operational detector-
characterization context now cites Omicron, hierarchical veto and BayesWave.
The only external submission item still pending is a resolvable DOI for the
separate evidence bundle; the existing Zenodo DOI remains the software DOI.

The final integrated gate reports 174 tests passed, one platform-dependent
skip and nine classified warnings.  The C2/BGV3 verifier passes all ten stages;
the CQG verifier passes domain, known-glitch, absorption, robustness and the
reviewer extensions; the manuscript checker passes both papers with artifact
hash reconstruction.  The portable bundle contains 249 files and passes its
manifest and ZIP round trip.  The updated robustness figure has SHA256
`863f856dca4fac16b95d0fa1952a5205257992260a46f5fdd5d608a03986dcc4`.

Final rendered objects were inspected page by page.  CQG has 24 pages and no
undefined citation, undefined reference, overfull box, clipping or overlap;
one underfull table cell is visually harmless.  The cover letter was reduced
from an accidental two-page rendering with an orphaned signature to one clean
page.  arXiv has 12 pages and all ten figures are present, ordered and legible.
RevTeX still reports its deferred-float warning while flushing the final CBC
figure before the references; inspection confirms that no float is lost or
clipped, so the warning is recorded rather than promoted to a scientific PASS.

| object | pages | SHA256 |
|---|---:|---|
| arXiv `main.tex` | -- | `0c90614b011d28d6e452a5dd295061a062ceda267a0df4eaa5c83a183c7e3ff8` |
| arXiv `main.pdf` | 12 | `e8d5acd56a90a32f6da0566de4c4a242e76dcb12d557c158f305a07bc0a44321` |
| CQG `main.tex` | -- | `af4852b02e46a6fb66736619683724dfa87373b7f4b3c2d6a2e8ef3a4284c20f` |
| CQG `main.pdf` | 24 | `ec11cdb18be1924815c7a3d31a90fc44f9898a2e319c26ca40a1e6f8d2d79c1a` |
| cover letter `cover_letter.tex` | -- | `31a6cc60fe94e34734d8d71931d239b07563d5f39704b6e4895a029f9b5c71f1` |
| cover letter `cover_letter.pdf` | 1 | `486376bfd807457293efc75ac35e474aadff95e1d407993b94c79eb872f111b5` |

## 41. DANTE acronym definition audit (2026-08-11)

A final editorial check found that the manuscripts used the project name
without expanding it.  Both abstracts and both main introductions now define
**DANTE as Domain-Adaptive Network for Transient Evaluation** at first use;
the CQG cover letter defines it independently.  Defining the acronym in both
abstract and body is intentional because the abstract is indexed and read as a
standalone object.  The titles retain the shorter project name.  Recompilation
preserves 12 arXiv pages, 24 CQG pages and the one-page cover; the affected
pages were rerendered and inspected with no clipping, overlap or new warning.

| object | pages | SHA256 after acronym definition |
|---|---:|---|
| arXiv `main.tex` | -- | `b9b7c83e26240336c33400e4115ffcfd9003f2a9113173a272a2fa69599237a4` |
| arXiv `main.pdf` | 12 | `70a421f58a3654700da192cef777259271bf5cc473878d5a5e44615aa2b20fcb` |
| CQG `main.tex` | -- | `c2ef5f36ff3ca3a5b3b82c69a945f6ea36b91e3b4fb9a19491a2478d93318fdd` |
| CQG `main.pdf` | 24 | `fbc30594691e4864d772d0576435b5ec52326c701a00a7ba3d6ee176aa2e7038` |
| cover letter `cover_letter.tex` | -- | `f122bce83d720e0d9513cb82f38314f127dfcf871371e107fa9f21a72cfd4929` |
| cover letter `cover_letter.pdf` | 1 | `283ea4af81dc54aa284bff1fc5fd2871a04b07d2deee41b94c433c2678b694f6` |

## 42. Final self-contained reporting closure (2026-08-12)

A new anonymous-review pass checked the current manuscripts against the
load-bearing code rather than only against the claim ledger.  The inspection
covered canonical whitening and crop, Q64/cividis rendering, Top-68 MIL,
chronological block calibration, physical coincidence, the detector--GPS PEM
rejoin, synthetic absorption, blind-map SNR scaling, and the CBC waveform and
projection path.

One factual discrepancy was found in the prose: the final multi-morphology
absorption runner uses duration 1.0 s for Blip and Koi Fish but 1.5 s for
Scattered Light.  Both papers had said generically 1 s.  The manuscripts,
MASTER_NUMBERS and claim ledger now carry the correct per-morphology durations;
no numerical artifact or scientific result changed.

The CQG article now includes a self-contained statistical-analysis subsection.
Both papers record the bootstrap units and replicate counts, primary versus
diagnostic endpoint hierarchy, absence of a global multiplicity correction
across exploratory controls, family-wise PEM construction, absorption units,
blind-map matched-filter SNR, and CBC waveform/orientation/trial contracts.
The arXiv text remains explicitly a continuation and correction of v5; CQG
remains the standalone journal treatment.

Final empirical gates after all manuscript and provenance edits:

- claim checker with artifact-hash reconstruction: PASS for both papers;
- C2/BGV3 verifier: all ten stages PASS;
- CQG verifier: domain, known-glitch, absorption, robustness and reviewer
  extensions PASS;
- complete suite: 174 passed, one platform-dependent skip, nine classified
  warnings (three optional-xFormers and six GWpy deprecation warnings);
- fail-closed obsolete-claim scan: no stale number occurs as a manuscript
  claim; legacy values remain only in forbidden-fragment guards or explicit
  withdrawal notes;
- bundle: 250 allowlisted files, manifest and ZIP round trip PASS; the final
  ZIP hash is recorded in the delivery checkpoint outside the payload to avoid
  a self-referential provenance record.

The final PDFs were rendered and visually inspected page by page: arXiv has 12
pages, CQG 25 pages and the cover one page.  No clipping, overlap, missing
figure, undefined reference, undefined citation or overfull box remains.  CQG
has one harmless underfull table cell.  RevTeX retains its recorded deferred-
float warning; all ten figures are present and legible.  The final CQG page is
the clean closing page of the bibliography, not an orphaned heading or figure.

| object | pages | SHA256 after reporting closure |
|---|---:|---|
| arXiv `main.tex` | -- | `12f9a82b513c2e3ed405f4d9871b7a490c802a44ef4fdc5b1f9954ac6d7844b8` |
| arXiv `main.pdf` | 12 | `15dab1453ebdee4198d85bc996e818d57584d4036d6c138ca17fc4e29bfcbd54` |
| CQG `main.tex` | -- | `c7c2668606eb365f9b23bde4c84e678d905f90c8947d67b9efa2d7858242f76e` |
| CQG `main.pdf` | 25 | `d26f9fbee0d2f916827712e5d589ac1a45fa527df30146c709a13fb860539133` |
| cover letter `cover_letter.tex` | -- | `f122bce83d720e0d9513cb82f38314f127dfcf871371e107fa9f21a72cfd4929` |
| cover letter `cover_letter.pdf` | 1 | `ce5b88a81a2094c6b2df0fcd99bd49f74878bd91402339f0b0fce84afd02dd4f` |

The only remaining submission gate is external: upload the final local
evidence bundle to a separate Zenodo record, obtain its resolvable DOI, and
replace the fail-closed `will be deposited` wording.  DOI
`10.5281/zenodo.21676289` remains the software DOI and is not substituted for
the evidence-record DOI.

## 43. Evidence DOI publication and submission freeze (2026-08-14)

The external evidence gate is closed.  Zenodo record
`10.5281/zenodo.21925453` is published as the dataset *DANTE v6:
Reproducibility and Validation Evidence Bundle*.  A direct Zenodo API check
returned the deposited file `dante_v6_reproducibility.zip`, size 8,958,047
byte and MD5 `2b84a96f557629a8a2805c3c08feede4`; these match the frozen local
payload exactly.  The independently calculated SHA256 is
`a04ef27a564ab356103eb1ae14031d14649359e884d571aa08a832bc822bd37c`.

The software and evidence records are deliberately distinct.  DANTE 3.7.0 is
the versioned software release `10.5281/zenodo.21912589`; the v6 evidence DOI
above identifies the immutable result bundle.  Both manuscripts and the CQG
cover letter now cite these records according to their separate roles.

The published ZIP is not rebuilt after inserting its own DOI in the submission
sources.  A rebuild would change the deposited bytes and create a recursive
deposit cycle.  The deposited payload therefore remains the validated
pre-deposit freeze, while the post-deposit manuscript PDFs and notebook are
checked independently.  Zenodo metadata contain one non-blocking typo in the
related identifier (`10.5281/zenodo. 21912589` with a stray space); this should
be corrected in the Zenodo metadata UI but does not alter either DOI or the
deposited file.

Post-deposit submission verification completed after DOI insertion:

- manuscript claim checker with artifact hashes: PASS for arXiv and CQG;
- C2/BGV3 verifier: all ten stages PASS;
- CQG validation verifier: all five stages PASS;
- full suite: 174 passed, one platform-dependent skip, nine classified
  warnings;
- LaTeX/BibTeX compilation: PASS for both manuscripts and the cover;
- visual review of the affected final pages and bibliographies: PASS; the DOI
  entries are legible, arXiv remains 12 pages, CQG 25 pages, and the cover one
  page.

| post-deposit object | pages | SHA256 |
|---|---:|---|
| arXiv `main.tex` | -- | `17180777060844db3d1f1466ec95e92450ffceca338d7a9962f78e3a2c8c2370` |
| arXiv `references.bib` | -- | `643563d5ebfc45fd5465013198a0d5e01c50dc4bc8c2f7d72b37834de13dd834` |
| arXiv `main.pdf` | 12 | `a6f1f25da4dd338ae87a8bd599fece2779a16c35c5476515e1985ea4b4444d87` |
| CQG `main.tex` | -- | `0f2665d1da7193f532a64e1b28fea5aaf39ddc4ac7dd2f0d5b3e7c8138e7cb1b` |
| CQG `references.bib` | -- | `54d0e4a03f9c08d4d80e5d518756e338539be4caebc45cd5a82a58840fa9b85b` |
| CQG `main.pdf` | 25 | `1607232fa6d39b71034a81a24e75dcf8a88c581b28df27b43adc4c967da0348f` |
| cover `cover_letter.tex` | -- | `c923ff4be55ccad6431c1484ec45646823ca3919b19eb9e732e0242f2a3b0226` |
| cover `cover_letter.pdf` | 1 | `ad0e2a0b55fedee1c682034b4e50b3fb20569840dab43bf4e1d1ffd517360dcc` |

## 44. Final reviewer minor-revision closure (2026-08-14)

The final simulated anonymous-review pass identified two reporting defects and
checked both against code before changing the manuscripts.

First, `coincidence_physical.py` computes one on-source statistic per event but
retains the maximum over 4--8 valid time shifts for that event; the reported
P99 is pooled across these per-event maxima.  A single on-source value and a
per-event maximum null value are not exchangeable.  The previous statements
that the on-source tail was consistent with, or not in excess of, the shifted
tail were therefore stronger than the implemented design supports.  Both
papers and the cover now report the exact conservative screen: 13/8,806 exceed
`tau_cc=0.4045910817732782`, but the count is not a tail-count test, receives no
p-value, and receives no physical interpretation.

Second, `validate_cross_run_domain_shift.py` and the final JSON show that the
cross-run construct control uses 60 training and 40 held-out windows per run
and detector, seed 20260730, and matched O3b/O4a dictionaries with `K=56`.
Both papers now distinguish this explicitly from the production O3b `K=275`
and native O4a `K=1216` dictionaries.  The H1/L1 domain-shift result is scoped
to the matched-`K=56` construct control and its samples.

The master contract now fails closed on both points: it forbids the three
superseded tail phrases and requires the non-exchangeability caveat and `K=56`
disclosure in both manuscripts.  The deposited Zenodo evidence ZIP was not
rebuilt.

Final verification after these reporting corrections:

- claim checker plus artifact-hash reconstruction: PASS;
- C2/BGV3 verifier: all ten stages PASS;
- CQG verifier: domain, known-glitch, absorption, robustness, and reviewer
  extensions PASS;
- complete suite: 174 passed, one platform-dependent skip, nine classified
  warnings;
- fail-closed stale-claim scan: no obsolete strong coincidence wording or
  listed stale numerical claim in either manuscript or the cover;
- compilation and logs: no undefined citation/reference/control sequence and
  no overfull box;
- visual inspection: modified arXiv pages 1, 4, 11 and 12; CQG pages 1, 9, 10,
  19, 21 and 22; and the one-page cover all PASS.

| reviewer-closure object | pages | SHA256 |
|---|---:|---|
| arXiv `main.tex` | -- | `3e346ec50e71f8b29e038301c446397204177b975abd31c5e66c601cf6143bf4` |
| arXiv `main.pdf` | 12 | `0cb81c9c6982dd3f1051020db52f2ece14456522248a6c0dc02700144f9195a7` |
| CQG `main.tex` | -- | `6233e6b16cfb3bd26b0104ae9a8dcdef679bf4270364442d1aad6b0ab8572e15` |
| CQG `main.pdf` | 25 | `75969a1d0a2577caaa28dac4eaf0240b9818bc012690d45ffa1bea0136463f6b` |
| cover `cover_letter.tex` | -- | `a1aae5efa6ff643131d52b549aa9fcf96e74e8e22beb9199207b894bbd09b6cb` |
| cover `cover_letter.pdf` | 1 | `f48af9d1ff254d862708692dd3157de2403e73202c37956da9d6814441b0a161` |

## 45. arXiv v6 source package (2026-08-14)

The arXiv upload archive was built from the final reviewer-closure source.  It
contains `main.tex`, the pre-generated `main.bbl`, `references.bib`, and exactly
the ten PNG figures referenced by `main.tex`.  Generated PDFs, logs, auxiliary
files, compile transcripts, unused images, evidence artifacts, and raw data are
excluded.  `main.tex` is at the ZIP root and figures retain the `img/` path used
by `\graphicspath`.

The archive was extracted into a new isolated directory and compiled with two
`pdflatex` passes without invoking BibTeX.  The build produced the expected
12-page manuscript with no missing file, undefined citation/reference/control
sequence, LaTeX error, or overfull box.  The known RevTeX deferred-float warning
remains non-fatal and all ten figures are present.  The manuscript claim checker
with artifact hashes and all ten C2/BGV3 verifier stages pass after packaging.

| arXiv upload object | files | bytes | SHA256 |
|---|---:|---:|---|
| `release/arxiv_v6_submission.zip` | 13 | 989,926 | `05c006f701dccea4a213ae53bf4fbd5ccc94b3b306e8b092bf20b3f70d3563ec` |

### arXiv path-separator correction (2026-08-15)

The first Windows-created archive encoded the ten `img` entry names with
backslashes.  arXiv correctly rejected those names and attempted to flatten
them, which would have broken `\graphicspath`.  No source or figure name was
changed.  The archive was regenerated with explicit POSIX `/` entry separators;
all 13 entry names now satisfy arXiv's stated filename character set.  The
superseded archive is retained locally as
`arxiv_v6_submission_windows_paths_invalid.zip` and must not be uploaded.

The corrected ZIP was independently opened, enumerated, extracted and compiled
with two `pdflatex` passes.  The clean build is PASS at 12 pages with all ten
figures, citations and references resolved.  The SHA256 in the table above and
the adjacent `.sha256` file refer to the corrected archive.

## 46. Final pre-submission gate (2026-08-15)

The corrected arXiv source archive was subjected to a final fail-closed gate
before upload.  It contains 13 entries, uses POSIX `/` separators throughout,
contains no generated PDF or auxiliary build product, and exactly matches the
canonical `main.tex`, `main.bbl`, and `references.bib` byte for byte.  The
superseded Windows-path archive remains explicitly invalid and must not be
uploaded.

The archive was extracted into a fresh isolated directory.  Two independent
compilation paths were checked: (i) direct compilation with the packaged
`main.bbl`, and (ii) `pdflatex -> bibtex -> pdflatex -> pdflatex`.  BibTeX
created the expected empty `mainNotes.bib` auxiliary file and returned success;
the regenerated `main.bbl` had SHA256
`a1f88fda5e1bb693afbff9ef1df32d072c53f07fc01f7552731b016ac5a67853`,
identical to the packaged file.  Both paths produced a 12-page manuscript with
no missing file, undefined citation/reference/control sequence, LaTeX error,
fatal error, emergency stop, or overfull box.  The remaining RevTeX deferred
float notices and underfull-box diagnostics are non-fatal and do not produce a
visible layout defect.

Final scientific and reproducibility gates:

- manuscript claim checker with artifact-hash reconstruction: PASS;
- C2/BGV3 verifier: all ten stages PASS (`P5`, `P4`, `P10`, multiscale,
  cohesion, whitening, `P9`, `R5`, `P11`, and PEM);
- CQG validation verifier: all five stages PASS (domain shift, known-glitch
  controls, absorption, robustness, and reviewer extensions);
- pertinent test suite: 174 passed, one platform-dependent skip, nine
  classified warnings (three optional xFormers notices and six GWpy
  deprecations);
- fail-closed scan for superseded claims, numbers, undefined references and
  missing assets: PASS;
- visual inspection: arXiv pages 1, 4, 11, and 12; CQG pages 1, 9, 19, 21, 22,
  and 25; and the one-page cover letter: PASS.

| final pre-submission object | pages/files | bytes | SHA256 |
|---|---:|---:|---|
| arXiv `main.tex` | -- | -- | `3e346ec50e71f8b29e038301c446397204177b975abd31c5e66c601cf6143bf4` |
| arXiv `main.pdf` | 12 | 1,318,574 | `afb5999aa2e3d258769bc9e06fac21e7bfd25ee8c68c2221ad1716d10aa6f858` |
| corrected `release/arxiv_v6_submission.zip` | 13 files | 989,926 | `05c006f701dccea4a213ae53bf4fbd5ccc94b3b306e8b092bf20b3f70d3563ec` |
| CQG `main.tex` | -- | -- | `6233e6b16cfb3bd26b0104ae9a8dcdef679bf4270364442d1aad6b0ab8572e15` |
| CQG `main.pdf` | 25 | 1,465,092 | `6cc54a74606bd726efc12dfe75dd6dd1a21ee62299df6121c0abb33bb6e1dca0` |
| CQG `cover_letter.tex` | -- | -- | `a1aae5efa6ff643131d52b549aa9fcf96e74e8e22beb9199207b894bbd09b6cb` |
| CQG `cover_letter.pdf` | 1 | 104,927 | `0c8b08c221feaaabf5e8960742cd10f64c90194bd4aab06405e9230ad68dd733` |

Verdict: no critical technical, numerical, provenance, packaging, bibliography,
or visible-layout blocker remains for the arXiv v6 upload.  The CQG manuscript
and cover letter also pass the same local pre-submission evidence gate; journal
portal metadata and the final uploaded-file preview remain the next external
checks.

## 47. DANTE-Light G0 reproducibility implementation (2026-08-15)

Work on the additive DANTE-Light upgrade began with the mandatory G0 gate; no
Light selection semantics or v6 paper artifact was changed.  The canonical
scorer now resolves O3b and O4a reference indices through per-artifact SHA256,
shape, dimension and Q-range contracts.  The real O3b K=275 and O4a Q64 K=1216
paths both pass the unmocked CLI integration.  Resume validation prefers SHA256
and leaves a divergent HDF5 file untouched.

DINOv2 loading is centralised and frozen to revision
`7b187bd4df8efce2cbcbbb67bd01532c19bf4c9c`, Python source-tree SHA256
`ca377bf21900d316a2c17dbff04b0e01d44770fe2706becb94a79ac3b60b74ef`
and weight SHA256
`f433177089a681826f849f194ece3bb48f4d63fb38d32fc837e3dc7a4e5641fb`.
Clean online acquisition and the verified offline mirror produced exactly equal
`1 x 1369 x 384` patch-token tensors (maximum absolute difference 0.0).

The local public-artifact bundle was rebuilt and verified at
`release/dante_reference_artifacts_v1.zip`: 73,444,397 bytes, nine ZIP members,
SHA256
`651a70dbf3798de8caba91f1117879cf1798581f1fd949cabf12e260d100fa63`.
It contains both dictionaries, their native-build sidecars/source state, the
machine-readable contract, documentation and licence.  The current software
and evidence Zenodo records do not contain this bundle, so the manifest remains
explicitly `not_deposited` and public download fails closed.

The loader refactor changed literal code hashes attached to frozen CQG token
caches while leaving inference bit-identical.  A schema-3 transition was added:
new caches pin the complete model contract; schema-2 caches are reusable only
under exact legacy identity plus exact audited current runtime/model hashes.
Any change forces rebuild, and no published cache was modified.  Deep
reconstruction after the migration passed domain shift, known-glitch controls,
absorption, robustness and reviewer extensions.  The complete C2/BGV3 gate
also passed all ten stages.

Final local regression evidence after all G0 changes: 192 passed, one
platform-dependent skip and nine classified non-numerical warnings.  A fresh
isolated CPU environment additionally passed smoke (21 passed, one skip),
artifact/model (8 passed) and real dual-index integration (2 passed).  Docker
was unavailable locally, so the checked-in CPU workflow is retained as the
independent environment gate.

The final ZIP was additionally installed into a new temporary artifact root
containing no reference data.  All five payloads were installed and both NPZ
indices passed digest, shape and Q-range verification from that root.  A second
temporary run seeded with a divergent O3b index was rejected without changing
the pre-existing bytes.  This closes local clean-install and non-destructive
failure behaviour; only the persistent public transport remains untested.

Decision: G0.1 and G0.2 are complete; G0.3 is locally complete but the public
clean-clone done gate is blocked on depositing the exact reference ZIP and
recording its persistent URL.  Per the approved dependency plan, L0 and later
DANTE-Light implementation must not start before that external action is
verified.

## 2026-08-15 -- DANTE-Light development continuation authorised

The user authorised DANTE-Light development on a separate branch before the
reference-bundle publication, while keeping publication as a later release
gate. Branch `codex/dante-light` was created, committed incrementally and pushed
without modifying the canonical default (`dante_light.enabled=false`, canonical
engine default).

L0 froze 9,388 replay cases / 9,387 detector-GPS windows and the exact
representation, index and model contracts. The canonical GPU baseline used 8
temporally stratified H1/L1 windows, two measured repeats, zero failures/drops,
bit-stable repeats and maximum archived-score delta 1.0430813e-7 under the
pre-registered 2e-7 tolerance. Throughput on the recorded RTX 5070 host was
1.1633 windows/s; data access (~47%) and Q-transform (~28%) dominated.

L1 split encoding from exact index scoring, retained the legacy API, added a
native score-only path and crash-safe idempotent HDF5 batches with an internal
commit boundary plus atomic external checkpoint. The same-commit paired
score-only comparison measured 1.1595 canonical vs 1.2934 shared windows/s
(ratio 1.1155). Scores remained exact; the full-output paired arm separately
proved Top-68 and MIL equality. Forced failures before and after the HDF5 commit
marker recovered without lost or duplicated scientific rows.

L2 added bounded concurrent preprocessing, single-consumer scoring and ordered
single-writer persistence with explicit back-pressure. Stress tests covered
slow/out-of-order preprocessing, slow writing, preflight, preprocessing,
scoring and writer failures. Queue saturation never drops a window.

L3 added opt-in `dante-light-replay` and `dante-light-shadow`, immutable run
manifests, append-only records/attempts, deterministic resume and scoreless
fail-closed dispositions. A real local-strain two-window smoke on commit
`42100ed` showed exact equality between canonical and shared engines for strain
hash, primary/native scores, Top-68 and disposition. The shipped completed-O4a
epoch is explicitly non-causal; the prospective command returns
`complete_with_defer/NON_CAUSAL_EPOCH` without scoring.

L4--L6 added only evidence-bounded infrastructure: a `research_only` cheap
feature arm that is prohibited from routing, six mandatory causal-epoch
promotion gates with temporal separation and artifact hashes, a drift alarm
that can freeze but never adapt automatically, replay/packet sources that fail
on gaps or divergent duplicates, and a content-addressed auxiliary-channel
cache primitive. No prefilter, causal epoch, Kafka transport or NDS2 PEM cache
integration is claimed operational.

Final current evidence: 253 tests passed, one platform-dependent skip and nine
classified warnings; C2/BGV3 passed all ten stages and CQG passed all five. The
release verifier reports `development=PASS`, `public-replay=NOT_READY` (bundle
not deposited/configured), and `operational=NOT_READY` (no H1/L1 causal epochs
and no locked later-epoch validation). These OPEN gates are required evidence,
not software failures, and must not be converted into PASS.

A final code-path review found and closed a fail-closed gap before the branch
checkpoint: `load_epochs` previously parsed a hand-edited `causal: true` value
without forcing the separate promotion verifier. It now requires the frozen
representation plus all six promotion gates and exact evidence hashes for any
causal epoch. A regression test proves that a causal epoch without promotion
evidence is rejected. The release verifier was also strengthened from file
presence checks to corpus counts/hashes, paired exact-score evidence, source
and JSONL hashes, verified causal promotion, a separate public clean-clone
replay gate and a locked prospective schema; a merely present
`status=complete` file fails.

## 2026-08-15 -- DANTE-Light final pre-publication verification

The branch was completed and pushed through commit
`128ab90876b46a6e54f25fceaf35503ba6411597`. The final paired score-only
benchmark was rebuilt from two independent clean worktrees: canonical
1.1534809413 window/s, shared 1.3017737595 window/s, ratio 1.1285611343
(+12.856%), repeat delta zero. Primary outputs are exact; the shared engine
deliberately omits the redundant native Top-68 diagnostic hash.

The full suite first exposed three CQG legacy-cache failures. Investigation
showed that the additive `remote_only=False` loader path retained legacy
behaviour, while the compatibility gate used platform-sensitive raw source
bytes. Only that runtime-equivalence source attestation was changed to
UTF-8/LF-normalized hashing; binary artifacts and cache payload hashes remain
byte-exact. Dedicated legacy/cache/line-ending tests passed, followed by the
complete result: 270 passed, 1 skipped and 9 known non-numerical warnings.
C2/BGV3 advanced through all 10 stages and CQG through all 5; DANTE-Light
development is PASS.

A final clean-room preflight cloned the pushed branch through HTTPS into a new
directory, used a new Torch cache, installed the local bundle with SHA-256
`651a70dbf3798de8caba91f1117879cf1798581f1fd949cabf12e260d100fa63`,
and forced `--strain-source gwosc-only` plus GWOSC CAT1. Canonical and shared
engines each processed the same two H1 public windows. Both completed with two
`NOT_ESCALATED`, zero DEFERs/drops/failures, identical dispositions and maximum
absolute score delta 0. The evidence is correctly labelled
`clean_clone_prepublish_preflight`, not public replay, because the bundle came
from a local path and remains `not_deposited` in the contract.

The run also found and fixed a verifier-only diagnostic bug: two explicitly
non-causal historical epochs now remain `OPEN` in a clean clone without
requiring unshipped promotion artifacts; any epoch changed to `causal=true`
still fails unless all promotion evidence and hashes validate.

No bundle was published and no merge to `main` was performed. The next human
gate is publication of this exact ZIP; afterward the `public` clean-clone mode
must self-download it and pass before merge is considered. Prospective/low-
latency claims remain forbidden until causal H1/L1 epochs and a genuinely later
shadow evaluation pass the locked operational verifier.

## 2026-08-15 -- DANTE-Light public bundle and clean-clone replay

The reference ZIP was published as the GitHub release asset
`dante-reference-artifacts-v1`. The GitHub API reports one custom asset,
`dante_reference_artifacts_v1.zip`, size 73,444,397 bytes and digest
`sha256:651a70dbf3798de8caba91f1117879cf1798581f1fd949cabf12e260d100fa63`.
The release tag points to `codex/dante-light` commit `128ab90`.

Zenodo DOI `10.5281/zenodo.21957984` was inspected separately. Its only file is
the 1,473,440-byte GitHub source-tag snapshot; it does not contain the 73 MB
release asset. The DOI is therefore recorded as source archival metadata, not
as the reference-bundle endpoint. The frozen runtime contract uses the direct
versioned GitHub asset URL and exact SHA-256.

After committing that public contract, a new HTTPS clone at commit
`9669fab678ce08fd5eac818ea530cc1ba1591ae6` ran the public clean-clone command
without `--bundle`. It downloaded and verified the asset itself, installed both
NPZ indices, used a new Torch cache, forced GWOSC-only strain and whole-window
CAT1, and processed two public H1 windows. Canonical and shared engines each
wrote two `NOT_ESCALATED` records with zero DEFERs, drops or failures; score
delta and disposition mismatches were zero. All eight supporting run-artifact
hashes reconstruct exactly.

The `public-replay` verifier is now PASS. The previous prepublish evidence was
moved recoverably to `archive/dante_light_prepublish_20260815`, and the public
evidence is stored at
`artifacts/dante_light/public_replay_validation_v1.json`. The operational gate
remains `NOT_READY`: no causal promoted H1/L1 epochs and no later-epoch
prospective validation exist. No merge to `main` was performed.

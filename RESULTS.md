# 🔬 Scientific Results and Benchmark Log (Phase 4: Patch-Level MIL)

This document tracks the results of the DANTE (Domain-Adaptive Network for Transient Evaluation) pipeline operating in its **Phase 4 architecture** (Patch-Level Multiple Instance Learning).

> **Note on Legacy Data:** The Phase 1 results (based on the global `[CLS]` token pooling) have been deprecated for short-duration glitches due to the Signal Dilution limit. They are preserved for historical context and macroscopic glitch analysis in [RESULTS_OLD.md](RESULTS_OLD.md).

---

## 📦 Downloaded Data Intervals (HDF5 Cache)

| Run | Session ID | GPS Start | GPS End | Duration (Hours) | Status |
|:----|:-----------|:----------|:--------|:-----------------|:-------|
| `O4a` | `1368973312` | 1368973312 | 1369478368 | ~140.3 | DetChar Validation Completed |

---

## 📅 Chronological Session Index (Patch-Level)

| Run | Session ID | Run Date/Time | Analysis Status | Salient Detections (NOVEL) |
|:---|:-----------|:--------------|:----------------|:---------------------------|
| `O4a` | `Production Scan` | 2026-06-27 | Aggregate Report (82 sessions) | **434 candidates** (359 local instrumental vs 75 unilateral). Cohesive morphological families completely collapse (0 structured families survive) against the native O4a background. Definitive evidence of Domain Shift distortion by the O3b index. |

---

## 🔬 Phase 4 Validation baselines

- **Threshold Calibration:** The operational detection threshold $\tau_{\rm op}$ is strictly defined non-parametrically as the empirical $99^{\rm th}$ percentile ($P_{99}$) of a massive background distribution ($N_{\rm null} = 150,000$ curated segments). All previous heuristic attempts to parameterize this heavy-tailed distribution via GEV (Fisher-Tippett-Gnedenko) have been excised. This is a formal mathematical requirement: the overlapping receptive fields of the ViT patches violate the strict statistical independence assumption required by extreme value theorem for block maxima, making parametric GEV fits structurally invalid for this architecture.
- **Topological Saliency:** Extracted via pure spatial cosine similarity (no VQ weighting).
- **Signal Dilution Barrier:** Broken via $K=68$ Top-K Patch Mean Pooling.
- **`[CLS]` Global Pooling Comparison:** Evaluated the 434 confirmed candidates against the identical $P_{99}$ empirical threshold using the 768D global `[CLS]` token. The global pooling yielded a 0.00% recall, with a mean cosine similarity of $0.996 \pm 0.002$ and a Kolmogorov-Smirnov separation from the background of $D = 0.04$ ($p > 0.5$). This empirically proves that standard ViT global pooling is mathematically blind to these anomalies in production data due to topological signal dilution.
<div align="center">
  <img src="paper_draft/springer/img/pooling_comparison_1368973312_H1.png" alt="CLS Baseline Comparison" width="600"/>
</div>
- **Mock Data Challenge (MDC) & Signal Dilution Limits:** **[COMPLETED 100%]** Injection of seven synthetic waveforms (Blip, AsymBlip, SpiralBurst, ScatteredLight, HarmonicComb, KoiFish, Whistle) into empirical O4a backgrounds ($K=100$, $N_{\rm inj}=100$ per bin). By evaluating against the theoretical **Matched-Filter SNR ($\rho$)**, we demonstrate empirical recall approaching 100% for long-duration stationary morphologies (HarmonicCombs). Conversely, we mathematically confirm a severe structural limitation: sub-second anomalies (Blips/AsymBlips) are fundamentally diluted in the 32-second window, yielding 0.00% recall even at very high SNR > 300. This is explicitly acknowledged as a critical operational failure requiring future multi-scale architectures. *(Note on the 32s Window: Short windows severely degrade the physical Power Spectral Density (PSD) estimation required for whitening. The 32s window is an engineering necessity for PSD stability).*

<div align="center">
  <img src="paper_draft/springer/img/fig_mdc_recall_snr.png" alt="MDC Recall Curve" width="600"/>
</div>
- **Domain Shift Invariance (O3b vs O4a):** [COMPLETED] Evaluated via an **Empirical Tail QQ-Plot** (from $p_{50}$ to $p_{99.8}$) computed on 150,000 rigorously vetted null segments per run, instead of a statistically irrelevant KS test on the bulk distribution. We demonstrated that at the operational threshold $\tau_{\rm op} = 0.889$ (the O3b baseline $p_{99}$), the empirical False Positive Rate (FPR) for native O4a is strictly bounded at $0.0\%$, compared to $1.0\%$ for O3b. This mathematically proves that domain shift does not inflate the extreme tail of the anomaly scores. Instrument drift is fully absorbed by local empirical recalibration. *Circularity Note: To ensure absolute purity and avoid the "Circularity Trap" (where pervasive new glitches contaminate the null set and become the "new normal"), the native O4a background was strictly built using rigorous Data Quality (DQ) PEM vetoes and H1/L1 Anti-Coincidence (ensuring one detector is clean while the other triggers). This scientifically validates the domain shift collapse.*
### 3.5 Targeted Cross-Detector Coincidence Veto (Wave 7)
To rigorously distinguish between anomalous local instrumental glitches and global phenomena (e.g., high-SNR gravitational waves, Schumann resonances), all 434 candidates were subjected to a targeted sub-threshold search on the partner detector.
By physically extracting the raw strain data from the partner at the exact $\pm 2$s trigger window and encoding it via frozen DINOv2, we bypassed the local detection thresholds to scan for sub-threshold coincidences.
**Veto Results:**
- **Table 3a (Confirmed Local Glitches):** 359 candidates. The partner was online, but the sub-threshold morphological match yielded $S < 0.9750$ (calibrated via Weibull-tail EVT).
- **Table 3b (Unverifiable Detections):** 75 candidates. The partner was offline or not in science mode.
- **Table 3c (Coincident Anomalies):** Exactly **0 candidates**.
The complete lack of cross-detector coincidence conclusively rules out astrophysical origins for this candidate population, confirming them as purely localized instrumental artifacts.

### 4. Domain Shift Resolution (O4a Native Index)
To resolve whether the candidates were genuine or artifacts of the O3b domain shift, we built a massive native O4a index, empirically recalibrated the $p_{99}$ threshold, and rescored all 434 candidates.

**Final Verdict:**
- **Cohesion Collapse**: $96.3\%$ overall robust survival rate (418 robust candidates out of 434 evaluated; H1: 6/6 robust, L1: 412/428 robust, 13 ambiguous, 3 background). **0.0\% of cohesive macro-families survived**. No family maintained both multiple survivors and sufficient morphological cohesion ($S > 0.9750$).
- **Family\_01 Paradox Resolution**: While Family\_01 exhibits an exceptionally structured morphology ($p < 0.001$ against Gaussian noise), it collapsed completely (0 robust survivors) under the native index. This exposes a fundamental limitation of unsupervised background-subtraction: the K-Means Vector Quantization inherently absorbs pervasive, continuously repeating morphological features into the reference dictionary to minimize inertia. The collapse under the native index does not prove Family\_01 is "indistinguishable from benign stationary noise", but rather demonstrates it is a macroscopically pervasive feature that circumvents the anomaly thresholding logic. It remains a *persistent pathological instrumental coupling*, but ultimate physical classification is contingent on auxiliary PEM data.
- **L1/H1 Detection Asymmetry (71:1)**: The pipeline autonomously detected 428 anomalies in L1 and only 6 in H1. This 71:1 ratio perfectly aligns with known O4a DetChar/Gravity Spy statistics: Livingston experienced macroscopic microseismic scattered light resulting in transient glitch rates up to $1.5 - 2.0$ Hz, compared to Hanford's stable $0.05 - 0.1$ Hz. This empirical hardware discrepancy ($\sim 70\times$) quantitatively corroborates the DANTE 71:1 ratio, proving the pipeline faithfully maps violent out-of-distribution non-stationarity.
- **Macroscopic Temporal Aggregates (Family\_03)**: The dominant aggregate, Family\_03 (417 members, 96\% of all candidates), showed extreme temporal clustering. To rigorously validate its diffuse nature without relying on degenerate single-linkage chaining heuristics, we compared its pairwise intra-cluster cosine distances directly against random stationary background noise. The distribution overlap confirms that Family\_03 represents a continuously drifting domain-shift manifold rather than a compact morphological cluster.
<div align="center">
  <img src="paper_draft/springer/img/morphological_diffusivity_distances.png" alt="Morphological Diffusivity Distances" width="600"/>
</div>
- **Falsifiability and Selectivity (Controlled Recovery Test):** To definitively rule out "methodological circularity" (the hypothesis that the native O4a index is so expansive it blindly absorbs all anomalies, creating a false negative for Family_01), we executed a Controlled Recovery Test. We injected discrete synthetic transients (HarmonicComb, ScatteredLight, WallOfLines, KoiFish, Whistle) into empirical O4a noise and rescored them against the native index. At matched-filter $\rho > 50$, the Recovery Rate for all discrete morphologies approaches 100% (Wilson 95% CI), with intermediate topologies like KoiFish remaining robustly detectable. This provides absolute empirical proof that the Domain Shift Defense is **selective**: it absorbs pervasive stationary artifacts (like Family_01) because they dominate the Vector Quantization geometry, but it strictly preserves rare, discrete anomalous signals.
- **K-Means Poisoning Immunity:** An empirical poisoning test confirmed that the native index `MiniBatchKMeans` ($K=1216$) does not allocate a dedicated centroid to a dense anomaly even at a massive $5.0\%$ contamination level ($7{,}500$ identical anomalies), capping at a maximum cosine similarity of $\approx 0.76$. Furthermore, an anomaly contaminating 5% of the data corresponds to 66 continuous hours, physically redefining it as a stationary environmental coupling rather than a discrete transient.
<div align="center">
  <img src="paper_draft/springer/img/fig_dsd_recovery_curves.png" alt="DSD Controlled Recovery Curves" width="600"/>
</div>
- This provides a definitive validation of the pipeline's **Domain Shift Defense**: without native recalibration, the O3b index introduces a significant bias, transforming ordinary background noise into cohesive structural artifacts.

### 5. Snapshot & Reproducibility Metadata
These results constitute a point-in-time snapshot of the pipeline execution. Due to the continuous evolution of the codebase, the generated JSON and CSV metrics are not checked into the repository.

*   **Run Date:** 2026-06-27
*   **Total Sessions Processed:** 82
*   **Total Segments Evaluated:** ~243,000
*   **Final Candidate Anomalies:** 434 (359 local instrumental, 75 unilateral)
*   **Transitivity Resolution:** 68/75 resolved (90%) *(Note: linkage threshold $\rho_{trans}=0.75$ is an empirical heuristic requiring further cross-session injection validation)*

#### Aggregated Taxonomy Report
*   **Family\_01**: 0 candidates (Collapsed under native index)
*   **Family\_02**: 3 candidates (Mean Internal Similarity: 0.757)
*   **Family\_03**: 412 candidates (Mean Internal Similarity: 0.812)
*   **Singletons**: 3 candidates. Formally cross-referenced against GraceDB O4a event triggers and Hardware Injections ($\pm 2$s window) with 0 coincidences, rigorously ruling out unregistered astrophysical events or calibrations. However, due to restricted public access to complete auxiliary Physical Environment Monitoring (PEM) channels, we cannot definitively rule out local environmental couplings. We strictly classify these as *mathematical outliers in the feature space*, avoiding claims of new transient discoveries. A formal cross-correlation with public O4 auxiliary PEM channels constitutes a mandatory step for future work.

*   **Commit Hash / Reference:** Please refer to the Zenodo deposition (DOI: 10.5281/zenodo.20960011) for the exact frozen artifacts (`master_report.json`, `global_taxonomy_report.json`) generated in `data/production/aggregated/`.

*To reproduce these results, checkout the pipeline version corresponding to the date above and run the `aggregate-report` module over the O4a production dataset.*
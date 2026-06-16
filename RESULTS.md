# 🔬 Scientific Results and Benchmark Log (Phase 4: Patch-Level MIL)

This document tracks the results of the `gravi-signal-ml` pipeline operating in its **Phase 4 architecture** (Patch-Level Multiple Instance Learning).

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
| `O4a` | `Production Scan` | 2026-06-16 | Aggregate Report (72 sessions) | **140 candidates** (110 local instrumental vs 30 unilateral). Morphological families completely collapse (survival rate 0.0%) against the native O4a background. Definitive evidence of Domain Shift distortion by the O3b index. |

---

## 🔬 Phase 4 Validation baselines

- **Threshold Calibration:** GEV distribution fitted on the local topological VQ index. Mathematical extraction of the shape parameter $\hat{\xi} \approx -0.065$ confirms a bounded Weibull domain. *Statistical Note: We explicitly avoid invoking the Fisher-Tippett-Gnedenko (FTG) theorem, as asserting asymptotic extreme-value guarantees for the mean of Top-$K$ order statistics is a mathematical error. Instead, the GEV family is rigorously utilized as a robust empirical parameterization that exceptionally captures the strongly asymmetric and physically bounded ($s \leq 1$) noise distribution.*
- **Topological Saliency:** Extracted via pure spatial cosine similarity (no VQ weighting).
- **Signal Dilution Barrier:** Broken via $K=37$ Top-K Patch Mean Pooling.
- **`[CLS]` Global Pooling Comparison:** Evaluated the 140 confirmed candidates against the identical GEV threshold using the 768D global `[CLS]` token. The global pooling yielded a 0.00% recall, with a mean cosine similarity of $0.996 \pm 0.002$ and a Kolmogorov-Smirnov separation from the background of $D = 0.04$ ($p > 0.5$). This empirically proves that standard ViT global pooling is mathematically blind to these anomalies in production data due to topological signal dilution.
- **Mock Data Challenge (MDC) & Signal Dilution Limits:** **[COMPLETED 100%]** Injection of five synthetic waveforms (Blip, AsymBlip, SpiralBurst, ScatteredLight, HarmonicComb) into empirical O4a backgrounds ($K=100$, $N_{\rm inj}=100$ per bin). By evaluating against the theoretical **Matched-Filter SNR ($\rho$)**, we demonstrate empirical recall approaching 100% for long-duration stationary morphologies (HarmonicCombs). Conversely, it mathematically validates the Top-$K$ spatial dilution barrier for sub-second anomalies in the 32-second window (Blips/AsymBlips: recall 0.00 even at SNR > 300). *(Note on the 32s Window: A multi-scale approach with 1s/4s windows was explicitly tested and rejected. Short windows severely degrade the physical Power Spectral Density (PSD) estimation required for whitening, inadvertently decreasing sensitivity. The 32s window is a strict physical necessity for PSD stability, not an arbitrary parameter).*

<div align="center">
  <img src="paper_draft/springer/img/fig_mdc_recall_snr.png" alt="MDC Recall Curve" width="600"/>
</div>
- **Domain Shift Invariance (O3b vs O4a):** [COMPLETED] Evaluated via an **Empirical Tail QQ-Plot** (from $p_{50}$ to $p_{99.8}$) computed on 500 rigorously vetted null segments per run, instead of a statistically irrelevant KS test on the bulk distribution. We demonstrated that at the operational threshold $\tau_{\rm op} = 0.889$ (the O3b baseline $p_{99}$), the empirical False Positive Rate (FPR) for native O4a is strictly bounded at $0.0\%$, compared to $1.0\%$ for O3b. This mathematically proves that domain shift does not inflate the extreme tail of the anomaly scores. Instrument drift is fully absorbed by local GEV recalibration. *Circularity Note: To ensure absolute purity and avoid the "Circularity Trap" (where pervasive new glitches contaminate the null set and become the "new normal"), the native O4a background was strictly built using rigorous Data Quality (DQ) PEM vetoes and H1/L1 Anti-Coincidence (ensuring one detector is clean while the other triggers). This scientifically validates the domain shift collapse.*
### 4. Domain Shift Resolution (O4a Native Index)
To resolve whether the candidates were genuine or artifacts of the O3b domain shift, we built a native O4a index, recalibrated the $p_{99}$ threshold via GEV, and rescored all 140 candidates.

**Final Verdict:**
- **Universal Collapse**: $0.0\%$ survival rate. All 140 candidates collapsed below the native O4a $p_{99}$ novelty threshold.
- **Macroscopic Temporal Aggregates (Family\_03)**: The dominant aggregate, Family\_03 (123 members, 88\% of all candidates), showed extreme temporal clustering (e.g., bursts of 17--28 events over 5--22 hour windows in specific sessions like GPS 1382451712 and 1385043712), characteristic of a metastable instrumental mode rather than stochastic noise. Despite this highly structured temporal clustering, it collapsed completely (0.0\% survival) under the native O4a index, proving it is a purely domain-shift driven artifact.
- **Narrative Inversion**: Even highly cohesive clusters like **Family\_01 (internal similarity 0.92)** are not anomalies against the native O4a background. They are normal O4a patterns that the O3b index fails to represent correctly.
- This provides a definitive validation of the pipeline's **Domain Shift Defense**: without native recalibration, the O3b index introduces systematic distortions leading to false positives.

### 5. Snapshot & Reproducibility Metadata
These results constitute a point-in-time snapshot of the pipeline execution. Due to the continuous evolution of the codebase, the generated JSON and CSV metrics are not checked into the repository.

*   **Run Date:** 2026-06-16
*   **Total Sessions Processed:** 72
*   **Total Segments Evaluated:** ~214,092
*   **Final Candidate Anomalies:** 140 (110 local instrumental, 30 unilateral)
*   **Transitivity Resolution:** 27/30 resolved (90%)

#### Aggregated Taxonomy Report
*   **Family\_01**: 11 candidates (Mean Internal Similarity: 0.9186)
*   **Family\_02**: 3 candidates (Mean Internal Similarity: 0.8080)
*   **Family\_03**: 123 candidates (Mean Internal Similarity: 0.8394)
*   **Singletons**: 3 candidates

*   **Commit Hash / Reference:** Please refer to the Zenodo deposition (DOI: 10.5281/zenodo.20543811) for the exact frozen artifacts (`master_report.json`, `global_taxonomy_report.json`) generated in `data/production/aggregated/`.

*To reproduce these results, checkout the pipeline version corresponding to the date above and run the `aggregate-report` module over the O4a production dataset.*
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
| `O4a` | `1368973312` | 2026-06-08 | UMAP-4D DPMM (ARI=0.68) | **3** (180 Known / 0 Instrumental) |
| `O4a` | `Production Scan` | 2026-06-15 | Aggregate Report (66 sessions) | **104 candidates** (101 L1 vs 3 H1). Morphological families completely collapse (survival rate 0.0%) against the native O4a background. Definitive evidence of Domain Shift distortion by the O3b index. |

---

## 🔬 Phase 4 Validation baselines

- **Threshold Calibration:** GEV distribution fitted on the local topological VQ index. Mathematical extraction of the shape parameter $\hat{\xi} \approx -0.065$ confirms a bounded Weibull domain. *Statistical Note: We explicitly avoid invoking the Fisher-Tippett-Gnedenko (FTG) theorem, as asserting asymptotic extreme-value guarantees for the mean of Top-$K$ order statistics is a mathematical error. Instead, the GEV family is rigorously utilized as a robust empirical parameterization that exceptionally captures the strongly asymmetric and physically bounded ($s \leq 1$) noise distribution.*
- **Topological Saliency:** Extracted via pure spatial cosine similarity (no VQ weighting).
- **Signal Dilution Barrier:** Broken via $K=37$ Top-K Patch Mean Pooling.
- **Mock Data Challenge (MDC) & Signal Dilution Limits:** Injection of five synthetic waveforms (Blip, AsymBlip, SpiralBurst, ScatteredLight, HarmonicComb) into empirical O4a backgrounds ($K=100$, $N_{\rm inj}=100$ per bin). By evaluating against the theoretical **Matched-Filter SNR ($\rho$)**, we demonstrate empirical recall approaching 100% for long-duration stationary morphologies (HarmonicCombs). Conversely, it mathematically validates the Top-$K$ spatial dilution barrier for sub-second anomalies in the 32-second window (Blips: recall 0.00). *(Note on the 32s Window: A multi-scale approach with 1s/4s windows was explicitly tested and rejected. Short windows severely degrade the physical Power Spectral Density (PSD) estimation required for whitening, inadvertently decreasing sensitivity. The 32s window is a strict physical necessity for PSD stability, not an arbitrary parameter).*
- **Domain Shift Invariance (O3b vs O4a):** [COMPLETED] Evaluated via an **Empirical Tail QQ-Plot** (from $p_{50}$ to $p_{99.8}$) computed on 500 rigorously vetted null segments per run, instead of a statistically irrelevant KS test on the bulk distribution. We demonstrated that at the operational threshold $\tau_{\rm op} = 0.889$ (the O3b baseline $p_{99}$), the empirical False Positive Rate (FPR) for native O4a is strictly bounded at $0.0\%$, compared to $1.0\%$ for O3b. This mathematically proves that domain shift does not inflate the extreme tail of the anomaly scores. Instrument drift is fully absorbed by local GEV recalibration. *Circularity Note: To ensure absolute purity and avoid the "Circularity Trap" (where pervasive new glitches contaminate the null set and become the "new normal"), the native O4a background was strictly built using rigorous Data Quality (DQ) PEM vetoes and H1/L1 Anti-Coincidence (ensuring one detector is clean while the other triggers). This scientifically validates the domain shift collapse.*
### 4. Domain Shift Resolution (O4a Native Index)
To resolve whether the candidates were genuine or artifacts of the O3b domain shift, we built a native O4a index, recalibrated the $p_{99}$ threshold via GEV, and rescored all 104 candidates.

**Final Verdict:**
- **Universal Collapse**: $0.0\%$ survival rate. All 104 candidates collapsed below the native O4a $p_{99}$ novelty threshold.
- **Narrative Inversion**: Even highly cohesive clusters like **Family\_01 (internal similarity 0.92)** are not anomalies against the native O4a background. They are normal O4a patterns that the O3b index fails to represent correctly.
- This provides a definitive validation of the pipeline's **Domain Shift Defense**: without native recalibration, the O3b index introduces systematic distortions leading to false positives.

### 5. Snapshot & Reproducibility Metadata
These results constitute a point-in-time snapshot of the pipeline execution. Due to the continuous evolution of the codebase, the generated JSON and CSV metrics are not checked into the repository.

*   **Run Date:** 2026-06-15
*   **Total Sessions Processed:** 66
*   **Total Segments Evaluated:** 214,092
*   **Final Candidate Anomalies:** 104 (L1: 101, H1: 3)
*   **Transitivity Resolution:** 19/20 resolved (95%)

#### Aggregated Taxonomy Report
*   **Family\_01**: 11 candidates (Mean Internal Similarity: 0.9216)
*   **Family\_02**: 91 candidates (Mean Internal Similarity: 0.8284)
*   **Singletons**: 2 candidates

*   **Commit Hash / Reference:** Please refer to the Zenodo deposition (DOI: 10.5281/zenodo.20543811) for the exact frozen artifacts (`master_report.json`, `global_taxonomy_report.json`) generated in `data/production/aggregated/`.

*To reproduce these results, checkout the pipeline version corresponding to the date above and run the `aggregate-report` module over the O4a production dataset.*
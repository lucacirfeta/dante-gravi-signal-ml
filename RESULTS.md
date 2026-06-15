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

- **Threshold Calibration:** GEV distribution fitted on the local topological VQ index. Mathematical extraction of the shape parameter $\hat{\xi} \approx -0.065$ confirms a bounded Weibull domain, avoiding heuristic assumptions of infinite heavy tails.
- **Topological Saliency:** Extracted via pure spatial cosine similarity (no VQ weighting).
- **Signal Dilution Barrier:** Broken via $K=37$ Top-K Patch Mean Pooling.
- **Domain Shift Invariance (O3b vs O4a):** [COMPLETED] 2-sample KS test on 4096s of pure background from O3b vs O4a using frozen ViT-S/14 patch-level similarities. Mean shift: +0.0047 (0.58\%). KS Test (sub N=5000): $D=0.0352$, $p=0.004$. Instrument drift is fully absorbed by local GEV recalibration.
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
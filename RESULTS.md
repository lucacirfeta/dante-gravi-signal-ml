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

---

## 🔬 Phase 4 Validation baselines

- **Threshold Calibration:** GEV distribution fitted on the local topological VQ index.
- **Topological Saliency:** Extracted via pure spatial cosine similarity (no VQ weighting).
- **Signal Dilution Barrier:** Broken via $K=37$ Top-K Patch Mean Pooling.
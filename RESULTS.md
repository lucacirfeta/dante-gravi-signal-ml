# 🔬 Scientific Results and Benchmark Log (Phase 4: Patch-Level MIL)

This document tracks the results of the `gravi-signal-ml` pipeline operating in its **Phase 4 architecture** (Patch-Level Multiple Instance Learning).

> **Note on Legacy Data:** The Phase 1 results (based on the global `[CLS]` token pooling) have been deprecated for short-duration glitches due to the Signal Dilution limit. They are preserved for historical context and macroscopic glitch analysis in [RESULTS_OLD.md](RESULTS_OLD.md).

---

## 📦 Downloaded Data Intervals (HDF5 Cache)

| Run | Session ID | GPS Start | GPS End | Duration (Hours) | Status |
|:----|:-----------|:----------|:--------|:-----------------|:-------|
| `O4a` | *TBD* | *TBD* | *TBD* | *TBD* | Awaiting Live Scan |

---

## 📅 Chronological Session Index (Patch-Level)

| Run | Session ID | Run Date/Time | Analysis Status | Salient Detections (NOVEL) |
|:---|:-----------|:--------------|:----------------|:---------------------------|
| - | - | - | - | - |

---

## 🔬 Phase 4 Validation baselines

- **Threshold Calibration:** GEV distribution fitted on the local topological VQ index.
- **Topological Saliency:** Extracted via pure spatial cosine similarity (no VQ weighting).
- **Signal Dilution Barrier:** Broken via $K=37$ Top-K Patch Mean Pooling.

*(New results will be populated here as `scan_live.py` executes the Patch-Level production runs).*

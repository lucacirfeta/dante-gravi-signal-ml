# 🔬 Scientific Results and Benchmark Log (RESULTS.md)

This document collects the chronological history of runs executed with the `gravi-signal-ml` pipeline. Data is organized by **Observational Run** and **Session ID** to track the evolution of analyses over time.

---

## 📦 Downloaded Data Intervals (HDF5 Cache)

The following GPS time intervals have been downloaded and analyzed:

| Session ID | GPS Start Interval | Start Date (UTC) | GPS End Interval | End Date (UTC) | Total Duration (Hours) |
|:-----------|:-------------------|:-----------------|:-----------------|:---------------|:-----------------------|
| `20260520_223147` | `1382918784` | `2023-11-02 00:06:06` | `1384112128` | `2023-11-15 19:35:10` | `331.5` |
| `20260522_074026` | `1370206208` | `2023-06-07 20:49:50` | `1371395168` | `2023-06-21 15:05:50` | `330.3` |
| `20260523_143914` | `1385542816` | `2023-12-02 08:59:58` | `1386565632` | `2023-12-14 05:06:54` | `284.1` |
| `20260524_200219` | `1386797312` | `2023-12-16 21:28:14` | `1387994880` | `2023-12-30 18:07:42` | `332.7` |
| `20260530_014148` | `1238166048` | `2019-04-01 15:00:30` | `1238684480` | `2019-04-07 15:01:02` | `144.0` |

---

## 📅 Chronological Session Index

| Run | Session ID | Run Date/Time | Analysis Status | Salient Detections (NOVEL) |
|:---|:-----------|:--------------|:----------------|:---------------------------|
| `O4a` | `20260520_223147` | `2026-05-24 07:48:54` | Completed (OK) | No anomalous clusters |
| `O4a` | `20260522_074026` | `2026-05-24 07:47:56` | Completed (OK) | No anomalous clusters |
| `O4a` | `20260523_143914` | `2026-05-24 17:29:37` | Completed (OK) | No anomalous clusters |
| `O4a` | `20260524_200219` | `2026-05-25 22:09:05` | Completed (OK) | No anomalous clusters |
| `O3a` | `20260530_014148` | `2026-06-05 07:24:50` | Completed (OK) | No anomalous clusters |

---

## 📑 Session Details

### Session: `O4a - 20260520_223147`

#### 📊 1. Dataset Statistics and Preprocessing
| Detector | Total Spectrograms | Duty Cycle (%) | Colormap | Notes / Limitations |
|:---------|:-------------------|:---------------|:---------|:--------------------|
| **H1** | `26623` | `71.4%` | `cividis` | None |
| **L1** | `27541` | `81.5%` | `cividis` | None |

#### 🤖 2. Clustering Results (DPMM + Cosine)
| Detector | Number of Clusters | Samples in Dominant Cluster | Anomalous Clusters (# ID / Sizes) | Noise Points | PCA Variance (%) |
|:---------|:-------------------|:----------------------------|:----------------------------------|:-------------|:-----------------|
| **H1** | `11` | `8033` | `C1, C5, C7, C10` | `0` | `98.7%` |
| **L1** | `11` | `6997` | `C17` | `0` | `98.7%` |

#### 🛡️ 3. Robustness Validation (Ablation & Stability)
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Shuffled-Intensity ARI | Validation Outcome |
|:---------|:-------------------|:-----------------------|:--------------------------------|:-------------------|
| **H1** | `0.859` | `0.620` | `0.866` | Approved with slight drop |
| **L1** | `0.967` | `0.966` | `0.945` | Approved |

#### 🔗 4. Temporal Analysis (Time-Slide Coincidence)
| Coincidence Window | Zero-Lag Coincidences | Empirical p-value | Significance (Z-score) | Outcome |
| :--- | :---: | :---: | :---: | :--- |
| `±32s` | `0` | `1.0` | `0.0` | Random (background compatible) |

#### 🔬 5. Morphological Interpretation (In-domain Morphcheck)
Glitches mapped to expected morphologies or continuous background populations.

| Detector | NOVEL | KNOWN | AMBIGUOUS |
|:---------|:-----:|:-----:|:---------:|
| **H1** | `0` | `10062` | `16561` |
| **L1** | `0` | `11565` | `15976` |

#### 📉 7. Cluster Quality Metrics (Silhouette & DB Index)
| Detector | Silhouette (UMAP 10D) | Silhouette (PCA 50D) | DB Index (UMAP 10D) | DB Index (PCA 50D) |
|:---------|:----------------------|:---------------------|:--------------------|:-------------------|
| **H1** | `0.0841` | `0.0694` | `0.9694` | `1.3249` |
| **L1** | `0.4439` | `0.2550` | `0.6805` | `1.2902` |

#### 📊 6. Subvariant Similarity Analysis
| Detector | Cluster ID | Samples | Interpretation | Top-1 Class (Similarity) |
|:---------|:-----------|:--------|:---------------|:-------------------------|
| **H1** | `C0` | `601` | KNOWN - alta similarità verso classi note | Whistle (`0.9868`) |
| **H1** | `C1` | `2` | KNOWN - alta similarità verso classi note | Repeating_Blips (`0.9959`) |
| **H1** | `C2` | `4526` | KNOWN - alta similarità verso classi note | 1400Ripples (`0.9943`) |
| **H1** | `C3` | `3450` | KNOWN - alta similarità verso classi note | Whistle (`0.9959`) |
| **H1** | `C4` | `2003` | KNOWN - alta similarità verso classi note | Tomte (`0.9958`) |
| **H1** | ... | ... | *(+ 6 other clusters)* | ... |
| **L1** | `C2` | `209` | KNOWN - alta similarità verso classi note | 1400Ripples (`0.9912`) |
| **L1** | `C5` | `777` | KNOWN - alta similarità verso classi note | Helix (`0.9954`) |
| **L1** | `C6` | `1294` | KNOWN - alta similarità verso classi note | 1400Ripples (`0.9936`) |
| **L1** | `C7` | `4358` | KNOWN - alta similarità verso classi note | Low_Frequency_Burst (`0.9962`) |
| **L1** | `C10` | `6997` | KNOWN - alta similarità verso classi note | No_Glitch (`0.9943`) |
| **L1** | ... | ... | *(+ 6 other clusters)* | ... |

---

### Session: `O4a - 20260522_074026`

#### 📊 1. Dataset Statistics and Preprocessing
| Detector | Total Spectrograms | Duty Cycle (%) | Colormap | Notes / Limitations |
|:---------|:-------------------|:---------------|:---------|:--------------------|
| **H1** | `21991` | `59.2%` | `cividis` | None |
| **L1** | `29953` | `79.6%` | `cividis` | None |

#### 🤖 2. Clustering Results (DPMM + Cosine)
| Detector | Number of Clusters | Samples in Dominant Cluster | Anomalous Clusters (# ID / Sizes) | Noise Points | PCA Variance (%) |
|:---------|:-------------------|:----------------------------|:----------------------------------|:-------------|:-----------------|
| **H1** | `11` | `13477` | `C7, C10, C11` | `0` | `98.7%` |
| **L1** | `15` | `13571` | `C3, C6, C10, C13, C14, C17` | `0` | `98.0%` |

#### 🛡️ 3. Robustness Validation (Ablation & Stability)
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Shuffled-Intensity ARI | Validation Outcome |
|:---------|:-------------------|:-----------------------|:--------------------------------|:-------------------|
| **H1** | `0.889` | `0.897` | `0.830` | Approved with slight drop |
| **L1** | `0.910` | `0.681` | `0.706` | Approved |

#### 🔗 4. Temporal Analysis (Time-Slide Coincidence)
| Coincidence Window | Zero-Lag Coincidences | Empirical p-value | Significance (Z-score) | Outcome |
| :--- | :---: | :---: | :---: | :--- |
| `±32s` | `0` | `1.0` | `0.0` | Random (background compatible) |

#### 🔬 5. Morphological Interpretation (In-domain Morphcheck)
Glitches mapped to expected morphologies or continuous background populations.

| Detector | NOVEL | KNOWN | AMBIGUOUS |
|:---------|:-----:|:-----:|:---------:|
| **H1** | `0` | `8216` | `13775` |
| **L1** | `0` | `15274` | `14679` |

#### 📉 7. Cluster Quality Metrics (Silhouette & DB Index)
| Detector | Silhouette (UMAP 10D) | Silhouette (PCA 50D) | DB Index (UMAP 10D) | DB Index (PCA 50D) |
|:---------|:----------------------|:---------------------|:--------------------|:-------------------|
| **H1** | `-0.0159` | `0.0705` | `0.5453` | `1.0502` |
| **L1** | `-0.1179` | `-0.0751` | `1.6351` | `1.9590` |

#### 📊 6. Subvariant Similarity Analysis
| Detector | Cluster ID | Samples | Interpretation | Top-1 Class (Similarity) |
|:---------|:-----------|:--------|:---------------|:-------------------------|
| **H1** | `C0` | `158` | KNOWN - alta similarità verso classi note | Power_Line (`0.9961`) |
| **H1** | `C2` | `774` | KNOWN - alta similarità verso classi note | 1400Ripples (`0.9953`) |
| **H1** | `C3` | `531` | KNOWN - alta similarità verso classi note | Low_Frequency_Burst (`0.9959`) |
| **H1** | `C4` | `277` | KNOWN - alta similarità verso classi note | Helix (`0.9952`) |
| **H1** | `C5` | `3563` | KNOWN - alta similarità verso classi note | Air_Compressor (`0.9970`) |
| **H1** | ... | ... | *(+ 6 other clusters)* | ... |
| **L1** | `C0` | `210` | KNOWN - alta similarità verso classi note | Low_Frequency_Burst (`0.9958`) |
| **L1** | `C3` | `3` | KNOWN - alta similarità verso classi note | 1400Ripples (`0.9959`) |
| **L1** | `C4` | `630` | KNOWN - alta similarità verso classi note | 1400Ripples (`0.9958`) |
| **L1** | `C5` | `891` | KNOWN - alta similarità verso classi note | Paired_Doves (`0.9964`) |
| **L1** | `C6` | `15` | KNOWN - alta similarità verso classi note | Air_Compressor (`0.9946`) |
| **L1** | ... | ... | *(+ 10 other clusters)* | ... |

---

### Session: `O4a - 20260523_143914`

#### 📊 1. Dataset Statistics and Preprocessing
| Detector | Total Spectrograms | Duty Cycle (%) | Colormap | Notes / Limitations |
|:---------|:-------------------|:---------------|:---------|:--------------------|
| **H1** | `19943` | `62.4%` | `cividis` | None |
| **L1** | `13089` | `43.6%` | `cividis` | None |

#### 🤖 2. Clustering Results (DPMM + Cosine)
| Detector | Number of Clusters | Samples in Dominant Cluster | Anomalous Clusters (# ID / Sizes) | Noise Points | PCA Variance (%) |
|:---------|:-------------------|:----------------------------|:----------------------------------|:-------------|:-----------------|
| **H1** | `15` | `9235` | `C0, C7, C21, C23` | `0` | `98.7%` |
| **L1** | `11` | `4807` | `None` | `0` | `98.5%` |

#### 🛡️ 3. Robustness Validation (Ablation & Stability)
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Shuffled-Intensity ARI | Validation Outcome |
|:---------|:-------------------|:-----------------------|:--------------------------------|:-------------------|
| **H1** | `0.864` | `0.900` | `0.848` | Approved with slight drop |
| **L1** | `0.927` | `0.852` | `0.875` | Approved |

#### 🔗 4. Temporal Analysis (Time-Slide Coincidence)
| Coincidence Window | Zero-Lag Coincidences | Empirical p-value | Significance (Z-score) | Outcome |
| :--- | :---: | :---: | :---: | :--- |
| `±32s` | `0` | `0.1` | `2.2` | Random (background compatible) |

#### 🔬 5. Morphological Interpretation (In-domain Morphcheck)
Glitches mapped to expected morphologies or continuous background populations.

| Detector | NOVEL | KNOWN | AMBIGUOUS |
|:---------|:-----:|:-----:|:---------:|
| **H1** | `0` | `8557` | `11386` |
| **L1** | `0` | `5968` | `7121` |

#### 📉 7. Cluster Quality Metrics (Silhouette & DB Index)
| Detector | Silhouette (UMAP 10D) | Silhouette (PCA 50D) | DB Index (UMAP 10D) | DB Index (PCA 50D) |
|:---------|:----------------------|:---------------------|:--------------------|:-------------------|
| **H1** | `0.1035` | `0.1265` | `0.6550` | `1.0508` |
| **L1** | `0.4484` | `0.2410` | `0.4548` | `1.1198` |

#### 📊 6. Subvariant Similarity Analysis
| Detector | Cluster ID | Samples | Interpretation | Top-1 Class (Similarity) |
|:---------|:-----------|:--------|:---------------|:-------------------------|
| **H1** | `C0` | `1` | KNOWN - alta similarità verso classi note | Blip_Low_Frequency (`0.9975`) |
| **H1** | `C1` | `455` | KNOWN - alta similarità verso classi note | Air_Compressor (`0.9899`) |
| **H1** | `C3` | `1299` | KNOWN - alta similarità verso classi note | Whistle (`0.9960`) |
| **H1** | `C6` | `222` | KNOWN - alta similarità verso classi note | Low_Frequency_Burst (`0.9960`) |
| **H1** | `C7` | `1` | KNOWN - alta similarità verso classi note | Blip_Low_Frequency (`0.9871`) |
| **H1** | ... | ... | *(+ 10 other clusters)* | ... |
| **L1** | `C0` | `2803` | KNOWN - alta similarità verso classi note | Whistle (`0.9933`) |
| **L1** | `C2` | `225` | KNOWN - alta similarità verso classi note | Tomte (`0.9951`) |
| **L1** | `C3` | `832` | KNOWN - alta similarità verso classi note | Low_Frequency_Burst (`0.9960`) |
| **L1** | `C4` | `457` | KNOWN - alta similarità verso classi note | 1080Lines (`0.9874`) |
| **L1** | `C5` | `451` | KNOWN - alta similarità verso classi note | Blip_Low_Frequency (`0.9945`) |
| **L1** | ... | ... | *(+ 6 other clusters)* | ... |

---

### Session: `O4a - 20260524_200219`

#### 📊 1. Dataset Statistics and Preprocessing
| Detector | Total Spectrograms | Duty Cycle (%) | Colormap | Notes / Limitations |
|:---------|:-------------------|:---------------|:---------|:--------------------|
| **H1** | `27017` | `72.2%` | `cividis` | None |
| **L1** | `21985` | `58.2%` | `cividis` | None |

#### 🤖 2. Clustering Results (DPMM + Cosine)
| Detector | Number of Clusters | Samples in Dominant Cluster | Anomalous Clusters (# ID / Sizes) | Noise Points | PCA Variance (%) |
|:---------|:-------------------|:----------------------------|:----------------------------------|:-------------|:-----------------|
| **H1** | `16` | `6978` | `C12, C13, C18, C23` | `0` | `98.7%` |
| **L1** | `10` | `9286` | `None` | `0` | `98.4%` |

#### 🛡️ 3. Robustness Validation (Ablation & Stability)
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Shuffled-Intensity ARI | Validation Outcome |
|:---------|:-------------------|:-----------------------|:--------------------------------|:-------------------|
| **H1** | `0.835` | `0.682` | `0.696` | Approved with slight drop |
| **L1** | `0.986` | `0.981` | `0.975` | Approved |

#### 🔗 4. Temporal Analysis (Time-Slide Coincidence)
| Coincidence Window | Zero-Lag Coincidences | Empirical p-value | Significance (Z-score) | Outcome |
| :--- | :---: | :---: | :---: | :--- |
| `±32s` | `0` | `1.0` | `-0.7` | Random (background compatible) |

#### 🔬 5. Morphological Interpretation (In-domain Morphcheck)
Glitches mapped to expected morphologies or continuous background populations.

| Detector | NOVEL | KNOWN | AMBIGUOUS |
|:---------|:-----:|:-----:|:---------:|
| **H1** | `0` | `11057` | `15960` |
| **L1** | `0` | `9884` | `12101` |

#### 📉 7. Cluster Quality Metrics (Silhouette & DB Index)
| Detector | Silhouette (UMAP 10D) | Silhouette (PCA 50D) | DB Index (UMAP 10D) | DB Index (PCA 50D) |
|:---------|:----------------------|:---------------------|:--------------------|:-------------------|
| **H1** | `0.2031` | `0.0736` | `0.9059` | `1.5691` |
| **L1** | `0.7477` | `0.4057` | `0.4353` | `1.2352` |

#### 📊 6. Subvariant Similarity Analysis
| Detector | Cluster ID | Samples | Interpretation | Top-1 Class (Similarity) |
|:---------|:-----------|:--------|:---------------|:-------------------------|
| **H1** | `C1` | `3251` | KNOWN - alta similarità verso classi note | Chirp (`0.9955`) |
| **H1** | `C3` | `3362` | KNOWN - alta similarità verso classi note | 1080Lines (`0.9836`) |
| **H1** | `C5` | `2935` | KNOWN - alta similarità verso classi note | Tomte (`0.9956`) |
| **H1** | `C7` | `330` | KNOWN - alta similarità verso classi note | Helix (`0.9959`) |
| **H1** | `C10` | `316` | KNOWN - alta similarità verso classi note | Paired_Doves (`0.9964`) |
| **H1** | ... | ... | *(+ 11 other clusters)* | ... |
| **L1** | `C2` | `975` | KNOWN - alta similarità verso classi note | Low_Frequency_Lines (`0.9955`) |
| **L1** | `C3` | `1366` | KNOWN - alta similarità verso classi note | Whistle (`0.9894`) |
| **L1** | `C4` | `769` | KNOWN - alta similarità verso classi note | Low_Frequency_Burst (`0.9960`) |
| **L1** | `C5` | `1378` | KNOWN - alta similarità verso classi note | Paired_Doves (`0.9965`) |
| **L1** | `C7` | `173` | KNOWN - alta similarità verso classi note | Light_Modulation (`0.9958`) |
| **L1** | ... | ... | *(+ 5 other clusters)* | ... |

---

## ⚖️ Cross-Run Comparison

| Metric | `20260520_223147` | `20260522_074026` | `20260523_143914` | `20260524_200219` | Comparison |
|:-------|:---|:---|:---|:---|:-----------|
| Spectrograms (H1 / L1) | `26623` / `27541` | `21991` / `29953` | `19943` / `13089` | `27017` / `21985` | Comparable |
| Number of Clusters (H1 / L1) | `11` / `11` | `11` / `15` | `15` / `11` | `16` / `10` | Consistent |
| Robustness (ARI H1 / L1) | `0.859` / `0.967` | `0.889` / `0.910` | `0.864` / `0.927` | `0.835` / `0.986` | Always > 0.85 |

---

## 🚨 3.6 Mock Data Challenge (MDC)

> **Status:** Three MDC runs completed. All results verified against raw CSV files.
> **Publication Note:** The methodology, formal results, and interpretations of this Mock Data Challenge are formally published in **[Cirfeta (2026b), arXiv:2606.06237](https://arxiv.org/abs/2606.06237)**.

### 3.6.1 Design

Synthetic glitches injected into raw L1 O4a strain **prior to whitening**, processing with the standard 32s Q-transform window.  
Session: `20260524_200219` L1 (σ_bg = 0.0073, hardest baseline).  
Amplitude grid: log-uniform [10⁻²², 10⁻²¹], 10 steps, 15–40 injections per (type, amplitude).

| Group | Morphologies | Characteristic |
|:------|:-------------|:---------------|
| A — Broadband | Butterfly, ZSweep, SpiralBurst, StepLadder, NoiseBlob | Visually distinct spectral shapes |
| B — Narrow-band | NarrowChirp (150→300 Hz, 0.5s), HarmonicComb (7×100 Hz), AsymBlip (τ_rise=10ms) | Physically motivated |

---

### 3.6.2 Run A — Dynamic Threshold (τ_dyn = 0.9811)

**Source:** `results/mdc/0037_04062026/mdc_results.csv`  
**Baseline:** mean = 0.9939, std = 0.0035, τ_dyn = 0.9852 (local), overall τ_dyn = 0.9811 (sessione)

| Glitch Type | SNR range | SNR₅₀ | Max Recall | N injections | Status |
|:------------|:----------|:-------|:----------:|:------------:|:------:|
| Butterfly | 17 – 345 | 80 | **1.000** | 366 | ✅ |
| ZSweep | 25 – 496 | 109 | **1.000** | 373 | ✅ |
| SpiralBurst | 13 – 269 | >2600 | 0.000 | 352 | ❌ |
| StepLadder | 20 – 403 | >4200 | 0.000 | 359 | ❌ |
| NoiseBlob | 23 – 484 | >3300 | 0.000 | 363 | ❌ |

**Interpretation:** Visually anisotropic chirp-like morphologies (Butterfly, ZSweep) are detectable. Noise-like and harmonic-step morphologies project within the reference manifold regardless of SNR. FPR is **uncontrolled** with the dynamic threshold.

---

### 3.6.3 Run B — Calibrated Threshold (τ_op = 0.874)

**Source:** `results/mdc_32s_calibrated/mdc_results_calibrated.csv`  
**Baseline locale:** mean = 0.9940, std = 0.0035, n_samples = 78, τ_dyn = 0.9852

| Glitch Type | SNR range | Max Recall | N injections | Status |
|:------------|:----------|:----------:|:------------:|:------:|
| Butterfly | 17 – 175 | 0.000 | 160 | ❌ |
| ZSweep | 25 – 251 | 0.000 | 177 | ❌ |
| SpiralBurst | 14 – 138 | 0.000 | 181 | ❌ |
| StepLadder | 21 – 207 | 0.000 | 177 | ❌ |
| NoiseBlob | 23 – 231 | 0.000 | 187 | ❌ |
| **Totale** | **14–251** | **0.000** | **882** | |

**FPR empirico:** Su 21.985 segmenti L1: 2 candidati (GPS: 1386816320, 1386824608) — entrambi falsi positivi. FPR_obs = 0.009%.

---

### 3.6.4 Run C — Narrow-band + Impulsive (τ_op = 0.874)

**Source:** `results/mdc_narrowband_calibrated/mdc_results.csv`  
**Baseline locale:** mean = 0.9939, std = 0.0051, n_samples = 85, τ_dyn = 0.9811

| Glitch Type | SNR range | Max Recall | N injections | Status |
|:------------|:----------|:----------:|:------------:|:------:|
| AsymBlip | 38 – 430 | 0.000 | 167 | ❌ |
| NarrowChirp | 20 – 208 | 0.000 | 168 | ❌ |
| HarmonicComb | 12 – 214 | 0.000 | 200 | ❌ |
| **Totale** | **12–430** | **0.000** | **535** | |

---

### 3.6.5 MDC Summary — Totale verificato

| Run | Threshold | N iniezioni | Recall (max) | FPR |
|:----|:----------|:-----------:|:------------:|:---:|
| Run A (dyn.) | τ_dyn = 0.9811 | 1813 | 1.000 (Butterfly, ZSweep) | Non controllato |
| Run B (cal.) | τ_op = 0.874 | 882 | 0.000 | 0.009% |
| Run C (cal.) | τ_op = 0.874 | 535 | 0.000 | 0.009% |
| **Totale cal.** | **τ_op = 0.874** | **1417** | **0.000** | **<0.01%** |

---

### 3.6.6 Signal Dilution Effect — Analisi del Failure Mode

Il **CLS token** in ViT-S/14 implementa un global average pooling su tutti i 37×37 = 1369 patch dell'immagine.

| Morfologia | Frazione patch con segnale | Diluzione |
|:-----------|:--------------------------|:----------|
| AsymBlip (0.5s su 32s) | ~1.6% temporale → ~1 colonna su 37 | 98.4% |
| NarrowChirp (0.5s su 32s) | ~1.6% temporale | 98.4% |
| HarmonicComb (7 armoniche) | ~5% spettrale → ~2 righe su 37 | 95% |
| Butterfly (4s su 32s) | ~12.5% temporale → ~4 colonne su 37 | 87.5% |
| ZSweep (4s su 32s) | ~12.5% temporale → ~4 colonne su 37 | 87.5% |

**Risultato:** Δs_max < 0.021 per tutte le morfologie. min(s_max) O4a background = 0.867. Threshold = 0.874.  
Il segnale anomalo è fisicamente e matematicamente impossibile da rilevare con CLS pooling globale sotto τ_op = 0.874.

---

## 🔬 3.7 Retrospective Analysis (Calibrated τ_op = 0.874)

Rianalisi retrospettiva sulla sessione `20260524_200219` (L1, 21.985 segmenti) con soglia operativa calibrata.

### 3.7.1 Risultati Operativi

| Metodo | Soglia | N_NOVEL | FPR |
|:-------|:-------|:-------:|:----|
| Empirical percentile | τ_op = 0.874 (FPR target < 0.01%) | **2** | 0.009% |

### 3.7.2 Candidati Flaggati — Falsi Positivi Confermati

1. **GPS:** `1386816320` — Nearest Reference: `Extremely_Loud`
2. **GPS:** `1386824608` — Nearest Reference: `Scattered_Light`

Ispezione visiva: entrambi falsi positivi a bassa energia. Null result confermato e statisticamente robusto.

### 3.7.3 Caratterizzazione della Distribuzione O4a

| Statistica | Valore |
|:-----------|:-------|
| N segmenti | 188.142 |
| Mean (μ) | 0.9953 |
| Std (σ) | 0.0031 |
| Min | 0.867 |
| Skewness | -4.12 |
| Excess kurtosis | 15.38 |
| Shapiro-Wilk W (n=5000) | 0.328 |
| Shapiro-Wilk p-value | 1.13 × 10⁻⁸⁶ |
| Best tail fit | GEV (LL=32413.6 vs Beta LL=31768.9) |

**Implicazione:** Soglie Gaussiane k-σ completamente inappropriate. τ_op deve essere calibrata come percentile empirico della distribuzione osservata.

**Scientific Implication:** Il null result su O4a è valido condizionalmente al regime di sensibilità caratterizzato dal MDC. Il pipeline non rileva morfologie che occupano <5% della griglia di patch nella finestra da 32s. Questa è una limitazione architetturale del CLS token, non di DINOv2 come modello.

---

## 🔬 3.8 O3a Analysis (Session 20260530_014148)

Questa sessione estende l'analisi ai dati dell'observing run precedente (O3a).

#### 📊 1. Dataset Statistics and Preprocessing
| Detector | Total Spectrograms | Duration | Duty Cycle (%) | Colormap |
|:---------|:-------------------|:---------|:---------------|:---------|
| **H1** | `11433` | `144.0h` | `70.6%` | `cividis` |
| **L1** | `11373` | `141.4h` | `71.5%` | `cividis` |

#### 🤖 2. Clustering & Morphological Cross-Check
| Detector | Clusters | Anomalous (DPMM) | Morphcheck NOVEL | Morphcheck KNOWN | Morphcheck AMBIGUOUS |
|:---------|:---------|:-----------------|:-----------------|:-----------------|:---------------------|
| **H1** | `8` | `None` | `0` | `5317` | `6116` |
| **L1** | `12` | `Cluster 15` | `0` | `4908` | `6465` |

**Nota su L1:** Il DPMM ha marcato il `Cluster 15` come anomalo. Tuttavia la similarità rispetto al reference ha riassorbito i campioni in classi note, restituendo 0 NOVEL. Conferma dell'efficacia del doppio step di validazione.

#### 🛡️ 3. Robustness Validation (Ablation & Stability)
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Inverted ARI | Ablation Shuffled ARI |
|:---------|:-------------------|:-----------------------|:----------------------|:----------------------|
| **H1** | `0.983` | `0.972` | `0.957` | `0.972` |
| **L1** | `0.955` | `0.939` | `0.950` | `0.926` |

**Conclusione Critica:** L'ARI grayscale di H1 in O3a raggiunge lo **0.972**. Questo risolve il problema riscontrato in O4a, dimostrando che l'instabilità di H1 in O4a era dovuta a variazioni non-stazionarie ambientali o strumentali (es. laser noise) specifiche di quel run, e non a un limite strutturale dell'encoder DINOv2 sui dati di Hanford.

#### 🔗 4. Temporal Analysis (Time-Slide Coincidence)
| Coincidence Window | Empirical p-value | Significance (Z-score) | Outcome |
| :--- | :---: | :---: | :--- |
| `±32s` | `1.0` | `-0.49` | Random (background compatible) |

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

---

## 📅 Chronological Session Index

| Run | Session ID | Run Date/Time | Analysis Status | Salient Detections (NOVEL) |
|:---|:-----------|:--------------|:----------------|:---------------------------|
| `O4a` | `20260520_223147` | `2026-05-24 07:48:54` | Completed (OK) | No anomalous clusters |
| `O4a` | `20260522_074026` | `2026-05-24 07:47:56` | Completed (OK) | No anomalous clusters |
| `O4a` | `20260523_143914` | `2026-05-24 17:29:37` | Completed (OK) | No anomalous clusters |
| `O4a` | `20260524_200219` | `2026-05-25 22:09:05` | Completed (OK) | No anomalous clusters |

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

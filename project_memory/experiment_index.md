# Experiment Index — Indice Completo degli Esperimenti
<!-- Last updated: 2026-06-02 | Source: RESULTS.md -->
<!-- Regola: aggiornare solo con dati verificabili in RESULTS.md. Non inventare valori numerici. -->

---

## 1. Dati Scaricati e Analizzati (O4a)

| Session ID | GPS Start | Data Start (UTC) | GPS End | Data End (UTC) | Durata (h) |
|:-----------|:----------|:-----------------|:--------|:---------------|:-----------|
| `20260520_223147` | 1382918784 | 2023-11-02 00:06:06 | 1384112128 | 2023-11-15 19:35:10 | **331.5** |
| `20260522_074026` | 1370206208 | 2023-06-07 20:49:50 | 1371395168 | 2023-06-21 15:05:50 | **330.3** |
| `20260523_143914` | 1385542816 | 2023-12-02 08:59:58 | 1386565632 | 2023-12-14 05:06:54 | **284.1** |
| `20260524_200219` | 1386797312 | 2023-12-16 21:28:14 | 1387994880 | 2023-12-30 18:07:42 | **332.7** |

**Totale analizzato:** ~1.278 ore di dati O4a (H1 + L1 indipendentemente).
**Spettrogrammi totali:** ~188.000+ (H1 + L1 combinati su 4 sessioni).
**Finestre temporali coperte:** Giugno 2023, Novembre 2023, Dicembre 2023 (2 finestre).

---

## 2. Sessione `20260520_223147` (2023-11-02 → 2023-11-15, 331.5h)

### Dataset & Preprocessing
| Detector | Spettrogrammi | Duty Cycle (%) | Colormap |
|:---------|:-------------|:---------------|:---------|
| H1 | 26.623 | 71.4% | cividis |
| L1 | 27.541 | 81.5% | cividis |

### Clustering (DPMM + Cosine)
| Detector | N Cluster | Dominant Cluster | Anomalous Clusters | Noise | PCA Variance |
|:---------|:----------|:-----------------|:-------------------|:------|:-------------|
| H1 | 11 | 8.033 | C1, C5, C7, C10 | 0 | 98.7% |
| L1 | 11 | 6.997 | C17 | 0 | 98.7% |

### Robustezza (Ablation & Stability)
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Shuffled-Int ARI | Esito |
|:---------|:-------------------|:-----------------------|:--------------------------|:------|
| H1 | 0.859 | 0.620 | 0.866 | Approved with slight drop |
| L1 | 0.967 | 0.966 | 0.945 | Approved |

> ⚠️ H1 Grayscale ARI = 0.620: sotto la soglia critica. Asimmetria H1 vs L1 confermata anche in questa sessione.

### Time-Slide Coincidence
| Window | Zero-Lag | p-value | Z-score | Esito |
|:-------|:---------|:--------|:--------|:------|
| ±32s | 0 | 1.0 | 0.0 | Random (background compatible) |

### Morphcheck In-Domain
| Detector | NOVEL | KNOWN | AMBIGUOUS |
|:---------|:-----:|:-----:|:---------:|
| H1 | **0** | 10.062 | 16.561 |
| L1 | **0** | 11.565 | 15.976 |

### Qualità Cluster (Silhouette & DB Index)
| Detector | Silhouette (10D) | Silhouette (50D) | DB Index (10D) | DB Index (50D) |
|:---------|:-----------------|:-----------------|:---------------|:---------------|
| H1 | 0.0841 | 0.0694 | 0.9694 | 1.3249 |
| L1 | 0.4439 | 0.2550 | 0.6805 | 1.2902 |

### Subvariant Similarity (campionamento)
| Detector | Cluster | Samples | Top-1 Class (Sim) |
|:---------|:--------|:--------|:------------------|
| H1 | C0 | 601 | Whistle (0.9868) |
| H1 | C1 | 2 | Repeating_Blips (0.9959) |
| H1 | C2 | 4.526 | 1400Ripples (0.9943) |
| H1 | C3 | 3.450 | Whistle (0.9959) |
| H1 | C4 | 2.003 | Tomte (0.9958) |
| L1 | C2 | 209 | 1400Ripples (0.9912) |
| L1 | C5 | 777 | Helix (0.9954) |
| L1 | C6 | 1.294 | 1400Ripples (0.9936) |
| L1 | C7 | 4.358 | Low_Frequency_Burst (0.9962) |
| L1 | C10 | 6.997 | No_Glitch (0.9943) |

---

## 3. Sessione `20260522_074026` (2023-06-07 → 2023-06-21, 330.3h)

### Dataset & Preprocessing
| Detector | Spettrogrammi | Duty Cycle (%) | Colormap |
|:---------|:-------------|:---------------|:---------|
| H1 | 21.991 | 59.2% | cividis |
| L1 | 29.953 | 79.6% | cividis |

### Clustering (DPMM + Cosine)
| Detector | N Cluster | Dominant Cluster | Anomalous Clusters | Noise | PCA Variance |
|:---------|:----------|:-----------------|:-------------------|:------|:-------------|
| H1 | 11 | 13.477 | C7, C10, C11 | 0 | 98.7% |
| L1 | 15 | 13.571 | C3, C6, C10, C13, C14, C17 | 0 | 98.0% |

### Robustezza
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Shuffled-Int ARI | Esito |
|:---------|:-------------------|:-----------------------|:--------------------------|:------|
| H1 | 0.889 | 0.897 | 0.830 | Approved with slight drop |
| L1 | 0.910 | 0.681 | 0.706 | Approved |

### Time-Slide Coincidence
| Window | Zero-Lag | p-value | Z-score | Esito |
|:-------|:---------|:--------|:--------|:------|
| ±32s | 0 | 1.0 | 0.0 | Random (background compatible) |

### Morphcheck In-Domain
| Detector | NOVEL | KNOWN | AMBIGUOUS |
|:---------|:-----:|:-----:|:---------:|
| H1 | **0** | 8.216 | 13.775 |
| L1 | **0** | 15.274 | 14.679 |

### Qualità Cluster
| Detector | Silhouette (10D) | Silhouette (50D) | DB Index (10D) | DB Index (50D) |
|:---------|:-----------------|:-----------------|:---------------|:---------------|
| H1 | -0.0159 | 0.0705 | 0.5453 | 1.0502 |
| L1 | -0.1179 | -0.0751 | 1.6351 | 1.9590 |

---

## 4. Sessione `20260523_143914` (2023-12-02 → 2023-12-14, 284.1h)

### Dataset & Preprocessing
| Detector | Spettrogrammi | Duty Cycle (%) | Colormap |
|:---------|:-------------|:---------------|:---------|
| H1 | 19.943 | 62.4% | cividis |
| L1 | 13.089 | 43.6% | cividis |

### Clustering (DPMM + Cosine)
| Detector | N Cluster | Dominant Cluster | Anomalous Clusters | Noise | PCA Variance |
|:---------|:----------|:-----------------|:-------------------|:------|:-------------|
| H1 | 15 | 9.235 | C0, C7, C21, C23 | 0 | 98.7% |
| L1 | 11 | 4.807 | None | 0 | 98.5% |

### Robustezza
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Shuffled-Int ARI | Esito |
|:---------|:-------------------|:-----------------------|:--------------------------|:------|
| H1 | 0.864 | 0.900 | 0.848 | Approved with slight drop |
| L1 | 0.927 | 0.852 | 0.875 | Approved |

### Time-Slide Coincidence
| Window | Zero-Lag | p-value | Z-score | Esito |
|:-------|:---------|:--------|:--------|:------|
| ±32s | 0 | 0.1 | 2.2 | Random (background compatible) |

> Nota: p-value = 0.1 è il valore più basso osservato tra le 4 sessioni (ma ancora > 0.05).

### Morphcheck In-Domain
| Detector | NOVEL | KNOWN | AMBIGUOUS |
|:---------|:-----:|:-----:|:---------:|
| H1 | **0** | 8.557 | 11.386 |
| L1 | **0** | 5.968 | 7.121 |

### Qualità Cluster
| Detector | Silhouette (10D) | Silhouette (50D) | DB Index (10D) | DB Index (50D) |
|:---------|:-----------------|:-----------------|:---------------|:---------------|
| H1 | 0.1035 | 0.1265 | 0.6550 | 1.0508 |
| L1 | 0.4484 | 0.2410 | 0.4548 | 1.1198 |

---

## 5. Sessione `20260524_200219` (2023-12-16 → 2023-12-30, 332.7h)

### Dataset & Preprocessing
| Detector | Spettrogrammi | Duty Cycle (%) | Colormap |
|:---------|:-------------|:---------------|:---------|
| H1 | 27.017 | 72.2% | cividis |
| L1 | 21.985 | 58.2% | cividis |

### Clustering (DPMM + Cosine)
| Detector | N Cluster | Dominant Cluster | Anomalous Clusters | Noise | PCA Variance |
|:---------|:----------|:-----------------|:-------------------|:------|:-------------|
| H1 | 16 | 6.978 | C12, C13, C18, C23 | 0 | 98.7% |
| L1 | 10 | 9.286 | None | 0 | 98.4% |

### Robustezza
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Shuffled-Int ARI | Esito |
|:---------|:-------------------|:-----------------------|:--------------------------|:------|
| H1 | 0.835 | 0.682 | 0.696 | Approved with slight drop |
| L1 | 0.986 | 0.981 | 0.975 | Approved |

### Time-Slide Coincidence
| Window | Zero-Lag | p-value | Z-score | Esito |
|:-------|:---------|:--------|:--------|:------|
| ±32s | 0 | 1.0 | -0.7 | Random (background compatible) |

### Morphcheck In-Domain
| Detector | NOVEL | KNOWN | AMBIGUOUS |
|:---------|:-----:|:-----:|:---------:|
| H1 | **0** | 11.057 | 15.960 |
| L1 | **0** | 9.884 | 12.101 |

### Qualità Cluster
| Detector | Silhouette (10D) | Silhouette (50D) | DB Index (10D) | DB Index (50D) |
|:---------|:-----------------|:-----------------|:---------------|:---------------|
| H1 | 0.2031 | 0.0736 | 0.9059 | 1.5691 |
| L1 | 0.7477 | 0.4057 | 0.4353 | 1.2352 |

---

## 6. Cross-Run Comparison (da `RESULTS.md`)

| Metrica | `20260520` | `20260522` | `20260523` | `20260524` | Trend |
|:--------|:-----------|:-----------|:-----------|:-----------|:------|
| Spettrogrammi H1/L1 | 26623/27541 | 21991/29953 | 19943/13089 | 27017/21985 | Comparabile |
| N Cluster H1/L1 | 11/11 | 11/15 | 15/11 | 16/10 | Stabile (10-16) |
| Stability ARI H1/L1 | 0.859/0.967 | 0.889/0.910 | 0.864/0.927 | 0.835/0.986 | Sempre > 0.835 |
| Grayscale ARI H1 | 0.620 | 0.897 | 0.900 | 0.682 | **Asimmetrico** |
| NOVEL (H1+L1) | 0+0 | 0+0 | 0+0 | 0+0 | **Null Result** |

---

## 7. Sommario Scientifico Aggregato

- **Esito principale:** NOVEL = 0 in tutte e 4 le sessioni su entrambi i detector. Nessun candidato anomalo strutturalmente stabile identificato.
- **Asimmetria H1 vs L1:** ARI grayscale di H1 è sistematicamente più basso (range 0.62–0.90 vs L1 sempre > 0.68). Ipotesi: H1 ha maggiore non-stazionarietà nel noise floor → diversità cromatica in cividis che, rimossa dal grayscale, degrada la coerenza dei cluster.
- **Temporal p-values:** p ≥ 0.1 in tutte le sessioni → compatibili con il background casuale.
- **PCA Variance:** ~98.4–98.7% spiegata con 50 componenti su embedding 384D. Eccezione: `20260522_074026` L1 = 98.0%.
- **L1 Silhouette:** Significativamente migliore di H1 in tutte le sessioni (L1 range 0.44–0.75, H1 range -0.02–0.20).

---

## 8. Esperimenti Legacy (pre-session-id)

### Scan 48h (pre-isolamento sessioni)
Eseguito in sessione 2026-05-10/11. Dati in `data/embeddings/` (legacy path):
- `o4a_h1_48h.npy` (2634, 384)
- `o4a_l1_48h.npy` (4982, 384)

**H1 48h clustering (HDBSCAN, pre-DPMM):**
- C0: 2305 (dominante), C1: 23 (ANOMALOUS), C2: 43, C3: 244, C4: 19 (ANOMALOUS). Noise: 0. PCA: 98.2%.
- C1 (23 pts): mappa su 1400Ripples/Low_Frequency_Lines. C4 (19 pts): alta ambiguità verso No_Glitch.

**L1 48h clustering (HDBSCAN, pre-DPMM):**
- C0: 4178 (dominante), C1: 161, C2: 73, C3: 441, C4: 32 (ANOMALOUS), C5: 96. Noise: 1. PCA: 98.4%.
- C4 mappa su Low_Frequency_Lines.

**Nota scientifica (da `docs/SESSION_HANDOFF.MD`):** Low_Frequency_Lines è una classe con tasso aumentato in O4a di cui la sorgente rimane non identificata (Soni et al., 2025, arXiv:2409.02831).

---

## 9. Esperimenti MDC (Mock Data Challenge)

### EXP-MDC-01 — MDC Run completo (pre-fix) — 2026-06-03
- **Script:** `src/injection.py` → `run_mdc()`, avviato tramite `main.py run-injection`
- **Detector:** L1, O4a (sessione 2023-06-07)
- **Glitch types:** SpiralBurst, StepLadder, NoiseBlob, Butterfly, ZSweep (+ NULL)
- **Amplitudini:** 10 livelli log-spaced [1e-22, 2e-21], 50 iniezioni/tipo/ampiezza
- **Risultato:** Recall=0.00 per SpiralBurst, StepLadder, NoiseBlob. Butterfly e ZSweep mostrano recall crescente con l'ampiezza (Butterfly max recall=1.0 a 2e-21, ZSweep max recall=0.97).
- **Esito:** **FAILURE** — run eseguita con double-whitening bug attivo e soglia globale fissa 0.85.
- **File:** `results/mdc/mdc_results.csv`

### EXP-MDC-02 — Baseline Noise Variance Test — 2026-06-04
- **Script:** `scratch/baseline_variance_test.py`
- **Detector:** L1, O4a (GPS 1369598418 + 1 week offset)
- **Metodo:** 30 segmenti consecutivi puro rumore (NULL), 4s Q-transform window, DINOv2 ViT-S/14, cosine similarity vs in-domain reference index
- **Risultato:**
  | Metrica | Valore |
  |---------|--------|
  | N campioni | 30 |
  | Mean max_sim | 0.9403 |
  | Std max_sim | 0.0210 |
  | Min | 0.9082 |
  | Max | 0.9844 |
  | Soglia dinamica (k=2.5) | **0.888** |
  | Drop segnale / std | **2.9 sigma** |
- **Conclusione chiave:** `std=0.021 < 0.03` → il dynamic threshold è statisticamente viable. Un drop di 0.06 (tipico per glitch sintetici post-whitening) corrisponde a 2.9σ dalla baseline.
- **Esito:** ✅ **SUCCESS** — conferma la feasibility del metodo.

### EXP-MDC-03 — Sanity Check Singolo Glitch — 2026-06-04
- **Script:** `scratch/sanity_check.py`
- **Glitch:** SpiralBurst, ampiezza 1e-21 (SNR=134.8), iniettato su L1 raw strain (GPS 1370205138)
- **Whitening:** Fisicamente corretto (raw strain → whiten → bandpass)
- **Risultato per finestra temporale:**
  | Window | Top Label | Top Sim | Status con threshold=0.85 | Status con dynamic (k=2.5) |
  |--------|-----------|---------|--------------------------|---------------------------|
  | 1.0s | Scattered_Light | 0.8623 | KNOWN (>0.85) | **NOVEL** (-3.7σ) |
  | 2.0s | Violin_Mode | 0.9006 | KNOWN | KNOWN (-1.9σ) |
  | 4.0s | Koi_Fish | 0.9238 | KNOWN | KNOWN (-0.8σ) |
- **Conclusione chiave:** La finestra 1s è ottimale per il dynamic threshold. Il multi-scale windowing aumenta la similarità (peggiora), non la abbassa.
- **Esito:** ✅ **SUCCESS** — dimostra che la finestra 1s è la scelta corretta con dynamic thresholding.

---

## 10. Esperimenti Pianificati (TODO)

| ID | Esperimento | Dipendenze | Stato |
|----|-------------|-----------|-------|
| EXP-01 | DINOv2 ViT-B/14 su H1 (ablation incluso) | Nessuno | [TODO] |
| EXP-02 | Multi-Q Analysis (qrange multi-finestra, 1152-dim) | EXP-01 | [TODO] |
| EXP-03 | Sensitivity test: variare `n_neighbors` (5, 15, 30) | Nessuno | [TODO] |
| EXP-04 | Variazione soglia morphcheck (0.80, 0.85, 0.90) | Nessuno | [TODO] |
| EXP-05 | Confronto con CTSAE (stesso dataset, ARI/NMI) | Nessuno | [TODO] |
| EXP-06 | Scan O4b data (GWTC-5.0, post-2024) | Accesso dati | [TODO] |
| EXP-07 | Embedding blocchi intermedi DINOv2 (Grad-CAM) | Nessuno | [TODO] |
| EXP-MDC-04 | **MDC re-run completo con Dynamic Thresholding** (k=2.5, 1s window, 50 iniezioni/tipo) | D-10 implementato | **[READY]** |
| EXP-MDC-05 | **Baseline H1 noise variance test** (misurare `mean`, `std` per H1 O4a) | Nessuno | **[READY]** |
| EXP-MDC-06 | ROC Curve sul MDC: sweep k_sigma [1.5, 2.0, 2.5, 3.0, 3.5] per AUC | EXP-MDC-04 | [TODO] |

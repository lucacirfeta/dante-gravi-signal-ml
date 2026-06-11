# Architecture State — Stato Corrente dell'Architettura
<!-- Last updated: 2026-06-11T21:30 | Source: README.md, config.yaml, src/ listing, CLI_REFERENCE.md -->
<!-- Regola: aggiornare solo con informazioni verificabili dalla repository. Non inventare dati. -->

---

## 1. Package Structure — Inventario Completo

La repository è organizzata in tre package principali per imporre la Single Responsibility e isolare il core engine dalla pipeline esplorativa.

### `src/core/` (Hardware-Agnostic Primitives)
| File | Ruolo | Stato |
|------|-------|-------|
| `data_loader.py` | Download HDF5 da GWOSC, thread pool fetching, progress tracking | ✅ Stabile |
| `preprocessor.py` | Whitening, bandpass, Q-Transform, generazione PNG | ✅ Stabile |
| `parallel_processor.py` | Parallelizzazione CPU-bound via ProcessPoolExecutor | ✅ Stabile |
| `encoder.py` | Wrapper per DINOv2 (Vision Transformer) | ✅ Stabile |
| `gravity_spy_checker.py` | Connettore DB SQLAlchemy per metadati Gravity Spy | ✅ Stabile |
| `utils.py` | Path resolution, costanti e utilità condivise | ✅ Stabile |
| `logging_utils.py` | Setup centralizzato del logging | ✅ Stabile |
| `benchmark_methods.py` | Metodi helper per test/confronto | ✅ Stabile |

### `src/pipeline_v2_production/` (Rigid O4a Engine - 384D)
| File | Ruolo | Stato |
|------|-------|-------|
| `patch_production.py` | DINOv2 inference, Patch-Level MIL (384D), extreme-value thresholding, SWMR HDF5 | ✅ Stabile |
| `production_cluster.py` | Adaptive PCA (90% var), DPMM con Conditional Covariance per fix collapse < 200 samples | ✅ Stabile |
| `production_report.py` | Generazione report Markdown, UMAP 4D ARI, Saliency Map overlay | ✅ Stabile |
| `aggregate_report.py` | Cross-session reducer: deduplicazione, Table 3a/3b, Spearman rank test | ✅ Stabile |
| `live_umap.py` | Dashboard interattiva in tempo reale per exhibition fisica | ✅ Stabile |
| `patch_analysis.py` | Orchestratore continous workflow state-aware | ✅ Stabile |

### `src/pipeline_v1_legacy/` (Exploratory 768D - Frozen)
Contiene i moduli sperimentali originali basati su Token CLS globale (768D), PCA e UMAP. Moduli: `clustering.py`, `dpmm_clustering.py`, `reporter.py`, `similarity_checker.py`, `similarity_analysis.py`, `ablation.py`, `stability.py`, `timeslide.py`, `full_analysis.py`.

---

## 2. Architettura della Pipeline — Flusso Dati

### Pipeline V2 Production (Top-K Patch MIL 384D)
```
[Input] Raw Strain HDF5 (GWOSC O4a, H1/L1)
           │
           ▼
       core/data_loader.py
           │
           ▼
       core/preprocessor.py + core/parallel_processor.py
       ┌─────────────────────────────────┐
       │ Q-Transform → PNG 256×256       │
       └─────────────────────────────────┘
           │
           ▼
       pipeline_v2_production/patch_production.py
       ┌─────────────────────────────────┐
       │ DINOv2 frozen (core/encoder)    │
       │ Extraction Patch Tokens (14x14) │
       │ L2-norm MIL Pooling Top-K → 384D│
       │ Vector Quantization compression │
       │ GEV Thresholding                │
       │ Output: novelties.h5 (SWMR)     │
       └─────────────────────────────────┘
           │
           ▼
       pipeline_v2_production/production_cluster.py
       ┌─────────────────────────────────┐
       │ Adaptive PCA (90% var / n-1)    │
       │ DPMM (Conditional Covariance)   │
       │ Output: cluster_report.json     │
       └─────────────────────────────────┘
           │
           ▼
       pipeline_v2_production/production_report.py
       ┌─────────────────────────────────┐
       │ Saliency Map overlay (cv2 upsmpl)│
       │ Markdown full_discovery_report  │
       └─────────────────────────────────┘
           │
           ▼
       pipeline_v2_production/aggregate_report.py
       ┌─────────────────────────────────┐
       │ Cross-session Deduplication     │
       │ Taxonomy separation (Table 3a/b)│
       │ Spearman stability defense      │
       └─────────────────────────────────┘
```

---

## 3. CLI — `main.py`
Divisa logicamente secondo la nuova struttura (V2 vs V1):

1. **Core & Data Acquisition**: `fetch`, `scan`, `scan-extended`, `fetch-raw`, `last-gps`
2. **Pipeline V2 Production (O4a 384D)**: `patch-production`, `production-cluster`, `patch-analysis`, `production-report`, `validate-reports`, `aggregate-report`, `live-umap`
3. **Pipeline V1 Legacy (768D Exploratory)**: `encode`, `cluster`, `report`, `full-analysis`, `stability`, `ablation`, `timeslide`, ecc.
4. **Reference Index**: `build-reference`, `validate-reference`, `morphcheck`
5. **Autopilot**: `calibrate-loglikelihood`, `calibrate-threshold`, `scan-live`

---

## 4. Struttura Output per Sessione

### Struttura V2 (Production)
```
data/production/
├── <session_id>_H1/ (o <session_id>_L1/)
│   ├── novelties.h5                     # Dataset SWMR continuo
│   ├── cluster_report_novelties_...json # Report DPMM 384D
│   ├── checkpoint.txt                   # State-aware marker
│   └── report/
│       ├── full_discovery_report_*.md   # Report finale
│       ├── report_status_*.json         # Dati strutturati
│       ├── saliency_gallery/            # Overlay anomalie vs background
│       └── umap_novelties.png           # Proiezione 2D
└── aggregated/                          # Output cross-session
    ├── aggregate_summary.json
    ├── master_candidates.csv
    ├── Table_3a_Confirmed_Local_Glitches.csv
    ├── Table_3b_Unverifiable_Unilateral_Detections.csv
    └── stability_synthesis.log
```

---

## 5. Bug e Debito Tecnico Noti
| ID | File | Problema | Stato |
|----|------|---------|-------|
| BUG-03 | `parallel_processor.py` | `print()` in worker invece di `logger` | ⬜ Aperto |
| BUG-06 | `full_analysis.py` | Default reference path hardcoded | ⬜ Aperto |
| BUG-07 | Vari | Messaggi log/commenti in italiano | ⬜ Aperto |
| BUG-08 | DPMM/UMAP | `random_state` non fissato | ✅ Risolto |

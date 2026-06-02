# Architecture State — Stato Corrente dell'Architettura
<!-- Last updated: 2026-06-02T20:26 | Source: README.md, config.yaml, src/ listing, docs/audit_report.md, requirements.txt -->
<!-- Regola: aggiornare solo con informazioni verificabili dalla repository. Non inventare dati. -->

---

## 1. Moduli `src/` — Inventario Completo

| File | Ruolo | Dipende da | Stato |
|------|-------|-----------|-------|
| `data_loader.py` | Fetch HDF5 da GWOSC, resume via progress.json, chunking 4096s | gwpy, gwosc, h5py | ✅ Stabile |
| `preprocessor.py` | Whitening, bandpass, Q-Transform, generazione PNG 256×256 cividis | scipy, matplotlib, gwpy | ✅ Stabile |
| `parallel_processor.py` | Parallelizza preprocessing su ProcessPoolExecutor | preprocessor, data_loader | ✅ Stabile (print() su worker invece di logger — bug noto) |
| `encoder.py` | DINOv2 inference frozen, CLS token 384-dim L2-norm | torch, torchvision | ✅ Stabile |
| `clustering.py` | PCA → UMAP(10D) → DPMM o HDBSCAN → UMAP(2D) | umap-learn, sklearn | ✅ Stabile |
| `dpmm_clustering.py` | Wrapper per DPMM (BayesianGaussianMixture sklearn) | sklearn | ✅ Stabile |
| `reporter.py` | Generazione report JSON, scatter UMAP, contact sheet | clustering, matplotlib | ✅ Stabile (BUG-01 risolto; BUG-02 risolto) |
| `similarity_checker.py` | KNN cosine morphcheck: KNOWN/AMBIGUOUS/NOVEL | numpy | ✅ Stabile |
| `similarity_analysis.py` | Subvariant similarity report per cluster | similarity_checker | ✅ Stabile |
| `ablation.py` | 4 perturbazioni: grayscale, inverted, shuffled-intensity, random-baseline | encoder, clustering | ✅ Stabile ✅ test_ablation.py |
| `stability.py` | Bootstrap ARI su variazioni hyperparameter | clustering, sklearn | ✅ Stabile ✅ test_stability.py |
| `timeslide.py` | H1-L1 coincidence p-value empirico (shift range ±5000s step 100s) | — | ✅ Stabile ✅ test_timeslide.py |
| `full_analysis.py` | Orchestratore end-to-end: encode → cluster → morphcheck → ablation → stability → timeslide | Tutti i moduli | ✅ Stabile ✅ test_full_analysis.py |
| `indomain_reference_builder.py` | Scarica GPS O3b da Zenodo, processa con nostra pipeline → .npz | encoder, preprocessor | ✅ Stabile |
| `reference_builder.py` | Gravity Spy tar.gz → indice .npz out-of-domain (legacy) | — | ✅ Stabile (sconsigliato per morphcheck) |
| `gravity_spy_checker.py` | Query GPS-based su DB Gravity Spy per crosscheck | sqlalchemy | ✅ Stabile |
| `loglikelihood_calibrator.py` | Calibrazione soglia anomalia DPMM | dpmm_clustering | ✅ Stabile |
| `threshold_calibrator.py` | Calibrazione soglie per-classe per scan_live | encoder, similarity_checker | ✅ Stabile |
| `scan_live.py` | Producer-consumer streaming per classificazione KNOWN/NOVEL in real-time | encoder, threshold_calibrator | ⚠️ Rimandato (instabilità H1 ablation non risolta) |
| `benchmark.py` | Confronto DPMM vs Gravity Spy (ARI benchmark) | clustering | ✅ Presente |
| `benchmark_methods.py` | Metodi helper per benchmark | — | ✅ Presente |
| `logging_utils.py` | Configurazione logger centralizzato | — | ✅ Stabile |
| `utils.py` | Utility generali (session_path, ecc.) | — | ✅ Stabile |
| `wizard.py` | CLI wizard interattivo (avvio senza args) | — | ✅ Stabile |
| `__init__.py` | Package init | — | ✅ Stabile |

**Totale moduli in `src/`:** 25 file Python.

---

## 2. Architettura della Pipeline — Flusso Dati

```
[Input] Raw Strain HDF5 (GWOSC O4a, H1/L1)
           │
           ▼
       data_loader.py
       ┌─────────────────────────────────┐
       │ fetch_open_data() / local HDF5  │
       │ Progress resume (progress.json) │
       │ ThreadPoolExecutor fetch         │
       │ Output: chunk 4096s HDF5        │
       └─────────────────────────────────┘
           │
           ▼
       preprocessor.py + parallel_processor.py
       ┌─────────────────────────────────┐
       │ Chunking: 4096s → 32s segments  │
       │ Whitening → Bandpass [20-2kHz]  │
       │ Q-Transform (qrange=[4,64])     │
       │ Colormap cividis → PNG 256×256  │
       │ ProcessPoolExecutor             │
       └─────────────────────────────────┘
           │ ~N PNG spettrogrammi per detector
           ▼
       encoder.py
       ┌─────────────────────────────────┐
       │ dinov2_vits14_reg (frozen)      │
       │ Input resize → 518px           │
       │ CLS token → 384-dim float32    │
       │ L2 normalization               │
       │ Device: CUDA(64)/MPS(32)/CPU(16)│
       │ Output: (N, 384) numpy array   │
       └─────────────────────────────────┘
           │
           ▼
       clustering.py + dpmm_clustering.py
       ┌─────────────────────────────────┐
       │ PCA(50D): 384 → 50 dims        │
       │ UMAP-A: 50 → 10D (clustering)  │
       │   n_neighbors=30, cosine        │
       │   min_dist=0.0                  │
       │ DPMM: n_components=25          │
       │   anomaly: >50% sotto p5 loglik │
       │ UMAP-B: 50 → 2D (viz solo)     │
       │   min_dist=0.1                  │
       └─────────────────────────────────┘
           │
           ▼
       reporter.py
       ┌─────────────────────────────────┐
       │ cluster_report.json             │
       │ UMAP 2D scatter plot            │
       │ HTML gallery per cluster        │
       │ Contact sheet (PNG grid)        │
       └─────────────────────────────────┘
           │
           ▼
       [Validation Layer — parallelo/orchestrato da full_analysis.py]
       ┌────────────────────────────────────────────────────────┐
       │ similarity_checker.py  → KNN(5) cosine morphcheck     │
       │                          vs indomain_O3b.npz           │
       │                          KNOWN / AMBIGUOUS / NOVEL     │
       │ similarity_analysis.py → Subvariant report per cluster │
       │ ablation.py            → ARI su 4 perturbazioni       │
       │ stability.py           → ARI bootstrap                │
       │ timeslide.py           → p-value empirico H1-L1       │
       └────────────────────────────────────────────────────────┘
```

---

## 3. CLI — 18 Subcommand in `main.py`

### Subcommand ufficialmente documentati
| # | Subcommand | Handler | Usa `--run` | Usa `--session-id` | Note |
|---|-----------|---------|-------------|---------------------|------|
| 1 | `fetch` | `cmd_fetch` | ❌ | ❌ | |
| 2 | `scan` | `cmd_scan` | ✅ | ✅ | |
| 3 | `scan-extended` | `cmd_scan_extended` | ✅ | ✅ | con `--full-analysis` |
| 4 | `fetch-raw` | `cmd_fetch_raw` | ✅ | ❌ | ⚠️ Mancante da README |
| 5 | `last-gps` | `cmd_last_gps` | ✅ | ✅ | ⚠️ Mancante da README |
| 6 | `reprocess-spectrograms` | `cmd_reprocess_spectrograms` | ✅ | ✅ | ⚠️ Mancante da README |
| 7 | `encode` | `cmd_encode` | ✅ | ✅ | |
| 8 | `cluster` | `cmd_cluster` | ✅ | ✅ | |
| 9 | `report` | `cmd_report` | ✅ | ✅ | ⚠️ Mancante da README |
| 10 | `stability` | `cmd_stability` | ✅ | ✅ | |
| 11 | `ablation` | `cmd_ablation` | ✅ | ✅ | |
| 12 | `crosscheck` | `cmd_crosscheck` | ❌ | ❌ | |
| 13 | `timeslide` | `cmd_timeslide` | ✅ | ✅ | |
| 14 | `build-reference` | `cmd_build_reference` | ❌ | ❌ | Out-of-domain (legacy) |
| 15 | `build-indomain-reference` | `cmd_build_indomain_reference` | custom | ❌ | In-domain (raccomandato) |
| 16 | `validate-reference` | `cmd_validate_reference` | ❌ | ❌ | GW150914 → Chirp@0.997 |
| 17 | `morphcheck` | `cmd_morphcheck` | ✅ | ❌ | `--reference` obbligatorio |
| 18 | `full-analysis` | `cmd_full_analysis` | ✅ | ✅ | Orchestratore end-to-end |

> ⚠️ `inspect-colormap` documentato in `docs/STEP.md` ma **NON esiste** in `main.py`.

### Subcommand Autopilot (non nel conteggio 18)
- `calibrate-loglikelihood` — soglia anomalia DPMM
- `calibrate-threshold` — soglie per-classe scan-live
- `scan-live` — streaming KNOWN/NOVEL (rimandato)

---

## 4. Struttura Output per Sessione

```
data/runs/<run>/<session_id>/          # Es: data/runs/o4a/20260520_223147/
├── spectrograms/<detector>/           # PNG 256×256 cividis
├── embeddings/                        # <run>_<det>.npy (N, 384) + metadata.json
├── clusters/<detector>/               # cluster_report.json, umap_*.png, gallery.html
├── morphcheck/                        # morphcheck_*.json per cluster anomalo
├── reports/                           # full_analysis_report.json unificato
├── ablation/                          # ablation_results.json
├── stability/                         # stability_results.json (ARI bootstrap)
├── timeslide/                         # timeslide_results.json (p-value)
└── logs/                              # session.log

data/reference/                        # STATICO — NON versionato in git
  indomain_O3b_H1.npz                  # In-domain reference (raccomandato)
  indomain_O3b_L1.npz
  gravity_spy_index.npz                # Out-of-domain (legacy — non usare per morphcheck)
  gs_classifications_O3b_H1.csv
  trainingsetv1d1.tar.gz               # Source data Gravity Spy

data/raw/                              # HDF5 strain scaricati (git-ignored, caching)
data/autopilot/<session_id>/           # Output scan-live
```

> **Nota path legacy:** Sessioni pre-isolamento (48h) usavano `data/embeddings/` e `data/clusters/` direttamente — percorsi obsoleti, non compatibili con la CLI corrente.

---

## 5. Hardware & Performance

| Device | Supporto | Batch Size | Note |
|--------|----------|-----------|------|
| CUDA (RTX 30XX/40XX) | ✅ Nativo | 64 | Auto-rilevato |
| CUDA (RTX 50XX Blackwell sm_120) | ⚠️ Richiede nightly cu128 | 64 | Fallback CPU se non disponibile |
| Apple MPS (M1/M2/M3/M4) | ✅ Nativo | 32 | Metal Framework |
| CPU (x86_64 / ARM) | ✅ Fallback | 16 | Sempre disponibile |

**Raccomandazione workers:** `--workers 6` su CPU multi-core (es. Ryzen 7800X3D). Default config: 2.
**GWOSC fetch thread cap:** 4 (rate limit GWOSC). Non superare.

---

## 6. Test Coverage

| Modulo | Test file | Stato |
|--------|----------|-------|
| `data_loader.py` | `test_data_loader.py` | ✅ Con mock network |
| `encoder.py` | `test_encoder.py` | ✅ Con mock |
| `gravity_spy_checker.py` | `test_gravity_spy_checker.py` | ✅ Con mock |
| `indomain_reference_builder.py` | `test_indomain_reference_builder.py` | ✅ Con mock |
| `reference_builder.py` | `test_reference_builder.py` | ✅ Con mock |
| `similarity_checker.py` | `test_similarity_checker.py` | ✅ Con mock |
| `ablation.py` | `test_ablation.py` | ✅ NUOVO — perturbation unit + study smoke (mocked) |
| `stability.py` | `test_stability.py` | ✅ NUOVO — HDBSCAN+DPMM mode, ARI symmetry, interpretation |
| `timeslide.py` | `test_timeslide.py` | ✅ NUOVO — GPS parsing, coincidence logic, full run_timeslide |
| `full_analysis.py` | `test_full_analysis.py` | ✅ NUOVO — smoke test, failure cases, skip_timeslide flag |
| `reporter.py` | `test_reporter.py` | ✅ NUOVO — JSON report, UMAP plot, contact sheet, print_summary |

**Run test suite:** `pytest tests/ -v` | `pytest tests/ -v --run-slow` | `pytest tests/ -v --cov=src`

---

## 7. Bug e Debito Tecnico Noti (da `docs/audit_report.md`)

| ID | File | Riga | Problema | Severità | Stato |
|----|------|------|---------|---------|-------|
| BUG-01 | `reporter.py` | 297 | `cmap="viridis"` hardcoded in `_make_contact_sheet()` | Media | ✅ Risolto (ARCH-01) |
| BUG-02 | `reporter.py` | 107-118 | Parametri pipeline hardcoded nel JSON | Bassa | ✅ Risolto (ARCH-02) |
| BUG-03 | `parallel_processor.py` | 43,65,75 | `print()` in worker invece di `logger` | Bassa | ⬜ Aperto |
| BUG-04 | `timeslide.py` | — | `iterations=50` hardcoded vs `100` in config | Bassa | ⬜ Aperto (ARCH-07) |
| BUG-05 | `timeslide.py` | 113 | Shift range `[-5000,+5000], step=100` hardcoded | Bassa | ⬜ Aperto (ARCH-08) |
| BUG-06 | `full_analysis.py` | 282 | Default reference path hardcoded | Bassa | ⬜ Aperto |
| BUG-07 | Vari | — | Messaggi log/commenti in italiano | Cosmetic | ⬜ Aperto |
| BUG-08 | DPMM/UMAP | — | `random_state` non fissato | Media | ✅ Risolto (ARCH-03) |

---

## 8. Dipendenze Esterne Critiche

| Risorsa | URL / DOI | Uso |
|---------|-----------|-----|
| DINOv2 model weights | Scaricati da `torch.hub` (~90 MB) | Encoder |
| Gravity Spy O3b GPS | DOI: 10.5281/zenodo.5649212 | In-domain reference |
| GWOSC O4a strain | https://gwosc.org/ | Raw data |
| gwpy OSDF (opzionale) | `--osdf` flag | Fast fetch alternativo |

---

## 9. TODOs Architetturali

| ID | Task | Priorità | Prerequisiti | Stato |
|----|------|---------|-------------|-------|
| ARCH-01 | Risolvere `cmap="viridis"` in `reporter.py:297` | Alta | Nessuno | ✅ Già risolto in versione corrente |
| ARCH-02 | Leggere parametri da config in JSON report (`reporter.py`) | Media | Nessuno | ✅ Già risolto in versione corrente |
| ARCH-03 | Fissare `random_state` in DPMM e UMAP (`config.yaml` + moduli) | Media | Nessuno | ✅ Risolto 2026-06-02: `random_state: 42` in `config.yaml`, propagato in `run_full_pipeline` → PCA, UMAP-A, DPMM, UMAP-B |
| ARCH-04 | Aggiungere test per `ablation.py`, `stability.py`, `timeslide.py`, `full_analysis.py`, `reporter.py` | Media | Nessuno | ✅ Risolto 2026-06-02: 5 nuovi file di test, 50 test, 50/50 pass |
| ARCH-05 | Supporto Virgo V1 in `timeslide.py` e `full_analysis.py` | Bassa | Dati O4b | ⬜ Aperto |
| ARCH-06 | Multi-Q Analysis: `generate_multiq_spectrograms` in `parallel_processor.py` + CLI subcommand | Bassa | ARCH-03 | ⬜ Aperto |
| ARCH-07 | Allineare `timeslide.iterations` tra `config.yaml` (100) e codice (50 hardcoded) | Bassa | Nessuno | ⬜ Aperto |
| ARCH-08 | Rendere configurabile il shift range in `timeslide.py:113` | Bassa | Nessuno | ⬜ Aperto |

# Project Overview — Memoria Centrale del Progetto
<!-- Last updated: 2026-06-02 | Source: README.md, RESULTS.md, config.yaml, CITATION.cff, docs/TODO.md, docs/SESSION_HANDOFF.MD -->
<!-- Regola: aggiornare solo con informazioni verificabili dalla repository. Non inventare dati. -->

---

## 1. Identità del Progetto

| Campo | Valore |
|-------|--------|
| **Nome repo** | `gravi-signal-ml` (`dante-gravi-signal-ml` su GitHub) |
| **GitHub** | https://github.com/lucacirfeta/dante-gravi-signal-ml |
| **Autore** | Luca Cirfeta (ORCID: 0009-0000-1235-3186) — Capgemini / Independent Researcher, Rome, IT |
| **Licenza** | Apache 2.0 |
| **Versione** | 1.0.0 (rilasciata 2026-05-01) |
| **DOI software** | [10.5281/zenodo.20121859](https://doi.org/10.5281/zenodo.20121859) |
| **DOI articolo** | [10.5281/zenodo.20121860](https://doi.org/10.5281/zenodo.20121860) |
| **Preprint arXiv** | [2605.28572](https://arxiv.org/abs/2605.28572) (astro-ph.IM, pubblicato 2026-05-28) |
| **Python minimo** | 3.11+ (testato su 3.13.2 — vedi note h5py) |

---

## 2. Missione Scientifica

L'obiettivo primario è la **caratterizzazione morfologica non supervisionata dei transienti di rumore strumentale (glitch)** nei dati di strain gravitazionale LIGO O2–O4a (H1 Hanford e L1 Livingston), senza dati etichettati, senza fine-tuning, e con accelerazione hardware nativa (CUDA/MPS).

La pipeline raggruppa spettrogrammi Q-transform in uno spazio latente costruito da un foundation model di computer vision (DINOv2) congelato, identifica cluster anomali via DPMM log-likelihood, e li incrocia con un indice di riferimento in-domain (O3b Gravity Spy) per classificarli come KNOWN, AMBIGUOUS o NOVEL.

> **Nota su Virgo (V1):** Virgo non ha partecipato a O4a (commissioning). La pipeline supporta solo H1 e L1 per O4a. Virgo è rientrata in O4b.

---

## 3. Stack Tecnico (verificato da `requirements.txt` e `docs/SESSION_HANDOFF.MD`)

| Layer | Tecnologie |
|-------|-----------|
| **GW data** | gwpy ≥ 3.0.13, gwosc ≥ 0.7.1, h5py ≥ 3.10, astropy ≥ 6.0 |
| **Signal processing** | numpy ≥ 1.26, scipy ≥ 1.12 |
| **ML/DL** | torch ≥ 2.1.0, torchvision ≥ 0.16.0, DINOv2 via `torch.hub` (~90 MB) |
| **Clustering** | umap-learn ≥ 0.5.6, scikit-learn ≥ 1.3.0 (HDBSCAN + DPMM via sklearn) |
| **Immagini** | Pillow ≥ 10.0.0, scikit-image ≥ 0.21.0 |
| **Database** | SQLAlchemy ≥ 2.0, psycopg2-binary ≥ 2.9, pandas ≥ 2.0 |
| **Dev** | pytest ≥ 8.0, ruff ≥ 0.3, mypy ≥ 1.8, pre-commit ≥ 3.6 |

**Note critiche:**
- DINOv2 si scarica via `torch.hub` — nessun pacchetto pip separato necessario.
- `trainingsetv1d1.h5` è **incompatibile** con h5py ≥ 3.12 su Python 3.13 → usare sempre il tar.gz.
- RTX 5070 (Blackwell sm_120): richiede PyTorch nightly cu128 (non supportato da stable build).

---

## 4. Pipeline End-to-End (verificata da `README.md` e `src/`)

```
Raw Strain HDF5 (GWOSC O2–O4a)
         │
         ▼
[data_loader.py]       gwpy fetch_open_data() / local HDF5
                       Parallel fetch: ThreadPoolExecutor
                       Resume intelligente via progress.json
                       Chunk a 4096s
         │
         ▼
[preprocessor.py /     Chunking 4096s → 32s
 parallel_processor.py] Whitening → Bandpass [20–2000 Hz]
                       Q-Transform (qrange=[4,64], frange=[20,2048])
                       Colormap: cividis (256×256 PNG)
                       Parallelizzazione: ProcessPoolExecutor
         │
         ▼ 256×256 PNG spectrograms
[encoder.py]           dinov2_vits14_reg (ViT-S/14 + register tokens)
                       Pesi congelati — zero training
                       CLS token → 384-dim vettore L2-normalizzato
                       Hardware: CUDA(64)/MPS(32)/CPU(16) batch size auto
         │
         ▼
[clustering.py /       PCA(50D) → UMAP(10D, cosine, min_dist=0.0)
 reporter.py]          DPMM (default) o HDBSCAN
                       DPMM anomaly: clusters con >50% samples sotto
                         il 5° percentile della log-likelihood
                       UMAP(2D) separato solo per visualizzazione
         │
         ▼
[Validation Layer]
  similarity_checker.py   — KNN cosine morphcheck (K=5)
  similarity_analysis.py  — Subvariant similarity report
  ablation.py             — ARI su 4 perturbazioni (grayscale, inverted,
                            shuffled-intensity, random-baseline)
  stability.py            — ARI bootstrap su variazioni hyperparameter
  timeslide.py            — H1-L1 coincidence p-value (50 shift, ±5000s, step 100s)
  full_analysis.py        — Orchestratore end-to-end
         │
         ▼
[Autopilot / Live Scan]
  threshold_calibrator.py     — Calibrazione soglie per-classe (percentile cosine)
  loglikelihood_calibrator.py — Calibrazione soglia anomalia DPMM
  scan_live.py                — Scanner streaming producer-consumer (KNOWN/NOVEL)
```

---

## 5. Parametri di Configurazione Chiave (`config.yaml`)

| Parametro | Valore | Note |
|-----------|--------|------|
| `preprocessing.sample_rate` | 4096 Hz | |
| `preprocessing.f_low/f_high` | 20.0 / 2000.0 Hz | |
| `preprocessing.qrange` | [4, 64] | Standard Q |
| `preprocessing.frange` | [20, 2048] | |
| `preprocessing.output_size` | [256, 256] | |
| `preprocessing.colormap` | cividis | Uniformità percettiva obbligatoria |
| `encoder.model` | dinov2_vits14_reg | ViT-S/14 con register tokens |
| `encoder.embedding_dim` | 384 | dim del CLS token |
| `encoder.input_size` | 518 | |
| `clustering.algorithm` | dpmm | default; HDBSCAN disponibile |
| `clustering.pca_components` | 50 | |
| `clustering.dpmm.n_components` | 25 | |
| `clustering.dpmm.anomaly_percentile` | 5.0 | |
| `clustering.dpmm.anomaly_threshold` | 4.0191 | calibrated fixed threshold |
| `clustering.umap_clustering` | 10D, cosine, n_neighbors=30, min_dist=0.0 | |
| `clustering.umap_viz` | 2D, cosine, n_neighbors=30, min_dist=0.1 | solo visualizzazione |
| `similarity.k_neighbors` | 5 | |
| `similarity.novelty_threshold` | 0.85 | cosine < 0.85 → NOVEL |
| `similarity.consensus_threshold` | 0.60 | |
| `timeslide.iterations` | 100 | (hardcoded 50 in cmd_timeslide e full_analysis) |
| `timeslide.window` | 32 s | |
| `hardware.cuda_batch_size` | 64 | |
| `hardware.mps_batch_size` | 32 | |
| `hardware.cpu_batch_size` | 16 | |
| `indomain_reference.zenodo_doi` | 10.5281/zenodo.5649212 | Gravity Spy O3b GPS |
| `indomain_reference.min_confidence` | 0.95 | |
| `indomain_reference.max_per_class` | 30 | |

---

## 6. Assunzioni Metodologiche Fondamentali

1. **Transfer Learning Morfologico:** Si assume che DINOv2, addestrato su immagini naturali (~142M), catturi le feature topologiche necessarie a discriminare i glitch GW senza fine-tuning.
2. **Register Tokens:** I token "register" di `dinov2_vits14_reg` eliminano artefatti globali spaziali dei ViT, rendendo il clustering geometricamente più coerente.
3. **DPMM vs HDBSCAN:** HDBSCAN causava mega-cluster (>80% campioni) biasati dall'intensità luminosa. DPMM con metrica coseno in 10D risolve questo problema determinando automaticamente il numero di cluster.
4. **Due UMAP Pass:** UMAP 10D+cosine per clustering; UMAP 2D separato solo per visualizzazione.
5. **Cividis:** Sostituisce viridis per uniformità percettiva e riduzione del bias geometrico da luminosità.
6. **Sessione Isolation:** Ogni run genera un ID timestamp univoco (`YYYYMMDD_HHMMSS`); tutto viene salvato sotto `data/runs/<run>/<session_id>/`.

---

## 7. Esito Scientifico Principale (Null Result)

**In 1.277 ore di dati O4a analizzate (4 sessioni), nessun cluster morfologicamente NOVEL è stato identificato.** Tutti i cluster anomali mappano su classi Gravity Spy esistenti con cosine similarity > 0.98, oppure sono ascrivibili a fondo continuo.

Questo risultato ("null result") è stato analizzato a fondo tramite una **Mock Data Challenge (MDC)** ufficiale, pubblicata nel paper [arXiv:2606.06237](https://arxiv.org/abs/2606.06237). L'MDC ha dimostrato che il null result stabilisce una baseline riproducibile zero-shot per la caratterizzazione morfologica dei glitch, ma soggiace a un limite architetturale invalicabile: l'effetto di **Signal Dilution** (causato dal token `[CLS]`), che nasconde i glitch che occupano <5% della griglia di patch temporale/spettrale (es. `SpiralBurst`, `NarrowChirp`, `HarmonicComb`) nel rumore di fondo altamente non-Gaussiano (Generalized Extreme Value distribution). Questo null result è valido condizionalmente al regime di sensibilità architetturale e non esclude anomalie fisiche a banda stretta o impulsive brevi.

**Benchmark DPMM vs Gravity Spy:** ARI = 0.133 (CTSAE supervisionato ottiene 0.409 su stesso dataset). Questo dimostra che la similarità morfologica visuale DINOv2 non mappa deterministicamente sulle categorie fisiche/umane di Gravity Spy — divergenza fondamentale di classificazione discussa nel preprint.

---

## 8. Metodi di Validazione Utilizzati

| Metrica | Scopo | Modulo |
|---------|-------|--------|
| **ARI (Adjusted Rand Index)** | Robustezza clustering (stability + ablation) | `stability.py`, `ablation.py` |
| **Cosine Similarity KNN=5** | Morphcheck KNOWN/AMBIGUOUS/NOVEL | `similarity_checker.py` |
| **Silhouette Score** | Qualità geometrica cluster (10D e 50D) | `clustering.py` / `reporter.py` |
| **DB Index** | Compattezza e separazione cluster | `clustering.py` / `reporter.py` |
| **Time-slide p-value** | Background coincidence H1-L1 (empirical) | `timeslide.py` |
| **GW150914 validation** | Sanity check reference (Chirp @ 0.997) | `validate-reference` subcommand |

Ablation variants implementate in `ablation.py`: `grayscale`, `inverted`, `shuffled-intensity`, `random-baseline`.

---

## 9. Confronto con Metodi Coevi (da `docs/COMPARISON.md`)

| Approccio | Tipo | Pro | Contro |
|-----------|------|-----|--------|
| **Questo (DINOv2+DPMM)** | Unsupervised, zero-training | Generalizzabile, nessun label | Domain gap, no validazione aux channels |
| **Ferreira et al. (t-SNE)** | Unsupervised | Correlazioni strumentali fisiche | t-SNE non preserva distanze globali |
| **Li et al. CTSAE** | Unsupervised autoencoder | In-domain, specifico per glitch | Addestramento costoso, meno generalizzabile |
| **Xiao et al. TDFAE (KAN+ViT)** | Unsupervised | Alta performance | Architettura molto complessa |
| **Wu et al. Gravity Spy O4** | Supervised | Standard LIGO, produzione | Non rileva classi nuove per definizione |

---

## 10. Limitazioni Documentate (da `README.md`)

1. **DINOv2 domain gap:** Addestrato su immagini naturali, non su spettrogrammi fisicamente motivati.
2. **UMAP distorsione globale:** Preserva struttura locale, distorce distanze globali. Cluster anomali potrebbero riflettere artefatti di preprocessing.
3. **Assenza canali ausiliari:** Solo strain H1/L1. Nessun incrocio con canali ambientali/strumentali per confermare l'origine fisica delle anomalie.
4. **Morfologie fisicamente distinte ma visivamente simili:** Classi fisicamente diverse ma spettrogrammaticamente simili non verrebbero distinte.
5. **OOD Blindness / Signal Dilution:** Come dimostrato in [arXiv:2606.06237](https://arxiv.org/abs/2606.06237), il global average pooling del token `[CLS]` di DINOv2 diluisce i segnali localizzati (occupanti <5% della griglia). Le morfologie a banda molto stretta o durata impulsiva non possono superare le rigorose soglie empiriche (es. $\tau_\mathrm{op} = 0.874$), rendendo la pipeline ceca verso di esse indipendentemente dal loro SNR (massimo Recall = 0). L'assunzione Gaussiana (soglie $k-\sigma$) è matematicamente scorretta per questo task poiché la coda di distribuzione è governata da una Generalized Extreme Value (GEV).

---

## 11. Problemi Aperti e Roadmap (da `docs/TODO.md`, aggiornato 2026-05-18)

### Priorità Alta (bloccanti)
- [TODO] Testare DINOv2 **ViT-B/14** (768-dim) su H1 per mitigare asimmetria ablation H1 vs L1
- [TODO] Costruire riferimento in-domain **O4a** (attualmente basato su O3b → temporal domain shift)
- [TODO] Estrarre embedding da **blocchi intermedi** DINOv2 per validare il transfer learning

### Priorità Media
- [TODO] Confronto esplicito con CTSAE e t-SNE O4a (ARI, stabilità, morphcheck)
- [TODO] Calibrazione soglia DPMM (log-likelihood vs background)
- [TODO] Analisi distribuzione similarità per cluster anomalo

### Priorità Bassa / Sperimentale
- [TODO] Multi-Q Analysis (qrange=[4,16], [16,64], [64,256]) — solo dopo ViT-B/14
- [TODO] Integrazione completa Virgo (V1) in `timeslide.py` e `full_analysis.py`
- [TODO] Fissare `random_state` in DPMM e UMAP per riproducibilità esatta
- [TODO] Documentare varianza spiegata PCA (384D → 50D)

---

## 12. CLI — Comandi Disponibili (18 subcommand, da `docs/audit_report.md`)

`fetch`, `scan`, `scan-extended`, `fetch-raw`, `last-gps`, `reprocess-spectrograms`, `encode`, `cluster`, `report`, `stability`, `ablation`, `crosscheck`, `timeslide`, `build-reference`, `build-indomain-reference`, `validate-reference`, `morphcheck`, `full-analysis`

Autopilot: `calibrate-loglikelihood`, `calibrate-threshold`, `scan-live`

> Nota: `inspect-colormap` è documentato in `docs/STEP.md` ma **non esiste** in `main.py`.

Entry point: `python main.py` (wizard interattivo se invocato senza argomenti).

---

## 13. Struttura Output per Sessione

```
data/runs/<run>/<session_id>/
├── spectrograms/<detector>/   # PNG Q-transform 256x256 cividis
├── embeddings/                # .npy array 384-dim + .json metadata
├── clusters/<detector>/       # report JSON, scatter UMAP, HTML gallery
├── morphcheck/                # report individuali per cluster
├── reports/                   # full-analysis unificato
├── ablation/                  # risultati ablation study
├── stability/                 # ARI bootstrap
├── timeslide/                 # background p-value
└── logs/                      # log sessione
data/reference/                # STATICO — indici .npz (git-ignored)
  indomain_O3b_H1.npz
  indomain_O3b_L1.npz
```

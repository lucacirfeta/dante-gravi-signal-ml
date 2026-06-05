# Decisions Log — Registro Decisioni Architetturali
<!-- Last updated: 2026-06-02T20:26 | Source: README.md, config.yaml, docs/audit_report.md, docs/TODO.md, docs/SESSION_HANDOFF.MD -->
<!-- Regola: aggiornare solo con decisioni verificabili dalla repository. Indicare la fonte. -->

---

## 1. Decisioni Consolidate (Irrevocabili)

### D-01 — Encoder: DINOv2 con Register Tokens
- **Modello:** `dinov2_vits14_reg` (ViT-S/14 + register tokens, 384-dim CLS)
- **Motivazione:** I token "register" di Darcet et al. 2023 (arXiv:2309.16588) puliscono l'embedding globale da artefatti spaziali che affliggono i ViT standard. Senza register, i ViT allocano feature globali in patch spaziali arbitrarie. Con register, il clustering è geometricamente più coerente.
- **Alternativa scartata:** `dinov2_vits14` (senza register) — testato, produce cluster meno coerenti.
- **Stato:** ✅ Definitivo. Non cambiare.
- **Fonte:** `README.md` §Critical Design Choices, `encoder.py`, `config.yaml`

### D-02 — Clustering: DPMM al posto di HDBSCAN
- **Algoritmo default:** DPMM (Dirichlet Process Mixture Model) con metrica coseno su UMAP 10D.
- **Motivazione:** HDBSCAN causava aggregazioni eccessive (>80% campioni in un mega-cluster) biasate dall'intensità luminosa della colormap. DPMM determina automaticamente il numero di cluster e quantifica le anomalie via log-likelihood: un cluster è marcato anomalo se >50% dei suoi membri ha log-likelihood sotto il 5° percentile.
- **Alternativa disponibile:** HDBSCAN rimane configurabile in `config.yaml` (`clustering.algorithm: hdbscan`) con parametri: `min_cluster_size: 15`, `min_samples: 10`, `cluster_selection_method: eom`.
- **Stato:** ✅ Definitivo. DPMM è il default.
- **Fonte:** `README.md` §Critical Design Choices, `config.yaml`, `clustering.py`

### D-03 — Colormap: cividis al posto di viridis
- **Valore:** `preprocessing.colormap: cividis` in `config.yaml`
- **Motivazione:** Uniformità percettiva di cividis riduce il bias geometrico da luminosità che storicamente causava mega-cluster con HDBSCAN. Viridis non è percettivamente uniforme.
- **Bug noto:** RISOLTO — il `cmap=` in `_make_contact_sheet()` era un remnant inerte (applicato su PNG già renderizzate). Confermato non presente nel codice corrente.
- **Stato:** ✅ Definitivo. Cividis obbligatorio ovunque.
- **Fonte:** `README.md`, `config.yaml`, `docs/audit_report.md` §1.3

### D-04 — Riduzione Dimensionale: Due UMAP Pass
- **Pass A (clustering):** UMAP 10D, cosine, n_neighbors=30, min_dist=0.0 → input per DPMM.
- **Pass B (visualizzazione):** UMAP 2D, cosine, n_neighbors=30, min_dist=0.1 → solo scatterplot.
- **Motivazione:** min_dist=0.0 nel Pass A massimizza la separazione locale per DPMM; min_dist=0.1 nel Pass B produce visualizzazioni meno crowded. DPMM opera sul Pass A, mai sul Pass B.
- **Pre-processing:** PCA(50D) prima di entrambi i UMAP pass (riduce il rumore in 384D prima del manifold learning).
- **Stato:** ✅ Verificato da `clustering.py` e confermato da `docs/audit_report.md` §1.3.
- **Fonte:** `config.yaml`, `clustering.py`, `README.md`

### D-05 — Parallelizzazione Ibrida (Micro-Locking)
- **CPU:** `ThreadPoolExecutor` per fetch dati (I/O bound); `ProcessPoolExecutor` per Q-transform (CPU bound).
- **GPU:** Inference DINOv2 con batch pipelined. Lock millisecondo-livello. VRAM flush istantaneo tra batch.
- **Default workers:** `performance.default_workers: 2` (safe su qualsiasi hardware). Raccomandato: 6 su CPU multi-core (es. Ryzen 7800X3D).
- **GWOSC fetch threads:** Hard cap a 4 per non superare rate limit GWOSC.
- **Stato:** ✅ Definitivo.
- **Fonte:** `README.md`, `config.yaml`

### D-06 — Session ID Isolation
- **Meccanismo:** Ogni run genera `session_id = YYYYMMDD_HHMMSS`. Tutti gli output vanno sotto `data/runs/<run>/<session_id>/`.
- **Motivazione:** Previene overwrite involontari tra sessioni diverse. Permette il confronto storico.
- **Stato:** ✅ Verificato da `docs/audit_report.md` §1.3 (Session isolation — CORRECT).
- **Fonte:** `README.md`, `docs/SESSION_HANDOFF.MD`, `docs/audit_report.md`

### D-07 — Reference Index In-Domain (vs Out-of-Domain)
- **Soluzione adottata:** `indomain_reference_builder.py` scarica i GPS timestamps da Gravity Spy Zenodo (DOI: 10.5281/zenodo.5649212), preleva il raw strain da GWOSC, e processa con la **nostra pipeline** (stesso Q-transform, stessa colormap, stessa normalizzazione). Produce `indomain_O3b_H1.npz` / `indomain_O3b_L1.npz`.
- **Problema che risolve:** Il riferimento out-of-domain (PNG diretti da Gravity Spy) ha un domain gap per parametri Q-transform, normalizzazione colore e dimensioni immagine diversi.
- **Validazione:** GW150914 mappa su Chirp con cosine similarity 0.997 usando il reference in-domain.
- **Stato:** ✅ Definitivo. Non usare mai `gravity_spy_index.npz` per morphcheck.
- **Fonte:** `indomain_reference_builder.py`, `docs/SESSION_HANDOFF.MD`, `docs/audit_report.md` §1.4

### D-08 — Finestra Temporale: 32 secondi
- **Valore:** `indomain_reference.segment_duration: 32.0` / chunking a 32s in preprocessing.
- **Motivazione:** Compromesso tra risoluzione temporale e contenuto informativo dello spettrogramma.
- **Limitazione nota (verificata):** La finestra fissa potrebbe perdere transienti su scale inferiori al secondo. Un esperimento (`test_window_hypothesis.py`) sembrava indicare che finestre più corte aumentassero la sensitivity del morphcheck. Tuttavia, questo esperimento era **metodologicamente viziato**: le iniezioni avvenivano su strain già sbiancato, bypassando il filtro della PSD reale del rivelatore. Ripetendo l'esperimento con la metodologia corretta (iniezione su raw strain + whitening fisico), la sensitività *diminuisce* al diminuire della finestra. Il multi-scale windowing è pertanto **scartato** come soluzione al problema del Recall=0.00 nel MDC.
- **Stato:** ✅ Definitivo per O4a. Il vero fix al Recall=0.00 è il Dynamic Thresholding (D-10).
- **Fonte:** `config.yaml`, `README.md`, `scratch/sanity_check.py`, `scratch/baseline_variance_test.py`

### D-09 — Timeslide: 50 Shift, Finestra ±5000s, Step 100s
- **Implementazione:** `timeslide.py` esegue shift su timestamps L1 nel range `[-5000, +5000]s` in step di 100s, escludendo 0. Calcola coincidenze a zero-lag e p-value empirico.
- **Nota discrepanza:** `config.yaml` specifica `timeslide.iterations: 100`, ma `cmd_timeslide` e `full_analysis.py` passano `iterations=50` hardcoded. Il valore effettivo usato è **50** (da `docs/audit_report.md` §1.3).
- **Stato:** ✅ Funzionale. La discrepanza `config.yaml` vs hardcoded è un bug noto.
- **Fonte:** `timeslide.py`, `docs/audit_report.md` §1.3

### D-10 — Dynamic Threshold per Morphcheck (vs Global Static)
- **Metodo:** `assess_novelty_dynamic()` in `src/similarity_checker.py`. Invece di confrontare `max_similarity` con una soglia globale fissa (0.85), calcola uno **score adattivo relativo al noise floor locale della sessione**:
  ```
  novelty_score = baseline_mean - max_similarity
  NOVEL se novelty_score > k_sigma * baseline_std
  ```
- **Motivazione fisica:** Il DINOv2 embedding space di strain LIGO sbiancato è empiricamente molto stabile (misurato su L1 O4a, n=30 segmenti NULL consecutivi, 4s window): `mean=0.940, std=0.021`. La soglia fissa di 0.85 è sempre inferiore al noise floor reale (~0.94), causando Recall=0.00 per tutti i glitch sintetici testati. Un glitch SpiralBurst con SNR>130 produce un drop a ~0.86, che è **-3.7 sigma** dalla baseline, non rilevabile da una soglia fissa ma pienamente rilevabile con il criterio sigma-based.
- **Parametri:** `k_sigma=2.5` (FAR teorico ~0.6% su rumore gaussiano). Soglia effettiva: `0.940 - 2.5×0.021 = 0.888`.
- **Fallback:** Se la baseline live non può essere calcolata (< 20 NULL segments), usa i valori empirici L1 O4a da `config.yaml.similarity.dynamic_threshold`.
- **Condizioni di validità:** `std < 0.03`. Verificato: L1 O4a `std=0.021`. Se `std ≥ 0.03`, il delta di segnale è statisticamente irrecuperabile con questo approccio (non verificato per H1 ancora).
- **Contributto metodologico (paper):** Questo approccio è pubblicabile come contributo indipendente — è il primo ad applicare un criterio di anomaly detection sigma-based nel cosine embedding space di un ViT pre-trainato su dati astronomici reali di LIGO.
- **Stato:** ✅ Implementato (2026-06-04). Integrato in `run_mdc()` di `src/injection.py`. Da validare su H1.
- **File:** `src/similarity_checker.py` (`assess_novelty_dynamic`, `compute_baseline_stats`), `src/injection.py` (`run_mdc`), `config.yaml` (`similarity.dynamic_threshold`)
- **Esperimento:** `scratch/baseline_variance_test.py` (30 segmenti L1), `scratch/sanity_check.py` (SpiralBurst SNR=134.8)

### D-11 — Calibrazione Empirica della Soglia Operativa (GEV)
- **Metodo:** L'impostazione di $\tau_\mathrm{op} = 0.874$ basata sul 5° percentile ($\times 10^{-5}$) della distribuzione empirica calcolata su 188.142 segmenti O4a di background.
- **Motivazione statistica:** Come dimostrato nel paper (arXiv:2606.06237), la distribuzione di background nello spazio coseno di DINOv2 è fortemente asimmetrica a sinistra (skewness = -4.12, kurtosis = 15.38) e segue una distribuzione GEV (Generalized Extreme Value), rendendo completamente inadeguate le soglie Gaussiane $k-\sigma$ (richiederebbero $k \approx 23.9$). 
- **Stato:** ✅ Pubblicato su arXiv:2606.06237 come standard di calibrazione riproducibile per anomaly detection ViT-based.
- **Fonte:** Paper arXiv:2606.06237, `README.md`, `project_overview.md`

---

## 2. Decisioni Aperte / Bug Noti

### D-OPEN-01 — `reporter.py` hardcoda parametri nel JSON
- **Problema:** `reporter.py` linee 107-118 scrivono `pca_components: 50`, `n_neighbors: 20`, `min_dist: 0.0`, `min_samples: 3` nel `cluster_report.json` invece di leggere dal config effettivo. Il JSON persisted potrebbe non riflettere i parametri reali.
- **Priorità:** Bassa (non impatta i risultati, solo la tracciabilità).
- **Fonte:** `docs/audit_report.md` §1.1

### D-OPEN-02 — Discrepanza `timeslide.iterations` (100 in config, 50 hardcoded)
- **Fonte:** `docs/audit_report.md` §1.3

### D-OPEN-03 — Remnant viridis in `reporter.py:297`
- **Stato:** ✅ RISOLTO 2026-06-02 — confermato non presente nel codice corrente.
- **Fonte:** `docs/audit_report.md` §1.3

### D-OPEN-04 — Messaggi di log in italiano in codice
- **File coinvolti:** `timeslide.py:141`, `parallel_processor.py`, `cmd_fetch_raw`.
- **Problema:** Un progetto open-source internazionale dovrebbe usare inglese.
- **Fonte:** `docs/audit_report.md` §1.5

### D-OPEN-05 — `random_state` non fissato in DPMM e UMAP
- **Stato:** ✅ RISOLTO 2026-06-02 — `random_state: 42` aggiunto in `config.yaml[clustering]`, propagato da `run_full_pipeline` a PCA, UMAP-A, DPMM, UMAP-B.
- **Fonte:** `docs/TODO.md` §7, `src/clustering.py`

### D-OPEN-06 — Nessun test per moduli Phase 3.3+
- **Stato:** ✅ RISOLTO 2026-06-02 — Creati `test_ablation.py`, `test_stability.py`, `test_timeslide.py`, `test_full_analysis.py`, `test_reporter.py`. 50/50 test passing.
- **Fonte:** `docs/audit_report.md` §1.2

---

## 3. TODOs Architetturali Futuri

| ID | Decisione / Feature | Prerequisiti | Stato |
|----|---------------------|-------------|-------|
| D-FUTURE-01 | ViT-B/14 (768-dim) — test su H1 | Nessuno | [DEGRADED] O3a ha risolto l'asimmetria H1 |
| D-FUTURE-02 | Multi-Q Analysis (3 qrange concatenati, 1152-dim) | D-FUTURE-01 | [TODO] |
| D-FUTURE-03 | In-domain reference O4a (sostituire O3b) | Nessuno | [TODO] |
| D-FUTURE-04 | Supporto completo V1 (Virgo) in timeslide + full_analysis | Disponibilità dati O4b | [TODO] |
| D-FUTURE-05 | Embedding da blocchi intermedi DINOv2 (explainability) | Nessuno | [TODO] |
| D-FUTURE-06 | Fissare random_state in DPMM/UMAP | Nessuno | ✅ DONE — risolto come ARCH-03 |

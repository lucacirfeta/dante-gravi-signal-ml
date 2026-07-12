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

### D-11 - Calibrazione Empirica della Soglia Operativa (P99 + GEV Descriptive)
- **Metodo:** L'impostazione di $\tau_\mathrm{op} = 0.874$ basata sul 5° percentile ($\times 10^{-5}$) della distribuzione empirica calcolata su 188.142 segmenti O4a di background.
- **Motivazione statistica:** Come dimostrato nel paper (arXiv:2606.06237), la distribuzione di background nello spazio coseno di DINOv2 è fortemente asimmetrica a sinistra (skewness = -4.12, kurtosis = 15.38) e segue una distribuzione GEV (Generalized Extreme Value), rendendo completamente inadeguate le soglie Gaussiane $k-\sigma$ (richiederebbero $k \approx 23.9$). 
- **Stato:** ✅ Pubblicato su arXiv:2606.06237 come standard di calibrazione riproducibile per anomaly detection ViT-based.
- **Fonte:** Paper arXiv:2606.06237, `README.md`, `project_overview.md`

### D-12 — Reference Index a Patch-Level (Vector Quantization)
- **Implementazione:** `src/index_builder.py` usa `MiniBatchKMeans` con K adattivo ($K = \min(64, \max(8, N//2))$) su `x_norm_patchtokens` (384-dim) normalizzati in L2 per approssimare la Spherical Cosine Distance.
- **Motivazione:** Il pooling `[CLS]` globale causa signal dilution per glitch deboli (SpiralBurst). L'astrazione a livello di patch cattura le morfologie locali. La Vector Quantization previene l'esplosione dimensionale (KNN), comprimendo tutto il dizionario O3b in soli 281 centroidi prototipali pur mantenendo una copertura superiore all'80% della struttura (95° percentile error < 0.20).
- **Stato:** ✅ Implementato (2026-06-06). Il vecchio indice globale `[CLS]` è obsoleto per anomaly detection locale.
- **Fonte:** `src/index_builder.py`, Logs di run, `walkthrough.md`

### D-13 — Topological Saliency Decoupling (Spatial Background Matrix)
- **Metodo:** `src/saliency_map.py` disaccoppia la generazione della Topologia Spaziale dal Vector Quantized Index (VQ) globale, calcolando l'anomalia visiva *esclusivamente* come distanza coseno contro una Matrice di Mediana Spaziale (1369, 384) precalcolata da segmenti NULL.
- **Motivazione statistica e fisica:** La Q-Transform non è shift-invariant (il rumore varia con la frequenza e ci sono ringing artifacts ai bordi della griglia ViT 37x37). Un indice VQ globalmente clusterizzato penalizza geometricamente i patch periferici, creando massicci falsi positivi spaziali. Inoltre, le similarità di DINOv2 producono fluttuazioni naturali (max/mean ratio > 5.5 per segmenti di solo rumore). Ciò certifica che la Saliency Map NON può essere usata come rilevatore (discriminatore) sul singolo frame, ma unicamente come visualizzatore morfologico *post-hoc*, ri-confermando che il Global Detection vero e proprio deve poggiare sulla distribuzione GEV e il dizionario VQ (D-11).
- **Stato:** ✅ Implementato (2026-06-07). Architettura blindata a due layer: Trigger GEV (su VQ index) → Localizzazione (su Spatial Median Matrix).
- **Fonte:** `src/saliency_map.py`, `scripts/run_saliency_demo.py`, `walkthrough.md`

### D-14 — Peer-Review Wave 3 Defenses (Philosophical Honesty)
- **Metodo:** Adozione di un approccio di "radical intellectual honesty" per placare le critiche sul rigore matematico e architetturale.
- **Decisioni:**
  1. Abbandono della GEV come bound statistico formale per le mean order statistics, relegata a parametrizzazione empirica/euristica.
  2. Dichiarazione esplicita della cecità ai transienti brevi (Blips) come "critical operational limitation" e non come scelta di design.
  3. Promozione dell'Adjusted Rand Index (ARI) a metrica quantitativa principale, declassando il "Validation Triangle" e la soglia di transitivity (0.75) a euristiche puramente qualitative.
  4. Abbandono dell'uso di Gravity Spy come prova di esclusione a favore di prova di Concept Drift.
  5. Riconoscimento formale della distorsione topologica della PCA nello spazio L2 in attesa di vMF-DPMM nativi sferici.
  6. La falsificazione di Family_01 dimostra solo che "non è distinguibile dal rumore stazionario O4a tramite solo strain", richiedendo i canali fisici PEM per il verdetto finale.
- **Stato:** ✅ Implementato (2026-06-17) nel manoscritto LaTeX.
- **Fonte:** `paper_v2_springer.tex`, `scratch/reviewer_defense.md`, Memorix `obs:219`

---

### D-15 — Peer-Review Wave 6 Defenses (Structural Amputations)
- **Metodo:** Ristrutturazione radicale del paper per rispondere a critiche fatali (dealbreakers) sulla statistica e sulla geometria.
- **Decisioni:**
  1. **Rimozione Totale GEV:** L'equazione GEV, la Tabella 1 e la Figura 3 sono state fisicamente amputate dal paper per evitare confusione matematica. La soglia $\tau_{\rm op}$ è definita strettamente come percentile empirico $P_{99}$.
  2. **Statistica Massiccia:** $N_{\rm null}$ corretto da 500 a 150.000 campioni per garantire la solidità statistica del 99° percentile.
  3. **Titolo:** Rinominato il paper aggiungendo "Extended-Transient", accettando formalmente l'incapacità di rilevare transienti sub-secondo (Blips).
  4. **Tautologia Domain Shift:** La narrativa di "scoperta" è stata convertita in "metodo per quantificare il limite inferiore di rilevabilità e fornire un protocollo di background subtraction nativo".
  5. **HDBSCAN vs vMF-DPMM:** Inserita difesa esplicita nella Sezione 3.2.2 spiegando che la PCA è un compromesso computazionale per evitare l'instabilità delle funzioni di Bessel (vMF-DPMM), e che HDBSCAN è stato empiricamente scartato per problemi di mega-cluster collassati nello spazio ViT.
- **Stato:** ✅ Implementato (2026-06-18) nel manoscritto LaTeX.
- **Fonte:** `paper_v2_springer.tex`, `reviewer_6.md`

---

### D-16 — Peer-Review Wave 11 Defenses (Notation & Provenance)
- **Metodo:** Disambiguazione completa dei simboli di soglia operativi e tracciamento rigoroso dei parametri di generazione dei Vector Quantized (VQ) indices.
- **Decisioni:**
  1. **Disambiguazione Thresholds:** Il simbolo `\tau_{\rm op}` era sovrascritto su tre scale incompatibili. È stato disambiguato in: $\tau_{\rm CLS}$ (baseline MDC globale), $\tau_{\rm O3b}$ (baseline storica patch-level), $\tau_{\rm op}$ (produzione P99), e $\tau_{\rm op}^{\rm L1}$ (soglia nativa O4a).
  2. **Disambiguazione DPMM:** Il parametro $n$ della Sezione 5.3.1 (segmenti processati dal DPMM, inclusi i segmenti di background) è stato separato da $n$ (numero di anomalie) in $N_{\rm seg}$ per risolvere il paradosso numerico dei "2700 candidati in L1".
  3. **Conteggio Centroidi O3b:** Corretto un bug documentativo critico. Il paper dichiarava erroneamente 1216 centroidi per l'indice O3b (che ne ha 281, con K adattivo su 23 classi). Il valore 1216 apparteneva in realtà all'indice O4a.
  4. **Documentazione Indice Nativo O4a:** Aggiunta una sottosezione metodologica dedicata all'indice nativo O4a per eliminare l'asimmetria documentativa.
- **Stato:** ✅ Implementato (2026-06-19) nel manoscritto LaTeX.
- **Fonte:** `paper_v2_springer.tex`, `reviewer_11.md`

---

### D-17 — Peer-Review Wave "Final" Defenses (GEV Excision & Production Realignment)
- **Metodo:** Rimozione totale del GEV a favore dell'empirico $P_{99}$ per incompatibilità teorica sui recettivi sovrapposti del ViT, e allineamento ai conteggi reali di produzione O4a.
- **Decisioni:**
  1. La soglia operativa $\tau_{\rm op}^{\rm Det}$ non usa più l'Extreme Value Theorem ma viene calcolata strettamente come il 99° percentile empirico.
  2. Aggiunta tabella di sensibilità sulla fraction $k$ del pooling MIL.
  3. Modifica dell'abstract per non dichiarare come "prova" la stazionarietà ma come "coerenza", riconoscendo la selettività condizionata.
- **Stato:** ✅ Implementato (2026-06-24) nel manoscritto LaTeX.
- **Fonte:** `paper_v2_springer.tex`, `reviewer/reviewer_response.md`

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


### D-XX — Audit 2026-07: invarianti hard protette da test (aggiunto 2026-07-12)
- **Bandpass singolo:** applicato UNA sola volta dentro `whiten_context()`; il doppio bandpass nei percorsi V3/veto/batch era un bug (B-1), rimosso ovunque e vietato da scan statico in `tests/test_regression_hard_constraints.py`.
- **K=275:** dimensione del dizionario di produzione verificata empiricamente (shape + MD5 pinnato in `PatchScorer`). Il K=281 in V3 era residuo mai andato in produzione; K=1216 è il native O4a index del DSD (artefatto distinto).
- **Semantica coincidenza:** `ACTIVE_UNVERIFIED` (osservabilità) ≠ `ACTIVE_NO_ANOMALY` (ricerca eseguita, nessun match — scrivibile SOLO da `cross_detector_veto`); `COINCIDENT_TRANSIENT` prodotto dal veto (prima irraggiungibile); errori I/O → tabella 3b, mai 3a.
- **Bootstrap:** moving-block (b=n^(1/3), B=1000, seed=42) anche in V3; GEV rifiutata ovunque.
- **Fonte:** audit report in conversazione agente 2026-07-09/12; test suite (36 test).

### D-XY — Leakage cross-run: ipotesi normalizzazione FALSIFICATA (aggiunto 2026-07-12)
- Esperimento pre-registrato (`results/norm_leakage/`): KS sui massimi pre-normalizzazione O3a/O4a p=0.47–0.79; probe run-classification AUC≈0.5 sotto entrambe le normalizzazioni.
- FPR cross-run rimisurato con codice corretto: 0.71/1.66/1.90/2.85 % (0.5/1/2/4 s), N=421; union compatibile con test multipli (p=0.40); residuo 4s guidato da 3 blocchi non stazionari (CI cluster [0.99, 4.79]%).
- **Decisione:** rimedio = soglie taggate `calibration_run` + guardia `assert_threshold_run()` (rifiuto del cross-run silenzioso). NON servono dizionari per-run né cambio di normalizzazione.

### D-XZ — V3 = layer di caratterizzazione, non secondo trigger (aggiunto 2026-07-12)
- `main.py multiscale-analysis`: ri-scoring dei soli candidati V2 alle scale {0.5,1,2,4} s → `Multiscale_Profile_<run>.csv` con scala dominante (stima durata). Niente OR-fusion dei flag per scala (evita inflazione da test multipli sui claim di discovery).
- Poisson UL: livetime intersecato con `{DET}_CBC_CAT1`; abort esplicito se i flag DQ non sono ottenibili (mai fallback allo span non gated).
- Run future (O5): bounds GPS in `config.yaml run_config`, risoluzione config-first in `get_observing_run()`.

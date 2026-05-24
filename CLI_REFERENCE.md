# 📖 Guida ai Comandi CLI — gravi-signal-ml

Questa guida fornisce un elenco completo e aggiornato di tutti i comandi disponibili nella CLI (`main.py`), completi di descrizioni e opzioni per ogni subcommand.

> **💡 Interfaccia Grafica:** È disponibile un'interfaccia grafica (Gooey). Puoi avviarla eseguendo `python gui.py`. Tutte le opzioni CLI elencate qui sotto saranno configurabili anche visivamente tramite la GUI.

> **🪄 Wizard Interattivo:** È disponibile un wizard testuale passo-passo nella CLI. Per avviarlo, esegui semplicemente `python main.py` senza alcun parametro. Il wizard rileva automaticamente tutti i comandi (inclusi eventuali nuovi comandi futuri) e ti guida nell'inserimento dei parametri con suggerimenti intelligenti (Smart Defaults).

---

## Quick Reference (Comandi Più Usati)

- **Scan & Full Analysis Automatica:**
  `python main.py scan-extended --workers 6 --full-analysis True`
- **Riprendere un Run Interrotto:**
  `python main.py scan-extended --session-id <SESSION_ID> --workers 6 --continue-run`
- **Generare Reference Index:**
  `python main.py build-indomain-reference --output data/reference/indomain_index.npz`
- **Visualizzare e Aggiornare Report UMAP:**
  `python main.py report --session-id <SESSION_ID> --detector H1`

---

## Convenzioni Strutturali

### Session ID Convention
Ogni run analitica è isolata automaticamente con un identificatore di sessione univoco (timestamp-based), ad esempio `20260510_143022`.
Tutti i file generati vengono archiviati seguendo questa struttura:
`data/runs/<run>/<session_id>/`
All'interno troverai sottocartelle per: `spectrograms`, `embeddings`, `clusters`, `reports`, `ablation`, `stability`, `timeslide` e `logs`. 
Usando il flag `--session-id` la CLI dedurrà automaticamente i percorsi di lettura/scrittura senza doverli specificare manualmente.

### Multi-Run Support
La pipeline supporta l'analisi di diversi run osservativi di LIGO/Virgo. I run attualmente supportati e selezionabili tramite il flag `--run` sono:
- **O2** (Start: 2016-11-30)
- **O3a** (Start: 2019-04-01)
- **O3b** (Start: 2019-11-01)
- **O4a** (Start: 2023-05-24) *[Default]*

---

## Indice dei Comandi

1. **Acquisizione Dati**
   - [`fetch`](#1-fetch) — Scarica evento noto
   - [`scan`](#2-scan) — Scansione batch
   - [`scan-extended`](#3-scan-extended) — Scansione estesa (sincronizzata)
   - [`fetch-raw`](#4-fetch-raw) — Download dati raw in HDF5
   - [`last-gps`](#5-last-gps) — Recupera ultimo tempo GPS

2. **Pipeline ML (Fasi 2 e 3)**
   - [`reprocess-spectrograms`](#6-reprocess-spectrograms) — Ri-processa spettrogrammi
   - [`encode`](#7-encode) — Estrae embedding DINOv2
   - [`cluster`](#8-cluster) — Esegue DPMM o HDBSCAN clustering
   - [`report`](#9-report) — Rigenera grafici UMAP/gallery

3. **Analisi & Validazione**
   - [`stability`](#10-stability) — Analisi stabilità clustering
   - [`ablation`](#11-ablation) — Studio ablazione perturbazioni
   - [`crosscheck`](#12-crosscheck) — Verifica cross-check Gravity Spy
   - [`timeslide`](#13-timeslide) — Analisi coincidenze e p-value
   - [`analyze-similarity`](#13b-analyze-similarity) — Analisi similarità sottovarianti

4. **Reference Index**
   - [`build-reference`](#14-build-reference) — Costruisce indice base
   - [`build-indomain-reference`](#15-build-indomain-reference) — Costruisce indice in-domain
   - [`validate-reference`](#16-validate-reference) — Valida indice con un evento reale
   - [`morphcheck`](#17-morphcheck) — Confronta anomalie con indice reference
   - [`benchmark-clustering`](#18-benchmark-clustering) — Valida pipeline non supervisionata con etichette ground truth
   - [`benchmark-methods`](#18b-benchmark-methods) — Genera report comparativo tra vari metodi di clustering

5. **Automazione End-to-End**
    - [`full-analysis`](#19-full-analysis) — Pipeline automatizzata completa
    - [`full-analysis-report`](#19b-full-analysis-report) — Rigenera solo i JSON finali della full analysis

6. **Autopilot & Thresholds**
    - [`calibrate-threshold`](#20-calibrate-threshold) — Calibra soglie di similarità per-classe
    - [`calibrate-loglikelihood`](#21-calibrate-loglikelihood) — Calibra soglie log-likelihood per cluster DPMM
    - [`scan-live`](#22-scan-live) — Scanner live: classifica spettrogrammi come KNOWN/NOVEL

---

## Acquisizione Dati

### 1. `fetch`
Scarica un evento GW noto (es. GW150914) ed estrae uno spettrogramma. Utile per validare il funzionamento della pipeline.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Contatta il database GWOSC tramite l'API di interrogazione per trovare il file di strain corrispondente all'evento e al tempo GPS richiesto.
  2. Scarica la serie temporale dello strain e applica lo sbiancamento (*whitening*) per dividere il segnale per la densità spettrale di ampiezza (ASD), rimuovendo così il rumore di fondo dipendente dalla frequenza.
  3. Applica un filtro passa-banda Butterworth tra 20 Hz e 2000 Hz per isolare lo spettro più sensibile dei rivelatori LIGO/Virgo.
  4. Esegue la trasformata Q costante (Q-transform) per generare una griglia tempo-frequenza logaritmica.
  5. Ridimensiona il spectrogramma a 256x256 pixel con interpolazione bilineare e lo salva in PNG con colormap `cividis`.

- `--event` **(Richiesto)**: Nome dell'evento. Scelte disponibili in config, tipicamente: `GW150914`, `GW170817`, `GW231123`.

### 2. `scan`
Esegue la scansione dei segmenti per un **singolo rivelatore** in un periodo definito. Includendo il `--session-id` esistente, attua automaticamente un resume dall'ultimo GPS processato.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Calcola l'intervallo temporale GPS richiesto. Se `--session-id` è impostato e la cartella contiene già degli spettrogrammi, identifica l'ultimo file scritto tramite regex (`^[A-Z]\d_(\d+)_(\d+)\.png$`) e imposta il `start_gps` di conseguenza per consentire una ripartenza automatica (*resume*).
  2. Suddivide l'intervallo totale in segmenti da 32 secondi (durata standard dei frame).
  3. Se `--raw-path` è specificato o rilevato, cerca file HDF5 locali di 4096 secondi scaricati precedentemente. Se li trova, estrae la porzione da 32 secondi in locale evitando richieste di rete; altrimenti scarica i dati da GWOSC al volo.
  4. Pre-processa ogni segmento da 32 secondi (sbiancamento, filtro passa-banda 20-2000 Hz, Q-transform con parametri da config, normalizzazione dei pixel in range `[0, 1]`).
  5. Salva lo spettrogramma PNG risultante in `data/runs/<run>/<session_id>/spectrograms/<detector>/`.

- `--detector` **(Richiesto)**: Rivelatore da usare. Scelte: `H1`, `L1`, `V1`.
- `--run`: Run osservativo di riferimento. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--hours`: Ore di durata della scansione (solo per nuovi scan). *Default: `1.0`*.
- `--workers`: Thread in parallelo. 1 = sequenziale. *Default: `1`*.
- `--session-id`: ID sessione univoco (es. `20260510_143022`). *Default: auto-generato*.
- `--no-cache-raw`: Flag booleano. Disabilita il salvataggio dei file HDF5 grezzi nella cartella `data/raw`. *Default: `True`* (non salva). Impostare a `False` per attivare il salvataggio.
- `--raw-path`: Percorso manuale ad una specifica sessione raw. Se non specificato, utilizzerà l'ultima cartella disponibile in `data/raw/` con GPS più alto.

### 3. `scan-extended`
Scansione estesa automatizzata di **H1 e L1** contemporaneamente (Phase 4). Sincronizza i due rivelatori in modo che riprendano dallo stesso GPS in caso di resume. Anche questo comando legge blocchi da 4096s da `data/raw/` di default prima di fare fallback su GWOSC.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Identifica le cartelle di spettrogrammi per H1 e L1 per la sessione specificata. In caso di resume, trova l'ultimo GPS registrato per ciascun detector e seleziona il *minimo comune* tra essi. Questo assicura che entrambi i detector ripartano esattamente dallo stesso secondo GPS, evitando disallineamenti temporali.
  2. Se `--raw-path` è specificato (o ricavato in automatico dall'ultimo download), analizza i file `.hdf5` per determinare l'intervallo temporale totale (`min_start` e `max_end`), forzando l'inizio e la fine dello scan sui limiti fisici dei file locali ed escludendo la necessità di configurare `--hours`.
  3. Divide il lavoro in parallelo usando un `ProcessPoolExecutor` (su Windows con multiprocessing `spawn`) dividendo equamente il numero totale di worker fra H1 e L1 per ottimizzare il calcolo CPU-bound della Q-transform.
  4. Per ciascun segmento da 32 secondi, estrae lo strain, esegue il preprocessing (whiten, bandpass, Q-transform) e scrive il PNG.
  5. Se `--full-analysis` è True, esegue automaticamente l'intera pipeline di embedding, clustering e validazione sui nuovi dati elaborati.
  6. Se `--continue-run` è abilitato, entra in un loop infinito (fino a `--max-iterations` o alla raggiungimento di `--stop-date`) alternando fasi di scansione incremental e fasi di clustering/validazione automatica.

- `--run`: Run osservativo. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--hours`: Override ore per rivelatore rispetto al config yaml (solo per nuovi scan).
- `--workers`: Numero di worker (deve essere un **numero pari**, es. 2, 4, 6, 8). I worker vengono divisi equamente tra H1 e L1. *Default: `1`*.
- `--session-id`: ID sessione. *Default: auto-generato*.
- `--no-cache-raw`: Flag booleano. Disabilita salvataggio HDF5. *Default: `True`*.
- `--full-analysis`: Flag booleano. Se impostato a `True`, avvia automaticamente la `full-analysis` al termine. *Default: `False`*.
- `--skip-timeslide`: Flag. Salta l'analisi timeslide nella full analysis.
- `--n-runs`: Numero di run per la stability analysis. *Default: `20`*.
- `--sequential`: Esegue i detector in sequenza anziché in parallelo.
- `--start-gps`: Fornisce un tempo GPS d'inizio fisso.
- `--continue-run`: Flag. Attiva il ciclo continuo di scansione e analisi sincronizzata (loop di resume).
- `--max-iterations`: Numero massimo di iterazioni per il ciclo continuo. *Default: `10`*.
- `--stop-date`: Limite temporale oltre il quale interrompere il ciclo continuo.
- `--raw-path`: Percorso manuale ad una specifica sessione raw. Se non specificato, utilizzerà l'ultima cartella disponibile in `data/raw/` con GPS più alto.

### 4. `fetch-raw`
Download massivo di dati strain (GWOSC) in formato `.hdf5`.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Risolve l'intervallo GPS del run osservativo prescelto.
  2. Suddivide l'intervallo temporale richiesto in blocchi rigidi da 4096 secondi (la durata predefinita impostata in `--segment-duration`).
  3. Contatta GWOSC tramite l'utility `gwosc.locate.get_urls` per ottenere le URL dirette per il download dei file HDF5.
  4. Lancia i download in parallelo tramite un `ThreadPoolExecutor` di worker di rete (limitati a un massimo di 4 thread per detector per evitare il blocco IP da parte del server GWOSC).
  5. Salva i file direttamente in `data/raw/<gps_start>/` con nome file `[Detector]_[gps_start]_[gps_end].hdf5`.
  6. Rileva i file parzialmente completati per riprendere in automatico i download interrotti.

- `--detector`: Rivelatore(i). *Default: `H1 L1`*.
- `--workers`: Numero totale di worker. *Default: `2`*.
- `--run`: Run osservativo base. *Default: `O4a`*.
- `--hours`: Ore totali da scaricare. *Default: letto da config.yaml per la run specificata*.
- `--start-gps`: Sovrascrive il tempo GPS di inizio. *Default: letto da config.yaml per la run specificata*.
- `--output-dir`: Cartella output cache. *Default: `data/raw`*.
- `--segment-duration`: Durata chunk in download (in secondi). *Default: `4096`*.
- `--no-resume`: Flag. Disattiva il resume automatico.
- `--retry`: Flag. Abilita retry con backoff esponenziale.
- `--continue`: Flag. Continua il download dall'ultima cartella GPS in data/raw/. *Default: `False`*.

### 5. `last-gps`
Restituisce il tempo GPS (end) più avanzato per riprendere run fermati senza invocare server esterni.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Accede alla cartella degli spettrogrammi `data/runs/<run>/<session_id>/spectrograms/<detector>/`.
  2. Legge la lista di file PNG salvati e applica il pattern regex `^[H|L|V]1_(\d+)_(\d+)\.png$`.
  3. Estrae il tempo GPS finale `gps_end` da ciascun file.
  4. Determina e stampa a schermo il valore massimo, permettendo di verificare rapidamente lo stato locale dello scan senza dipendere da contatti di rete con GWOSC.

- `--detector` **(Richiesto)**: Rivelatore.
- `--session-id` **(Richiesto)**: ID sessione per trovare la directory.
- `--run`: Run osservativo di ricerca. *Default: `O4a`*.

---

## Pipeline ML

### 6. `reprocess-spectrograms`
Ri-renderizza i file PNG esistenti applicando i setting visivi correnti del config.yaml.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Legge la lista di file PNG esistenti nella sessione.
  2. Cerca nella cache locale HDF5 (`data/raw/`) la serie temporale originale per lo stesso intervallo GPS del frame.
  3. Se i dati grezzi sono presenti, li rielabora applicando la nuova configurazione (es. cambio di colormap come `viridis`, `plasma` o `cividis`, oppure modifiche all'intervallo di frequenza `frange` o ai fattori di scala della trasformata Q).
  4. Se `--backup` è abilitato, sposta la vecchia immagine PNG in una cartella di backup prima di sovrascriverla.

- `--session-id`: ID sessione.
- `--detector`: Rivelatore.
- `--run`: Run osservativo in uso. *Default: `O4a`*.
- `--input-dir`: Path esplicito agli spettrogrammi.
- `--workers`: Numero thread. *Default: `1`*.
- `--backup`: Flag. Salva un file backup prima di sovrascrivere.
- `--dry-run`: Flag. Analizza e stampa a video i task previsti.
- `--use-cache`: Flag. Controlla prima la cache locale HDF5.

### 7. `encode`
Usa il modello DINOv2-Reg preaddestrato per mappare gli spettrogrammi in vettori embedding ad alta dimensionalità.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Carica il modello di deep learning `dinov2_vits14_reg` (Vision Transformer Small a 14 patch con token di registro) via `torch.hub`. Configura tutti i pesi come bloccati (*frozen*) in modalità valutazione (`eval()`). I token di registro impediscono al modello di focalizzarsi su artefatti in zone vuote/uniformi dello spettrogramma.
  2. Legge ricorsivamente i file PNG. Per ciascuna immagine: la converte in RGB, la ridimensiona a 518x518 pixel (dimensione ottimale per DINOv2) e applica la normalizzazione statistica di ImageNet (mean/std).
  3. Esegue la forward pass del modello sul dispositivo disponibile (GPU CUDA, Apple Silicon MPS o CPU) con la batch size desiderata.
  4. Gestisce errori Out-Of-Memory (OOM) su CUDA: se la GPU si satura, svuota la cache PyTorch, dimezza temporaneamente la batch size e riprova automaticamente l'estrazione.
  5. Estrae il CLS token finale dall'output e applica la normalizzazione L2 (assegnando ad ogni embedding norma pari a 1.0) in modo che la distanza euclidea coincida con la distanza coseno su un'ipersfera a 384 dimensioni.
  6. Salva la matrice degli embedding risultante in un file NumPy `.npy` (dimensioni `[N, 384]`) e un file JSON di metadati di accompagnamento che traccia l'ordine dei file PNG corrispondenti.

- `--session-id`: ID sessione.
- `--detector`: Rivelatore.
- `--run`: Run osservativo. *Default: `O4a`*.
- `--input-dir`: Cartella diretta file `.png`.
- `--output`: File di arrivo (`.npy`).
- `--batch-size`: Batch inference size PyTorch. *Default: `32`*.

### 8. `cluster`
Raggruppa dinamicamente i dati (DPMM o HDBSCAN), trovando eventuali classi di glitch e anomalie.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. **PCA (Principal Component Analysis):** Applica l'algoritmo PCA per ridurre gli embedding da 384 dimensioni a 50 componenti principali. Questo riduce il rumore statistico e accelera l'esecuzione di UMAP.
  2. **UMAP Passaggio A (Clustering):** Riduce i vettori da 50D a 10D. Utilizza parametri specifici (`min_dist=0.0`, metrica di distanza *coseno*) che forzano i dati a formare gruppi estremamente concentrati e ad alta densità geometrica, ideali per algoritmi di clustering densità-based.
  3. **Algoritmo di Raggruppamento:**
     - **DPMM (Dirichlet Process Mixture Model - default):** Esegue una miscela variazionale di gaussiane con un prior a processo di Dirichlet. Trova in modo del tutto autonomo il numero di classi potando i pesi dei cluster vuoti. Calcola il log-likelihood di ciascun campione rispetto alla miscela e marca i campioni nella coda inferiore (es. 5° percentile) come anomalie individuali. A livello di cluster, aggrega queste anomalie: un cluster è marcato come *anomalo* se **>50% dei suoi membri** hanno log-likelihood sotto la soglia del 5° percentile. Questo criterio è coerente con quello usato dalla stability analysis.
     - **HDBSCAN:** Calcola i gruppi di densità a 10D. Isola come rumore (`-1`) i campioni sparsi. Qualsiasi cluster identificato con dimensione totale inferiore alla soglia impostata (default 10 o 1% del dataset) viene contrassegnato come *cluster anomalo* (novità morfologiche candidate).
  4. **UMAP Passaggio B (Visualizzazione):** Riduce gli embedding a 2D. Utilizza un valore `min_dist=0.1` per distanziare graficamente i cluster e permettere la creazione di grafici di dispersione 2D puliti e ad alta leggibilità.
  5. Scrive i risultati (etichette, UMAP 2D, statistiche ed elenco anomalie) in un report di clustering JSON.

- `--session-id`: ID della sessione.
- `--detector`: Rivelatore. 
- `--run`: Run osservativo. *Default: `O4a`*.
- `--input`: File numpy (`.npy`).
- `--output`: Cartella in cui salvare plot e JSON.
- `--algorithm`: Algoritmo di clustering (`dpmm`, `hdbscan`). *Default: `dpmm`*.

### 9. `report`
Rigenera gallerie d'immagini riepilogative e plot UMAP 2D caricando il JSON risultante da un precedente `cluster`.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Carica il file NumPy degli embedding e il JSON del report di clustering.
  2. Esegue il plot di dispersione 2D in base alle coordinate UMAP-2D. Colora ciascun punto in base al suo cluster ID e contrassegna graficamente i glitch identificati come anomalie/novelty.
  3. Per ogni cluster identificato, campiona un sottoinsieme di spettrogrammi PNG rappresentativi.
  4. Costruisce una galleria HTML e un'immagine riepilogativa a griglia per consentire ai fisici/analisti di ispezionare visivamente le forme d'onda raggruppate nei cluster.

- `--session-id`: ID della sessione.
- `--detector`: Rivelatore target.
- `--run`: Run osservativo. *Default: `O4a`*.
- `--embeddings`: Path ad embedding.
- `--report`: Path a JSON.
- `--output-dir`: Cartella output custom.
- `--algorithm`: Algoritmo utilizzato per i dati. *Default: `dpmm`*.

---

## Analisi & Validazione

### 10. `stability`
Riesegue il cluster introducendo micro-perturbazioni per verificare la robustezza (ARI).

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Esegue il PCA baseline a 50D sugli embedding originali.
  2. Avvia un ciclo di `N` run di clustering perturbato (default 20). Per ogni run:
     - Moltiplica i parametri `n_neighbors` (UMAP) e `min_cluster_size` (HDBSCAN) per un fattore casuale estratti uniformemente in `[0.8, 1.2]`.
     - Varia il seed di inizializzazione casuale di UMAP.
     - Esegue UMAP-10D e l'algoritmo di clustering (DPMM o HDBSCAN).
  3. Calcola il punteggio Adjusted Rand Index (ARI) per ogni coppia di run. L'ARI misura la similarità tra due partizioni ignorando le permutazioni di etichette.
  4. Calcola la media e lo scostamento standard dell'ARI complessivo per fornire una misura quantitativa di stabilità (`mean_ari > 0.8` = robusto; `mean_ari < 0.5` = instabile).
  5. Calcola la frequenza con cui ciascun campione viene etichettato come anomalo in tutte le prove. I campioni marcati come anomali in almeno l'80% delle run totali costituiscono l'elenco finale delle *anomalie stabili*.
  6. Genera un report JSON contenente le statistiche e la matrice ARI.

- `--session-id`: ID della sessione target.
- `--detector`: Rivelatore. *Default: `H1`*.
- `--run`: Run osservativo. *Default: `O4a`*.
- `--n-runs`: Numero di prove ripetute. *Default: `20`*.
- `--embeddings`: Path input `.npy`.

### 11. `ablation`
Valuta l'impatto pre-processuale mutando le immagini e analizzando l'accuratezza in ARI dei vari cluster (es. grayscale, inverted).

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Definisce 4 condizioni di perturbazione visiva:
     - `grayscale`: Trasforma lo spettrogramma a toni di grigio, azzerando le informazioni cromatiche della colormap.
     - `inverted`: Inverte tutti i pixel per testare l'invarianza al contrasto positivo/negativo.
     - `shuffled-intensity`: Moltiplica i pixel di ciascuna immagine per un fattore casuale compreso tra 0.5 e 1.5 per simulare variazioni di intensità globale.
     - `random-baseline`: Sostituisce i vettori DINOv2 con vettori gaussiani casuali per controllare il comportamento in caso di assenza totale di informazione.
  2. Per ciascun set modificato, estrae i nuovi embedding con il modello DINOv2.
  3. Esegue la pipeline di clustering standard sui nuovi embedding perturbati.
  4. Calcola l'Adjusted Rand Index (ARI) confrontando le nuove partizioni ottenute con quella baseline originale.
  5. Se l'ARI del set `grayscale` scende sotto 0.4, solleva un warning sul fatto che la pipeline dipende da dettagli grafici di rendering invece che dalla fisica dello strain.
  6. Salva un report riepilogativo in JSON.

- `--session-id`: ID sessione.
- `--detector`: Rivelatore target.
- `--run`: Run osservativo. *Default: `O4a`*.
- `--embeddings`: Path baseline embedding `.npy`.
- `--spectrogram-dir`: Percorso agli spettrogrammi `.png`.
- `--output-dir`: Cartella di destinazione.
- `--batch-size`: Batch size per DINOv2. *Default: `32`*.

### 12. `crosscheck`
Incrocia i cluster anomali del JSON col set reale di LIGO tramite query remote via API in Gravity Spy.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Carica il JSON di report contenente l'elenco dei glitch classificati come anomalie o novità morfologiche.
  2. Estrae gli intervalli temporali GPS associati a tali transitori.
  3. Interroga le API pubbliche di Gravity Spy inviando i tempi GPS e il detector di origine.
  4. Recupera le etichette ufficiali assegnate a quegli eventi dagli algoritmi di Gravity Spy e dai volontari della community (es. Blip, Whistle, Scratch).
  5. Confronta e calcola le corrispondenze tra i cluster generati dal nostro modello non supervisionato e le classi note, scrivendo un resoconto finale.

- `--report` **(Richiesto)**: Path al JSON output del cluster.
- `--metadata` **(Richiesto)**: Path JSON dei metadati base forniti da `encode`.
- `--detector`: Rivelatore usato. *Default: `H1`*.
- `--output`: Path in cui redigere un resoconto.

### 13. `timeslide`
Stima il p-value empirico di coincidenza tra anomalie `H1` e `L1` tramite time-shift casuali. Supporta sia le anomalie da **cluster HDBSCAN** che le anomalie individuali rilevate da **DPMM** (`anomalous_samples`). L'output è salvato automaticamente.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Estrae i tempi GPS delle anomalie rilevate separatamente per H1 e per L1 nella sessione. La raccolta integra entrambe le sorgenti:
     - **Cluster anomali (HDBSCAN):** scorre i cluster marcati come anomali nel report e raccoglie i `sample_files` associati.
     - **Campioni anomali DPMM (`anomalous_samples`):** risolve gli indici salvati nel report contro la lista `files` del metadata JSON prodotto da `encode`.
  2. **Calcolo Zero-lag:** Conta il numero effettivo di coincidenze reali tra H1 e L1. Due anomalie coincidono se i loro GPS differiscono al massimo di una finestra prefissata (default 32 secondi, configurabile via `--window`). Ciascun segmento viene accoppiato al massimo una volta.
  3. **Analisi Time-slide:** Genera un fondo di controllo simulato eseguendo `N` iterazioni (default 100, configurabile via `--iterations`). In ciascuna iterazione:
     - Applica uno slittamento temporale (*time-slide*) artificiale ai tempi GPS di L1 (scelto casualmente tra multipli di 100 secondi nel range da -5000 a 5000 s, escludendo lo zero). Questo distrugge ogni correlazione temporale fisica coerente.
     - Ricalcola il numero di coincidenze casuali ottenute tra la serie H1 originale e la serie L1 shiftata.
     - Memorizza il conteggio per costruire la distribuzione statistica del fondo casuale.
  4. Calcola la media e la deviazione standard della distribuzione del fondo casuale.
  5. Calcola il **p-value empirico** come la frazione di run di time-slide che hanno registrato un numero di coincidenze casuali pari o superiore rispetto alle coincidenze reali (zero-lag). Un `p-value < 0.05` indica che le coincidenze osservate sono statisticamente significative e non imputabili al caso.
  6. Calcola il **z-score** e scrive i risultati in `timeslide_report_H1_L1.json`.

- `--session-id`: ID univoco sessione (risolve automaticamente tutti i path). *Alternativa agli argomenti espliciti.*
- `--run`: Run osservativo. *Default: `O4a`*.
- `--metadata-h1` / `--metadata-l1`: Path al JSON dei metadati prodotto da `encode` (override rispetto al session-id).
- `--report-h1` / `--report-l1`: Path al JSON del cluster report (override rispetto al session-id).
- `--iterations`: Numero di time-slide per la stima del fondo. *Default: `100`*. Configurabile anche in `config.yaml → timeslide.iterations`.
- `--window`: Finestra di coincidenza in secondi. *Default: `32`*. Configurabile anche in `config.yaml → timeslide.window`.

> **💡 Nota:** senza `--session-id`, i quattro argomenti `--metadata-h1`, `--metadata-l1`, `--report-h1`, `--report-l1` sono tutti obbligatori. Gli argomenti `--embeddings-*` non sono necessari e sono stati rimossi.

### 13b. `analyze-similarity`
Analizza la distribuzione delle similarità coseno per ogni cluster rispetto alle classi del riferimento in-domain.
Utile per determinare se un cluster anomalo è genuinamente equidistante da molte classi (indicatore potenziale NOVEL) oppure è una sottovariante di una classe nota (similarità sistematicamente più alta verso quella classe).

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Carica il morphcheck report e il cluster_report.
  2. Per ogni cluster, estrae i campioni e le loro similarità verso le top-5 classi del riferimento.
  3. Calcola similarità media, deviazione standard, e rapporto tra top-1 e top-2.
  4. Produce un resoconto indicante l'interpretazione (Equidistante vs Sottovariante) per l'eventuale NOVEL candidate.

- `--session-id` **(Richiesto)**: ID univoco sessione.
- `--detector` **(Richiesto)**: Rivelatore usato (es. `H1`).
- `--run`: Run osservativo (es. `O4a`).
- `--reference`: Path al reference index `.npz`.

---

## Reference Index

### 14. `build-reference`
Avvia il builder estraendo dall'archivio di Gravity Spy un indice di embeddings.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Cerca in locale il file compresso `.tar.gz` contenente il dataset di Gravity Spy (organizzato in sotto-cartelle corrispondenti alle classi note di glitch).
  2. Estrae fino a un numero massimo stabilito (default 50) di campioni per ogni classe di glitch.
  3. Pre-processa le immagini estratte e le passa all'encoder DINOv2 per calcolare gli embedding a 384 dimensioni.
  4. Raccoglie tutti i vettori di embedding e le relative etichette testuali delle classi, salvandoli in un unico file NumPy compresso `.npz` (`data/reference/`).

- `--output` **(Richiesto)**: Destinazione finale per il `.npz`.
- `--max-per-class`: Campioni estratti da ogni classe. *Default: `50`*.
- `--tar-path`: Percorso al .tar.gz in locale. *Default: `data/reference/trainingsetv1d1.tar.gz`*.

### 15. `build-indomain-reference`
Crea l'indice reference usando eventi reali in-domain processati dalla nostra pipeline, riducendo il domain-gap.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Carica i file di spettrogrammi e le predizioni del modello per le sessioni selezionate.
  2. Filtra gli eventi mantenendo unicamente quelli che hanno una probabilità di classificazione superiore alla soglia critica (default 0.95), per garantire l'assoluta purezza delle classi.
  3. Limita il numero di campioni per ciascuna classe (default 30) per mantenere l'indice bilanciato.
  4. Genera e salva gli embedding DINOv2 normalizzati e le corrispondenti etichette di classe in un file `.npz`.

- `--output` **(Richiesto)**: Path finale all'indice `.npz`.
- `--detector`: Rivelatore associato. *Default: `H1`*.
- `--run`: Run osservativo. *Default: `O3b`*.
- `--max-per-class`: Limitazione campioni per classe. *Default: `30`*.
- `--min-confidence`: Accuratezza minima per includere glitch. *Default: `0.95`*.
- `--workers`: Numero Thread. *Default: `1`*.

### 16. `validate-reference`
Validazione on-the-fly tramite evento test.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Carica il file dell'indice di riferimento `.npz` in memoria.
  2. Carica ed elabora il segnale di strain per un evento noto iniettato come stress-test (es. GW150914).
  3. Calcola il vettore di embedding DINOv2 dell'evento.
  4. Esegue la ricerca coseno KNN contro l'indice per assicurarsi che l'evento iniettato venga correttamente associato alla sua classe fisica reale, confermando l'assenza di errori di scalatura o formattazione.

- `--reference` **(Richiesto)**: Path indice pre-estratto `.npz`.
- `--test-event`: Evento per l'injection di stress-test. *Default: `GW150914`*.

### 17. `morphcheck`
Utilizza un indice di riferimento (in-domain o standard) per valutare i cluster identificati, etichettando ogni anomalia come NOVEL o KNOWN.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Carica la matrice degli embedding e l'indice di riferimento `.npz`.
  2. **Cosine KNN Search:** Per ciascun campione nei cluster anomali, calcola il prodotto matriciale degli embedding (già normalizzati a norma 1.0) con gli embedding di riferimento, ottenendo una matrice di similarità coseno. Identifica i `K` vicini più prossimi (default K=5).
  3. **Novelty Evaluation:**
     - Se la similarità coseno massima con il vicino più vicino è inferiore alla soglia di novità (`novelty_threshold`, default 0.85), il campione viene classificato come **NOVEL** (indica una forma d'onda anomala non presente nel catalogo di riferimento).
     - Se la similarità è superiore alla soglia e c'è consenso di classe tra i K vicini (percentuale superiore al `consensus_threshold`, default 60%), l'evento è classificato come **KNOWN** (associato alla classe del vicino dominante, es. Blip).
     - Negli altri casi, l'evento è catalogato come **AMBIGUOUS**.
  4. Genera un JSON finale con i dettagli della classificazione per ogni singolo glitch analizzato.

- `--embeddings` **(Richiesto)**: Path file Numpy base array.
- `--report` **(Richiesto)**: Path cluster report JSON.
- `--reference` **(Richiesto)**: Indice `.npz` di paragone.
- `--output` **(Richiesto)**: Percorso del file JSON in uscita.
- `--run`: Run associato. *Default: `O4a`*.

### 18. `benchmark-clustering`
Esegue un benchmark della pipeline di clustering non supervisionata usando un reference index come ground truth per il calcolo metrico (ARI, AMI).

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Estrae dal file `.npz` di riferimento gli embedding e le rispettive classi note.
  2. Applica l'algoritmo di clustering non supervisionato selezionato (DPMM o HDBSCAN) direttamente su tali vettori, ignorando le etichette reali.
  3. Confronta le partizioni generate dall'algoritmo con le etichette reali di ground truth.
  4. Calcola metriche formali per il confronto delle partizioni: **Adjusted Rand Index (ARI)** e **Adjusted Mutual Information (AMI)**.
  5. Salva i punteggi in un JSON di report, utile per validare modifiche o ottimizzazioni apportate al codice di clustering.

- `--reference`: Path all'indice di reference `.npz`. *Default: `data/reference/indomain_index.npz`*.
- `--min-samples-per-class`: Rimuove le classi con meno campioni specificati. *Default: `10`*.
- `--output`: Path in cui salvare il JSON di report del benchmark. *Default: `data/reference/benchmark_report.json`*.
- `--algorithm`: Algoritmo di clustering da usare. *Default: `dpmm`*.

### 18b. `benchmark-methods`
Esegue un benchmark comparativo tra diverse combinazioni di metodi (es. DINOv2+DPMM, DINOv2+HDBSCAN, baseline PCA+tSNE) calcolando metriche globali (ARI, AMI) contro un ground truth di riferimento.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Estrae dall'indice `.npz` di riferimento gli embedding e le classi note.
  2. Elabora iterativamente i dati usando configurazioni hardcoded di vari algoritmi e pipeline riduttive (es. PCA, t-SNE, UMAP).
  3. Calcola metriche ARI e AMI per ogni configurazione.
  4. Salva un report riepilogativo per facilitare il confronto metodologico.

- `--reference`: Path all'indice reference `.npz`. *Default: `data/reference/indomain_index.npz`*.
- `--output`: Path JSON di destinazione. *Default: `data/reference/benchmark_methods.json`*.

---

## Automazione End-to-End

### 19. `full-analysis`
Automatizza l'intero workflow di analisi (Encode, Cluster, Morphcheck, Ablation, Stability e Timeslide). Per default analizza H1 e L1 in parallelo.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Verifica quali rivelatori sono presenti nella sessione. Per impostazione predefinita, avvia l'elaborazione per H1 e L1.
  2. Esegue il comando **`encode`** per generare le matrici di embedding `.npy` e metadati `.json` per ciascun detector.
  3. Esegue il comando **`cluster`** per applicare la riduzione dimensionale (PCA + UMAP) e il clustering (DPMM o HDBSCAN).
  4. Esegue il comando **`morphcheck`** confrontando gli embedding ottenuti con l'indice in-domain reference per determinare lo stato di novità (KNOWN/NOVEL) di ogni glitch.
  5. Lancia l'analisi di **`ablation`** su ciascun rivelatore per testare la dipendenza dalle impostazioni grafiche.
  6. Esegue l'analisi di **`stability`** introducendo perturbazioni per verificare la robustezza strutturale delle classi scoperte.
  7. Se non esplicitamente disabilitato tramite `--skip-timeslide`, esegue il calcolo delle coincidenze casuali mediante **`timeslide`** confrontando H1 e L1 per stimare il p-value empirico delle coincidenze fisiche.
  8. Memorizza tutti i report grafici e testuali all'interno della directory della sessione corrente.

- `--session-id` **(Richiesto)**: ID della sessione da analizzare.
- `--detector`: Uno o più rivelatori (es. `--detector H1 L1`). Se omesso, deduce automaticamente i rivelatori nella sessione.
- `--run`: Run osservativo. *Default: `O4a`*.
- `--skip-timeslide`: Flag. Forza l'esclusione del timeslide.
- `--n-runs`: Numero di run per la stability analysis. *Default: `20`*.
- `--sequential`: Esecuzione sequenziale dei detector.
- `--algorithm`: Algoritmo di clustering (`dpmm`, `hdbscan`). *Default: `dpmm`*.

### 19b. `full-analysis-report`
Rigenera solo i JSON finali della full-analysis aggregando le informazioni dei file JSON dei vari step (clustering, ablation, ecc.) per i detector nella sessione corrente.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Identifica le cartelle di report dei detector specificati.
  2. Rilegge e compila `cluster_report.json`, `ablation_report`, `stability_report`, ecc. in un unico file `[detector]_full_report.json`.

- `--session-id` **(Richiesto)**: ID della sessione.
- `--run`: Run osservativo. *Default: `O4a`*.

---

## Autopilot

I comandi Autopilot operano in modo **completamente separato** dalla pipeline standard (`data/runs/`). Tutti gli output sono scritti in `data/autopilot/`.

### 20. `calibrate-threshold`
Calibra soglie di similarità coseno per-classe dall'indice di reference in-domain. Per ogni classe, campiona fino a 200 coppie intra-classe, calcola la similarità coseno, e salva il percentile N-esimo come soglia.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Carica l'indice reference `.npz` e mappa i vettori associati a ciascuna classe di glitch.
  2. Per ciascuna classe:
     - Calcola la similarità coseno per tutte le possibili coppie formate da campioni appartenenti a quella stessa classe (fino a un limite di 200 coppie campionate a caso).
     - Ordina le similarità ottenute e individua il valore in corrispondenza del percentile richiesto (es. il 5% più basso, impostato con `--percentile 5`).
     - Questo valore di similarità coseno intra-classe rappresenta il limite minimo al di sotto del quale un campione, sebbene vicino a quella classe, si discosta troppo dalla sua variabilità standard e deve essere considerato potenzialmente estraneo.
  3. Salva la mappa delle soglie personalizzate risultante in `thresholds.json` per essere impiegata nello scanner Autopilot in tempo reale.

```bash
python main.py calibrate-threshold --reference data/reference/indomain_index.npz --percentile 5 --output data/autopilot/reference/thresholds.json
```

- `--reference`: Path all'indice reference `.npz`. *Default: `data/reference/indomain_index.npz`*.
- `--percentile`: Percentile per la soglia intra-classe (più basso = più restrittivo). *Default: `5`*.
- `--output`: Path JSON di destinazione. *Default: `data/autopilot/reference/thresholds.json`*.

Formato output (`thresholds.json`):
```json
{
  "metadata": {
    "reference": "data/reference/indomain_index.npz",
    "percentile": 5,
    "calibrated_at": "2026-05-16T12:00:00",
    "n_classes": 22
  },
  "thresholds": {
    "Blip": 0.847,
    "Low_Frequency_Lines": 0.812
  }
}
```

### 21. `calibrate-loglikelihood`
Calibra la soglia di anomalia per la log-likelihood usata dal clustering DPMM, ricavandola dall'indice di riferimento in-domain. Questo garantisce che la soglia sia consistente tra le varie esecuzioni.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. Carica l'indice reference `.npz` contenente gli embedding.
  2. Esegue PCA (50D) e UMAP (10D) usando la stessa pipeline del clustering.
  3. Fitta un Bayesian Gaussian Mixture (DPMM) con 25 componenti.
  4. Calcola la log-likelihood per ogni campione, e determina la soglia in base al percentile fornito.
  5. Salva la soglia risultante in un file JSON. Questo valore andrà poi riportato in `config.yaml` sotto `dpmm.anomaly_threshold`.

```bash
python main.py calibrate-loglikelihood --reference data/reference/indomain_index.npz --percentile 5 --output data/autopilot/reference/loglikelihood_threshold.json
```

- `--reference`: Path all'indice reference `.npz`. *Default: `data/reference/indomain_index.npz`*.
- `--percentile`: Percentile per la log-likelihood (più basso = più restrittivo). *Default: `5`*.
- `--output`: Path JSON di destinazione. *Default: `data/autopilot/reference/loglikelihood_threshold.json`*.

Formato output (`loglikelihood_threshold.json`):
```json
{
  "threshold": -148.32,
  "percentile": 5.0,
  "reference": "data/reference/indomain_index.npz",
  "n_samples": 528,
  "calibrated_at": "2026-05-23T23:10:00+00:00"
}
```

### 22. `scan-live`
Scanner autopilot con architettura producer-consumer. Lavora a blocchi di 4096s in cui un producer scarica l'HDF5 di 4096s in `tmp/`, processa internamente 128 segmenti da 32s ciascuno (`whiten -> bandpass -> q-transform`), ed il consumer le valuta classificando ogni spettrogramma come KNOWN/AMBIGUOUS/NOVEL usando DINOv2 + soglie per-classe. Cancella temporanei HDF5 e PNG in tempo reale ad eccezione dei NOVEL.

* **Sotto il cofano (Dettagli di Elaborazione):**
  1. **Producer Thread:** Scarica in parallelo i file HDF5 da 4096 secondi da GWOSC in una cartella di lavoro temporanea `tmp/`. Estrae i 128 segmenti da 32 secondi, calcolando localmente in memoria whiten, bandpass e Q-transform per produrre immagini temporanee.
  2. **Consumer Thread:** Riceve i percorsi dei frame temporanei non appena completati. Per ciascuno di essi:
     - Calcola il vettore di embedding a 384 dimensioni mediante il modello DINOv2.
     - Calcola la similarità coseno con tutti i glitch dell'in-domain reference index (`.npz`).
     - Esegue il confronto con le **soglie per-classe calibrate** (caricate da `thresholds.json`). Se la similarità massima registrata con la classe di glitch più affine è *inferiore* alla soglia critica calibrata per quella specifica classe, il frame viene marcato come **NOVEL** (anomalia non catalogata).
  3. **Pulizia Spazio Disco:** Per minimizzare lo spazio su disco occupato dallo scanner continuo, cancella immediatamente i file grezzi HDF5 e le immagini PNG dei glitch classificati come `KNOWN`. Salva definitivamente su disco solo le informazioni relative alle novità (**NOVEL**), incluse le immagini PNG e i vettori di embedding `.npy`.
  4. Scrive la traccia di ogni singolo evento in un file di log strutturato `metadata.jsonl`.
  5. Al termine della scansione, se il numero totale di glitch NOVEL rilevati supera la soglia prefissata (default `--min-novel 10`), avvisa l'utente emettendo a video l'invito a lanciare la pipeline standard di `full-analysis` per raggruppare e analizzare scientificamente la nuova classe di anomalie rilevate.

```bash
python main.py scan-live --detector H1 --run O4a --workers 4
python main.py scan-live --detector H1 --run O4a --session-id autopilot_20260516_120000 --workers 4 --min-novel 10
```

- `--detector` **(Richiesto)**: Rivelatore da usare. Scelte: `H1`, `L1`, `V1`.
- `--run`: Run osservativo. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--workers`: Thread producer paralleli per fetch GWOSC. *Default: `4`*.
- `--session-id`: ID sessione. *Default: `autopilot_{timestamp}`*.
- `--min-novel`: Soglia minima NOVEL per suggerire il clustering. *Default: `10`*.
- `--reference`: Path all'indice reference `.npz`. *Default: `data/reference/indomain_index.npz`*.
- `--hours`: Override durata scan in ore. *Default: da `run_config`*.

Struttura output:
```
data/autopilot/
├── reference/
│   └── thresholds.json
└── <session_id>/
    ├── tmp/                     ← PNG temporanei, cancellati dopo processing
    ├── novel/                   ← PNG + .npy embedding NOVEL
    ├── metadata.jsonl           ← un record JSON per spettrogramma processato
    └── report.json              ← report finale
```

Formato record `metadata.jsonl`:
```json
{"gps_start": 1369211232, "gps_end": 1369211264, "status": "NOVEL", "top_label": "Low_Frequency_Lines", "top_similarity": 0.743, "threshold_used": 0.812}
```

Se NOVEL ≥ `--min-novel`, il comando suggerisce di usare la pipeline standard:
```
Ready for clustering — use standard pipeline:
  python main.py full-analysis --session-id <session_id> --run <run>
```

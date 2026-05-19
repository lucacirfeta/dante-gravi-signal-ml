# 📖 Guida ai Comandi CLI — gravi-signal-ml

Questa guida fornisce un elenco completo e aggiornato di tutti i comandi disponibili nella CLI (`main.py`), completi di descrizioni e opzioni per ogni subcommand.

> **💡 Interfaccia Grafica:** È disponibile un'interfaccia grafica (Gooey). Puoi avviarla eseguendo `python gui.py`. Tutte le opzioni CLI elencate qui sotto saranno configurabili anche visivamente tramite la GUI.

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

4. **Reference Index**
   - [`build-reference`](#14-build-reference) — Costruisce indice base
   - [`build-indomain-reference`](#15-build-indomain-reference) — Costruisce indice in-domain
   - [`validate-reference`](#16-validate-reference) — Valida indice con un evento reale
   - [`morphcheck`](#17-morphcheck) — Confronta anomalie con indice reference
   - [`benchmark-clustering`](#18-benchmark-clustering) — Valida pipeline non supervisionata con etichette ground truth

5. **Automazione End-to-End**
   - [`full-analysis`](#19-full-analysis) — Pipeline automatizzata completa

---

## Acquisizione Dati

### 1. `fetch`
Scarica un evento GW noto (es. GW150914) ed estrae uno spettrogramma. Utile per validare il funzionamento della pipeline.
- `--event` **(Richiesto)**: Nome dell'evento. Scelte disponibili in config, tipicamente: `GW150914`, `GW170817`, `GW231123`.

### 2. `scan`
Esegue la scansione dei segmenti per un **singolo rivelatore** in un periodo definito. Includendo il `--session-id` esistente, attua automaticamente un resume dall'ultimo GPS processato.
- `--detector` **(Richiesto)**: Rivelatore da usare. Scelte: `H1`, `L1`, `V1`.
- `--run`: Run osservativo di riferimento. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--hours`: Ore di durata della scansione (solo per nuovi scan). *Default: `1.0`*.
- `--workers`: Thread in parallelo. 1 = sequenziale. *Default: `1`*.
- `--session-id`: ID sessione univoco (es. `20260510_143022`). *Default: auto-generato*.
- `--no-cache-raw`: Flag booleano. Disabilita il salvataggio dei file HDF5 grezzi nella cartella `data/raw`. *Default: `True`* (non salva). Impostare a `False` per attivare il salvataggio.

### 3. `scan-extended`
Scansione estesa automatizzata di **H1 e L1** contemporaneamente (Phase 4). Sincronizza i due rivelatori in modo che riprendano dallo stesso GPS in caso di resume.
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

### 4. `fetch-raw`
Download massivo di dati strain (GWOSC) in formato `.hdf5`.
- `--detector`: Rivelatore. *Opzionale se si usa --workers*.
- `--workers`: Numero totale di worker (deve essere pari se senza detector esplicito).
- `--run`: Run osservativo base. *Default: `O4a`*.
- `--hours`: Ore totali da scaricare. *Default: `1.0`*.
- `--output-dir`: Cartella output cache. *Default: `data/raw`*.
- `--segment-duration`: Durata chunk in download (in secondi). *Default: `3600`*.
- `--no-resume`: Flag. Disattiva il resume automatico.
- `--no-cache-raw`: Flag booleano. Se `True` disabilita salvataggio `.hdf5`. *Default: `True`*.
- `--retry`: Flag. Abilita retry con backoff esponenziale.

### 5. `last-gps`
Restituisce il tempo GPS (end) più avanzato per riprendere run fermati senza invocare server esterni.
- `--detector` **(Richiesto)**: Rivelatore.
- `--session-id` **(Richiesto)**: ID sessione per trovare la directory.
- `--run`: Run osservativo di ricerca. *Default: `O4a`*.

---

## Pipeline ML

### 6. `reprocess-spectrograms`
Ri-renderizza i file PNG esistenti applicando i setting visivi correnti del config.yaml.
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
- `--session-id`: ID sessione.
- `--detector`: Rivelatore.
- `--run`: Run osservativo. *Default: `O4a`*.
- `--input-dir`: Cartella diretta file `.png`.
- `--output`: File di arrivo (`.npy`).
- `--batch-size`: Batch inference size PyTorch. *Default: `32`*.

### 8. `cluster`
Raggruppa dinamicamente i dati (DPMM o HDBSCAN), trovando eventuali classi di glitch e anomalie.
- `--session-id`: ID della sessione.
- `--detector`: Rivelatore. 
- `--run`: Run osservativo. *Default: `O4a`*.
- `--input`: File numpy (`.npy`).
- `--output`: Cartella in cui salvare plot e JSON.
- `--algorithm`: Algoritmo di clustering (`dpmm`, `hdbscan`). *Default: `dpmm`*.

### 9. `report`
Rigenera gallerie d'immagini riepilogative e plot UMAP 2D caricando il JSON risultante da un precedente `cluster`.
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
- `--session-id`: ID della sessione target.
- `--detector`: Rivelatore. *Default: `H1`*.
- `--run`: Run osservativo. *Default: `O4a`*.
- `--n-runs`: Numero di prove ripetute. *Default: `20`*.
- `--embeddings`: Path input `.npy`.

### 11. `ablation`
Valuta l'impatto pre-processuale mutando le immagini e analizzando l'accuratezza in ARI dei vari cluster (es. grayscale, inverted).
- `--session-id`: ID sessione.
- `--detector`: Rivelatore target.
- `--run`: Run osservativo. *Default: `O4a`*.
- `--embeddings`: Path baseline embedding `.npy`.
- `--spectrogram-dir`: Percorso agli spettrogrammi `.png`.
- `--output-dir`: Cartella di destinazione.
- `--batch-size`: Batch size per DINOv2. *Default: `32`*.

### 12. `crosscheck`
Incrocia i cluster anomali del JSON col set reale di LIGO tramite query remote via API in Gravity Spy.
- `--report` **(Richiesto)**: Path al JSON output del cluster.
- `--metadata` **(Richiesto)**: Path JSON dei metadati base forniti da `encode`.
- `--detector`: Rivelatore usato. *Default: `H1`*.
- `--output`: Path in cui redigere un resoconto.

### 13. `timeslide`
Stima il p-value empirico di coincidenza tra anomalie `H1` e `L1` tramite 50 time-shift casuali. L'output è salvato automaticamente.
- `--session-id`: ID univoco sessione. 
- `--run`: Run osservativo. *Default: `O4a`*.
- `--embeddings-h1` / `--embeddings-l1`: Path a matrice embeddings.
- `--metadata-h1` / `--metadata-l1`: Path ai metadati base `.json`.
- `--report-h1` / `--report-l1`: Path ai json finali del cluster.

---

## Reference Index

### 14. `build-reference`
Avvia il builder estraendo dall'archivio di Gravity Spy un indice di embeddings.
- `--output` **(Richiesto)**: Destinazione finale per il `.npz`.
- `--max-per-class`: Campioni estratti da ogni classe. *Default: `50`*.
- `--tar-path`: Percorso al .tar.gz in locale. *Default: `data/reference/trainingsetv1d1.tar.gz`*.

### 15. `build-indomain-reference`
Crea l'indice reference usando eventi reali in-domain processati dalla nostra pipeline, riducendo il domain-gap.
- `--output` **(Richiesto)**: Path finale all'indice `.npz`.
- `--detector`: Rivelatore associato. *Default: `H1`*.
- `--run`: Run osservativo. *Default: `O3b`*.
- `--max-per-class`: Limitazione campioni per classe. *Default: `30`*.
- `--min-confidence`: Accuratezza minima per includere glitch. *Default: `0.95`*.
- `--workers`: Numero Thread. *Default: `1`*.

### 16. `validate-reference`
Validazione on-the-fly tramite evento test.
- `--reference` **(Richiesto)**: Path indice pre-estratto `.npz`.
- `--test-event`: Evento per l'injection di stress-test. *Default: `GW150914`*.

### 17. `morphcheck`
Utilizza un indice di riferimento (in-domain o standard) per valutare i cluster identificati, etichettando ogni anomalia come NOVEL o KNOWN.
- `--embeddings` **(Richiesto)**: Path file Numpy base array.
- `--report` **(Richiesto)**: Path cluster report JSON.
- `--reference` **(Richiesto)**: Indice `.npz` di paragone.
- `--output` **(Richiesto)**: Percorso del file JSON in uscita.
- `--run`: Run associato. *Default: `O4a`*.

### 18. `benchmark-clustering`
Esegue un benchmark della pipeline di clustering non supervisionata usando un reference index come ground truth per il calcolo metrico (ARI, AMI).
- `--reference`: Path all'indice di reference `.npz`. *Default: `data/reference/indomain_index.npz`*.
- `--min-samples-per-class`: Rimuove le classi con meno campioni specificati. *Default: `10`*.
- `--output`: Path in cui salvare il JSON di report del benchmark. *Default: `data/reference/benchmark_report.json`*.
- `--algorithm`: Algoritmo di clustering da usare. *Default: `dpmm`*.

---

## Automazione End-to-End

### 19. `full-analysis`
Automatizza l'intero workflow di analisi (Encode, Cluster, Morphcheck, Ablation, Stability e Timeslide). Per default analizza H1 e L1 in parallelo.
- `--session-id` **(Richiesto)**: ID della sessione da analizzare.
- `--detector`: Uno o più rivelatori (es. `--detector H1 L1`). Se omesso, deduce automaticamente i rivelatori nella sessione.
- `--run`: Run osservativo. *Default: `O4a`*.
- `--skip-timeslide`: Flag. Forza l'esclusione del timeslide.
- `--n-runs`: Numero di run per la stability analysis. *Default: `20`*.
- `--sequential`: Esecuzione sequenziale dei detector.
- `--continue-run`: Flag. Attiva il ciclo continuo generando nuove sessioni in loop.
- `--max-iterations`: Limite iterazioni loop continuo. *Default: `10`*.
- `--stop-date`: Limite data in cui interrompere il ciclo.
- `--algorithm`: Algoritmo di clustering (`dpmm`, `hdbscan`). *Default: `dpmm`*.

# 📖 Guida ai Comandi CLI — gravi-signal-ml

Questa guida fornisce un elenco completo e aggiornato di tutti i comandi disponibili nella CLI (`main.py`), completi di descrizioni e opzioni per ogni subcommand.

> **💡 Interfaccia Grafica:** È disponibile un'interfaccia grafica (Gooey). Puoi avviarla eseguendo `python gui.py`. Tutte le opzioni CLI elencate qui sotto saranno configurabili anche visivamente tramite la GUI.

---

## Indice dei Comandi

1. **Acquisizione Dati**
   - [`fetch`](#1-fetch) — Scarica evento noto
   - [`scan`](#2-scan) — Scansione batch
   - [`scan-extended`](#3-scan-extended) — Scansione estesa
   - [`fetch-raw`](#4-fetch-raw) — Download dati raw in HDF5
   - [`last-gps`](#5-last-gps) — Recupera ultimo tempo GPS

2. **Pipeline ML (Fasi 2 e 3)**
   - [`reprocess-spectrograms`](#6-reprocess-spectrograms) — Ri-processa spettrogrammi
   - [`encode`](#7-encode) — Estrae embedding DINOv2
   - [`cluster`](#8-cluster) — Esegue HDBSCAN clustering
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

5. **Automazione End-to-End**
   - [`full-analysis`](#18-full-analysis) — Pipeline automatizzata completa

---

## Acquisizione Dati

### 1. `fetch`
Scarica un evento GW noto (es. GW150914) ed estrae uno spettrogramma. Utile per validare il funzionamento della pipeline.

- `--event` **(Richiesto)**: Nome dell'evento. Scelte disponibili in config, tipicamente: `GW150914`, `GW170817`, `GW231123`.

---

### 2. `scan`
Esegue la scansione dei segmenti per un **singolo rivelatore** in un periodo definito. Includendo il `--session-id` esistente, attua automaticamente un resume dall'ultimo GPS processato.

> [!IMPORTANT]
> **Modalità Resume:** Se si riprende una sessione esistente, il comando ignora il flag `--hours` e utilizza la durata predefinita definita in `config.yaml` (`hours_per_detector`).

- `--detector` **(Richiesto)**: Rivelatore da usare. Scelte: `H1`, `L1`, `V1`.
- `--run`: Run osservativo di riferimento. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--hours`: Ore di durata della scansione (solo per nuovi scan). *Default: `1.0`*.
- `--workers`: Thread in parallelo. 1 = sequenziale. *Default: `1`*.
- `--session-id`: ID sessione univoco (es. `20260510_143022`). *Default: auto-generato*.
- `--no-cache-raw`: Flag booleano. Disabilita il salvataggio dei file HDF5 grezzi nella cartella `data/raw`. *Default: `True`* (non salva). Impostare a `False` per attivare il salvataggio.

---

### 3. `scan-extended`
Scansione estesa automatizzata di **H1 e L1** contemporaneamente (Phase 4). A differenza del comando `scan`, questo comando sincronizza i due rivelatori: se interrotto, il resume riparte dal punto minimo comune ad entrambi per garantire un allineamento temporale perfetto.

- `--run`: Run osservativo. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--hours`: Override ore per rivelatore rispetto al config yaml (solo per nuovi scan).
- `--workers`: Numero di worker (deve essere un **numero pari**, es. 2, 4, 6, 8). I worker vengono divisi equamente tra H1 e L1. *Default: `1` (sequenziale)*.
- `--session-id`: ID sessione. *Default: auto-generato*.
- `--no-cache-raw`: Flag booleano. Disabilita il salvataggio dei file HDF5 grezzi nella cartella `data/raw`. *Default: `True`* (non salva). Impostare a `False` per attivare il salvataggio.
- `--full-analysis`: Flag booleano. Se impostato a `True`, avvia automaticamente l'intera pipeline di analisi (`full-analysis`) al termine della scansione. *Default: `False`*.
- `--skip-timeslide`: Flag. Se la `full-analysis` automatica è attiva, salta l'analisi timeslide.
- `--n-runs`: Numero di run per la stability analysis (se `full-analysis` è attiva). *Default: `20`*.
- `--sequential`: Se `full-analysis` è attiva, esegue l'analisi dei detector in sequenza anziché in parallelo.
- `--start-gps`: Fornisce un tempo GPS d'inizio fisso, bypassando la logica di resume automatico o del run start.
- `--continue-run`: Flag. Attiva il ciclo continuo di scansione e analisi sincronizzata (loop di resume). Al termine dell'analisi completa corrente, genera una nuova sessione e lancia `scan-extended` a partire da `GPS = min(last_H1, last_L1) + 1` con la durata definita in `config.yaml`, per poi ri-analizzarla.
- `--max-iterations`: Numero massimo di iterazioni per il ciclo continuo. *Default: `10`*.
- `--stop-date`: Limite temporale (data ISO UTC o tempo GPS) oltre il quale interrompere il ciclo continuo.

---

### 4. `fetch-raw`
Tool per il download massivo di dati strain (GWOSC) in formato `.hdf5`. Supporta l'esecuzione parallela sincronizzata per H1 e L1. Se lanciato con `--workers`, suddivide il carico tra i due detector garantendo che l'intervallo temporale scaricato sia identico per entrambi.

- `--detector`: Rivelatore. Scelte: `H1`, `L1`, `V1`. *Opzionale se si usa --workers*.
- `--workers`: Numero totale di worker. Deve essere un **numero pari** (2, 4, 6 o 8). Se usato, attiva il download parallelo H1+L1.
- `--run`: Run osservativo base. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--hours`: Ore totali da scaricare. *Default: `1.0`*.
- `--output-dir`: Cartella output cache. *Default: `data/raw`*.
- `--segment-duration`: Durata chunk in download (in secondi). *Default: `3600`*.
- `--no-resume`: Flag. Disattiva il resume automatico.
- `--no-cache-raw`: Flag booleano. Esegue il fetch dei dati ma **non salva** i file HDF5. *Default: `True`* (non salva). Impostare a `False` per attivare il salvataggio.
- `--retry`: Flag. Abilita la logica di retry con backoff esponenziale.

---

### 5. `last-gps`
Cerca negli spettrogrammi locali e restituisce a schermo il tempo GPS (end) più avanzato per riprendere run fermati senza invocare server esterni.

- `--detector` **(Richiesto)**: Rivelatore. Scelte: `H1`, `L1`, `V1`.
- `--session-id` **(Richiesto)**: ID sessione per trovare la directory giusta.
- `--run`: Run osservativo di ricerca. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.

---

## Pipeline ML

### 6. `reprocess-spectrograms`
Ri-renderizza tutti i file PNG esistenti applicando i setting visivi correnti del config.yaml (ad esempio, per una nuova colormap).

- `--session-id`: ID sessione. Necessario assieme a `--detector`.
- `--detector`: Rivelatore. Scelte: `H1`, `L1`, `V1`.
- `--run`: Run osservativo in uso. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--input-dir`: Path esplicito agli spettrogrammi. Override dei param session/detector.
- `--workers`: Numero thread. *Default: `1`*.
- `--backup`: Flag. Salva un file backup prima di rimpiazzare `.png`.
- `--dry-run`: Flag. Analizza e stampa a video i task previsti senza eseguire file writing.
- `--use-cache`: Flag. Controlla prima il local raw-data cache per il download `hdf5`.

---

### 7. `encode`
Usa il modello DINOv2-Reg preaddestrato per mappare gli spettrogrammi in vettori embedding ad alta dimensionalità.

- `--session-id`: ID sessione in lettura.
- `--detector`: Rivelatore per cui estrarre data. Scelte: `H1`, `L1`, `V1`.
- `--run`: Run osservativo. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--input-dir`: Cartella diretta file `.png`.
- `--output`: File di arrivo (`.npy`).
- `--batch-size`: Batch inference size PyTorch. *Default: `32`*.

---

### 8. `cluster`
Prende il file `.npy` di encode e raggruppa dinamicamente i dati con PCA, UMAP, HDBSCAN trovando eventuali classi sconosciute di glitch. 

- `--session-id`: ID della sessione per auto-matching cartelle.
- `--detector`: Rivelatore (`H1`, `L1`, `V1`). 
- `--run`: Run osservativo (`O2`, `O3a`, `O3b`, `O4a`). *Default: `O4a`*.
- `--input`: File numpy (`.npy`).
- `--output`: Cartella in cui salvare i plot e i report JSON.

---

### 9. `report`
Rigenera gallerie d'immagini riepilogative e plot UMAP 2D caricando il JSON risultante da un precedente `cluster`.

- `--session-id`: ID della sessione target.
- `--detector`: Rivelatore target (`H1`, `L1`, `V1`).
- `--run`: Run osservativo (`O2`, `O3a`, `O3b`, `O4a`). *Default: `O4a`*.
- `--embeddings`: Path ad embedding.
- `--report`: Path a JSON (`cluster_report.json`).
- `--output-dir`: Cartella output custom.

---

## Analisi & Validazione

### 10. `stability`
Riesegue svariate volte (n-runs) il cluster introducendo micro-perturbazioni in HDBSCAN e UMAP, e tramite Adjusted Rand Index verifica la robustezza.

- `--n-runs`: Numero di prove ripetute. *Default: `20`*.
- `--detector`: Rivelatore (`H1`, `L1`, `V1`). *Default: `H1`*.
- `--run`: Run osservativo (`O2`, `O3a`, `O3b`, `O4a`). *Default: `O4a`*.
- `--session-id`: ID della sessione target.
- `--embeddings`: Path input `.npy`.

---

### 11. `ablation`
Valuta l'impatto pre-processuale. Muta le immagini PNG sorgente e analizza l'accuratezza in ARI dei vari cluster.

- `--detector`: Rivelatore target. Scelte: `H1`, `L1`, `V1`.
- `--run`: Run osservativo in esame. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--session-id`: ID sessione.
- `--embeddings`: Path baseline embedding `.npy`.
- `--spectrogram-dir`: Percorso agli spettrogrammi intatti `.png`.
- `--output-dir`: JSON in uscita.
- `--batch-size`: Batch size per DINOv2. *Default: `32`*.

---

### 12. `crosscheck`
Incrocia i cluster anomali del JSON col set reale di LIGO tramite query remote via API in Gravity Spy.

- `--report` **(Richiesto)**: Path al JSON output del comando cluster.
- `--metadata` **(Richiesto)**: Path JSON dei metadati base forniti da `encode`.
- `--detector`: Rivelatore usato (filtra query LIGO). Scelte: `H1`, `L1`, `V1`. *Default: `H1`*.
- `--output`: Path in cui redigere un resoconto finale JSON.

---

### 13. `timeslide`
Estima p-value per anomali pattern di background coincidenziale incrociando `H1` e `L1`.

- `--run`: Run osservativo. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--session-id`: ID univoco sessione per auto-parsing file.
- `--embeddings-h1` / `--embeddings-l1`: Path a matrice embeddings dei rivelatori.
- `--metadata-h1` / `--metadata-l1`: Path ai metadati base `.json`.
- `--report-h1` / `--report-l1`: Path ai json finali del cluster.

---

## Reference Index

### 14. `build-reference`
Avvia il builder estraendo dal gigantesco tar di addestramento `.tar.gz` di Gravity Spy un indice pre-compilato di embeddings morfologici.

- `--output` **(Richiesto)**: Destinazione finale per il `.npz`.
- `--max-per-class`: Campioni estratti da ogni classe. *Default: `50`*.
- `--tar-path`: Percorso al .tar.gz originale in locale. *Default: `data/reference/trainingsetv1d1.tar.gz`*.

---

### 15. `build-indomain-reference`
Alternativa che scarica i GPS categorizzati di GravitySpy e scarica i dati freschi da GWOSC riprocessandoli direttamente coi filtri attuali, bypassando discrepanze (domain gap).

- `--output` **(Richiesto)**: Path finale all'indice creato `.npz`.
- `--detector`: Rivelatore associato alle classi. Scelte: `H1`, `L1`, `V1`. *Default: `H1`*.
- `--run`: Run osservativo usato come target dati di apprendimento. *Default: `O3b`*.
- `--max-per-class`: Limitazione query per categoria base. *Default: `30`*.
- `--min-confidence`: Accuratezza minima richiesta su GWOSC per includere glitch. *Default: `0.95`*.
- `--workers`: Numero Thread. *Default: `1`*.

---

### 16. `validate-reference`
Validazione on-the-fly. Carica l'indice npz (da build o build-indomain), innesca ricerca top-5 nearest-neighbor con un target per certificarne l'allineamento dati.

- `--reference` **(Richiesto)**: Path indice pre-estratto `.npz`.
- `--test-event`: Evento per l'injection di stress-test (es. `GW150914`). *Default: `GW150914`*.

---

### 17. `morphcheck`
Utilizza un indice di riferimento (via in-domain o standard npz) per valutare i cluster identificati. Determina e classifica ogni sample anomalo come NOVEL o KNOWN.

- `--embeddings` **(Richiesto)**: Path file Numpy base array.
- `--report` **(Richiesto)**: Path cluster report JSON a cui si fa capo.
- `--reference` **(Richiesto)**: Indice `.npz` di paragone generato su GravitySpy.
- `--output` **(Richiesto)**: Percorso del file JSON in uscita (es. `morphological_crosscheck_indomain.json`). Contiene la classificazione di ogni spettrogramma anomalo (NOVEL, KNOWN, AMBIGUOUS).
- `--run`: Run associato. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.

---

### 18. `full-analysis`
Automatizza l'intero workflow di analisi. Per impostazione predefinita, l'analisi di **H1 e L1 viene eseguita in parallelo** per massimizzare l'efficienza. Esegue: Encode (se necessario), Clustering, Morphological Cross-check, Ablation Study, Stability Analysis e Time-slide (se applicabile).

- `--session-id` **(Richiesto)**: ID della sessione da analizzare.
- `--detector`: Uno o più rivelatori da analizzare (es. `--detector H1 L1`). Se omesso, il comando identifica automaticamente i rivelatori presenti nella cartella della sessione.
- `--run`: Run osservativo. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--skip-timeslide`: Flag. Forza l'esclusione dell'analisi timeslide anche se H1 e L1 sono entrambi presenti.
- `--n-runs`: Numero di run ripetuti per la stability analysis. *Default: `20`*.
- `--sequential`: Forza l'esecuzione sequenziale dei detector (prima H1, poi L1) invece di quella parallela predefinita.
- `--continue-run`: Flag. Attiva il ciclo continuo di scansione e analisi sincronizzata (loop di resume). Al termine dell'analisi completa corrente, genera una nuova sessione e lancia `scan-extended` a partire da `GPS = min(last_H1, last_L1) + 1` con la durata definita in `config.yaml`, per poi ri-analizzarla.
- `--max-iterations`: Numero massimo di iterazioni per il ciclo continuo. *Default: `10`*.
- `--stop-date`: Limite temporale (data ISO UTC o tempo GPS) oltre il quale interrompere il ciclo continuo.

> [!NOTE]
> **Session Summary:** Il report generato include ora una sezione iniziale `session_summary` con statistiche descrittive del dataset analizzato (numero di spettrogrammi, intervallo GPS, durata totale e duty cycle), calcolate direttamente dai file PNG prima dell'encoding.

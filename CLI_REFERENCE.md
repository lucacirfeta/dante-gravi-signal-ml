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

---

### 3. `scan-extended`
Scansione estesa automatizzata di **tutti i rivelatori** definiti in `config.yaml` (solitamente `H1` e `L1`) in sequenza. Effettua scansioni continue e permette resume automatici indipendenti per ogni rivelatore.

- `--run`: Run osservativo. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--hours`: Override ore per rivelatore rispetto al config yaml (solo per nuovi scan).
- `--workers`: Numero thread paralleli. *Default: `1`*.
- `--session-id`: ID sessione. *Default: auto-generato*.

---

### 4. `fetch-raw`
Tool indipendente per il download massivo di dati strain (GWOSC) come file .hdf5, usabili poi come cache locale. Implementa un blocco anti-interruzione.

- `--detector` **(Richiesto)**: Rivelatore. Scelte: `H1`, `L1`, `V1`.
- `--mode`: Modalità. Scelte: `current` (ultime N ore) o `o4a_start` (da inizio run O4a). *Default: `current`*.
- `--run`: Run osservativo base. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--hours`: Ore totali (se mode=`current`). *Default: `1.0`*.
- `--output-dir`: Cartella output cache. *Default: `data/raw`*.
- `--segment-duration`: Durata chunk in download (in secondi). *Default: `3600`*.
- `--no-resume`: Flag. Disattiva il check e resume dei file hdf5 già scaricati.
- `--retry`: Flag. Abilita la logica di retry in caso di fallimento del download. *Default: disabilitato*.

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
- `--output` **(Richiesto)**: Path output.
- `--run`: Run associato. Scelte: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.

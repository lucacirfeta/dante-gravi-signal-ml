# 📖 CLI Reference — gravi-signal-ml

> **Ultimo aggiornamento:** 2026-05-12  
> **Generato da:** `main.py` (1709 righe, 16 subcommand)  
> **Config di riferimento:** `config.yaml`

---

## Interfaccia Grafica (GUI)

È disponibile un'interfaccia grafica (basata su Gooey) per tutti i comandi elencati in questo documento. Per avviarla, esegui:
```bash
python gui.py
```
La GUI genererà automaticamente i campi di input per tutti i parametri richiesti.

---

## Indice comandi

| # | Comando | Descrizione | Prerequisiti |
|---|---------|-------------|--------------|
| 1 | [`fetch`](#1-fetch) | Scarica un evento GW noto e genera uno spettrogramma di validazione | Connessione internet |
| 2 | [`scan`](#2-scan) | Scansiona segmenti per un singolo rivelatore (O2-O4a) | Connessione internet |
| 3 | [`scan-extended`](#3-scan-extended) | Scansione estesa H1 + L1 in sequenza (O2-O4a) | Connessione internet |
| 4 | [`last-gps`](#4-last-gps) | Stampa l'ultimo tempo GPS trovato negli spettrogrammi di una sessione | Sessione con PNG esistenti |
| 5 | [`reprocess-spectrograms`](#5-reprocess-spectrograms) | Ri-renderizza gli spettrogrammi con la colormap corrente | PNG esistenti + connessione internet |
| 6 | [`encode`](#6-encode) | Estrae embedding DINOv2 dagli spettrogrammi | PNG da scan/scan-extended |
| 7 | [`cluster`](#7-cluster) | Raggruppa gli embedding per scoprire classi di glitch | Embedding da encode |
| 8 | [`report`](#8-report) | Rigenera grafici UMAP e gallery dai risultati esistenti | Embedding + cluster_report.json |
| 9 | [`stability`](#9-stability) | Misura robustezza del clustering con ARI su run multipli | Embedding da encode |
| 10 | [`ablation`](#10-ablation) | Studio di ablazione: verifica se il clustering cattura morfologie reali | Embedding + PNG originali |
| 11 | [`crosscheck`](#11-crosscheck) | Confronto anomalie con database Gravity Spy via API | ⚠️ Auth LIGO richiesta |
| 12 | [`build-reference`](#12-build-reference) | Costruisce indice di riferimento dal training set Gravity Spy | ⚠️ Download ~5 GB tar.gz |
| 13 | [`morphcheck`](#13-morphcheck) | Confronto morfologico con indice di riferimento | Indice .npz + embedding |
| 14 | [`build-indomain-reference`](#14-build-indomain-reference) | Costruisce riferimento in-domain da GPS etichettati | ⚠️ Download da GWOSC + Zenodo |
| 15 | [`validate-reference`](#15-validate-reference) | Valida l'indice di riferimento con GW150914 | Indice .npz costruito |
| 16 | [`timeslide`](#16-timeslide) | Stima la significatività delle coincidenze background tra H1 e L1 | Risultati clustering per H1 e L1 |

---

## 1. `fetch`

**Cosa fa:** Scarica i dati strain di un evento gravitazionale noto (es. GW150914), applica whitening + bandpass e salva lo spettrogramma Q-transform come PNG. Serve come proof-of-concept per verificare che la pipeline di preprocessing sia corretta (il chirp deve essere visibile).

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--event` | `str` | ✅ | — | Nome evento di riferimento (`GW150914`, `GW170817`, `GW231123`) |

**Esempio:**
```bash
python main.py fetch --event GW150914
```

**Output:** `data/spectrograms/GW150914_H1.png` — spettrogramma Q-transform 256×256.  
**Log:** `Phase 1 complete. Chirp visible at data/spectrograms/GW150914_H1.png`

**Note:** Eseguire una sola volta. Richiede connessione internet per scaricare dati da GWOSC.

---

## 2. `scan`

**Cosa fa:** Scansiona segmenti dell'osservazione O4a per un singolo rivelatore, generando spettrogrammi PNG. Supporta **modalità incrementale**: se si fornisce `--session-id` di una sessione esistente, riparte automaticamente dall'ultimo tempo GPS trovato nei file PNG.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--detector` | `str` | ✅ | — | Rivelatore: `H1`, `L1` o `V1` |
| `--run` | `str` | — | `O4a` | Run osservativo: `O2`, `O3a`, `O3b`, `O4a` |
| `--hours` | `float` | — | `1.0` | Durata da scansionare (ore). Ignorato in modalità incrementale |
| `--workers` | `int` | — | `1` | Worker paralleli. `1` = sequenziale. Consigliato: `6` |
| `--session-id` | `str` | — | `auto` | ID sessione (es. `20260510_143022`). Auto-generato se omesso |

**Esempio — nuova scansione:**
```bash
python main.py scan --detector H1 --hours 6 --workers 6
```

**Esempio — ripresa incrementale:**
```bash
python main.py scan --detector H1 --session-id 20260510_143022
```

**Output:** `data/spectrograms/{run_lower}/<SESSION_ID>/H1/*.png`  
**Log:** `Scan complete: N processed, M skipped, X.X h scanned`

**Note:** In modalità incrementale la durata viene letta da `config.yaml → scan_extended.hours_per_detector` (default: 48h), non da `--hours`. I thread GWOSC sono limitati a 4 (`config.yaml → performance.gwosc_fetch_threads`).

---

## 3. `scan-extended`

**Cosa fa:** Esegue una scansione estesa su entrambi i rivelatori H1 e L1 in sequenza, con offset temporali configurabili. I parametri vengono letti da `config.yaml → scan_extended`. Supporta modalità incrementale per-detector.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--workers` | `int` | — | `1` | Worker paralleli |
| `--run` | `str` | — | `O4a` | Run osservativo: `O2`, `O3a`, `O3b`, `O4a` |
| `--hours` | `int` | — | `48` (da config) | Override ore per rivelatore |
| `--session-id` | `str` | — | `auto` | ID sessione |

**Esempio:**
```bash
python main.py scan-extended --workers 6

# Ripresa incrementale
python main.py scan-extended --workers 6 --session-id 20260510_143022
```

**Output:** `data/spectrograms/{run_lower}/<SESSION_ID>/H1/*.png` e `.../L1/*.png`  
**Log:** `Extended scan complete: H1=N L1=M spectrograms saved.`

**Note:** Offset di default: letti da `config.yaml` (`run_config`). Detectors: `["H1", "L1"]` da config.

---

## 4. `last-gps`

**Cosa fa:** Scansiona i nomi dei file PNG in una directory di sessione e stampa il tempo GPS di fine più alto trovato. Utile per verificare fino a dove è arrivata una scansione senza contattare GWOSC.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--session-id` | `str` | ✅ | — | ID sessione |
| `--detector` | `str` | ✅ | — | Rivelatore: `H1`, `L1`, `V1` |
| `--run` | `str` | — | `O4a` | Run osservativo |

**Esempio:**
```bash
python main.py last-gps --session-id 20260510_143022 --detector H1
```

**Output:** Stampa su stdout il valore GPS intero (es. `1369620018`).  
**Note:** Non effettua chiamate di rete. Richiede PNG con formato `<DET>_<start>_<end>.png`.

---

## 5. `reprocess-spectrograms`

**Cosa fa:** Ri-scarica i dati strain e ri-genera gli spettrogrammi con la colormap corrente da `config.yaml → preprocessing.colormap` (default: `cividis`). Utile dopo una migrazione di colormap.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--session-id` | `str` | — | `None` | ID sessione (richiede anche `--detector`) |
| `--detector` | `str` | — | `None` | Rivelatore |
| `--run` | `str` | — | `O4a` | Run osservativo |
| `--input-dir` | `str` | — | `None` | Path esplicito alla directory PNG. Override di session-id+detector |
| `--workers` | `int` | — | `1` | Worker paralleli |
| `--backup` | flag | — | `False` | Crea `.viridis.bak.png` prima di sovrascrivere |
| `--dry-run` | flag | — | `False` | Solo report, nessuna modifica |
| `--use-cache` | flag | — | `False` | Cerca file HDF5 locali in `data/raw/` prima di ri-scaricare |

**Esempio:**
```bash
# Dry run per vedere quanti PNG verrebbero rielaborati
python main.py reprocess-spectrograms --session-id 20260510_143022 --detector H1 --dry-run

# Esecuzione reale con backup e cache
python main.py reprocess-spectrograms --session-id 20260510_143022 --detector H1 --workers 6 --backup --use-cache
```

**Output:** PNG sovrascritti nella stessa directory. Backup opzionali `*.viridis.bak.png`.  
**Log:** `Reprocessing complete: N succeeded, M failed (colormap: cividis)`

---

## 6. `encode`

**Cosa fa:** Carica il modello DINOv2-Reg (ViT-S/14) e produce un vettore di embedding a 384 dimensioni per ogni spettrogramma PNG. Salva un array `.npy` e un file `.json` con i metadati dei file elaborati.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--input-dir` | `str` | — | `None` | Directory con PNG. Override di session-id+detector |
| `--output` | `str` | — | `None` | Path file `.npy`. Override di session-id+detector |
| `--batch-size` | `int` | — | `32` | Batch size per inferenza |
| `--session-id` | `str` | — | `None` | ID sessione |
| `--detector` | `str` | — | `None` | Rivelatore: `H1`, `L1`, `V1` |
| `--run` | `str` | — | `O4a` | Run osservativo |

Serve almeno `--input-dir` oppure `--session-id` + `--detector`.

**Esempio:**
```bash
python main.py encode --session-id 20260510_143022 --detector H1
```

**Output:**  
- `data/embeddings/{run_lower}/<SESSION_ID>/{run_lower}_h1.npy` — array `(N, 384)` float32  
- `data/embeddings/{run_lower}/<SESSION_ID>/{run_lower}_h1.json` — metadati  

**Log:** `Phase 2 complete. Embeddings ready for Phase 3 clustering.`

**Note:** Il modello DINOv2 (~90 MB) viene scaricato al primo avvio via `torch.hub`. CPU-only, ~10 min per 2600 immagini.

---

## 7. `cluster`

**Cosa fa:** Esegue la pipeline di clustering non supervisionato: PCA(50D) → UMAP(10D) → HDBSCAN → UMAP(2D) per visualizzazione. Identifica cluster anomali e genera report + grafici.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--input` | `str` | — | `None` | Path embedding `.npy`. Override di session-id+detector |
| `--output` | `str` | — | `data/clusters/` | Directory output |
| `--session-id` | `str` | — | `None` | ID sessione |
| `--detector` | `str` | — | `None` | Rivelatore: `H1`, `L1`, `V1` |
| `--run` | `str` | — | `O4a` | Run osservativo |

**Esempio:**
```bash
python main.py cluster --session-id 20260510_143022 --detector H1
```

**Output:**  
- `data/clusters/{run_lower}/<SESSION_ID>/h1/cluster_report.json`  
- `data/clusters/{run_lower}/<SESSION_ID>/h1/umap_visualization.png`  
- `data/clusters/{run_lower}/<SESSION_ID>/h1/cluster_gallery/cluster_N/contact_sheet.png`  

**Log:** `Phase 3 complete. Results in data/clusters/...`

**Note:** `min_cluster_size` auto-scalato a 0.5% di N. `anomaly_threshold` auto-scalato a 1% di N.

---

## 8. `report`

**Cosa fa:** Rigenera i grafici UMAP 2D e le gallery dei cluster a partire da embedding e `cluster_report.json` già esistenti. Non riesegue il clustering, ma ricalcola PCA e UMAP.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--embeddings` | `str` | — | `None` | Path embedding `.npy` |
| `--report` | `str` | — | `None` | Path `cluster_report.json` |
| `--output-dir` | `str` | — | `data/clusters/` | Directory output |
| `--session-id` | `str` | — | `None` | ID sessione |
| `--detector` | `str` | — | `None` | Rivelatore |
| `--run` | `str` | — | `O4a` | Run osservativo |

**Esempio:**
```bash
python main.py report --session-id 20260510_143022 --detector H1
```

**Output:** `umap_visualization.png` e `cluster_gallery/` aggiornati nella directory di output.

---

## 9. `stability`

**Cosa fa:** Esegue il clustering N volte con perturbazioni casuali dei parametri UMAP (`n_neighbors`) e HDBSCAN (`min_cluster_size`). Calcola l'ARI (Adjusted Rand Index) tra ogni coppia di run per valutare la robustezza.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--embeddings` | `str` | — | `None` | Path embedding `.npy` |
| `--n-runs` | `int` | — | `20` | Numero di run perturbati |
| `--session-id` | `str` | — | `None` | ID sessione |
| `--detector` | `str` | — | `H1` | Rivelatore |
| `--run` | `str` | — | `O4a` | Run osservativo |

**Esempio:**
```bash
python main.py stability --session-id 20260510_143022 --detector H1 --n-runs 20
```

**Output:** `data/stability/{run_lower}/<SESSION_ID>/stability_report.json` — contiene matrice ARI N×N e cluster consistentemente anomali (≥80% dei run).

---

## 10. `ablation`

**Cosa fa:** Testa se il clustering cattura morfologie fisiche reali o artefatti di rendering. Genera embedding alternativi da spettrogrammi perturbati (scala di grigi, invertiti, intensità mescolata, random) e confronta i cluster risultanti con quelli originali tramite ARI.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--embeddings` | `str` | — | `None` | Path embedding baseline `.npy` |
| `--spectrogram-dir` | `str` | — | `None` | Directory spettrogrammi originali |
| `--output-dir` | `str` | — | `data/ablation/` | Directory output |
| `--session-id` | `str` | — | `None` | ID sessione |
| `--detector` | `str` | — | `None` | Rivelatore |
| `--run` | `str` | — | `O4a` | Run osservativo |
| `--batch-size` | `int` | — | `32` | Batch size DINOv2 |

**Esempio:**
```bash
python main.py ablation --session-id 20260510_143022 --detector H1
```

**Output:** `data/ablation/{run_lower}/<SESSION_ID>/ablation_report.json`

**Note:** Se ARI grayscale < 0.4, la pipeline segnala comportamento "preprocessing-dominant".

---

## 11. `crosscheck`

⚠️ **Richiede autenticazione LIGO per le API Gravity Spy.**

**Cosa fa:** Confronta i cluster anomali con il database Gravity Spy tramite query GPS, per verificare se i glitch sono già classificati.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--report` | `str` | ✅ | — | Path `cluster_report.json` |
| `--metadata` | `str` | ✅ | — | Path metadati encoder `.json` |
| `--detector` | `str` | — | `H1` | Rivelatore per query Gravity Spy |
| `--output` | `str` | — | `None` | Path output JSON |

**Esempio:**
```bash
python main.py crosscheck \
  --report data/clusters/o4a/20260510_143022/h1/cluster_report.json \
  --metadata data/embeddings/o4a/20260510_143022/o4a_h1.json \
  --detector H1
```

**Output:** JSON con risultati del confronto. Log: `Cross-check complete. Results: N unclassified candidates.`

---

## 12. `build-reference`

⚠️ **Richiede download manuale di `trainingsetv1d1.tar.gz` (~5 GB) da Zenodo.**

**Cosa fa:** Costruisce un indice di riferimento DINOv2 dal training set Gravity Spy. Estrae PNG dal tar.gz, genera embedding e salva un file `.npz`.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--output` | `str` | ✅ | — | Path output `.npz` |
| `--max-per-class` | `int` | — | `50` | Max campioni per classe |
| `--tar-path` | `str` | — | `data/reference/trainingsetv1d1.tar.gz` | Path al file tar.gz |

**Esempio:**
```bash
python main.py build-reference --output data/reference/gravity_spy_index.npz --max-per-class 50
```

**Output:** `data/reference/gravity_spy_index.npz`

**Note:** ⚠️ Domain gap: le immagini Gravity Spy usano parametri Q-transform diversi. Preferire `build-indomain-reference`.

---

## 13. `morphcheck`

**Cosa fa:** Esegue un confronto morfologico KNN-coseno tra gli embedding dei cluster e un indice di riferimento. Ogni spettrogramma anomalo riceve un'etichetta: `NOVEL`, `KNOWN` o `AMBIGUOUS`.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--embeddings` | `str` | ✅ | — | Path embedding `.npy` |
| `--report` | `str` | ✅ | — | Path `cluster_report.json` |
| `--reference` | `str` | ✅ | — | Path indice `.npz` (da build-reference o build-indomain-reference) |
| `--output` | `str` | ✅ | — | Path output JSON |
| `--run` | `str` | — | `O4a` | Run osservativo per query Gravity Spy e logging |

**Esempio:**
```bash
python main.py morphcheck \
  --embeddings data/embeddings/o4a/20260510_143022/o4a_h1.npy \
  --report data/clusters/o4a/20260510_143022/h1/cluster_report.json \
  --reference data/reference/indomain_index.npz \
  --output data/clusters/o4a/20260510_143022/h1/morphological_crosscheck.json \
  --run O4a
```

**Output:** JSON con label per-spettrogramma. Log: `Morphological check complete. N novel candidates.`

**Note:** Soglie da `config.yaml → similarity`: `novelty_threshold: 0.85`, `consensus_threshold: 0.60`, `k_neighbors: 5`.

---

## 14. `build-indomain-reference`

⚠️ **Scarica CSV da Zenodo (~50 MB) e dati strain da GWOSC. Può richiedere ore.**

**Cosa fa:** Scarica timestamp GPS etichettati da Gravity Spy (Zenodo), recupera i dati strain da GWOSC, li processa attraverso la **nostra** pipeline e genera un indice di riferimento in-domain. Elimina il domain gap rispetto a `build-reference`.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--output` | `str` | ✅ | — | Path output `.npz` |
| `--detector` | `str` | — | `H1` | Rivelatore |
| `--run` | `str` | — | `O3b` | Run osservativo (es. `O3b`) |
| `--max-per-class` | `int` | — | `30` | Max campioni per classe |
| `--min-confidence` | `float` | — | `0.95` | Soglia minima di confidenza ML |
| `--workers` | `int` | — | `1` | Worker paralleli per fetch GWOSC |

**Esempio:**
```bash
python main.py build-indomain-reference \
  --output data/reference/indomain_index.npz \
  --detector H1 --run O3b --max-per-class 30
```

**Output:** `data/reference/indomain_index.npz`

---

## 15. `validate-reference`

**Cosa fa:** Verifica che l'indice di riferimento funzioni correttamente usando GW150914 come test. Scarica l'evento, genera embedding e cerca i 5 vicini più simili nell'indice. Il test passa se il vicino più prossimo è di classe `Chirp`.

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--reference` | `str` | ✅ | — | Path indice `.npz` |
| `--test-event` | `str` | — | `GW150914` | Evento di test |

**Esempio:**
```bash
python main.py validate-reference \
  --reference data/reference/indomain_index.npz \
  --test-event GW150914
```

**Output:** Stampa top-5 vicini con similarità coseno. `✅ PASS` se il più vicino è `Chirp`.

---

## 16. `timeslide`

**Cosa fa:** Estrae i tempi GPS degli spettrogrammi anomali per H1 e L1 dai report di clustering. Calcola le coincidenze a zero-lag (finestra ±32s) e stima la significatività statistica (p-value e z-score) rispetto a un fondo casuale generato con time-slide (shift temporali multipli di 100s).

| Argomento | Tipo | Obbligatorio | Default | Descrizione |
|-----------|------|:---:|---------|-------------|
| `--session-id` | `str` | — | `None` | ID sessione (risolve automaticamente tutti i path se usato) |
| `--run` | `str` | — | `O4a` | Run osservativo |
| `--embeddings-h1` | `str` | — | `None` | Path embedding H1 |
| `--embeddings-l1` | `str` | — | `None` | Path embedding L1 |
| `--metadata-h1` | `str` | — | `None` | Path metadata H1 `.json` |
| `--metadata-l1` | `str` | — | `None` | Path metadata L1 `.json` |
| `--report-h1` | `str` | — | `None` | Path cluster report H1 |
| `--report-l1` | `str` | — | `None` | Path cluster report L1 |

**Esempio:**
```bash
python main.py timeslide --session-id 20260510_143022
```

**Output:** `data/timeslide/{run_lower}/<SESSION_ID>/timeslide_report.json` con p-value, z-score, e interpretazione.  
**Log:** `Time-slide: zero-lag=X coincidences, background mean=Y±Z, p-value=P`

---

## 🔄 Flusso completo per nuova sessione

Eseguire i comandi nell'ordine seguente. Sostituire `<SID>` con il Session ID stampato al punto 1.

```bash
# ── 0. Setup una tantum (solo la prima volta) ──────────────────────
python main.py fetch --event GW150914                          # Verifica pipeline
python main.py build-indomain-reference \
  --output data/reference/indomain_index.npz                   # ⚠️ ~1-2 ore
python main.py validate-reference \
  --reference data/reference/indomain_index.npz                # Deve stampare ✅ PASS

# ── 1. Scansione ───────────────────────────────────────────────────
python main.py scan-extended --workers 6 --run O4a
# → Annotare il Session ID stampato: <SID>

# ── 2. Estrazione feature ─────────────────────────────────────────
python main.py encode --session-id <SID> --detector H1 --run O4a
python main.py encode --session-id <SID> --detector L1 --run O4a

# ── 3. Clustering ─────────────────────────────────────────────────
python main.py cluster --session-id <SID> --detector H1 --run O4a
python main.py cluster --session-id <SID> --detector L1 --run O4a

# ── 4. Confronto morfologico ──────────────────────────────────────
python main.py morphcheck \
  --embeddings data/embeddings/o4a/<SID>/o4a_h1.npy \
  --report data/clusters/o4a/<SID>/h1/cluster_report.json \
  --reference data/reference/indomain_index.npz \
  --output data/clusters/o4a/<SID>/h1/morphological_crosscheck.json \
  --run O4a

python main.py morphcheck \
  --embeddings data/embeddings/o4a/<SID>/o4a_l1.npy \
  --report data/clusters/o4a/<SID>/l1/cluster_report.json \
  --reference data/reference/indomain_index.npz \
  --output data/clusters/o4a/<SID>/l1/morphological_crosscheck.json \
  --run O4a

# ── 5. Validazione robustezza e coincidenze ───────────────────────
python main.py ablation --session-id <SID> --detector H1 --run O4a
python main.py stability --session-id <SID> --detector H1 --n-runs 20 --run O4a
python main.py timeslide --session-id <SID> --run O4a
```

---

## 🔧 Note tecniche

### Parametri hardware consigliati

| Componente | Minimo | Consigliato |
|-----------|--------|-------------|
| CPU | 4 core | 8+ core (es. Ryzen 7 7800X3D) |
| RAM | 8 GB | 16+ GB |
| Disco | 10 GB liberi | 50+ GB (per scansioni estese) |
| GPU | Non richiesta | Non supportata (PyTorch stable non supporta sm_120) |
| Rete | Necessaria per scan/fetch | Stabile per scansioni lunghe |

### Valori config.yaml di riferimento

| Parametro | Valore | Descrizione |
|-----------|--------|-------------|
| `preprocessing.colormap` | `cividis` | Colormap percettivamente uniforme |
| `preprocessing.sample_rate` | `4096` Hz | Frequenza campionamento |
| `preprocessing.f_low / f_high` | `20 / 2000` Hz | Banda del filtro passa-banda |
| `preprocessing.output_size` | `256 × 256` | Dimensione spettrogrammi |
| `encoder.model` | `dinov2_vits14_reg` | ViT-S/14 con token registro |
| `encoder.embedding_dim` | `384` | Dimensionalità embedding |
| `clustering.pca_components` | `50` | Componenti PCA |
| `clustering.hdbscan.min_cluster_size` | `auto` (0.5% di N) | Dimensione minima cluster |
| `scan_extended.hours_per_detector` | `48` | Ore per rivelatore |
| `performance.default_workers` | `1` | Worker sequenziali |
| `performance.gwosc_fetch_threads` | `4` | Max thread GWOSC (rate limit) |

### Variabili d'ambiente

| Variabile | Effetto |
|-----------|---------|
| `GWPY_CACHE=1` | Abilita caching nativo gwpy per evitare re-download |

### Convenzione nomi file PNG

```
<DETECTOR>_<GPS_START>_<GPS_END>.png
Esempio: H1_1369598418_1369598450.png
```

Usata da `scan`, `scan-extended`, `last-gps`, `reprocess-spectrograms` per parsing automatico.

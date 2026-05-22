# 🔬 Registro Risultati Scientifici e Benchmark (RESULTS.md)

Questo documento raccoglie la cronologia dei run effettuati con la pipeline `gravi-signal-ml`. I dati sono organizzati per **Run osservativo** e **Session ID** per tracciare l'evoluzione delle analisi nel tempo.

---

## 📦 Intervalli di Dati Scaricati (HDF5 Cache)

Di seguito sono registrati gli intervalli temporali GPS scaricati e memorizzati localmente come cache grezza in `data/raw/` per le analisi:

| Identificativo | Intervallo GPS Inizio | Intervallo GPS Fine | Durata Totale (Ore) | Stato / Note      |
|:---------------|:----------------------|:--------------------|:-------------------:|:------------------|
| `run1`         | `1370206208`          | `1371415808`        |       `336.0`       | Scaricato offline |
| `run2`         | `1382903808`          | `1384113408`        |       `336.0`       | Scaricato offline |

---

## 📅 Indice Cronologico delle Sessioni

| Run   | Session ID        | Data/Ora Run                         | Stato Analisi                      | Rilevazioni Salienti / Anomalie Novel |
|:------|:------------------|:-------------------------------------|:-----------------------------------|:--------------------------------------|
| `O4a` | `run1`            | `2026-05-22 07:03:51`                | Completato (OK)                    | Nessun cluster anomalo (0 NOVEL)      |
| `O4a` | `20260520_223147` | `[NON DISPONIBILE]`                  | [NON DISPONIBILE]                  | [NON DISPONIBILE]                     |

---

## 📑 Dettaglio Sessioni

### Sessione: `O4a - run1`

**Completato con successo:** Nessuna nuova morfologia identificata.

#### 📊 1. Statistiche Dataset e Preprocessing
| Detector | Spettrogrammi Totali | Duty Cycle (%) | Colormap  | Note / Limitazioni |
|:---------|:--------------------:|:--------------:|:---------:|:-------------------|
| **H1**   |      `21991`         |     `59.2%`    | `cividis` | Nessuna            |
| **L1**   |      `29953`         |     `79.6%`    | `cividis` | Nessuna            |

#### 🤖 2. Risultati del Clustering (DPMM + Cosine)
| Detector | Numero Cluster | Campioni nel Cluster Dominante | Cluster Anomalous (# ID / Dimensioni) | Punti Rumore (Noise) | Varianza PCA (%) |
|:---------|:--------------:|:------------------------------:|:--------------------------------------|:--------------------:|:----------------:|
| **H1**   |      `11`      |            `13477`             | Nessuno                               |         `0`          |     `98.7%`      |
| **L1**   |      `15`      |            `13571`             | Nessuno                               |         `0`          |     `98.0%`      |

#### 🛡️ 3. Validazione Robustezza (Ablation & Stability)
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Shuffled-Intensity ARI | Esito Validazione                    |
|:---------|:------------------:|:----------------------:|:-------------------------------:|:-------------------------------------|
| **H1**   |       `0.896`      |         `0.897`        |             `0.830`             | Approvato                            |
| **L1**   |       `0.915`      |         `0.681`        |             `0.706`             | Approvato con lieve calo ablation    |

#### 🔗 4. Analisi Temporale (Time-Slide Coincidence)
| Finestra di Coincidenza | Numero Coincidenze a Lag Zero | p-value Empirico | Significatività (Z-score) | Esito |
| :--- | :---: | :---: | :---: | :--- |
| `±32s` | `0` | `1.0` | `0.0` | Casuale (compatibile con fondo) |

#### 🔬 5. Interpretazione Morfologica (Morphcheck in-domain)
Nessun cluster anomalo da analizzare (0 cluster trovati). Entrambi i detector hanno restituito una lista vuota in clustering. Tutti i glitch si sono mappati in morfologie attese o popolazioni continue di fondo.

---

### Sessione: `O4a - 20260520_223147`

#### 📊 1. Statistiche Dataset e Preprocessing
| Detector | Spettrogrammi Totali |   Duty Cycle (%)    | Colormap  | Note / Limitazioni |
|:---------|:--------------------:|:-------------------:|:---------:|:-------------------|
| **H1**   |       `26623`        | `[NON DISPONIBILE]` | `cividis` | Nessuna            |
| **L1**   |       `27541`        | `[NON DISPONIBILE]` | `cividis` | Nessuna            |

#### 🤖 2. Risultati del Clustering (DPMM + Cosine)
| Detector | Numero Cluster | Campioni nel Cluster Dominante | Cluster Anomalous (# ID / Dimensioni) | Punti Rumore (Noise) | Varianza PCA (%) |
|:---------|:--------------:|:------------------------------:|:--------------------------------------|:--------------------:|:----------------:|
| **H1**   |      `11`      |             `8033`             | `C7 (1 pts), C10 (1 pts), C1 (2 pts)` |         `0`          |     `98.7%`      |
| **L1**   |      `11`      |             `6997`             | `C17 (1 pts)`                         |         `0`          |     `98.7%`      |

#### 🛡️ 3. Validazione Robustezza (Ablation & Stability)
| Detector | Stability Mean ARI (σ) | Ablation Grayscale ARI | Ablation Shuffled-Intensity ARI | Esito Validazione |
|:---------|:----------------------:|:----------------------:|:-------------------------------:|:------------------|
| **H1**   |    `0.867 (±0.051)`    |        `0.620`         |             `0.865`             | Approvato         |
| **L1**   |    `0.971 (±0.013)`    |        `0.966`         |             `0.945`             | Approvato         |

#### 🔗 4. Analisi Temporale (Time-Slide Coincidence)
| Finestra di Coincidenza | Numero Coincidenze a Lag Zero | p-value Empirico | Significatività (Z-score) | Esito                           |
|:------------------------|:-----------------------------:|:----------------:|:-------------------------:|:--------------------------------|
| `±32s`                  |              `0`              |      `1.0`       |           `0.0`           | Casuale (compatibile con fondo) |

#### 🔬 5. Interpretazione Morfologica (Morphcheck in-domain)
| Detector | Cluster ID | Classificazione (KNOWN / NOVEL / AMBIGUOUS) | Mappatura Classi Gravity Spy Principali | Interpretazione Scientifica / Note |
|:---------|:----------:|:--------------------------------------------|:----------------------------------------|:-----------------------------------|
| **H1**   |   `C12`    | `KNOWN/AMBIGUOUS`                           | `[Low_Frequency_Lines, 1080Lines]`      | Composizione mista                 |
| **H1**   |   `C18`    | `AMBIGUOUS`                                 | `[Tomte, Fast_Scattering]`              | Cluster dominante                  |
| **L1**   |   `C10`    | `AMBIGUOUS`                                 | `[Low_Frequency_Lines, Whistle]`        | Cluster dominante                  |
| **L1**   |   `C18`    | `KNOWN`                                     | `[1400Ripples, Low_Frequency_Lines]`    | Popolazione stabile                |

#### 🧠 6. Interpretation (Run 2)
Cluster dominanti principalmente mappabili in classi esistenti o ambigue; nessuna nuova morfologia emergente ("NOVEL"). La robustezza su L1 è eccellente (ARI 0.97), mentre H1 presenta un leggero calo con grayscale ma rimane stabile. Nessun eccesso di coincidenze temporali riscontrato.

---

## ⚖️ Cross-Run Comparison

| Metrica                 | `run1 (20260522_074026)`           | `run2 (20260520_223147)` | Confronto   |
|:------------------------|:-----------------------------------|:-------------------------|:------------|
| Spettrogrammi (H1 / L1) | `21991` / `29953`                  | `26623` / `27541`        | Paragonabili |
| Numero Cluster          | H1 `11` / L1 `15`                  | `11` / `11`              | Più frammentazione in L1 (run1) |
| Classi Novel            | `0`                                | `0`                      | Coerente    |
| Robustezza (ARI)        | H1 `0.896`, L1 `0.915`             | H1 `0.867`, L1 `0.971`   | L1 leggermente meno robusto in run1 ma sempre >0.9 |

# 🔬 Registro Risultati Scientifici e Benchmark (RESULTS.md)

Questo documento raccoglie la cronologia dei run effettuati con la pipeline `gravi-signal-ml`. I dati sono organizzati per **Run osservativo** e **Session ID** per tracciare l'evoluzione delle analisi nel tempo.

---

## 📦 Intervalli di Dati Scaricati (HDF5 Cache)

Di seguito sono registrati gli intervalli temporali GPS scaricati e analizzati:

| Session ID        | Intervallo GPS Inizio | Data Inizio (UTC)     | Intervallo GPS Fine | Data Fine (UTC)       | Durata Totale (Ore) |
|:------------------|:----------------------|:----------------------|:--------------------|:----------------------|:--------------------|
| `20260520_223147` | `1382918784`          | `2023-11-02 00:06:06` | `1384112128`        | `2023-11-15 19:35:10` | `331.5`             |
| `20260522_074026` | `1370206208`          | `2023-06-07 20:49:50` | `1371395168`        | `2023-06-21 15:05:50` | `330.3`             |

---

## 📅 Indice Cronologico delle Sessioni

| Run   | Session ID        | Data/Ora Run          | Stato Analisi   | Rilevazioni Salienti (NOVEL)                |
|:------|:------------------|:----------------------|:----------------|:--------------------------------------------|
| `O4a` | `20260520_223147` | `2026-05-23 22:39:28` | Completato (OK) | (22 cluster potenziale NOVEL da similarity) |
| `O4a` | `20260522_074026` | `2026-05-23 22:39:07` | Completato (OK) | (26 cluster potenziale NOVEL da similarity) |

---

## 📑 Dettaglio Sessioni

### Sessione: `O4a - 20260520_223147`

#### 📊 1. Statistiche Dataset e Preprocessing
| Detector | Spettrogrammi Totali | Duty Cycle (%) | Colormap  | Note / Limitazioni |
|:---------|:--------------------:|:--------------:|:----------|:-------------------|
| **H1**   |       `26623`        |    `71.4%`     | `cividis` | Nessuna            |
| **L1**   |       `27541`        |    `81.5%`     | `cividis` | Nessuna            |

#### 🤖 2. Risultati del Clustering (DPMM + Cosine)
| Detector | Numero Cluster | Campioni nel Cluster Dominante | Cluster Anomalous (# ID / Dimensioni) | Punti Rumore (Noise) | Varianza PCA (%) |
|:---------|:--------------:|:------------------------------:|:--------------------------------------|:--------------------:|:----------------:|
| **H1**   |      `11`      |             `8033`             | `C1, C5, C7, C10`                     |         `0`          |     `98.7%`      |
| **L1**   |      `11`      |             `6997`             | `C17`                                 |         `0`          |     `98.7%`      |

#### 🛡️ 3. Validazione Robustezza (Ablation & Stability)
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Shuffled-Intensity ARI | Esito Validazione        |
|:---------|:------------------:|:----------------------:|:-------------------------------:|:-------------------------|
| **H1**   |      `0.859`       |        `0.620`         |             `0.866`             | Approvato con lieve calo |
| **L1**   |      `0.967`       |        `0.966`         |             `0.945`             | Approvato                |

#### 🔗 4. Analisi Temporale (Time-Slide Coincidence)
| Finestra di Coincidenza | Numero Coincidenze a Lag Zero | p-value Empirico | Significatività (Z-score) | Esito                           |
|:------------------------|:-----------------------------:|:----------------:|:-------------------------:|:--------------------------------|
| `±32s`                  |              `0`              |      `1.0`       |           `0.0`           | Casuale (compatibile con fondo) |

#### 🔬 5. Interpretazione Morfologica (Morphcheck in-domain)
I glitch si sono mappati in morfologie attese o popolazioni continue di fondo.


#### 📊 6. Analisi Similarità Sottovarianti (Analyze-Similarity)
| Detector | Cluster ID | Campioni | Interpretazione                 | Top-1 Classe (Similitudine)    |
|:---------|:----------:|:--------:|:--------------------------------|:-------------------------------|


---

### Sessione: `O4a - 20260522_074026`

#### 📊 1. Statistiche Dataset e Preprocessing
| Detector | Spettrogrammi Totali | Duty Cycle (%) | Colormap  | Note / Limitazioni |
|:---------|:--------------------:|:--------------:|:----------|:-------------------|
| **H1**   |       `21991`        |    `59.2%`     | `cividis` | Nessuna            |
| **L1**   |       `29953`        |    `79.6%`     | `cividis` | Nessuna            |

#### 🤖 2. Risultati del Clustering (DPMM + Cosine)
| Detector | Numero Cluster | Campioni nel Cluster Dominante | Cluster Anomalous (# ID / Dimensioni) | Punti Rumore (Noise) | Varianza PCA (%) |
|:---------|:--------------:|:------------------------------:|:--------------------------------------|:--------------------:|:----------------:|
| **H1**   |      `11`      |            `13477`             | `C7, C10, C11`                        |         `0`          |     `98.7%`      |
| **L1**   |      `15`      |            `13571`             | `C3, C6, C10, C13, C14, C17`          |         `0`          |     `98.0%`      |

#### 🛡️ 3. Validazione Robustezza (Ablation & Stability)
| Detector | Stability Mean ARI | Ablation Grayscale ARI | Ablation Shuffled-Intensity ARI | Esito Validazione        |
|:---------|:------------------:|:----------------------:|:-------------------------------:|:-------------------------|
| **H1**   |      `0.889`       |        `0.897`         |             `0.830`             | Approvato con lieve calo |
| **L1**   |      `0.910`       |        `0.681`         |             `0.706`             | Approvato                |

#### 🔗 4. Analisi Temporale (Time-Slide Coincidence)
| Finestra di Coincidenza | Numero Coincidenze a Lag Zero | p-value Empirico | Significatività (Z-score) | Esito                           |
|:------------------------|:-----------------------------:|:----------------:|:-------------------------:|:--------------------------------|
| `±32s`                  |              `0`              |      `1.0`       |           `0.0`           | Casuale (compatibile con fondo) |

#### 🔬 5. Interpretazione Morfologica (Morphcheck in-domain)
I glitch si sono mappati in morfologie attese o popolazioni continue di fondo.


#### 📊 6. Analisi Similarità Sottovarianti (Analyze-Similarity)
| Detector | Cluster ID | Campioni | Interpretazione                 | Top-1 Classe (Similitudine)    |
|:---------|:----------:|:--------:|:--------------------------------|:-------------------------------|

---

## ⚖️ Cross-Run Comparison

| Metrica                  | `20260520_223147` | `20260522_074026` | Confronto     |
|:-------------------------|:------------------|:------------------|:--------------|
| Spettrogrammi (H1 / L1)  | `26623` / `27541` | `21991` / `29953` | Paragonabili  |
| Numero Cluster (H1 / L1) | `11` / `11`       | `11` / `15`       | Coerente      |
| Robustezza (ARI H1 / L1) | `0.859` / `0.967` | `0.889` / `0.910` | Sempre > 0.85 |

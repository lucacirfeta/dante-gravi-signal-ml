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
| `O4a` | `run1`            | `[IN ATTESA — run1 in elaborazione]` | [IN ATTESA — run1 in elaborazione] | [IN ATTESA — run1 in elaborazione]    |
| `O4a` | `20260520_223147` | `[NON DISPONIBILE]`                  | [NON DISPONIBILE]                  | [NON DISPONIBILE]                     |

---

## 📑 Dettaglio Sessioni

### Sessione: `O4a - run1`

[IN ATTESA — run1 in elaborazione]

#### 📊 1. Statistiche Dataset e Preprocessing
| Detector | Spettrogrammi Totali | Duty Cycle (%) | Colormap  | Note / Limitazioni |
|:---------|:--------------------:|:--------------:|:---------:|:-------------------|
| **H1**   |      `[NUMERO]`      |  `[VALORE]%`   | `cividis` | `[Note]`           |
| **L1**   |      `[NUMERO]`      |  `[VALORE]%`   | `cividis` | `[Note]`           |

#### 🤖 2. Risultati del Clustering (DPMM + Cosine)
| Detector | Numero Cluster | Campioni nel Cluster Dominante | Cluster Anomalous (# ID / Dimensioni) | Punti Rumore (Noise) | Varianza PCA (%) |
|:---------|:--------------:|:------------------------------:|:--------------------------------------|:--------------------:|:----------------:|
| **H1**   |   `[NUMERO]`   |           `[NUMERO]`           | `[E.g. C1 (23 pts), C4 (19 pts)]`     |      `[NUMERO]`      |   `[VALORE]%`    |
| **L1**   |   `[NUMERO]`   |           `[NUMERO]`           | `[E.g. C4 (32 pts)]`                  |      `[NUMERO]`      |   `[VALORE]%`    |

#### 🛡️ 3. Validazione Robustezza (Ablation & Stability)
| Detector | Stability Mean ARI (σ) | Ablation Grayscale ARI | Ablation Shuffled-Intensity ARI | Esito Validazione                    |
|:---------|:----------------------:|:----------------------:|:-------------------------------:|:-------------------------------------|
| **H1**   | `[VALORE] (±[VALORE])` |       `[VALORE]`       |           `[VALORE]`            | [Approvato / Bias Colormap Rilevato] |
| **L1**   | `[VALORE] (±[VALORE])` |       `[VALORE]`       |           `[VALORE]`            | [Approvato / Bias Colormap Rilevato] |

#### 🔗 4. Analisi Temporale (Time-Slide Coincidence)
| Finestra di Coincidenza | Numero Coincidenze a Lag Zero | p-value Empirico | Significatività (Z-score) | Esito |
| :--- | :---: | :---: | :---: | :--- |
| `±32s` | `[NUMERO]` | `[VALORE]` | `[VALORE]` | [Casuale / Statisticamente Significativa] |

#### 🔬 5. Interpretazione Morfologica (Morphcheck in-domain)
| Detector | Cluster ID | Classificazione (KNOWN / NOVEL / AMBIGUOUS) | Mappatura Classi Gravity Spy Principali | Interpretazione Scientifica / Note |
| :--- | :---: | :--- | :--- | :--- |
| **H1** | `C1` | `[KNOWN / NOVEL / AMBIGUOUS]` | `[Classe 1, Classe 2]` | `[Note]` |
| **H1** | `C4` | `[KNOWN / NOVEL / AMBIGUOUS]` | `[Classe 1, Classe 2]` | `[Note]` |
| **L1** | `C4` | `[KNOWN / NOVEL / AMBIGUOUS]` | `[Classe 1, Classe 2]` | `[Note]` |

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

| Metrica                 | `run1`                             | `run2 (20260520_223147)` | Confronto   |
|:------------------------|:-----------------------------------|:-------------------------|:------------|
| Spettrogrammi (H1 / L1) | [IN ATTESA — run1 in elaborazione] | `26623` / `27541`        | [IN ATTESA] |
| Numero Cluster          | [IN ATTESA — run1 in elaborazione] | `11` / `11`              | [IN ATTESA] |
| Classi Novel            | [IN ATTESA — run1 in elaborazione] | `0`                      | [IN ATTESA] |
| Robustezza              | [IN ATTESA — run1 in elaborazione] | H1 `0.867`, L1 `0.971`   | [IN ATTESA] |

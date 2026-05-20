# 🔬 Registro Risultati Scientifici e Benchmark (RESULTS.md)

Questo documento raccoglie la cronologia dei run effettuati con la pipeline `gravi-signal-ml`. I dati sono organizzati per **Run osservativo** e **Session ID** per tracciare l'evoluzione delle analisi nel tempo.

---

## 📦 Intervalli di Dati Scaricati (HDF5 Cache)

Di seguito sono registrati gli intervalli temporali GPS scaricati e memorizzati localmente come cache grezza in `data/raw/` per le analisi:

| Identificativo | Intervallo GPS Inizio | Intervallo GPS Fine | Durata Totale (Ore) | Stato / Note |
| :--- | :--- | :--- | :---: | :--- |
| `run1` | `1368993792` | `1370203392` | `336.0` | Scaricato offline |
| `run2` | `1370206208` | `1371415808` | `336.0` | Scaricato offline |

---

## 📅 Indice Cronologico delle Sessioni

| Run | Session ID | Data/Ora Run | Stato Analisi | Rilevazioni Salienti / Anomalie Novel |
| :--- | :--- | :--- | :--- | :--- |
| `O4a` | `TEMPLATE_SESSION_ID_1` | `YYYY-MM-DD HH:MM:SS` | [Completata / In corso / Fallita] | [E.g. H1 Cluster 4 candidato Novel] |
| `O4a` | `TEMPLATE_SESSION_ID_2` | `YYYY-MM-DD HH:MM:SS` | [Completata / In corso / Fallita] | [E.g. No novel detections] |

---

## 📑 Dettaglio Sessioni

### Sessione: `[RUN] - [SESSION_ID]`

#### 📊 1. Statistiche Dataset e Preprocessing
| Detector | Spettrogrammi Totali | Duty Cycle (%) | Colormap | Note / Limitazioni |
| :--- | :---: | :---: | :---: | :--- |
| **H1** | `[NUMERO]` | `[VALORE]%` | `cividis` | `[Note]` |
| **L1** | `[NUMERO]` | `[VALORE]%` | `cividis` | `[Note]` |

#### 🤖 2. Risultati del Clustering (DPMM + Cosine)
| Detector | Numero Cluster | Campioni nel Cluster Dominante | Cluster Anomalous (# ID / Dimensioni) | Punti Rumore (Noise) | Varianza PCA (%) |
| :--- | :---: | :---: | :--- | :---: | :---: |
| **H1** | `[NUMERO]` | `[NUMERO]` | `[E.g. C1 (23 pts), C4 (19 pts)]` | `[NUMERO]` | `[VALORE]%` |
| **L1** | `[NUMERO]` | `[NUMERO]` | `[E.g. C4 (32 pts)]` | `[NUMERO]` | `[VALORE]%` |

#### 🛡️ 3. Validazione Robustezza (Ablation & Stability)
| Detector | Stability Mean ARI (σ) | Ablation Grayscale ARI | Ablation Shuffled-Intensity ARI | Esito Validazione |
| :--- | :---: | :---: | :---: | :--- |
| **H1** | `[VALORE] (±[VALORE])` | `[VALORE]` | `[VALORE]` | [Approvato / Bias Colormap Rilevato] |
| **L1** | `[VALORE] (±[VALORE])` | `[VALORE]` | `[VALORE]` | [Approvato / Bias Colormap Rilevato] |

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

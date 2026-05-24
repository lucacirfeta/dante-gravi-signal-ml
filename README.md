<div align="center">

# 🌊 gravi-signal-ml [![DOI](https://zenodo.org/badge/1231613598.svg)](https://doi.org/10.5281/zenodo.20121859)

**Unsupervised Morphological Characterization of Gravitational-Wave Glitches**

*Unsupervised morphological characterization of LIGO/Virgo O4a glitches using DINOv2 frozen features*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![GWOSC O4a](https://img.shields.io/badge/data-GWOSC%20O4a-orange.svg)](https://gwosc.org/)

</div>

---

## 🎯 What This Project Does

This pipeline performs **unsupervised morphological characterization** of glitch
activity in [O2–O4a gravitational-wave data](https://gwosc.org/) — without
labeled training data and without GPU.

It clusters glitch spectrograms by visual morphology using frozen DINOv2 features,
identifies statistically anomalous clusters, and cross-checks them against
known Gravity Spy classes to assess whether they represent known or potentially
uncharacterized glitch morphologies.

> **Note on Virgo (V1):** Virgo did not participate in O4a due to a commissioning
> issue. It rejoined the network in O4b. This pipeline therefore targets H1
> (Hanford) and L1 (Livingston) only.

---

## 🏗️ Architecture & Core Components

```text
Raw Strain Data (GWOSC O2–O4a)
        │
        ▼
┌─────────────────────┐
│   Data Loader       │  gwpy fetch_open_data() or local 4096s raw HDF5
│   (data_loader.py)  │  Parallel fetch: ThreadPoolExecutor (--workers N)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Preprocessor      │  Chunking 4096s into 32s · Whitening → Bandpass → Q-Transform
│   (preprocessor.py) │  Parallel Q-transform: ProcessPoolExecutor
│   (parallel_        │  Colormap: cividis (perceptually uniform)
│    processor.py)    │
└────────┬────────────┘
         │  256×256 PNG spectrograms
         ▼
┌─────────────────────┐
│   DINOv2-Reg        │  dinov2_vits14_reg (ViT-S/14 + register tokens)
│   Encoder           │  Frozen weights — zero training required
│   (encoder.py)      │  CLS token → 384-dim L2-normalized embeddings
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Clustering        │  PCA(50D) → UMAP(10D, cosine, min_dist=0.0)
│   (clustering.py)   │  → DPMM (default, Dirichlet Process Mixture Model)
│   (reporter.py)     │    or HDBSCAN; UMAP(2D) for visualization
└────────┬────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│   Validation & Cross-Check                          │
│                                                     │
│   similarity_checker.py  — KNN cosine morphcheck    │
│   similarity_analysis.py — Subvariant similarity    │
│   ablation.py            — ARI vs perturbations     │
│   stability.py           — ARI across hyperparams   │
│   timeslide.py           — H1-L1 coincidence p-val  │
│   full_analysis.py       — End-to-end orchestrator  │
│                                                     │
│   indomain_reference_    — In-domain reference from │
│     builder.py             labeled GPS              │
│   reference_builder.py   — Gravity Spy tar.gz index │
│   gravity_spy_checker.py — GPS-based DB query       │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│   Autopilot (scan-live)                             │
│                                                     │
│   threshold_calibrator.py — Per-class threshold     │
│                              calibration from       │
│                              intra-class cosine sim │
│   loglikelihood_calibrator.py — DPMM anomaly        │
│                              threshold calibration  │
│   scan_live.py            — Producer-consumer live  │
│                              scanner (4096s chunks) │
│                              classification via     │
│                              DINOv2 + KNN cosine    │
└─────────────────────────────────────────────────────┘
```

### Critical Design Choices (Context per LLM/Sviluppatori)

- **DINOv2 with Registers (`dinov2_vits14_reg`)**: Usiamo la variante con "register tokens". Senza questi token, i Vision Transformer tendono ad allocare feature globali in patch spaziali arbitrarie (causando artefatti). I register tokens ripuliscono l'embedding, rendendo il clustering geometricamente più coerente.
- **DPMM vs HDBSCAN**: L'algoritmo di default è DPMM (Dirichlet Process Mixture Model) con metrica Cosine. HDBSCAN causava un enorme bias di densità (unendo >80% dei campioni in un mega-cluster) guidato dall'intensità luminosa (colormap). DPMM risolve questo problema catturando forme geometriche su uno spazio UMAP 10D con metrica coseno. Per l'identificazione dei cluster anomali, DPMM calcola la log-likelihood di ogni campione rispetto alla miscela: i cluster in cui >50% dei membri hanno log-likelihood sotto il 5° percentile vengono marcati come anomali. Questo criterio è coerente con l'analisi di stabilità.
- **Due Pass di UMAP**: UMAP 10D + Cosine per il clustering (mantiene la topologia multidimensionale adatta a Gaussian Mixture), seguito da UMAP 2D per la pura visualizzazione scatterplot.
- **Colormap `cividis`**: Sostituisce `viridis` per garantire un'uniformità percettiva e ridurre bias artefatti nel rendering geometrico.
- **Isolamento per Session ID**: Qualsiasi run (scan o analisi) genera un ID univoco basato sul timestamp. Ogni step intermedio (spettrogrammi, embeddings, json) è salvato isolatamente per evitare sovrascritture incrociate.

---

## 📂 Project Structure & Naming Conventions

Tutti gli output generati dalla pipeline seguono rigorosamente questa convenzione di path `data/runs/<run>/<session_id>/...`.
```text
gravi-signal-ml/
├── data/                             # Git-ignored data artifacts
│   ├── raw/                          # .hdf5 strain downloads
│   ├── runs/<run>/<session_id>/      # Isolamento completo delle sessioni (es. O4a/20260510_143022)
│   │   ├── spectrograms/             # Q-transform PNGs (es. h1, l1)
│   │   ├── embeddings/               # DINOv2 .npy arrays + .json metadata
│   │   ├── clusters/                 # Cluster reports, galleries, morphcheck
│   │   ├── reports/                  # Unified full-analysis reports
│   │   ├── ablation/                 # Ablation study results
│   │   ├── stability/                # Robustness analysis (ARI metrics)
│   │   ├── timeslide/                # Time-slide background estimation
│   │   └── logs/                     # Session-specific log files
│   └── reference/                    # Static — reference indexes (es. indomain_index.npz)
├── src/                              # Source code python (moduli core)
├── tests/                            # Pytest suite
├── docs/                             # Documentazione aggiuntiva
├── main.py                           # CLI entry point principale
├── config.yaml                       # Configurazione globale (parametri clustering, UMAP, scan)
├── CLI_REFERENCE.md                  # Manuale completo dei comandi CLI
└── RESULTS.md                        # Documento contenente i risultati scientifici e benchmark
```

---

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/lucacirfeta/dante-gravi-signal-ml.git
cd dante-gravi-signal-ml

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# Enable GWPY caching to avoid re-downloading identical segments
export GWPY_CACHE=1         # Linux/macOS
# set GWPY_CACHE=1          # Windows

# Install dependencies
pip install -r requirements.txt
```

> **Note on GPU:** The pipeline automatically detects and uses the best available
> accelerator (CUDA → MPS → CPU). See [Hardware & Performance](#-hardware--performance)
> below for device compatibility.

---

## 🚀 Usage & Quick Start

Per l'elenco completo di tutti i comandi disponibili, opzioni e subcommand, consultare **[CLI_REFERENCE.md](CLI_REFERENCE.md)**.

### 🧙‍♂️ Wizard Interattivo
Puoi avviare il tool in modalità interattiva semplicemente lanciando il comando base senza parametri:
```bash
python main.py
```
Il wizard rileverà automaticamente tutti i comandi implementati (anche quelli futuri), fornendo aiuti contestuali e suggerimenti intelligenti (Smart Defaults) per la configurazione dei run.

### Esempio di utilizzo End-to-End
1. **Generazione In-Domain Reference:**
   ```bash
   python main.py build-indomain-reference --output data/reference/indomain_index.npz --detector H1 --run O3b
   ```
2. **Scan Automatico + Analisi Completa:**
   Effettua lo scan su H1 e L1 sincronizzati e invoca l'intero loop ML.
   ```bash
   python main.py scan-extended --workers 6 --run O4a --full-analysis True
   ```
   > I risultati verranno salvati in `data/runs/o4a/<SESSION_ID>/reports/`.

### Autopilot & Threshold Calibration
1. **Calibrazione soglie log-likelihood (Clustering):**
   ```bash
   python main.py calibrate-loglikelihood --reference data/reference/indomain_index.npz --percentile 5
   ```
2. **Calibrazione soglie per-classe (Scan Live):**
   ```bash
   python main.py calibrate-threshold --reference data/reference/indomain_index.npz --percentile 5
   ```
3. **Scan live con classificazione KNOWN/NOVEL:**
   ```bash
   python main.py scan-live --detector H1 --run O4a --workers 4
   ```
   > I risultati verranno salvati in `data/autopilot/<SESSION_ID>/`. Se il numero di NOVEL supera `--min-novel`, il comando suggerirà di usare la pipeline standard per il clustering.

Tutti i risultati scientifici, validazioni e benchmark prodotti dalla pipeline sono disponibili in **[RESULTS.md](RESULTS.md)**.

---

## ⚡ Hardware & Performance

The pipeline automatically detects the best available hardware accelerator at startup:

| Device Target | Support Status | Notes |
|:---|:---|:---|
| **CUDA** (RTX 30XX / 40XX) | ✅ Full Native Support | Auto-detected and allocated. |
| **CUDA** (RTX 50XX / Blackwell sm_120) | ⚠️ Requires Nightly Build | Requires cu128 toolkit (see below). |
| **Apple MPS** (Silicon M1/M2/M3/M4) | ✅ Full Native Support | Auto-allocated via Metal Framework. |
| **CPU** (x86_64 / ARM) | ✅ Safe Fallback | Always active when no accelerator is available. |

Batch sizes are auto-tuned per device type (CUDA=64, MPS=32, CPU=16) and configurable in `config.yaml`.

### Configuration for Blackwell GPUs (RTX 5070)

PyTorch stable does not yet include pre-compiled kernels for `sm_120` architecture.
To unlock GPU acceleration on Blackwell hardware:

```bash
pip uninstall torch torchvision -y
pip install --pre torch torchvision --index-url https://download.pytorch.org/whl/nightly/cu128
```

The pipeline will automatically detect Blackwell GPUs and fall back to CPU with a
WARNING log if the nightly build is not installed.

---

## ⚠️ Known Limitations

1. **UMAP distortion:** UMAP distorce le distanze globali per preservare la struttura locale. Cluster anomali separati da UMAP potrebbero riflettere artefatti di preprocessing piuttosto che morfologie fisicamente distinte. L'Ablation study (ARI > 0.999) aiuta a validarne la robustezza.
2. **Domain transfer assumption:** DINOv2 è addestrato su immagini naturali. Il transfer learning su spettrogrammi GW è basato su euristiche e validato sul campo tramite *morphcheck*.
3. **Single Q-transform window:** L'utilizzo fisso dei parametri standard (qrange=[4,64], finestra di 32s) può oscurare strutture transienti ad alta frequenza o broadband lenti.
4. **Divergenza dal Ground Truth:** Il clustering non supervisionato raggiunge un ARI relativamente basso rispetto alle label manuali (Gravity Spy). Questo indica che la similarità morfologica visiva (DINOv2) cattura caratteristiche intrinseche diverse dalle convenzioni classiche umane.
5. **Blackwell GPU (sm_120):** PyTorch stable non include ancora i kernel per sm_120. Usare la build nightly cu128 per accelerazione hardware su RTX 5070. Il fallback su CPU è automatico.
6. **GUI dependency:** Il pacchetto `Gooey` per l'interfaccia `gui.py` è opzionale e va installato manualmente se necessario.

---

## 🧪 Running Tests

```bash
pytest tests/ -v
pytest tests/ -v --run-slow          # Include slow tests
pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## 🤝 Contributing & License
Contributions are welcome. This project is open-source under the **Apache License 2.0**.
See [LICENSE](LICENSE) for details.

Per le citazioni, fare riferimento al file `CITATION.cff` o al README sorgente.

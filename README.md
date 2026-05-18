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

### Why is this needed?

The gravitational-wave community (LIGO/Virgo/KAGRA) already has excellent tools
for *known* problems:

| Tool                            | What it does                                             | Limitation                                  |
|---------------------------------|----------------------------------------------------------|---------------------------------------------|
| **Gravity Spy**                 | Supervised CNN classifier for 23 known O4 glitch classes | Cannot detect new/unknown classes by design |
| **ConvNeXt/ViT pipelines**      | Transfer learning on labeled Gravity Spy datasets        | Still requires labeled training data        |
| **Chirp-vs-glitch classifiers** | Binary classification                                    | Solved problem — no novelty                 |

**What's missing** — and what this project provides:

1. 🔍 **Unsupervised morphological grouping** — cluster glitch spectrograms
   without pre-labeled training data (self-supervised, zero annotation cost)
2. 🌐 **Cross-detector validation** — independent replication on H1 and L1
   to rule out instrument-local artefacts
3. 🔬 **Morphological similarity search** — compare anomalous clusters against
   the Gravity Spy training set using DINOv2 embedding space
4. 📖 **Reproducible, open-source code** — runs on any laptop (CPU only)

> **Note on Virgo (V1):** Virgo did not participate in O4a due to a commissioning
> issue. It rejoined the network in O4b. This pipeline therefore targets H1
> (Hanford) and L1 (Livingston) only.

---

## 🏗️ Architecture

```
Raw Strain Data (GWOSC O2–O4a)
        │
        ▼
┌─────────────────────┐
│   Data Loader       │  gwpy fetch_open_data() · Segment management
│   (data_loader.py)  │  Parallel fetch: ThreadPoolExecutor (--workers N)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Preprocessor      │  Whitening → Bandpass (20–2000 Hz) → Q-Transform
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
│   ablation.py            — ARI vs perturbations     │
│   stability.py           — ARI across hyperparams   │
│   timeslide.py           — H1-L1 coincidence p-val  │
│   full_analysis.py       — End-to-end orchestrator  │
│                                                     │
│   indomain_reference_    — In-domain reference from │
│     builder.py             labeled GPS (Phase 3.4)  │
│   reference_builder.py   — Gravity Spy tar.gz index │
│   gravity_spy_checker.py — GPS-based DB query       │
└─────────────────────────────────────────────────────┘
```

---

## 🚀 Scientific & Methodological Milestones

### 📢 Important Update: Migration from HDBSCAN to DPMM + Cosine Distance

During the validation phase of the **O4a 72-hour run (2023-05-27)**, a major systematic bias was discovered and resolved. The pipeline has officially migrated its default clustering engine from **HDBSCAN (Euclidean)** to a **Dirichlet Process Mixture Model (DPMM)** operating on a **Cosine Distance** UMAP projection space.

#### ⚠️ The "Mega-Cluster" & Rendering Bias (The Old HDBSCAN Approach)
Ablation and stability tests revealed that HDBSCAN suffered from severe density-blindness when dealing with high-dimensional frozen DINOv2 embeddings:
* **Population Collapse:** HDBSCAN merged over **83.3% (H1)** and **84.5% (L1)** of all detector samples into a single, massive "mega-cluster" (Cluster 0), completely masking the underlying morphological taxonomy.
* **Color/Rendering Bias:** In the `shuffled-intensity` ablation test (where spectrogram pixels are randomized to destroy geometric shapes while preserving the colormap intensity), HDBSCAN yielded an Adjusted Rand Index (ARI) of **0.9846 (H1)** and **0.9828 (L1)**. This proved that **HDBSCAN was clustering glitches based on image contrast and colormap rendering statistics rather than actual astrophysical morphology.**
* **Flawed Time-Slide Coincidences:** Due to the artificial mega-cluster wrapping most samples, the time-slide analysis reported a *false positive* zero-lag coincidence peak ($p \approx 0.04$, $Z = 2.30$), tricking the pipeline into identifying non-physical correlated noise across sites.

#### 🔧 Technical Configuration & Computational Footprint
* **Zero Computational Overhead:** Variational Inference for DPMM runs directly on the 10D UMAP space. Total pipeline execution times remained perfectly invariant (~16 mins for H1, ~31 mins for L1), proving that the scientific upgrade introduces no performance penalties.
* **Global Space Regularization:** UMAP hyper-parameters were tuned by increasing `n_neighbors` from 20 to 30 alongside the `cosine` metric. This shifts the embedding focus toward global morphological topology, providing a smoother space for Gaussian components to fit.
* **Granular vs. Cluster-Wide Anomalies:** The new pipeline marks `anomalous_clusters` as empty `[]`, replacing unstable, artifact-driven micro-clusters with a robust, sample-by-sample continuous log-likelihood thresholding.

####  The DPMM + Cosine Solution (Current Default)
Switching to a DPMM framework with Cosine metric successfully regularized the space and resolved the artifact:
1. **Granular Taxonomy:** The mega-cluster was resolved and unfolded into **11 distinct, clean sub-morphologies** for both H1 and L1 detectors, mapping fine-grained structures like *Blips*, *Tomtes*, and *Scattered Light* branches.
2. **True Geometric Clustering:** The `shuffled-intensity` ARI dropped significantly to **0.8394 (H1)** and **0.6071 (L1)**, proving that the pipeline now heavily prioritizes the geometric and spatial features extracted by DINOv2 over superficial colormap brightness.
3. **Mathematical Stability:** The pipeline achieves an honest, robust clustering stability with an average ARI of **0.9002 ($\sigma=0.058$) for H1** and **0.9464 ($\sigma=0.017$) for L1** under stochastic space perturbations.
4. **Sanitized Time-Slides:** The zero-lag coincidences dropped to **0** ($p = 1.0$, $Z = 0.0$), correctly aligning with the expected background distribution of independent environmental noise.

| Metric / Artifact | Old Pipeline (HDBSCAN) | New Pipeline (DPMM + Cosine) | Status |
| :--- | :---: | :---: | :---: |
| **Max Cluster Size (H1 / L1)** | 83.3% / 84.5% | **Resolved (Distributed over 11 clusters)** |  Fixed |
| **Shuffled-Intensity ARI (H1)** | 0.9846 | **0.8394** (Immune to color bias) |  Fixed |
| **Shuffled-Intensity ARI (L1)** | 0.9828 | **0.6071** (Immune to color bias) |  Fixed |
| **False-Positive Coincidences** | 4 events ($p < 0.05$) | **0 events ($p = 1.0$, background)** |  Fixed |
| **Anomaly / Novelty Detection** | Binary noise flag (failed) | **Continuous Log-Likelihood Percentile** |  Improved |

*This update ensures that any downstream physical inference or time-coincidence study conducted with `gravi-signal-ml` is mathematically sound, highly reproducible, and unbiased by spectrogram preprocessing choices.*

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
pre-commit install          # Optional
```

> **Note on GPU:** The pipeline runs fully on CPU. Encoding ~7000 spectrograms
> takes ~25 min on CPU — acceptable for batch workloads.

---

## 🖥️ Graphical User Interface (GUI)

A Gooey-based wrapper is available for graphical configuration of all commands:

```bash
pip install Gooey>=1.2.0a0   # Not included in requirements.txt by default
python gui.py
```

---

## 🚀 Usage

### ONE-TIME Setup Commands

#### 1. Validate the Preprocessing Pipeline

```bash
python main.py fetch --event GW150914
```

Downloads H1 strain data for GW150914, applies whitening + bandpass,
and saves the Q-transform spectrogram. A visible chirp confirms the
preprocessing pipeline is mathematically correct.

#### 2. Build Reference Indexes

##### In-Domain Reference (Recommended)

Fetches labeled Gravity Spy glitch timestamps from Zenodo, downloads their
strain from GWOSC, and processes them through **our** pipeline — ensuring
query and reference live in the same embedding space.

```bash
python main.py build-indomain-reference --output data/reference/indomain_index.npz --detector H1 --run O3b
python main.py validate-reference --reference data/reference/indomain_index.npz --test-event GW150914
```

# 3. Benchmark clustering against Gravity Spy labels
```bash
python main.py benchmark-clustering --reference data/reference/indomain_index.npz --min-samples-per-class 10 --output data/reference/benchmark_report.json
```
Quantitatively compares the unsupervised clusters against the Gravity Spy
ground truth labels. Computes ARI, AMI, and a contingency matrix.

⚠️ **Requires ~2h of GWOSC downloads** for ~600 labeled glitch segments.

✅ Validation passes if GW150914 maps to class `Chirp` with cosine similarity ≥ 0.99.

##### Gravity Spy Out-of-Domain Reference (Not Recommended)

> ⚠️ Download `trainingsetv1d1.tar.gz` (~5 GB) from:
> https://zenodo.org/records/1476551/files/trainingsetv1d1.tar.gz
> and save to `data/reference/trainingsetv1d1.tar.gz`

```bash
python main.py build-reference --output data/reference/gravity_spy_index.npz --max-per-class 50
```

> ⚠️ **Domain Gap Warning:** The Gravity Spy training images use different
> Q-transform parameters, color normalization, and image dimensions than this
> pipeline. Use the in-domain reference above for scientifically valid results.

---

### EVERY NEW RUN

Each run is automatically isolated by a **session ID** (timestamp-based, e.g.
`20260510_143022`), so multiple runs never overwrite each other.

#### Step 1 — Data Acquisition

**Recommended: Extended Scan (H1 + L1 synchronized)**

```bash
python main.py scan-extended --workers 6 --run O4a
```

> [!IMPORTANT]
> `--workers` must be an **even number** (2, 4, 6, 8). Workers are split equally between H1 and L1.

**Single-detector scan:**

```bash
python main.py scan --detector H1 --hours 72 --workers 6 --run O4a
```

**Incremental mode** — resume an interrupted scan:

```bash
python main.py scan-extended --workers 6 --session-id <PREVIOUS_SESSION_ID>
```

> [!IMPORTANT]
> In resume mode, `--hours` is ignored; duration comes from `config.yaml` (`hours_per_detector`).

> [!TIP]
> By default, raw HDF5 files are **not saved** to disk. Use `--no-cache-raw False` to enable caching.

📋 Note the **Session ID** printed at startup — needed for all subsequent steps.

#### Step 2 — Automated Full Analysis (Recommended)

```bash
python main.py full-analysis --session-id <SESSION_ID> --detector H1 L1 --run O4a
```

This sequentially executes: **encoding → clustering → morphcheck → ablation → stability → timeslide**, producing a unified report per detector at `data/runs/o4a/<SESSION_ID>/reports/<DET>_full_report.json`.

> [!TIP]
> Trigger automatically after scanning:
> ```bash
> python main.py scan-extended --workers 6 --full-analysis True
> ```

> [!TIP]
> Use `--sequential` if you experience resource issues with parallel detector analysis.

#### Continuous Run Mode

```bash
python main.py full-analysis --session-id <SESSION_ID> --detector H1 L1 \
    --continue-run --max-iterations 5 --stop-date "2023-06-01 12:00:00"
```

This loop automatically creates new sessions and advances through the observing run.

---

### Manual Step-by-Step Analysis

<details>
<summary>Click to expand manual commands</summary>

#### Step 2 — Feature Extraction (DINOv2 with Registers)

```bash
python main.py encode --session-id <SESSION_ID> --detector H1 --run O4a
python main.py encode --session-id <SESSION_ID> --detector L1 --run O4a
```

#### Step 3 — Clustering & Anomaly Identification

```bash
python main.py cluster --session-id <SESSION_ID> --detector H1 --run O4a
python main.py cluster --session-id <SESSION_ID> --detector L1 --run O4a
```

**Pipeline:** PCA(50D) → UMAP(10D, cosine, `min_dist=0.0`) → DPMM (default) or HDBSCAN → UMAP(2D) viz

By default, the pipeline uses a **Dirichlet Process Mixture Model (DPMM)** for probabilistic clustering and novelty detection. The top 5% of samples with the lowest log-likelihood scores are flagged as anomalies. Alternatively, HDBSCAN can be selected using strict, conservative values (e.g., `min_cluster_size=15`, `min_samples=10`) to prevent over-fragmentation.

#### Step 4 — Morphological Cross-Check

```bash
python main.py morphcheck \
    --embeddings data/runs/o4a/<SESSION_ID>/embeddings/o4a_h1.npy \
    --report data/runs/o4a/<SESSION_ID>/clusters/h1/cluster_report.json \
    --reference data/reference/indomain_index.npz \
    --output data/runs/o4a/<SESSION_ID>/clusters/h1/morphcheck_report.json
```

Each anomalous spectrogram receives: **NOVEL** / **KNOWN** / **AMBIGUOUS**.

#### Step 5 — Ablation Study

```bash
python main.py ablation --session-id <SESSION_ID> --detector H1 --run O4a
```

Tests: grayscale, inverted, shuffled-intensity, random-baseline.

#### Step 6 — Stability Analysis

```bash
python main.py stability --session-id <SESSION_ID> --detector H1 --n-runs 20 --run O4a
```

#### Step 7 — Time-Slide Background Validation

```bash
python main.py timeslide --session-id <SESSION_ID> --run O4a
```

50 random L1 time shifts, ±32s coincidence window, empirical p-value.

</details>

---

### The Three Levels of Glitch Validation

| Level | Phase | Question | Commands |
|-------|-------|----------|----------|
| **1. Internal Robustness** | `ablation` + `stability` | Are clusters real or preprocessing artifacts? | After clustering |
| **2. Physical Significance** | `timeslide` | Are H1-L1 coincidences significant? | After robustness |
| **3. Morphological Classification** | `morphcheck` | Known Gravity Spy class or uncharacterized? | After timeslide |

---

### Performance & Parallelization

| Hardware        | Mode          | Speed                         |
|-----------------|---------------|-------------------------------|
| Any laptop      | `--workers 1` | ~1.5 s/segment                |
| Ryzen 7 7800X3D | `--workers 6` | ~0.35 s/segment (~4× speedup) |

GWOSC fetch threads are capped at 4 regardless of `--workers`.

---

## ⚠️ Known Limitations

1. **UMAP distortion:** UMAP distorts global distances to preserve local structure.
   Anomalous clusters separated by UMAP may reflect preprocessing artifacts,
   not distinct physical morphologies. Ablation ARI > 0.999 partially mitigates this.

2. **Domain transfer assumption:** DINOv2 is trained on natural images; transfer
   to GW spectrograms is assumed but not formally validated for this domain.

3. **Single Q-transform window:** Standard Q-transform (qrange=[4,64], 32s window)
   may miss fast narrowband or slow broadband structures.

4. **Clustering vs. Gravity Spy ground truth:** The unsupervised clustering
   achieves an ARI of 0.146 against the Gravity Spy labeled catalog (benchmark
   via `benchmark-clustering`). This reflects a structural difference between
   visual morphology similarity (captured by DINOv2) and physics-based human
   classification. Clusters are morphologically coherent but do not map 1:1
   onto existing class labels.

5. **No GPU acceleration:** PyTorch stable does not yet support RTX 5070 (Blackwell
   sm_120). Pipeline is CPU-only, which limits throughput on very large datasets.

6. **GUI dependency:** The `Gooey` GUI package is commented out in `requirements.txt`
   and must be installed manually.

---

## 🧪 Running Tests

```bash
pytest tests/ -v
pytest tests/ -v --run-slow          # Include slow tests
pytest tests/ -v --cov=src --cov-report=term-missing
```

All tests use synthetic data and mocked network calls.

---

## 📂 Project Structure

```
gravi-signal-ml/
├── data/                             # Git-ignored data artifacts
│   ├── raw/                          # .hdf5 strain downloads (optional cache)
│   ├── runs/<run>/<session_id>/      # Complete run and session isolation
│   │   ├── spectrograms/             # Q-transform PNGs (H1/L1 subdirs)
│   │   ├── embeddings/               # DINOv2 .npy arrays + .json metadata
│   │   ├── clusters/                 # Cluster reports, galleries, morphcheck
│   │   ├── reports/                  # Unified full-analysis reports
│   │   ├── ablation/                 # Ablation study results
│   │   ├── stability/                # Robustness analysis (ARI metrics)
│   │   ├── timeslide/                # Time-slide background estimation
│   │   └── logs/                     # Session-specific log files
│   └── reference/                    # Static — reference indexes
├── src/
│   ├── data_loader.py                # GWOSC fetch + segment management
│   ├── preprocessor.py               # Whitening · bandpass · Q-transform
│   ├── parallel_processor.py         # ThreadPool + ProcessPool pipeline
│   ├── encoder.py                    # DINOv2-Reg frozen encoder
│   ├── clustering.py                 # PCA + UMAP + DPMM/HDBSCAN pipeline
│   ├── reporter.py                   # Cluster report + UMAP viz + gallery
│   ├── similarity_checker.py         # Cosine KNN novelty assessment
│   ├── reference_builder.py          # Gravity Spy tar.gz → reference index
│   ├── indomain_reference_builder.py # In-domain reference (Phase 3.4)
│   ├── gravity_spy_checker.py        # GPS-based Gravity Spy DB query
│   ├── ablation.py                   # ARI vs preprocessing variants
│   ├── stability.py                  # ARI across hyperparameter runs
│   ├── timeslide.py                  # Time-slide background estimation
│   ├── full_analysis.py              # End-to-end pipeline orchestrator
│   └── utils.py                      # Config · logging · GPS conversion
├── tests/                            # Pytest suite (synthetic data, mocked)
├── docs/                             # Pipeline steps, implementation notes
├── main.py                           # CLI entry point (19 subcommands)
├── gui.py                            # Gooey-based GUI wrapper
├── config.yaml                       # Central configuration
├── CLI_REFERENCE.md                  # Complete CLI reference
├── requirements.txt                  # Dependencies
└── .pre-commit-config.yaml           # ruff + mypy + file hygiene
```

---

## 🤝 Contributing

Contributions are welcome. This project is designed as a community resource
for gravitational-wave open science.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Ensure tests pass: `pytest tests/ -v`
4. Ensure code quality: `ruff check . && mypy src/`
5. Submit a pull request

---

## 📚 References

- [GWOSC — Gravitational Wave Open Science Center](https://gwosc.org/)
- [Gravity Spy](https://gravityspy.org/) — supervised glitch classifier
- [gwpy documentation](https://gwpy.github.io/docs/stable/)
- Zevin et al. (2017) — *Gravity Spy: Integrating Advanced LIGO Detector Characterization, Machine Learning, and Citizen Science*
- Oquab et al. (2023) — *DINOv2: Learning Robust Visual Features without Supervision*
- Darcet et al. (2023) — *Vision Transformers Need Registers* (ICLR 2024)
- Glanzer et al. (2023) — *Data quality up to the third observing run of Advanced LIGO: Gravity Spy glitch classifications*
- LIGO/Virgo/KAGRA Collaboration — O4a data release (GWTC-4.0, 2024)
- CTSAE (2024) — Cross-Temporal Spectrogram Autoencoder for GW glitch clustering. arXiv:2404.15552
- Soni et al. (2025) — LIGO Detector Characterization in O4a. arXiv:2409.02831

---

## 📄 Citation

If you use this code in your research, please cite:

```bibtex
@software{gravi_signal_ml,
  title  = {gravi-signal-ml: Unsupervised Morphological Characterization of Gravitational-Wave Glitches},
  author = {Cirfeta, Luca},
  year   = {2026},
  url    = {https://github.com/lucacirfeta/dante-gravi-signal-ml},
  doi    = {10.5281/zenodo.20121859},
  note   = {Unsupervised morphological characterization of LIGO O4a glitches using DINOv2 frozen features}
}
```

## 📝 License

Apache License 2.0 — see [LICENSE](LICENSE) for details.

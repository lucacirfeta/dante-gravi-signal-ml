<div align="center">

# 🌊 gravi-signal-ml [![DOI](https://zenodo.org/badge/1231613598.svg)](https://doi.org/10.5281/zenodo.20121859)

**Unsupervised Morphological Characterization of Gravitational-Wave Glitches**

*Unsupervised morphological characterization of LIGO/Virgo O4a glitches using DINOv2 frozen features*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![GWOSC O4a](https://img.shields.io/badge/data-GWOSC%20O4a-orange.svg)](https://gwosc.org/)
[![arXiv](https://img.shields.io/badge/arXiv-2605.28572-B31B1B.svg)](https://arxiv.org/abs/2605.28572)

</div>

---

## 📢 News

**26 May 2026** – The LIGO-Virgo-KAGRA Collaboration released the **GWTC-5.0 catalog** 
([press release](https://www.ligo.org/news/)), reporting 161 new gravitational-wave events 
and bringing the total number of detections to 390. Our pipeline `gravi-signal-ml` provides 
a ready‑to‑use, open‑source tool for glitch characterization in O4a data, complementing 
these new observations.

**28 May 2026** – Our preprint is now available on arXiv: **[2605.28572](https://arxiv.org/abs/2605.28572)**.

---

## 🎯 What This Project Does

This pipeline performs **unsupervised morphological characterization** of glitch
activity in [O2–O4a gravitational-wave data](https://gwosc.org/) — without
labeled training data and with native hardware acceleration (CUDA/MPS) for
lightning-fast inference.

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

### Critical Design Choices (Context for LLMs/Developers)

- **DINOv2 with Registers (`dinov2_vits14_reg`)**: We use the variant with "register tokens". Without these tokens, Vision Transformers tend to allocate global features in arbitrary spatial patches (causing artifacts). Register tokens clean up the embedding, making the clustering geometrically more coherent.
- **DPMM vs HDBSCAN**: The default algorithm is DPMM (Dirichlet Process Mixture Model) with Cosine metric. HDBSCAN caused a huge density bias (merging >80% of samples in a mega-cluster) driven by luminous intensity (colormap). DPMM solves this issue by capturing geometric shapes on a 10D UMAP space with cosine metric. For anomalous cluster identification, DPMM computes the log-likelihood of each sample relative to the mixture: clusters where >50% of the members have log-likelihood under the 5th percentile are marked as anomalous. This criterion is consistent with the stability analysis.
- **Two UMAP Passes**: UMAP 10D + Cosine for clustering (maintains multidimensional topology suitable for Gaussian Mixture), followed by UMAP 2D purely for scatterplot visualization.
- **Colormap `cividis`**: Replaces `viridis` to guarantee perceptual uniformity and reduce artifact bias in geometric rendering.
- **Hardware Acceleration & Pipelined Execution**: Full native support for NVIDIA CUDA (with cuDNN auto-tuner enabled for `inference_mode`) and Apple MPS. Leverages an advanced *Micro-Locking* approach at the batch level: image reading and decoding happens asynchronously via multi-threading on the CPU, while the GPU executes pure mathematical inference with millisecond locks and instantaneous VRAM flushing.
- **Session ID Isolation**: Any run (scan or analysis) generates a unique ID based on the timestamp. Each intermediate step (spectrograms, embeddings, json) is saved in isolation to prevent cross-overwrites.

---

## 📂 Project Structure & Naming Conventions

All pipeline-generated outputs strictly follow this path convention: `data/runs/<run>/<session_id>/...`.
```text
gravi-signal-ml/
├── data/                             # Git-ignored data artifacts
│   ├── raw/                          # .hdf5 strain downloads
│   ├── runs/<run>/<session_id>/      # Complete session isolation (e.g. O4a/20260510_143022)
│   │   ├── spectrograms/             # Q-transform PNGs (e.g. h1, l1)
│   │   ├── embeddings/               # DINOv2 .npy arrays + .json metadata
│   │   ├── clusters/                 # Cluster reports, galleries, morphcheck
│   │   ├── reports/                  # Unified full-analysis reports
│   │   ├── ablation/                 # Ablation study results
│   │   ├── stability/                # Robustness analysis (ARI metrics)
│   │   ├── timeslide/                # Time-slide background estimation
│   │   └── logs/                     # Session-specific log files
│   └── reference/                    # Static — reference indexes (e.g. indomain_index.npz)
├── src/                              # Python source code (core modules)
├── tests/                            # Pytest suite
├── docs/                             # Additional documentation
├── main.py                           # Main CLI entry point
├── config.yaml                       # Global configuration (clustering, UMAP, scan params)
├── CLI_REFERENCE.md                  # Complete CLI commands manual
└── RESULTS.md                        # Document containing scientific results and benchmarks
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

For the complete list of all available commands, options, and subcommands, consult **[CLI_REFERENCE.md](CLI_REFERENCE.md)**.

### 🧙‍♂️ Interactive Wizard
You can start the tool in interactive mode simply by running the base command without parameters:
```bash
python main.py
```
The wizard will automatically detect all implemented commands (including future ones), providing contextual help and smart suggestions (Smart Defaults) for run configuration.

### End-to-End Usage Example
1. **In-Domain Reference Generation:**
   ```bash
   python main.py build-indomain-reference --output data/reference/indomain_index.npz --detector H1 --run O3b
   ```
2. **Automatic Scan + Full Analysis:**
   Performs the scan on synchronized H1 and L1 and invokes the entire ML loop.
   ```bash
   python main.py scan-extended --workers 6 --run O4a --full-analysis True
   ```
   > The results will be saved in `data/runs/o4a/<SESSION_ID>/reports/`.

### Autopilot & Threshold Calibration
1. **Log-likelihood Threshold Calibration (Clustering):**
   ```bash
   python main.py calibrate-loglikelihood --reference data/reference/indomain_index.npz --percentile 5
   ```
2. **Per-class Threshold Calibration (Scan Live):**
   ```bash
   python main.py calibrate-threshold --reference data/reference/indomain_index.npz --percentile 5
   ```
3. **Live Scan with KNOWN/NOVEL Classification:**
   ```bash
   python main.py scan-live --detector H1 --run O4a --workers 4
   ```
   > The results will be saved in `data/autopilot/<SESSION_ID>/`. If the NOVEL count exceeds `--min-novel`, the command will suggest using the standard pipeline for clustering.

All scientific results, validations, and benchmarks produced by the pipeline are available in **[RESULTS.md](RESULTS.md)**.

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

1. **UMAP distortion:** UMAP distorts global distances to preserve local structure. Anomalous clusters separated by UMAP might reflect preprocessing artifacts rather than physically distinct morphologies. The Ablation study (ARI > 0.999) helps validate its robustness.
2. **Domain transfer assumption:** DINOv2 is trained on natural images. Transfer learning on GW spectrograms is based on heuristics and field-validated through *morphcheck*.
3. **Single Q-transform window:** The fixed use of standard parameters (qrange=[4,64], 32s window) may obscure high-frequency transient structures or slow broadbands.
4. **Ground Truth Divergence:** Unsupervised clustering achieves a relatively low ARI compared to manual labels (Gravity Spy). This indicates that visual morphological similarity (DINOv2) captures intrinsic features different from classical human conventions.
5. **Blackwell GPU (sm_120):** Stable PyTorch does not yet include kernels for sm_120. Use the cu128 nightly build for hardware acceleration on RTX 5070. The CPU fallback is automatic.
6. **GUI dependency:** The `Gooey` package for the `gui.py` interface is optional and must be installed manually if required.

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

## 📝 Citation

If you use this software in your research, please cite our preprint:

```bibtex
@software{gravi_signal_ml_arxiv,
  title  = {Unsupervised Morphological Characterization of Gravitational-Wave Glitches in LIGO O4a Using Frozen DINOv2 Features},
  author = {Cirfeta, Luca},
  year   = {2026},
  eprint = {2605.28572},
  archivePrefix = {arXiv},
  primaryClass = {astro-ph.IM},
  doi    = {10.48550/arXiv.2605.28572},
  url    = {https://arxiv.org/abs/2605.28572}
}
```

For more details, please refer to the `CITATION.cff` file.

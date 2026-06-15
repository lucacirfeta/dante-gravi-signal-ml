<div align="center">

# 🌊 gravi-signal-ml [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20543811.svg)](https://doi.org/10.5281/zenodo.20543811)

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

**15 June 2026** – We completed the full environmental vetting and strain sanity check for our O4a anomalies. The pipeline successfully isolated a genuine physical "Dark Glitch" (Family_01) with perfectly clean, non-clipped strain ($1.6\times 10^{-17}$) operating in a data segment lacking active GWOSC DQ science flags. Concurrently, it isolated macro data dropouts (Singleton) composed entirely of `NaNs`. The extreme 79:3 (L1:H1) candidate asymmetry firmly establishes a local instrumental origin at Livingston, demonstrating the power of zero-shot learning to map uncatalogued noise manifolds.

**14 June 2026** – We formally validated the **Domain Shift Invariance** of our VQ Index between O3b and O4a via a large-scale Kolmogorov-Smirnov test. Furthermore, applying our pipeline on 140 hours of O4a data yielded 82 unilateral glitch candidates with a severe 16:1 L1/H1 asymmetry. Rigorous statistical null testing demonstrated that these anomalous morphological families are indistinguishable from the background ($p > 0.05$), proving that applying an O3b-calibrated reference index to O4a produces diffuse noise clustering. This finding robustly characterizes the domain shift between the observing runs and highlights the necessity of a native O4a index.

**07 June 2026** – We drafted the third paper of our series on the topological extraction of GW glitches: *"Patch-Level DINOv2 Scoring for Gravitational-Wave Glitch Detection: Breaking the Signal Dilution Barrier via Vector-Quantized Local Feature Indexing"*.

**05 June 2026** – Our new Mock Data Challenge (MDC) paper is available on arXiv: **[2606.06237](https://arxiv.org/abs/2606.06237)**. It formally details the sensitivity limits of the pipeline and the Signal Dilution effect.

**26 May 2026** – The LIGO-Virgo-KAGRA Collaboration released the **GWTC-5.0 catalog** 
([press release](https://www.ligo.org/news/)), reporting 161 new gravitational-wave events 
and bringing the total number of detections to 390. Our pipeline `gravi-signal-ml` provides 
a ready‑to‑use, open‑source tool for glitch characterization in O4a data, complementing 
these new observations.

**28 May 2026** – Our pipeline method preprint is available on arXiv: **[2605.28572](https://arxiv.org/abs/2605.28572)**.

---

## 🎯 What This Project Does

This pipeline performs **unsupervised morphological characterization** of glitch
activity in [O2–O4a gravitational-wave data](https://gwosc.org/) — without
labeled training data and with native hardware acceleration (CUDA/MPS) for
lightning-fast inference.

It clusters glitch spectrograms by visual morphology within a latent space using frozen DINOv2 features.
It identifies anomaly clusters through zero-shot novelty detection via **Patch-Level Multiple Instance Learning (MIL)** and **Adaptive GEV Thresholding** ($p_{99}$), and cross-checks them against an in-domain Gravity Spy O3b reference index. Robustness validation is ensured through stability and ablation testing, and temporal background is estimated via time-slide coincidence analysis.

> **Note on Virgo (V1):** Virgo did not participate in O4a due to a commissioning
> issue. It rejoined the network in O4b. This pipeline therefore targets H1
> (Hanford) and L1 (Livingston) only.

---

## 🏗️ Architecture & Core Components

The codebase is organized into **three single-responsibility packages** under `src/`:

```text
 Raw Strain Data (GWOSC O2–O4a)
         │
         ▼
 ┌───────────────────────────────────────────────────────────────┐
 │  src/core/  —  Shared Primitives (Hardware-Agnostic)          │
 │                                                               │
 │  data_loader.py         gwpy / local HDF5 fetch              │
 │  preprocessor.py        Whiten → Bandpass → Q-Transform      │
 │  parallel_processor.py  ProcessPoolExecutor Q-transform       │
 │  encoder.py             DINOv2-Reg ViT-S/14 (frozen)         │
 │  patch_producer.py      Spectrogram → 256×256 RGB batches    │
 │  patch_scorer.py        Top-K MIL scoring + GEV thresholding │
 │  utils.py               Config, logging, device selection     │
 │  logging_utils.py       Structured JSON logging              │
 │  wizard.py              Interactive CLI wizard               │
 └───────────────────────┬───────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
 ┌────────────────────────┐    ┌────────────────────────────────┐
 │  pipeline_v2_production│    │  pipeline_v1_legacy (FROZEN)   │
 │  384D Patch-Level MIL  │    │  768D CLS-Token Exploratory    │
 │                        │    │                                │
 │  production_cluster.py │    │  clustering.py    reporter.py  │
 │  production_report.py  │    │  stability.py     ablation.py  │
 │  aggregate_report.py   │    │  timeslide.py     injection.py │
 │  production_writer.py  │    │  full_analysis.py scan_live.py │
 │  saliency_map.py       │    │  similarity_checker.py  ...    │
 └────────────────────────┘    └────────────────────────────────┘
```

### Critical Design Choices (Context for LLMs/Developers)

- **DINOv2 with Registers (`dinov2_vits14_reg`)**: We use the variant with "register tokens". Without these tokens, Vision Transformers tend to allocate global features in arbitrary spatial patches (causing artifacts). Register tokens clean up the embedding, making the clustering geometrically more coherent.
- **DPMM vs HDBSCAN**: The default algorithm is DPMM (Dirichlet Process Mixture Model) with Cosine metric. HDBSCAN caused a huge density bias (merging >80% of samples in a mega-cluster) driven by luminous intensity (colormap). DPMM solves this issue by capturing geometric shapes on a 10D UMAP space with cosine metric. For anomalous cluster identification, DPMM computes the log-likelihood of each sample relative to the mixture: clusters where >50% of the members have log-likelihood under the 5th percentile are marked as anomalous. This criterion is consistent with the stability analysis.
- **Two UMAP Passes**: UMAP 10D + Cosine for clustering (maintains multidimensional topology suitable for Gaussian Mixture), followed by UMAP 2D purely for scatterplot visualization.
- **Colormap `cividis`**: Replaces `viridis` to guarantee perceptual uniformity and reduce artifact bias in geometric rendering.
- **Hardware Acceleration & Pipelined Execution**: Full native support for NVIDIA CUDA (with cuDNN auto-tuner enabled for `inference_mode`) and Apple MPS. Leverages an advanced *Micro-Locking* approach at the batch level: image reading and decoding happens asynchronously via multi-threading on the CPU, while the GPU executes pure mathematical inference with millisecond locks and instantaneous VRAM flushing.
- **Session ID Isolation**: Any run (scan or analysis) generates a unique ID based on the timestamp. Each intermediate step (spectrograms, embeddings, json) is saved in isolation to prevent cross-overwrites.

---

## 🔬 Scientific Scope

This pipeline evaluates the **morphology** of instrumental noise transients in the latent space constructed by frozen DINOv2 embeddings. It is specifically designed for unsupervised anomaly clustering and novelty detection.

**Within the DINOv2 latent representation and strict Data Quality gating framework (`L1_CBC_CAT1`) used in this study, 82 morphologically unclassified unilateral segments were discovered in the analyzed pristine O4a data.** A rigorous topological characterization revealed a severe detection asymmetry between L1 and H1 (16:1). While the taxonomy pipeline successfully clustered these candidates into families using cross-session transitivity, statistical hypothesis testing against the empirical O3b background showed these aggregates fail the null test ($p > 0.05$). This validates the pipeline's robustness as a diagnostic tool: rather than falsely reporting noise fluctuations as new astrophysical discoveries, it successfully maps the severe domain shift that occurred between O3b and O4a due to instrumental upgrades.

The pipeline establishes a reproducible baseline for zero-shot glitch morphology characterization. The topological stability of the extracted morphological families was formally proven via UMAP-4D Bootstrapped DPMM clustering (N=20, ARI=0.68).

## ⚠️ Limitations

1. **Dependence on DINOv2 Embeddings:** DINOv2 is a foundation model trained on natural images. While empirical tests show effective transfer learning to spectrograms, its feature extraction heuristics are not physically motivated by gravitational-wave mechanics.
2. **UMAP Geometry Distortions:** UMAP distorts global distances to preserve local structure. Anomalous clusters separated by UMAP might reflect preprocessing artifacts rather than physically distinct morphologies.
3. **Absence of Auxiliary Channel Validation:** This tool operates entirely on primary strain data (H1/L1). It does not cross-reference environmental or instrumental auxiliary channels to confirm the physical origin of the anomalies.
4. **Physically Distinct but Visually Similar Glitches:** The pipeline has an inability to exclude physically distinct glitch classes if they produce visually similar spectrogram morphologies. Ground-truth physical novelty may exist undetected within existing clusters.
5. **Out-Of-Distribution (OOD) Blindness / Signal Dilution:** Mock Data Challenge (MDC) tests on both short-duration broadband (`SpiralBurst`, `StepLadder`) and long-duration narrowband (`HarmonicComb`, `NarrowChirp`) morphologies revealed that the original pipeline completely fails to recognize them as `NOVEL`, even at extreme SNRs up to $\approx 430$ (Max Recall = 0.00). As formally demonstrated in **[Cirfeta (2026b), arXiv:2606.06237](https://arxiv.org/abs/2606.06237)**, this is caused by the *Signal Dilution Effect* induced by the global average pooling of DINOv2's `[CLS]` token over 32s windows. While the architecture was upgraded to a **Patch-Level MIL (Multiple Instance Learning)** framework to mathematically separate the distributions (achieving $KS \sim 0.90$), the extremely heavy-tailed background of LIGO O4a requires a strict empirical 99th-percentile threshold to guarantee a 1% FPR. This threshold acts as a guillotine, collapsing the effective Boolean recall to just **16.6%** even for very loud signals ($SNR \sim 138$). Thus, the O4a "Null Result" reflects the extreme statistical nature of the background noise tails rather than the definitive absence of physical anomalies.
6. **Saliency Map Discrimination:** Due to the severely non-isotropic geometry of the DINOv2 hypersphere on spectrograms, Fréchet-tail stochastic noise can produce extreme local cosine similarities matching or exceeding those of loud astrophysical bursts. Consequently, a single-patch cosine similarity threshold cannot be employed as a binary detector (e.g., $s_i > \tau$). This is precisely why Pipeline V2 implements a **Top-$k$ Multiple Instance Learning (MIL)** aggregation paired with an adaptive GEV recalibration, integrating the anomaly score over a morphological footprint rather than a single peak. The GEV shape parameter extraction ($\hat{\xi} \approx -0.065$) ensures threshold decisions rest on strict bounds rather than unbounded heavy-tail heuristics.

---

## 🖼️ Visual Diagnostic Layer: Saliency Gallery

The pipeline includes a three-panel visual diagnostic engine (`saliency_gallery/`) designed to make the neural architecture fully inspectable and interpretable. Each PNG file generated for the anomalies provides the following structural analysis of the transient:

1. **Panel 1 (Original Q-Transform):** Represents the raw 256x256 tensor of the Q-Transform spectrogram. It is used to visually isolate energy bursts in the time-frequency space prior to any neural extraction.
2. **Panel 2 (Patch Saliency):** Displays the native 37x37 attention grid of the DINOv2 patches. The hollow red rectangles highlight the Top-68 local anomalous patches, algorithmically selected via Multiple Instance Learning (MIL) to construct the final 384-dimensional latent vector.
3. **Panel 3 (Anomaly Saliency Overlay):** Utilizes a bilinear up-sampling (from 37x37 to 256x256 pixels) via standard graphics libraries to perfectly register the anomaly score heatmap onto the base physical coordinates of the original spectrogram.

**Physical Interpretation vs. Domain-Shift Hallucinations:**
The Saliency Gallery is the fundamental tool to distinguish real transients from model artifacts in an unsupervised detection task.
- A **true physical alignment** (glitch) manifests as a localized, high-contrast overlay, where the red rectangles (the extracted MIL patches) accurately trace the actual morphology of a signal against the background.
- A **domain-shift hallucination** instead presents as a regular, diffuse "chessboard" pattern, dictated by the rigid 14x14 pixel grid of the Vision Transformer. This visual anomaly occurs in the absence of real signal contrast and is driven almost entirely by the bias of the ViT's *positional embeddings*, forcing the model to search in vain for features within a purely stochastic and isotropic background noise.

---

## 📂 Project Structure & Naming Conventions

All pipeline-generated outputs strictly follow this path convention: `data/runs/<run>/<session_id>/...`.
```text
gravi-signal-ml/
├── data/                                    # Git-ignored data artifacts
│   ├── raw/                                 # .hdf5 strain downloads from GWOSC
│   ├── production/                          # Validated V2 session outputs and JSON/CSV reports
│   │   └── <session_id>/
│   │       ├── novelties.h5                 # SWMR HDF5 archive (384D MIL vectors)
│   │       └── report/                      # Cluster reports, saliency galleries, Markdown
│   ├── runs/<run>/<session_id>/             # V1 Legacy session isolation
│   │   ├── spectrograms/                    # Q-transform PNGs
│   │   ├── embeddings/                      # DINOv2 .npy arrays + .json metadata
│   │   ├── clusters/                        # Cluster reports, UMAP plots, HTML galleries
│   │   ├── morphcheck/                      # Individual morphcheck reference reports
│   │   ├── reports/                         # Unified full-analysis reports
│   │   ├── ablation/                        # Ablation study results
│   │   ├── stability/                       # Robustness analysis (ARI metrics)
│   │   ├── timeslide/                       # Time-slide background estimation
│   │   └── logs/                            # Session-specific log files
│   └── reference/                           # Static — reference indexes (e.g. indomain_O3b_H1.npz)
│
├── src/                                     # Python source packages
│   ├── __init__.py
│   ├── core/                                # Shared primitives (data loaders, encoder, utils)
│   │   ├── data_loader.py
│   │   ├── encoder.py                       # DINOv2-Reg ViT-S/14 (CLS + Patch tokens)
│   │   ├── preprocessor.py                  # Whiten → Bandpass → Q-Transform
│   │   ├── patch_producer.py                # CPU-bound spectrogram batch producer
│   │   ├── patch_scorer.py                  # Top-K MIL scoring + GEV thresholding
│   │   ├── parallel_processor.py            # ProcessPoolExecutor Q-transform
│   │   ├── utils.py                         # Config, logging, device selection
│   │   ├── logging_utils.py                 # Structured JSON logging
│   │   └── wizard.py                        # Interactive CLI wizard
│   │
│   ├── pipeline_v2_production/              # RIGID PRODUCTION O4A ENGINE (384D)
│   │   ├── production_cluster.py            # Adaptive PCA + Conditional DPMM
│   │   ├── production_report.py             # Per-session Markdown report generator
│   │   ├── aggregate_report.py              # Cross-session deduplicator & Spearman reducer
│   │   ├── production_writer.py             # SWMR-enabled HDF5 novelty archive writer
│   │   └── saliency_map.py                  # Three-panel topological saliency map
│   │
│   └── pipeline_v1_legacy/                  # FROZEN LEGACY PIPELINE (Read-Only)
│       ├── clustering.py                    # PCA + UMAP + DPMM/HDBSCAN
│       ├── stability.py                     # ARI robustness analysis
│       ├── timeslide.py                     # H1-L1 coincidence p-value
│       ├── full_analysis.py                 # End-to-end orchestrator
│       └── ...                              # 18 additional legacy modules
│
├── tests/                                   # Pytest suite
├── tests_and_validation/                    # Production validation gatekeepers
│   └── validate_reports.py                  # 384D geometry + GPS dedup validator
├── docs/                                    # Additional documentation
├── main.py                                  # Unified CLI entry point
├── config.yaml                              # Global configuration
├── CLI_REFERENCE.md                         # Complete CLI commands manual
├── RESULTS_OLD.md                           # Historical results (Phase 1 Global Pooling)
└── RESULTS.md                               # Active scientific results (Phase 4 Patch-Level MIL)
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
   python main.py build-indomain-reference --detector H1 --run O3b
   ```
2. **Automatic Scan + Full Analysis:**
   Performs the scan on synchronized H1 and L1 and invokes the entire ML loop.
   ```bash
   python main.py scan-extended --workers 6 --run O4a --full-analysis True
   ```
   > The results will be saved in `data/runs/o4a/<SESSION_ID>/reports/`.

### Reference Files & Auto-Discovery
Reference indexes follow the naming convention `indomain_{run}_{detector}.npz` (e.g. `indomain_O3b_H1.npz`) and are stored in `data/reference/`. To batch-download and build all indexes at once:
```bash
python main.py download-all-references --all --detector H1 L1
```
This downloads Gravity Spy CSVs from Zenodo and builds one `.npz` per run/detector pair. Existing files are skipped automatically.

When `--reference` is omitted in `morphcheck` or `full-analysis`, the pipeline **auto-discovers** all `indomain_*.npz` files in `data/reference/` and evaluates against every matching index.

### Autopilot & Threshold Calibration
1. **Log-likelihood Threshold Calibration (Clustering):**
   ```bash
   python main.py calibrate-loglikelihood --reference data/reference/indomain_O3b_H1.npz --percentile 5
   ```
2. **Per-class Threshold Calibration (Scan Live):**
   ```bash
   python main.py calibrate-threshold --reference data/reference/indomain_O3b_H1.npz --percentile 5
   ```
3. **Live Scan with KNOWN/NOVEL Classification:**
   ```bash
   python main.py scan-live --detector H1 --run O4a --workers 4
   ```
   > The results will be saved in `data/autopilot/<SESSION_ID>/`. If the NOVEL count exceeds `--min-novel`, the command will suggest using the standard pipeline for clustering.

4. **Patch-Level Production Pipeline (Phase 4):**
   ```bash
   python main.py patch-production \
                  --detector L1 \
                  --resume \
                  --k 68 \
                  --fpr 0.01 \
                  --workers 8 \
                  --batch-size 32
   ```
   > Scans raw HDF5 dataset using Patch-Level MIL vectors. Bypasses Signal Dilution Limits. Results are continuously written to SWMR-enabled HDF5 archives. Employs Producer-Consumer multiprocessing and Batched GPU inference for extreme performance.

5. **Clustering & Automated Reporting (Phase 5-7):**
   ```bash
   python main.py production-cluster --input data/production/<SESSION_ID>/novelties.h5
   python main.py production-report --detector L1 --session-id <SESSION_ID>
   ```
   > Automatically performs DPMM clustering on the 768D manifold, applies VQ Cosine Similarity Fallback for known classes, projects via 4D UMAP to calculate structural ARI (Bootstrap Stability), and compiles a complete Markdown report with Topological Saliency Galleries.

6. **Cross-Session Aggregation & Dedup:**
   ```bash
   python main.py aggregate-report --production-dir data/production/
   ```
   > Aggregates all validated production sessions into a master summary, resolving cross-detector coincidences and deduplicating overlapping GPS times. Outputs final peer-review taxonomy tables (Table 3a/3b) and computes Spearman rank correlations for topological stability defense.

All scientific results, validations, and benchmarks produced by the pipeline are available in **[RESULTS.md](RESULTS.md)**. Legacy data from Phase 1 is preserved in **[RESULTS_OLD.md](RESULTS_OLD.md)**.

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
To unlock GPU acceleration on Blackwell hardware (RTX 5070):

```bash
pip uninstall torch torchvision torchaudio -y
pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128
```

The pipeline will automatically detect Blackwell GPUs and fall back to CPU with a
WARNING log if the nightly build is not installed.

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
  doi    = {10.5281/zenodo.20543811},
  url    = {https://arxiv.org/abs/2605.28572}
}
```

For more details, please refer to the `CITATION.cff` file.

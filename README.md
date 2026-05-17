<div align="center">

# 🌊 gravi-signal-ml [![DOI](https://zenodo.org/badge/1231613598.svg)](https://doi.org/10.5281/zenodo.20121859)

**Unsupervised Anomaly Detection for Gravitational-Wave Data**

*Unsupervised morphological characterization of LIGO/Virgo O4a glitches using DINOv2 frozen features*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![GWOSC O4a](https://img.shields.io/badge/data-GWOSC%20O4a-orange.svg)](https://gwosc.org/)

</div>

---

## 🎯 What This Project Does

This pipeline performs **unsupervised anomaly detection** on freshly released
[O2–O4a gravitational-wave data](https://gwosc.org/) to
perform **unsupervised morphological characterization** of glitch activity not
yet catalogued by the community — without labeled training data and without GPU.

### Why is this needed?

The gravitational-wave community (LIGO/Virgo/KAGRA) already has excellent tools
for *known* problems:

| Tool                            | What it does                                             | Limitation                                  |
|---------------------------------|----------------------------------------------------------|---------------------------------------------|
| **Gravity Spy**                 | Supervised CNN classifier for 23 known O4 glitch classes | Cannot detect new/unknown classes by design |
| **ConvNeXt/ViT pipelines**      | Transfer learning on labeled Gravity Spy datasets        | Still requires labeled training data        |
| **Chirp-vs-glitch classifiers** | Binary classification                                    | Solved problem — no novelty                 |

**What's missing** — and what this project provides:

1. 🔍 **Novel glitch discovery** — detect unknown glitch classes without
   pre-labeled training data (self-supervised, zero annotation cost)
2. 🌐 **Cross-detector validation** — independent replication on H1 and L1
   to rule out instrument-local artefacts
3. 🔬 **Morphological similarity search** — compare anomalies against the
   full Gravity Spy O1–O3b training set using DINOv2 embedding space
4. 📖 **Reproducible, open-source code** — most GW ML papers do not release
   usable code; this project does, running on any laptop (CPU only)

> **Note on Virgo (V1):** Virgo did not participate in O4a due to a commissioning
> issue. It rejoined the network in O4b. This pipeline therefore targets H1
> (Hanford) and L1 (Livingston) only, which operated with duty cycles of 67.5%
> and 69% respectively during O4a (and similarly in other runs).

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
│   (clustering.py)   │  → HDBSCAN (auto-scaled min_cluster_size)
│                     │  → UMAP(2D) for visualization
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Morphological     │  KNN cosine search against in-domain
│   Cross-Check       │  reference index (Phase 3.4, recommended)
│  (similarity_       │  or Gravity Spy training set (Phase 3.3)
│   checker.py)       │  NOVEL / KNOWN / AMBIGUOUS per spectrogram
└─────────────────────┘
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
pre-commit install          # Optional
```

> **Note on GPU:** The pipeline runs fully on CPU. The RTX 5070 (Blackwell sm_120)
> is not yet supported by PyTorch stable. Encoding 2600 spectrograms takes ~10 min on CPU — acceptable for batch workloads.

---

## 🚀 Usage

### Graphical User Interface (GUI)

For those who prefer a graphical interface over the command line, a Gooey-based wrapper is available:

```bash
python gui.py
```
This opens a minimalist user interface where you can configure and run all the commands listed below without typing parameters manually.

### Phase 1 — Fetch a Known Event (Proof of Concept) - ONE TIME

```bash
python main.py fetch --event GW150914
```

Downloads H1 strain data for GW150914, applies whitening + bandpass,
and saves the Q-transform spectrogram to `data/spectrograms/GW150914_H1.png`.
A visible chirp confirms the preprocessing pipeline is mathematically correct.

---

### ONE-TIME — Build Reference Indexes

#### Gravity Spy Out-of-Domain Reference

> Download `trainingsetv1d1.tar.gz` (~5GB) from:
> https://zenodo.org/records/1476551/files/trainingsetv1d1.tar.gz
> and save to `data/reference/trainingsetv1d1.tar.gz`

```bash
python main.py build-reference --output data/reference/gravity_spy_index.npz --max-per-class 50
```

> **Note:** `trainingsetv1d1.h5` is **not used** — incompatible with h5py on Python 3.13.
> Always use the `.tar.gz` approach.

> **⚠️ Domain Gap Warning:** The Gravity Spy training images use different
> Q-transform parameters, color normalization, and image dimensions than this
> pipeline. This creates a systematic domain gap — use the in-domain reference
> below for scientifically valid morphcheck results.

#### In-Domain Reference (Recommended)

Fetches labeled Gravity Spy glitch timestamps from Zenodo, downloads their
strain from GWOSC, and processes them through **our** pipeline — ensuring
query and reference live in the same embedding space.

```bash
python main.py build-indomain-reference --output data/reference/indomain_index.npz --detector H1 --run O3b
python main.py validate-reference --reference data/reference/indomain_index.npz --test-event GW150914
```

✅ Validation passes if GW150914 maps to class `Chirp` with high cosine similarity.

---

### EVERY NEW RUN

Each run is automatically isolated by a **session ID** (timestamp-based, e.g. `20260510_143022`),
so multiple runs never overwrite each other. The session ID is printed at startup and used
to reconstruct all paths in subsequent commands.

Edit `config.yaml` to set scan duration and other parameters before starting.

#### Step 1 — Scan (Data Acquisition Strategies)

The pipeline supports two distinct scientific strategies for data acquisition depending on your objective:

**Mode A — Independent Scans (Single Detector)**
- **Goal:** Independent morphological discovery for each detector.
- **Approach:** Each detector is analyzed during its optimal observing period (e.g., high duty cycle, high stability). The anomalous clusters found are independent morphological candidates and do not require temporal coincidence.
- **Command:** Use the `scan` command to specify custom durations and runs for a single instrument.
```bash
python main.py scan --detector H1 --hours 72 --workers 6 --run O4a
python main.py scan --detector L1 --hours 48 --workers 6 --run O3b
```

> [!IMPORTANT]
> **Synchronized Parallelism:** For `scan-extended`, the `--workers` parameter must be an **even number** (e.g. 2, 4, 6, 8). The pipeline will automatically divide the workers between H1 and L1, processing the same time window in parallel to ensure perfect temporal alignment.

> [!TIP]
> **Automated Analysis:** You can automatically trigger the entire analysis pipeline (encoding, clustering, and all validation levels) after a scan by adding the `--full-analysis True` flag to your `scan-extended` or `scan` command.

**Incremental Mode:** To resume an interrupted scan or append more data, simply provide the same `--session-id`. The pipeline will automatically detect the highest GPS end-time of existing spectrograms and resume from there.

> [!IMPORTANT]
> **Priority Note:** In resume mode, the pipeline ignores the `--hours` CLI flag and always reads the scan duration from `config.yaml` (`hours_per_detector`) to ensure session consistency.

```bash
python main.py scan-extended --workers 6 --session-id <PREVIOUS_SESSION_ID>
```

> [!TIP]
> **Disk Space Optimization:** By default, the pipeline **does not save** raw HDF5 files to `data/raw` to save disk space. If you need to cache raw data, use the `--no-cache-raw False` flag.


📋 Note the **Session ID** printed at startup — you will need it for all subsequent steps.

Spectrograms are saved to `data/spectrograms/{run}/<SESSION_ID>/{detector}/`.

#### Step 2 — Feature Extraction (DINOv2 with Registers)

**Why DINOv2-Reg and not SimCLR/MAE:**
- SimCLR on GW waveforms: already published (2022)
- Autoencoder anomaly detection on O3 glitches: already published (arXiv:2310.03453)
- **DINOv2 frozen on GW spectrograms: not done — our contribution**
- Register tokens (ICLR 2024) suppress feature map artefacts → cleaner clusters
- No labeled data, no GPU training, reproducible on any laptop

```bash
python main.py encode --session-id <SESSION_ID> --detector H1 --run O4a
python main.py encode --session-id <SESSION_ID> --detector L1 --run O4a
```

Loads DINOv2-Reg ViT-S/14 via `torch.hub` (~90 MB on first run) and saves
a `(N, 384)` float32 embedding array + companion `.json` metadata.

#### Step 3 — Clustering & Novel Glitch Discovery

**Pipeline:** PCA(50D) → UMAP(10D, cosine, `min_dist=0.0`) → HDBSCAN → UMAP(2D) visualization

Two UMAP passes are required:
- **Clustering pass** (`min_dist=0.0`, 10D): tight packing for HDBSCAN density detection
- **Visualization pass** (`min_dist=0.1`, 2D): readable scatter plot — never cluster on this

HDBSCAN `min_cluster_size` is **auto-scaled** to 0.5% of N, ensuring comparable
sensitivity across datasets of different sizes.

```bash
python main.py cluster --session-id <SESSION_ID> --detector H1 --run O4a
python main.py cluster --session-id <SESSION_ID> --detector L1 --run O4a
```

**Outputs:**
- `cluster_report.json` — structured report with cluster sizes and anomaly flags
- `umap_visualization.png` — 2D colored scatter plot with anomalous clusters marked ⭐
- `cluster_gallery/cluster_N/contact_sheet.png` — 3×3 grids of representative spectrograms

> [!TIP]
> **Cross-Detector Validation:** If you used **Mode B (Coincident Scans)** and an anomalous morphology appears **independently on both H1 and L1** in the same time window, instrument-local explanations are significantly weakened — a key scientific requirement before any claim.

### The Three Levels of Glitch Validation

Glitch validation in this pipeline is not a single step, but a rigorous **three-level process** designed to ensure scientific solidity before making any claims about novel morphological classes.

| Level | Phase | Question it Answers | When to Execute |
|-------|-------|---------------------|-----------------|
| **1. Internal Robustness** | `ablation` + `stability` | Are the clusters real, or just artifacts of preprocessing/hyperparameters? | Immediately after clustering |
| **2. Physical Significance** | `timeslide` | Do anomalies appear on both detectors simultaneously, or are they random coincidences? | After robustness checks pass |
| **3. Morphological Classification** | `morphcheck` | Does this anomaly match a known Gravity Spy class, or is it truly NOVEL? | After timeslide (or in parallel) |

**Validation Flowchart:**
```text
scan → encode → cluster
                      ↓
                 ABLATION ──── if it fails → STOP, clusters are not robust
                      ↓
                 STABILITY ─── if it fails → STOP, clusters are unstable
                      ↓
                 TIMESLIDE ─── if p > 0.05 → H1-L1 coincidences are not significant
                      ↓
                 MORPHCHECK ── NOVEL / KNOWN / AMBIGUOUS
```
> [!IMPORTANT]
> **Scientific Rigor:** Only when all three levels of validation yield positive results can you scientifically claim the discovery of a truly NOVEL or exceptionally rare glitch class.

### 🤖 Automated Full Analysis (Recommended)

To automate the entire analysis pipeline (Level 1, 2, and 3 validation) for a session, use the `full-analysis` command. This sequentially executes **encoding, clustering, morphological cross-checks, ablation studies, stability analysis, and time-slides**, producing a unified report.

**Manual execution:**
```bash
python main.py full-analysis --session-id <SESSION_ID> --detector H1 L1 --run O4a
```
> [!TIP]
> **Performance:** By default, detector analysis (H1/L1) runs in **parallel** to save time. If you experience resource issues, use the `--sequential` flag to run them one after the other.

**Automatic trigger after scan:**
```bash
python main.py scan-extended --workers 6 --full-analysis True
```

This produces a unified JSON report at `data/reports/{run}/<SESSION_ID>/{detector}_full_report.json` summarizing the entire pipeline status, including a **session summary** with descriptive statistics (GPS range, duration, duty cycle).

### 🔄 Continuous Synchronized Run Mode (`--continue-run`)

To perform large-scale sequential analyses over consecutive time periods automatically, you can use the `--continue-run` option with either `full-analysis` or `scan-extended` (when `--full-analysis True` is specified).

When specified, after completing the full analysis of the current session:
1. It automatically searches for the highest processed GPS timestamps for H1 and L1 in the session folder.
2. It calculates the synchronized resume time: `GPS_synchronized = min(ultimo_H1, ultimo_L1)`.
3. It generates a new, collision-free `session-id`.
4. It programmatically launches `scan-extended` on the new session starting at `GPS = GPS_synchronized + 1` for the duration configured in `config.yaml` (`run_config.<run>.hours_per_detector`).
5. It runs `full-analysis` on the new session and repeats.

This loop safely stops when it reaches `--max-iterations` (default `10`) or when it passes the `--stop-date` limit (ISO string or GPS time).

**Examples:**
```bash
# Start from full-analysis and continue up to 5 iterations
python main.py full-analysis --session-id <SESSION_ID> --detector H1 L1 --continue-run --max-iterations 5

# Start from scan-extended, auto-analyze, and continue until a specific stop date
python main.py scan-extended --workers 6 --full-analysis True --continue-run --stop-date "2023-06-01 12:00:00"
```

---

#### Step 4 — Morphological Cross-Check

```bash
python main.py morphcheck --embeddings data/embeddings/<SESSION_ID>/o4a_h1.npy --report data/clusters/<SESSION_ID>/h1/cluster_report.json --reference data/reference/indomain_index.npz --output data/clusters/<SESSION_ID>/h1/morphological_crosscheck_indomain.json --run O4a

python main.py morphcheck --embeddings data/embeddings/<SESSION_ID>/o4a_l1.npy --report data/clusters/<SESSION_ID>/l1/cluster_report.json --reference data/reference/indomain_index.npz --output data/clusters/<SESSION_ID>/l1/morphological_crosscheck_indomain.json --run O4a
```

**Outputs:**
- `morphological_crosscheck_indomain.json` — Detailed report classifying each anomalous spectrogram as NOVEL, KNOWN, or AMBIGUOUS with cosine similarity scores and nearest-neighbor classes.

Each anomalous spectrogram receives one of three labels:

| Status        | Condition                              | Meaning                                          |
|---------------|----------------------------------------|--------------------------------------------------|
| **NOVEL**     | cosine sim < threshold                 | Not similar to any known class → novel candidate |
| **KNOWN**     | sim ≥ threshold, label agreement ≥ 60% | Matches a known Gravity Spy class                |
| **AMBIGUOUS** | sim ≥ threshold, agreement < 60%       | Visually similar but no clear class match        |

#### Step 5 — Ablation Study (Robustness Check)

Verify if the DINOv2+UMAP+HDBSCAN clustering is capturing true physical morphologies or just rendering artifacts (e.g. colormap, intensity, contrast). The ablation subcommand generates alternative embeddings using grayscale, inverted, and random-intensity spectrograms, as well as a random baseline, and computes the Adjusted Rand Index (ARI) against the original clusters.

```bash
python main.py ablation --session-id <SESSION_ID> --detector H1 --run O4a
```

If the `grayscale` ARI < 0.4, the pipeline warns of "preprocessing-dominant" behavior.

#### Step 6 — Stability Analysis

Measure the robustness of the clustering pipeline against variations in hyperparameters. The `stability` subcommand runs the clustering pipeline multiple times, applying random perturbations to the UMAP `n_neighbors` and HDBSCAN `min_cluster_size` parameters. It computes the pairwise Adjusted Rand Index (ARI) to evaluate consistency.

```bash
python main.py stability --session-id <SESSION_ID> --detector H1 --n-runs 20 --run O4a
```

Outputs a comprehensive `stability_report.json` with an $N \times N$ ARI matrix and flags clusters that are consistently anomalous across $\ge 80\%$ of runs.

#### Step 7 — Time-slide Background Validation

Estimate the statistical significance of anomalous cluster coincidences between H1 and L1 using time-slides to model the random background rate.

```bash
python main.py timeslide --session-id <SESSION_ID> --run O4a
```

Calculates the zero-lag coincidences (±32s window) and compares it against 50 random L1 time shifts to produce an empirical p-value and z-score.

---

### Performance & Parallelization

By default all scans run sequentially (`--workers 1`) and work on any hardware.

```bash
python main.py scan --detector H1 --hours 6 --workers 6 --run O4a
python main.py scan-extended --workers 6 --run O4a
```

| Hardware        | Mode          | Speed                         |
|-----------------|---------------|-------------------------------|
| Any laptop      | `--workers 1` | ~1.5 s/segment                |
| Ryzen 7 7800X3D | `--workers 6` | ~0.35 s/segment (~4x speedup) |

GWOSC fetch threads are capped at 4 regardless of `--workers` to respect public server rate limits.

---

## 📊 Preliminary Results (O4a, 48h H1 + 48h L1)

| Detector | Samples | Clusters | Anomalous           | Noise | PCA Variance |
|----------|---------|----------|---------------------|-------|--------------|
| H1       | 2,634   | 5        | **2** (23 + 19 pts) | 0.0%  | 98.2%        |
| L1       | 4,982   | 6        | **1** (32 pts)      | 0.0%  | 98.4%        |

Anomalous clusters were identified independently on both detectors.
Morphological cross-check against the in-domain Gravity Spy O3b reference
(Phase 3.4, GW150914 validation: Chirp@0.997) shows:

- **H1 Cluster 1** (23 pts): maps to Low_Frequency_Lines / 1400Ripples (KNOWN)
- **H1 Cluster 4** (19 pts): 89% AMBIGUOUS between Low_Frequency_Lines and No_Glitch
- **L1 Cluster 4** (32 pts): maps to Low_Frequency_Lines (KNOWN/AMBIGUOUS)

No fully novel morphologies were identified in this 48h window. The pipeline
is validated end-to-end and ready for extended analysis.

**Robustness validation (H1):**
- Ablation study: ARI > 0.999 across grayscale/inverted/shuffled-intensity variants
- Random baseline: ARI ≈ 0.000 (correct negative control)
- Stability analysis: ARI mean=0.9997 ± 0.0003 across 21 hyperparameter configurations
- **L1 note:** grayscale ARI = 0.377 — L1 clustering shows partial dependence on
  rendering statistics; physical interpretation requires further investigation

**Known methodological limitations:**
- UMAP distorts global distances to preserve local structure — anomalous
  clusters separated by UMAP may reflect preprocessing artifacts, not distinct
  physical morphologies. Ablation ARI > 0.999 partially mitigates this concern.
- DINOv2 is trained on natural images; transfer to GW spectrograms is assumed
  but not yet formally validated for this domain.
- Standard Q-transform (qrange=[4,64]) may miss fast narrowband or slow
  broadband structures — Multi-Q analysis (Phase 5) addresses this.
- L1 clustering shows partial rendering dependence (grayscale ARI=0.377);
  physical interpretation of L1 clusters requires further validation.
---

## 🧪 Running Tests

```bash
pytest tests/ -v
pytest tests/ -v --run-slow
pytest tests/ -v --cov=src --cov-report=term-missing
```

All tests use synthetic data and mocked network calls. Slow tests marked
with `@pytest.mark.slow` are skipped by default for CI compatibility.

---

## 📂 Project Structure

```
gravi-signal-ml/
├── data/                             # Git-ignored data artifacts
│   ├── raw/                          # .gwf / .hdf5 strain downloads
│   ├── runs/<run>/<session_id>/      # Complete run and session isolation
│   │   ├── spectrograms/             # Q-transform PNGs (H1/L1)
│   │   ├── embeddings/               # DINOv2 .npy embedding arrays and metadata .json
│   │   ├── clusters/                 # Cluster reports, galleries, and morphcheck reports
│   │   ├── reports/                  # Unified end-to-end analysis reports
│   │   ├── ablation/                 # Ablation study results
│   │   ├── stability/                # Robustness analysis (ARI metrics)
│   │   └── timeslide/                # Time-slide background estimation reports
│   └── reference/                    # Static — Gravity Spy reference indexes
├── src/
│   ├── data_loader.py                # GWOSC fetch + O4a segment management
│   ├── preprocessor.py               # Whitening · bandpass · Q-transform · batch
│   ├── parallel_processor.py         # ThreadPool + ProcessPool pipeline
│   ├── encoder.py                    # DINOv2-Reg frozen encoder
│   ├── clustering.py                 # PCA + UMAP + HDBSCAN pipeline
│   ├── reporter.py                   # Cluster report + UMAP viz + gallery
│   ├── gravity_spy_checker.py        # GPS-based cross-check (requires LIGO auth)
│   ├── reference_builder.py          # Gravity Spy tar.gz → DINOv2 reference index
│   ├── indomain_reference_builder.py # In-domain reference from labeled GPS (Phase 3.4)
│   ├── similarity_checker.py         # Cosine KNN novelty assessment
│   └── utils.py                      # Config · logging · GPS conversion · normalization
│   ├── ablation.py                   # Ablation study — ARI vs preprocessing variants
│   ├── stability.py                  # Stability analysis — ARI across hyperparameter runs
│   ├── timeslide.py                  # Time-slide background estimation
│   └── full_analysis.py              # End-to-end pipeline orchestrator
├── results/
│   └── figures/                      # Committed: UMAP plots + anomalous contact sheets
├── docs/
│   ├── SESSION_HANDOFF.md            # Session continuity document
│   ├── STEP.md                       # Full pipeline commands reference
│   ├── TODO.md                       # Current TODO and open tasks
│   └── IMPL.md                       # Implementation notes
├── notebooks/                        # Exploratory Jupyter notebooks
├── tests/                            # Pytest suite (synthetic data, mocked network)
├── main.py                           # CLI entry point (18 subcommands)
├── config.yaml                       # Central configuration (all parameters)
├── CLI_REFERENCE.md                  # Complete CLI reference (auto-generated)
├── requirements.txt                  # Pinned dependencies
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

---

## 📄 Citation

If you use this code in your research, please cite:

```bibtex
@software{gravi_signal_ml,
  title  = {gravi-signal-ml: Unsupervised Anomaly Detection for Gravitational-Wave Data},
  author = {Cirfeta, Luca},
  year   = {2026},
  url    = {https://github.com/lucacirfeta/dante-gravi-signal-ml},
  note   = {Unsupervised morphological characterization of LIGO O4a glitches using DINOv2 frozen features}
}
```

## 📝 License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
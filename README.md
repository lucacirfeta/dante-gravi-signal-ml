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
[O4a gravitational-wave data](https://gwosc.org/) (GWTC-4.0, 2024) to
surface **candidate novel glitch classes** and unknown signal morphologies not
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
3. 🔬 **Morphological similarity search** — compare O4a anomalies against the
   full Gravity Spy O1–O3b training set using DINOv2 embedding space
4. 📖 **Reproducible, open-source code** — most GW ML papers do not release
   usable code; this project does, running on any laptop (CPU only)

> **Note on Virgo (V1):** Virgo did not participate in O4a due to a commissioning
> issue. It rejoined the network in O4b. This pipeline therefore targets H1
> (Hanford) and L1 (Livingston) only, which operated with duty cycles of 67.5%
> and 69% respectively during O4a.

---

## 🏗️ Architecture

```
Raw Strain Data (GWOSC O4a)
        │
        ▼
┌─────────────────────┐
│   Data Loader       │  gwpy fetch_open_data() · O4a segment management
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

# Install dependencies
pip install -r requirements.txt
pre-commit install          # Optional
```

> **Note on GPU:** The pipeline runs fully on CPU. The RTX 5070 (Blackwell sm_120)
> is not yet supported by PyTorch stable. Encoding 2600 spectrograms takes ~10 min on CPU — acceptable for batch workloads.

---

## 🚀 Usage

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

#### Step 1 — Scan

```bash
# H1 + L1 together, duration from config.yaml
python main.py scan-extended --workers 6

# Or custom duration per detector
python main.py scan --detector H1 --hours 72 --workers 6
python main.py scan --detector L1 --hours 72 --workers 6
```

📋 Note the **Session ID** printed at startup — you will need it for all subsequent steps.

Spectrograms are saved to `data/spectrograms/o4a/<SESSION_ID>/{detector}/`.

#### Step 2 — Feature Extraction (DINOv2 with Registers)

**Why DINOv2-Reg and not SimCLR/MAE:**
- SimCLR on GW waveforms: already published (2022)
- Autoencoder anomaly detection on O3 glitches: already published (arXiv:2310.03453)
- **DINOv2 frozen on GW spectrograms: not done — our contribution**
- Register tokens (ICLR 2024) suppress feature map artefacts → cleaner clusters
- No labeled data, no GPU training, reproducible on any laptop

```bash
python main.py encode --session-id <SESSION_ID> --detector H1
python main.py encode --session-id <SESSION_ID> --detector L1
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
python main.py cluster --session-id <SESSION_ID> --detector H1
python main.py cluster --session-id <SESSION_ID> --detector L1
```

**Outputs:**
- `cluster_report.json` — structured report with cluster sizes and anomaly flags
- `umap_visualization.png` — 2D colored scatter plot with anomalous clusters marked ⭐
- `cluster_gallery/cluster_N/contact_sheet.png` — 3×3 grids of representative spectrograms

If anomalous morphologies appear **independently on both H1 and L1**, instrument-local
explanations are significantly weakened — a key scientific requirement before any claim.

#### Step 4 — Morphological Cross-Check

```bash
python main.py morphcheck --embeddings data/embeddings/<SESSION_ID>/o4a_h1.npy --report data/clusters/<SESSION_ID>/h1/cluster_report.json --reference data/reference/indomain_index.npz --output data/clusters/<SESSION_ID>/h1/morphological_crosscheck_indomain.json

python main.py morphcheck --embeddings data/embeddings/<SESSION_ID>/o4a_l1.npy --report data/clusters/<SESSION_ID>/l1/cluster_report.json --reference data/reference/indomain_index.npz --output data/clusters/<SESSION_ID>/l1/morphological_crosscheck_indomain.json
```

Each anomalous spectrogram receives one of three labels:

| Status        | Condition                              | Meaning                                          |
|---------------|----------------------------------------|--------------------------------------------------|
| **NOVEL**     | cosine sim < threshold                 | Not similar to any known class → novel candidate |
| **KNOWN**     | sim ≥ threshold, label agreement ≥ 60% | Matches a known Gravity Spy class                |
| **AMBIGUOUS** | sim ≥ threshold, agreement < 60%       | Visually similar but no clear class match        |

---

### Performance & Parallelization

By default all scans run sequentially (`--workers 1`) and work on any hardware.

```bash
python main.py scan --detector H1 --hours 6 --workers 6
python main.py scan-extended --workers 6
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
- **H1 Cluster 4** (19 pts): 89% AMBIGUOUS between Low_Frequency_Lines and
  No_Glitch — suggests subtle sub-threshold narrowband activity in O4a
- **L1 Cluster 4** (32 pts): morphological crosscheck in progress

No fully novel morphologies were identified in this 48h window. The pipeline
is validated end-to-end and ready for extended analysis.

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
│   ├── spectrograms/o4a/<session_id>/ # Q-transform PNGs, isolated per run
│   ├── embeddings/<session_id>/      # DINOv2 .npy embedding arrays
│   ├── clusters/<session_id>/        # Cluster reports + galleries
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
├── results/
│   └── figures/                      # Committed: UMAP plots + anomalous contact sheets
├── docs/
│   ├── SESSION_HANDOFF.md            # Session continuity document
│   └── STEPS.md                      # Full pipeline commands reference
├── notebooks/                        # Exploratory Jupyter notebooks
├── tests/                            # Pytest suite (synthetic data, mocked network)
├── main.py                           # CLI entry point
├── config.yaml                       # Central configuration (all parameters)
├── requirements.txt                  # Pinned dependencies
└── .pre-commit-config.yaml           # ruff + mypy + file hygiene
```

---

## 🗺️ Roadmap

| Phase         | Description                                          | Status                             |
|---------------|------------------------------------------------------|------------------------------------|
| **Phase 1**   | Preprocessing pipeline + GW150914 chirp validation   | ✅ Complete                         |
| **Phase 2**   | DINOv2-Reg frozen encoder (384-dim embeddings)       | ✅ Complete                         |
| **Phase 3**   | PCA + UMAP + HDBSCAN clustering                      | ✅ Complete                         |
| **Phase 3.1** | Extended scan 48h H1+L1 + GPS cross-check            | ✅ Complete                         |
| **Phase 3.2** | Parallel pipeline (`--workers N`)                    | ✅ Complete                         |
| **Phase 3.3** | Morphological similarity vs Gravity Spy training set | ✅ Complete (domain gap documented) |
| **Phase 3.4** | In-domain reference + session isolation              | ✅ Complete                         |
| **Phase 4**   | Novel candidate reporting + community contribution   | 🔲 Planned                         |

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
  note   = {Novel glitch discovery in LIGO/Virgo O4a data using DINOv2 frozen features}
}
```

## 📝 License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
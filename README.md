<div align="center">

# 🌊 gravi-signal-ml

**Unsupervised Anomaly Detection for Gravitational-Wave Data**

*Discovering novel glitch classes in LIGO/Virgo O4a data that Gravity Spy can't see*

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

| Tool | What it does | Limitation |
|------|-------------|------------|
| **Gravity Spy** | Supervised CNN classifier for 23 known O4 glitch classes | Cannot detect new/unknown classes by design |
| **ConvNeXt/ViT pipelines** | Transfer learning on labeled Gravity Spy datasets | Still requires labeled training data |
| **Chirp-vs-glitch classifiers** | Binary classification | Solved problem — no novelty |

**What's missing** — and what this project provides:

1. 🔍 **Novel glitch discovery** — detect unknown glitch classes without
   pre-labeled training data (self-supervised, zero annotation cost)
2. 🌐 **Cross-detector validation** — independent replication on H1 and L1
   to rule out instrument-local artefacts
3. 🔬 **Morphological similarity search** — compare O4a anomalies against the
   full Gravity Spy O1–O3b training set using DINOv2 embedding space
4. 📖 **Reproducible, open-source code** — most GW ML papers do not release
   usable code; this project does, running on any laptop (CPU only)

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

# (Optional) Set up pre-commit hooks
pre-commit install
```

> **Note on GPU:** The pipeline runs fully on CPU. The RTX 5070 (Blackwell sm_120)
> is not yet supported by PyTorch stable. Encoding 2600 spectrograms takes ~10 min on CPU — acceptable for batch workloads.

---

## 🚀 Usage

### Phase 1 — Fetch a Known Event (Proof of Concept)

```bash
python main.py fetch --event GW150914
```

Downloads H1 strain data for GW150914, applies whitening + bandpass,
and saves the Q-transform spectrogram to `data/spectrograms/GW150914_H1.png`.
A visible chirp confirms the preprocessing pipeline is mathematically correct.

### Phase 1 — Batch Scan O4a Data

```bash
# Sequential (default, works on any machine)
python main.py scan --detector H1 --hours 6

# Parallel (multi-core systems, e.g. Ryzen 7 7800X3D)
python main.py scan --detector H1 --hours 6 --workers 6

# Full extended scan: 48h H1 + 48h L1
python main.py scan-extended --workers 6
```

Spectrograms are saved to `data/spectrograms/o4a/{detector}/`.

### Phase 2 — Feature Extraction (DINOv2 with Registers)

**Why DINOv2-Reg and not SimCLR/MAE:**
- SimCLR on GW waveforms: already published (2022)
- Autoencoder anomaly detection on O3 glitches: already published (arXiv:2310.03453)
- **DINOv2 frozen on GW spectrograms: not done — our contribution**
- Register tokens (ICLR 2024) suppress feature map artefacts → cleaner clusters
- No labeled data, no GPU training, reproducible on any laptop

```bash
python main.py encode \
  --input-dir data/spectrograms/o4a/H1/ \
  --output    data/embeddings/o4a_h1_48h.npy \
  --batch-size 32
```

Loads DINOv2-Reg ViT-S/14 via `torch.hub` (~90 MB on first run) and saves
a `(N, 384)` float32 embedding array + companion `.json` metadata.

### Phase 3 — Clustering & Novel Glitch Discovery

**Pipeline:** PCA(50D) → UMAP(10D, cosine, `min_dist=0.0`) → HDBSCAN → UMAP(2D) visualization

Two UMAP passes are required:
- **Clustering pass** (`min_dist=0.0`, 10D): tight packing for HDBSCAN density detection
- **Visualization pass** (`min_dist=0.1`, 2D): readable scatter plot — never cluster on this

HDBSCAN `min_cluster_size` is **auto-scaled** to 0.5% of N, ensuring comparable
sensitivity across datasets of different sizes.

```bash
python main.py cluster \
  --input  data/embeddings/o4a_h1_48h.npy \
  --output data/clusters/h1_48h/
```

**Outputs:**
- `cluster_report.json` — structured report with cluster sizes and anomaly flags
- `umap_visualization.png` — 2D colored scatter plot with anomalous clusters marked ⭐
- `cluster_gallery/cluster_N/contact_sheet.png` — 3×3 grids of representative spectrograms

### Phase 3.1 — Extended Scan + Cross-Detector Validation

```bash
# Re-cluster L1
python main.py cluster \
  --input  data/embeddings/o4a_l1_48h.npy \
  --output data/clusters/l1_48h/
```

If anomalous morphologies appear **independently on both H1 and L1**, instrument-local
explanations are significantly weakened — a key scientific requirement before any claim.

### Phase 3.2 — Performance & Parallelization

By default all scans run sequentially (`--workers 1`) and work on any hardware.

```bash
# Multi-core (recommended: CPU cores - 2)
python main.py scan --detector H1 --hours 6 --workers 6
python main.py scan-extended --workers 6
```

| Hardware | Mode | Speed |
|----------|------|-------|
| Any laptop | `--workers 1` | ~1.5 s/segment |
| Ryzen 7 7800X3D | `--workers 6` | ~0.35 s/segment (~4x speedup) |

GWOSC fetch threads are capped at 4 regardless of `--workers` to respect public server rate limits.

### Phase 3.3 — Morphological Similarity Cross-Check

**Scientific rationale:** O4a data is not in the Gravity Spy Zenodo catalog (only O1–O3b).
GPS-based lookup requires LIGO authentication. Morphological similarity in DINOv2 embedding
space is the correct approach: it asks *"does this LOOK like a known glitch?"* rather than
*"was this exact timestamp already classified?"*

#### Step 1 — Build the Reference Index (one-time, ~10 min)

Download the Gravity Spy training set from Zenodo (~5 GB):

```
https://zenodo.org/records/1476551/files/trainingsetv1d1.tar.gz
```

Save to `data/reference/trainingsetv1d1.tar.gz`, then:

```bash
python main.py build-reference \
  --output data/reference/gravity_spy_index.npz \
  --max-per-class 50
```

Extracts up to 50 images per class (22 classes ≈ 1100 images), applies the official
Gravity Spy crop (`x=[66:532], y=[105:671]`), and builds a `(1100, 384)` DINOv2
reference index.

> **Note:** `trainingsetv1d1.h5` is **not used** — incompatible with h5py on Python 3.13.
> Always use the `.tar.gz` approach.

#### Step 2 — Run the Morphological Cross-Check

```bash
# H1 anomalous clusters
python main.py morphcheck \
  --embeddings data/embeddings/o4a_h1_48h.npy \
  --report     data/clusters/h1_48h/cluster_report.json \
  --reference  data/reference/gravity_spy_index.npz \
  --output     data/clusters/h1_48h/morphological_crosscheck.json

# L1 anomalous clusters
python main.py morphcheck \
  --embeddings data/embeddings/o4a_l1_48h.npy \
  --report     data/clusters/l1_48h/cluster_report.json \
  --reference  data/reference/gravity_spy_index.npz \
  --output     data/clusters/l1_48h/morphological_crosscheck.json
```

Each anomalous spectrogram receives one of three labels:

| Status | Condition | Meaning |
|--------|-----------|---------|
| **NOVEL** | cosine sim < 0.85 | Not similar to any known class → novel candidate |
| **KNOWN** | sim ≥ 0.85, label agreement ≥ 60% | Matches a known Gravity Spy class |
| **AMBIGUOUS** | sim ≥ 0.85, agreement < 60% | Visually similar to training set but no clear match |

> **⚠️ Domain Gap Warning (Phase 3.3):** The Gravity Spy training images use
> different Q-transform parameters, color normalization, and image dimensions
> than our pipeline. This creates a systematic domain gap (all similarities
> < 0.85, even GW150914 → Wandering_Line@0.67 instead of Chirp). Use the
> in-domain reference (Phase 3.4) for scientifically valid results.

### Phase 3.4 — In-Domain Morphological Reference (Recommended)

**Why in-domain instead of the Gravity Spy training images:**

The Gravity Spy training set images use different Q-transform parameters,
color mapping, and normalization than our pipeline. DINOv2 sees two different
"image styles", creating a systematic domain gap (all similarities < 0.85,
even GW150914 → Wandering_Line@0.67 instead of Chirp).

**Solution:** download Gravity Spy labeled glitch timestamps (Zenodo, public),
fetch their strain from GWOSC, and process with **our** pipeline. Reference and
query are now in identical domain.

```bash
# Build in-domain reference (~30 events × 21 classes = ~600 downloads, ~2h)
python main.py build-indomain-reference \
  --output data/reference/indomain_index.npz \
  --detector H1 --run O3b

# Validate: GW150914 should map to Chirp class
python main.py validate-reference \
  --reference data/reference/indomain_index.npz \
  --test-event GW150914

# Run morphological crosscheck with in-domain reference
python main.py morphcheck \
  --embeddings data/embeddings/o4a_h1_48h.npy \
  --report     data/clusters/h1_48h/cluster_report.json \
  --reference  data/reference/indomain_index.npz \
  --output     data/clusters/h1_48h/morphological_crosscheck_indomain.json
```

**Scientific validity:** If `validate-reference` PASSES (GW150914 → Chirp with
high similarity), the morphcheck results are trustworthy. **NOVEL** status then
means the morphology genuinely differs from all known O1–O3b glitch classes.

---

## 📊 Preliminary Results (O4a, 48h H1 + 48h L1)

| Detector | Samples | Clusters | Anomalous | Noise | PCA Variance |
|----------|---------|----------|-----------|-------|--------------|
| H1 | 2,634 | 5 | **2** (23 + 19 pts) | 0.0% | 98.2% |
| L1 | 4,982 | 6 | **1** (32 pts) | 0.0% | 98.4% |

Anomalous clusters were identified independently on two detectors with
different instrumental noise characteristics. Morphological cross-check
against the Gravity Spy O1–O3b training set is in progress.

---

## 🧪 Running Tests

```bash
# Full test suite (fast, no internet required)
pytest tests/ -v

# Include slow tests (requires DINOv2 model download ~90MB)
pytest tests/ -v --run-slow

# With coverage
pytest tests/ -v --cov=src --cov-report=term-missing
```

All tests use synthetic data and mocked network calls. Slow tests marked
with `@pytest.mark.slow` are skipped by default for CI compatibility.

---

## 📂 Project Structure

```
gravi-signal-ml/
├── data/                        # Git-ignored data artifacts
│   ├── raw/                     # .gwf / .hdf5 strain downloads
│   ├── spectrograms/            # Q-transform PNGs
│   ├── embeddings/              # DINOv2 .npy embedding arrays
│   ├── clusters/                # Cluster reports + galleries
│   └── reference/               # Gravity Spy reference index
├── src/
│   ├── data_loader.py           # GWOSC fetch + O4a segment management
│   ├── preprocessor.py          # Whitening · bandpass · Q-transform · batch
│   ├── parallel_processor.py    # ThreadPool + ProcessPool pipeline
│   ├── encoder.py               # DINOv2-Reg frozen encoder
│   ├── clustering.py            # PCA + UMAP + HDBSCAN pipeline
│   ├── reporter.py              # Cluster report + UMAP viz + gallery
│   ├── gravity_spy_checker.py       # GPS-based cross-check (requires LIGO auth)
│   ├── reference_builder.py         # Gravity Spy tar.gz → DINOv2 reference index
│   ├── indomain_reference_builder.py # In-domain reference from labeled GPS (Phase 3.4)
│   ├── similarity_checker.py        # Cosine KNN novelty assessment
│   └── utils.py                     # Config · logging · GPS conversion · normalization
├── results/
│   └── figures/                 # Committed: UMAP plots + anomalous contact sheets
├── docs/
│   └── SESSION_HANDOFF.md       # Session continuity document
├── notebooks/                   # Exploratory Jupyter notebooks
├── tests/                       # Pytest suite (synthetic data, mocked network)
├── main.py                      # CLI: fetch · scan · encode · cluster · morphcheck
├── config.yaml                  # Central configuration (all parameters)
├── requirements.txt             # Pinned dependencies
└── .pre-commit-config.yaml      # ruff + mypy + file hygiene
```

---

## 🗺️ Roadmap

| Phase | Description | Status |
|-------|------------|--------|
| **Phase 1** | Preprocessing pipeline + GW150914 chirp validation | ✅ Complete |
| **Phase 2** | DINOv2-Reg frozen encoder (384-dim embeddings) | ✅ Complete |
| **Phase 3** | PCA + UMAP + HDBSCAN clustering | ✅ Complete |
| **Phase 3.1** | Extended scan 48h H1+L1 + GPS cross-check | ✅ Complete |
| **Phase 3.2** | Parallel pipeline (`--workers N`) | ✅ Complete |
| **Phase 3.3** | Morphological similarity vs Gravity Spy training set | ✅ Complete (domain gap noted) |
| **Phase 3.4** | In-domain reference (our pipeline on labeled GPS) | 🔄 In Progress |
| **Phase 4** | Novel candidate reporting + community contribution | 🔲 Planned |

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
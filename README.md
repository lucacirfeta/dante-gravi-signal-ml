<div align="center">

# 🌊 gravi-signal-ml

**Unsupervised Anomaly Detection for Gravitational-Wave Data**

*Discovering novel glitch classes in LIGO/Virgo O4a data that Gravity Spy can't see*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

</div>

---

## 🎯 What This Project Does

This pipeline performs **unsupervised anomaly detection** on freshly released
[O4a gravitational-wave data](https://gwosc.org/) (GWTC-4.0, August 2025) to
surface **candidate novel glitch classes** and unknown signal morphologies not
yet catalogued by the community.

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
   pre-labeled training data (self-supervised)
2. 🌐 **Cross-detector generalization** — models that train on H1 and
   transfer to L1/V1 without fine-tuning
3. 📖 **Reproducible, open-source code** — most GW ML papers do not release
   usable code (a major gap noted in the literature)

## 🏗️ Architecture

```
Raw Strain Data (GWOSC)
        │
        ▼
┌─────────────────┐
│  Data Loader    │  fetch_open_data() via gwpy
│  (data_loader)  │  O4a segment management
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Preprocessor   │  Whitening → Bandpass → Q-Transform
│  (preprocessor) │  Batch processing with fault tolerance
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Encoder        │  DINOv2-Reg ViT-S/14 (frozen)
│  (Phase 2)      │  CLS token → 384-dim L2-norm embeddings
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Clustering     │  UMAP + HDBSCAN
│  (Phase 3)      │  Novel class candidate discovery
└─────────────────┘
```

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/lucacirfeta/dante-gravi-signal-ml.git
cd dante-gravi-signal-ml

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# (Optional) Set up pre-commit hooks
pre-commit install
```

## 🚀 Usage

### Fetch a Known Event (Proof of Concept)

Download strain data for GW150914 (the first gravitational-wave detection),
preprocess it, and generate a Q-transform spectrogram:

```bash
python main.py fetch --event GW150914
```

This will:
- Download H1 strain data from GWOSC
- Apply whitening + bandpass filtering (20–2000 Hz)
- Generate a Q-transform spectrogram
- Save to `data/spectrograms/GW150914_H1.png`

### Batch Scan O4a Data

Scan the first 2 hours of O4a data from LIGO Hanford:

```bash
python main.py scan --detector H1 --hours 2
```

Spectrograms are saved to `data/spectrograms/o4a/H1/` with progress tracking
and fault-tolerant error handling.

### Phase 2 — Feature Extraction (DINOv2 with Registers)

**Why DINOv2-Reg and not SimCLR/MAE:**
- SimCLR on GW waveforms: already published (sidml, 2022)
- Autoencoder anomaly detection on O3 glitches: already published (arXiv:2310.03453)
- DINOv2 frozen on GW spectrograms: **not done — our contribution**
- No labeled data, no GPU training, fully reproducible on a laptop
- Register tokens (ICLR 2024) suppress feature artifacts → cleaner clusters

Extract 384-dim embeddings from spectrograms:

```bash
python main.py encode \
  --input-dir data/spectrograms/o4a/H1/ \
  --output    data/embeddings/o4a_h1.npy \
  --batch-size 32
```

This will:
- Load DINOv2-Reg ViT-S/14 via `torch.hub` (~90 MB on first run)
- Extract L2-normalized 384-dim CLS token embeddings
- Save `.npy` embeddings and companion `.json` metadata

### Phase 3 — Clustering & Novel Glitch Discovery

**Pipeline:** PCA(50D) → UMAP(10D, cosine) → HDBSCAN → Report + Gallery

**Why two UMAP passes?**
- **Clustering pass** (`min_dist=0.0`): packs points tightly for optimal HDBSCAN density detection
- **Visualization pass** (`min_dist=0.1`): produces a readable 2D scatter plot

Clustering is performed on the 10D output (not the 2D visualization).

```bash
python main.py cluster \
  --input  data/embeddings/o4a_h1_6h.npy \
  --output data/clusters/
```

**Outputs:**
- `data/clusters/cluster_report.json` — full structured report with cluster sizes, anomaly flags, and file lists
- `data/clusters/umap_visualization.png` — colored 2D UMAP scatter plot
- `data/clusters/cluster_gallery/` — per-cluster folders with representative spectrogram grids

Small clusters (≤ 10 samples) are automatically flagged as **anomalous** — potential novel glitch classes not yet catalogued by Gravity Spy.

### Phase 3.1 — Extended Scan + Gravity Spy Validation

**Why this step:**
- 344 samples (6h) insufficient for statistical confidence
- Cross-detector replication (H1+L1) rules out local artefacts
- Gravity Spy cross-check prevents false novelty claims

**Extended scan** (~6-8h runtime, run overnight):

```bash
# Extended scan: 48h H1 (offset 6h) + 48h L1 (offset 0h)
python main.py scan-extended

# Re-encode all spectrograms per detector
python main.py encode \
  --input-dir data/spectrograms/o4a/H1/ \
  --output    data/embeddings/o4a_h1_48h.npy

python main.py encode \
  --input-dir data/spectrograms/o4a/L1/ \
  --output    data/embeddings/o4a_l1_48h.npy

# Re-cluster with larger dataset
python main.py cluster \
  --input  data/embeddings/o4a_h1_48h.npy \
  --output data/clusters/h1_48h/
```

**Cross-check anomalous candidates** against the [Gravity Spy](https://gravityspy.org/) glitch database:

```bash
python main.py crosscheck \
  --report   data/clusters/h1_48h/cluster_report.json \
  --metadata data/embeddings/o4a_h1_48h.json \
  --detector H1 \
  --output   data/clusters/h1_48h/gravity_spy_crosscheck.json
```

Each anomalous spectrogram is classified as:
- **CLASSIFIED** — known Gravity Spy glitch (confidence ≥ 0.95)
- **LOW_CONFIDENCE** — uncertain Gravity Spy match (confidence < 0.95)
- **UNCLASSIFIED** — genuine novel candidate (no Gravity Spy match)

### Performance & Parallelization

By default, all scans run sequentially (`--workers 1`).
This works on any machine including laptops.

If you have a multi-core CPU:
```bash
python main.py scan --detector H1 --hours 6 --workers 6
python main.py scan-extended --workers 6
```

Recommended workers = CPU cores - 2 (leave headroom for OS).

Hardware reference (Ryzen 7 7800X3D, 32GB RAM):
- Sequential (`--workers 1`): ~1.5s/segment → 4h for 48h scan
- Parallel (`--workers 6`): ~0.35s/segment → ~55min for 48h scan

Note: GWOSC fetch threads are capped at 4 regardless of `--workers` to respect the public server's rate limits.

## 🗺️ Roadmap

| Phase | Description | Status |
|-------|------------|--------|
| **Phase 1** | Verified preprocessing pipeline + spectrogram generation | ✅ Complete |
| **Phase 2** | Frozen DINOv2-Reg feature extraction (384-dim embeddings) | ✅ Complete |
| **Phase 3** | PCA + UMAP + HDBSCAN clustering & novel glitch discovery | ✅ Complete |
| **Phase 3.1** | Extended scan (48h H1+L1) + Gravity Spy cross-check | 🔄 In Progress |
| **Phase 4** | Novel class candidate reporting + community contribution | 🔲 Planned |

## 🧪 Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=src --cov-report=term-missing
```

Tests use synthetic data and mocked network calls — no internet required.

## 📂 Project Structure

```
gravi-signal-ml/
├── data/                   # Git-ignored data artifacts
│   ├── raw/                # .hdf5 downloads
│   ├── spectrograms/       # PNG + .pt tensors
│   └── embeddings/         # Latent vectors from encoder
├── src/
│   ├── __init__.py
│   ├── data_loader.py      # GWOSC fetch + segment management
│   ├── preprocessor.py     # Whitening, bandpass, Q-transform
│   ├── encoder.py          # Self-supervised backbone (Phase 2)
│   ├── clustering.py       # PCA + UMAP + HDBSCAN pipeline (Phase 3)
│   ├── reporter.py         # Cluster reporting & visualization (Phase 3)
│   └── utils.py            # Config, logging, time conversion
├── notebooks/              # Exploratory Jupyter notebooks
├── tests/                  # Pytest test suite
├── main.py                 # CLI entry point
├── config.yaml             # Central configuration
├── requirements.txt        # Python dependencies
└── .pre-commit-config.yaml # Code quality hooks
```

## 🤝 Contributing

Contributions are welcome! This project is designed to be a community
resource for the gravitational-wave open science community.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Ensure tests pass (`pytest tests/ -v`)
4. Ensure code quality (`ruff check . && mypy src/`)
5. Submit a pull request

## 📚 References

- [GWOSC — Gravitational Wave Open Science Center](https://gwosc.org/)
- [Gravity Spy](https://gravityspy.org/) — supervised glitch classifier
- [gwpy documentation](https://gwpy.github.io/docs/stable/)
- Zevin et al. (2017) — *Gravity Spy: Integrating Advanced LIGO Detector
  Characterization, Machine Learning, and Citizen Science*
- LIGO/Virgo/KAGRA Collaboration — O4a data release (GWTC-4.0)

## 📄 Citation

If you use this code in your research, please cite:

```bibtex
@software{gravi_signal_ml,
  title  = {gravi-signal-ml: Unsupervised Anomaly Detection for Gravitational-Wave Data},
  author = {Luca Cirfeta},
  year   = {2025},
  url    = {https://github.com/lucacirfeta/dante-gravi-signal-ml},
}
```

## 📝 License

This project is licensed under the Apache License 2.0 — see [LICENSE](LICENSE)
for details.

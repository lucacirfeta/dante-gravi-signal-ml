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
│  Encoder        │  Self-supervised CNN (SimCLR/MAE)
│  (Phase 2)      │  ConvNeXt-Tiny → 128-dim embeddings
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

### Extract Embeddings (Phase 2)

```bash
python main.py encode --input-dir data/spectrograms/
```

### Cluster for Novel Classes (Phase 3)

```bash
python main.py cluster --input-dir data/embeddings/
```

## 🗺️ Roadmap

| Phase | Description | Status |
|-------|------------|--------|
| **Phase 1** | Verified preprocessing pipeline + spectrogram generation | ✅ Complete |
| **Phase 2** | Self-supervised feature extraction (SimCLR or MAE) | 🔲 Scaffolded |
| **Phase 3** | Unsupervised clustering (UMAP + HDBSCAN) on O4a data | 🔲 Scaffolded |
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
│   ├── clustering.py       # UMAP + HDBSCAN pipeline (Phase 3)
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

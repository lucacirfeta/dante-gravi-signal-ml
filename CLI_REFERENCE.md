# 📖 CLI Command Guide — gravi-signal-ml

This guide provides a complete and updated list of all available commands in the CLI (`main.py`), complete with descriptions and options for each subcommand.

> **💡 Graphical Interface:** A graphical user interface (Gooey) is available. You can launch it by running `python gui.py`. All CLI options listed below will also be visually configurable through the GUI.

> **🪄 Interactive Wizard:** A step-by-step text wizard is available in the CLI. To launch it, simply run `python main.py` without any parameters. The wizard automatically detects all commands (including any future ones) and guides you through parameter input with smart suggestions (Smart Defaults).

> **📊 Argument Traceability:** All CLI commands automatically print a formatted configuration table displaying the parsed arguments (both user-provided and default values) before execution. This ensures complete traceability of hyper-parameters (e.g., `batch-size`, `k`, `fpr`) in both console output and session `.log` files.

---

## Quick Reference (Most Used Commands)

- **Automatic Scan & Full Analysis:**
  `python main.py scan-extended --workers 6 --full-analysis True`
- **Resume an Interrupted Run:**
  `python main.py scan-extended --session-id <SESSION_ID> --workers 6 --continue-run`
- **Generate Reference Index:**
  `python main.py build-indomain-reference --run O3b --detector H1`
- **Visualize and Update UMAP Report:**
  `python main.py report --session-id <SESSION_ID> --detector H1`

---

## Structural Conventions

### Session ID Convention
Each analytical run is automatically isolated with a unique session identifier (timestamp-based), for example, `20260510_143022`.
All generated files are stored following this structure:
`data/runs/<run>/<session_id>/`

Inside the session folder:
- `{det}_full_report.json` — **single source of truth** per detector (session root)
- `reports/` — raw step outputs (`cluster_report_{det}.json`, `ablation_report_{det}.json`, `stability_report_{det}.json`, `morphcheck_summary_{det}.json`, `{det}_similarity_analysis.json`, `timeslide_report_H1_L1.json`)
- `spectrograms/`, `embeddings/`, `clusters/`, `logs/` — as before

By using the `--session-id` flag, the CLI will automatically infer read/write paths without having to specify them manually.

### Multi-Run Support
The pipeline supports the analysis of different LIGO/Virgo observational runs. Currently supported and selectable runs via the `--run` flag are:
- **O2** (Start: 2016-11-30)
- **O3a** (Start: 2019-04-01)
- **O3b** (Start: 2019-11-01)
- **O4a** (Start: 2023-05-24) *[Default]*

---

## Command Index

1. **Data Acquisition**
   - [`fetch`](#1-fetch) — Download known event
   - [`scan`](#2-scan) — Batch scan
   - [`scan-extended`](#3-scan-extended) — Extended scan (synchronized)
   - [`fetch-raw`](#4-fetch-raw) — Download raw data in HDF5
   - [`patch-production`](#5-patch-production) — Phase 4 Patch-Level Production
   - [`last-gps`](#5b-last-gps) — Retrieve last GPS time

2. **ML Pipeline (Phases 2 and 3)**
   - [`encode`](#6-encode) — Extract DINOv2 embeddings
   - [`explain`](#7-explain) — Generate attention maps for anomaly explainability
   - [`cluster`](#8-cluster) — Execute DPMM or HDBSCAN clustering
   - [`report`](#9-report) — Regenerate UMAP/gallery plots

3. **Analysis & Validation**
   - [`stability`](#10-stability) — Clustering stability analysis
   - [`ablation`](#11-ablation) — Perturbation ablation study
   - [`timeslide`](#13-timeslide) — Coincidences and p-value analysis
   - [`cluster-similarity`](#13b-cluster-similarity) — Subvariant similarity analysis
   - [`run-injection`](#13c-run-injection) — Execute Mock Data Challenge (MDC) injections

4. **Reference Index**
   - [`build-reference`](#14-build-reference) — Build base or in-domain reference index
   - [`download-all-references`](#15b-download-all-references) — Batch download and build all in-domain indexes
   - [`validate-reference`](#16-validate-reference) — Validate index with a real event
   - [`morphcheck`](#17-morphcheck) — Compare anomalies with reference index
   - [`benchmark-clustering`](#18-benchmark-clustering) — Validate unsupervised pipeline with ground truth labels

5. **End-to-End Automation**
    - [`full-analysis`](#19-full-analysis) — Complete automated pipeline
    - [`full-analysis-report`](#19b-full-analysis-report) — Regenerate only the final JSONs of the full analysis

6. **Autopilot & Thresholds**
    - [`calibrate-threshold`](#20-calibrate-threshold) — Calibrate per-class similarity thresholds
    - [`calibrate-loglikelihood`](#21-calibrate-loglikelihood) — Calibrate log-likelihood thresholds for DPMM clusters
    - [`scan-live`](#22-scan-live) — Live scanner: classifies spectrograms as KNOWN/NOVEL

---

## Data Acquisition

### 1. `fetch`
Downloads a known GW event (e.g., GW150914) and extracts a spectrogram. Useful to validate pipeline functionality.

* **Under the Hood (Processing Details):**
  1. Contacts the GWOSC database via the query API to find the strain file corresponding to the requested event and GPS time.
  2. Downloads the strain time series and applies *whitening* to divide the signal by the amplitude spectral density (ASD), thus removing frequency-dependent background noise.
  3. Applies a Butterworth band-pass filter between 20 Hz and 2000 Hz to isolate the most sensitive spectrum of LIGO/Virgo detectors.
  4. Executes the constant Q-transform to generate a logarithmic time-frequency grid.
  5. Resizes the spectrogram to 256x256 pixels with bilinear interpolation and saves it as a PNG with `cividis` colormap.

- `--event` **(Required)**: Event name. Available choices in config, typically: `GW150914`, `GW170817`, `GW231123`.

### 2. `scan`
Scans segments for a **single detector** in a defined period. By including an existing `--session-id`, it automatically resumes from the last processed GPS.

* **Under the Hood (Processing Details):**
  1. Calculates the requested GPS time interval. If `--session-id` is set and the folder already contains spectrograms, it identifies the last written file via regex (`^[A-Z]\d_(\d+)_(\d+)\.png$`) and sets `start_gps` accordingly to allow an automatic restart (*resume*).
  2. Divides the total interval into 32-second segments (standard frame duration).
  3. If `--raw-path` is specified or detected, it looks for locally pre-downloaded 4096-second HDF5 files. If found, it extracts the 32-second portion locally avoiding network requests; otherwise, it downloads data from GWOSC on the fly.
  4. Pre-processes each 32-second segment (whitening, 20-2000 Hz band-pass, Q-transform with config parameters, pixel normalization in `[0, 1]` range).
  5. Saves the resulting PNG spectrogram in `data/runs/<run>/<session_id>/spectrograms/<detector>/`.

- `--detector` **(Required)**: Detector to use. Choices: `H1`, `L1`, `V1`.
- `--run`: Reference observational run. Choices: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--hours`: Hours of scan duration (only for new scans). *Default: from config.yaml*.
- `--workers`: Threads in parallel. 1 = sequential. *Default: `1`*.
- `--session-id`: Unique session ID (e.g., `20260510_143022`). *Default: auto-generated*.
- `--reprocess`: Re-render existing spectrograms with current colormap.
- `--no-cache-raw`: Boolean flag. Disables saving raw HDF5 files in the `data/raw` folder. *Default: `True`* (does not save). Set to `False` to enable saving.
- `--raw-path`: Manual path to a specific raw session. If not specified, it will use the latest available folder in `data/raw/` with the highest GPS.

### 3. `scan-extended`
Automated extended scan of **H1 and L1** simultaneously (Phase 4). Synchronizes the two detectors so they resume from the same GPS in case of a resume. This command also reads 4096s blocks from `data/raw/` by default before falling back to GWOSC.

* **Under the Hood (Processing Details):**
  1. Identifies the spectrogram folders for H1 and L1 for the specified session. In case of resume, it scans the generated spectrograms to find the absolute minimum GPS start to establish the original baseline, computing the target end as `Original Start + Target Hours`. It then finds the last recorded GPS for each detector and selects the *least common minimum* between them to safely resume. This ensures the session precisely completes its original quota of hours and accurately logs the remaining time and progress percentage.
  2. If `--raw-path` is specified explicitly, it parses the `.hdf5` files to determine the total time interval (`min_start` and `max_end`), forcing the scan start and end to the physical limits of the local files and excluding the need to configure `--hours`. If automatically derived, it simply uses the local files to speed up segments that intersect its range without altering the configured start GPS.
  3. Divides the workload in parallel using a `ProcessPoolExecutor` (on Windows with `spawn` multiprocessing), equally dividing the total number of workers between H1 and L1 to optimize the CPU-bound calculation of the Q-transform.
  4. For each 32-second segment, extracts the strain, executes preprocessing (whiten, bandpass, Q-transform), and writes the PNG.
  5. If `--full-analysis` is True, automatically runs the entire embedding, clustering, and validation pipeline on the newly processed data.
  6. If `--continue-run` is enabled, enters a continuous loop (until `--max-iterations` or the reaching of `--stop-date`) to perform incremental scanning phases. If `--full-analysis` is also True, it alternates between incremental scanning and automatic clustering/validation phases.

- `--run`: Observational run. Choices: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--hours`: Override hours per detector relative to yaml config (only for new scans).
- `--workers`: Number of workers (must be an **even number**, e.g. 2, 4, 6, 8). Workers are equally divided between H1 and L1. *Default: `1`*.
- `--session-id`: Session ID. *Default: auto-generated*.
- `--reprocess`: Re-render existing spectrograms with current colormap.
- `--no-cache-raw`: Boolean flag. Disables HDF5 saving. *Default: `True`*.
- `--full-analysis`: Boolean flag. If set to `True`, automatically starts `full-analysis` at the end. *Default: `False`*.
- `--skip-timeslide`: Flag. Skips timeslide analysis in full analysis.
- `--n-runs`: Number of runs for stability analysis. *Default: `20`*.
- `--sequential`: Runs detectors in sequence rather than in parallel.
- `--start-gps`: Provides a fixed start GPS time.
- `--continue-run`: Flag. Enables the continuous scan and synchronized analysis loop (resume loop).
- `--max-iterations`: Maximum iterations for the continuous loop. *Default: `10`*.
- `--stop-date`: Temporal limit beyond which to stop the continuous loop.
- `--raw-path`: Manual path to a specific raw session. If not specified, uses the latest available folder in `data/raw/` with the highest GPS.

### 4. `fetch-raw`
Massive download of strain data (GWOSC) in `.hdf5` format.

* **Under the Hood (Processing Details):**
  1. Resolves the GPS interval of the chosen observational run.
  2. Divides the requested time interval into rigid 4096-second blocks (the default duration set in `--segment-duration`).
  3. Contacts GWOSC via the `gwosc.locate.get_urls` utility to get direct download URLs for HDF5 files.
  4. Launches parallel downloads via a `ThreadPoolExecutor` of network workers (limited to a maximum of 4 threads per detector to avoid IP blocking from the GWOSC server).
  5. Saves the files directly to `data/raw/<gps_start>/` with filename `[Detector]_[gps_start]_[gps_end].hdf5`.
  6. **Smart Resume**: Detects partially completed folders. If `--continue` is used, it will first download the missing hours into the same folder to reach the 144h quota (or `--hours`). If `--loop` is active, it then seamlessly creates the next folders in sequence to download continuously until finished.

- `--detector`: Detector(s). *Default: `H1 L1`*.
- `--workers`: Total number of workers. *Default: `2`*.
- `--run`: Base observational run. *Default: `O4a`*.
- `--hours`: Total hours to download. *Default: read from config.yaml for the specified run*.
- `--start-gps`: Overrides the start GPS time. *Default: read from config.yaml for the specified run*.
- `--session-id`: Alias for `--start-gps`. Specifies the exact folder/GPS to resume from. If combined with `--continue`, it forces the download to start exactly here and loop forward.
- `--output-dir`: Cache output folder. *Default: `data/raw`*.
- `--segment-duration`: Download chunk duration (in seconds). *Default: `4096`*.
- `--no-resume`: Flag. Disables automatic resume.
- `--retry`: Flag. Enables retry with exponential backoff.
- `--continue`: Flag. Continues download from the last GPS folder in data/raw/. Completes incomplete folders before starting new ones. *Default: `False`*.
- `--loop`: Flag. Loops continuously, downloading new blocks (e.g. 144h each) until stopped or `max-iterations` is reached.
- `--max-iterations`: Max loop iterations. *Default: `100`*.

### 5. `patch-production`
Run the Phase 4 Patch-Level Production pipeline directly on raw O4a data.

* **Under the Hood (Processing Details):**
  1. Searches the `data-dir` for HDF5 raw data folders grouped by session.
  2. Spawns `ProcessPoolExecutor` with the specified number of `--workers` to extract raw strain, apply whitening, bandpass filter, and compute Q-transforms entirely on CPU cores.
  3. Preprocessed images are yielded in batches of size `--batch-size`.
  4. The batched images are sent to DINOv2 on GPU, generating embeddings, calculating Top-K L2-normalized MIL vectors, and computing extreme-value p99 threshold anomaly scores against a compressed Vector Quantization (VQ) reference index.
  5. Continuous output is recorded chronologically in an SWMR HDF5 dataset inside `data/production/<session_id>`. Supports seamless `--resume`.

- `--detector` **(Required)**: Detector to use. Choices: `H1`, `L1`.
- `--data-dir`: Directory containing raw HDF5 files. *Default: `data/raw/o4a/`*.
- `--sessions`: List of sessions to process. If empty, processes all folders.
- `--output-dir`: Output directory. *Default: `data/production/`*.
- `--resume`: Flag. Resumes from the last checkpoint written to the HDF5 archive.
- `--k`: Number of top-k patches for MIL vector pooling. *Default: `68`*.
- `--fpr`: False Positive Rate for theoretical GEV thresholding (future use). *Default: `0.01`*.
- `--n-background`: Samples used for empirical threshold calibration. *Default: `500`*.
- `--seed`: Random seed. *Default: `42`*.
- `--workers`: Number of CPU workers for parallel Q-Transform preprocessing. *Default: `8`*.
- `--batch-size`: Number of spectrograms grouped per DINOv2 GPU inference pass. *Default: `32`*.

### 5b. `production-cluster`
Clusters the 384D novel anomalies extracted during `patch-production`. This command operates strictly on the HDF5 output of Phase 4 without applying any PCA bottlenecks to preserve DINOv2 non-linear topology.

* **Under the Hood (Processing Details):**
  1. Opens the `novelties.h5` SWMR archive.
  2. Extracts the `mil_vectors` (384D) and rigorously enforces PyTorch L2-normalization on the entire set.
  3. Executes the Dirichlet Process Mixture Model (`BayesianGaussianMixture`) directly on the 384D space to calculate the topological likelihood of each segment belonging to a new cluster class.
  4. Projects the 384D space down to 2D using UMAP (cosine metric) strictly for visualization purposes.
  5. Saves a comprehensive JSON `cluster_report` mapped to the physical GPS times and a `umap_novelties.png` scatter plot.

- `--input` **(Required)**: Path to the `novelties.h5` file generated by `patch-production`.
- `--output-dir`: Output directory for the cluster report and UMAP plots. If omitted, saves alongside the input file.

### 5c. `patch-analysis` (Meta-Command)
Automated continuous workflow that safely chains `patch-production` $\to$ `production-cluster` $\to$ `production-report` into a zero-click, state-aware pipeline.

* **Under the Hood (Processing Details):**
  1. Intercepts all configuration arguments and logs them globally for absolute traceability.
  2. Spawns the `patch-production` pipeline identically to the standalone command, natively enforcing `--resume`. It maintains state via `checkpoint.txt` and HDF5 SWMR checkpoints.
  3. **State-Aware Resilience:** If a session's checkpoint is marked as `DONE`, the orchestrator skips the heavy DINOv2 processing instantly. If `full_discovery_report_{detector}.md` exists, it skips the entire session, ensuring flawless and rapid execution when resuming massive multi-session runs.
  4. Upon conclusion of each step, it autonomously invokes the `production-cluster` and `production-report` commands sequentially.
  
- *Accepts identical arguments as `patch-production`.*

### 5d. `production-report`
Executes the final Phase 6 and 7 automated validation pipeline to produce the `full_discovery_report_{detector}.md`. It performs cross-validation against the Gravity Spy catalog, calculates topological stability metrics, and generates saliency galleries.

* **Under the Hood (Processing Details):**
  1. Identifies the `novelties.h5` and `cluster_report.json` for the given session.
  2. Executes internal VQ Cosine Similarity Fallback by normalizing and querying the compressed reference background index to map known classes.
  3. Projects the 384D Multiple Instance Learning vectors down to an exact 4D space using UMAP (cosine metric) and calculates the Bootstrap Adjusted Rand Index (ARI, N=20).
  4. Dynamically samples pristine background segments (`Science Mode`) from the GWOSC timeline, and computes the spatial median background.
  5. Computes Ablation studies by extracting the `global_mean` and evaluating the Signal Dilution effect.
  6. Renders Topological Saliency maps for the Top-5 clusters and generates the comprehensive Markdown report.

- `--session-id` **(Required)**: Session ID to evaluate.
- `--detector` **(Required)**: Detector. Choices: `H1`, `L1`.
- `--run`: Search observational run. *Default: `O4a`*.

### 5e. `last-gps`
Returns the most advanced (end) GPS time to resume stopped runs without invoking external servers.

* **Under the Hood (Processing Details):**
  1. Accesses the spectrograms folder `data/runs/<run>/<session_id>/spectrograms/<detector>/`.
  2. Reads the list of saved PNG files and applies the regex pattern `^[H|L|V]1_(\d+)_(\d+)\.png$`.
  3. Extracts the final GPS time `gps_end` from each file.
  4. Determines and prints the maximum value on screen, allowing quick verification of local scan status without relying on network contacts with GWOSC.

- `--detector` **(Required)**: Detector.
- `--session-id` **(Required)**: Session ID to find the directory.
- `--run`: Search observational run. *Default: `O4a`*.

---

## ML Pipeline

### 6. `encode`
Uses the pre-trained DINOv2-Reg model to map spectrograms into high-dimensionality embedding vectors.

* **Under the Hood (Processing Details):**
  1. Loads the `dinov2_vits14_reg` deep learning model (Vision Transformer Small 14-patch with register tokens) via `torch.hub`. Configures all weights as *frozen* in evaluation mode (`eval()`). Register tokens prevent the model from focusing on artifacts in empty/uniform areas of the spectrogram.
  2. Recursively reads PNG files. For each image: converts to RGB, resizes to 518x518 pixels (optimal size for DINOv2), and applies ImageNet statistical normalization (mean/std).
  3. Executes the model forward pass on the available device (CUDA GPU, Apple Silicon MPS, or CPU) with the desired batch size.
  4. Handles Out-Of-Memory (OOM) errors on CUDA: if the GPU saturates, clears the PyTorch cache, temporarily halves the batch size, and automatically retries the extraction.
  5. Extracts the final CLS token from the output and applies L2 normalization (assigning each embedding a norm of 1.0) so that Euclidean distance coincides with cosine distance on a 384-dimensional hypersphere.
  6. Saves the resulting embedding matrix in a `.npy` NumPy file (dimensions `[N, 384]`) and an accompanying JSON metadata file tracking the order of corresponding PNG files.

- `--session-id`: Session ID.
- `--detector`: Detector.
- `--run`: Observational run. *Default: `O4a`*.
- `--input-dir`: Direct folder of `.png` files.
- `--output`: Destination file (`.npy`).
- `--batch-size`: PyTorch batch inference size. *Default: `auto-detect` (CUDA=64, MPS=32, CPU=16).*

### 7. `explain`
[STUB] Generate attention maps for anomaly explainability. (Feature not yet implemented. Stub for Phase 2: DINOv2 Explainability).

### 8. `cluster`
Dynamically clusters the data (DPMM or HDBSCAN), finding any glitch classes and anomalies.

* **Under the Hood (Processing Details):**
  1. **PCA (Principal Component Analysis):** Applies the PCA algorithm to reduce embeddings from 384 dimensions to 50 principal components. This reduces statistical noise and accelerates UMAP execution.
  2. **UMAP Pass A (Clustering):** Reduces vectors from 50D to 10D. Uses specific parameters (`min_dist=0.0`, *cosine* distance metric) forcing data to form extremely concentrated and high geometric density groups, ideal for density-based clustering algorithms.
  3. **Clustering Algorithm:**
     - **DPMM (Dirichlet Process Mixture Model - default):** Executes a variational Gaussian mixture with a Dirichlet process prior. Fully autonomously finds the number of classes by pruning the weights of empty clusters. Computes the log-likelihood of each sample against the mixture and marks samples in the lower tail (e.g. 5th percentile) as individual anomalies. At the cluster level, it aggregates these anomalies: a cluster is marked as *anomalous* if **>50% of its members** have log-likelihoods below the 5th percentile threshold. This criterion is consistent with that used by stability analysis.
     - **HDBSCAN:** Calculates density groups in 10D. Isolates scattered samples as noise (`-1`). Any identified cluster with total size below the set threshold (default 10 or 1% of the dataset) is marked as an *anomalous cluster* (candidate morphological novelties).
  4. **UMAP Pass B (Visualization):** Reduces embeddings to 2D. Uses a `min_dist=0.1` value to graphically distance clusters and allow the creation of clean and highly readable 2D scatter plots.
  5. Writes the results (labels, 2D UMAP, statistics and anomalies list) into a JSON clustering report.

- `--session-id`: Session ID.
- `--detector`: Detector. 
- `--run`: Observational run. *Default: `O4a`*.
- `--input`: Numpy file (`.npy`).
- `--output`: Folder to save plot and JSON.
- `--algorithm`: Clustering algorithm (`dpmm`, `hdbscan`). *Default: `dpmm`*.

### 9. `report`
Regenerates summary image galleries and 2D UMAP plots by loading the JSON resulting from a previous `cluster`.

* **Under the Hood (Processing Details):**
  1. Loads the NumPy embedding file and the clustering report JSON.
  2. Executes the 2D scatter plot based on UMAP-2D coordinates. Colors each point based on its cluster ID and graphically marks glitches identified as anomalies/novelties.
  3. For each identified cluster, samples a subset of representative PNG spectrograms.
  4. Builds an HTML gallery and a grid summary image to allow physicists/analysts to visually inspect waveforms grouped in clusters.

- `--session-id`: Session ID.
- `--detector`: Target detector.
- `--run`: Observational run. *Default: `O4a`*.
- `--embeddings`: Path to embeddings.
- `--report`: Path to JSON.
- `--output-dir`: Custom output folder.
- `--algorithm`: Algorithm used for the data. *Default: `dpmm`*.

---

## Analysis & Validation

### 10. `stability`
Reruns the cluster introducing micro-perturbations to verify robustness (ARI).

* **Under the Hood (Processing Details):**
  1. Executes baseline 50D PCA on the original embeddings.
  2. Starts a cycle of `N` perturbed clustering runs (default 20). For each run:
     - Multiplies parameters `n_neighbors` (UMAP) and `min_cluster_size` (HDBSCAN) by a random factor uniformly extracted in `[0.8, 1.2]`.
     - Varies UMAP's random initialization seed.
     - Executes UMAP-10D and the clustering algorithm (DPMM or HDBSCAN).
  3. Computes the Adjusted Rand Index (ARI) score for each pair of runs. ARI measures the similarity between two partitions, ignoring label permutations.
  4. Computes the overall mean and standard deviation of ARI to provide a quantitative measure of stability (`mean_ari > 0.8` = robust; `mean_ari < 0.5` = unstable).
  5. Computes the frequency with which each sample is labeled as anomalous across all trials. Samples marked as anomalous in at least 80% of total runs constitute the final list of *stable anomalies*.
  6. Generates a JSON report containing statistics and the ARI matrix.

- `--session-id`: Target session ID.
- `--detector`: Detector. *Default: `H1`*.
- `--run`: Observational run. *Default: `O4a`*.
- `--n-runs`: Number of repeated trials. *Default: `20`*.
- `--embeddings`: Input `.npy` path.

### 11. `ablation`
Evaluates the pre-processing impact by mutating images and analyzing the ARI accuracy of various clusters (e.g. grayscale, inverted).

* **Under the Hood (Processing Details):**
  1. Defines 4 visual perturbation conditions:
     - `grayscale`: Transforms the spectrogram to grayscale, zeroing the color information of the colormap.
     - `inverted`: Inverts all pixels to test invariance to positive/negative contrast.
     - `shuffled-intensity`: Multiplies the pixels of each image by a random factor between 0.5 and 1.5 to simulate global intensity variations.
     - `random-baseline`: Replaces DINOv2 vectors with random Gaussian vectors to check behavior in case of total lack of information.
  2. For each modified set, extracts new embeddings with the DINOv2 model.
  3. Executes the standard clustering pipeline on the new perturbed embeddings.
  4. Computes the Adjusted Rand Index (ARI) by comparing the newly obtained partitions with the original baseline partition.
  5. If the `grayscale` set ARI drops below 0.4, raises a warning that the pipeline depends on graphical rendering details rather than strain physics.
  6. Saves a summary report in JSON.

- `--session-id`: Session ID.
- `--detector`: Target detector.
- `--run`: Observational run. *Default: `O4a`*.
- `--embeddings`: Path to baseline `.npy` embedding.
- `--spectrogram-dir`: Path to `.png` spectrograms.
- `--output-dir`: Destination folder.
- `--batch-size`: Batch size for DINOv2. *Default: `auto-detect`.*

### 13. `timeslide`

Estimates the empirical p-value of coincidence between `H1` and `L1` anomalies via random time-shifts. Supports both anomalies from **HDBSCAN clusters** and individual anomalies detected by **DPMM** (`anomalous_samples`). Output is saved automatically.

* **Under the Hood (Processing Details):**
  1. Extracts GPS times of detected anomalies separately for H1 and L1 in the session. The collection integrates both sources:
     - **Anomalous clusters (HDBSCAN):** scans clusters marked as anomalous in the report and collects associated `sample_files`.
     - **Anomalous DPMM samples (`anomalous_samples`):** resolves indices saved in the report against the `files` list of the metadata JSON produced by `encode`.
  2. **Zero-lag Calculation:** Counts the actual number of real coincidences between H1 and L1. Two anomalies coincide if their GPS differ by at most a prefixed window (default 32 seconds, configurable via `--window`). Each segment is paired at most once.
  3. **Time-slide Analysis:** Generates a simulated control background by executing `N` iterations (default 100, configurable via `--iterations`). In each iteration:
     - Applies an artificial time-shift (*time-slide*) to L1 GPS times (randomly chosen among multiples of 100 seconds in the range -5000 to 5000 s, excluding zero). This destroys any coherent physical temporal correlation.
     - Recalculates the number of random coincidences obtained between the original H1 series and the shifted L1 series.
     - Stores the count to build the statistical distribution of the random background.
  4. Computes the mean and standard deviation of the random background distribution.
  5. Computes the **empirical p-value** as the fraction of time-slide runs that recorded a number of random coincidences equal to or greater than the real coincidences (zero-lag). A `p-value < 0.05` indicates that the observed coincidences are statistically significant and not attributable to chance.
  6. Computes the **z-score** and writes the results in `timeslide_report_H1_L1.json`.

- `--session-id`: Unique session ID (automatically resolves all paths). *Alternative to explicit arguments.*
- `--run`: Observational run. *Default: `O4a`*.
- `--metadata-h1` / `--metadata-l1`: Path to JSON metadata produced by `encode` (overrides session-id).
- `--report-h1` / `--report-l1`: Path to JSON cluster report (overrides session-id).
- `--iterations`: Number of time-slides for background estimation. *Default: `100`*. Also configurable in `config.yaml → timeslide.iterations`.
- `--window`: Coincidence window in seconds. *Default: `32`*. Also configurable in `config.yaml → timeslide.window`.

> **💡 Note:** without `--session-id`, the four arguments `--metadata-h1`, `--metadata-l1`, `--report-h1`, `--report-l1` are all required. The `--embeddings-*` arguments are not necessary and have been removed.

### 13b. `cluster-similarity`
Analyzes the distribution of cosine similarities for each cluster compared to the in-domain reference classes.
Useful to determine if an anomalous cluster is genuinely equidistant from many classes (potential NOVEL indicator) or is a subvariant of a known class (systematically higher similarity towards that class).

* **Under the Hood (Processing Details):**
  1. Loads the morphcheck report and cluster_report.
  2. For each cluster, extracts the samples and their similarities toward the top-5 reference classes.
  3. Computes mean similarity, standard deviation, and ratio between top-1 and top-2.
  4. Produces a report indicating the interpretation (Equidistant vs Subvariant) for any NOVEL candidate.

- `--session-id` **(Required)**: Unique session ID.
- `--detector` **(Required)**: Used detector (e.g. `H1`).
- `--run`: Observational run (e.g. `O4a`).
- `--reference`: Path to the `.npz` reference index.

### 13c. `run-injection`
Executes the Mock Data Challenge (MDC) by injecting synthetic transient waveforms directly into the strain data to evaluate the pipeline's detection capability (Recall) at varying Signal-to-Noise Ratios (SNR).

* **Under the Hood (Processing Details):**
  1. Loads background noise segments (null-segments) from the configured session.
  2. Generates or loads synthetic strain waveforms based on specified morphologies (e.g., SineGaussian, Ringdown, SpiralBurst).
  3. Scales the amplitude of the synthetic signal to match the requested matched-filter SNR against the background noise PSD.
  4. Injects the signal into the center of the 32s analysis window.
  5. Processes the injected data through the standard pipeline (whitening, bandpass, Q-transform, DINOv2 embedding).
  6. Compares the resulting embeddings against the `novelty_threshold` to calculate the detection Recall.

- `--session-id` **(Required)**: Unique session ID for background data.
- `--run`: Observational run. *Default: `O4a`*.
- `--detector`: Target detector. *Default: `H1`*.
- `--morphology` **(Required)**: Synthetic morphology to inject.
- `--snr-range`: Range of SNRs to evaluate.

---

## Reference Index

### 14. `build-reference`
Starts the builder by extracting an embeddings index from the Gravity Spy archive or from labeled GPS timestamps (in-domain).

* **Under the Hood (Processing Details):**
  1. (Out-of-Domain) Looks locally for the compressed `.tar.gz` file containing the Gravity Spy dataset. Extracts up to a maximum set number of samples for each glitch class.
  2. (In-Domain) Loads spectrogram files and model predictions for selected sessions, filtering events with classification probability above the critical threshold (default 0.95).
  3. Pre-processes the extracted images and passes them to the DINOv2 encoder to compute 384-dimensional embeddings.
  4. Collects all embedding vectors and relative textual class labels, saving them in a single compressed NumPy file `.npz` (`data/reference/`).

- `--domain` **(Required)**: Choose `in-domain` or `out-of-domain`.
- `--output`: Final destination for `.npz`. Auto-generated for in-domain if omitted.
- `--max-per-class`: Samples extracted from each class. *Default: 50 (OOD), 30 (In-domain)*.
- `--tar-path`: Path to local .tar.gz (for out-of-domain).
- `--detector`: Associated detector (for in-domain). *Default: `H1`*.
- `--run`: Observational run (for in-domain). *Default: `O3b`*.
- `--min-confidence`: Minimum accuracy to include glitches (for in-domain). *Default: `0.95`*.
- `--workers`: Number of Threads (for in-domain). *Default: `1`*.
- `--local-csv`: Local fallback path for Gravity Spy classifications CSV.

### 15b. `download-all-references`
Batch-downloads Gravity Spy classification CSVs from Zenodo and builds in-domain reference indexes for each run/detector combination. Files are saved with the naming convention `indomain_{run}_{detector}.npz` in `data/reference/`. Existing files are skipped (resume support). Downloads are sequential to respect Zenodo rate limits.

```bash
python main.py download-all-references --run O4a --detector H1 L1 V1
python main.py download-all-references --all --detector H1 L1
```

- `--run`: Observing run (e.g. `O4a`). *Required unless `--all` is used.*
- `--all`: Download all available runs (`O2`, `O3a`, `O3b`, `O4a`).
- `--detector`: Detectors to build references for. *Default: `H1 L1 V1`*.
- `--min-confidence`: Minimum `ml_confidence` threshold. *Default: `0.95`*.
- `--max-per-class`: Maximum samples per class. *Default: `30`*.
- `--workers`: Number of parallel workers for GWOSC fetch. *Default: `1`*.

### 16. `validate-reference`
On-the-fly validation via test event.

* **Under the Hood (Processing Details):**
  1. Loads the reference index file `.npz` in memory.
  2. Loads and processes the strain signal for a known event injected as a stress-test (e.g. GW150914).
  3. Computes the DINOv2 embedding vector of the event.
  4. Executes the KNN cosine search against the index to ensure the injected event is correctly associated with its real physical class, confirming the absence of scaling or formatting errors.

- `--reference` **(Required)**: Path to pre-extracted `.npz` index.
- `--test-event`: Event for the stress-test injection. *Default: `GW150914`*.

### 17. `morphcheck`
Uses a reference index (in-domain or standard) to evaluate the identified clusters, labeling each anomaly as NOVEL or KNOWN.

* **Under the Hood (Processing Details):**
  1. Loads the embedding matrix and the `.npz` reference index (or auto-discovers all indexes in `data/reference` if not explicitly provided).
  2. **Cosine KNN Search:** For each sample in the anomalous clusters, computes the matrix product of embeddings (already normalized to norm 1.0) with reference embeddings, obtaining a cosine similarity matrix. Identifies the `K` nearest neighbors (default K=5).
  3. **Novelty Evaluation:**
     - If the maximum cosine similarity with the nearest neighbor is below the novelty threshold (`novelty_threshold`, default 0.85), the sample is classified as **NOVEL** (indicates an anomalous waveform not present in the reference catalog).
     - If the similarity is above the threshold and there is class consensus among the K neighbors (percentage above `consensus_threshold`, default 60%), the event is classified as **KNOWN** (associated to the dominant neighbor class, e.g. Blip).
     - In other cases, the event is cataloged as **AMBIGUOUS**.
  4. Generates a final JSON with classification details for each single analyzed glitch.

- `--embeddings`: Path to Numpy base array file. Required if not using `--session-id`.
- `--report`: Path to cluster report JSON. Required if not using `--session-id`.
- `--reference`: `.npz` index for comparison. If omitted, runs auto-discovery across all references in `data/reference/`.
- `--output`: Path for the outgoing JSON file. Required if not using `--session-id` and not using auto-discovery.
- `--session-id`: Session identifier to resolve paths automatically. Requires `--detector`.
- `--detector`: Associated detector. Required if using `--session-id`.
- `--run`: Associated run. *Default: `O4a`*.

### 18. `benchmark-clustering`
Benchmarks the unsupervised clustering pipeline using a reference index as ground truth for metric calculation (ARI, AMI).

* **Under the Hood (Processing Details):**
  1. Extracts embeddings and respective known classes from the reference `.npz` file.
  2. Applies the selected unsupervised clustering algorithm (DPMM or HDBSCAN) directly on these vectors, ignoring real labels.
  3. Compares the generated partitions by the algorithm with the real ground truth labels.
  4. Computes formal metrics for partition comparison: **Adjusted Rand Index (ARI)** and **Adjusted Mutual Information (AMI)**.
  5. Saves scores in a JSON report, useful for validating modifications or optimizations made to the clustering code.

- `--reference`: Path to `.npz` reference index. *Default: `data/reference/indomain_O4a_H1.npz`*.
- `--min-samples-per-class`: Removes classes with less than specified samples. *Default: `10`*.
- `--output`: Path to save the benchmark report JSON. *Default: `data/reference/benchmark_report.json`*.
- `--algorithm`: Clustering algorithm to use. *Default: `dpmm`*.

---

## End-to-End Automation

### 19. `full-analysis`
Automates the entire analysis workflow (Encode, Cluster, Morphcheck, Ablation, Stability and Timeslide). By default, analyzes H1 and L1 in parallel.

* **Under the Hood (Processing Details):**
  1. Verifies which detectors are present in the session. By default, starts processing for H1 and L1.
  2. Executes the **`encode`** command to generate `.npy` embedding matrices and `.json` metadata for each detector.
  3. Executes the **`cluster`** command to apply dimensionality reduction (PCA + UMAP) and clustering (DPMM or HDBSCAN).
  4. Executes the **`morphcheck`** command comparing obtained embeddings with the in-domain reference index to determine the novelty status (KNOWN/NOVEL) of each glitch.
  5. Launches **`ablation`** analysis on each detector to test dependence on graphical settings.
  6. Executes **`stability`** analysis introducing perturbations to verify the structural robustness of discovered classes.
  7. If not explicitly disabled via `--skip-timeslide`, executes random coincidence calculation via **`timeslide`** comparing H1 and L1 to estimate the empirical p-value of physical coincidences.
  8. Stores all graphical and textual reports within the current session directory.

- `--session-id` **(Required)**: ID of the session to analyze.
- `--detector`: One or more detectors (e.g. `--detector H1 L1`). If omitted, automatically infers detectors in the session.
- `--run`: Observational run. *Default: `O4a`*.
- `--skip-timeslide`: Flag. Forces exclusion of timeslide.
- `--n-runs`: Number of runs for stability analysis. *Default: `20`*.
- `--sequential`: Sequential execution of detectors.
- `--algorithm`: Clustering algorithm (`dpmm`, `hdbscan`). *Default: `dpmm`*.

### 19b. `full-analysis-report`
Regenerates only the final JSONs of the full-analysis by aggregating information from JSON files of various steps (clustering, ablation, etc.) for the detectors in the current session.

* **Under the Hood (Processing Details):**
  1. Identifies report files for the specified detectors inside `reports/` (with automatic fallback to legacy sub-folders for backward compatibility).
  2. Re-reads and compiles `cluster_report_{det}.json`, `ablation_report_{det}.json`, `stability_report_{det}.json`, `morphcheck_summary_{det}.json`, etc. into a single `{det}_full_report.json` at the **session root**.

- `--session-id` **(Required)**: Session ID.
- `--run`: Observational run. *Default: `O4a`*.

---

## Autopilot

The Autopilot commands operate in a **completely separate** way from the standard pipeline (`data/runs/`). All outputs are written to `data/autopilot/`.

### 20. `calibrate`
Calibrates anomaly thresholds (either `cosine` per-class similarity thresholds or `loglikelihood` DPMM anomaly threshold) from the in-domain reference index.

* **Under the Hood (Processing Details):**
  - **Cosine**: Samples up to 200 intra-class pairs, computes cosine similarity, and saves the N-th percentile as the minimum limit.
  - **Loglikelihood**: Executes PCA and UMAP, fits a Bayesian Gaussian Mixture (DPMM) with 25 components, computes log-likelihood for each sample, and sets threshold based on the requested percentile.

```bash
python main.py calibrate --method cosine --reference data/reference/indomain_O4a_H1.npz --percentile 5
python main.py calibrate --method loglikelihood --reference data/reference/indomain_O4a_H1.npz --percentile 5
```

- `--method` **(Required)**: Method to calibrate. Choices: `cosine`, `loglikelihood`.
- `--reference`: Path to `.npz` reference index. *Default: auto-resolved*.
- `--percentile`: Percentile threshold. *Default: 5*.
- `--output`: Destination JSON path.

### 22. `scan-live`
Autopilot scanner with producer-consumer architecture. Works in 4096s blocks where a producer downloads the 4096s HDF5 to `tmp/`, internally processes 128 segments of 32s each (`whiten -> bandpass -> q-transform`), and the consumer evaluates them by classifying each spectrogram as KNOWN/AMBIGUOUS/NOVEL using DINOv2 + per-class thresholds. Deletes temporary HDF5s and PNGs in real time except for NOVELs.

* **Under the Hood (Processing Details):**
  1. **Producer Thread:** Downloads 4096-second HDF5 files from GWOSC in parallel to a temporary working folder `tmp/`. Extracts the 128 32-second segments, locally computing whiten, bandpass and Q-transform in memory to produce temporary images.
  2. **Consumer Thread:** Receives paths of temporary frames as soon as they are completed. For each of them:
     - Computes the 384-dimensional embedding vector via the DINOv2 model.
     - Computes cosine similarity with all glitches from the in-domain reference index (`.npz`).
     - Executes comparison against the **calibrated per-class thresholds** (loaded from `thresholds.json`). If the maximum recorded similarity with the most affine glitch class is *below* the critical threshold calibrated for that specific class, the frame is marked as **NOVEL** (uncatalogued anomaly).
  3. **Disk Space Cleanup:** To minimize disk space occupied by continuous scanning, immediately deletes raw HDF5 files and PNG images of glitches classified as `KNOWN`. Permanently saves to disk only information relating to novelties (**NOVEL**), including PNG images and `.npy` embedding vectors.
  4. Writes the trace of each single event to a structured log file `metadata.jsonl`.
  5. At the end of the scan, if the total number of detected NOVEL glitches exceeds the set threshold (default `--min-novel 10`), it alerts the user by displaying a prompt to run the standard `full-analysis` pipeline to group and scientifically analyze the newly detected class of anomalies.

```bash
python main.py scan-live --detector H1 --run O4a --workers 4
python main.py scan-live --detector H1 --run O4a --session-id autopilot_20260516_120000 --workers 4 --min-novel 10
```

- `--detector` **(Required)**: Detector to use. Choices: `H1`, `L1`, `V1`.
- `--run`: Observational run. Choices: `O2`, `O3a`, `O3b`, `O4a`. *Default: `O4a`*.
- `--workers`: Parallel producer threads for GWOSC fetch. *Default: `4`*.
- `--session-id`: Session ID. *Default: `autopilot_{timestamp}`*.
- `--min-novel`: Minimum NOVEL threshold to suggest clustering. *Default: `10`*.
- `--reference`: Path to `.npz` reference index. *Default: `data/reference/indomain_O4a_H1.npz`*.
- `--hours`: Scan duration override in hours. *Default: from `run_config`*.

Output structure:
```
data/autopilot/
├── reference/
│   └── thresholds.json
└── <session_id>/
    ├── tmp/                     ← Temporary PNGs, deleted after processing
    ├── novel/                   ← PNG + .npy embedding NOVEL
    ├── metadata.jsonl           ← One JSON record per processed spectrogram
    └── report.json              ← Final report
```

`metadata.jsonl` record format:
```json
{"gps_start": 1369211232, "gps_end": 1369211264, "status": "NOVEL", "top_label": "Low_Frequency_Lines", "top_similarity": 0.743, "threshold_used": 0.812}
```

If NOVEL ≥ `--min-novel`, the command suggests using the standard pipeline:
```
Ready for clustering — use standard pipeline:
  python main.py full-analysis --session-id <session_id> --run <run>
```

---

## Standalone Tools

### `live_monitor.py`
A realtime UMAP dashboard designed for physical exhibitions, expos, and presentations. It safely hooks into the Phase 4 `patch-production` ongoing SWMR (`Single Writer Multiple Reader`) HDF5 database to generate a live, updating map of detected anomalies without interrupting the main processing pipeline.

* **Under the Hood (Processing Details):**
  1. Opens the target `.h5` file in read-only SWMR mode (`swmr=True`).
  2. Waits for new vectors (`NOVEL` transient embeddings) to be appended by the backend process.
  3. Every `interval` seconds, if at least `min-update` new glitches were detected, computes a 2D UMAP projection dynamically.
  4. Renders a dark-themed scatter plot highlighting the topological clusters and extreme novelty scores.
  5. Includes a self-explanatory legend suitable for public displays.

```bash
python live_monitor.py --file data/production/<session_id>/novelties_<session_id>_L1.h5 --interval 5 --min-update 5
```

- `--file` **(Required)**: Path to the target `.h5` file generated by `patch-production`.
- `--interval`: Refresh interval in seconds. *Default: `5.0`*.
- `--min-update`: Minimum new points required to trigger an expensive UMAP recalculation. *Default: `5`*.

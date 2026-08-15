"""GW-spectrogram autoencoder comparator for the coherent DANTE stress pool.

The comparator is trained from scratch, separately for H1 and L1, on
candidate-vetoed O4a Q-transform backgrounds.  It receives the same 32x32
log-power features used by the classical PCA control and scores exactly the
same 160 near-boundary candidates.  The endpoint is agreement with the DANTE
ROBUST-versus-AMBIGUOUS disposition, not physical glitch-class accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

from src.pipeline_v2_production.pca_baseline import _features
from src.pipeline_v3_multiscale.norm_leakage.common import raw_qgram

AGG = Path("data/production/aggregated")
REP = "idxq4-64_queryq4-64"
PCA_RESULT = AGG / f"pca_baseline_o4a_{REP}.json"
TAXONOMY = AGG / f"Master_Taxonomy_O4a_{REP}.csv"
OUTPUT = AGG / f"gw_autoencoder_baseline_o4a_{REP}.json"
SCORES_OUTPUT = AGG / f"gw_autoencoder_baseline_scores_o4a_{REP}.csv"
SEEDS = (42, 314159, 271828)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_split(
    n_items: int,
    *,
    validation_fraction: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    if n_items < 4 or not 0 < validation_fraction < 0.5:
        raise ValueError("Need at least four items and 0 < validation_fraction < 0.5")
    rng = np.random.default_rng(seed)
    order = rng.permutation(n_items)
    n_validation = max(1, int(round(n_items * validation_fraction)))
    return np.sort(order[n_validation:]), np.sort(order[:n_validation])


class ConvAutoencoder:
    """Small nonlinear autoencoder trained only on GW Q-transform images."""

    def __new__(cls, latent_dim: int = 16):
        import torch
        from torch import nn

        class _Model(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.encoder_conv = nn.Sequential(
                    nn.Conv2d(1, 8, 3, stride=2, padding=1),
                    nn.ReLU(),
                    nn.Conv2d(8, 16, 3, stride=2, padding=1),
                    nn.ReLU(),
                    nn.Conv2d(16, 16, 3, stride=2, padding=1),
                    nn.ReLU(),
                )
                self.encoder_linear = nn.Linear(16 * 4 * 4, latent_dim)
                self.decoder_linear = nn.Linear(latent_dim, 16 * 4 * 4)
                self.decoder_conv = nn.Sequential(
                    nn.ConvTranspose2d(16, 16, 4, stride=2, padding=1),
                    nn.ReLU(),
                    nn.ConvTranspose2d(16, 8, 4, stride=2, padding=1),
                    nn.ReLU(),
                    nn.ConvTranspose2d(8, 1, 4, stride=2, padding=1),
                )

            def forward(self, values):
                encoded = self.encoder_conv(values).flatten(1)
                latent = self.encoder_linear(encoded)
                decoded = self.decoder_linear(latent).reshape(-1, 16, 4, 4)
                return self.decoder_conv(decoded)

        return _Model()


def _set_deterministic(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False


def fit_autoencoder(
    background: np.ndarray,
    query: np.ndarray,
    *,
    seed: int,
    epochs: int = 120,
    patience: int = 15,
    batch_size: int = 64,
    device: str = "cuda",
    latent_dim: int = 16,
) -> dict:
    import torch
    from torch import nn

    values = np.asarray(background, dtype=np.float32)
    queries = np.asarray(query, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != 1024 or queries.shape[1] != 1024:
        raise ValueError("Autoencoder inputs must be flattened 32x32 features")
    if not np.isfinite(values).all() or not np.isfinite(queries).all():
        raise ValueError("Autoencoder inputs must be finite")
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
    _set_deterministic(seed)
    train_idx, validation_idx = deterministic_split(
        len(values), validation_fraction=0.2, seed=seed
    )
    mean = values[train_idx].mean(axis=0, dtype=np.float64).astype(np.float32)
    scale = values[train_idx].std(axis=0, dtype=np.float64).astype(np.float32)
    scale[scale < 1e-5] = 1.0

    def tensor(data: np.ndarray) -> torch.Tensor:
        normalized = (data - mean) / scale
        return torch.from_numpy(normalized.reshape(-1, 1, 32, 32)).to(device)

    train = tensor(values[train_idx])
    validation = tensor(values[validation_idx])
    query_tensor = tensor(queries)
    model = ConvAutoencoder(latent_dim=latent_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    loss_function = nn.MSELoss()
    generator = torch.Generator(device="cpu").manual_seed(seed)
    best_loss = float("inf")
    best_state = None
    stale = 0
    history: list[float] = []
    for _ in range(int(epochs)):
        model.train()
        order = torch.randperm(len(train), generator=generator)
        for start in range(0, len(train), int(batch_size)):
            batch = train[order[start : start + int(batch_size)].to(device)]
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(batch), batch)
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            validation_loss = float(loss_function(model(validation), validation).cpu())
        history.append(validation_loss)
        if validation_loss < best_loss - 1e-7:
            best_loss = validation_loss
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= int(patience):
                break
    if best_state is None:
        raise RuntimeError("Autoencoder training produced no finite checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        validation_scores = ((model(validation) - validation) ** 2).flatten(1).mean(1).cpu().numpy()
        query_scores = ((model(query_tensor) - query_tensor) ** 2).flatten(1).mean(1).cpu().numpy()
    return {
        "query_scores": query_scores.astype(np.float64),
        "validation_scores": validation_scores.astype(np.float64),
        "train_indices": train_idx,
        "validation_indices": validation_idx,
        "best_validation_loss": best_loss,
        "epochs_completed": len(history),
        "device": device,
    }


def _encode_background_from_ledger(
    detector: str,
    *,
    n_background: int,
) -> tuple[np.ndarray, Path, Path]:
    from gwpy.timeseries import TimeSeries

    from src.core.preprocessor import extract_clean_subwindow, whiten_context

    threshold_doc = json.loads(
        (AGG / f"dsd_thresholds_o4a_{REP}.json").read_text(encoding="utf-8")
    )
    source_ledger = Path(threshold_doc["thresholds"][detector]["background_ledger_path"])
    source = pd.read_csv(source_ledger).sort_values(
        ["source_start", "gps_start"], kind="stable"
    )
    per_block = 10
    n_blocks = int(np.ceil(n_background / per_block))
    grouped = [
        group for _, group in source.groupby("source_path", sort=False)
        if len(group) >= per_block
    ]
    if len(grouped) < n_blocks:
        raise RuntimeError(
            f"Only {len(grouped)} complete raw blocks for {n_blocks} requested"
        )
    chosen_blocks = np.linspace(0, len(grouped) - 1, n_blocks, dtype=int)
    selected_parts = []
    remaining = n_background
    for block_index in chosen_blocks:
        group = grouped[int(block_index)]
        take = min(per_block, remaining)
        row_indices = np.linspace(0, len(group) - 1, take, dtype=int)
        selected_parts.append(group.iloc[row_indices])
        remaining -= take
    if remaining != 0:
        raise RuntimeError(f"Background selection is short by {remaining} windows")
    selected = pd.concat(selected_parts, ignore_index=True).sort_values(
        ["gps_start"], kind="stable"
    ).reset_index(drop=True)
    selected["sampling_strategy"] = (
        "run_spanning_complete_raw_blocks_within_block_even_spacing"
    )
    selected.insert(0, "selection_ordinal", np.arange(len(selected), dtype=int))
    ledger = AGG / f"gw_autoencoder_background_{detector}_o4a_{REP}_n{n_background}_ledger.csv"
    cache = AGG / f"gw_autoencoder_background_{detector}_o4a_{REP}_n{n_background}.npz"
    selected.to_csv(ledger, index=False)
    ledger_hash = file_sha256(ledger)
    if cache.exists():
        with np.load(cache, allow_pickle=False) as saved:
            if str(saved["ledger_sha256"]) == ledger_hash:
                features = saved["features"]
                if features.shape == (n_background, 1024) and np.isfinite(features).all():
                    return features.astype(np.float32), cache, ledger

    # The calibration ledger records the immutable raw block for each window.
    # Read each 4096 s HDF5 block once; reopening it for every 40 s crop is the
    # dominant cost and provides no scientific benefit.
    feature_rows: dict[int, np.ndarray] = {}
    for source_path, group in selected.groupby("source_path", sort=True):
        block_path = Path(str(source_path))
        if not block_path.is_file():
            raise FileNotFoundError(block_path)
        block = TimeSeries.read(block_path)
        if int(round(float(block.sample_rate.value))) != 4096:
            block = block.resample(4096)
        for row in group.itertuples(index=False):
            start, end = float(row.gps_start), float(row.gps_end)
            context = block.crop(start - 4.0, end + 4.0)
            whitened, _ = whiten_context(context, start, end, pad=4.0)
            clean = extract_clean_subwindow(whitened, start, end)
            feature_rows[int(row.selection_ordinal)] = _features(
                raw_qgram(clean, qrange=(4, 64))
            )
    if set(feature_rows) != set(range(n_background)):
        raise RuntimeError(f"Incomplete {detector} background encoding")
    array = np.asarray(
        [feature_rows[index] for index in range(n_background)], dtype=np.float32
    )
    if array.shape != (n_background, 1024) or not np.isfinite(array).all():
        raise RuntimeError(f"Invalid {detector} background feature matrix {array.shape}")
    np.savez_compressed(
        cache,
        features=array,
        detector=np.asarray(detector),
        ledger_sha256=np.asarray(ledger_hash),
        representation=np.asarray(REP),
        qrange=np.asarray([4, 64]),
    )
    return array, cache, ledger


def _auc(scores: np.ndarray, labels: np.ndarray) -> float:
    from scipy.stats import mannwhitneyu

    positive = scores[labels]
    negative = scores[~labels]
    return float(
        mannwhitneyu(positive, negative, alternative="two-sided").statistic
        / (len(positive) * len(negative))
    )


def run(*, n_background: int, epochs: int, device: str) -> dict:
    from scipy.stats import spearmanr

    pca_result = json.loads(PCA_RESULT.read_text(encoding="utf-8"))
    threshold_path = AGG / f"dsd_thresholds_o4a_{REP}.json"
    threshold_doc = json.loads(threshold_path.read_text(encoding="utf-8"))
    candidate_cache = Path(pca_result["candidate_feature_cache"])
    with np.load(candidate_cache, allow_pickle=False) as saved:
        candidate_features = saved["cand_feat"].astype(np.float32)
        candidate_keys = saved["candidate_keys"].astype(str)
    taxonomy = pd.read_csv(TAXONOMY)
    taxonomy["candidate_key"] = [
        f"{detector}:{float(gps):.0f}"
        for detector, gps in zip(taxonomy["detector"], taxonomy["gps_start"])
    ]
    lookup = taxonomy.set_index("candidate_key")
    if not lookup.index.is_unique:
        raise RuntimeError("Taxonomy candidate keys are not unique")
    candidates = lookup.loc[candidate_keys].reset_index()
    candidates["feature_row"] = np.arange(len(candidates), dtype=int)
    class_column = "robustness_class_idxq4_64_queryq4_64"
    score_column = "native_score_idxq4_64_queryq4_64"
    if set(candidates[class_column]) != {"ROBUST", "AMBIGUOUS"}:
        raise RuntimeError("Comparator pool must contain only ROBUST and AMBIGUOUS")

    percentile_by_seed = np.full((len(SEEDS), len(candidates)), np.nan, dtype=np.float64)
    raw_by_seed = np.full_like(percentile_by_seed, np.nan)
    training: dict[str, dict] = {}
    background_sources: dict[str, dict] = {}
    for detector in ("H1", "L1"):
        background, cache, ledger = _encode_background_from_ledger(
            detector, n_background=n_background
        )
        mask = candidates["detector"].astype(str).to_numpy() == detector
        query = candidate_features[mask]
        training[detector] = {}
        for seed_index, seed in enumerate(SEEDS):
            fit = fit_autoencoder(
                background,
                query,
                seed=seed,
                epochs=epochs,
                device=device,
            )
            validation_sorted = np.sort(fit["validation_scores"])
            percentiles = np.searchsorted(
                validation_sorted, fit["query_scores"], side="right"
            ) / (len(validation_sorted) + 1.0)
            percentile_by_seed[seed_index, mask] = percentiles
            raw_by_seed[seed_index, mask] = fit["query_scores"]
            training[detector][str(seed)] = {
                "best_validation_loss": float(fit["best_validation_loss"]),
                "epochs_completed": int(fit["epochs_completed"]),
                "n_train": int(len(fit["train_indices"])),
                "n_validation": int(len(fit["validation_indices"])),
                "device": str(fit["device"]),
            }
        background_sources[detector] = {
            "feature_cache": str(cache),
            "feature_cache_sha256": file_sha256(cache),
            "selection_ledger": str(ledger),
            "selection_ledger_sha256": file_sha256(ledger),
            "upstream_calibration_ledger": threshold_doc["thresholds"][detector][
                "background_ledger_path"
            ],
            "upstream_calibration_ledger_sha256": file_sha256(
                threshold_doc["thresholds"][detector]["background_ledger_path"]
            ),
            "n_background": int(len(background)),
        }

    if not np.isfinite(percentile_by_seed).all():
        raise RuntimeError("Comparator produced incomplete percentile scores")
    mean_score = percentile_by_seed.mean(axis=0)
    is_robust = candidates[class_column].to_numpy() == "ROBUST"
    dante_score = candidates[score_column].to_numpy(dtype=float)
    detector_values = candidates["detector"].astype(str).to_numpy()
    metrics = {
        "pooled": {
            "auc_robust_vs_ambiguous": _auc(mean_score, is_robust),
            "spearman_with_dante": float(spearmanr(mean_score, dante_score).statistic),
        },
        "by_detector": {},
        "auc_by_seed": {},
    }
    for detector in ("H1", "L1"):
        mask = detector_values == detector
        metrics["by_detector"][detector] = {
            "auc_robust_vs_ambiguous": _auc(mean_score[mask], is_robust[mask]),
            "spearman_with_dante": float(
                spearmanr(mean_score[mask], dante_score[mask]).statistic
            ),
        }
    for seed_index, seed in enumerate(SEEDS):
        metrics["auc_by_seed"][str(seed)] = _auc(
            percentile_by_seed[seed_index], is_robust
        )

    score_table = candidates[
        ["candidate_key", "gps_start", "detector", class_column, score_column]
    ].copy()
    score_table["autoencoder_percentile_mean"] = mean_score
    for seed_index, seed in enumerate(SEEDS):
        score_table[f"autoencoder_percentile_seed_{seed}"] = percentile_by_seed[seed_index]
        score_table[f"autoencoder_mse_seed_{seed}"] = raw_by_seed[seed_index]
    score_table.to_csv(SCORES_OUTPUT, index=False)

    result = {
        "schema_version": 1,
        "status": "complete",
        "experiment": "gw_autoencoder_baseline",
        "scope": (
            "Detector-specific nonlinear autoencoder trained from scratch on "
            "O4a Q-transform backgrounds and evaluated on the same 160 "
            "near-boundary candidates as the PCA/energy controls. Agreement "
            "with DANTE dispositions is not physical classification accuracy."
        ),
        "representation": REP,
        "architecture": "conv-8-16-16-latent16-16-16-8",
        "input": "32x32 log1p Q-transform power, Q in [4,64]",
        "detector_specific_training": True,
        "seeds": list(SEEDS),
        "n_candidates": int(len(candidates)),
        "candidate_class_counts": {
            label: int(count) for label, count in candidates[class_column].value_counts().items()
        },
        "metrics": metrics,
        "training": training,
        "sources": {
            "thresholds": {
                "path": str(threshold_path),
                "sha256": file_sha256(threshold_path),
            },
            "taxonomy": {"path": str(TAXONOMY), "sha256": file_sha256(TAXONOMY)},
            "candidate_feature_cache": {
                "path": str(candidate_cache),
                "sha256": file_sha256(candidate_cache),
            },
            "backgrounds": background_sources,
            "scores": {"path": str(SCORES_OUTPUT), "sha256": file_sha256(SCORES_OUTPUT)},
        },
    }
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-background", type=int, default=650)
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args()
    result = run(
        n_background=args.n_background,
        epochs=args.epochs,
        device=args.device,
    )
    print(json.dumps(result["metrics"], indent=2))
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()

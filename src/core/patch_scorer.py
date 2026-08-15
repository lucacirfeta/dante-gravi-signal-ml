import hashlib
import logging
from pathlib import Path
import time
from typing import Mapping

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from src.core.encoder import build_dinov2_transform
from src.core.artifact_manifest import resolve_reference_index
from src.core.index_contract import sha256_file
from src.core.model_loader import load_dinov2_model
from src.core.utils import get_device, setup_logger

logger = setup_logger(__name__)

class PatchScorer:
    """GPU-bound scorer for the Patch-Level production pipeline.
    
    Loads frozen DINOv2 and the reference background index.
    Calculates empirical thresholds and scores segments via Patch-Level MIL.
    """
    def __init__(
        self,
        reference_index_path: str | Path,
        device: str | torch.device | None = None,
        k: int = 68,
        k_ablations: list[int] | None = None,
        fpr: float = 0.01,
        n_background: int = 500,
        seed: int = 42,
        verify_md5: bool = True,
        expected_sha256: str | None = None,
        artifact_manifest_path: str | Path | None = None,
        model: torch.nn.Module | None = None,
    ):
        self.device = torch.device(device) if device else get_device()
        self.k = k
        self.k_ablations = k_ablations or []
        self.fpr = fpr
        self.n_background = n_background
        self.seed = seed
        self.reference_index_path = Path(reference_index_path)
        self.expected_sha256 = expected_sha256
        self.artifact_manifest_path = artifact_manifest_path
        
        # 1. Immutable index verification. ``verify_md5`` is retained as a
        # backward-compatible argument name; verification is SHA-256 based.
        if verify_md5:
            self._verify_md5()
        else:
            self.reference_sha256 = sha256_file(self.reference_index_path)
            self.reference_md5 = self._legacy_md5()
            self.index_integrity_verified = False
            self.index_artifact_id = None
            logger.warning(
                "Reference index integrity verification explicitly disabled: %s",
                self.reference_index_path,
            )
        
        # 2. Load Centroids
        with np.load(self.reference_index_path, allow_pickle=False) as data:
            centroids_np = np.asarray(data["embeddings"], dtype=np.float32)
        
        # Expected shape constraint (N_centroids, 384)
        if centroids_np.ndim != 2 or centroids_np.shape[1] != 384:
            raise RuntimeError(f"Expected reference index shape (N, 384), got {centroids_np.shape}")
        if verify_md5 and self.reference_index_spec.n_centroids >= 0:
            expected_shape = (
                self.reference_index_spec.n_centroids,
                self.reference_index_spec.embedding_dim,
            )
            if centroids_np.shape != expected_shape:
                raise RuntimeError(
                    f"Reference index shape {centroids_np.shape} violates "
                    f"manifest contract {expected_shape}"
                )
            
        self.centroids = torch.tensor(centroids_np, device=self.device, dtype=torch.float32)
        # Explicit L2 normalization
        self.centroids = F.normalize(self.centroids, p=2, dim=-1)
        
        # 3. Load DINOv2
        self.model = model
        if self.model is None:
            self.model = load_dinov2_model(self.device)
        self.model.eval()
        for param in self.model.parameters():
            param.requires_grad = False
        self.model.to(self.device)
        
        # 4. Transform
        self.transform = build_dinov2_transform()
        
        logger.info(f"PatchScorer initialized on {self.device}. k={self.k}, FPR={self.fpr}")
        
    def _legacy_md5(self) -> str:
        hash_md5 = hashlib.md5()
        with open(self.reference_index_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _verify_md5(self):
        """Verify the per-index SHA-256 contract (legacy method name)."""
        self.reference_index_spec = resolve_reference_index(
            self.reference_index_path,
            manifest_path=self.artifact_manifest_path,
        )
        manifest_sha256 = self.reference_index_spec.sha256
        if (
            self.expected_sha256 is not None
            and self.expected_sha256.lower() != manifest_sha256
        ):
            raise RuntimeError(
                "Caller SHA-256 and artifact manifest disagree for "
                f"{self.reference_index_path}: {self.expected_sha256} != "
                f"{manifest_sha256}"
            )
        actual_sha256 = sha256_file(self.reference_index_path)
        if actual_sha256 != manifest_sha256:
            raise RuntimeError(
                "SHA-256 mismatch for reference index! Expected "
                f"{manifest_sha256}, got {actual_sha256}"
            )
        self.reference_sha256 = actual_sha256
        self.reference_md5 = self._legacy_md5()
        self.index_integrity_verified = True
        self.index_artifact_id = self.reference_index_spec.artifact_id
        logger.info(
            "Reference SHA-256 verified: %s (%s)",
            self.reference_sha256,
            self.index_artifact_id,
        )

    @torch.no_grad()
    def calibrate_threshold(self, background_spectrograms: list[np.ndarray], batch_size: int = 32) -> tuple[float, np.ndarray, dict]:
        """Calibrates threshold empirically (p99) on background samples."""
        if len(background_spectrograms) < self.n_background:
            logger.warning(f"Calibration expected {self.n_background} samples, got {len(background_spectrograms)}")
            
        all_novelty_scores = []
        import gc
        for i in range(0, len(background_spectrograms), batch_size):
            batch = background_spectrograms[i:i+batch_size]
            results = self.score_spectrogram(batch, threshold=1.0) # threshold 1.0 ensures is_novel=False
            for res in results:
                all_novelty_scores.append(res["novelty_score"])
                
            # Explicit garbage collection to prevent DINOv2 VRAM fragmentation
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
        scores_np = np.array(all_novelty_scores, dtype=np.float32)
        
        # Empirical percentile direct computation (Correction #3 implies no GEV)
        percentile_target = (1.0 - self.fpr) * 100.0
        threshold = float(np.percentile(scores_np, percentile_target))
        
        # GEV fitting on bulk population is a mathematical fallacy according to EVT.
        # We strictly avoid it and set parameters to None to prevent downstream reporting of invalid metrics.
        gev_params = {"mu": None, "sigma": None, "xi": None}
        
        logger.info("[CALIBRATION] n_background: %d", len(background_spectrograms))
        logger.info("[CALIBRATION] novelty_score mean: %.4f", scores_np.mean())
        logger.info("[CALIBRATION] novelty_score std:  %.4f", scores_np.std())
        logger.info("[CALIBRATION] threshold (p%d):    %.4f", int(percentile_target), threshold)
        logger.info("[CALIBRATION] method: empirical_percentile only (GEV strictly rejected)")
        
        return threshold, scores_np, gev_params

    @torch.no_grad()
    def encode_patch_tokens(
        self,
        spectrogram_arrays: list[np.ndarray],
        *,
        timings: dict[str, float] | None = None,
    ) -> torch.Tensor:
        """Encode images once into normalized DINOv2 patch tokens.

        The returned tensor remains on ``self.device`` and may be scored against
        multiple compatible reference indexes without another model forward.
        """
        def clock() -> float:
            if timings is not None and self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            return time.perf_counter()

        def elapsed(name: str, started: float) -> None:
            if timings is not None:
                timings[name] = timings.get(name, 0.0) + (clock() - started)

        started = clock()
        tensors = []
        for arr in spectrogram_arrays:
            img = Image.fromarray(arr)
            tensors.append(self.transform(img))
        batch_tensor = torch.stack(tensors)
        elapsed("tensor_transform_s", started)

        # Stack into (B, 3, 256, 256)
        started = clock()
        batch_tensor = batch_tensor.to(self.device)
        elapsed("host_to_device_s", started)
        
        # 1. Forward Features
        started = clock()
        features = self.model.forward_features(batch_tensor)
        patch_tokens = features["x_norm_patchtokens"] # (B, 1369, 384)
        elapsed("dino_forward_s", started)

        started = clock()
        patch_tokens = F.normalize(patch_tokens, p=2, dim=-1)
        elapsed("token_normalization_s", started)
        return patch_tokens

    @torch.no_grad()
    def score_patch_tokens(
        self,
        patch_tokens: torch.Tensor,
        threshold: float,
        *,
        timings: dict[str, float] | None = None,
    ) -> list[dict]:
        """Score a normalized token batch against this scorer's frozen index."""
        if patch_tokens.ndim != 3 or patch_tokens.shape[-1] != self.centroids.shape[-1]:
            raise ValueError(
                "Expected patch tokens with shape (batch, patches, "
                f"{self.centroids.shape[-1]}), got {tuple(patch_tokens.shape)}"
            )
        if patch_tokens.device != self.centroids.device:
            raise ValueError(
                f"Patch tokens are on {patch_tokens.device}, index is on "
                f"{self.centroids.device}"
            )

        def clock() -> float:
            if timings is not None and self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            return time.perf_counter()

        def elapsed(name: str, started: float) -> None:
            if timings is not None:
                timings[name] = timings.get(name, 0.0) + (clock() - started)

        started = clock()
        # similarities = (B, 1369, 281)
        similarities = torch.matmul(patch_tokens, self.centroids.T)
        max_sims, _ = torch.max(similarities, dim=-1) # (B, 1369)
        
        # 4. Anomaly Scores (1 - sim)
        anomaly_scores = 1.0 - max_sims # (B, 1369)
        
        # 5. Top-K Pooling
        top_k_scores, top_k_indices = torch.topk(anomaly_scores, self.k, dim=-1) # (B, K)
        novelty_scores = top_k_scores.mean(dim=-1) # (B,)
        elapsed("index_scoring_s", started)
        
        # 6. MIL Vector Extraction
        started = clock()
        cpu_transfer_s = 0.0
        results = []
        for i in range(patch_tokens.shape[0]):
            k_idx = top_k_indices[i] # (K,)
            top_k_patches = patch_tokens[i][k_idx] # (K, 384)
            mil_vector = top_k_patches.mean(dim=0)
            mil_vector = F.normalize(mil_vector, p=2, dim=-1)
            
            transfer_started = clock()
            n_score = float(novelty_scores[i].cpu().item())
            cpu_transfer_s += clock() - transfer_started
            
            # Compute ablation scores for different k values seamlessly
            ablation_k_scores = {}
            if hasattr(self, 'k_ablations') and self.k_ablations:
                for ab_k in self.k_ablations:
                    ab_k = min(ab_k, anomaly_scores.shape[-1])
                    transfer_started = clock()
                    ab_score = anomaly_scores[i].topk(ab_k)[0].mean().item()
                    cpu_transfer_s += clock() - transfer_started
                    ablation_k_scores[f"k_{ab_k}"] = ab_score

            transfer_started = clock()
            top_k_indices_np = k_idx.cpu().numpy().astype(np.int32)
            mil_vector_np = mil_vector.cpu().numpy().astype(np.float32)
            patch_scores_np = anomaly_scores[i].cpu().numpy().astype(np.float32)
            cpu_transfer_s += clock() - transfer_started
            
            results.append({
                "novelty_score": n_score,
                "ablation_k_scores": ablation_k_scores,
                "is_novel": n_score > threshold,
                "top_k_indices": top_k_indices_np,
                "mil_vector": mil_vector_np,
                "patch_anomaly_scores": patch_scores_np,
            })
        elapsed("result_materialization_s", started)
        if timings is not None:
            timings["cpu_transfer_s"] = timings.get("cpu_transfer_s", 0.0) + cpu_transfer_s
        return results

    def _cleanup(self, timings: dict[str, float] | None = None) -> None:
        def clock() -> float:
            if timings is not None and self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            return time.perf_counter()

        cleanup_started = clock()
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if timings is not None:
            timings["cleanup_s"] = timings.get("cleanup_s", 0.0) + (
                clock() - cleanup_started
            )

    @torch.no_grad()
    def score_multi_index(
        self,
        spectrogram_arrays: list[np.ndarray],
        targets: Mapping[str, tuple["PatchScorer", float]],
        *,
        timings: dict[str, float] | None = None,
    ) -> dict[str, list[dict]]:
        """Encode once, then score exactly against each named frozen index."""
        if not targets:
            raise ValueError("At least one scoring target is required")
        for name, (scorer, _) in targets.items():
            if not name or not name.replace("_", "").isalnum():
                raise ValueError(f"Invalid target name: {name!r}")
            if scorer.device != self.device:
                raise ValueError(
                    f"Target {name!r} uses {scorer.device}; encoder uses {self.device}"
                )

        def clock() -> float:
            if timings is not None and self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            return time.perf_counter()

        total_started = clock()
        encode_timings: dict[str, float] | None = {} if timings is not None else None
        patch_tokens = self.encode_patch_tokens(
            spectrogram_arrays, timings=encode_timings
        )
        if timings is not None and encode_timings is not None:
            timings.update({f"encoder_{key}": value for key, value in encode_timings.items()})

        results: dict[str, list[dict]] = {}
        for name, (scorer, threshold) in targets.items():
            target_timings: dict[str, float] | None = {} if timings is not None else None
            results[name] = scorer.score_patch_tokens(
                patch_tokens, threshold, timings=target_timings
            )
            if timings is not None and target_timings is not None:
                timings.update(
                    {f"{name}_{key}": value for key, value in target_timings.items()}
                )
        self._cleanup(timings)
        if timings is not None:
            timings["score_total_s"] = timings.get("score_total_s", 0.0) + (
                clock() - total_started
            )
        return results

    @torch.no_grad()
    def score_spectrogram(
        self,
        spectrogram_arrays: list[np.ndarray],
        threshold: float,
        *,
        timings: dict[str, float] | None = None,
    ) -> list[dict]:
        """Run the legacy single-index MIL path with unchanged return values.

        ``timings`` is an opt-in benchmark sink. CUDA synchronization is
        performed only when it is supplied, so the normal production path is
        unaffected.
        """
        def clock() -> float:
            if timings is not None and self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            return time.perf_counter()

        total_started = clock()
        encode_timings: dict[str, float] | None = {} if timings is not None else None
        patch_tokens = self.encode_patch_tokens(
            spectrogram_arrays, timings=encode_timings
        )
        if timings is not None and encode_timings is not None:
            timings.update(encode_timings)
        scoring_timings: dict[str, float] | None = {} if timings is not None else None
        results = self.score_patch_tokens(
            patch_tokens, threshold, timings=scoring_timings
        )
        if timings is not None and scoring_timings is not None:
            timings.update(scoring_timings)
        self._cleanup(timings)
        if timings is not None:
            timings["score_total_s"] = timings.get("score_total_s", 0.0) + (
                clock() - total_started
            )
        return results

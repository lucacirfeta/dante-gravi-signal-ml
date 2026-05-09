"""Frozen DINOv2-with-Registers feature extractor — Phase 2.

Loads ``dinov2_vits14_reg`` (ViT-S/14 + register tokens, ICLR 2024) via
``torch.hub`` and extracts L2-normalized 384-dim CLS token embeddings from
Q-transform spectrogram PNGs.  All weights are frozen — no training
required.  The register variant suppresses high-norm artifact tokens in
low-informative image regions, producing cleaner clusters downstream
(Phase 3: UMAP + HDBSCAN).

Usage::

    encoder = DINOv2Encoder()
    emb = encoder.extract(Path("spectrogram.png"))          # (384,)
    embs = encoder.extract_batch([p1, p2, p3])              # (3, 384)
    encoder.extract_dataset(in_dir, Path("out.npy"))        # saves .npy + .json
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torchvision import transforms
from tqdm import tqdm

from src.utils import get_device, setup_logger

logger: logging.Logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# Transform pipeline (module-level for test reuse)
# ---------------------------------------------------------------------------


def build_dinov2_transform(output_size: int = 518) -> transforms.Compose:
    """Build the image transform pipeline for DINOv2 inference.

    Converts a grayscale (mode ``"L"``) spectrogram PNG into a
    ``(3, output_size, output_size)`` float32 tensor normalised with
    ImageNet statistics — matching the frozen DINOv2 pretraining.

    Args:
        output_size: Spatial resolution fed to the ViT.  **518** is the
            native resolution for DINOv2 (14 px patch × 37 patches = 518).

    Returns:
        A ``torchvision.transforms.Compose`` pipeline.
    """
    return transforms.Compose(
        [
            transforms.Lambda(lambda img: img.convert("RGB")),
            transforms.Resize((output_size, output_size)),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ]
    )


# ---------------------------------------------------------------------------
# DINOv2Encoder
# ---------------------------------------------------------------------------


class DINOv2Encoder:
    """Frozen DINOv2-with-Registers feature extractor for GW spectrograms.

    Loads ``dinov2_vits14_reg`` (ViT-S/14 + register tokens) via
    ``torch.hub``.  Weights are frozen at instantiation.  Outputs
    L2-normalized 384-dim CLS token embeddings suitable for downstream
    UMAP + HDBSCAN clustering.

    Args:
        device: Compute device.  Defaults to auto-detection
            (``cuda`` / ``mps`` / ``cpu``).
        batch_size: Default batch size for :meth:`extract_batch`.
            Default **32**.
    """

    def __init__(
        self,
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        self.device: str = device or get_device()
        self.batch_size: int = batch_size

        # Load DINOv2-Reg ViT-S/14 via torch.hub
        self.model: torch.nn.Module = torch.hub.load(
            "facebookresearch/dinov2",
            "dinov2_vits14_reg",
        )
        self.model.eval()

        # Freeze all parameters — no training, pure feature extraction
        for param in self.model.parameters():
            param.requires_grad = False

        self.model.to(self.device)

        # Pre-built transform (grayscale PNG → 3×518×518 tensor)
        self.transform: transforms.Compose = build_dinov2_transform()

        logger.info(
            "DINOv2-Reg ViT-S/14 loaded on %s (frozen, eval mode)",
            self.device,
        )

    # ------------------------------------------------------------------
    # Single-image extraction
    # ------------------------------------------------------------------

    def extract(self, image_path: Path) -> np.ndarray:
        """Extract a single L2-normalized 384-dim embedding.

        Args:
            image_path: Path to a spectrogram PNG (typically 256×256,
                mode ``"L"``).

        Returns:
            ``float32`` numpy array of shape ``(384,)`` with
            L2-norm ≈ 1.0.
        """
        img = Image.open(image_path)
        tensor = self.transform(img).unsqueeze(0).to(self.device)

        with torch.no_grad():
            cls_token: torch.Tensor = self.model(tensor)

        # L2-normalize
        cls_token = torch.nn.functional.normalize(cls_token, p=2, dim=1)
        return cls_token.squeeze(0).cpu().numpy().astype(np.float32)

    # ------------------------------------------------------------------
    # Batch extraction
    # ------------------------------------------------------------------

    def extract_batch(
        self,
        image_paths: list[Path],
        batch_size: int | None = None,
    ) -> np.ndarray:
        """Extract L2-normalized embeddings for a list of images.

        Args:
            image_paths: Ordered list of spectrogram PNG paths.
            batch_size: Override the instance default if provided.

        Returns:
            ``float32`` numpy array of shape ``(N, 384)``.

        Raises:
            RuntimeError: If a CUDA OOM persists after halving the
                batch size once.
        """
        bs: int = batch_size or self.batch_size
        all_embeddings: list[np.ndarray] = []

        for start in tqdm(
            range(0, len(image_paths), bs),
            desc="Extracting embeddings",
        ):
            batch_paths = image_paths[start : start + bs]
            tensors = torch.stack(
                [self.transform(Image.open(p)) for p in batch_paths]
            ).to(self.device)

            try:
                with torch.no_grad():
                    cls_tokens: torch.Tensor = self.model(tensors)
            except RuntimeError as exc:
                if "out of memory" not in str(exc):
                    raise

                # OOM guard — halve batch size and retry once
                retry_bs = max(1, bs // 2)
                logger.warning(
                    "OOM with batch_size=%d — retrying with %d",
                    bs,
                    retry_bs,
                )
                torch.cuda.empty_cache()

                sub_embeddings: list[torch.Tensor] = []
                for sub_start in range(0, len(batch_paths), retry_bs):
                    sub_batch = batch_paths[sub_start : sub_start + retry_bs]
                    sub_tensors = torch.stack(
                        [self.transform(Image.open(p)) for p in sub_batch]
                    ).to(self.device)

                    try:
                        with torch.no_grad():
                            sub_cls: torch.Tensor = self.model(sub_tensors)
                        sub_embeddings.append(sub_cls)
                    except RuntimeError as retry_exc:
                        if "out of memory" not in str(retry_exc):
                            raise
                        raise RuntimeError(
                            f"CUDA OOM persists at batch_size={retry_bs}. "
                            f"Reduce --batch-size or use CPU."
                        ) from retry_exc

                cls_tokens = torch.cat(sub_embeddings, dim=0)

            # L2-normalize the whole batch
            cls_tokens = torch.nn.functional.normalize(cls_tokens, p=2, dim=1)
            all_embeddings.append(cls_tokens.cpu().numpy().astype(np.float32))

        return np.concatenate(all_embeddings, axis=0)

    # ------------------------------------------------------------------
    # Full dataset extraction + save
    # ------------------------------------------------------------------

    def extract_dataset(
        self,
        input_dir: Path,
        output_path: Path,
        batch_size: int = 32,
    ) -> None:
        """Scan a directory for PNGs, extract embeddings, and save.

        Saves two files:

        * ``output_path`` — NumPy ``.npy`` of shape ``(N, 384)``
        * ``output_path.with_suffix('.json')`` — companion metadata

        Args:
            input_dir: Directory to recursively glob for ``*.png``.
            output_path: Destination ``.npy`` file path.
            batch_size: Batch size for inference.

        Raises:
            FileNotFoundError: If *input_dir* contains no PNG files.
        """
        sorted_paths: list[Path] = sorted(input_dir.rglob("*.png"))

        if not sorted_paths:
            raise FileNotFoundError(
                f"No PNG files found in {input_dir}. "
                f"Run 'python main.py scan' first to generate spectrograms."
            )

        embeddings: np.ndarray = self.extract_batch(
            sorted_paths, batch_size=batch_size
        )

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        np.save(output_path, embeddings)

        # Companion metadata JSON
        metadata = {
            "model": "dinov2_vits14_reg",
            "embedding_dim": 384,
            "n_samples": len(sorted_paths),
            "shape": list(embeddings.shape),
            "files": [str(p) for p in sorted_paths],
            "device": self.device,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        json_path = output_path.with_suffix(".json")
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2)

        logger.info(
            "Saved %d embeddings → %s + .json",
            len(sorted_paths),
            output_path,
        )

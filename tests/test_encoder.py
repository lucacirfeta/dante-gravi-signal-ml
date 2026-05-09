"""Tests for src.encoder — DINOv2-Reg feature extraction pipeline.

Fast tests (no model download) validate the transform pipeline.
Slow tests (marked @pytest.mark.slow) validate end-to-end embedding
extraction and require ~90 MB DINOv2-Reg weights download on first run.

Run fast tests only:   pytest tests/test_encoder.py -v
Run all tests:         pytest tests/test_encoder.py -v --run-slow
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

from src.encoder import build_dinov2_transform


# =====================================================================
# FAST tests — no model download required
# =====================================================================


class TestBuildDINOv2Transform:
    """Validate the image transform pipeline in isolation."""

    def test_output_shape(self) -> None:
        """Grayscale 256×256 → (3, 518, 518) float32 tensor."""
        img = Image.fromarray(
            np.random.randint(0, 256, (256, 256), dtype=np.uint8), mode="L"
        )
        transform = build_dinov2_transform()
        tensor = transform(img)

        assert tensor.shape == torch.Size([3, 518, 518])
        assert tensor.dtype == torch.float32

    def test_rgb_conversion(self) -> None:
        """Pure-black L-mode image is expanded to 3 RGB channels."""
        img = Image.fromarray(np.zeros((256, 256), dtype=np.uint8), mode="L")
        transform = build_dinov2_transform()
        tensor = transform(img)

        # Dimension 0 should be the channel axis with 3 channels
        assert tensor.shape[0] == 3


class TestExtractDatasetEmptyDir:
    """Validate that extract_dataset raises on an empty directory."""

    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        """Passing a directory with no PNGs should raise FileNotFoundError."""
        from unittest.mock import MagicMock

        from src.encoder import DINOv2Encoder

        # Mock the encoder to avoid downloading the model
        encoder = object.__new__(DINOv2Encoder)
        encoder.device = "cpu"
        encoder.batch_size = 32
        encoder.transform = build_dinov2_transform()
        encoder.model = MagicMock()

        with pytest.raises(FileNotFoundError, match="No PNG files found"):
            encoder.extract_dataset(
                tmp_path, tmp_path / "out.npy", batch_size=32
            )


# =====================================================================
# SLOW tests — require DINOv2-Reg model download (~90 MB)
# =====================================================================


def _make_noise_png(path: Path, size: tuple[int, int] = (256, 256)) -> Path:
    """Write a random grayscale noise PNG and return its path."""
    arr = np.random.randint(0, 256, size, dtype=np.uint8)
    Image.fromarray(arr, mode="L").save(path)
    return path


@pytest.mark.slow
class TestExtractSingleEmbedding:
    """Validate single-image embedding extraction."""

    def test_shape_and_norm(self, tmp_path: Path) -> None:
        """extract() → (384,) float32 with L2-norm ≈ 1.0."""
        from src.encoder import DINOv2Encoder

        png = _make_noise_png(tmp_path / "noise.png")
        encoder = DINOv2Encoder()
        result = encoder.extract(png)

        assert result.shape == (384,)
        assert result.dtype == np.float32
        assert abs(np.linalg.norm(result) - 1.0) < 1e-5


@pytest.mark.slow
class TestExtractBatchShapes:
    """Validate batch embedding extraction."""

    def test_batch_output(self, tmp_path: Path) -> None:
        """extract_batch(5 PNGs) → (5, 384) float32."""
        from src.encoder import DINOv2Encoder

        paths = [
            _make_noise_png(tmp_path / f"noise_{i}.png") for i in range(5)
        ]
        encoder = DINOv2Encoder()
        result = encoder.extract_batch(paths)

        assert result.shape == (5, 384)
        assert result.dtype == np.float32


@pytest.mark.slow
class TestExtractDatasetOutputs:
    """Validate full dataset extraction + serialisation."""

    def test_npy_and_json(self, tmp_path: Path) -> None:
        """extract_dataset() saves .npy and companion .json with correct metadata."""
        from src.encoder import DINOv2Encoder

        # Create 3 test PNGs
        for i in range(3):
            _make_noise_png(tmp_path / f"spec_{i:03d}.png")

        output_npy = tmp_path / "embeddings.npy"
        encoder = DINOv2Encoder()
        encoder.extract_dataset(tmp_path, output_npy)

        # Validate .npy
        assert output_npy.exists()
        embeddings = np.load(output_npy)
        assert embeddings.shape == (3, 384)

        # Validate companion .json
        json_path = output_npy.with_suffix(".json")
        assert json_path.exists()

        with open(json_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)

        assert meta["model"] == "dinov2_vits14_reg"
        assert meta["n_samples"] == 3
        assert meta["embedding_dim"] == 384
        assert meta["shape"] == [3, 384]

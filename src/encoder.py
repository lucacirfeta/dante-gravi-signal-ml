"""Self-supervised spectrogram encoder — Phase 2 scaffold.

This module will provide a lightweight CNN backbone for extracting
fixed-length embedding vectors from Q-transform spectrograms.  The
embeddings are used downstream by the clustering module to discover
novel glitch classes without labeled training data.

Architecture:
    - Backbone: ConvNeXt-Tiny (or EfficientNet-B0) via torchvision
    - Head: Global average pool → Linear → 128-dim L2-normalized embedding
    - Training: SimCLR contrastive learning or MAE reconstruction (Phase 2)

NOTE: This is a Phase 2 scaffold.  Only the model architecture is defined;
the training loop will be implemented in Phase 2.
"""

from __future__ import annotations

import logging

import torch
import torch.nn as nn
import torchvision.models as models

from src.utils import load_config, setup_logger

logger: logging.Logger = setup_logger(__name__)

_CFG = load_config()
_ENCODER_CFG = _CFG["encoder"]


class SpectrogramEncoder(nn.Module):
    """CNN backbone for self-supervised spectrogram feature extraction.

    Wraps a pretrained torchvision model (default: ConvNeXt-Tiny) and
    replaces the classification head with a projection layer that outputs
    a compact, L2-normalized embedding vector.

    Args:
        backbone_name: Name of the torchvision model to use as the
            feature extractor.  Must be a model available via
            ``torchvision.models``.
        embedding_dim: Dimensionality of the output embedding vector.
        pretrained: Whether to load ImageNet-pretrained weights.

    Shape:
        - Input:  ``(B, 3, 256, 256)`` — batch of RGB spectrograms
        - Output: ``(B, embedding_dim)`` — L2-normalized embeddings

    Example::

        >>> encoder = SpectrogramEncoder()
        >>> x = torch.randn(4, 3, 256, 256)
        >>> z = encoder(x)
        >>> z.shape
        torch.Size([4, 128])
        >>> torch.allclose(z.norm(dim=1), torch.ones(4))
        True
    """

    def __init__(
        self,
        backbone_name: str = _ENCODER_CFG["backbone"],
        embedding_dim: int = _ENCODER_CFG["embedding_dim"],
        pretrained: bool = _ENCODER_CFG["pretrained"],
    ) -> None:
        super().__init__()
        self.embedding_dim = embedding_dim

        # Load backbone from torchvision
        weights = "IMAGENET1K_V1" if pretrained else None
        backbone_fn = getattr(models, backbone_name, None)
        if backbone_fn is None:
            raise ValueError(
                f"Unknown backbone '{backbone_name}'. "
                f"Must be a valid torchvision model name."
            )

        backbone = backbone_fn(weights=weights)

        # Remove the classification head — keep only feature extraction
        # ConvNeXt uses .classifier, ResNet/EfficientNet uses .fc
        if hasattr(backbone, "classifier"):
            feature_dim = backbone.classifier[-1].in_features
            backbone.classifier = nn.Identity()
        elif hasattr(backbone, "fc"):
            feature_dim = backbone.fc.in_features
            backbone.fc = nn.Identity()
        else:
            raise ValueError(
                f"Cannot determine classification head for '{backbone_name}'."
            )

        self.backbone = backbone

        # Projection head: maps backbone features → compact embedding
        self.projection = nn.Sequential(
            nn.Linear(feature_dim, feature_dim // 2),
            nn.GELU(),
            nn.Linear(feature_dim // 2, embedding_dim),
        )

        logger.info(
            "SpectrogramEncoder: %s -> %d-dim (pretrained=%s)",
            backbone_name,
            embedding_dim,
            pretrained,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Extract L2-normalized embeddings from spectrogram images.

        Args:
            x: Input tensor of shape ``(B, 3, 256, 256)``.
               Spectrograms should be normalized to ImageNet statistics
               if using pretrained weights.

        Returns:
            Tensor of shape ``(B, embedding_dim)`` with unit-norm rows.
        """
        # Backbone feature extraction
        # Input:  (B, 3, 256, 256)
        # Output: (B, feature_dim)  — after global average pooling
        features = self.backbone(x)

        # Projection to compact embedding
        # (B, feature_dim) → (B, embedding_dim)
        embeddings = self.projection(features)

        # L2 normalize — critical for contrastive learning (SimCLR)
        embeddings = nn.functional.normalize(embeddings, p=2, dim=1)

        return embeddings

from __future__ import annotations

import numpy as np

from scripts.run_gw_autoencoder_baseline import (
    ConvAutoencoder,
    deterministic_split,
    fit_autoencoder,
)


def test_deterministic_split_is_disjoint_complete_and_seeded() -> None:
    first = deterministic_split(25, validation_fraction=0.2, seed=42)
    second = deterministic_split(25, validation_fraction=0.2, seed=42)
    train, validation = first
    assert np.array_equal(train, second[0])
    assert np.array_equal(validation, second[1])
    assert len(validation) == 5
    assert set(train).isdisjoint(validation)
    assert sorted(np.concatenate([train, validation]).tolist()) == list(range(25))


def test_autoencoder_preserves_32_square_shape() -> None:
    import torch

    model = ConvAutoencoder(latent_dim=8)
    values = torch.zeros((3, 1, 32, 32), dtype=torch.float32)
    assert model(values).shape == values.shape


def test_autoencoder_training_is_finite_and_reproducible_on_cpu() -> None:
    rng = np.random.default_rng(7)
    background = rng.normal(size=(24, 1024)).astype(np.float32)
    query = rng.normal(size=(5, 1024)).astype(np.float32)
    first = fit_autoencoder(
        background,
        query,
        seed=11,
        epochs=2,
        patience=2,
        batch_size=8,
        device="cpu",
    )
    second = fit_autoencoder(
        background,
        query,
        seed=11,
        epochs=2,
        patience=2,
        batch_size=8,
        device="cpu",
    )
    assert np.isfinite(first["query_scores"]).all()
    assert np.array_equal(first["train_indices"], second["train_indices"])
    assert np.array_equal(first["validation_indices"], second["validation_indices"])
    np.testing.assert_allclose(first["query_scores"], second["query_scores"], rtol=0, atol=0)

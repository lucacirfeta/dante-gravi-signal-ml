from __future__ import annotations

import numpy as np
import pytest

from src.dante_light.aux_cache import AuxChannelCache, AuxChannelKey
from src.dante_light.contracts import ContractError


def key(channel="H1:PEM-TEST"):
    return AuxChannelKey(
        detector="H1",
        channel=channel,
        gps_start=1000.0,
        gps_end=1002.0,
        sample_rate_hz=16.0,
        source="nds2.example:31200",
    )


def test_aux_cache_cold_and_warm_values_are_exact(tmp_path) -> None:
    cache = AuxChannelCache(tmp_path)
    calls = 0

    def fetch(_key):
        nonlocal calls
        calls += 1
        return np.linspace(-1.0, 1.0, 32, dtype=np.float64)

    cold, was_cached = cache.get_or_fetch(key(), fetch)
    assert was_cached is False
    warm, was_cached = cache.get_or_fetch(key(), fetch)
    assert was_cached is True
    assert calls == 1
    np.testing.assert_array_equal(cold, warm)


def test_aux_cache_key_separates_channels_and_detects_tampering(tmp_path) -> None:
    cache = AuxChannelCache(tmp_path)
    values = np.arange(32, dtype=np.float64)
    first, _ = cache.get_or_fetch(key("H1:PEM-A"), lambda _key: values)
    second, _ = cache.get_or_fetch(key("H1:PEM-B"), lambda _key: values + 1)
    assert not np.array_equal(first, second)

    data_path, _ = cache._paths(key("H1:PEM-A"))
    with data_path.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(ContractError, match="SHA256 mismatch"):
        cache.load(key("H1:PEM-A"))


def test_aux_cache_rejects_wrong_length_before_persisting(tmp_path) -> None:
    cache = AuxChannelCache(tmp_path)
    with pytest.raises(ContractError, match="length"):
        cache.get_or_fetch(key(), lambda _key: np.zeros(31))
    assert not list(tmp_path.iterdir())

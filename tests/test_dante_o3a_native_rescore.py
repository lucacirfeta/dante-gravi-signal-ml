"""Fail-closed O3a native-rescore contract, cache and shard checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np
import pytest
import torch

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_native_contract import ROOT
from src.dante_light import o3a_native_rescore as rescore


def _contract() -> dict:
    return {
        "contract_digest": "a" * 64,
        "execution": {
            "batch_size": 2,
            "download_retries": 1,
            "free_space_reserve_bytes": 0,
            "raw_cache_limit_bytes": 1024,
        },
    }


def _row(*, gps: int = 1000) -> dict:
    return {
        "population": "native_calibration",
        "ordinal": 0,
        "detector": "H1",
        "gps_start": gps,
        "identity_digest": "b" * 64,
        "expected_image_sha256": "c" * 64,
        "context_sources": [],
        "context_sources_digest": "d" * 64,
    }


def test_real_contract_preserves_scoring_parity():
    contract = rescore.build_rescore_contract(root=ROOT)
    o4a = json.loads((ROOT / rescore.METHOD_REL).read_text(encoding="utf-8"))
    o3a_scan = json.loads((ROOT / "config/dante_o3a_primary_scan_v1.json").read_text(encoding="utf-8"))
    assert contract["scoring"]["top_k"] == o4a["scoring"]["top_k"]
    assert contract["scoring"]["top_k"] == o3a_scan["representation"]["top_k"]
    assert contract["scientific_boundary"]["native_threshold_or_class_computed"] is False


def test_shard_roundtrip_and_mutation_rejected(tmp_path: Path):
    contract = _contract()
    row = _row()
    scored = {
        **row,
        "image_sha256": row["expected_image_sha256"],
        "native_score": 0.25,
        "score_float32_hex": rescore._float32_hex(0.25),
    }
    rescore._write_shard(run_dir=tmp_path, batch_index=0, inputs=[row], outputs=[scored], contract=contract)
    assert rescore._read_shard(run_dir=tmp_path, batch_index=0, expected=[row], contract=contract) == [scored]
    path = rescore._shard_path(tmp_path, 0)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["rows"][0]["native_score"] = 0.5
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ContractError, match="shard changed"):
        rescore._read_shard(run_dir=tmp_path, batch_index=0, expected=[row], contract=contract)


def test_source_frame_conflict_rejected():
    first = {"detector": "H1", "filename": "raw.hdf5", "sha256": "a" * 64, "size_bytes": 3}
    second = {**first, "sha256": "b" * 64}
    rows = [{"context_sources": [first]}, {"context_sources": [second]}]
    with pytest.raises(ContractError, match="differs across rows"):
        rescore._frame_dependency_order([[rows[0]], [rows[1]]])


def test_verified_raw_cache_reused_then_evicted(tmp_path: Path, monkeypatch):
    payload = b"abc"
    source = {
        "detector": "H1",
        "filename": "raw.hdf5",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }
    calls = []

    def download(*, frame, target, retries, expected_sha256):
        calls.append((frame, retries, expected_sha256))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return {"sha256": source["sha256"], "size_bytes": len(payload)}

    monkeypatch.setattr(rescore, "_download_frame", download)
    batch = [{"context_sources": [source]}]
    known = {}
    rescore._prepare_batch_sources(batch=batch, run_dir=tmp_path, contract=_contract(), known=known)
    rescore._prepare_batch_sources(batch=batch, run_dir=tmp_path, contract=_contract(), known=known)
    assert len(calls) == 1
    key = ("H1", "raw.hdf5")
    rescore._evict_finished_frames(
        run_dir=tmp_path,
        batch_index=0,
        last_use={key: 0},
        sources={key: source},
        known=known,
    )
    assert not (tmp_path / "transient_raw/H1/raw.hdf5").exists()


def test_cross_frame_context_and_image_replay(tmp_path: Path, monkeypatch):
    from src.core import preprocessor

    rate = 4096
    cache = tmp_path / "transient_raw/H1"
    cache.mkdir(parents=True)
    sources = []
    for name, start, values in (
        ("left.hdf5", 1000, np.ones(20 * rate, dtype=np.float64)),
        ("right.hdf5", 1020, np.full(20 * rate, 2.0, dtype=np.float64)),
    ):
        with h5py.File(cache / name, "w") as handle:
            handle.create_dataset("strain/Strain", data=values)
        sources.append({"detector": "H1", "filename": name, "gps_start": start, "gps_end": start + 20})
    monkeypatch.setattr(
        preprocessor,
        "whiten_context",
        lambda series, _start, _end, pad: (series, {"effective_left": pad, "effective_right": pad}),
    )
    monkeypatch.setattr(
        preprocessor,
        "generate_qtransform",
        lambda *_args, **_kwargs: np.zeros((256, 256), dtype=np.float64),
    )
    image = (plt.get_cmap("cividis")(np.zeros((256, 256)))[:, :, :3] * 255).astype(np.uint8)
    row = {
        **_row(gps=1004),
        "context_sources": sources,
        "context_sources_digest": rescore.canonical_json_sha256(sources),
        "expected_image_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
    }
    contract = {
        "preprocessing": {"whitening_pad_s": 4, "analysis_duration_s": 32, "sample_rate_hz": rate},
        "representation": {"qrange": [4, 64], "frequency_range_hz": [20, 2048], "image_shape": [256, 256, 3], "colormap": "cividis"},
    }
    actual, replay = rescore._prepare_score_row((row, str(tmp_path / "transient_raw"), contract))
    assert np.array_equal(actual, image)
    expected_raw = np.concatenate([np.ones(20 * rate), np.full(20 * rate, 2.0)])
    assert replay["raw_context_sha256"] == hashlib.sha256(expected_raw.tobytes()).hexdigest()
    assert replay["clean_window_shape"] == [32 * rate]
    with pytest.raises(ContractError, match="image hash changed"):
        rescore._prepare_score_row(({**row, "expected_image_sha256": "0" * 64}, str(tmp_path / "transient_raw"), contract))


def test_score_only_never_promotes_a_class():
    class Scorer:
        def encode_patch_tokens(self, images):
            return torch.ones((len(images), 2, 3), dtype=torch.float32)

        def score_patch_tokens(self, _tokens, _threshold, *, output_mode):
            assert output_mode == "score_only"
            return [{"novelty_score": 0.125, "is_novel": True}]

    contract = {
        "representation": {"patch_tokens_per_image": 2, "embedding_dimension": 3},
        "scoring": {"temporary_threshold": 1.0, "output_mode": "score_only"},
    }
    result = rescore._score_prepared([(np.zeros((2, 2, 3)), _row())], scorer=Scorer(), contract=contract)
    assert result[0]["native_score"] == 0.125
    assert "is_novel" not in result[0]
    assert "class" not in result[0]

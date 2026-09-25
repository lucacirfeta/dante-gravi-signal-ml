"""Outcome-blind O3a physical-coincidence contract guards."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_native_coincidence import (
    _event_summary,
    _read_shard,
    _write_shard,
    plan_sources,
    primary_null_threshold,
    split_seed_populations,
)


def _contract() -> dict:
    return {
        "population": {
            "exact_counts": {
                "primary": {"H1": 1, "L1": 1, "total": 2},
                "diagnostic": {"H1": 1, "L1": 0, "total": 1},
                "excluded": {"H1": 0, "L1": 1, "total": 1},
            }
        }
    }


def _rows() -> list[dict]:
    return [
        {"detector": "H1", "gps_start": 100, "native_class": "ROBUST"},
        {"detector": "L1", "gps_start": 100, "native_class": "ROBUST"},
        {"detector": "H1", "gps_start": 200, "native_class": "AMBIGUOUS"},
        {"detector": "L1", "gps_start": 200, "native_class": "BACKGROUND"},
    ]


def test_split_uses_seed_class_only_and_keeps_diagnostic_separate() -> None:
    primary, diagnostic = split_seed_populations(_rows(), contract=_contract())
    assert [(r["detector"], r["gps_start"]) for r in primary] == [
        ("H1", 100),
        ("L1", 100),
    ]
    assert [(r["detector"], r["gps_start"]) for r in diagnostic] == [("H1", 200)]


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "wrong_class", "float_gps"])
def test_split_fails_closed_on_population_or_identity_drift(mutation: str) -> None:
    rows = copy.deepcopy(_rows())
    if mutation == "duplicate":
        rows.append(dict(rows[0]))
    elif mutation == "missing":
        rows.pop()
    elif mutation == "wrong_class":
        rows[0]["native_class"] = "AMBIGUOUS"
    else:
        rows[0]["gps_start"] = 100.0
    with pytest.raises(ContractError):
        split_seed_populations(rows, contract=_contract())


def test_pooled_p99_uses_one_robust_maximum_per_measured_seed() -> None:
    rows = [
        {"measurement_status": "MEASURED", "cc_null_max": float(v)}
        for v in (0.1, 0.2, 0.3, 0.4)
    ] + [{"measurement_status": "PARTNER_DATA_UNAVAILABLE", "cc_null_max": None}]
    measurement = {"threshold_quantile_percent": 99.0, "threshold_quantile_method": "linear"}
    assert primary_null_threshold(rows, measurement=measurement) == pytest.approx(
        np.percentile([0.1, 0.2, 0.3, 0.4], 99, method="linear")
    )


def test_empty_measured_primary_null_fails_closed() -> None:
    with pytest.raises(ContractError):
        primary_null_threshold([], measurement={"threshold_quantile_percent": 99.0, "threshold_quantile_method": "linear"})


def _frame(detector: str) -> dict:
    return {
        "detector": detector,
        "filename": f"{detector}.hdf5",
        "gps_start": 0,
        "gps_end": 4096,
        "url": f"https://gwosc.org/{detector}.hdf5",
    }


def test_source_plan_uses_opposite_detector_without_partner_class() -> None:
    frames = {d: [_frame(d)] for d in ("H1", "L1")}
    ledger = {
        (d, f"{d}.hdf5"): {**_frame(d), "sha256": d * 32, "size_bytes": 100}
        for d in ("H1", "L1")
    }
    plans, audit = plan_sources(
        [{"detector": "H1", "gps_start": 100, "native_class": "ROBUST"}],
        frames_by_detector=frames, raw_frame_ledger=ledger, pad=4, duration=32,
    )
    assert [(r["detector"], r["role"]) for r in plans] == [
        ("H1", "SEED"), ("L1", "PARTNER")
    ]
    assert audit["unique_source_frame_count"] == 2
    assert audit["partner_class_consulted"] is False
    assert audit["strain_opened"] is False


def test_source_plan_rejects_seed_context_drift() -> None:
    frames = {d: [_frame(d)] for d in ("H1", "L1")}
    with pytest.raises(ContractError, match="seed source context changed"):
        plan_sources(
            [{"detector": "H1", "gps_start": 100, "context_sources": []}],
            frames_by_detector=frames, raw_frame_ledger={}, pad=4, duration=32,
        )


def test_source_plan_partner_gap_is_not_seed_gap() -> None:
    frames = {"H1": [_frame("H1")], "L1": []}
    plans, audit = plan_sources(
        [{"detector": "H1", "gps_start": 100}],
        frames_by_detector=frames, raw_frame_ledger={}, pad=4, duration=32,
    )
    assert audit["partner_source_coverage_unavailable"] == 1
    assert plans[1]["availability"] == "NO_COMPLETE_SOURCE_COVERAGE"
    with pytest.raises(ContractError, match="raw source coverage gap"):
        plan_sources(
            [{"detector": "L1", "gps_start": 100}],
            frames_by_detector=frames, raw_frame_ledger={}, pad=4, duration=32,
        )


def test_pooled_threshold_excludes_ambiguous_and_is_strict() -> None:
    contract = {"measurement": {
        "threshold_quantile_percent": 99.0,
        "threshold_quantile_method": "linear",
    }}
    primary = [
        {"measurement_status": "MEASURED", "cc_null_max": 0.5,
         "cc_onsource": 0.5, "per_event_null_exceeded": False},
        {"measurement_status": "MEASURED", "cc_null_max": 0.5,
         "cc_onsource": 0.6, "per_event_null_exceeded": True},
    ]
    diagnostic = [
        {"measurement_status": "MEASURED", "cc_null_max": 999.0,
         "cc_onsource": 0.6, "per_event_null_exceeded": False},
    ]
    summary, primary_rows, diagnostic_rows = _event_summary(primary, diagnostic, contract)
    assert summary["primary_null_p99"] == 0.5
    assert [r["exceeds_primary_threshold"] for r in primary_rows] == [False, True]
    assert diagnostic_rows[0]["exceeds_primary_threshold"] is True
    assert summary["primary"]["primary_threshold_exceeded"] == 1


def test_event_shard_rejects_tampered_null_even_with_resealed_digest(tmp_path) -> None:
    from src.dante_light.contracts import canonical_json_sha256
    from src.dante_light.o3a_native_coincidence import _shard_path
    import json

    contract = {"contract_digest": "c" * 64, "measurement": {"null_shifts_s": [1.0, -1.0]}}
    seed = {"detector": "H1", "gps_start": 100,
            "native_class": "ROBUST", "native_score": 0.4,
            "identity_digest": "a" * 64}
    event = {"detector": "H1", "gps_start": 100,
             "seed_native_class": "ROBUST", "seed_native_score": 0.4,
             "seed_identity_digest": "a" * 64,
             "partner_class_consulted": False, "population": "primary",
             "measurement_status": "MEASURED", "cc_onsource": 0.3,
             "cc_null_values": [0.1, 0.2], "cc_null_max": 0.2,
             "cc_null_mean": float(np.mean([0.1, 0.2])),
             "n_null": 2, "per_event_null_exceeded": True}
    _write_shard(tmp_path, 0, [seed], [event], contract, "k" * 64)
    assert _read_shard(tmp_path, 0, [seed], contract, "k" * 64) == [event]
    path = _shard_path(tmp_path, 0)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["rows"][0]["cc_null_max"] = 0.9
    body = dict(stored)
    body.pop("shard_digest")
    stored["shard_digest"] = canonical_json_sha256(body)
    path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(ContractError, match="measured null ledger"):
        _read_shard(tmp_path, 0, [seed], contract, "k" * 64)


def test_measure_batch_keeps_seed_and_partner_roles_separate(monkeypatch, tmp_path) -> None:
    from src.dante_light import o3a_native_coincidence as module

    seed = {"detector": "H1", "gps_start": 100, "native_class": "ROBUST",
            "identity_digest": "a" * 64, "native_score": 0.4,
            "image_sha256": "seed", "clean_window_sha256": "clean-seed",
            "raw_context_sha256": "raw-seed"}
    plans = {
        (d, 100): {"detector": d, "gps_start": 100, "availability": "SOURCE_COVERED", "sources": []}
        for d in ("H1", "L1")
    }

    def prepared(task):
        plan, _cache, _contract = task
        is_seed = plan["detector"] == "H1"
        return {"detector": plan["detector"], "gps_start": 100,
                "availability": "AVAILABLE", "image": np.zeros((2, 2, 3), dtype=np.uint8),
                "clean": np.ones(4), "image_sha256": "seed" if is_seed else "partner",
                "clean_window_sha256": "clean-seed" if is_seed else "clean-partner",
                "raw_context_sha256": "raw-seed" if is_seed else "raw-partner"}

    class Executor:
        def map(self, function, items):
            return map(function, items)

    class Scorer:
        def encode_patch_tokens(self, images):
            import torch
            return torch.zeros((len(images), 3, 4))

        def score_patch_tokens(self, tokens, _threshold, *, output_mode):
            assert output_mode == "full"
            return [
                {"novelty_score": score, "top_k_indices": [0, 1]}
                for score in (0.4, 0.2)
            ]

    monkeypatch.setattr(module, "_read_context", prepared)
    monkeypatch.setattr(module, "measure_physical_arrays", lambda *_args, **_kwargs: {
        "cc_onsource": 0.3, "cc_null_values": [0.1, 0.2],
        "cc_null_max": 0.2, "n_null": 2,
        "per_event_null_exceeded": True,
    })
    contract = {
        "scoring": {"top_k": 2, "max_seed_score_delta": 2e-7,
                    "temporary_threshold": 0.1},
        "representation": {"patch_tokens_per_image": 3, "embedding_dimension": 4},
        "measurement": {},
    }
    rows = module._measure_batch(
        seeds=[seed], plan_rows=[plans[("H1", 100)], plans[("L1", 100)]],
        plan_map=plans, seed_map={("H1", 100): seed},
        cache_root=tmp_path, contract=contract, scorer=Scorer(), executor=Executor(),
    )
    assert len(rows) == 1
    assert rows[0]["measurement_status"] == "MEASURED"
    assert rows[0]["partner"] == "L1"
    assert rows[0]["partner_class_consulted"] is False
    assert "partner_native_class" not in rows[0]


@pytest.mark.parametrize("error_type,allowed", [
    ("InfrastructureError", True), ("ContractError", False),
])
def test_archive_only_verified_infrastructure_failure(
    monkeypatch, tmp_path, error_type: str, allowed: bool,
) -> None:
    import json
    from src.dante_light import o3a_native_coincidence as module
    from src.dante_light.contracts import canonical_json_sha256

    contract = {"contract_digest": "c" * 64, "execution": {"batch_size": 32}}
    preflight = {"preflight_digest": "p" * 64}
    monkeypatch.setattr(module, "load_contract", lambda **_kwargs: contract)
    monkeypatch.setattr(
        module, "_preflight_details", lambda **_kwargs: (preflight, [], []),
    )
    monkeypatch.setattr(module, "_run_key", lambda *_args: "k" * 64)
    run_dir = tmp_path / f"native_coincidence_{'k' * 64}"
    run_dir.mkdir()
    (run_dir / "preflight.json").write_text(json.dumps(preflight), encoding="utf-8")
    body = {
        "status": "FAILED_O3A_NATIVE_COINCIDENCE",
        "contract_digest": contract["contract_digest"],
        "run_key": "k" * 64,
        "error_type": error_type,
        "error": "synthetic failure",
    }
    failure = {**body, "artifact_digest": canonical_json_sha256(body)}
    (run_dir / "failure.json").write_text(json.dumps(failure), encoding="utf-8")
    if allowed:
        archive = module.archive_infrastructure_failure(
            root=tmp_path, external_root=tmp_path,
        )
        assert json.loads(archive.read_text(encoding="utf-8")) == failure
        assert not (run_dir / "failure.json").exists()
    else:
        with pytest.raises(ContractError, match="not verified infrastructure-only"):
            module.archive_infrastructure_failure(root=tmp_path, external_root=tmp_path)
        assert (run_dir / "failure.json").exists()

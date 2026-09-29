"""Synthetic binding tests for the frozen comparative PEM background spans."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light import o3a_o4a_common_pem_span_reader as span_reader


def _sealed(path: Path, body: dict) -> dict:
    document = {**body, "receipt_digest": canonical_json_sha256(body)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return document


def _fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    monkeypatch.setattr(span_reader, "ROOT", root)
    for name in span_reader.SPAN_SOURCE_FILES + span_reader.ACQUISITION_SOURCE_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if name == span_reader.SPAN_CONFIG_PATH else "frozen")
    base = tmp_path / "o3a_o4a_common_pem_v1"
    acquisition_plan_body = {
        "source_sha256": {
            name: sha256_file(root / name)
            for name in span_reader.ACQUISITION_SOURCE_FILES
        },
        "runs": {
            run: {
                "spans": [
                    {
                        "detector": "H1",
                        "gps_start": 100 if run == "O3a" else 300,
                        "interval_gps": [200, 204] if run == "O3a" else [400, 404],
                    }
                ]
            }
            for run in ("O3a", "O4a")
        },
    }
    acquisition_digest = canonical_json_sha256(acquisition_plan_body)
    acquisition_dir = (
        base
        / "background_acquisition"
        / f"background_acquisition_v2_{acquisition_digest}"
    )
    acquisition_plan = _sealed(acquisition_dir / "plan.json", acquisition_plan_body)
    acquisition_summary = _sealed(
        acquisition_dir / "summary.json",
        {
            "status": "PASS_ACQUIRED_BACKGROUND_FRAME_BYTES_V2_ONLY",
            "plan_digest": acquisition_digest,
        },
    )
    span_plan_body = {
        "status": "FROZEN_BACKGROUND_SPAN_REPLAY_NO_PEM_OUTCOMES",
        "contract_digest": canonical_json_sha256({}),
        "source_sha256": {
            name: sha256_file(root / name) for name in span_reader.SPAN_SOURCE_FILES
        },
        "parent_plan_digest": acquisition_digest,
        "parent_summary_digest": acquisition_summary["receipt_digest"],
        "spans": {
            run: acquisition_plan["runs"][run]["spans"] for run in ("O3a", "O4a")
        },
    }
    span_digest = canonical_json_sha256(span_plan_body)
    span_dir = base / "background_span_replay" / f"background_spans_{span_digest}"
    _sealed(span_dir / "plan.json", span_plan_body)
    span_summary = _sealed(
        span_dir / "summary.json",
        {
            "status": "PASS_BACKGROUND_SPAN_REPLAY_COMPLETE_ONLY",
            "plan_digest": span_digest,
            "span_counts": {"O3a": 1, "O4a": 1},
        },
    )
    backgrounds = {}
    sources = {}
    for run, gps, left, right in (("O3a", 100, 200, 204), ("O4a", 300, 400, 404)):
        background = {
            "detector": "H1",
            "interval_gps": [left, right],
            "frames": [],
            "samples_sha256": "a" * 64,
        }
        backgrounds[run] = background
        _sealed(
            span_dir / "receipts" / f"{run}_H1_{gps}.json",
            {
                "status": "PASS_BACKGROUND_SPAN_REPLAY_ONLY",
                "run": run,
                "target_gps": gps,
                "background": background,
            },
        )
        manifest = f"synthetic-{run}".encode()
        (acquisition_dir / f"{run}_strain_hdf_md5.txt").write_bytes(manifest)
        sources[run] = {
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "release": f"{run}_4KHZ_R1",
            "frame_duration_s": 4,
        }
    monkeypatch.setattr(
        span_reader,
        "load_background_source_contract",
        lambda **kwargs: {"sources": sources},
    )
    monkeypatch.setattr(
        span_reader,
        "parse_official_frame_manifest",
        lambda *args, **kwargs: {},
    )
    calls = []

    class LocalOnly:
        def __init__(self, *, source, manifest, cache_dir):
            calls.append(cache_dir)
            self.receipts = []

        def __call__(self, detector, start, end):
            self.receipts.append(backgrounds["O3a"])
            return "synthetic-series"

    monkeypatch.setattr(span_reader, "OfficialBackgroundReader", LocalOnly)
    binding = {
        "schema_version": 1,
        "contract_id": "dante-o3a-o4a-common-pem-background-input-binding-v1",
        "status": "FROZEN_LOCAL_STRAIN_INPUT_ONLY_NO_PEM_OUTCOMES",
        "span_run_key": span_digest,
        "span_summary_digest": span_summary["receipt_digest"],
        "acquisition_run_key": acquisition_digest,
        "acquisition_summary_digest": acquisition_summary["receipt_digest"],
        "expected_spans": {"O3a": 1, "O4a": 1},
        "transport_policy": "VERIFIED_OFFICIAL_FRAME_BYTES_LOCAL_ONLY_NO_DOWNLOAD",
        "scientific_boundary": {
            "background_strain_samples_only": True,
            "five_channel_null_opened": False,
            "paired_pem_outcomes_opened": False,
            "global_significance_claim": False,
        },
    }
    path = root / span_reader.BINDING_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(binding), encoding="utf-8")
    return span_dir, acquisition_dir, calls


def test_local_span_matches_sealed_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    span_dir, acquisition_dir, calls = _fixture(monkeypatch, tmp_path)
    reader = span_reader.VerifiedSpanReader(
        span_dir, acquisition_dir, run="O3a", detector="H1", target_gps=100
    )
    assert reader("H1", 200, 204) == "synthetic-series"
    assert calls == [acquisition_dir / "frames"]
    with pytest.raises(ContractError, match="interval is not frozen"):
        reader("H1", 201, 205)


def test_changed_parent_and_receipt_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    span_dir, acquisition_dir, _ = _fixture(monkeypatch, tmp_path)
    reader = span_reader.VerifiedSpanReader(
        span_dir, acquisition_dir, run="O3a", detector="H1", target_gps=100
    )
    receipt = reader.receipt_path
    receipt.write_text(receipt.read_text(encoding="utf-8").replace("a" * 64, "0" * 64))
    with pytest.raises(ContractError, match="receipt seal changed"):
        reader("H1", 200, 204)
    binding_path = span_reader.ROOT / span_reader.BINDING_PATH
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["span_run_key"] = "0" * 64
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(ContractError, match="parent seal changed"):
        span_reader.VerifiedSpanReader(
            span_dir, acquisition_dir, run="O3a", detector="H1", target_gps=100
        )


def test_missing_local_frame_cannot_trigger_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    span_dir, acquisition_dir, _ = _fixture(monkeypatch, tmp_path)

    class MissingFrame:
        def __init__(self, *, source, manifest, cache_dir):
            self.receipts = []

        def __call__(self, detector, start, end):
            span_reader.background_module._download_official(
                "https://example.invalid/frame", tmp_path / "frame.hdf5"
            )

    monkeypatch.setattr(span_reader, "OfficialBackgroundReader", MissingFrame)
    reader = span_reader.VerifiedSpanReader(
        span_dir, acquisition_dir, run="O3a", detector="H1", target_gps=100
    )
    with pytest.raises(ContractError, match="verified background frame missing"):
        reader("H1", 200, 204)
    assert not (tmp_path / "frame.hdf5").exists()

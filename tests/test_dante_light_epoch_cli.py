from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.promote_dante_light_epoch import assemble_promoted_epochs
from src.dante_light.contracts import ContractError, RepresentationContract
from src.dante_light.epoch import REQUIRED_GATES
from src.dante_light.runner import load_epochs


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _promotion(
    root: Path,
    detector: str,
    *,
    threshold: Path,
    representation: RepresentationContract,
) -> Path:
    ledger = root / f"{detector.lower()}_ledger.csv"
    ledger.write_text("gps,score\n1000,0.1\n", encoding="utf-8")
    payload = {
        "schema_version": 1,
        "source_threshold_artifact": {
            "path": threshold.name,
            "sha256": _sha256(threshold),
        },
        "calibration_ledger": {
            "path": ledger.name,
            "sha256": _sha256(ledger),
        },
        "epoch": {
            "schema_version": 1,
            "epoch_id": f"o4b-causal-{detector.lower()}-v1",
            "run": "O4B",
            "detector": detector,
            "cutoff_gps": 2000.0,
            "threshold": 0.2,
            "threshold_artifact_sha256": _sha256(threshold),
            "native_index_sha256": representation.native_index_sha256,
            "causal": True,
        },
        "promotion_evidence": {
            "detector": detector,
            "run": "O4B",
            "calibration_start_gps": 1000.0,
            "calibration_end_gps": 2000.0,
            "evaluation_start_gps": 3000.0,
            "evaluation_end_gps": 4000.0,
            "gates": {gate: "PASS" for gate in REQUIRED_GATES},
            "gate_artifacts": {
                gate: [threshold.name] for gate in REQUIRED_GATES
            },
            "artifacts": [
                {"path": threshold.name, "sha256": _sha256(threshold)},
                {"path": ledger.name, "sha256": _sha256(ledger)},
            ],
        },
    }
    path = root / f"promote_{detector.lower()}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _manifest(root: Path) -> Path:
    source = Path("config/reference_artifacts.json")
    target = root / "reference_artifacts.json"
    target.write_bytes(source.read_bytes())
    return target


def test_cli_assembles_loadable_detector_specific_causal_epochs(tmp_path) -> None:
    manifest = _manifest(tmp_path)
    representation = RepresentationContract.from_reference_manifest(manifest)
    threshold = tmp_path / "threshold.json"
    threshold.write_text("{}\n", encoding="utf-8")
    promotions = [
        _promotion(tmp_path, detector, threshold=threshold, representation=representation)
        for detector in ("H1", "L1")
    ]
    output = tmp_path / "epochs.json"
    first = assemble_promoted_epochs(
        promotions,
        output_path=output,
        root=tmp_path,
        reference_manifest=manifest,
    )
    second = assemble_promoted_epochs(
        promotions,
        output_path=output,
        root=tmp_path,
        reference_manifest=manifest,
    )
    assert first == second
    _, epochs = load_epochs(
        output, representation=representation, root=tmp_path
    )
    assert set(epochs) == {"H1", "L1"}
    assert all(epoch.causal for epoch in epochs.values())


def test_cli_rejects_missing_ledger_evidence_and_divergent_output(tmp_path) -> None:
    manifest = _manifest(tmp_path)
    representation = RepresentationContract.from_reference_manifest(manifest)
    threshold = tmp_path / "threshold.json"
    threshold.write_text("{}\n", encoding="utf-8")
    promotion = _promotion(
        tmp_path, "H1", threshold=threshold, representation=representation
    )
    payload = json.loads(promotion.read_text(encoding="utf-8"))
    payload["promotion_evidence"]["artifacts"] = payload["promotion_evidence"][
        "artifacts"
    ][:1]
    promotion.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="required provenance"):
        assemble_promoted_epochs(
            [promotion],
            output_path=tmp_path / "epochs.json",
            root=tmp_path,
            reference_manifest=manifest,
        )

    valid = _promotion(
        tmp_path, "H1", threshold=threshold, representation=representation
    )
    output = tmp_path / "epochs.json"
    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ContractError, match="divergent"):
        assemble_promoted_epochs(
            [valid], output_path=output, root=tmp_path, reference_manifest=manifest
        )

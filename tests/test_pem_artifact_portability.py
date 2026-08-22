from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PEM_DIRECTORY = "data/production/aggregated/pem/idxq4-64_queryq4-64"
PROVENANCE = ROOT / PEM_DIRECTORY / "pem_provenance_manifest.json"
EOL_SENSITIVE_PATHS = (
    f"{PEM_DIRECTORY}/selection_manifest.json",
    f"{PEM_DIRECTORY}/selected_targets.csv",
    f"{PEM_DIRECTORY}/coherence_report.csv",
    "data/production_reference/channel_thresholds.json",
    f"{PEM_DIRECTORY}/pem_family_wise_verdicts.csv",
    f"{PEM_DIRECTORY}/pem_class_association.json",
)
HISTORICAL_BASELINE = (
    "data/production/aggregated/archive/detector_dedup_bug_20260805/"
    "Master_Taxonomy_O4a_idxq4-64_queryq4-64.pre_detector_aware.csv"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_relative(raw: str) -> str:
    normalized = raw.replace("\\", "/")
    marker = "data/"
    index = normalized.find(marker)
    assert index >= 0, f"PEM provenance path is outside the repository data tree: {raw}"
    return normalized[index:]


def test_pem_machine_hashed_text_bytes_match_provenance() -> None:
    manifest = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    expected = {
        _repository_relative(record["path"]): record["sha256"]
        for record in manifest["files"]
    }
    assert set(EOL_SENSITIVE_PATHS).issubset(expected)
    assert {
        relative: _sha256(ROOT / relative) for relative in EOL_SENSITIVE_PATHS
    } == {
        relative: expected[relative] for relative in EOL_SENSITIVE_PATHS
    }


def test_pem_machine_hashed_text_disables_git_eol_conversion() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "data/production/aggregated/pem/**/*.json binary" in attributes
    assert "data/production/aggregated/pem/**/*.csv binary" in attributes
    assert "data/production_reference/channel_thresholds.json binary" in attributes


def test_detector_aware_historical_baseline_bytes_match_transition_contract() -> None:
    transition = json.loads(
        (
            ROOT
            / "data/production/aggregated/"
            "dsd_representation_transition_detector_aware.json"
        ).read_text(encoding="utf-8")
    )
    baseline = transition["source"]["historical_taxonomy"]
    assert baseline["path"] == HISTORICAL_BASELINE
    assert _sha256(ROOT / HISTORICAL_BASELINE) == baseline["sha256"]
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert f"{HISTORICAL_BASELINE} binary" in attributes

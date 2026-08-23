from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v5_scattering import (
    ARTIFACT_STATUS,
    load_config,
    synthetic_probes,
    validate_artifact,
    validate_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dante_light_prefilter_v5_scattering_feasibility.json"
ARTIFACT = ROOT / "artifacts/dante_light/prefilter_l4_v5_design/scattering_feasibility_v5.json"


def test_scattering_config_is_feasibility_only() -> None:
    config = load_config(CONFIG)
    boundary = config["scientific_boundary"]
    assert all(
        boundary[key] is False
        for key in (
            "may_access_development_outcomes",
            "may_access_o4b",
            "may_access_reserved_confirmation",
            "may_access_teacher_scores",
            "may_freeze_v5",
            "may_select_scattering",
            "routing_enabled",
        )
    )
    assert config["dependency"]["production_dependency_added"] is False
    assert config["dependency"]["execution_scope"] == "isolated_wsl_only_not_production"
    assert config["transform"] == {
        "J": 10,
        "Q": [8, 1],
        "T": 1024,
        "average": True,
        "backend": "torch",
        "device": "cpu",
        "frontend": "torch",
        "max_order": 2,
        "out_type": "array",
        "oversampling": 0,
    }


def test_scattering_config_rejects_promotion() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["scientific_boundary"]["may_select_scattering"] = True
    body = dict(config)
    body.pop("config_digest")
    config["config_digest"] = canonical_json_sha256(body)
    with pytest.raises(ContractError, match="protected or promotable"):
        validate_config(config)


def test_scattering_synthetic_probes_are_deterministic_and_outcome_blind() -> None:
    config = load_config(CONFIG)
    first = synthetic_probes(config)
    second = synthetic_probes(config)
    assert set(first) == {"white_noise", "centered_impulse", "linear_chirp"}
    for name in first:
        assert first[name].shape == (131072,)
        assert first[name].dtype == np.float32
        assert np.array_equal(first[name], second[name])
        assert np.isfinite(first[name]).all()


def test_scattering_not_added_to_production_environments() -> None:
    for path in (
        ROOT / "environment.yml",
        ROOT / "environment-dante-light-v3.yml",
        ROOT / "environment-o4b-aux.yml",
    ):
        assert "kymatio" not in path.read_text(encoding="utf-8").lower()


def test_committed_scattering_artifact_verifies_without_kymatio() -> None:
    config = load_config(CONFIG)
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    validate_artifact(artifact, config=config)
    assert artifact["status"] == ARTIFACT_STATUS
    assert artifact["candidate_selected"] is False
    assert artifact["protocol_frozen"] is False
    assert artifact["routing_enabled"] is False
    assert artifact["outcome_access"] == {
        "development_outcomes": [],
        "reserved_confirmation": [],
        "o4b": [],
        "teacher_scores": [],
    }
    assert artifact["runtime"]["execution_scope"] == "WSL_ONLY"
    assert artifact["dependency"]["production_dependency_added"] is False
    assert artifact["dependency"]["installed_metadata_license"] == "BSD-3-Clause"
    assert artifact["dependency"]["import_status"] == {
        "strategy": "scoped_internal_1d_frontend_compatibility_fallback",
        "public_import_succeeded": False,
        "public_import_error": {
            "type": "ImportError",
            "reason": "SCIPY_SPECIAL_SPH_HARM_UNAVAILABLE",
        },
    }
    assert artifact["interpretation_boundary"][
        "maintenance_risk_must_be_reassessed_before_protocol_entry"
    ] is True
    serialized = json.dumps(artifact)
    assert "C:\\\\" not in serialized
    assert "/home/" not in serialized


def test_scattering_cli_verifier_passes_on_windows() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_dante_light_prefilter_v5_scattering_feasibility.py"),
            "--verify",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert ARTIFACT_STATUS in completed.stdout

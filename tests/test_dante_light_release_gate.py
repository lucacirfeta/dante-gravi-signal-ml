from __future__ import annotations

import json

from scripts.verify_dante_light_release import (
    ROOT,
    _source_sha256,
    _validate_causal_epochs,
    _validate_prospective,
    _validate_public_bundle,
    evaluate_gates,
    verify,
)
from src.dante_light.contracts import RepresentationContract


def test_development_and_bundle_pass_but_runtime_claims_remain_open() -> None:
    development, gates = verify("development")
    public, _ = verify("public-replay")
    operational, _ = verify("operational")
    by_name = {gate.name: gate for gate in gates}
    assert development is True
    assert public is False
    assert operational is False
    assert by_name["public_reference_bundle"].status == "PASS"
    assert by_name["public_clean_clone_replay"].status == "OPEN"
    assert by_name["causal_detector_epochs"].status == "OPEN"
    assert by_name["prospective_validation"].status == "OPEN"
    assert all(gate.status != "FAIL" for gate in gates)


def test_release_gate_exposes_scope_for_every_gate() -> None:
    gates = evaluate_gates()
    assert gates
    assert all(gate.required_for for gate in gates)
    assert {scope for gate in gates for scope in gate.required_for} == {
        "development",
        "public-replay",
        "operational",
    }


def test_source_hash_is_stable_across_lf_and_crlf(tmp_path) -> None:
    lf = tmp_path / "lf.py"
    crlf = tmp_path / "crlf.py"
    lf.write_bytes(b"first\nsecond\n")
    crlf.write_bytes(b"first\r\nsecond\r\n")
    assert _source_sha256(lf) == _source_sha256(crlf)


def test_public_bundle_requires_deposit_https_url_and_real_sha256() -> None:
    status, _ = _validate_public_bundle(
        {
            "publication_status": "deposited",
            "url": "https://doi.org/10.5281/zenodo.fixture",
            "sha256": "a" * 64,
        }
    )
    assert status == "PASS"
    invalid_bundles = (
        {"publication_status": "not_deposited", "url": None, "sha256": None},
        {
            "publication_status": "deposited",
            "url": "http://example.test",
            "sha256": "a" * 64,
        },
        {
            "publication_status": "deposited",
            "url": "https://example.test",
            "sha256": "not-a-hash",
        },
    )
    assert _validate_public_bundle(invalid_bundles[0])[0] == "OPEN"
    for invalid in invalid_bundles[1:]:
        assert _validate_public_bundle(invalid)[0] == "FAIL"


def test_existing_but_unverified_prospective_file_fails_closed(tmp_path) -> None:
    path = tmp_path / "prospective_validation_v1.json"
    path.write_text(json.dumps({"status": "complete"}), encoding="utf-8")
    valid, detail = _validate_prospective(
        tmp_path,
        path,
        bundle_sha256="a" * 64,
        epochs={},
    )
    assert valid is False
    assert "schema/status" in detail


def test_prospective_preflight_cannot_masquerade_as_operational(tmp_path) -> None:
    path = tmp_path / "prospective_validation_v1.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "complete",
                "mode": "prospective_shadow_preflight",
                "prefilter": "none",
                "public_sources_only": False,
            }
        ),
        encoding="utf-8",
    )
    valid, detail = _validate_prospective(
        tmp_path,
        path,
        bundle_sha256="a" * 64,
        epochs={},
    )
    assert valid is False
    assert "shadow mode" in detail


def test_prepublish_clean_clone_is_not_public_replay_evidence(tmp_path) -> None:
    path = tmp_path / "preflight.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "complete",
                "mode": "clean_clone_prepublish_preflight",
                "public_sources_only": False,
            }
        ),
        encoding="utf-8",
    )
    from scripts.verify_dante_light_release import _validate_public_replay

    valid, detail = _validate_public_replay(
        tmp_path,
        path,
        bundle_sha256="a" * 64,
        replay={"manifest_sha256": "b" * 64, "entries_file_sha256": "c" * 64},
    )
    assert valid is False
    assert "clean-clone mode" in detail


def test_declared_causal_epoch_with_missing_evidence_is_failure() -> None:
    epochs = json.loads(
        (ROOT / "config/dante_light_epochs_v1.json").read_text(encoding="utf-8")
    )
    epochs["epochs"]["H1"]["causal"] = True
    representation = RepresentationContract.from_reference_manifest(
        ROOT / "config/reference_artifacts.json"
    )
    status, detail, _ = _validate_causal_epochs(ROOT, epochs, representation)
    assert status == "FAIL"
    assert "lacks promotion evidence" in detail


def test_historical_epochs_remain_open_without_unshipped_threshold(tmp_path) -> None:
    epochs = json.loads(
        (ROOT / "config/dante_light_epochs_v1.json").read_text(encoding="utf-8")
    )
    representation = RepresentationContract.from_reference_manifest(
        ROOT / "config/reference_artifacts.json"
    )
    status, detail, verified = _validate_causal_epochs(
        tmp_path, epochs, representation
    )
    assert status == "OPEN"
    assert "H1, L1" in detail
    assert verified == {}

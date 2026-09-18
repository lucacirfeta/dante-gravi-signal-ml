from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import (
    FORBIDDEN_OUTCOME_FIELDS,
    ROOT,
    _canonical_forbidden_blocks,
    _verify_rows,
    load_contract,
    select_cohort_rows,
    validate_contract,
)


def _rehash(payload: dict) -> dict:
    value = copy.deepcopy(payload)
    value.pop("contract_digest", None)
    value["contract_digest"] = canonical_json_sha256(value)
    return value


def test_contract_accepts_checked_in_freeze() -> None:
    contract = load_contract(ROOT)
    assert contract["status"] == "APPROVED_OUTCOME_BLIND_FREEZE_INPUT"
    assert contract["endpoints"]["primary"].startswith("end_to_end_32s")
    assert (
        contract["scientific_boundary"]["legacy_july_2026_artifacts_consumed"] is False
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda p: p["population"]["roles"]["primary_injection"].update(
                source_blocks_per_detector=99
            ),
            "primary_injection",
        ),
        (lambda p: p["endpoints"].update(scale_or_fusion_allowed=True), "OR-fusion"),
        (lambda p: p["uncertainty"].update(method="iid_bootstrap"), "raw-block"),
        (lambda p: p["scientific_boundary"].update(forbidden_fields=[]), "firewall"),
    ],
)
def test_contract_rejects_scientific_drift(mutation, message: str) -> None:
    payload = load_contract(ROOT)
    mutation(payload)
    with pytest.raises(ContractError, match=message):
        validate_contract(_rehash(payload), ROOT)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _small_contract() -> dict:
    value = copy.deepcopy(load_contract(ROOT))
    roles = value["population"]["roles"]
    roles["short_scale_index"]["identities_per_detector"] = 1
    roles["short_scale_calibration"]["identities_per_detector"] = 3
    roles["primary_injection"]["source_blocks_per_detector"] = 2
    roles["secondary_dsd_control"]["source_blocks_per_detector"] = 1
    return value


def _fixture_geometry() -> tuple[dict, dict, list[float], set]:
    raw = {"H1": [], "L1": []}
    geometry = {"H1": [], "L1": []}
    forbidden = set()
    for detector_index, detector in enumerate(("H1", "L1")):
        base = 1_000_000
        for block_index in range(9):
            start = float(base + block_index * 4096)
            block = {
                "detector": detector,
                "gps_start": start,
                "gps_end": start + 4096.0,
                "source_relative_path": f"{detector}/{int(start)}.hdf5",
                "source_sha256": _digest(f"{detector}-{block_index}"),
            }
            raw[detector].append(block)
            for offset in (64.0, 160.0, 256.0, 352.0):
                gps = start + offset
                geometry[detector].append(
                    {
                        "detector": detector,
                        "gps_start": gps,
                        "expected_clean_image_sha256": _digest(
                            f"image-{detector}-{gps}"
                        ),
                        "source_identity_digest": _digest(f"identity-{detector}-{gps}"),
                    }
                )
        first = raw[detector][0]
        forbidden.add(
            (detector, first["gps_start"], first["gps_end"], first["source_sha256"])
        )
    # Cross-detector firewall: this removes the second source block from both
    # detectors even though the timestamp is recorded only once.
    candidate_times = [raw["H1"][1]["gps_start"] + 64.0]
    return raw, geometry, candidate_times, forbidden


def test_selection_is_deterministic_outcome_free_and_block_disjoint() -> None:
    contract = _small_contract()
    raw, geometry, candidate_times, forbidden = _fixture_geometry()
    first, audit = select_cohort_rows(
        contract=contract,
        raw_blocks=raw,
        scan_geometry=geometry,
        candidate_times=candidate_times,
        canonical_forbidden_blocks=forbidden,
    )
    second, _ = select_cohort_rows(
        contract=contract,
        raw_blocks=raw,
        scan_geometry=geometry,
        candidate_times=candidate_times,
        canonical_forbidden_blocks=forbidden,
    )
    assert first == second
    assert not any(FORBIDDEN_OUTCOME_FIELDS & set(row) for row in first)
    expected = {(detector, "short_scale_index"): 1 for detector in ("H1", "L1")}
    expected.update(
        {(detector, "short_scale_calibration"): 3 for detector in ("H1", "L1")}
    )
    expected.update({(detector, "primary_injection"): 2 for detector in ("H1", "L1")})
    expected.update(
        {(detector, "secondary_dsd_control"): 1 for detector in ("H1", "L1")}
    )
    counts = {}
    block_roles = {}
    for row in first:
        key = (row["detector"], row["role"])
        counts[key] = counts.get(key, 0) + 1
        block = (
            row["detector"],
            row["raw_block"]["gps_start"],
            row["raw_block"]["gps_end"],
            row["raw_block"]["source_sha256"],
        )
        assert block not in forbidden
        block_roles.setdefault(block, row["role"])
        assert block_roles[block] == row["role"]
    assert counts == expected
    assert all(audit[d]["candidate_guard_rejections"] >= 1 for d in ("H1", "L1"))


def test_selection_refuses_incomplete_role_pool() -> None:
    contract = _small_contract()
    raw, geometry, candidate_times, forbidden = _fixture_geometry()
    contract["population"]["roles"]["primary_injection"][
        "source_blocks_per_detector"
    ] = 100
    with pytest.raises(
        ContractError, match="primary_injection block pool is incomplete"
    ):
        select_cohort_rows(
            contract=contract,
            raw_blocks=raw,
            scan_geometry=geometry,
            candidate_times=candidate_times,
            canonical_forbidden_blocks=forbidden,
        )


def test_row_verifier_rejects_identity_and_outcome_tampering() -> None:
    contract = _small_contract()
    raw, geometry, candidate_times, forbidden = _fixture_geometry()
    rows, _ = select_cohort_rows(
        contract=contract,
        raw_blocks=raw,
        scan_geometry=geometry,
        candidate_times=candidate_times,
        canonical_forbidden_blocks=forbidden,
    )
    _verify_rows(rows, contract)

    identity_tamper = copy.deepcopy(rows)
    identity_tamper[0]["identity_digest"] = _digest("tampered")
    with pytest.raises(ContractError, match="identity digest mismatch"):
        _verify_rows(identity_tamper, contract)

    outcome_tamper = copy.deepcopy(rows)
    outcome_tamper[0]["score"] = 0.5
    with pytest.raises(ContractError, match="outcome fields"):
        _verify_rows(outcome_tamper, contract)


def test_canonical_exclusion_uses_every_index_context_source(tmp_path: Path) -> None:
    blocks = []
    for index in range(3):
        start = float(1_000_000 + 4096 * index)
        blocks.append(
            {
                "detector": "H1",
                "gps_start": start,
                "gps_end": start + 4096.0,
                "source_sha256": _digest(f"raw-{index}"),
            }
        )
    context_sources = [
        {
            "block_interval": [block["gps_start"], block["gps_end"]],
            "sha256": block["source_sha256"],
        }
        for block in blocks[:2]
    ]
    manifest = {
        "rows": [
            {
                "detector": "H1",
                "gps_start": blocks[0]["gps_end"] - 16.0,
                "identity_digest": _digest("identity"),
                "context_sources_digest": _digest("sources"),
            }
        ]
    }
    cohort = {
        **manifest["rows"][0],
        "context_sources": context_sources,
    }
    calibration = {
        "detector": "H1",
        "context_sources": [
            {
                "block_interval": [blocks[2]["gps_start"], blocks[2]["gps_end"]],
                "source_sha256": blocks[2]["source_sha256"],
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    cohort_path = tmp_path / "cohort.jsonl"
    calibration_path = tmp_path / "calibration.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    cohort_path.write_text(json.dumps(cohort) + "\n", encoding="utf-8")
    calibration_path.write_text(json.dumps(calibration) + "\n", encoding="utf-8")

    forbidden = _canonical_forbidden_blocks(
        raw_blocks={"H1": blocks},
        native_index_manifest=manifest_path,
        native_index_cohort_ledger=cohort_path,
        native_calibration_ledger=calibration_path,
    )
    assert forbidden == {
        ("H1", block["gps_start"], block["gps_end"], block["source_sha256"])
        for block in blocks
    }

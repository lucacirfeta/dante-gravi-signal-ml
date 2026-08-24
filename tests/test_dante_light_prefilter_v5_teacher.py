from __future__ import annotations

import copy
import hashlib
import json

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, RepresentationContract
from src.dante_light.prefilter_v5_protocol import ROOT
from src.dante_light.prefilter_v5_teacher import (
    PreparedTeacherInput,
    build_teacher_ledger,
    build_teacher_contract,
    load_training_rows,
    validate_teacher_contract,
    verify_teacher_ledger_summary,
)


def test_teacher_contract_freezes_native_o4a_only() -> None:
    contract = build_teacher_contract(root=ROOT)
    validate_teacher_contract(contract, root=ROOT)
    representation = RepresentationContract.from_reference_manifest(
        ROOT / "config/reference_artifacts.json"
    )
    teacher = contract["teacher"]
    assert teacher["target_name"] == "native_o4a_novelty_score"
    assert teacher["decision_score_key"] == "native"
    assert teacher["target_index_sha256"] == representation.native_index_sha256
    assert teacher["primary_o3b_score_as_target"] is False
    assert teacher["threshold_applied"] is False


def test_saved_teacher_contract_rebuilds_exactly() -> None:
    saved = json.loads(
        (ROOT / "config/dante_light_prefilter_v5_teacher_contract.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved == build_teacher_contract(root=ROOT)


def test_teacher_rows_are_training_background_only() -> None:
    _header, rows = load_training_rows(root=ROOT)
    assert len(rows) == 19200
    assert {row["partition"] for row in rows} == {"training"}
    assert {row["role"] for row in rows} == {"background"}
    assert {row["detector"] for row in rows} == {"H1", "L1"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("development_rows_allowed", True),
        ("confirmation_rows_allowed", True),
        ("o4b_rows_allowed", True),
        ("morphology_labels_used", True),
    ],
)
def test_teacher_contract_rejects_widened_access(field: str, value: bool) -> None:
    contract = build_teacher_contract(root=ROOT)
    contract["access_boundary"][field] = value
    with pytest.raises(ContractError):
        validate_teacher_contract(contract, root=ROOT)


def test_teacher_contract_rejects_primary_as_target() -> None:
    contract = build_teacher_contract(root=ROOT)
    contract["teacher"]["decision_score_key"] = "primary"
    with pytest.raises(ContractError):
        validate_teacher_contract(contract, root=ROOT)


def test_teacher_contract_self_digest_is_fail_closed() -> None:
    contract = copy.deepcopy(build_teacher_contract(root=ROOT))
    contract["training_identity_count"] -= 1
    with pytest.raises(ContractError):
        validate_teacher_contract(contract, root=ROOT)


def test_teacher_ledger_smoke_is_training_only_and_resumable(tmp_path) -> None:
    contract = build_teacher_contract(root=ROOT)
    implementation = ROOT / "src/dante_light/prefilter_v5_teacher.py"
    builder = ROOT / "scripts/build_dante_light_prefilter_v5_teacher_ledger.py"
    references = {
        "teacher_implementation": {
            "path": implementation.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(implementation.read_bytes()).hexdigest(),
        },
        "ledger_builder": {
            "path": builder.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(builder.read_bytes()).hexdigest(),
        },
    }

    def prepare(window):
        value = np.full(4096 * 32, float(window.gps_start % 7), dtype=np.float32)
        image = np.full((256, 256, 3), int(window.gps_start) % 251, dtype=np.uint8)
        digest = hashlib.sha256(value.tobytes()).hexdigest()
        return PreparedTeacherInput(
            image=image,
            clean_strain=value,
            raw_strain_sha256="a" * 64,
            clean_strain_sha256=digest,
            image_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
            timings={"test_s": 0.0},
        )

    def score(images):
        return [float(image[0, 0, 0]) / 255.0 for image in images], {"test_s": 0.0}

    kwargs = dict(
        root=ROOT,
        contract=contract,
        cache_root=tmp_path / "cache",
        compact_artifact_path=tmp_path / "compact.json",
        code_references=references,
        prepare=prepare,
        score=score,
        workers=2,
        limit_blocks=1,
    )
    first = build_teacher_ledger(**kwargs)
    second = build_teacher_ledger(**kwargs)
    assert first == second
    assert first["status"] == "SMOKE_ONLY"
    assert first["row_count"] == 8
    assert first["development_rows_accessed"] == []
    assert first["confirmation_rows_accessed"] == []
    assert first["o4b_rows_accessed"] == []
    assert not (tmp_path / "compact.json").exists()
    verified = verify_teacher_ledger_summary(
        first,
        root=ROOT,
        contract=contract,
        cache_root=tmp_path / "cache",
        require_complete=False,
    )
    assert verified["status"] == "PASS_SMOKE_ONLY"
    assert verified["row_count"] == 8

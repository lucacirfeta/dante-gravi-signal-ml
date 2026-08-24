from __future__ import annotations

import copy
import hashlib
import json

import numpy as np
import pytest
from gwpy.timeseries import TimeSeries

from scripts import verify_dante_light_prefilter_v5_teacher_ledger as teacher_verifier
from src.dante_light.contracts import (
    ContractError,
    RepresentationContract,
    WindowIdentity,
)
from src.dante_light.prefilter_v5_protocol import ROOT
from src.dante_light.prefilter_v5_teacher import (
    PreparedTeacherInput,
    build_teacher_ledger,
    build_teacher_contract,
    load_training_rows,
    read_contiguous_teacher_span,
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


def test_teacher_stitches_only_contiguous_local_raw_files(tmp_path) -> None:
    boundary = 1369889024
    first_start = boundary - 64
    second_end = boundary + 64
    first = tmp_path / f"H1_{first_start}_{boundary}.hdf5"
    second = tmp_path / f"H1_{boundary}_{second_end}.hdf5"
    TimeSeries(
        np.zeros(64 * 4096, dtype=np.float32), sample_rate=4096, t0=first_start
    ).write(first, format="hdf5", path="strain")
    TimeSeries(
        np.ones(64 * 4096, dtype=np.float32), sample_rate=4096, t0=boundary
    ).write(second, format="hdf5", path="strain")
    joined = read_contiguous_teacher_span(
        [(first_start, boundary, first), (boundary, second_end, second)],
        gps_start=boundary - 24,
        gps_end=boundary + 16,
        sample_rate_hz=4096,
    )
    assert joined is not None
    assert joined.size == 40 * 4096
    assert np.all(joined.value[: 24 * 4096] == 0.0)
    assert np.all(joined.value[24 * 4096 :] == 1.0)


def test_teacher_refuses_to_stitch_across_local_gap(tmp_path) -> None:
    first = tmp_path / "L1_1000_1010.hdf5"
    second = tmp_path / "L1_1011_1021.hdf5"
    TimeSeries(np.zeros(10 * 4096), sample_rate=4096, t0=1000).write(
        first, format="hdf5", path="strain"
    )
    TimeSeries(np.ones(10 * 4096), sample_rate=4096, t0=1011).write(
        second, format="hdf5", path="strain"
    )
    assert (
        read_contiguous_teacher_span(
            [(1000, 1010, first), (1011, 1021, second)],
            gps_start=1005,
            gps_end=1016,
            sample_rate_hz=4096,
        )
        is None
    )


def test_teacher_ledger_smoke_is_training_only_and_resumable(tmp_path) -> None:
    contract = build_teacher_contract(root=ROOT)
    paths = {
        "artifact_manifest": "src/core/artifact_manifest.py",
        "core_preprocessor": "src/core/preprocessor.py",
        "core_utils": "src/core/utils.py",
        "dante_preprocessing": "src/dante_light/preprocessing.py",
        "data_loader": "src/core/data_loader.py",
        "encoder": "src/core/encoder.py",
        "ledger_builder": "scripts/build_dante_light_prefilter_v5_teacher_ledger.py",
        "model_loader": "src/core/model_loader.py",
        "patch_scorer": "src/core/patch_scorer.py",
        "runtime_config": "config.yaml",
        "teacher_implementation": "src/dante_light/prefilter_v5_teacher.py",
    }
    references = {
        label: {
            "path": path,
            "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
        }
        for label, path in paths.items()
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


def test_teacher_verifier_replays_frozen_samples_exactly(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identities = [
        WindowIdentity(run="O4A", detector="H1", gps_start=1_370_000_000.0),
        WindowIdentity(run="O4A", detector="L1", gps_start=1_370_004_096.0),
    ]
    images = {
        identity.window_id: np.full((2, 2, 3), index + 1, dtype=np.uint8)
        for index, identity in enumerate(identities)
    }
    clean = {
        identity.window_id: np.full(16, index + 0.25, dtype=np.float32)
        for index, identity in enumerate(identities)
    }
    scores = {
        identity.window_id: np.float32(index + 0.125)
        for index, identity in enumerate(identities)
    }
    run_dir = tmp_path / "cache" / "teacher_test"
    block_dir = run_dir / "blocks"
    block_dir.mkdir(parents=True)
    references = []
    training_rows = []
    for identity in identities:
        row = {
            "window": identity.to_dict(),
            "raw_strain_sha256": "a" * 64,
            "clean_strain_sha256": hashlib.sha256(
                clean[identity.window_id].tobytes()
            ).hexdigest(),
            "image_sha256": hashlib.sha256(
                images[identity.window_id].tobytes()
            ).hexdigest(),
            "teacher_target": {
                "float32_hex": scores[identity.window_id].tobytes().hex()
            },
        }
        path = block_dir / f"{identity.detector}.json"
        path.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
        references.append({"path": f"blocks/{path.name}"})
        training_rows.append({"window": identity.to_dict()})
    artifact = tmp_path / "summary.json"
    artifact.write_text(
        json.dumps(
            {
                "cache_location": {"run_subdirectory": "teacher_test"},
                "block_references": references,
            }
        ),
        encoding="utf-8",
    )
    contract = build_teacher_contract(root=ROOT)
    contract["replay_sample_window_ids"] = [
        identity.window_id for identity in identities
    ]

    def prepare(identity, **_kwargs):
        return PreparedTeacherInput(
            image=images[identity.window_id],
            clean_strain=clean[identity.window_id],
            raw_strain_sha256="a" * 64,
            clean_strain_sha256=hashlib.sha256(
                clean[identity.window_id].tobytes()
            ).hexdigest(),
            image_sha256=hashlib.sha256(
                images[identity.window_id].tobytes()
            ).hexdigest(),
            timings={"test_s": 0.0},
        )

    class FakeTeacher:
        def __init__(self, **_kwargs) -> None:
            pass

        def score(self, batch):
            by_bytes = {
                image.tobytes(): scores[window_id]
                for window_id, image in images.items()
            }
            return [by_bytes[image.tobytes()] for image in batch], {}

    monkeypatch.setattr(teacher_verifier, "load_teacher_contract", lambda **_kwargs: contract)
    monkeypatch.setattr(
        teacher_verifier,
        "verify_teacher_ledger_summary",
        lambda *_args, **_kwargs: {"status": "PASS_COMPLETE"},
    )
    monkeypatch.setattr(
        teacher_verifier, "load_training_rows", lambda **_kwargs: ({}, training_rows)
    )
    monkeypatch.setattr(teacher_verifier, "prepare_teacher_input", prepare)
    monkeypatch.setattr(teacher_verifier, "ExactNativeTeacher", FakeTeacher)

    result = teacher_verifier.verify(
        artifact=artifact,
        cache_root=tmp_path / "cache",
        replay_samples=True,
        device="cpu",
    )
    assert result["status"] == "PASS_COMPLETE"
    assert [row["status"] for row in result["exact_replay_samples"]] == [
        "EXACT_MATCH",
        "EXACT_MATCH",
    ]

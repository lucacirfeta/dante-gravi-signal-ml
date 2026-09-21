from __future__ import annotations

import copy
from pathlib import Path

import h5py
import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_primary_scan import (
    FrameGroupReader,
    InfrastructureError,
    _insert_frame,
    _open_database,
    _parallel_events,
    _verify_raw_frame_ledger,
    group_identities_by_target_frame,
    load_scan_contract,
    validate_scan_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def _frame(name: str, start: int, end: int) -> dict[str, object]:
    return {
        "filename": name,
        "gps_start": start,
        "gps_end": end,
        "duration_s": end - start,
        "url": f"https://example.invalid/{name}",
    }


def _write_frame(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as handle:
        dataset = handle.create_dataset("strain/Strain", data=values)
        dataset.attrs["Xspacing"] = 1.0 / 4096


def test_identity_grouping_is_ordered_unique_and_gap_closed() -> None:
    frames = [_frame("a.hdf5", 0, 10), _frame("b.hdf5", 10, 20)]
    assert group_identities_by_target_frame([1, 5, 10, 19], frames) == [
        (frames[0], [1, 5]),
        (frames[1], [10, 19]),
    ]
    with pytest.raises(ContractError, match="strictly increasing"):
        group_identities_by_target_frame([1, 1], frames)
    with pytest.raises(ContractError, match="no O3a source frame"):
        group_identities_by_target_frame([20], frames)


def test_frame_reader_stitches_exact_context(tmp_path: Path) -> None:
    frames = [_frame("a.hdf5", 0, 1), _frame("b.hdf5", 1, 2)]
    first = tmp_path / "a.hdf5"
    second = tmp_path / "b.hdf5"
    _write_frame(first, np.arange(4096, dtype=np.float64))
    _write_frame(second, np.arange(4096, 8192, dtype=np.float64))
    with FrameGroupReader(frames, {"a.hdf5": first, "b.hdf5": second}) as reader:
        observed = reader.read(0, 2)
    assert observed.shape == (8192,)
    assert np.array_equal(observed, np.arange(8192, dtype=np.float64))


def test_database_resume_identity_is_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "scan.sqlite"
    first = {"run_key": "a", "contract_digest": "b"}
    connection = _open_database(path, identity=first)
    connection.close()
    connection = _open_database(path, identity=first)
    connection.close()
    with pytest.raises(ContractError, match="identity changed"):
        _open_database(path, identity={"run_key": "different"})


def test_raw_frame_ledger_round_trips_named_columns_and_resumes(tmp_path: Path) -> None:
    connection = _open_database(
        tmp_path / "scan.sqlite",
        identity={"run_key": "run", "contract_digest": "contract"},
    )
    frame = {
        "detector": "H1",
        "gps_start": 100,
        "gps_end": 200,
        "filename": "H-test-100-100.hdf5",
        "url": "https://example.invalid/H-test-100-100.hdf5",
        "sha256": "ab" * 32,
        "size_bytes": 123,
        "retained_calibration_raw": False,
    }
    _insert_frame(connection, frame)
    connection.commit()
    _insert_frame(connection, frame)
    connection.commit()
    assert connection.execute(
        "SELECT detector,gps_start,gps_end,filename,url,sha256,size_bytes,"
        "retained_calibration_raw FROM raw_frames"
    ).fetchone() == (
        "H1",
        100,
        200,
        "H-test-100-100.hdf5",
        "https://example.invalid/H-test-100-100.hdf5",
        "ab" * 32,
        123,
        0,
    )
    assert _verify_raw_frame_ledger(
        connection,
        required_by_detector={"H1": [frame], "L1": []},
    ) == 1
    changed = dict(frame, sha256="cd" * 32)
    with pytest.raises(ContractError, match="provenance changed"):
        _insert_frame(connection, changed)
    connection.close()


def test_raw_frame_verifier_rejects_shifted_positional_ledger(tmp_path: Path) -> None:
    connection = _open_database(
        tmp_path / "scan.sqlite",
        identity={"run_key": "run", "contract_digest": "contract"},
    )
    connection.execute(
        "INSERT INTO raw_frames VALUES(?,?,?,?,?,?,?,?)",
        (
            "H1",
            "H-test-100-100.hdf5",
            100,
            200,
            "https://example.invalid/H-test-100-100.hdf5",
            "ab" * 32,
            123,
            0,
        ),
    )
    with pytest.raises(ContractError, match="provenance changed"):
        _verify_raw_frame_ledger(
            connection,
            required_by_detector={
                "H1": [
                    {
                        "gps_start": 100,
                        "gps_end": 200,
                        "filename": "H-test-100-100.hdf5",
                        "url": "https://example.invalid/H-test-100-100.hdf5",
                    }
                ],
                "L1": [],
            },
        )
    connection.close()


def test_parallel_producer_preserves_retryable_failure_type() -> None:
    def failing():
        raise InfrastructureError("network down")
        yield "unreachable", None

    with pytest.raises(InfrastructureError, match="network down"):
        list(_parallel_events({"H1": failing()}, queue_depth=1))


def test_frozen_contract_binds_thresholds_population_and_noncausal_note() -> None:
    value = load_scan_contract(root=ROOT)
    assert value["population"]["counts_by_detector"] == {
        "H1": 349_925,
        "L1": 372_986,
    }
    assert value["thresholds"]["rule"] == (
        "primary_score_strictly_greater_than_detector_p99"
    )
    assert value["thresholds"]["detector_pooling_allowed"] is False
    assert value["thresholds"]["retuning_allowed"] is False
    assert value["storage"]["retained_primary_scan_raw_frames"] == 0
    assert value["execution"]["process_start_method"] == "spawn"
    assert value["ci_asymmetry_annotation"]["status"] == "NON_CAUSAL_HYPOTHESIS"
    assert (
        value["scientific_boundary"]["candidate_outcomes_visible_during_run"] is False
    )


def test_contract_rejects_threshold_drift() -> None:
    value = load_scan_contract(root=ROOT)
    mutated = copy.deepcopy(value)
    mutated["thresholds"]["values"]["H1"] = 0.0
    body = {key: item for key, item in mutated.items() if key != "contract_digest"}
    mutated["contract_digest"] = canonical_json_sha256(body)
    with pytest.raises(ContractError, match="contract is stale"):
        validate_scan_contract(mutated, root=ROOT)

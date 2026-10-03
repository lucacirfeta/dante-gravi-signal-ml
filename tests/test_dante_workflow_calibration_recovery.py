"""Exact native raw recovery and refusal to silently admit changed inputs."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import h5py
import numpy as np
import pytest

from src.dante_workflow import calibration_recovery as recovery


@pytest.fixture
def case(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "source.py").write_text("synthetic source")
    (root / "protocol.json").write_text("synthetic config")
    frame = tmp_path / "synthetic.hdf5"
    values = np.arange(40, dtype=np.float64)
    with h5py.File(frame, "w") as handle:
        ds = handle.create_dataset("strain/Strain", data=values)
        ds.attrs["Xstart"] = 100
        ds.attrs["Xspacing"] = 0.5
        for name, value in {"Detector": "H1", "GPSstart": 100, "Duration": 20}.items():
            handle.create_dataset("meta/" + name, data=value)
    url = "https://gwosc.org/archive/data/Synthetic_R1/synthetic.hdf5"
    interval = {
        "detector": "H1",
        "gps_start": 103,
        "gps_end": 118,
        "files": [
            {
                "detector": "H1",
                "gps_start": 100,
                "gps_end": 120,
                "sample_rate_hz": 2,
                "url": url,
            }
        ],
    }
    old = {
        "records": [
            {
                "detector": "H1",
                "gps_start": 103,
                "gps_end": 118,
                "strain_values_sha256": hashlib.sha256(
                    values[6:36].tobytes()
                ).hexdigest(),
                "file_sha256": "0" * 64,
            }
        ]
    }
    oldpath = tmp_path / "old.json"
    oldpath.write_text(json.dumps(old))
    reportpath = tmp_path / "report.json"
    reportpath.write_text("synthetic report bytes")
    plan = recovery.sealed(
        {
            "status": "PLAN_RAW_RECOVERY_ONLY",
            "dataset": "Synthetic_R1",
            "parent": {
                "path": "protocol.json",
                "sha256": recovery._hash(root / "protocol.json"),
            },
            "report": {"intervals": [interval]},
            "sample_rate_hz": 2,
            "historical_receipt": old,
            "historical_receipt_path": str(oldpath),
            "historical_receipt_sha256": recovery._hash(oldpath),
            "report_path": str(reportpath),
            "report_sha256": recovery._hash(reportpath),
            "source_hashes": {"source.py": recovery._hash(root / "source.py")},
            "replacement_bytes_admitted": False,
            "scientific_execution_ready": False,
        }
    )
    md5 = recovery.file_hashes(frame)[1]

    def checksums(dataset):
        return f"{md5}  H1/synthetic.hdf5\n".encode(), {"synthetic.hdf5": md5}

    def download(url, path):
        shutil.copyfile(frame, path)

    return root, frame, plan, checksums, download


def acquire(case, tmp_path, **kwargs):
    root, _, plan, checksums, download = case
    run = tmp_path / "external" / "new_run"
    result = recovery.acquire(
        plan, run, root=root, checksum_fetch=checksums, downloader=download, **kwargs
    )
    return run, result


def test_exact_slice_and_offline_replay(case, tmp_path, monkeypatch):
    run, result = acquire(case, tmp_path)
    assert result["records"][0]["sample_count"] == 30
    assert result["records"][0]["numerical_bytes_match"]
    assert not result["records"][0]["container_bytes_match"]
    monkeypatch.setattr(recovery, "download", lambda *a: pytest.fail("offline only"))
    replay = recovery.verify(run, root=case[0])
    assert replay["status"] == "PASS_VERIFIED_RAW_NUMERIC_MATCH_ONLY"
    assert replay["interval_count"] == 1
    assert not replay["replacement_bytes_admitted"]
    assert not replay["scientific_execution_ready"]
    assert not (run / "controller.lock").exists()


def test_existing_run_never_resumed(case, tmp_path):
    run, _ = acquire(case, tmp_path)
    with pytest.raises(FileExistsError):
        recovery.acquire(
            case[2], run, root=case[0], checksum_fetch=case[3], downloader=case[4]
        )


def test_source_drift_before_download(case, tmp_path):
    (case[0] / "source.py").write_text("changed")
    with pytest.raises(recovery.RecoveryError, match="source"):
        acquire(case, tmp_path)
    assert not (tmp_path / "external" / "new_run").exists()


def test_md5_failure_preserves_partial(case, tmp_path):
    root, _, plan, _, download = case
    run = tmp_path / "run"
    with pytest.raises(recovery.RecoveryError, match="MD5"):
        recovery.acquire(
            plan,
            run,
            root=root,
            downloader=download,
            checksum_fetch=lambda d: (b"fake", {"synthetic.hdf5": "0" * 32}),
        )
    assert (run / "failure.json").exists()
    assert list((run / "frames").glob("*.partial"))


def test_numerical_mismatch_stops_preserves_context(case, tmp_path):
    root, frame, _, checksums, download = case
    plan = deepcopy(case[2])
    plan["historical_receipt"]["records"][0]["strain_values_sha256"] = "f" * 64
    oldpath = Path(plan["historical_receipt_path"])
    oldpath.write_text(json.dumps(plan["historical_receipt"]))
    plan["historical_receipt_sha256"] = recovery._hash(oldpath)
    plan.pop("digest")
    plan = recovery.sealed(plan)
    run = tmp_path / "run"
    with pytest.raises(recovery.RecoveryError, match="numerical SHA"):
        recovery.acquire(
            plan, run, root=root, checksum_fetch=checksums, downloader=download
        )
    assert len(list((run / "contexts").glob("*.hdf5"))) == 1
    assert not (run / "summary.json").exists()
    assert not (run / "controller.lock").exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda h: h["strain/Strain"].attrs.update(Xstart=101),
        lambda h: h["strain/Strain"].attrs.update(Xspacing=0.25),
        lambda h: h["strain/Strain"].__setitem__(6, float("nan")),
    ],
)
def test_grid_or_finite_mismatch(case, change):
    with h5py.File(case[1], "a") as handle:
        change(handle)
    interval = case[2]["report"]["intervals"][0]
    with pytest.raises(recovery.RecoveryError):
        recovery.samples_from_frames(
            interval, {interval["files"][0]["url"]: case[1]}, 2
        )


@pytest.mark.parametrize("filename", ["source.py", "protocol.json"])
def test_verifier_source_or_parent_drift(case, tmp_path, filename):
    run, _ = acquire(case, tmp_path)
    (case[0] / filename).write_text("changed")
    with pytest.raises(recovery.RecoveryError):
        recovery.verify(run, root=case[0])


def test_verifier_context_tamper(case, tmp_path):
    run, result = acquire(case, tmp_path)
    (run / result["records"][0]["path"]).write_bytes(b"changed")
    with pytest.raises(Exception):
        recovery.verify(run, root=case[0])


@pytest.mark.parametrize("name", ["controller.lock", "failure.json", "bad.partial"])
def test_verifier_dirty_run_refused(case, tmp_path, name):
    run, _ = acquire(case, tmp_path)
    (run / name).write_text("evidence")
    with pytest.raises(recovery.RecoveryError):
        recovery.verify(run, root=case[0])

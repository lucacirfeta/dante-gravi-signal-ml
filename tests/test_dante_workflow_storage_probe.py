"""Temporary byte fixtures only; no real parents, model or scientific launch."""

import json

import pytest

from src.dante_workflow import storage_probe as probe
from src.dante_workflow.calibration_recovery import read_sealed


@pytest.fixture
def trees(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "images").mkdir()
    (source / "empty").mkdir()
    (source / "images" / "a.npy").write_bytes(b"opaque bytes not numpy")
    (source / "receipt.json").write_bytes(b"{\r\nunchanged LF/CRLF\n}\r\n")
    return source, tmp_path / "probe"


def test_full_byte_mirror_and_measure(trees):
    source, work = trees
    before = probe.inventory(source)
    assert probe.mirror(source, work) == (2, sum(r["size_bytes"] for r in before))
    assert probe.inventory(work / "parent") == before
    assert (work / "parent" / "empty").is_dir()
    samples = probe.measure(source, work, 2)
    assert [(s["iteration"], s["arm"]) for s in samples] == [
        (0, "original"),
        (0, "mirror"),
        (1, "mirror"),
        (1, "original"),
    ]
    assert all(s["quiet_seconds"] >= 0 for s in samples)
    result = read_sealed(work / "measurement.json")
    assert result["boundary"] == probe.BOUNDARY
    assert result["boundary"]["scientific_execution_ready"] is False
    assert probe.inventory(source) == before
    with pytest.raises(ValueError, match="immutable"):
        probe.measure(source, work, 1)
    with pytest.raises(FileExistsError):
        probe.mirror(source, work)


@pytest.mark.parametrize(
    "name", ["controller.lock", "failure.json", "x.partial", "x.tmp"]
)
def test_active_failed_incomplete_parent_rejected(trees, name):
    source, work = trees
    (source / name).write_bytes(b"evidence")
    with pytest.raises(ValueError):
        probe.mirror(source, work)
    assert not work.exists()
    assert (source / name).exists()


@pytest.mark.parametrize("overlap", ["equal", "inside", "ancestor"])
def test_overlap_rejected(trees, overlap):
    source, _ = trees
    target = {"equal": source, "inside": source / "probe", "ancestor": source.parent}[
        overlap
    ]
    with pytest.raises(ValueError, match="overlaps"):
        probe.mirror(source, target)


def test_symlink_rejected(trees, tmp_path):
    source, work = trees
    outside = tmp_path / "outside"
    outside.write_bytes(b"not admitted")
    (source / "linked").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        probe.mirror(source, work)
    assert read_sealed(work / "failure.json")["error"] == "ValueError"
    assert not (work / "mirror.json").exists()


@pytest.mark.parametrize("arm", ["source", "mirror"])
def test_tamper_rejected(trees, arm):
    source, work = trees
    probe.mirror(source, work)
    target = source if arm == "source" else work / "parent"
    (target / "receipt.json").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="inventory differs"):
        probe.measure(source, work, 1)
    assert not (work / "measurement.json").exists()
    assert read_sealed(work / "failure.json")["error"] == "ValueError"
    with pytest.raises(ValueError, match="immutable"):
        probe.measure(source, work, 1)


def test_copy_failure_preserved_no_resume(trees, monkeypatch):
    source, work = trees

    def fail(*args):
        raise OSError("simulated storage failure")

    monkeypatch.setattr(probe.shutil, "copyfileobj", fail)
    with pytest.raises(OSError):
        probe.mirror(source, work)
    assert read_sealed(work / "failure.json")["error"] == "OSError"
    assert not (work / "mirror.json").exists()
    with pytest.raises(FileExistsError):
        probe.mirror(source, work)
    with pytest.raises(ValueError, match="immutable"):
        probe.measure(source, work, 1)


@pytest.mark.parametrize("count", [0, -1, True, 1.5])
def test_bad_repeat_count(trees, count):
    with pytest.raises(ValueError, match="repetition"):
        probe.measure(*trees, count)


@pytest.mark.parametrize("arm", ["source", "mirror"])
def test_empty_directory_drift_rejected(trees, arm):
    source, work = trees
    probe.mirror(source, work)
    target = source if arm == "source" else work / "parent"
    (target / "extra_empty").mkdir()
    with pytest.raises(ValueError, match="directory layout differs"):
        probe.measure(source, work, 1)
    assert not (work / "measurement.json").exists()


def test_policy_rejects_scientific_promotion(trees, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"schema_version": 1, "status": "SCIENTIFIC_PASS"}))
    with pytest.raises(ValueError, match="I/O-only"):
        probe.load_policy(tmp_path, config, probe._hash(config))


def test_policy_hash_mismatch_stops(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    with pytest.raises(ValueError, match="SHA pin"):
        probe.load_policy(tmp_path, config, "0" * 64)


@pytest.mark.parametrize("relative", ["../outside", "/tmp/outside"])
def test_policy_reference_escape(tmp_path, relative):
    with pytest.raises(ValueError, match="escapes"):
        probe.root_file(tmp_path, relative)


def test_real_policy_shape_on_sealed_fixtures(trees, tmp_path):
    source, work = trees
    parent = {}
    for name, status in [
        ("summary", "PASS_COMPLETE_EXPANDED_CALIBRATION_PREPROCESSING_ONLY"),
        ("verification", "PASS_VERIFIED_EXPANDED_CALIBRATION_PREPROCESSING_ONLY"),
    ]:
        path = source / f"{name}.json"
        probe.new_report(path, {"status": status})
        parent[f"{name}_sha256"] = probe._hash(path)
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"preprocessing_parent": parent}))
    policy = {
        "schema_version": 1,
        "status": "ISOLATED_STORAGE_PROBE_V1",
        "boundary": probe.BOUNDARY,
        "repetitions": 1,
        "source_pins": [],
        "productive_profile": {"path": profile.name, "sha256": probe._hash(profile)},
        "source_directory": str(source),
        "workspace": str(work),
    }
    config = tmp_path / "config.json"
    config.write_text(json.dumps(policy))
    assert probe.load_policy(tmp_path, config, probe._hash(config)) == policy
    base_args = [
        "--repository-root",
        str(tmp_path),
        "--config",
        str(config),
        "--config-sha256",
        probe._hash(config),
    ]
    assert probe.main(["--stage", "mirror", *base_args]) == 0
    assert probe.main(["--stage", "measure", *base_args]) == 0
    assert read_sealed(work / "measurement.json")["boundary"] == probe.BOUNDARY

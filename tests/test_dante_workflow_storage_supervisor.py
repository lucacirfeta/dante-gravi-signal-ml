"""Byte fixtures and subprocess lifecycle only; no real parents or science."""

import json
from pathlib import Path
import sys
import tempfile

import pytest

from src.dante_workflow import storage_probe as probe
from src.dante_workflow import storage_supervisor as supervisor
from src.dante_workflow.calibration_recovery import read_sealed
from src.dante_workflow.input_coverage import InputCoverageError


@pytest.fixture
def bound(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "opaque.bin").write_bytes(b"LF\nCRLF\r\n")
    config = root / "config.json"
    config.write_text("{}")
    pin = root / "pinned.bin"
    pin.write_bytes(b"unchanged")
    policy = {
        "source_directory": str(source),
        "workspace": str(tmp_path / "work"),
        "repetitions": 2,
    }
    monkeypatch.setattr(supervisor, "load_policy", lambda *args: policy)
    return root, config, policy, {pin.name: probe._hash(pin)}, tmp_path / "logs"


def execute_fixture(command, directory, stage, stream):
    policy = json.loads((directory.parent / "policy.json").read_text())
    if stage == "mirror":
        probe.mirror(policy["source_directory"], policy["workspace"])
    else:
        probe.measure(
            policy["source_directory"], policy["workspace"], policy["repetitions"]
        )
    supervisor.event(stream, stage=stage, state="EXIT_OBSERVED", exit_code=0)
    return 0


def start(bound, executor=execute_fixture):
    root, config, policy, pins, logs = bound
    (logs.parent / "policy.json").write_text(json.dumps(policy))
    return supervisor.supervise(root, config, probe._hash(config), pins, logs, executor)


def test_one_mirror_one_measure_and_immutable_evidence(bound):
    assert start(bound) == 0
    result = read_sealed(bound[-1] / "summary.json")
    assert result["mirror_exit_code"] == result["measure_exit_code"] == 0
    assert result["boundary"] == probe.BOUNDARY
    with pytest.raises(FileExistsError):
        start(bound)


@pytest.mark.parametrize("stage", ["mirror", "measure"])
def test_nonzero_exit_stops_without_retry(bound, stage):
    calls = []

    def failing(command, directory, current, stream):
        calls.append(current)
        if current == stage:
            supervisor.event(stream, stage=current, state="EXIT_OBSERVED", exit_code=2)
            return 2
        return execute_fixture(command, directory, current, stream)

    with pytest.raises(RuntimeError, match="observed OS exit 2"):
        start(bound, failing)
    assert calls == (["mirror"] if stage == "mirror" else ["mirror", "measure"])
    assert read_sealed(bound[-1] / "failure.json")["error"] == "RuntimeError"
    assert not (bound[-1] / "summary.json").exists()


def test_exit_zero_without_receipt_never_launches_measure(bound):
    calls = []

    def missing(command, directory, stage, stream):
        calls.append(stage)
        return 0

    with pytest.raises(InputCoverageError, match="cannot be read"):
        start(bound, missing)
    assert calls == ["mirror"]
    assert (bound[-1] / "failure.json").exists()


def test_pin_drift_stops_before_launch(bound):
    (bound[0] / "pinned.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA pin"):
        start(bound)
    assert not Path(bound[2]["workspace"]).exists()
    assert (bound[-1] / "failure.json").exists()


def test_drift_between_stages_stops_measure(bound):
    calls = []

    def drift(command, directory, stage, stream):
        calls.append(stage)
        result = execute_fixture(command, directory, stage, stream)
        (bound[0] / "pinned.bin").write_bytes(b"changed")
        return result

    with pytest.raises(ValueError, match="SHA pin"):
        start(bound, drift)
    assert calls == ["mirror"]


def test_mirror_seal_drift_stops_measure(bound):
    def tamper(command, directory, stage, stream):
        execute_fixture(command, directory, stage, stream)
        receipt = Path(bound[2]["workspace"]) / "mirror.json"
        raw = json.loads(receipt.read_text())
        raw["total_bytes"] += 1
        receipt.write_text(json.dumps(raw))
        return 0

    with pytest.raises(ValueError):
        start(bound, tamper)
    assert not (Path(bound[2]["workspace"]) / "measurement.json").exists()


@pytest.mark.parametrize("code", [0, 2])
def test_actual_subprocess_exit_and_durable_output(tmp_path, code):
    with (tmp_path / "events.jsonl").open("x") as stream:
        result = supervisor.run_stage(
            [sys.executable, "-c", f"print('fixture only'); raise SystemExit({code})"],
            tmp_path,
            "mirror",
            stream,
        )
    assert result == code
    assert "fixture only" in (tmp_path / "mirror.stdout.log").read_text()
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text().splitlines()
    ]
    assert events[-1]["exit_code"] == code
    assert events[0]["pid"] > 0


def test_final_measurement_binding_required(bound):
    def corrupt(command, directory, stage, stream):
        execute_fixture(command, directory, stage, stream)
        if stage == "measure":
            path = Path(bound[2]["workspace"]) / "measurement.json"
            raw = read_sealed(path)
            raw.pop("digest")
            raw["mirror_digest"] = "wrong"
            path.unlink()  # Owned temporary fixture only, not an external run.
            probe.new_report(path, raw)
        return 0

    with pytest.raises(ValueError, match="measurement binding"):
        start(bound, corrupt)
    assert not (bound[-1] / "summary.json").exists()


def test_real_cli_chain_on_temporary_byte_fixtures(tmp_path):
    # Repository-relative fixture profile is required by the unchanged policy.
    # TemporaryDirectory owns only its generated test files, never real artifacts.
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="storage_test_", dir=root) as fixture:
        fixture = Path(fixture)
        source = tmp_path / "source"
        source.mkdir()
        (source / "opaque.bin").write_bytes(b"fixture only\r\n")
        parent = {}
        for name, status in (
            ("summary", "PASS_COMPLETE_EXPANDED_CALIBRATION_PREPROCESSING_ONLY"),
            ("verification", "PASS_VERIFIED_EXPANDED_CALIBRATION_PREPROCESSING_ONLY"),
        ):
            path = source / f"{name}.json"
            probe.new_report(path, {"status": status})
            parent[f"{name}_sha256"] = probe._hash(path)
        profile = fixture / "profile.json"
        profile.write_text(json.dumps({"preprocessing_parent": parent}))
        config = fixture / "config.json"
        config.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "ISOLATED_STORAGE_PROBE_V1",
                    "boundary": probe.BOUNDARY,
                    "repetitions": 1,
                    "source_pins": [],
                    "productive_profile": {
                        "path": profile.relative_to(root).as_posix(),
                        "sha256": probe._hash(profile),
                    },
                    "source_directory": str(source),
                    "workspace": str(tmp_path / "work"),
                }
            )
        )
        args = [
            "--repository-root",
            str(root),
            "--config",
            str(config),
            "--config-sha256",
            probe._hash(config),
            "--probe-sha256",
            probe._hash(root / "src/dante_workflow/storage_probe.py"),
            "--runner-sha256",
            probe._hash(root / "scripts/benchmark_dante_workflow_storage.py"),
            "--supervisor-sha256",
            probe._hash(root / "src/dante_workflow/storage_supervisor.py"),
            "--log-directory",
            str(tmp_path / "logs"),
        ]
        assert supervisor.main(args) == 0
        events = [
            json.loads(line)
            for line in (tmp_path / "logs/events.jsonl").read_text().splitlines()
        ]
        assert [
            (e["stage"], e["exit_code"])
            for e in events
            if e["state"] == "EXIT_OBSERVED"
        ] == [("mirror", 0), ("measure", 0)]
        assert read_sealed(tmp_path / "logs/summary.json")["boundary"] == probe.BOUNDARY

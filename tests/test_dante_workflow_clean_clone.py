"""Technical-smoke boundaries; no scientific execution in unit tests."""

import json
from types import SimpleNamespace

import pytest

from scripts import run_dante_workflow_clean_clone as smoke
from src.dante_light.contracts import ContractError


def test_frozen_smoke_selects_one_background_identity_per_detector():
    config = smoke.load_config()
    source = smoke.ReplayManifestSource(smoke.ROOT / "config/dante_light_replay_v1.json", root=smoke.ROOT)
    tasks = source.tasks(roles={config["role"]}, limit_per_detector=config["limit_per_detector"])
    assert [task.window.detector for task in tasks] == ["H1", "L1"]


@pytest.mark.parametrize("field,value", [("scope", "production"), ("limit_per_detector", 0), ("timeout_seconds", True)])
def test_invalid_scope_and_limits_fail_closed(tmp_path, field, value):
    config = smoke.load_config()
    config[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ContractError):
        smoke.load_config(path)


def test_reference_drift_rejected(tmp_path):
    config = smoke.load_config()
    config["references"]["config/reference_artifacts.json"] = "0" * 64
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ContractError, match="reference mismatch"):
        smoke.load_config(path)


def test_command_forces_public_sources_without_recalibration(tmp_path):
    cmd = smoke.replay_command(smoke.load_config(), tmp_path, "canonical", "cpu")
    assert "dante-light-replay" in cmd
    assert cmd[cmd.index("--strain-source") + 1] == "gwosc-only"
    assert cmd[cmd.index("--cat1-mode") + 1] == "gwosc"
    assert "calibrate" not in " ".join(cmd)


def test_artifact_change_or_path_escape_rejected(tmp_path):
    artifact = tmp_path / "receipt.json"
    artifact.write_text("{}")
    files = {"receipt.json": smoke.sha(artifact)}
    smoke.verify_files(files, tmp_path)
    artifact.write_text("changed")
    with pytest.raises(ContractError):
        smoke.verify_files(files, tmp_path)
    with pytest.raises(ContractError):
        smoke.verify_files({"../escape": "0" * 64}, tmp_path)


def test_lock_is_exclusive_and_reusable(tmp_path):
    with smoke.exclusive_lock(tmp_path):
        with pytest.raises(OSError):
            with smoke.exclusive_lock(tmp_path):
                pytest.fail("duplicate execution")
    with smoke.exclusive_lock(tmp_path):
        pass


def test_completed_smoke_resume_verifies_without_running(tmp_path, monkeypatch):
    config = smoke.load_config()
    task = SimpleNamespace(window=SimpleNamespace(window_id="fixture", to_dict=lambda: {"id": "fixture"}))
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    monkeypatch.setattr(smoke, "load_config", lambda: config)
    monkeypatch.setattr(smoke, "git_checkout_provenance", lambda _: {"commit": "a" * 40})
    monkeypatch.setattr(smoke, "ReplayManifestSource", lambda *a, **kw: SimpleNamespace(tasks=lambda **kw: [task]))
    monkeypatch.setattr(smoke.importlib.metadata, "version", lambda _: "fixture")
    plan = smoke.run("plan", "cpu")
    directory = tmp_path / "artifacts/dante_workflow/public_smoke_v1" / plan["run_key"]
    directory.mkdir(parents=True)
    artifact = directory / "report.md"
    artifact.write_text("fixture only")
    files = {artifact.relative_to(tmp_path).as_posix(): smoke.sha(artifact)}
    smoke.atomic_json(directory / "technical_receipt.json", {"scope": smoke.SCOPE, "identity": plan["identity"], "files": files})
    # Default root is bound at definition time; keep real hash validation in this fixture.
    original_verify = smoke.verify_files
    monkeypatch.setattr(smoke, "verify_files", lambda files: original_verify(files, tmp_path))
    monkeypatch.setattr(smoke, "download_reference_bundle", lambda _: pytest.fail("already complete"))
    assert smoke.run("local", "cpu")["status"] == "SKIPPED_VERIFIED_TECHNICAL_SMOKE"
    artifact.write_text("corrupt")
    with pytest.raises(ContractError):
        smoke.run("verify", "cpu")

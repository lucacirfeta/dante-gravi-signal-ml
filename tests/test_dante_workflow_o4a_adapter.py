from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.dante_workflow.adapters import (
    AdapterError,
    O4aCorrectedAdapter,
    WorkflowPaths,
)
from src.dante_workflow.schema import REQUIRED_STAGE_NAMES, load_workflow_spec


ROOT = Path(__file__).resolve().parents[1]
SPEC = load_workflow_spec(
    ROOT / "config/dante_workflow_productization_v1.json", root=ROOT
)


@pytest.fixture
def adapter() -> O4aCorrectedAdapter:
    return O4aCorrectedAdapter(SPEC)


@pytest.fixture
def paths(tmp_path: Path) -> WorkflowPaths:
    return WorkflowPaths(
        repository_root=ROOT,
        raw_root=tmp_path / "raw",
        cache_root=tmp_path / "cache",
    )


def test_adapter_covers_every_frozen_stage_with_existing_clis(
    adapter: O4aCorrectedAdapter, paths: WorkflowPaths
) -> None:
    for stage in REQUIRED_STAGE_NAMES:
        run_command = adapter.build_command(stage, "run", paths)
        verify_command = adapter.build_command(stage, "verify", paths)

        assert (ROOT / run_command.argv[1]).is_file()
        assert (ROOT / verify_command.argv[1]).is_file()
        expected_prefix = SPEC.stage(stage).verifier_command
        assert ("python", *verify_command.argv[1 : len(expected_prefix)]) == expected_prefix
        source = (ROOT / run_command.argv[1]).read_text(encoding="utf-8")
        flags = {
            token
            for token in (*run_command.argv, *verify_command.argv)
            if token.startswith("--")
        }
        for flag in flags:
            assert f'"{flag}"' in source or f"'{flag}'" in source


def test_commands_bind_only_stage_scientific_config_digests(
    adapter: O4aCorrectedAdapter, paths: WorkflowPaths
) -> None:
    command = adapter.build_command("RESCORE", "run", paths)

    assert command.scientific_config_digests == {
        name: SPEC.scientific_configs[name].sha256
        for name in SPEC.stage("RESCORE").config_refs
    }
    assert "score" not in command.to_dict()
    assert "class" not in command.to_dict()
    assert "threshold" not in command.to_dict()
    assert command.command_digest == command.to_dict()["command_digest"]


def test_rescore_command_translates_all_roots_without_scientific_values(
    adapter: O4aCorrectedAdapter, paths: WorkflowPaths
) -> None:
    command = adapter.build_command("RESCORE", "run", paths)
    argv = command.argv
    roots = adapter.cache_roots(paths)

    assert argv[:4] == (
        "python",
        "scripts/run_dante_o4a_native_rescore_v2.py",
        "--stage",
        "run",
    )
    for flag, root_name in (
        ("--primary-external-root", "primary"),
        ("--native-external-root", "cohort"),
        ("--calibration-external-root", "native_calibration"),
        ("--index-external-root", "index"),
        ("--external-root", "rescore"),
    ):
        position = argv.index(flag)
        assert argv[position + 1] == str(roots[root_name])
    assert "--raw-root" in argv
    assert "--device" in argv
    assert "cuda" in argv
    assert "--workers" not in argv
    assert "--batch-size" not in argv


def test_native_calibration_is_a_distinct_cli_stage(
    adapter: O4aCorrectedAdapter, paths: WorkflowPaths
) -> None:
    run_command = adapter.build_command("NATIVE_CALIBRATION", "run", paths)
    verify_command = adapter.build_command("NATIVE_CALIBRATION", "verify", paths)

    assert run_command.argv[1:4] == (
        "scripts/run_dante_o4a_native_calibration.py",
        "--stage",
        "freeze",
    )
    assert verify_command.argv[1:4] == (
        "scripts/run_dante_o4a_native_calibration.py",
        "--stage",
        "verify",
    )


def test_index_window_manifest_receipt_reuses_exact_cohort_bytes(
    adapter: O4aCorrectedAdapter, tmp_path: Path
) -> None:
    cohort = tmp_path / "native_cohort.jsonl"
    cohort.write_bytes(b'{"detector":"H1","gps_start":1}\n')

    receipt = adapter.index_window_manifest_receipt(cohort)

    assert receipt.name == "index_window_manifest"
    assert receipt.path == str(cohort.resolve())
    assert receipt.sha256 == hashlib.sha256(cohort.read_bytes()).hexdigest()


def test_adapter_rejects_unknown_stage_or_action(
    adapter: O4aCorrectedAdapter, paths: WorkflowPaths
) -> None:
    with pytest.raises(AdapterError, match="unsupported corrected O4a stage"):
        adapter.build_command("UNKNOWN", "run", paths)
    with pytest.raises(AdapterError, match="unsupported stage action"):
        adapter.build_command("SCAN", "repair", paths)

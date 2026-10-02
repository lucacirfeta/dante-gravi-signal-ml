"""Driver-only author waiver; never numerical equivalence or productive bypass."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from src.dante_light import o3a_native_contract as native
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_workflow import o3a_retained_runtime as retained
from src.dante_workflow.o3a_initial_verification import _Evidence

ROOT = Path(__file__).resolve().parents[1]


def sealed_environment(value):
    body = copy.deepcopy(value)
    body.pop("environment_digest", None)
    return {**body, "environment_digest": canonical_json_sha256(body)}


@pytest.fixture
def environments():
    frozen = native.load_runtime_contract(root=ROOT)["runtime_environment"]
    observed = copy.deepcopy(frozen)
    observed["cuda_device"]["driver_version"] = "synthetic-other-driver"
    return frozen, sealed_environment(observed)


@pytest.fixture
def evidence(tmp_path):
    path = tmp_path / retained.POLICY_REL
    path.parent.mkdir(parents=True)
    path.write_bytes((ROOT / retained.POLICY_REL).read_bytes())
    return tmp_path, retained.RetainedRuntimeEvidence(tmp_path)


def test_driver_only_change_disclosed_not_equivalence(environments):
    frozen, observed = environments
    before = copy.deepcopy((frozen, observed))
    result = retained.compare_retained_runtime(frozen, observed)
    assert result["driver_version_changed"] is True
    assert result["driver_version_comparison_waived"] is True
    assert result["observed_environment_digest"] != result["frozen_environment_digest"]
    assert all(value is False for value in result["boundary"].values())
    assert (frozen, observed) == before


def test_equal_driver_still_explicit_qualification(environments):
    frozen, _ = environments
    assert (
        retained.compare_retained_runtime(frozen, frozen)["driver_version_changed"]
        is False
    )


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("packages", "numpy", "other"),
        ("packages", "torch", "other"),
        ("python", "executable_sha256", "0" * 64),
        ("operating_system", "release", "other"),
        ("cuda_device", "name", "other"),
        ("cuda_device", "capability", [0, 0]),
        ("cuda_device", "device_count", 2),
        ("cuda_device", "request", "cpu"),
        ("torch", "cudnn_version", 0),
        ("torch", "deterministic_algorithms_enabled", 1),
    ],
)
def test_resealed_other_runtime_drift_refused(environments, section, field, value):
    frozen, observed = environments
    observed[section][field] = value
    with pytest.raises(ValueError, match="beyond driver"):
        retained.compare_retained_runtime(frozen, sealed_environment(observed))


@pytest.mark.parametrize("which", [0, 1])
def test_environment_digest_is_not_ignored(environments, which):
    values = list(copy.deepcopy(environments))
    values[which]["environment_digest"] = "0" * 64
    with pytest.raises(ValueError, match="seal"):
        retained.compare_retained_runtime(*values)


@pytest.mark.parametrize("value", [None, "", 123])
def test_missing_driver_is_not_an_open_waiver(environments, value):
    frozen, observed = environments
    observed["cuda_device"]["driver_version"] = value
    with pytest.raises(ValueError, match="metadata is absent"):
        retained.compare_retained_runtime(frozen, sealed_environment(observed))


def test_explicit_default_remains_strict(tmp_path):
    calls = []

    def loader(**kwargs):
        calls.append(kwargs)
        raise ContractError("STOP_ENVIRONMENT_MISMATCH")

    obj = retained.new_evidence(tmp_path)
    assert type(obj) is _Evidence
    assert retained.receipt_fields(obj) == {}
    with pytest.raises(ContractError, match="STOP_ENVIRONMENT"):
        retained.load_runtime(obj, loader, root=tmp_path)
    assert calls == [{"root": tmp_path, "require_current": True}]


def test_qualified_runtime_retains_frozen_keys_and_receipt(
    evidence, environments, monkeypatch
):
    root, obj = evidence
    frozen, observed = environments
    calls = []

    def loader(**kwargs):
        calls.append(kwargs)
        return {"runtime_environment": frozen}

    monkeypatch.setattr(
        native, "_capture_o3a_runtime", lambda device: copy.deepcopy(observed)
    )
    for _ in range(7):
        assert (
            retained.load_runtime(obj, loader, root=root)["runtime_environment"]
            == frozen
        )
    obj.unchanged()
    receipt = retained.receipt_fields(obj)["retained_runtime_qualification"]
    assert receipt["observed_driver_version"] == "synthetic-other-driver"
    assert len(receipt["policy_sha256"]) == 64
    assert all(item["require_current"] is False for item in calls)
    receipt["boundary"]["fresh_scoring_authorized"] = True
    assert obj.qualification()["boundary"]["fresh_scoring_authorized"] is False


@pytest.mark.parametrize("when", ["parent", "final"])
def test_mid_replay_driver_change_refused(evidence, environments, monkeypatch, when):
    root, obj = evidence
    frozen, observed = environments
    monkeypatch.setattr(native, "_capture_o3a_runtime", lambda device: observed)

    def loader(**kwargs):
        return {"runtime_environment": frozen}

    retained.load_runtime(obj, loader, root=root)
    changed = copy.deepcopy(observed)
    changed["cuda_device"]["driver_version"] = "yet-another"
    monkeypatch.setattr(
        native, "_capture_o3a_runtime", lambda device: sealed_environment(changed)
    )
    with pytest.raises(ValueError, match="during retained replay"):
        if when == "parent":
            retained.load_runtime(obj, loader, root=root)
        else:
            obj.unchanged()


def test_policy_changed_refused_before_or_after(evidence, environments, monkeypatch):
    root, obj = evidence
    frozen, observed = environments
    monkeypatch.setattr(native, "_capture_o3a_runtime", lambda device: observed)
    retained.load_runtime(
        obj, lambda **kwargs: {"runtime_environment": frozen}, root=root
    )
    path = root / retained.POLICY_REL
    changed = copy.deepcopy(retained.POLICY)
    changed["ignored_metadata_fields"].append("packages.torch")
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="policy changed"):
        retained.RetainedRuntimeEvidence(root)
    with pytest.raises(ValueError, match="evidence changed"):
        obj.unchanged()


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_nonboolean_opt_in_refused(tmp_path, value):
    with pytest.raises(ValueError, match="boolean"):
        retained.new_evidence(tmp_path, allow_retained_driver_drift=value)


def test_unchecked_waiver_cannot_emit_receipt(evidence):
    _, obj = evidence
    with pytest.raises(ValueError, match="never checked"):
        obj.qualification()
    with pytest.raises(ValueError, match="never checked"):
        obj.unchanged()


def test_productive_runtime_guard_not_modified(environments, monkeypatch):
    _, observed = environments
    monkeypatch.setattr(native, "_capture_o3a_runtime", lambda device: observed)
    with pytest.raises(ContractError, match="STOP_ENVIRONMENT_MISMATCH"):
        native.load_runtime_contract(root=ROOT, require_current=True)


def test_calibration_directory_strict_default_calls_original(tmp_path, monkeypatch):
    from src.dante_light import o3a_native_calibration_cohort as calibration
    from src.dante_workflow import o3a_score_verification as scores

    seen = []

    def strict(contract, **kwargs):
        seen.append((contract, kwargs))
        raise ContractError("STOP_ENVIRONMENT_MISMATCH")

    monkeypatch.setattr(calibration, "_run_dir", strict)
    contract = {"contract_digest": "synthetic"}
    with pytest.raises(ContractError, match="STOP_ENVIRONMENT"):
        scores._calibration_directory(
            root=tmp_path,
            external_root=tmp_path,
            contract=contract,
            runtime={},
            evidence=_Evidence(),
        )
    assert seen == [(contract, {"root": tmp_path, "external_root": tmp_path})]


def calibration_key_contract():
    # Unit path parity is portable; productive contract rebuilding is WSL-only.
    from src.dante_light import o3a_native_calibration_cohort as calibration

    value = json.loads((ROOT / calibration.CONTRACT_REL).read_bytes())
    body = dict(value)
    seal = body.pop("contract_digest")
    assert seal == canonical_json_sha256(body)
    return value


def test_qualified_calibration_directory_matches_original_key(
    evidence, environments, monkeypatch
):
    from src.dante_light import o3a_native_calibration_cohort as calibration
    from src.dante_workflow import o3a_score_verification as scores

    root, obj = evidence
    frozen, observed = environments
    runtime = {"runtime_environment": frozen}
    contract = calibration_key_contract()
    before = copy.deepcopy((runtime, contract))
    monkeypatch.setattr(native, "_capture_o3a_runtime", lambda device: observed)
    retained.load_runtime(obj, lambda **kwargs: runtime, root=root)
    calls = []

    def historically_exact(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr(calibration, "load_runtime_contract", historically_exact)
    original = calibration._run_dir(
        contract, root=root, external_root=root / "external"
    )
    assert calls == [{"root": root, "require_current": True}]
    monkeypatch.setattr(
        calibration,
        "_run_dir",
        lambda *args, **kwargs: pytest.fail("productive resolver called under opt-in"),
    )
    assert (
        scores._calibration_directory(
            root=root,
            external_root=root / "external",
            contract=contract,
            runtime=runtime,
            evidence=obj,
        )
        == original
    )
    assert (runtime, contract) == before
    obj.unchanged()


@pytest.mark.parametrize("change", ["seal", "environment", "parent"])
def test_qualified_calibration_directory_rejects_substituted_identity(
    evidence, environments, monkeypatch, change
):
    from src.dante_workflow import o3a_score_verification as scores

    root, obj = evidence
    frozen, observed = environments
    runtime = {"runtime_environment": copy.deepcopy(frozen)}
    contract = calibration_key_contract()
    monkeypatch.setattr(native, "_capture_o3a_runtime", lambda device: observed)
    retained.load_runtime(obj, lambda **kwargs: runtime, root=root)
    if change == "seal":
        runtime["runtime_environment"]["environment_digest"] = "0" * 64
    elif change == "environment":
        runtime["runtime_environment"] = observed
    else:
        contract["parents"]["runtime"]["environment_digest"] = "0" * 64
    with pytest.raises(ValueError, match="runtime identity changed"):
        scores._calibration_directory(
            root=root,
            external_root=root,
            contract=contract,
            runtime=runtime,
            evidence=obj,
        )


def test_calibration_directory_requires_completed_qualification(evidence):
    from src.dante_workflow import o3a_score_verification as scores

    root, obj = evidence
    with pytest.raises(ValueError, match="never checked"):
        scores._calibration_directory(
            root=root,
            external_root=root,
            contract={},
            runtime={},
            evidence=obj,
        )


def test_all_seven_existing_read_only_runtime_calls_wired():
    files = [
        "o3a_native_verification.py",
        "o3a_index_verification.py",
        "o3a_score_verification.py",
        "o3a_decision_verification.py",
        "o3a_coincidence_verification.py",
    ]
    calls = []
    for filename in files:
        tree = ast.parse((ROOT / "src/dante_workflow" / filename).read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "load_runtime"
            ):
                assert (
                    isinstance(node.args[0], ast.Name) and node.args[0].id == "evidence"
                )
                assert (
                    isinstance(node.args[1], ast.Attribute)
                    and node.args[1].attr == "load_runtime_contract"
                )
                calls.append(node)
    assert len(calls) == 7


@pytest.mark.parametrize("script", ["coincidence", "pem"])
def test_cli_opt_in_explicit_and_default_false(monkeypatch, script, capsys):
    from src.dante_workflow import o3a_coincidence_verification as coin
    from src.dante_workflow import o3a_pem_verification as pem
    from src.dante_workflow import evidence_snapshot as snapshots

    spec = importlib.util.spec_from_file_location(
        "waiver_cli", ROOT / f"scripts/verify_dante_o3a_{script}_evidence.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    seen = []

    def verify(**kwargs):
        seen.append(kwargs["allow_retained_driver_drift"])
        return {"status": "SYNTHETIC_ARGUMENT_WIRING_ONLY"}

    args = []
    if script == "coincidence":
        monkeypatch.setattr(coin, "verify_coincidence_evidence", verify)
        names = ["external-root"] + [
            f"{n}-external-root"
            for n in [
                "taxonomy",
                "classification",
                "threshold",
                "rescore",
                "calibration",
                "index",
                "cohort",
                "primary",
            ]
        ]
    else:
        monkeypatch.setattr(pem, "verify_pem_evidence", verify)
        monkeypatch.setattr(
            snapshots, "read_snapshot_blob", lambda *a, **kw: b"synthetic"
        )
        args += [
            "--snapshot",
            "synthetic",
            "--expected-snapshot-sha256",
            "s",
            "--expected-plan-sha256",
            "p",
        ]
        names = [
            f"{n}-external-root"
            for n in [
                "pem",
                "coincidence",
                "taxonomy",
                "classification",
                "threshold",
                "rescore",
                "calibration",
                "index",
                "cohort",
                "primary",
            ]
        ]
    for name in names:
        args += ["--" + name, str(ROOT)]
    assert cli.main(args) == 0
    assert cli.main(args + ["--allow-retained-driver-drift"]) == 0
    assert seen == [False, True]
    capsys.readouterr()

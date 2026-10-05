"""Exact historical/current provenance qualification, never a newline waiver."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.dante_workflow import expanded_preprocessing_binding as binding
from src.dante_workflow.calibration_recovery import sealed, write_json

from src.dante_workflow.expanded_preprocessing_binding import (
    BOUNDARY,
    SOURCES,
    qualify_bytes,
    representation_check,
)
from src.dante_workflow.input_coverage import InputCoverageError


def sha(data):
    return hashlib.sha256(data).hexdigest()


def test_exact_historical_and_current_pins():
    historical = b"first\nsecond\n"
    current = historical.replace(b"\n", b"\r\n")
    result = qualify_bytes(
        current,
        current_sha=sha(current),
        historical_sha=sha(historical),
        relation="EXACT_LF_TO_CRLF_RECONSTRUCTION",
    )
    assert result["historical_sha256"] == sha(historical)
    assert current == b"first\r\nsecond\r\n"


@pytest.mark.parametrize(
    "fault", ["current", "historical", "relation", "mixed", "content"]
)
def test_qualification_fails_closed(fault):
    historical, current = b"a\nb\n", b"a\r\nb\r\n"
    kwargs = dict(
        current_sha=sha(current),
        historical_sha=sha(historical),
        relation="EXACT_LF_TO_CRLF_RECONSTRUCTION",
    )
    if fault == "current":
        kwargs["current_sha"] = "0" * 64
    elif fault == "historical":
        kwargs["historical_sha"] = "0" * 64
    elif fault == "relation":
        kwargs["relation"] = "NORMALIZE_ANYTHING"
    elif fault == "mixed":
        current = b"a\r\nb\n"
        kwargs["current_sha"] = sha(current)
    else:
        current = b"changed\r\nb\r\n"
        kwargs["current_sha"] = sha(current)
    with pytest.raises(InputCoverageError):
        qualify_bytes(current, **kwargs)


def test_exact_bytes_relation():
    data = b"pinned\n"
    qualify_bytes(
        data, current_sha=sha(data), historical_sha=sha(data), relation="EXACT_BYTES"
    )
    with pytest.raises(InputCoverageError):
        qualify_bytes(
            data,
            current_sha=sha(data),
            historical_sha=sha(b"other"),
            relation="EXACT_BYTES",
        )


@pytest.fixture
def representation():
    protocol = {
        "representation": dict(
            query_qrange=[2, 7],
            frequency_range_hz=[11, 97],
            image_shape=[12, 18, 3],
            colormap="test",
        )
    }
    config = {
        "preprocessing": dict(
            qrange=[2, 7], frange=[11, 97], output_size=[12, 18], colormap="test"
        )
    }
    return protocol, config


def test_representation_uses_parent_not_default_constants(representation):
    protocol, config = representation
    assert representation_check(protocol, config) == protocol["representation"]


@pytest.mark.parametrize("key", ["qrange", "frange", "output_size", "colormap"])
def test_changed_representation_rejected(representation, key):
    protocol, original = representation
    config = deepcopy(original)
    config["preprocessing"][key] = "changed" if key == "colormap" else [0, 1]
    with pytest.raises(InputCoverageError):
        representation_check(protocol, config)


def test_contract_boundary_and_exact_current_pins():
    root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (
            root / "config/dante_workflow_expanded_preprocessing_binding_v1.json"
        ).read_text()
    )
    protocol = json.loads((root / contract["protocol"]["path"]).read_text())
    assert contract["boundary"] == BOUNDARY
    assert contract["source_paths"] == list(SOURCES)
    for role, row in contract["current_source_qualification"].items():
        ref = protocol["source_references"][role]
        qualify_bytes(
            (root / ref["path"]).read_bytes(),
            current_sha=row["sha256"],
            historical_sha=ref["sha256"],
            relation=row["historical_relation"],
        )


@pytest.fixture
def full_case(tmp_path, monkeypatch, representation):
    root, native = tmp_path / "repo", tmp_path / "native"
    root.mkdir()
    native.mkdir()
    protocol, config = deepcopy(representation)
    protocol["representation"].update(
        sample_rate_hz=4, analysis_duration_s=2, whitening_pad_s=1
    )
    protocol["execution_parameters"] = {
        "primary_calibration": {"workers": 1, "batch_size": 2}
    }
    protocol["source_references"] = {}
    qualified = {}
    for role, data in (
        ("patch_producer", b"pinned\n"),
        ("preprocessor", b"preprocess\r\n"),
        ("runtime_config", yaml.safe_dump(config).encode().replace(b"\n", b"\r\n")),
        ("raw_window_validity_audit", b"{}"),
        ("dq_snapshot", b"{}"),
    ):
        path = root / role
        path.write_bytes(data)
        historical = data.replace(b"\r\n", b"\n")
        protocol["source_references"][role] = {"path": role, "sha256": sha(historical)}
        if role not in ("raw_window_validity_audit", "dq_snapshot"):
            qualified[role] = {
                "sha256": sha(data),
                "historical_relation": "EXACT_LF_TO_CRLF_RECONSTRUCTION"
                if b"\r\n" in data
                else "EXACT_BYTES",
            }
    protocol_path = root / "protocol.json"
    write_json(protocol_path, protocol)
    (root / "native-contract.json").write_text("{}")
    bind_path = tmp_path / "binding.json"
    write_json(bind_path, sealed({"test": "bound"}))
    native_binding = sealed(
        dict(
            identity_count=3,
            identity_counts={"H1": 2, "L1": 1},
            context_keys_sha256="synthetic-union",
        )
    )
    summary = sealed(
        dict(
            status="PASS_COMPLETE_EXPANDED_NATIVE_CONSUMER_ONLY",
            binding=native_binding,
            record_count=2,
        )
    )
    write_json(native / "summary.json", summary)
    verified = sealed(
        dict(
            status="PASS_VERIFIED_EXPANDED_NATIVE_CONSUMER_ONLY",
            binding=native_binding,
            record_count=2,
            summary_digest=summary["digest"],
            summary_sha256=binding._hash(native / "summary.json"),
        )
    )
    write_json(native / "verification.json", verified)
    contract = dict(
        schema_version=1,
        status="INHERITED_CALIBRATION_PREPROCESSING_BINDING_ONLY_V1",
        source_paths=list(SOURCES),
        boundary=BOUNDARY,
        protocol={"path": "protocol.json", "sha256": binding._hash(protocol_path)},
        current_source_qualification=qualified,
        native_replay=dict(
            contract_path="native-contract.json",
            contract_sha256="pinned",
            source_freeze="f" * 40,
            summary_sha256=binding._hash(native / "summary.json"),
            verification_sha256=binding._hash(native / "verification.json"),
        ),
        calibration_validity_rule="synthetic finite rule",
        preprocessing_order="inherited",
    )
    contract_path = root / "contract.json"
    write_json(contract_path, contract)
    provider = SimpleNamespace(allowed=frozenset({("H1", 10, 14), ("L1", 20, 24)}))
    provider.planned = {
        key: dict(sample_rate_hz=4, sample_count=16) for key in provider.allowed
    }
    provider.read = lambda **kw: pytest.fail(
        "metadata binding must not read raw or measure"
    )
    monkeypatch.setattr(binding, "source_audit", lambda *a: {"synthetic": "pinned"})
    monkeypatch.setattr(binding, "native_bind", lambda **kw: (provider, native_binding))
    return SimpleNamespace(
        root=root,
        native=native,
        contract=contract,
        contract_path=contract_path,
        provider=provider,
        native_binding=native_binding,
        summary=summary,
        verified=verified,
        args=dict(
            root=root,
            contract_path=contract_path,
            contract_sha=binding._hash(contract_path),
            source_freeze="f" * 40,
            recovery_dir=tmp_path / "recovery",
            native_dir=native,
            binding_path=bind_path,
            binding_sha=binding._hash(bind_path),
        ),
    )


def test_full_binding_only_preserves_population_without_measurements(full_case):
    result = binding.preflight(**full_case.args)
    assert result["context_count"] == 2
    assert result["identity_count"] == 3
    assert result["identity_counts"] == {"H1": 2, "L1": 1}
    assert result["boundary"] == BOUNDARY
    assert result["population_reduced"] is False
    assert result["new_dq_filter_applied"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "bool_version",
        "numeric_boundary",
        "summary_status",
        "verification_status",
        "binding",
        "count",
        "summary_digest",
        "geometry",
        "rate",
        "grid",
        "source",
        "lock",
    ],
)
def test_full_binding_rejects_faults(full_case, fault):
    c = full_case
    if fault in ("bool_version", "numeric_boundary"):
        c.contract = deepcopy(c.contract)
        if fault == "bool_version":
            c.contract["schema_version"] = True
        else:
            c.contract["boundary"]["method_and_input_binding_only"] = 1
        write_json(c.contract_path, c.contract)
        c.args["contract_sha"] = binding._hash(c.contract_path)
    elif fault == "summary_status":
        c.summary["status"] = "NOT_PASS"
        write_json(c.native / "summary.json", sealed(c.summary))
    elif fault in ("verification_status", "binding", "count", "summary_digest"):
        field, value = {
            "verification_status": ("status", "NOT_PASS"),
            "binding": ("binding", {}),
            "count": ("record_count", 1),
            "summary_digest": ("summary_digest", "wrong"),
        }[fault]
        c.verified[field] = value
        write_json(c.native / "verification.json", sealed(c.verified))
    elif fault == "geometry":
        c.provider.allowed = frozenset({("H1", 10, 13), ("L1", 20, 24)})
    elif fault in ("rate", "grid"):
        key = sorted(c.provider.allowed)[0]
        c.provider.planned[key][
            "sample_rate_hz" if fault == "rate" else "sample_count"
        ] = 3
    elif fault == "source":
        (c.root / "preprocessor").write_bytes(b"changed\r\n")
    else:
        (c.native / "controller.lock").write_text("active")
    # Repin mutated parents to test semantics separately from the exact byte guards.
    if fault in (
        "summary_status",
        "verification_status",
        "binding",
        "count",
        "summary_digest",
    ):
        c.contract["native_replay"]["summary_sha256"] = binding._hash(
            c.native / "summary.json"
        )
        c.contract["native_replay"]["verification_sha256"] = binding._hash(
            c.native / "verification.json"
        )
        write_json(c.contract_path, c.contract)
        c.args["contract_sha"] = binding._hash(c.contract_path)
    with pytest.raises((InputCoverageError, ValueError)):
        binding.preflight(**c.args)


def test_parent_changed_during_rebinding_rejected(full_case, monkeypatch):
    def mutate(**kw):
        (full_case.native / "verification.json").write_text("changed")
        return full_case.provider, full_case.native_binding

    monkeypatch.setattr(binding, "native_bind", mutate)
    with pytest.raises(InputCoverageError):
        binding.preflight(**full_case.args)


def test_existing_output_rejected_before_preflight(tmp_path, monkeypatch):
    output = tmp_path / "exists.json"
    output.write_text("preserve")
    monkeypatch.setattr(
        binding, "preflight", lambda **kw: pytest.fail("must reject before binding")
    )
    args = []
    for name in (
        "repository-root",
        "contract",
        "recovery-dir",
        "native-dir",
        "binding",
        "output",
    ):
        args.extend(["--" + name, str(output if name == "output" else tmp_path / name)])
    for name in ("contract-sha256", "source-freeze", "binding-sha256"):
        args.extend(["--" + name, "pin"])
    with pytest.raises(SystemExit):
        binding.main(args)
    assert output.read_text() == "preserve"

"""Bind inherited preprocessing, without executing it or changing a population."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from .calibration_admission import _pinned
from .calibration_expanded_admission import same
from .calibration_recovery import read_sealed, sealed, write_json
from .expanded_context_replay import bind as native_bind
from .expanded_context_replay import quiet
from .input_coverage import InputCoverageError
from .input_preflight import _file, _hash
from .schema_v2 import strict_json_object


SOURCES = (
    "src/dante_workflow/expanded_preprocessing_binding.py",
    "scripts/preflight_dante_workflow_expanded_preprocessing.py",
)
BOUNDARY = {
    "method_and_input_binding_only": True,
    "all_contexts_preprocessed": False,
    "full_context_validity_verified": False,
    "full_calibration_verified": False,
    "default_provider_replaced": False,
    "score_values_read": False,
    "o4b_launch_allowed": False,
}


def qualify_bytes(data, *, current_sha, historical_sha, relation):
    """Two exact pins, never generic newline normalization as an acceptance rule."""
    if hashlib.sha256(data).hexdigest() != current_sha:
        raise InputCoverageError("current preprocessing source bytes changed")
    if relation == "EXACT_BYTES":
        historical = data
    elif relation == "EXACT_LF_TO_CRLF_RECONSTRUCTION":
        historical = data.replace(b"\r\n", b"\n")
        if historical.replace(b"\n", b"\r\n") != data:
            raise InputCoverageError("not exact LF-to-CRLF reconstruction")
    else:
        raise InputCoverageError("unsupported historical source qualification")
    if hashlib.sha256(historical).hexdigest() != historical_sha:
        raise InputCoverageError("historical preprocessing source content changed")
    return dict(
        current_sha256=current_sha,
        historical_sha256=historical_sha,
        historical_relation=relation,
    )


def representation_check(protocol, config):
    rep = protocol["representation"]
    pre = config["preprocessing"]
    for name, key in (
        ("qrange", "query_qrange"),
        ("frange", "frequency_range_hz"),
        ("output_size", "image_shape"),
    ):
        expected = rep[key][:2] if key == "image_shape" else rep[key]
        if list(pre[name]) != expected:
            raise InputCoverageError(
                "preprocessing representation differs from protocol"
            )
    if pre["colormap"] != rep["colormap"]:
        raise InputCoverageError("preprocessing colormap differs from protocol")
    return rep


def source_audit(root, freeze):
    if not isinstance(freeze, str) or not re.fullmatch(r"[0-9a-f]{40}", freeze):
        raise InputCoverageError("full preprocessing binding source freeze required")
    hashes = {}
    for name in SOURCES:
        data = subprocess.run(
            ["git", "show", f"{freeze}:{name}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        sha = hashlib.sha256(data).hexdigest()
        _pinned(_file(root, name), sha)
        hashes[name] = sha
    if _hash(Path(__file__)) != hashes[SOURCES[0]]:
        raise InputCoverageError("executed binding source differs from freeze")
    return hashes


def preflight(
    *,
    root,
    contract_path,
    contract_sha,
    source_freeze,
    recovery_dir,
    native_dir,
    binding_path,
    binding_sha,
):
    import yaml

    root = Path(root).resolve()
    contract_path = _pinned(contract_path, contract_sha)
    contract = strict_json_object(
        contract_path.read_text(), label="preprocessing binding"
    )
    if (
        type(contract.get("schema_version")) is not int
        or contract.get("schema_version") != 1
        or contract.get("status")
        != "INHERITED_CALIBRATION_PREPROCESSING_BINDING_ONLY_V1"
        or contract.get("source_paths") != list(SOURCES)
        or not same(contract.get("boundary"), BOUNDARY)
    ):
        raise InputCoverageError("unsupported preprocessing binding authority")
    sources = source_audit(root, source_freeze)
    ref = contract["protocol"]
    protocol_path = _pinned(_file(root, ref["path"]), ref["sha256"])
    protocol = strict_json_object(protocol_path.read_text(), label="inherited protocol")
    qualified = {}
    for role, declared in contract["current_source_qualification"].items():
        inherited = protocol["source_references"][role]
        path = _file(root, inherited["path"])
        qualified[role] = {
            "path": inherited["path"],
            **qualify_bytes(
                path.read_bytes(),
                current_sha=declared["sha256"],
                historical_sha=inherited["sha256"],
                relation=declared["historical_relation"],
            ),
        }
    if set(qualified) != {"patch_producer", "preprocessor", "runtime_config"}:
        raise InputCoverageError("incomplete inherited preprocessing source set")
    config = yaml.safe_load(
        _file(root, qualified["runtime_config"]["path"]).read_text()
    )
    representation = representation_check(protocol, config)
    native_dir = Path(native_dir).resolve()
    quiet(native_dir)
    prior = contract["native_replay"]
    summary = read_sealed(_pinned(native_dir / "summary.json", prior["summary_sha256"]))
    verified = read_sealed(
        _pinned(native_dir / "verification.json", prior["verification_sha256"])
    )
    provider, binding = native_bind(
        root=root,
        contract_path=_file(root, prior["contract_path"]),
        contract_sha=prior["contract_sha256"],
        recovery_dir=recovery_dir,
        binding_path=binding_path,
        binding_sha=binding_sha,
        freeze=prior["source_freeze"],
    )
    if (
        summary["status"] != "PASS_COMPLETE_EXPANDED_NATIVE_CONSUMER_ONLY"
        or verified["status"] != "PASS_VERIFIED_EXPANDED_NATIVE_CONSUMER_ONLY"
        or not same(summary["binding"], binding)
        or not same(verified["binding"], binding)
        or verified["summary_digest"] != summary["digest"]
        or verified["summary_sha256"] != prior["summary_sha256"]
        or verified["record_count"] != len(provider.allowed)
        or summary["record_count"] != len(provider.allowed)
    ):
        raise InputCoverageError("native verified parent relationship differs")
    rate = representation["sample_rate_hz"]
    duration = representation["analysis_duration_s"]
    pad = representation["whitening_pad_s"]
    for key in provider.allowed:
        if key[2] - key[1] != duration + 2 * pad:
            raise InputCoverageError("inherited symmetric context geometry differs")
        row = provider.planned[key]
        if (
            row["sample_rate_hz"] != rate
            or row["sample_count"] != (key[2] - key[1]) * rate
        ):
            raise InputCoverageError("inherited native sample grid differs")
    validity = protocol["source_references"]["raw_window_validity_audit"]
    dq = protocol["source_references"]["dq_snapshot"]
    for inherited in (validity, dq):
        _pinned(_file(root, inherited["path"]), inherited["sha256"])
    # Recheck actual source bytes after slow parent rebinding, not a cached waiver.
    for row in qualified.values():
        _pinned(_file(root, row["path"]), row["current_sha256"])
    _pinned(contract_path, contract_sha)
    _pinned(protocol_path, ref["sha256"])
    _pinned(native_dir / "summary.json", prior["summary_sha256"])
    _pinned(native_dir / "verification.json", prior["verification_sha256"])
    _pinned(binding_path, binding_sha)
    quiet(native_dir)
    if source_audit(root, source_freeze) != sources:
        raise InputCoverageError("binding sources changed during preflight")
    return sealed(
        {
            "status": "PASS_INHERITED_PREPROCESSING_BINDING_ONLY",
            "contract_sha256": contract_sha,
            "source_freeze": source_freeze,
            "source_hashes": sources,
            "qualified_sources": qualified,
            "protocol": ref,
            "representation": representation,
            "execution_parameters": protocol["execution_parameters"][
                "primary_calibration"
            ],
            "native_summary_sha256": prior["summary_sha256"],
            "native_verification_sha256": prior["verification_sha256"],
            "native_binding_digest": binding["digest"],
            "identity_count": binding["identity_count"],
            "identity_counts": binding["identity_counts"],
            "context_count": len(provider.allowed),
            "context_keys_sha256": binding["context_keys_sha256"],
            "calibration_validity_rule": contract["calibration_validity_rule"],
            "preprocessing_order": contract["preprocessing_order"],
            "scan_validity_reference": validity,
            "dq_reference": dq,
            "new_dq_filter_applied": False,
            "population_reduced": False,
            "boundary": BOUNDARY,
        }
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "repository-root",
        "contract",
        "recovery-dir",
        "native-dir",
        "binding",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("contract-sha256", "source-freeze", "binding-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    output = args.output
    protected = (
        args.repository_root,
        args.recovery_dir,
        args.native_dir,
        args.binding.parent,
    )
    if (
        not output.is_absolute()
        or output.exists()
        or any(p.is_symlink() for p in (output, *output.parents))
        or any(output.resolve().is_relative_to(p.resolve()) for p in protected)
    ):
        parser.error("fresh external output outside preserved parents required")
    result = preflight(
        root=args.repository_root,
        contract_path=args.contract,
        contract_sha=args.contract_sha256,
        source_freeze=args.source_freeze,
        recovery_dir=args.recovery_dir,
        native_dir=args.native_dir,
        binding_path=args.binding,
        binding_sha=args.binding_sha256,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x"):
        pass
    write_json(output, result)
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("status", "digest", "context_count", "identity_count")
            },
            sort_keys=True,
        )
    )
    return 0

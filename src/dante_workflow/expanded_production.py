"""Explicit isolated productive input binding, never a global reader redirect."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .calibration_admission import _pinned
from .calibration_recovery import read_sealed, sealed, write_json
from .expanded_context_replay import isolated, quiet
from .expanded_preprocessing_replay import BOUNDARY as PREPROCESSING_BOUNDARY
from .expanded_preprocessing_replay import bind as preprocessing_bind
from .input_coverage import InputCoverageError
from .input_preflight import _file, _hash
from .schema_v2 import strict_json_object


SOURCES = (
    "src/dante_workflow/expanded_production.py",
    "scripts/preflight_dante_workflow_expanded_production.py",
)
INPUT_RULE = "entire verified expanded calibration context union through unchanged per-read native guards; no manifest, error fallback, historical shard or threshold reuse"
BOUNDARY = {
    "isolated_productive_input_binding_only": True,
    "default_provider_replaced": False,
    "full_calibration_verified": False,
    "encoder_scoring_runtime_qualified": False,
    "historical_scores_or_thresholds_reused": False,
    "candidate_scan_allowed": False,
    "o4b_launch_allowed": False,
}


def source_audit(root, freeze):
    if not isinstance(freeze, str) or not re.fullmatch(r"[0-9a-f]{40}", freeze):
        raise InputCoverageError("productive source freeze required")
    hashes = {}
    for name in SOURCES:
        data = subprocess.run(
            ["git", "show", f"{freeze}:{name}"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        hashes[name] = hashlib.sha256(data).hexdigest()
        _pinned(_file(root, name), hashes[name])
    if hashes[SOURCES[0]] != _hash(Path(__file__)):
        raise InputCoverageError("executed productive integration differs from freeze")
    return hashes


class IsolatedExpandedProductionProvider:
    """Whole exact-context reader with preprocessing prerequisite rehashed per read."""

    def __init__(self, delegate, pins, preprocessing_dir):
        self.delegate = delegate
        self.allowed = delegate.allowed
        self.pins = dict(pins)
        self.preprocessing_dir = preprocessing_dir

    def guard(self):
        quiet(self.preprocessing_dir)
        for path, sha in self.pins.items():
            _pinned(path, sha)

    def read(self, *, detector, start, end):
        self.guard()
        result = self.delegate.read(detector=detector, start=start, end=end)
        self.guard()
        return result


def bind(*, profile_path, profile_sha, source_freeze, preprocessing_dir, parent_args):
    root = Path(parent_args["root"]).resolve()
    profile_path = _pinned(profile_path, profile_sha)
    profile = strict_json_object(profile_path.read_text(), label="productive profile")
    if (
        type(profile.get("schema_version")) is not int
        or profile["schema_version"] != 1
        or profile.get("status") != "ISOLATED_EXPANDED_PRODUCTIVE_INPUT_PROFILE_V1"
        or profile.get("source_paths") != list(SOURCES)
        or profile.get("input_rule") != INPUT_RULE
        or profile.get("output_namespace") != "expanded_production_v1"
        or profile.get("automatic_resume") is not False
        or profile.get("boundary") != BOUNDARY
        or any(type(x) is not bool for x in profile["boundary"].values())
    ):
        raise InputCoverageError("unsupported isolated productive profile")
    sources = source_audit(root, source_freeze)
    approved = profile["approved_profile_parent"]
    approved_path = _pinned(_file(root, approved["path"]), approved["sha256"])
    ref = profile["preprocessing_parent"]
    kwargs = dict(
        **parent_args,
        contract_path=_file(root, ref["path"]),
        contract_sha=ref["sha256"],
        source_freeze=ref["source_freeze"],
    )
    directory = Path(preprocessing_dir).resolve()
    quiet(directory)
    pins = {
        profile_path: profile_sha,
        approved_path: approved["sha256"],
        kwargs["contract_path"]: ref["sha256"],
        _file(directory, "summary.json"): ref["summary_sha256"],
        _file(directory, "verification.json"): ref["verification_sha256"],
    }
    for path, sha in pins.items():
        _pinned(path, sha)
    summary = read_sealed(directory / "summary.json")
    verified = read_sealed(directory / "verification.json")
    delegate, parent = preprocessing_bind(**kwargs)
    method = parent["method"]
    if (
        summary.get("status") != "PASS_COMPLETE_EXPANDED_CALIBRATION_PREPROCESSING_ONLY"
        or verified.get("status")
        != "PASS_VERIFIED_EXPANDED_CALIBRATION_PREPROCESSING_ONLY"
        or summary.get("binding") != parent
        or verified.get("binding") != parent
        or read_sealed(_file(directory, "binding.json")) != parent
        or verified.get("summary_sha256") != ref["summary_sha256"]
        or verified.get("summary_digest") != summary["digest"]
        or summary.get("record_count") != len(delegate.allowed)
        or verified.get("record_count") != len(delegate.allowed)
        or method["context_count"] != len(delegate.allowed)
        or method["identity_count"] != delegate.identity_count
        or method["identity_counts"] != delegate.identity_counts
        or summary.get("boundary") != PREPROCESSING_BOUNDARY
        or verified.get("boundary") != PREPROCESSING_BOUNDARY
        or summary.get("all_frozen_contexts_preprocessed") is not True
        or summary.get("population_reduced") is not False
        or summary.get("new_dq_filter_applied") is not False
        or verified.get("verification_was_second_fetch") is not False
    ):
        raise InputCoverageError("full verified preprocessing prerequisite differs")
    pins[directory / "binding.json"] = _hash(directory / "binding.json")
    pins[Path(parent_args["method_path"])] = parent["method_sha256"]
    for inventory in (
        parent["source_hashes"],
        method["source_hashes"],
        parent["additional_runtime_source_pins"],
    ):
        for name, sha in inventory.items():
            pins[_file(root, name)] = sha
    for row in method["qualified_sources"].values():
        pins[_file(root, row["path"])] = row["current_sha256"]
    for role in ("protocol", "dq_reference", "scan_validity_reference"):
        ref_pin = method[role]
        pins[_file(root, ref_pin["path"])] = ref_pin["sha256"]
    for name, sha in sources.items():
        pins[_file(root, name)] = sha
    provider = IsolatedExpandedProductionProvider(delegate, pins, directory)
    provider.guard()
    if source_audit(root, source_freeze) != sources:
        raise InputCoverageError("productive source changed during binding")
    return provider, sealed(
        dict(
            status="PASS_ISOLATED_EXPANDED_PRODUCTIVE_INPUT_BINDING_ONLY",
            profile_sha256=profile_sha,
            source_freeze=source_freeze,
            source_hashes=sources,
            preprocessing_summary_sha256=ref["summary_sha256"],
            preprocessing_verification_sha256=ref["verification_sha256"],
            preprocessing_binding=parent,
            identity_count=delegate.identity_count,
            identity_counts=delegate.identity_counts,
            context_count=len(delegate.allowed),
            boundary=BOUNDARY,
        )
    )


def execute(*, stage, run_dir, binding_kwargs, expected_sha=None):
    provider, result = bind(**binding_kwargs)
    directory = isolated(run_dir, provider.delegate)
    parents = [Path(binding_kwargs["preprocessing_dir"]).resolve()]
    for name in ("native_dir", "method_path"):
        parent = Path(binding_kwargs["parent_args"][name]).resolve()
        parents.append(parent.parent if name == "method_path" else parent)
    if any(directory.is_relative_to(p) or p.is_relative_to(directory) for p in parents):
        raise InputCoverageError("productive output overlaps preserved parent")
    evidence = directory / "preflight.json"
    if stage == "bind":
        directory.mkdir(parents=True, exist_ok=False)
    elif stage == "verify":
        quiet(directory)
        if (directory / "verification.json").exists():
            raise InputCoverageError("productive verification already exists")
        if read_sealed(_pinned(evidence, expected_sha)) != result:
            raise InputCoverageError(
                "productive binding differs from standalone replay"
            )
    else:
        raise InputCoverageError("unsupported productive stage")
    lock = directory / "controller.lock"
    with lock.open("x") as stream:
        json.dump({"pid": os.getpid(), "stage": stage}, stream)
    try:
        provider.guard()
        if stage == "bind":
            write_json(evidence, result)
        else:
            _pinned(evidence, expected_sha)
            result = sealed(
                dict(
                    status="PASS_VERIFIED_ISOLATED_EXPANDED_PRODUCTIVE_INPUT_BINDING_ONLY",
                    preflight_sha256=expected_sha,
                    preflight_digest=result["digest"],
                    binding=result,
                    context_count=result["context_count"],
                    identity_count=result["identity_count"],
                    boundary=BOUNDARY,
                )
            )
            write_json(directory / "verification.json", result)
        return result
    except Exception as exc:
        write_json(
            directory / "failure.json",
            sealed(
                dict(
                    status="FAILED_ISOLATED_EXPANDED_PRODUCTIVE_INPUT_BINDING",
                    stage=stage,
                    error_type=type(exc).__name__,
                    message=str(exc),
                    automatic_resume=False,
                    boundary=BOUNDARY,
                )
            ),
        )
        raise
    finally:
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("bind", "verify"), required=True)
    for name in (
        "repository-root",
        "profile",
        "recovery-dir",
        "native-dir",
        "binding",
        "method",
        "preprocessing-dir",
        "run-dir",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("profile-sha256", "source-freeze", "binding-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args(argv)
    if args.stage == "verify" and args.expected_sha256 is None:
        parser.error("standalone verify requires pinned preflight")
    result = execute(
        stage=args.stage,
        run_dir=args.run_dir,
        expected_sha=args.expected_sha256,
        binding_kwargs=dict(
            profile_path=args.profile,
            profile_sha=args.profile_sha256,
            source_freeze=args.source_freeze,
            preprocessing_dir=args.preprocessing_dir,
            parent_args=dict(
                root=args.repository_root,
                recovery_dir=args.recovery_dir,
                native_dir=args.native_dir,
                binding_path=args.binding,
                binding_sha=args.binding_sha256,
                method_path=args.method,
            ),
        ),
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("status", "digest", "context_count", "identity_count")
            }
        )
    )
    return 0

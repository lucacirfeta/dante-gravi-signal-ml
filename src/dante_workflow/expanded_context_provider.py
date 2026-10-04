"""Opt-in exact expanded calibration consumer; no productive promotion."""

from collections import Counter
import argparse
import hashlib
import json
import math
from pathlib import Path

from .calibration_admission import _directory, _pinned
from .calibration_contexts import AdmittedContextProvider
from .calibration_expanded_admission import (
    BOUNDARY as ADMISSION_BOUNDARY,
    audit,
    load_policy,
    population,
    same,
)
from .calibration_recovery import read_sealed, sealed, write_json
from .calibration_transport import _integer
from .input_coverage import InputCoverageError
from .input_preflight import _file, _hash
from .schema_v2 import strict_json_object


BOUNDARY = {
    "context_consumer_only": True,
    "default_provider_replaced": False,
    "preprocessing_verified": False,
    "full_calibration_verified": False,
    "scientific_execution_ready": False,
    "candidate_scan_allowed": False,
    "o4b_launch_allowed": False,
}
INPUT_RULE = (
    "exact complete frozen calibration context union; new admitted native containers "
    "plus preserved prior references; no manifest or exception fallback"
)


class ExpandedCalibrationContextProvider:
    """Bind completed input evidence, then read only exactly declared contexts.

    Constructor checks metadata and sealed receipts, NOT another raw replay.
    Each read rechecks container/native identity through the existing reader.
    No scientific workflow factory or default runner uses this opt-in class.
    """

    def __init__(self, *, root, contract_path, contract_sha, run_dir):
        self.root = Path(root).resolve()
        self.contract_path = _pinned(contract_path, contract_sha)
        self.contract_sha = contract_sha
        contract = strict_json_object(
            self.contract_path.read_text(), label="expanded consumer"
        )
        if (
            type(contract.get("schema_version")) is not int
            or contract["schema_version"] != 1
            or contract.get("status")
            != "OPT_IN_EXPANDED_CALIBRATION_CONTEXT_CONSUMER_V1"
            or not same(contract.get("boundary"), BOUNDARY)
            or contract.get("input_rule") != INPUT_RULE
            or contract.get("reader_reference")
            != "src/dante_workflow/calibration_contexts.py:AdmittedContextProvider.read"
            or contract.get("representation_rule")
            != "inherit geometry and native sample rate from admission policy protocol; no preprocessing, resampling or crop in this provider"
        ):
            raise InputCoverageError("unsupported expanded consumer authority")
        self.directory = _directory(run_dir).resolve()
        if self.directory.is_relative_to(self.root):
            raise InputCoverageError("external preserved recovery directory required")
        self._quiet(scan_partials=True)
        pins = contract["evidence_sha256"]
        if set(pins) != {
            "admission.json",
            "plan.json",
            "summary.json",
            "verification.json",
        }:
            raise InputCoverageError("complete consumer evidence pins required")
        evidence = {
            name: read_sealed(_pinned(self.directory / name, sha))
            for name, sha in pins.items()
        }
        plan, summary, verified, receipt = (
            evidence[name]
            for name in (
                "plan.json",
                "summary.json",
                "verification.json",
                "admission.json",
            )
        )
        ref = contract["admission_policy"]
        policy_path = _pinned(_file(self.root, ref["path"]), ref["sha256"])
        policy, profile, protocol, sources = load_policy(
            self.root, policy_path, ref["sha256"]
        )
        audit(plan, self.root)
        if plan["policy_sha256"] != ref["sha256"] or sources != plan["source_hashes"]:
            raise InputCoverageError("consumer admission policy/source mismatch")
        expected_verification = sealed(
            {
                "status": "PASS_VERIFIED_CALIBRATION_NATIVE_RAW_ONLY",
                "plan_sha256": pins["plan.json"],
                "summary_sha256": pins["summary.json"],
                "plan_digest": plan["digest"],
                "identity_count": plan["identity_count"],
                "new_context_count": len(plan["new_contexts"]),
                "prior_context_count": len(plan["prior_contexts"]),
                "frame_count": len(plan["frames"]),
                "boundary": ADMISSION_BOUNDARY,
                "verification_was_second_fetch": False,
                "inputs_admitted": False,
            }
        )
        expected_receipt = sealed(
            {
                "status": "PASS_ADMITTED_CALIBRATION_EXACT_NATIVE_INPUTS_ONLY",
                "policy_sha256": plan["policy_sha256"],
                "plan_sha256": pins["plan.json"],
                "summary_sha256": pins["summary.json"],
                "verification_sha256": pins["verification.json"],
                "recovery_directory": receipt["recovery_directory"],
                "prior_receipt_path": plan["prior_receipt_path"],
                "prior_receipt_sha256": plan["prior_receipt_sha256"],
                "identity_count": plan["identity_count"],
                "identity_counts": plan["identity_counts"],
                "unique_context_count": plan["unique_context_count"],
                "records": summary["records"],
                "prior_contexts": plan["prior_contexts"],
                "source_hashes": sources,
                "boundary": ADMISSION_BOUNDARY,
            }
        )
        if (
            not same(verified, expected_verification)
            or not same(receipt, expected_receipt)
            or summary["status"]
            != "PASS_COMPLETE_CALIBRATION_RAW_NUMERIC_MATCH_PENDING_ADMISSION"
            or summary["plan_digest"] != plan["digest"]
            or not same(summary["boundary"], ADMISSION_BOUNDARY)
            or summary["inputs_admitted"] is not False
            or Path(receipt["recovery_directory"]).resolve() != self.directory
            or len(summary["frames"]) != len(plan["frames"])
        ):
            raise InputCoverageError("expanded consumer evidence relationship mismatch")
        metadata, self.prior = population(
            self.root, profile, protocol, Path(plan["prior_receipt_path"])
        )
        rate = protocol["representation"]["sample_rate_hz"]
        pad = protocol["representation"]["whitening_pad_s"]
        duration = protocol["representation"]["analysis_duration_s"]
        allowed, identities, counts = set(), set(), Counter()
        for row in metadata:
            identity = row["session_id"], row["detector"], row["catalog_gps_start"]
            begin, end = row["required_padded_interval"]
            if (
                identity in identities
                or begin != row["analysis_gps_start"] - pad
                or end != row["analysis_gps_start"] + duration + pad
            ):
                raise InputCoverageError("consumer frozen identity/geometry mismatch")
            _integer(begin * rate)
            _integer(end * rate)
            identities.add(identity)
            counts[row["detector"]] += 1
            allowed.add((row["detector"], begin, end))
        planned = {}
        for row in plan["new_contexts"] + plan["prior_contexts"]:
            key = row["detector"], row["gps_start"], row["gps_end"]
            if key in planned or row["sample_count"] != _integer(
                (key[2] - key[1]) * rate
            ):
                raise InputCoverageError("consumer duplicate context/grid mismatch")
            if not same(row["sample_rate_hz"], rate):
                raise InputCoverageError("consumer native rate mismatch")
            planned[key] = row
        self.rows = {
            (r["detector"], r["gps_start"], r["gps_end"]): r for r in receipt["records"]
        }
        prior_keys = {
            (r["detector"], r["gps_start"], r["gps_end"])
            for r in plan["prior_contexts"]
        }
        if (
            len(self.rows) != len(receipt["records"])
            or set(self.rows) & prior_keys
            or prior_keys != set(self.prior.rows)
            or set(self.rows) | prior_keys != allowed
            or set(planned) != allowed
            or len(allowed) != plan["unique_context_count"]
            or len(identities) != plan["identity_count"]
            or len(identities) != protocol["calibration_population"]["identity_count"]
            or dict(counts) != plan["identity_counts"]
        ):
            raise InputCoverageError("consumer full frozen population split mismatch")
        for key, row in self.rows.items():
            expected = planned[key]
            for name in (
                "sample_rate_hz",
                "sample_count",
                "historical_strain_values_sha256",
            ):
                if not same(row[name], expected[name]):
                    raise InputCoverageError(
                        "consumer retained context metadata mismatch"
                    )
            if (
                row["strain_values_sha256"]
                != expected["historical_strain_values_sha256"]
            ):
                raise InputCoverageError("consumer historical native SHA mismatch")
        for key in prior_keys:
            if (
                self.prior.rows[key]["file_sha256"]
                != planned[key]["prior_container_sha256"]
            ):
                raise InputCoverageError("consumer prior container pin mismatch")
        self.planned, self.allowed = planned, frozenset(allowed)
        self.receipt, self.receipt_sha = receipt, pins["admission.json"]
        self.receipt_path = self.directory / "admission.json"
        self.name_template = policy["series_name_template"]
        paths = contract["source_paths"]
        if (
            not isinstance(paths, list)
            or len(set(paths)) != len(paths)
            or set(paths)
            != {
                "src/dante_workflow/expanded_context_provider.py",
                "scripts/preflight_dante_workflow_expanded_context_provider.py",
                "src/dante_workflow/calibration_contexts.py",
                "src/dante_workflow/calibration_expanded_admission.py",
                "src/core/patch_producer.py",
            }
        ):
            raise InputCoverageError("consumer source inventory absent/duplicated")
        self.source_hashes = {p: _hash(_file(self.root, p)) for p in paths}
        if self.source_hashes.get(
            "src/dante_workflow/expanded_context_provider.py"
        ) != _hash(Path(__file__)):
            raise InputCoverageError("executed consumer differs from checkout")
        self.identity_counts = dict(counts)
        self.identity_count = len(identities)
        self.evidence_sha256 = dict(pins)
        for name, sha in pins.items():
            _pinned(self.directory / name, sha)
        _pinned(self.contract_path, self.contract_sha)
        self._quiet(scan_partials=True)

    def _quiet(self, *, scan_partials=False):
        if (
            any(
                (self.directory / p).exists()
                for p in ("controller.lock", "failure.json")
            )
            or (scan_partials and any(self.directory.rglob("*.partial")))
            or (scan_partials and any(self.directory.rglob("*.tmp")))
        ):
            raise InputCoverageError("consumer recovery has active/incomplete evidence")

    def read(self, *, detector, start, end):
        import numpy as np

        if (
            not isinstance(detector, str)
            or any(
                type(x) not in (int, float) or not math.isfinite(x)
                for x in (start, end)
            )
            or (detector, start, end) not in self.allowed
        ):
            raise InputCoverageError("exact expanded detector/interval required")
        self._quiet()
        _pinned(self.contract_path, self.contract_sha)
        _pinned(self.receipt_path, self.receipt_sha)
        for path, sha in self.source_hashes.items():
            _pinned(_file(self.root, path), sha)
        key = detector, start, end
        if key in self.rows:
            context = AdmittedContextProvider.read(
                self, detector=detector, start=start, end=end
            )
            path = _file(self.directory, self.rows[key]["relative_path"])
            if not same(read_sealed(path.with_suffix(".json")), sealed(self.rows[key])):
                raise InputCoverageError("consumer retained context receipt mismatch")
        else:
            context = self.prior.read(detector=detector, start=start, end=end)
        values = np.ascontiguousarray(context.series.value)
        row = self.planned[key]
        if (
            float(context.series.t0.value) != start
            or float(context.series.sample_rate.value) != row["sample_rate_hz"]
            or values.shape != (row["sample_count"],)
            or not np.isfinite(values).all()
            or hashlib.sha256(values.tobytes()).hexdigest()
            != row["historical_strain_values_sha256"]
            or str(context.series.name) != self.name_template.format(detector=detector)
        ):
            raise InputCoverageError("consumer native/name identity mismatch")
        _pinned(self.receipt_path, self.receipt_sha)
        _pinned(self.contract_path, self.contract_sha)
        for path, sha in self.source_hashes.items():
            _pinned(_file(self.root, path), sha)
        self._quiet()
        return context


def preflight(**kwargs):
    """Metadata/receipt binding only; NOT full-domain consumer numerical replay."""
    provider = ExpandedCalibrationContextProvider(**kwargs)
    return sealed(
        {
            "status": "PASS_EXPANDED_CONTEXT_CONSUMER_BINDING_ONLY",
            "contract_sha256": provider.contract_sha,
            "recovery_directory": str(provider.directory),
            "evidence_sha256": provider.evidence_sha256,
            "source_hashes": provider.source_hashes,
            "identity_count": provider.identity_count,
            "identity_counts": provider.identity_counts,
            "unique_context_count": len(provider.allowed),
            "new_context_count": len(provider.rows),
            "prior_context_count": len(provider.prior.rows),
            "all_expanded_contexts_read_through_consumer": False,
            "verification_was_second_fetch": False,
            "boundary": BOUNDARY,
        }
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("preflight", "verify"), required=True)
    for name in ("repository-root", "contract", "run-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args(argv)
    if args.stage == "verify":
        if (
            args.expected is None
            or args.expected_sha256 is None
            or args.output is not None
        ):
            parser.error("verify requires pinned expected evidence and no output")
        expected = read_sealed(_pinned(args.expected, args.expected_sha256))
    else:
        if (
            args.output is None
            or args.expected is not None
            or args.expected_sha256 is not None
        ):
            parser.error("preflight requires a new external output only")
        output = args.output
        _directory(output)
        protected = [args.repository_root.resolve(), args.run_dir.resolve()]
        plan = read_sealed(args.run_dir / "plan.json")
        protected += [
            Path(plan[k]).resolve()
            for k in ("historical_directory", "metadata_directory")
        ]
        protected.append(Path(plan["prior_receipt_path"]).resolve().parent)
        if output.exists() or any(
            output.resolve().is_relative_to(p) for p in protected
        ):
            parser.error("new output outside checkout and preserved evidence required")
    result = preflight(
        root=args.repository_root,
        contract_path=args.contract,
        contract_sha=args.contract_sha256,
        run_dir=args.run_dir,
    )
    if args.stage == "verify":
        if not same(result, expected):
            raise InputCoverageError("consumer binding independent replay differs")
        _pinned(args.expected, args.expected_sha256)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x"):
            pass
        write_json(output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "independent_binding_replay": args.stage == "verify",
                "identity_count": result["identity_count"],
                "unique_context_count": result["unique_context_count"],
                "digest": result["digest"],
                "scientific_execution_ready": False,
            },
            sort_keys=True,
        )
    )
    return 0

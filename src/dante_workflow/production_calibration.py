"""Isolated productive input boundary; no legacy runner or artifact redirection."""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
import json
import math
from pathlib import Path
import sys

from .calibration_admission import _directory, _pinned
from .calibration_contexts import AdmittedContextProvider
from .calibration_recovery import read_sealed, sealed, write_json
from .input_coverage import InputCoverageError
from .input_preflight import _file, _hash
from .schema import canonical_json_sha256
from .schema_v2 import strict_json_object
from .scoring_replay import compare_runtime, load_policy


RULES = {
    "input_rule": "all calibration identities; exact admitted gaps, otherwise frozen manifest only; no hash-error fallback",
    "copy_rule": "one existing copy per required logical span; every existing copy must match frozen SHA and size",
    "runtime_rule": "fresh numerical receipt at exact observed runtime; driver metadata recorded, not fixed-version gate",
    "scientific_rules": "inherit protocol population, geometry, execution parameters, per-session-detector p99 and historical full-context replay without modification",
    "output_namespace": "production_calibration_v1",
    "historical_output_writes_allowed": False,
    "historical_shard_or_threshold_reuse_allowed": False,
    "boundary": {
        "preflight_and_provider_only": True,
        "full_calibration_verified": False,
        "candidate_scan_allowed": False,
        "o4b_launch_allowed": False,
        "legacy_workflow_redirected": False,
    },
}


def load_profile(path, sha, root):
    value = strict_json_object(
        _pinned(path, sha).read_text(), label="production profile"
    )
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("status") != "AUTHOR_APPROVED_ISOLATED_CALIBRATION_PROFILE_V1"
        or any(
            canonical_json_sha256(value.get(k)) != canonical_json_sha256(v)
            for k, v in RULES.items()
        )
    ):
        raise InputCoverageError("unsupported productive profile or boundary")
    for role in ("workflow_parent", "protocol_parent", "qualification_policy"):
        ref = value[role]
        _pinned(_file(root, ref["path"]), ref["sha256"])
    sources = value["source_paths"]
    if (
        not isinstance(sources, list)
        or not sources
        or len(set(sources)) != len(sources)
        or "src/dante_workflow/production_calibration.py" not in sources
    ):
        raise InputCoverageError("productive source inventory absent or duplicated")
    return value


def source_hashes(root, profile):
    sources = {p: _hash(_file(root, p)) for p in profile["source_paths"]}
    if sources["src/dante_workflow/production_calibration.py"] != _hash(Path(__file__)):
        raise InputCoverageError("executed productive provider differs from checkout")
    return sources


def intervals(rows, admitted, protocol):
    """Metadata only; no historical score dataset values are accessed."""
    rep = protocol["representation"]
    duration, pad = rep["analysis_duration_s"], rep["whitening_pad_s"]
    allowed, keys, counts, sessions = set(), set(), Counter(), set()
    normal = {}
    for row in rows:
        detector = row["detector"]
        begin, end = row["required_padded_interval"]
        start, gps = row["analysis_gps_start"], row["catalog_gps_start"]
        if (
            detector not in admitted.readiness["detectors"]
            or any(
                type(x) not in (int, float) or not math.isfinite(x)
                for x in (begin, end, start, gps)
            )
            or begin != start - pad
            or end != start + duration + pad
            or type(row["session_id"]) is not int
            or begin >= end
        ):
            raise InputCoverageError("productive identity geometry/detector mismatch")
        identity = (row["historical_hdf5"], gps)
        if identity in keys:
            raise InputCoverageError("duplicate productive calibration identity")
        keys.add(identity)
        key = detector, begin, end
        allowed.add(key)
        counts[detector] += 1
        sessions.add((detector, row["session_id"]))
        if key not in admitted.rows:
            normal.setdefault(detector, set()).add((begin, end))
    population = protocol["calibration_population"]
    expected_counts = admitted.readiness["counts"]
    if (
        len(keys) != population["identity_count"]
        or dict(counts) != expected_counts
        or dict(Counter(d for d, _ in sessions))
        != population["session_detector_counts"]
        or not set(admitted.rows).issubset(allowed)
    ):
        raise InputCoverageError("productive frozen population/session mismatch")
    return allowed, normal, dict(counts)


def _copy_path(raw_root, relative):
    """Confined path check also works for absent copies, without accepting links."""
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise InputCoverageError("raw copy requires a relative POSIX path")
    parts = Path(relative)
    if parts.is_absolute() or ".." in parts.parts or not parts.parts:
        raise InputCoverageError("raw copy escapes root")
    candidate = raw_root
    for part in parts.parts:
        candidate /= part
        if candidate.is_symlink():
            raise InputCoverageError("raw copy traverses a symlink")
    if not candidate.resolve().is_relative_to(raw_root):
        raise InputCoverageError("raw copy escapes root")
    return candidate


def inspect_manifest(manifest_path, manifest_sha, raw_root, normal):
    """Hash only physical copies overlapping the required calibration contexts."""
    raw_root = _directory(raw_root).resolve()
    _pinned(manifest_path, manifest_sha)
    ranges = {d: sorted(spans) for d, spans in normal.items()}
    starts = {d: [a for a, _ in spans] for d, spans in ranges.items()}
    ends = {d: sorted(b for _, b in spans) for d, spans in ranges.items()}
    records, entries, hashes, seen = [], {}, {}, set()
    for line in manifest_path.read_text().splitlines():
        if not line.strip():
            continue
        row = strict_json_object(line, label="productive raw manifest")
        detector, begin, end = row["detector"], row["gps_start"], row["gps_end"]
        key = detector, begin, end
        if (
            any(
                type(x) not in (int, float) or not math.isfinite(x)
                for x in (begin, end)
            )
            or begin >= end
            or key in seen
        ):
            raise InputCoverageError("invalid or duplicate logical raw span")
        seen.add(key)
        if detector not in ranges or bisect_left(starts[detector], end) <= bisect_right(
            ends[detector], begin
        ):
            continue
        copies = row["physical_copies"]
        if not isinstance(copies, list) or not copies:
            raise InputCoverageError("required raw span has no frozen copies")
        available, copy_paths = [], set()
        for copy in copies:
            path = _copy_path(raw_root, copy["relative_path"])
            if path in copy_paths or copy["sha256"] != row["sha256"]:
                raise InputCoverageError(
                    "duplicate copy or conflicting declared raw SHA"
                )
            copy_paths.add(path)
            if path.exists():
                if not path.is_file() or path.stat().st_size != copy["size_bytes"]:
                    raise InputCoverageError("productive raw file type/size mismatch")
                _pinned(path, copy["sha256"])
                available.append(copy["relative_path"])
                entries.setdefault(detector, []).append((begin, end, path))
                hashes[path] = copy["sha256"]
        records.append(
            {
                "detector": detector,
                "gps_start": begin,
                "gps_end": end,
                "sha256": row["sha256"],
                "available_copies": sorted(available),
                "declared_copies": len(copies),
            }
        )
    # Require exact coverage for each non-admitted context. Missing logical spans
    # are reported, never replaced by admitted bytes for a different interval.
    covered = 0
    for detector, spans in ranges.items():
        logical = sorted({(a, b) for a, b, _ in entries.get(detector, [])})
        for begin, end in spans:
            cursor = begin
            for a, b in logical:
                if b <= cursor:
                    continue
                if a > cursor:
                    break
                cursor = max(cursor, b)
                if cursor >= end:
                    covered += 1
                    break
    _pinned(manifest_path, manifest_sha)
    return (
        {
            "required_logical_span_count": len(records),
            "missing_logical_span_count": sum(
                not r["available_copies"] for r in records
            ),
            "verified_physical_copy_count": len(hashes),
            "normal_unique_context_count": sum(map(len, ranges.values())),
            "covered_normal_unique_context_count": covered,
            "records": records,
        },
        entries,
        hashes,
    )


class ProductionContextProvider:
    """Exact admitted gaps plus unchanged legacy slicing, without fallback."""

    def __init__(self, *, admitted, allowed, normal, manifest_ref, raw_root):
        from src.core.patch_producer import FrozenRawManifest

        self.admitted = admitted
        self.allowed = frozenset(allowed)
        declared = set(admitted.rows) | {
            (d, a, b) for d, spans in normal.items() for a, b in spans
        }
        if self.allowed != declared:
            raise InputCoverageError("productive reader population split differs")
        self.manifest_ref = manifest_ref
        self.manifest_path = _file(admitted.root, manifest_ref["path"])
        report, entries, hashes = inspect_manifest(
            self.manifest_path, manifest_ref["sha256"], raw_root, normal
        )
        if (
            report["covered_normal_unique_context_count"]
            != report["normal_unique_context_count"]
        ):
            raise InputCoverageError("productive raw coverage incomplete")
        self.base = {
            d: FrozenRawManifest(
                self.manifest_path,
                manifest_ref["sha256"],
                tuple(e),
                tuple(sorted({p for _, _, p in e})),
                hashes,
            )
            for d, e in entries.items()
        }

    def read(self, *, detector, start, end):
        from src.dante_light.o4a_corrected_execution import _CorrectedContextReader

        if (
            any(
                type(x) not in (int, float) or not math.isfinite(x)
                for x in (start, end)
            )
            or (detector, start, end) not in self.allowed
        ):
            raise InputCoverageError("exact productive detector/interval required")
        _pinned(self.manifest_path, self.manifest_ref["sha256"])
        _pinned(self.admitted.receipt_path, self.admitted.receipt_sha)
        if (detector, start, end) in self.admitted.rows:
            result = self.admitted.read(detector=detector, start=start, end=end)
        else:
            # Reuse the original method explicitly, never its fallback or globals.
            result = _CorrectedContextReader._read_manifest_slice(
                self, detector=detector, start=start, end=end
            )
        _pinned(self.manifest_path, self.manifest_ref["sha256"])
        _pinned(self.admitted.receipt_path, self.admitted.receipt_sha)
        return result


def preflight(
    *, root, profile_path, profile_sha, receipt_path, qualification_path, raw_root
):
    from .adapters import build_adapter
    from .schema import load_workflow_spec
    from src.dante_light.o4a_corrected_runtime import capture_runtime_environment

    root = Path(root).resolve()
    profile = load_profile(profile_path, profile_sha, root)
    sources = source_hashes(root, profile)
    protocol = strict_json_object(
        _file(root, profile["protocol_parent"]["path"]).read_text(), label="protocol"
    )
    ref = profile["workflow_parent"]
    spec = load_workflow_spec(_file(root, ref["path"]), root=root)
    adapter = build_adapter(spec)
    admitted = AdmittedContextProvider(
        spec,
        adapter,
        root=root,
        receipt_path=receipt_path,
        receipt_sha=profile["admission_sha256"],
    )
    if any(
        admitted.receipt["parent"].get(k) != v
        for k, v in profile["protocol_parent"].items()
    ):
        raise InputCoverageError("productive admission parent mismatch")
    qp = profile["qualification_policy"]
    policy = load_policy(_file(root, qp["path"]), qp["sha256"])
    qualification_path = _pinned(qualification_path, profile["qualification_sha256"])
    qualified = read_sealed(qualification_path)
    if (
        qualified["status"] != "PASS_BOUNDED_FRESH_SCORING_REPLAY_ONLY"
        or qualified["policy_sha256"] != qp["sha256"]
        or qualified["admission_sha256"] != admitted.receipt_sha
        or qualified["record_count"] != len(admitted.rows)
        or qualified["parents"]["protocol_parent"] != profile["protocol_parent"]
        or qualified["boundary"] != policy["boundary"]
    ):
        raise InputCoverageError("productive numerical qualification parent mismatch")
    for path, sha in qualified["source_hashes"].items():
        _pinned(_file(root, path), sha)
    frozen = strict_json_object(
        _file(root, policy["runtime_parent"]["path"]).read_text(),
        label="frozen runtime",
    )
    execution = protocol["execution_parameters"]["primary_calibration"]
    observed = capture_runtime_environment(execution["device"])
    compare_runtime(frozen["runtime_environment"], observed)
    if observed != qualified["runtime"]:
        raise InputCoverageError(
            "fresh numerical receipt required for observed runtime"
        )
    allowed, normal, counts = intervals(
        adapter.iter_calibration_input_metadata(root, protocol), admitted, protocol
    )
    manifest = protocol["source_references"]["raw_manifest"]
    report, _, _ = inspect_manifest(
        _file(root, manifest["path"]), manifest["sha256"], raw_root, normal
    )
    ready = (
        report["covered_normal_unique_context_count"]
        == report["normal_unique_context_count"]
    )
    if (
        capture_runtime_environment(execution["device"]) != observed
        or source_hashes(root, profile) != sources
    ):
        raise InputCoverageError("runtime/source changed during productive preflight")
    load_profile(profile_path, profile_sha, root)
    _pinned(receipt_path, admitted.receipt_sha)
    _pinned(qualification_path, profile["qualification_sha256"])
    body = {
        "schema_version": 1,
        "status": "PASS_PRODUCTIVE_INPUT_BYTES_ONLY"
        if ready
        else "BLOCKED_PRODUCTIVE_RAW_FILES",
        "profile_sha256": profile_sha,
        "parents": {
            k: profile[k]
            for k in ("protocol_parent", "workflow_parent", "qualification_policy")
        },
        "admission_sha256": admitted.receipt_sha,
        "qualification_sha256": profile["qualification_sha256"],
        "source_hashes": sources,
        "runtime": observed,
        "execution_parameters": execution,
        "raw_root": str(Path(raw_root).resolve()),
        "identity_count": admitted.readiness["identity_count"],
        "counts": counts,
        "unique_context_count": len(allowed),
        "admitted_context_count": len(admitted.rows),
        "raw_manifest": manifest,
        "physical_input_audit": report,
        "input_bytes_ready": ready,
        "scientific_execution_ready": False,
        "raw_manifest_samples_replayed": False,
        "score_values_read": False,
        "historical_scores_or_thresholds_reused": False,
        "writer_exclusion_established": False,
        "remaining_gates": [
            "FULL_CONTEXT_NUMERICAL_VALIDITY",
            "ISOLATED_EXECUTION_AND_INDEPENDENT_VERIFY",
        ],
        "boundary": profile["boundary"],
    }
    return sealed({**body, "profile_run_key": canonical_json_sha256(body)})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("preflight", "verify"), required=True)
    for name in (
        "repository-root",
        "profile",
        "receipt",
        "qualification",
        "raw-root",
        "output-root",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args(argv)
    if args.stage == "verify" and (
        args.expected is None or args.expected_sha256 is None
    ):
        parser.error("verify requires pinned preflight evidence")
    root = args.repository_root.resolve()
    output = _directory(args.output_root).resolve()
    protected = (
        root,
        args.raw_root.resolve(),
        args.receipt.parent.resolve(),
        args.qualification.parent.resolve(),
    )
    if any(
        output == p or output.is_relative_to(p) or p.is_relative_to(output)
        for p in protected
    ):
        parser.error("separate isolated output root required")
    result = preflight(
        root=root,
        profile_path=args.profile,
        profile_sha=args.profile_sha256,
        receipt_path=args.receipt,
        qualification_path=args.qualification,
        raw_root=args.raw_root,
    )
    if args.stage == "verify":
        expected = read_sealed(_pinned(args.expected, args.expected_sha256))
        if result != expected:
            raise InputCoverageError(
                "productive preflight differs from independent replay"
            )
        evidence = args.expected
    else:
        namespace = load_profile(args.profile, args.profile_sha256, root)[
            "output_namespace"
        ]
        directory = _directory(output / namespace)
        directory.mkdir(parents=True, exist_ok=True)
        evidence = directory / f"preflight_{result['profile_run_key']}.json"
        if evidence.exists():
            raise InputCoverageError("preflight evidence already exists; use verify")
        write_json(evidence, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "independent_replay": args.stage == "verify",
                "evidence": str(evidence),
                "sha256": _hash(evidence),
                "identity_count": result["identity_count"],
                "counts": result["counts"],
                "input_bytes_ready": result["input_bytes_ready"],
                "audit_counts": {
                    k: v
                    for k, v in result["physical_input_audit"].items()
                    if k != "records"
                },
                "scientific_execution_ready": False,
            },
            sort_keys=True,
        )
    )
    return 0 if result["input_bytes_ready"] else 2


if __name__ == "__main__":
    sys.exit(main())

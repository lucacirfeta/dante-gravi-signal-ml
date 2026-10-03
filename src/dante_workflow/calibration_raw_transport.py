"""Frozen missing raw inventory -> public metadata plan, never raw admission."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

from .calibration_admission import _directory, _pinned
from .calibration_recovery import official_checksums, read_sealed, sealed, write_json
from .calibration_transport import _integer, fetch_metadata
from .input_preflight import _file, _hash
from .schema import canonical_json_sha256
from .schema_v2 import strict_json_object


BOUNDARY = {
    "metadata_only": True,
    "raw_download_allowed": False,
    "replacement_bytes_admitted": False,
    "historical_release_equivalence_checked": False,
    "scientific_execution_ready": False,
}


def inputs(root, policy_path, policy_sha, report_path):
    root = Path(root).resolve()
    policy = strict_json_object(
        _pinned(policy_path, policy_sha).read_text(), label="transport policy"
    )
    if (
        type(policy.get("schema_version")) is not int
        or policy["schema_version"] != 1
        or policy.get("status") != "TRANSPORT_METADATA_ONLY_V1"
        or policy.get("boundary") != BOUNDARY
        or any(type(v) is not bool for v in policy["boundary"].values())
        or type(policy.get("metadata_bucket_s")) is not int
        or policy["metadata_bucket_s"] <= 0
        or not re.fullmatch(r"[A-Za-z0-9_]+", policy.get("candidate_dataset", ""))
    ):
        raise ValueError("unsupported metadata-only policy")
    ref = policy["production_profile"]
    profile = strict_json_object(
        _pinned(_file(root, ref["path"]), ref["sha256"]).read_text(),
        label="production profile",
    )
    parent = profile["protocol_parent"]
    protocol = strict_json_object(
        _pinned(_file(root, parent["path"]), parent["sha256"]).read_text(),
        label="protocol",
    )
    _pinned(report_path, policy["blocked_preflight_sha256"])
    report = read_sealed(report_path)
    manifest = protocol["source_references"]["raw_manifest"]
    if (
        report["status"] != "BLOCKED_PRODUCTIVE_RAW_FILES"
        or report["profile_sha256"] != ref["sha256"]
        or report["parents"]["protocol_parent"] != parent
        or report["raw_manifest"] != manifest
        or report["scientific_execution_ready"] is not False
        or report["input_bytes_ready"] is not False
    ):
        raise ValueError("blocked preflight parent/status mismatch")
    raw = _pinned(_file(root, manifest["path"]), manifest["sha256"]).read_text()
    rows = {}
    for line in raw.splitlines():
        row = strict_json_object(line, label="manifest row")
        key = row["detector"], _integer(row["gps_start"]), _integer(row["gps_end"])
        if key in rows or key[1] >= key[2]:
            raise ValueError("duplicate/invalid frozen manifest interval")
        rows[key] = row
    records, seen = [], set()
    audit = report["physical_input_audit"]
    for item in audit["records"]:
        key = item["detector"], _integer(item["gps_start"]), _integer(item["gps_end"])
        if key in seen or key not in rows:
            raise ValueError("unknown/duplicate required raw interval")
        seen.add(key)
        row = rows[key]
        copies = row["physical_copies"]
        if item["sha256"] != row["sha256"] or item["declared_copies"] != len(copies):
            raise ValueError("required raw inventory differs from frozen manifest")
        if not item["available_copies"]:
            records.append(row)
    if (
        len(records) != audit["missing_logical_span_count"]
        or len(audit["records"]) != audit["required_logical_span_count"]
        or not records
    ):
        raise ValueError("missing raw cardinality mismatch")
    sources = {p: _hash(_file(root, p)) for p in policy["source_paths"]}
    if sources.get("src/dante_workflow/calibration_raw_transport.py") != _hash(
        Path(__file__)
    ):
        raise ValueError("executed metadata source differs from checkout")
    for path, sha in report.get("source_hashes", {}).items():
        _pinned(_file(root, path), sha)
    return (
        policy,
        protocol,
        sorted(records, key=lambda x: (x["detector"], x["gps_start"])),
        sources,
    )


def queries(records, bucket_s):
    groups = {}
    for row in records:
        key = row["detector"], row["gps_start"] // bucket_s
        interval = groups.setdefault(key, [row["gps_start"], row["gps_end"]])
        interval[0] = min(interval[0], row["gps_start"])
        interval[1] = max(interval[1], row["gps_end"])
    return [(key[0], *groups[key]) for key in sorted(groups)]


def backup_audit(records, roots):
    """Exact declared or flat filenames only; no recursive backup hunt."""
    results = []
    for root in roots:
        root = _directory(root)
        if root.exists() and not root.is_dir():
            raise ValueError("backup root must be a directory")
        checked, present = set(), []
        for row in records:
            for copy in row["physical_copies"]:
                relative = copy["relative_path"]
                for candidate in (relative, Path(relative).name):
                    parts = PurePosixPath(candidate)
                    if (
                        "\\" in candidate
                        or ":" in candidate
                        or parts.is_absolute()
                        or ".." in parts.parts
                        or not parts.parts
                    ):
                        raise ValueError("unsafe backup relative path")
                    path = root.joinpath(*parts.parts)
                    _directory(path)
                    if not path.resolve().is_relative_to(root.resolve()):
                        raise ValueError("backup path outside root")
                    if path in checked:
                        continue
                    checked.add(path)
                    if path.exists():
                        if (
                            path.stat().st_size != copy["size_bytes"]
                            or _hash(path) != copy["sha256"]
                        ):
                            raise ValueError(
                                "backup candidate hash/size mismatch; preserve and stop"
                            )
                        present.append(str(path))
        results.append(
            {
                "root": str(root),
                "root_exists": root.exists(),
                "exact_paths_checked": len(checked),
                "matching_files": present,
            }
        )
    return results


def parse_metadata(raw, dataset, detector, start, end, rate):
    value = strict_json_object(raw.decode(), label="GWOSC metadata")
    if (
        value.get("dataset") != dataset
        or _integer(value.get("GPSstart")) != start
        or _integer(value.get("GPSend")) != end
        or not isinstance(value.get("strain"), list)
    ):
        raise ValueError("metadata dataset/query mismatch")
    files, seen = [], set()
    for row in value["strain"]:
        if row.get("format") != "hdf5":
            continue
        parsed = urlsplit(row.get("url", ""))
        begin, duration = _integer(row.get("GPSstart")), _integer(row.get("duration"))
        if (
            row.get("detector") != detector
            or _integer(row.get("sampling_rate")) != rate
            or duration <= 0
            or parsed.scheme != "https"
            or parsed.netloc != "gwosc.org"
            or not parsed.path.startswith(f"/archive/data/{dataset}/")
            or not re.fullmatch(r"[A-Za-z0-9_.-]+\.hdf5", parsed.path.split("/")[-1])
            or parsed.query
            or parsed.fragment
            or row["url"] in seen
        ):
            raise ValueError("public file origin/detector/rate/grid/duplicate mismatch")
        seen.add(row["url"])
        files.append(
            {
                "detector": detector,
                "gps_start": begin,
                "gps_end": begin + duration,
                "sample_rate_hz": rate,
                "url": row["url"],
            }
        )
    return files


def checksum_map(raw):
    result = {}
    for line in raw.decode().splitlines():
        md5, relative = line.split()
        name = relative.split("/")[-1]
        if not re.fullmatch(r"[a-f0-9]{32}", md5) or name in result:
            raise ValueError("official checksum snapshot ambiguity")
        result[name] = md5
    return result


def assemble(records, responses, dataset, rate, checksums):
    files = {}
    for detector, start, end, raw in responses:
        for item in parse_metadata(raw, dataset, detector, start, end, rate):
            key = item["url"]
            if key in files and files[key] != item:
                raise ValueError("public metadata inconsistency between queries")
            files[key] = item
    planned, needed = [], {}
    for row in records:
        start, end = row["gps_start"], row["gps_end"]
        selected = sorted(
            [
                f
                for f in files.values()
                if f["detector"] == row["detector"]
                and f["gps_start"] < end
                and f["gps_end"] > start
            ],
            key=lambda x: (x["gps_start"], x["gps_end"], x["url"]),
        )
        cursor = start
        for item in selected:
            if item["gps_start"] > cursor:
                raise ValueError("public metadata coverage hole")
            cursor = max(cursor, item["gps_end"])
            name = urlsplit(item["url"]).path.split("/")[-1]
            if name not in checksums:
                raise ValueError("public file missing official MD5")
            item = {**item, "official_md5": checksums[name]}
            needed[item["url"]] = item
        if cursor < end:
            raise ValueError("public metadata coverage hole")
        planned.append(
            {
                "historical_manifest_record": row,
                "public_files": [needed[f["url"]] for f in selected],
            }
        )
    return {
        "required_logical_span_count": len(records),
        "counts": dict(Counter(x["detector"] for x in records)),
        "unique_public_file_count": len(needed),
        "historical_minimum_container_bytes": sum(
            min(c["size_bytes"] for c in x["physical_copies"]) for x in records
        ),
        "records": planned,
    }


def execute(
    *,
    root,
    policy_path,
    policy_sha,
    report_path,
    run_dir,
    backup_roots,
    stage,
    expected_plan_sha=None,
):
    args = root, policy_path, policy_sha, report_path
    policy, protocol, records, sources = inputs(*args)
    rate = _integer(protocol["representation"]["sample_rate_hz"])
    dataset = policy["candidate_dataset"]
    query_list = queries(records, policy["metadata_bucket_s"])
    run_dir = _directory(run_dir)
    if run_dir.is_relative_to(Path(root).resolve()) or any(
        run_dir.is_relative_to(_directory(p)) for p in backup_roots
    ):
        raise ValueError(
            "new external evidence directory required, outside backup roots"
        )
    evidence = run_dir / "metadata_plan.json"
    if stage == "plan":
        run_dir.mkdir(parents=True, exist_ok=False)
        write_json(run_dir / "policy.json", policy)
        write_json(
            run_dir / "request.json",
            {
                "policy_sha256": policy_sha,
                "report_sha256": policy["blocked_preflight_sha256"],
                "queries": query_list,
                "source_hashes": sources,
            },
        )
        try:
            backups = backup_audit(records, backup_roots)
            md5_raw, _ = official_checksums(dataset)
            (run_dir / "official_md5.txt").write_bytes(md5_raw)
            responses, snapshots = [], []
            for index, (detector, start, end) in enumerate(query_list):
                url = f"https://gwosc.org/archive/links/{dataset}/{detector}/{start}/{end}/json/"
                raw = fetch_metadata(url)
                name = f"metadata_{index:04d}.json"
                (run_dir / name).write_bytes(raw)
                responses.append((detector, start, end, raw))
                snapshots.append(
                    {
                        "path": name,
                        "url": url,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    }
                )
            inventory = assemble(
                records, responses, dataset, rate, checksum_map(md5_raw)
            )
            if inputs(*args) != (policy, protocol, records, sources):
                raise ValueError("input/source changed during metadata queries")
            result = sealed(
                {
                    "status": "PASS_PUBLIC_RAW_METADATA_PLAN_ONLY",
                    "policy_sha256": policy_sha,
                    "blocked_preflight_sha256": policy["blocked_preflight_sha256"],
                    "source_hashes": sources,
                    "candidate_dataset": dataset,
                    "sample_rate_hz": rate,
                    "queried_at_utc": datetime.now(timezone.utc).isoformat(),
                    "snapshots": snapshots,
                    "official_md5_sha256": hashlib.sha256(md5_raw).hexdigest(),
                    "backup_audit": backups,
                    "inventory": inventory,
                    "boundary": BOUNDARY,
                    "raw_samples_checked": False,
                    "dq_validity_checked": False,
                    "historical_score_values_used": False,
                    "network_volume_estimated": False,
                }
            )
            write_json(evidence, result)
        except Exception as exc:
            write_json(
                run_dir / "failure.json",
                sealed(
                    {
                        "status": "FAILED_METADATA_PLAN_STOP",
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                ),
            )
            raise
    else:
        if (run_dir / "failure.json").exists() or list(run_dir.glob("*.tmp")):
            raise ValueError("failure/partial evidence present; no automatic retry")
        _pinned(evidence, expected_plan_sha)
        result = read_sealed(evidence)
        if (
            result["source_hashes"] != sources
            or result["policy_sha256"] != policy_sha
            or result["blocked_preflight_sha256"] != policy["blocked_preflight_sha256"]
            or canonical_json_sha256(result["boundary"])
            != canonical_json_sha256(BOUNDARY)
            or result["candidate_dataset"] != dataset
            or result["sample_rate_hz"] != rate
            or result["status"] != "PASS_PUBLIC_RAW_METADATA_PLAN_ONLY"
        ):
            raise ValueError("metadata plan authority/parent/source mismatch")
        for field in (
            "raw_samples_checked",
            "dq_validity_checked",
            "historical_score_values_used",
            "network_volume_estimated",
        ):
            if result.get(field) is not False:
                raise ValueError(
                    "metadata plan cannot claim numerical/scientific evidence"
                )
        stored_policy = strict_json_object(
            (run_dir / "policy.json").read_text(), label="policy snapshot"
        )
        stored_request = strict_json_object(
            (run_dir / "request.json").read_text(), label="request snapshot"
        )
        expected_request = {
            "policy_sha256": policy_sha,
            "report_sha256": policy["blocked_preflight_sha256"],
            "queries": query_list,
            "source_hashes": sources,
        }
        if canonical_json_sha256(stored_policy) != canonical_json_sha256(
            policy
        ) or canonical_json_sha256(stored_request) != canonical_json_sha256(
            expected_request
        ):
            raise ValueError("metadata request/policy snapshot changed")
        raw = _pinned(
            run_dir / "official_md5.txt", result["official_md5_sha256"]
        ).read_bytes()
        responses = []
        if len(result["snapshots"]) != len(query_list):
            raise ValueError("metadata query cardinality mismatch")
        for index, ((detector, start, end), snapshot) in enumerate(
            zip(query_list, result["snapshots"], strict=True)
        ):
            if (
                snapshot["path"] != f"metadata_{index:04d}.json"
                or snapshot["url"]
                != f"https://gwosc.org/archive/links/{dataset}/{detector}/{start}/{end}/json/"
            ):
                raise ValueError("metadata snapshot identity mismatch")
            responses.append(
                (
                    detector,
                    start,
                    end,
                    _pinned(
                        _file(run_dir, snapshot["path"]), snapshot["sha256"]
                    ).read_bytes(),
                )
            )
        if (
            canonical_json_sha256(
                assemble(records, responses, dataset, rate, checksum_map(raw))
            )
            != canonical_json_sha256(result["inventory"])
            or backup_audit(records, backup_roots) != result["backup_audit"]
        ):
            raise ValueError("local metadata/backup replay differs")
        expected_files = {
            "metadata_plan.json",
            "policy.json",
            "request.json",
            "official_md5.txt",
            *(s["path"] for s in result["snapshots"]),
        }
        if {p.name for p in run_dir.iterdir()} != expected_files:
            raise ValueError("extra/missing metadata evidence files")
        if inputs(*args) != (policy, protocol, records, sources):
            raise ValueError("input/source changed during metadata replay")
        result = sealed(
            {
                "status": "PASS_VERIFIED_PUBLIC_RAW_METADATA_ONLY",
                "plan_digest": result["digest"],
                "required_logical_span_count": len(records),
                "unique_public_file_count": result["inventory"][
                    "unique_public_file_count"
                ],
                "boundary": BOUNDARY,
                "verification_was_second_fetch": False,
            }
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("plan", "verify"), required=True)
    for name in ("repository-root", "policy", "policy-sha256", "report", "run-dir"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--backup-root", action="append", default=[])
    parser.add_argument("--expected-plan-sha256")
    options = parser.parse_args()
    result = execute(
        root=Path(options.repository_root),
        policy_path=Path(options.policy),
        policy_sha=options.policy_sha256,
        report_path=Path(options.report),
        run_dir=Path(options.run_dir),
        backup_roots=[Path(p) for p in options.backup_root],
        stage=options.stage,
        expected_plan_sha=options.expected_plan_sha256,
    )
    print(
        result["status"],
        result.get(
            "required_logical_span_count",
            result.get("inventory", {}).get("required_logical_span_count"),
        ),
    )


if __name__ == "__main__":
    main()

"""Exact native raw recovery/admission for a frozen calibration domain only."""

import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from urllib.error import URLError
from urllib.parse import urlsplit

from .calibration_admission import _directory, _pinned
from .calibration_contexts import AdmittedContextProvider
from .calibration_raw_transport import execute as verify_transport
from .calibration_recovery import download, file_hashes, read_sealed, sealed, write_json
from .calibration_transport import _integer
from .input_preflight import _file, _hash
from .schema import canonical_json_sha256, load_workflow_spec
from .schema_v2 import strict_json_object


BOUNDARY = {
    "calibration_inputs_only": True,
    "exact_numerical_match_required": True,
    "historical_container_equivalence_claimed": False,
    "historical_scores_or_thresholds_reused": False,
    "full_calibration_verified": False,
    "candidate_scan_allowed": False,
    "other_run_inputs_admitted": False,
    "legacy_workflow_redirected": False,
    "scientific_execution_ready": False,
}


def same(a, b):
    return canonical_json_sha256(a) == canonical_json_sha256(b)


def load_policy(root, path, sha):
    policy = strict_json_object(
        _pinned(path, sha).read_text(), label="expanded admission"
    )
    if (
        type(policy.get("schema_version")) is not int
        or policy["schema_version"] != 1
        or policy.get("status")
        != "AUTHOR_APPROVED_CALIBRATION_EXACT_NUMERIC_ADMISSION_V1"
        or policy.get("identity_rule")
        != "EXACT_NATIVE_NUMERICAL_SHA_NEW_CONTAINER_RECEIPT_CALIBRATION_ONLY"
        or not same(policy.get("boundary"), BOUNDARY)
        or policy.get("container_format") != "gwpy_hdf5"
        or policy.get("series_name_template") != "{detector}:GWOSC-16KHZ_R1_STRAIN"
        or policy["transport"].get("automatic_retry_or_resume") is not False
        or type(policy["transport"].get("maximum_frame_bytes")) is not int
        or policy["transport"].get("maximum_frame_bytes") != 512 * 1024 * 1024
        or type(policy["transport"].get("context_container_reserve_bytes")) is not int
        or policy["transport"]["context_container_reserve_bytes"] < 0
    ):
        raise ValueError("unsupported calibration-only admission policy")
    refs = {}
    for role in ("production_profile", "metadata_policy", "historical_calibration"):
        ref = policy[role]
        refs[role] = _pinned(_file(root, ref["path"]), ref["sha256"])
    profile = strict_json_object(
        refs["production_profile"].read_text(), label="productive parent"
    )
    ref = profile["protocol_parent"]
    protocol = strict_json_object(
        _pinned(_file(root, ref["path"]), ref["sha256"]).read_text(),
        label="scientific protocol",
    )
    paths = policy["source_paths"]
    if not paths or len(set(paths)) != len(paths):
        raise ValueError("source inventory absent/duplicated")
    sources = {p: _hash(_file(root, p)) for p in paths}
    if sources.get("src/dante_workflow/calibration_expanded_admission.py") != _hash(
        Path(__file__)
    ):
        raise ValueError("executed admission source differs from checkout")
    return policy, profile, protocol, sources


def population(root, profile, protocol, prior_receipt):
    from .adapters import build_adapter

    ref = profile["workflow_parent"]
    _pinned(_file(root, ref["path"]), ref["sha256"])
    spec = load_workflow_spec(_file(root, ref["path"]), root=root)
    adapter = build_adapter(spec)
    for ref in protocol["calibration_population"]["source_hdf5_references"]:
        _pinned(_file(root, ref["path"]), ref["sha256"])
    prior = AdmittedContextProvider(
        spec,
        adapter,
        root=root,
        receipt_path=prior_receipt,
        receipt_sha=profile["admission_sha256"],
    )
    rows = list(adapter.iter_calibration_input_metadata(root, protocol))
    return rows, prior


def baseline(root, policy, protocol, metadata, historical_dir):
    """Parse sealed score-containing bodies, but use ONLY identity/raw-hash fields."""
    compact_path = _file(root, policy["historical_calibration"]["path"])
    compact = strict_json_object(
        compact_path.read_text(), label="historical calibration"
    )
    body = dict(compact)
    digest = body.pop("artifact_digest")
    historical_dir = _directory(historical_dir)
    if (
        digest != canonical_json_sha256(body)
        or compact["status"] != "PASS_COMPLETE_PRIMARY_CALIBRATION"
        or compact["protocol_digest"] != protocol["protocol_digest"]
        or historical_dir.name != compact["external_run_directory"]
        or _file(historical_dir, "primary_calibration_summary.json").read_bytes()
        != compact_path.read_bytes()
    ):
        raise ValueError("historical calibration seal/parent/snapshot mismatch")
    expected = {}
    rate = _integer(protocol["representation"]["sample_rate_hz"])
    duration = protocol["representation"]["analysis_duration_s"]
    pad = protocol["representation"]["whitening_pad_s"]
    for row in metadata:
        identity = row["session_id"], row["detector"], row["catalog_gps_start"]
        if identity in expected:
            raise ValueError("duplicate frozen calibration identity")
        start, end = row["required_padded_interval"]
        if (
            start != row["analysis_gps_start"] - pad
            or end != row["analysis_gps_start"] + duration + pad
        ):
            raise ValueError("frozen context geometry changed")
        _integer(start * rate)
        _integer(end * rate)
        expected[identity] = row
    contexts, found, pins, sessions = {}, set(), {}, set()
    for ref in compact["thresholds"]:
        path = _file(historical_dir, ref["shard"])
        value = strict_json_object(path.read_text(), label="historical shard")
        shard = dict(value)
        seal = shard.pop("shard_digest")
        session = value["session_id"], value["detector"]
        if (
            seal != canonical_json_sha256(shard)
            or seal != ref["shard_digest"]
            or value["run_key"] != compact["run_key"]
            or session in sessions
            or session != (ref["session_id"], ref["detector"])
            or value["row_count"] != len(value["rows"])
            or ref["n"] != len(value["rows"])
        ):
            raise ValueError("historical raw baseline shard seal/identity mismatch")
        sessions.add(session)
        pins[ref["shard"]] = _hash(path)
        for row in value["rows"]:
            identity = row["session_id"], row["detector"], row["catalog_gps_start"]
            if identity in found or identity not in expected or identity[:2] != session:
                raise ValueError(
                    "historical identity missing/duplicated/outside population"
                )
            found.add(identity)
            meta = expected[identity]
            for field in (
                "analysis_gps_start",
                "required_padded_interval",
                "historical_context_disposition",
            ):
                if not same(row[field], meta[field]):
                    raise ValueError(
                        "historical identity geometry differs from frozen metadata"
                    )
            start, end = row["required_padded_interval"]
            sha = row["raw_strain_sha256"]
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError("historical native SHA missing")
            key = row["detector"], start, end
            record = {
                "detector": key[0],
                "gps_start": start,
                "gps_end": end,
                "sample_rate_hz": rate,
                "sample_count": _integer((end - start) * rate),
                "historical_strain_values_sha256": sha,
            }
            if key in contexts and not same(contexts[key], record):
                raise ValueError("inconsistent historical SHA for shared context")
            contexts[key] = record
    pop = protocol["calibration_population"]
    if (
        found != set(expected)
        or len(found) != pop["identity_count"]
        or compact["row_count"] != len(found)
        or dict(Counter(d for _, d in sessions)) != pop["session_detector_counts"]
        or compact["session_detector_count"] != len(sessions)
    ):
        raise ValueError("historical raw baseline population is incomplete")
    return contexts, pins


def map_frames(contexts, public):
    files = {}
    for record in public["inventory"]["records"]:
        for f in record["public_files"]:
            if f["url"] in files and not same(files[f["url"]], f):
                raise ValueError("inconsistent public frame metadata")
            files[f["url"]] = f
    planned, needed = [], {}
    for key, row in sorted(contexts.items()):
        selected = sorted(
            [
                f
                for f in files.values()
                if f["detector"] == key[0]
                and f["gps_start"] < key[2]
                and f["gps_end"] > key[1]
            ],
            key=lambda f: (f["gps_start"], f["gps_end"], f["url"]),
        )
        cursor = key[1]
        for f in selected:
            if f["gps_start"] > cursor:
                raise ValueError("exact calibration context has public coverage gap")
            cursor = max(cursor, min(key[2], f["gps_end"]))
            needed[f["url"]] = f
        if cursor != key[2]:
            raise ValueError("exact calibration context has public coverage gap")
        planned.append({**row, "files": selected})
    names = [urlsplit(url).path.split("/")[-1] for url in needed]
    if len(set(names)) != len(names):
        raise ValueError("public frame filename collision")
    return planned, sorted(
        needed.values(), key=lambda f: (f["detector"], f["gps_start"], f["url"])
    )


def build_plan(
    *,
    root,
    policy_path,
    policy_sha,
    metadata_dir,
    report_path,
    historical_dir,
    prior_receipt,
    population_loader=population,
):
    root = _directory(root).resolve()
    policy, profile, protocol, sources = load_policy(root, policy_path, policy_sha)
    metadata_dir, historical_dir = _directory(metadata_dir), _directory(historical_dir)
    public_path = _pinned(
        metadata_dir / "metadata_plan.json", policy["metadata_plan_sha256"]
    )
    public = read_sealed(public_path)
    parent = policy["metadata_policy"]
    verify_transport(
        root=root,
        policy_path=_file(root, parent["path"]),
        policy_sha=parent["sha256"],
        report_path=report_path,
        run_dir=metadata_dir,
        backup_roots=[Path(x["root"]) for x in public["backup_audit"]],
        stage="verify",
        expected_plan_sha=policy["metadata_plan_sha256"],
    )
    metadata, prior = population_loader(root, profile, protocol, prior_receipt)
    contexts, shards = baseline(root, policy, protocol, metadata, historical_dir)
    if not set(prior.rows).issubset(contexts):
        raise ValueError("prior admitted context outside frozen calibration")
    prior_records = []
    for key, row in sorted(prior.rows.items()):
        context = prior.read(detector=key[0], start=key[1], end=key[2])
        values = context.series.value
        if (
            hashlib.sha256(values.tobytes()).hexdigest()
            != contexts[key]["historical_strain_values_sha256"]
        ):
            raise ValueError("prior admitted context differs from historical baseline")
        prior_records.append(
            {**contexts.pop(key), "prior_container_sha256": row["file_sha256"]}
        )
    planned, frames = map_frames(contexts, public)
    body = {
        "status": "PLAN_CALIBRATION_NATIVE_RAW_RECOVERY_ONLY",
        "policy_path": str(Path(policy_path).resolve()),
        "policy_sha256": policy_sha,
        "metadata_directory": str(metadata_dir.resolve()),
        "metadata_plan_sha256": policy["metadata_plan_sha256"],
        "report_path": str(Path(report_path).resolve()),
        "historical_directory": str(historical_dir.resolve()),
        "historical_shard_sha256": shards,
        "prior_receipt_path": str(Path(prior_receipt).resolve()),
        "prior_receipt_sha256": profile["admission_sha256"],
        "source_hashes": sources,
        "protocol_parent": profile["protocol_parent"],
        "candidate_dataset": public["candidate_dataset"],
        "sample_rate_hz": protocol["representation"]["sample_rate_hz"],
        "identity_count": len(metadata),
        "identity_counts": dict(Counter(r["detector"] for r in metadata)),
        "unique_context_count": len(planned) + len(prior_records),
        "new_contexts": planned,
        "prior_contexts": prior_records,
        "frames": frames,
        "new_context_payload_bytes": sum(x["sample_count"] * 8 for x in planned),
        "series_name_template": policy["series_name_template"],
        "transport": policy["transport"],
        "boundary": BOUNDARY,
        "raw_bytes_recovered": False,
        "inputs_admitted": False,
    }
    # Pins rechecked after the metadata/baseline scan. No scoring/model access.
    if not same(
        load_policy(root, policy_path, policy_sha),
        (policy, profile, protocol, sources),
    ):
        raise ValueError("source or parent changed while planning")
    _pinned(public_path, policy["metadata_plan_sha256"])
    _pinned(prior_receipt, profile["admission_sha256"])
    for path, sha in shards.items():
        _pinned(_file(historical_dir, path), sha)
    return sealed(body)


def audit(plan, root):
    body = dict(plan)
    digest = body.pop("digest", None)
    if (
        digest != canonical_json_sha256(body)
        or not same(plan.get("boundary"), BOUNDARY)
        or plan.get("inputs_admitted") is not False
    ):
        raise ValueError("raw recovery plan seal/authority mismatch")
    policy, profile, protocol, sources = load_policy(
        root, Path(plan["policy_path"]), plan["policy_sha256"]
    )
    if (
        sources != plan["source_hashes"]
        or not same(policy["transport"], plan["transport"])
        or not same(profile["protocol_parent"], plan["protocol_parent"])
        or plan["metadata_plan_sha256"] != policy["metadata_plan_sha256"]
        or plan["prior_receipt_sha256"] != profile["admission_sha256"]
        or plan["series_name_template"] != policy["series_name_template"]
        or not same(
            plan["sample_rate_hz"], protocol["representation"]["sample_rate_hz"]
        )
        or plan["status"] != "PLAN_CALIBRATION_NATIVE_RAW_RECOVERY_ONLY"
        or plan["raw_bytes_recovered"] is not False
    ):
        raise ValueError("raw recovery source/transport changed")
    _pinned(
        Path(plan["metadata_directory"]) / "metadata_plan.json",
        plan["metadata_plan_sha256"],
    )
    _pinned(Path(plan["prior_receipt_path"]), plan["prior_receipt_sha256"])
    for path, sha in plan["historical_shard_sha256"].items():
        _pinned(_file(Path(plan["historical_directory"]), path), sha)


def regenerate(plan, root):
    return build_plan(
        root=root,
        policy_path=Path(plan["policy_path"]),
        policy_sha=plan["policy_sha256"],
        metadata_dir=Path(plan["metadata_directory"]),
        report_path=Path(plan["report_path"]),
        historical_dir=Path(plan["historical_directory"]),
        prior_receipt=Path(plan["prior_receipt_path"]),
    )


def isolated_directory(path, root, metadata_dir, historical_dir, prior_receipt):
    path = _directory(path)
    protected = [root, metadata_dir, historical_dir, Path(prior_receipt).parent]
    if any(path.resolve().is_relative_to(Path(p).resolve()) for p in protected):
        raise ValueError("isolated external raw recovery directory required")
    # Reject symlink ancestors, not merely a symlink at the final nonexistent path.
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlink raw recovery directory forbidden")
    return path


def native_slice(row, paths):
    """Direct native HDF5 slice, exact half-open sample indices, no resampling."""
    import h5py
    import numpy as np

    rate = row["sample_rate_hz"]
    values = np.empty(row["sample_count"], dtype=np.float64)
    cursor, offset = row["gps_start"], 0
    for frame in row["files"]:
        begin, finish = frame["gps_start"], frame["gps_end"]
        end = min(finish, row["gps_end"])
        if end <= cursor:
            continue
        if begin > cursor:
            raise ValueError("native raw context gap")
        first, last = _integer((cursor - begin) * rate), _integer((end - begin) * rate)
        with h5py.File(paths[frame["url"]], "r") as h:
            ds = h["strain/Strain"]

            def text(name):
                v = h["meta"][name][()]
                return v.decode() if isinstance(v, bytes) else str(v)

            if (
                text("Detector") != row["detector"]
                or float(text("GPSstart")) != begin
                or float(text("Duration")) != finish - begin
                or ds.dtype != np.dtype("float64")
                or ds.shape != (_integer((finish - begin) * rate),)
                or float(ds.attrs["Xstart"]) != begin
                or float(ds.attrs["Xspacing"]) != 1 / rate
            ):
                raise ValueError("official frame detector/dtype/native grid mismatch")
            piece = ds[first:last]
        if piece.shape != (last - first,):
            raise ValueError("native raw context short read")
        values[offset : offset + len(piece)] = piece
        offset += len(piece)
        cursor = end
    if (
        cursor != row["gps_end"]
        or offset != len(values)
        or not np.isfinite(values).all()
    ):
        raise ValueError("native raw context incomplete/nonfinite")
    if (
        hashlib.sha256(values.tobytes()).hexdigest()
        != row["historical_strain_values_sha256"]
    ):
        raise ValueError("historical native numerical SHA mismatch; preserve and stop")
    return values


def write_context(row, paths, run_dir, name_template):
    from gwpy.timeseries import TimeSeries

    values = native_slice(row, paths)
    key = [row["detector"], row["gps_start"], row["gps_end"]]
    path = run_dir / "contexts" / ("context_" + canonical_json_sha256(key) + ".hdf5")
    partial = path.with_suffix(".hdf5.partial")
    TimeSeries(
        values,
        t0=row["gps_start"],
        sample_rate=row["sample_rate_hz"],
        name=name_template.format(detector=row["detector"]),
    ).write(partial, format="hdf5")
    partial.rename(path)
    record = {
        "detector": row["detector"],
        "gps_start": row["gps_start"],
        "gps_end": row["gps_end"],
        "sample_rate_hz": row["sample_rate_hz"],
        "sample_count": len(values),
        "dtype": values.dtype.str,
        "relative_path": path.relative_to(run_dir).as_posix(),
        "file_sha256": _hash(path),
        "strain_values_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
        "historical_strain_values_sha256": row["historical_strain_values_sha256"],
        "frame_urls": [f["url"] for f in row["files"]],
    }
    write_json(path.with_suffix(".json"), sealed(record))
    return record


def run(plan, run_dir, *, root, downloader=download):
    audit(plan, root)
    if not same(regenerate(plan, root), plan):
        raise ValueError("independent recovery plan changed before download")
    run_dir = isolated_directory(
        run_dir,
        root,
        plan["metadata_directory"],
        plan["historical_directory"],
        plan["prior_receipt_path"],
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "plan.json", plan)
    lock = run_dir / "controller.lock"
    with lock.open("x") as stream:
        json.dump({"pid": os.getpid(), "plan_digest": plan["digest"]}, stream)
    try:
        (run_dir / "frames").mkdir()
        (run_dir / "contexts").mkdir()
        frames, paths, records = {}, {}, []

        def progress():
            write_json(
                run_dir / "progress.json",
                sealed(
                    {
                        "plan_digest": plan["digest"],
                        "completed_frames": len(frames),
                        "completed_contexts": len(records),
                    }
                ),
            )

        for f in plan["frames"]:
            if (
                shutil.disk_usage(run_dir).free
                < plan["new_context_payload_bytes"]
                + plan["transport"]["context_container_reserve_bytes"]
                + plan["transport"]["maximum_frame_bytes"]
            ):
                raise OSError("insufficient disk reserve for exact raw recovery")
            name = urlsplit(f["url"]).path.split("/")[-1]
            partial = run_dir / "frames" / (name + ".partial")
            downloader(f["url"], partial)
            sha, md5 = file_hashes(partial)
            if (
                md5 != f["official_md5"]
                or partial.stat().st_size > plan["transport"]["maximum_frame_bytes"]
            ):
                raise ValueError(
                    "downloaded frame differs from official MD5/size guard"
                )
            path = partial.with_suffix("")
            partial.rename(path)
            paths[f["url"]] = path
            frames[f["url"]] = {
                "relative_path": path.relative_to(run_dir).as_posix(),
                "sha256": sha,
                "md5": md5,
                "size_bytes": path.stat().st_size,
            }
            write_json(path.with_suffix(".json"), sealed(frames[f["url"]]))
            progress()
            # Validate each context as soon as its official frames are present.
            # A numerical mismatch stops before downloading later frames.
            while len(records) < len(plan["new_contexts"]):
                row = plan["new_contexts"][len(records)]
                if not all(f["url"] in paths for f in row["files"]):
                    break
                records.append(
                    write_context(row, paths, run_dir, plan["series_name_template"])
                )
                progress()
        if len(records) != len(plan["new_contexts"]):
            raise ValueError("not all planned contexts have retained frames")
        audit(plan, root)
        result = sealed(
            {
                "status": "PASS_COMPLETE_CALIBRATION_RAW_NUMERIC_MATCH_PENDING_ADMISSION",
                "plan_digest": plan["digest"],
                "frames": frames,
                "records": records,
                "boundary": BOUNDARY,
                "inputs_admitted": False,
            }
        )
        write_json(run_dir / "summary.json", result)
        return result
    except Exception as exc:
        kind = (
            "FAILED_INFRASTRUCTURE"
            if isinstance(exc, (OSError, URLError))
            else "FAILED_RAW_PROVENANCE_OR_STRUCTURE"
        )
        write_json(
            run_dir / "failure.json",
            sealed(
                {
                    "status": kind,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "plan_digest": plan["digest"],
                }
            ),
        )
        raise
    finally:
        lock.unlink()


def verify(run_dir, *, root, plan_sha, summary_sha):
    import numpy as np
    from gwpy.timeseries import TimeSeries

    run_dir = _directory(run_dir)
    if (
        any((run_dir / p).exists() for p in ("controller.lock", "failure.json"))
        or list(run_dir.rglob("*.partial"))
        or list(run_dir.rglob("*.tmp"))
    ):
        raise ValueError("raw recovery has lock/failure/partial evidence")
    _pinned(run_dir / "plan.json", plan_sha)
    _pinned(run_dir / "summary.json", summary_sha)
    plan, summary = (
        read_sealed(run_dir / "plan.json"),
        read_sealed(run_dir / "summary.json"),
    )
    audit(plan, root)
    regenerated = regenerate(plan, root)
    if (
        not same(plan, regenerated)
        or summary["status"]
        != "PASS_COMPLETE_CALIBRATION_RAW_NUMERIC_MATCH_PENDING_ADMISSION"
        or summary["plan_digest"] != plan["digest"]
        or not same(summary["boundary"], BOUNDARY)
        or summary["inputs_admitted"] is not False
    ):
        raise ValueError("raw recovery summary/independent plan mismatch")
    expected = {f["url"]: f for f in plan["frames"]}
    if set(summary["frames"]) != set(expected) or len(summary["records"]) != len(
        plan["new_contexts"]
    ):
        raise ValueError("raw recovery inventory mismatch")
    paths = {}
    for url, item in summary["frames"].items():
        if item["relative_path"] != "frames/" + urlsplit(url).path.split("/")[-1]:
            raise ValueError("noncanonical retained frame path")
        path = _file(run_dir, item["relative_path"])
        if (
            file_hashes(path) != (item["sha256"], expected[url]["official_md5"])
            or item["md5"] != expected[url]["official_md5"]
            or path.stat().st_size != item["size_bytes"]
            or not same(read_sealed(path.with_suffix(".json")), sealed(item))
        ):
            raise ValueError("retained official frame/receipt changed")
        paths[url] = path

    @lru_cache(maxsize=1)
    def official_series(url):
        # GWPy reads an entire official frame before cropping. Keep only one
        # immutable frame in memory instead of rereading it for every context.
        return TimeSeries.read(paths[url], format="hdf5.gwosc")

    for row, item in zip(plan["new_contexts"], summary["records"], strict=True):
        expected_name = (
            "contexts/context_"
            + canonical_json_sha256([row["detector"], row["gps_start"], row["gps_end"]])
            + ".hdf5"
        )
        if item["relative_path"] != expected_name:
            raise ValueError("noncanonical retained context path")
        path = _pinned(_file(run_dir, item["relative_path"]), item["file_sha256"])
        series = TimeSeries.read(path, format="hdf5")
        values = np.ascontiguousarray(series.value)
        key = (item["detector"], item["gps_start"], item["gps_end"])
        if (
            key != (row["detector"], row["gps_start"], row["gps_end"])
            or not same(item["sample_rate_hz"], row["sample_rate_hz"])
            or not same(item["sample_count"], row["sample_count"])
            or float(series.t0.value) != key[1]
            or float(series.sample_rate.value) != row["sample_rate_hz"]
            or str(series.name) != plan["series_name_template"].format(detector=key[0])
            or values.dtype != np.dtype("float64")
            or values.dtype.str != item["dtype"]
            or values.shape != (row["sample_count"],)
            or not np.isfinite(values).all()
            or hashlib.sha256(values.tobytes()).hexdigest()
            != row["historical_strain_values_sha256"]
            or item["strain_values_sha256"] != row["historical_strain_values_sha256"]
            or item["historical_strain_values_sha256"]
            != row["historical_strain_values_sha256"]
        ):
            raise ValueError("recovered context native/hash/identity mismatch")
        # Read official files through GWPy, not the direct native_slice writer path.
        pieces, cursor = [], key[1]
        for f in row["files"]:
            end = min(key[2], f["gps_end"])
            if end > cursor:
                source = official_series(f["url"]).crop(start=cursor, end=end)
                if (
                    float(source.t0.value) != cursor
                    or float(source.sample_rate.value) != row["sample_rate_hz"]
                    or source.value.shape
                    != (_integer((end - cursor) * row["sample_rate_hz"]),)
                ):
                    raise ValueError("independent GWPy half-open native read differs")
                pieces.append(source.value)
                cursor = end
        if (
            cursor != key[2]
            or np.concatenate(pieces).tobytes() != values.tobytes()
            or not same(read_sealed(path.with_suffix(".json")), sealed(item))
            or item["frame_urls"] != [f["url"] for f in row["files"]]
        ):
            raise ValueError("independent official numeric slice/receipt differs")
        _pinned(path, item["file_sha256"])
    if len(list((run_dir / "frames").iterdir())) != 2 * len(expected) or len(
        list((run_dir / "contexts").iterdir())
    ) != 2 * len(summary["records"]):
        raise ValueError("extra/missing raw frame or context files")
    for url, path in paths.items():
        if file_hashes(path) != (
            summary["frames"][url]["sha256"],
            expected[url]["official_md5"],
        ):
            raise ValueError("official frame changed during replay")
    audit(plan, root)
    _pinned(run_dir / "plan.json", plan_sha)
    _pinned(run_dir / "summary.json", summary_sha)
    return sealed(
        {
            "status": "PASS_VERIFIED_CALIBRATION_NATIVE_RAW_ONLY",
            "plan_sha256": plan_sha,
            "summary_sha256": summary_sha,
            "plan_digest": plan["digest"],
            "identity_count": plan["identity_count"],
            "new_context_count": len(plan["new_contexts"]),
            "prior_context_count": len(plan["prior_contexts"]),
            "frame_count": len(expected),
            "boundary": BOUNDARY,
            "verification_was_second_fetch": False,
            "inputs_admitted": False,
        }
    )


def admit(run_dir, *, root, plan_sha, summary_sha, verification_sha):
    run_dir = _directory(run_dir)
    _pinned(run_dir / "verification.json", verification_sha)
    verified = read_sealed(run_dir / "verification.json")
    # Admission replays the named verifier instead of trusting a status string.
    replay = verify(run_dir, root=root, plan_sha=plan_sha, summary_sha=summary_sha)
    if not same(replay, verified):
        raise ValueError("expanded admission verified evidence differs")
    _pinned(run_dir / "verification.json", verification_sha)
    plan, summary = (
        read_sealed(run_dir / "plan.json"),
        read_sealed(run_dir / "summary.json"),
    )
    return sealed(
        {
            "status": "PASS_ADMITTED_CALIBRATION_EXACT_NATIVE_INPUTS_ONLY",
            "policy_sha256": plan["policy_sha256"],
            "plan_sha256": plan_sha,
            "summary_sha256": summary_sha,
            "verification_sha256": verification_sha,
            "recovery_directory": str(run_dir.resolve()),
            "prior_receipt_path": plan["prior_receipt_path"],
            "prior_receipt_sha256": plan["prior_receipt_sha256"],
            "identity_count": plan["identity_count"],
            "identity_counts": plan["identity_counts"],
            "unique_context_count": plan["unique_context_count"],
            "records": summary["records"],
            "prior_contexts": plan["prior_contexts"],
            "source_hashes": plan["source_hashes"],
            "boundary": BOUNDARY,
        }
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=("plan", "run", "verify", "admit"), required=True
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    for name in ("policy", "metadata-dir", "report", "historical-dir", "prior-receipt"):
        parser.add_argument(f"--{name}", type=Path)
    for name in (
        "policy-sha256",
        "plan-sha256",
        "summary-sha256",
        "verification-sha256",
    ):
        parser.add_argument(f"--{name}")
    args = parser.parse_args()
    root = args.repository_root.resolve()
    required = {
        "plan": (
            "policy",
            "policy_sha256",
            "metadata_dir",
            "report",
            "historical_dir",
            "prior_receipt",
        ),
        "run": ("plan_sha256",),
        "verify": ("plan_sha256", "summary_sha256"),
        "admit": ("plan_sha256", "summary_sha256", "verification_sha256"),
    }
    if any(getattr(args, name) is None for name in required[args.stage]):
        parser.error("missing required pinned stage arguments")
    if args.stage == "plan":
        isolated_directory(
            args.run_dir,
            root,
            args.metadata_dir,
            args.historical_dir,
            args.prior_receipt,
        )
        if args.run_dir.exists():
            raise FileExistsError("prepared plan directory already exists")
        result = build_plan(
            root=root,
            policy_path=args.policy,
            policy_sha=args.policy_sha256,
            metadata_dir=args.metadata_dir,
            report_path=args.report,
            historical_dir=args.historical_dir,
            prior_receipt=args.prior_receipt,
        )
        args.run_dir.mkdir(parents=True, exist_ok=False)
        write_json(args.run_dir / "prepared_plan.json", result)
        print(
            json.dumps(
                {
                    "prepared_plan_sha256": _hash(args.run_dir / "prepared_plan.json"),
                    "new_context_count": len(result["new_contexts"]),
                    "prior_context_count": len(result["prior_contexts"]),
                    "frame_count": len(result["frames"]),
                    "new_context_payload_bytes": result["new_context_payload_bytes"],
                }
            )
        )
    elif args.stage == "run":
        prepared = _pinned(args.run_dir / "prepared_plan.json", args.plan_sha256)
        result = run(read_sealed(prepared), args.run_dir / "recovery", root=root)
    elif args.stage == "verify":
        result = verify(
            args.run_dir,
            root=root,
            plan_sha=args.plan_sha256,
            summary_sha=args.summary_sha256,
        )
        target = args.run_dir / "verification.json"
        if target.exists():
            raise ValueError("verification evidence already exists; refuse overwrite")
        write_json(target, result)
    else:
        result = admit(
            args.run_dir,
            root=root,
            plan_sha=args.plan_sha256,
            summary_sha=args.summary_sha256,
            verification_sha=args.verification_sha256,
        )
        target = args.run_dir / "admission.json"
        if target.exists():
            raise ValueError("admission evidence already exists; refuse overwrite")
        write_json(target, result)
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k
                in (
                    "status",
                    "digest",
                    "identity_count",
                    "new_context_count",
                    "prior_context_count",
                    "frame_count",
                )
            }
        )
    )


if __name__ == "__main__":
    main()

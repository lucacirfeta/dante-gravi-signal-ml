"""Isolated raw transport/comparison; not a scientific input admission gate."""

import hashlib
import json
from pathlib import Path
import os
import re
from urllib.parse import urlsplit
from urllib.request import build_opener

from .calibration_transport import _NoRedirect, _receipt, missing_intervals
from .input_preflight import _file, _hash, _select
from .input_coverage import _read
from .schema import canonical_json_sha256
from .schema_v2 import strict_json_object


class RecoveryError(ValueError):
    """Transport, sample or provenance mismatch; preserve and stop."""


def sealed(body):
    return {**body, "digest": canonical_json_sha256(body)}


def read_sealed(path):
    value = strict_json_object(_read(path).decode(), label="recovery evidence")
    body = dict(value)
    digest = body.pop("digest", None)
    if digest != canonical_json_sha256(body):
        raise RecoveryError("recovery evidence seal mismatch")
    return value


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
    temporary.replace(path)


def build_plan(spec, adapter, *, root, report_path, report_sha, receipt_path):
    diagnosis, payload, missing = missing_intervals(spec, adapter, root)
    raw = _read(report_path)
    if hashlib.sha256(raw).hexdigest() != report_sha:
        raise RecoveryError("metadata report SHA mismatch")
    report = strict_json_object(raw.decode(), label="metadata report")
    body = dict(report)
    seal = body.pop("report_digest", None)
    rate = _select(
        payload, adapter.input_preflight_binding().declarations["sample_rate_hz"]
    )
    if (
        seal != canonical_json_sha256(body)
        or report["status"] != "PASS_PUBLIC_TRANSPORT_METADATA_ONLY"
        or report["parent"] != diagnosis["input_contract"]
        or report["sample_rate_hz"] != rate
        or {(x["detector"], x["gps_start"], x["gps_end"]) for x in report["intervals"]}
        != set(missing)
        or len(report["intervals"]) != len(missing)
        or report["scientific_execution_ready"] is not False
        or not re.fullmatch(r"[A-Za-z0-9_]+", report["candidate_dataset"])
    ):
        raise RecoveryError("metadata report parent/interval/authority mismatch")
    historical = _receipt(
        _read(receipt_path),
        report["historical_receipt_sha256"],
        diagnosis["input_contract"],
        missing,
        rate,
    )
    sources = [
        "src/dante_workflow/calibration_recovery.py",
        "scripts/recover_dante_workflow_calibration_inputs.py",
        "src/dante_workflow/calibration_transport.py",
        "src/dante_workflow/calibration_inputs.py",
        "src/dante_workflow/input_coverage.py",
        "src/dante_workflow/input_preflight.py",
        "src/dante_workflow/schema.py",
        "src/dante_workflow/schema_v2.py",
        "src/dante_workflow/adapters/o4a_corrected.py",
        "src/dante_light/o4a_corrected_protocol.py",
    ]
    return sealed(
        {
            "schema_version": 1,
            "status": "PLAN_RAW_RECOVERY_ONLY",
            "parent": diagnosis["input_contract"],
            "dataset": report["candidate_dataset"],
            "report_sha256": report_sha,
            "report": report,
            "report_path": str(Path(report_path).resolve()),
            "historical_receipt_path": str(Path(receipt_path).resolve()),
            "historical_receipt_sha256": report["historical_receipt_sha256"],
            "historical_receipt": historical,
            "sample_rate_hz": rate,
            "source_hashes": {p: _hash(_file(root, p)) for p in sources},
            "replacement_bytes_admitted": False,
            "scientific_execution_ready": False,
        }
    )


def official_checksums(dataset):
    url = f"https://gwosc.org/archive/md5/{dataset}/strain-hdf.txt"
    with build_opener(_NoRedirect()).open(url, timeout=30) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise RecoveryError("official checksum manifest too large")
    checksums = {}
    for line in raw.decode().splitlines():
        md5, relative = line.split()
        name = relative.split("/")[-1]
        if not re.fullmatch(r"[a-f0-9]{32}", md5) or name in checksums:
            raise RecoveryError("official checksum manifest ambiguity")
        checksums[name] = md5
    return raw, checksums


def file_hashes(path):
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def download(url, path):
    # Transfer guard only, not a scientific parameter. No redirects or retries.
    with (
        build_opener(_NoRedirect()).open(url, timeout=30) as response,
        path.open("xb") as out,
    ):
        total = 0
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            total += len(chunk)
            if total > 512 * 1024 * 1024:
                raise RecoveryError("frame exceeds bounded transfer size")
            out.write(chunk)


def samples_from_frames(interval, paths, rate):
    import h5py
    import numpy as np

    detector, start, end = (
        interval["detector"],
        interval["gps_start"],
        interval["gps_end"],
    )
    pieces, cursor = [], start
    for frame in sorted(interval["files"], key=lambda f: f["gps_start"]):
        begin, finish = frame["gps_start"], frame["gps_end"]
        left, right = max(cursor, begin), min(end, finish)
        if right <= left:
            continue
        if left != cursor:
            raise RecoveryError("native context has a gap")
        with h5py.File(paths[frame["url"]], "r") as handle:
            ds, meta = handle["strain/Strain"], handle["meta"]

            def text(name):
                item = meta[name][()]
                return item.decode() if isinstance(item, bytes) else str(item)

            if (
                text("Detector") != detector
                or text("GPSstart") != str(begin)
                or text("Duration") != str(finish - begin)
                or ds.dtype != np.dtype("float64")
                or ds.shape != ((finish - begin) * rate,)
                or float(ds.attrs["Xstart"]) != begin
                or float(ds.attrs["Xspacing"]) != 1 / rate
            ):
                raise RecoveryError("official frame detector/dtype/grid/shape mismatch")
            part = np.ascontiguousarray(
                ds[(left - begin) * rate : (right - begin) * rate]
            )
            if not np.isfinite(part).all():
                raise RecoveryError("selected native samples nonfinite")
            pieces.append(part)
            cursor = right
    if cursor != end:
        raise RecoveryError("native context incomplete")
    values = np.concatenate(pieces)
    if values.shape != ((end - start) * rate,):
        raise RecoveryError("native sample count mismatch")
    return values


def acquire(
    plan, run_dir, *, root, downloader=download, checksum_fetch=official_checksums
):
    from gwpy.timeseries import TimeSeries

    run_dir = Path(run_dir)
    if (
        not run_dir.is_absolute()
        or run_dir.resolve().is_relative_to(Path(root).resolve())
        or any(p.is_symlink() for p in (run_dir, *run_dir.parents))
    ):
        raise RecoveryError("new external non-symlink run directory required")
    audit_sources(plan, root)
    run_dir.mkdir(parents=True, exist_ok=False)
    lock = run_dir / "controller.lock"
    lock.write_text(str(os.getpid()))
    write_json(run_dir / "plan.json", plan)
    try:
        raw, checksums = checksum_fetch(plan["dataset"])
        (run_dir / "official_md5.txt").write_bytes(raw)
        paths, frames, records = {}, {}, []
        (run_dir / "frames").mkdir()
        (run_dir / "contexts").mkdir()
        old = {
            (x["detector"], x["gps_start"], x["gps_end"]): x
            for x in plan["historical_receipt"]["records"]
        }
        for interval in plan["report"]["intervals"]:
            for frame in interval["files"]:
                url = frame["url"]
                parsed = urlsplit(url)
                name = parsed.path.split("/")[-1]
                if (
                    parsed.scheme != "https"
                    or parsed.netloc != "gwosc.org"
                    or not parsed.path.startswith(f"/archive/data/{plan['dataset']}/")
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+\.hdf5", name)
                    or parsed.query
                    or parsed.fragment
                    or name not in checksums
                ):
                    raise RecoveryError("official pinned file URL/checksum invalid")
                if url not in paths:
                    partial = run_dir / "frames" / (name + ".partial")
                    downloader(url, partial)
                    sha, md5 = file_hashes(partial)
                    if md5 != checksums[name]:
                        raise RecoveryError(
                            "download MD5 differs from official manifest"
                        )
                    path = partial.with_suffix("")
                    if path.exists():
                        raise RecoveryError("frame filename collision")
                    partial.rename(path)
                    paths[url] = path
                    frames[url] = {
                        "path": path.relative_to(run_dir).as_posix(),
                        "sha256": sha,
                        "md5": md5,
                    }
            values = samples_from_frames(interval, paths, plan["sample_rate_hz"])
            key = (interval["detector"], interval["gps_start"], interval["gps_end"])
            digest = hashlib.sha256(values.tobytes()).hexdigest()
            name = f"{key[0]}_{key[1]}_{key[2]}_{digest}.hdf5"
            context = run_dir / "contexts" / name
            TimeSeries(
                values,
                t0=key[1],
                sample_rate=plan["sample_rate_hz"],
                name=f"{key[0]}:STRAIN",
                unit="strain",
            ).write(context, format="hdf5")
            item = {
                "detector": key[0],
                "gps_start": key[1],
                "gps_end": key[2],
                "path": context.relative_to(run_dir).as_posix(),
                "file_sha256": _hash(context),
                "strain_values_sha256": digest,
                "dtype": values.dtype.str,
                "sample_count": len(values),
                "numerical_bytes_match": digest == old[key]["strain_values_sha256"],
                "container_bytes_match": _hash(context) == old[key]["file_sha256"],
            }
            write_json(context.with_suffix(".json"), sealed(item))
            if not item["numerical_bytes_match"]:
                raise RecoveryError(
                    "historical raw numerical SHA differs; stop for review"
                )
            records.append(item)
            write_json(
                run_dir / "progress.json", sealed({"completed_contexts": len(records)})
            )
        audit_sources(plan, root)
        summary = sealed(
            {
                "status": "COMPLETE_RAW_NUMERIC_MATCH_PENDING_ADMISSION",
                "plan_digest": plan["digest"],
                "official_md5_sha256": hashlib.sha256(raw).hexdigest(),
                "frames": frames,
                "records": records,
                "replacement_bytes_admitted": False,
                "scientific_execution_ready": False,
            }
        )
        write_json(run_dir / "summary.json", summary)
        return summary
    except Exception as exc:
        write_json(
            run_dir / "failure.json",
            sealed(
                {
                    "status": "FAILED_RAW_RECOVERY_STOP",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "plan_digest": plan["digest"],
                }
            ),
        )
        raise
    finally:
        lock.unlink()


def audit_sources(plan, root):
    body = dict(plan)
    digest = body.pop("digest", None)
    if digest != canonical_json_sha256(body):
        raise RecoveryError("plan seal mismatch")
    if (
        plan["replacement_bytes_admitted"] is not False
        or plan["scientific_execution_ready"] is not False
    ):
        raise RecoveryError("transport plan cannot admit scientific inputs")
    for field, pin in (
        ("report_path", "report_sha256"),
        ("historical_receipt_path", "historical_receipt_sha256"),
    ):
        path = Path(plan[field])
        if (
            not path.is_absolute()
            or any(p.is_symlink() for p in (path, *path.parents))
            or _hash(path) != plan[pin]
        ):
            raise RecoveryError("external parent SHA/path mismatch")
    if (
        strict_json_object(
            _read(Path(plan["historical_receipt_path"])).decode(), label="old receipt"
        )
        != plan["historical_receipt"]
    ):
        raise RecoveryError("historical receipt snapshot differs")
    for path, sha in plan["source_hashes"].items():
        if _hash(_file(Path(root).resolve(), path)) != sha:
            raise RecoveryError("source SHA mismatch")
    parent = plan["parent"]
    if _hash(_file(Path(root).resolve(), parent["path"])) != parent["sha256"]:
        raise RecoveryError("parent scientific config changed")


def verify(run_dir, *, root):
    import numpy as np
    from gwpy.timeseries import TimeSeries

    run_dir = Path(run_dir).resolve()
    if any(
        (run_dir / name).exists() for name in ("controller.lock", "failure.json")
    ) or list(run_dir.rglob("*.partial")):
        raise RecoveryError("run has lock/failure/partial evidence")
    plan, summary = (
        read_sealed(run_dir / "plan.json"),
        read_sealed(run_dir / "summary.json"),
    )
    audit_sources(plan, root)
    if (
        summary["plan_digest"] != plan["digest"]
        or summary["status"] != "COMPLETE_RAW_NUMERIC_MATCH_PENDING_ADMISSION"
    ):
        raise RecoveryError("summary parent/status mismatch")
    if _hash(run_dir / "official_md5.txt") != summary["official_md5_sha256"]:
        raise RecoveryError("official checksum snapshot changed")
    checksums = {
        line.split()[1].split("/")[-1]: line.split()[0]
        for line in (run_dir / "official_md5.txt").read_text().splitlines()
    }
    expected_urls = {f["url"] for i in plan["report"]["intervals"] for f in i["files"]}
    if (
        set(summary["frames"]) != expected_urls
        or summary["replacement_bytes_admitted"] is not False
        or summary["scientific_execution_ready"] is not False
    ):
        raise RecoveryError("frame inventory/authority changed")
    paths = {}
    for url, item in summary["frames"].items():
        path = _file(run_dir, item["path"])
        if file_hashes(path) != (item["sha256"], item["md5"]):
            raise RecoveryError("retained frame bytes changed")
        if checksums.get(path.name) != item["md5"]:
            raise RecoveryError("frame MD5 no longer matches official snapshot")
        paths[url] = path
    intervals = plan["report"]["intervals"]
    historical = {
        (x["detector"], x["gps_start"], x["gps_end"]): x
        for x in plan["historical_receipt"]["records"]
    }
    if len(summary["records"]) != len(intervals):
        raise RecoveryError("recovery record count mismatch")
    for interval, item in zip(intervals, summary["records"], strict=True):
        key = (item["detector"], item["gps_start"], item["gps_end"])
        if key != (interval["detector"], interval["gps_start"], interval["gps_end"]):
            raise RecoveryError("recovery interval identity changed")
        path = _file(run_dir, item["path"])
        series = TimeSeries.read(path, format="hdf5")
        values = np.ascontiguousarray(series.value)
        original = samples_from_frames(interval, paths, plan["sample_rate_hz"])
        digest = hashlib.sha256(values.tobytes()).hexdigest()
        if (
            float(series.t0.value) != key[1]
            or float(series.sample_rate.value) != plan["sample_rate_hz"]
            or values.dtype.str != item["dtype"]
            or len(values) != item["sample_count"]
            or digest != item["strain_values_sha256"]
            or digest != historical[key]["strain_values_sha256"]
            or not np.array_equal(values, original)
            or _hash(path) != item["file_sha256"]
            or item["numerical_bytes_match"] is not True
            or item["container_bytes_match"]
            != (_hash(path) == historical[key]["file_sha256"])
        ):
            raise RecoveryError("context raw/identity/container comparison changed")
        record = read_sealed(path.with_suffix(".json"))
        if {k: v for k, v in record.items() if k != "digest"} != item:
            raise RecoveryError("context receipt differs")
    if len(list((run_dir / "contexts").glob("*.hdf5"))) != len(intervals):
        raise RecoveryError("extra/missing context files")
    if len(list((run_dir / "frames").iterdir())) != len(expected_urls) or len(
        list((run_dir / "contexts").glob("*.json"))
    ) != len(intervals):
        raise RecoveryError("extra/missing frame/receipt inventory")
    return sealed(
        {
            "status": "PASS_VERIFIED_RAW_NUMERIC_MATCH_ONLY",
            "run_digest": summary["digest"],
            "interval_count": len(intervals),
            "container_match_count": sum(
                x["container_bytes_match"] for x in summary["records"]
            ),
            "replacement_bytes_admitted": False,
            "scientific_execution_ready": False,
            "verification_was_second_fetch": False,
        }
    )

"""Public file metadata availability only; never acquire or admit strain."""

import hashlib
from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from .calibration_inputs import inspect_calibration_inputs
from .input_coverage import _components, _read
from .input_preflight import _file, _select
from .schema import canonical_json_sha256
from .schema_v2 import strict_json_object


class TransportPreflightError(ValueError):
    """An untrusted receipt or incomplete public metadata must fail closed."""


def _integer(value):
    if type(value) not in (int, float) or not float(value).is_integer():
        raise TransportPreflightError("finite integral GPS/rate required")
    return int(value)


def missing_intervals(spec, adapter, root):
    """Reuse the audited metadata reader, never the score-containing selector."""
    diagnosis = inspect_calibration_inputs(spec, adapter, root=root)
    if diagnosis["status"] != "BLOCKED_CALIBRATION_SUPPLEMENT_REQUIRED":
        raise TransportPreflightError("expected a frozen missing-input diagnosis")
    contract = diagnosis["input_contract"]
    payload = strict_json_object(
        _read(_file(root, contract["path"])).decode(), label="protocol"
    )
    binding = adapter.input_coverage_binding()
    ref = adapter.input_preflight_binding().references["raw_manifest"]
    manifest_ref = _select(payload, ref)
    components = _components(
        _read(_file(root, manifest_ref["path"])), binding, adapter.detectors
    )
    spans = set()
    for row in adapter.iter_calibration_input_metadata(root, payload):
        start, end = row["required_padded_interval"]
        if not any(a <= start and b >= end for a, b in components[row["detector"]][1]):
            spans.add((row["detector"], _integer(start), _integer(end)))
    if len(spans) != diagnosis["missing_manifest_intervals"]:
        raise TransportPreflightError("missing interval identity drift")
    # Rechecking the full metadata binding also detects concurrent source drift.
    if inspect_calibration_inputs(spec, adapter, root=root) != diagnosis:
        raise TransportPreflightError("calibration metadata changed")
    return diagnosis, payload, sorted(spans)


def _receipt(data, sha, contract, missing, rate):
    if hashlib.sha256(data).hexdigest() != sha:
        raise TransportPreflightError("historical receipt SHA mismatch")
    value = strict_json_object(data.decode(), label="historical acquisition")
    body = dict(value)
    seal = body.pop("manifest_digest", None)
    records = body.get("records")
    if (
        seal != canonical_json_sha256(body)
        or body.get("schema_version") != 1
        or body.get("status") != "COMPLETE_CONTENT_ADDRESSED_INPUTS"
        or body.get("protocol_digest") != contract["seal"]
        or body.get("protocol_reference")
        != {"path": contract["path"], "sha256": contract["sha256"]}
        or not isinstance(records, list)
        or type(body.get("record_count")) is not int
        or body["record_count"] != len(records)
        or body.get("record_digest") != canonical_json_sha256(records)
        or body.get("network_fetch_was_outcome_blind") is not True
        or body.get("scores_or_labels_accessed_during_fetch") != []
    ):
        raise TransportPreflightError("historical receipt seal/parent mismatch")
    found = set()
    for row in records:
        key = (row["detector"], _integer(row["gps_start"]), _integer(row["gps_end"]))
        if (
            key in found
            or key not in missing
            or row.get("sample_rate_hz") != rate
            or type(row.get("sample_count")) is not int
            or row["sample_count"] != (key[2] - key[1]) * rate
            or any(
                not isinstance(row.get(field), str)
                or not re.fullmatch(r"[0-9a-f]{64}", row[field])
                for field in ("file_sha256", "strain_values_sha256")
            )
        ):
            raise TransportPreflightError("historical interval/geometry/hash mismatch")
        found.add(key)
    if found != set(missing):
        raise TransportPreflightError("historical missing-interval set differs")
    return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_metadata(url):
    """Bounded JSON GET only; raw file URLs are never requested."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "gwosc.org"
        or not re.fullmatch(
            r"/archive/links/[A-Za-z0-9_]+/[A-Za-z0-9]+/\d+/\d+/json/", parsed.path
        )
        or parsed.query
        or parsed.fragment
    ):
        raise TransportPreflightError("metadata GET endpoint required")
    with build_opener(_NoRedirect()).open(url, timeout=25) as response:
        if response.geturl() != url:
            raise TransportPreflightError("metadata redirect refused")
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise TransportPreflightError("metadata response too large")
    return data


def inspect_transport_metadata(
    *, receipt_data, receipt_sha, contract, missing, sample_rate, dataset, fetch
):
    """Candidate release coverage, not historical calibration equivalence."""
    if not isinstance(dataset, str) or not re.fullmatch(r"[A-Za-z0-9_]+", dataset):
        raise TransportPreflightError("explicit candidate dataset required")
    if not missing or len(set(missing)) != len(missing):
        raise TransportPreflightError("unique nonempty frozen interval set required")
    historical = _receipt(receipt_data, receipt_sha, contract, missing, sample_rate)
    reports = []
    files = {}
    for detector, start, end in missing:
        url = (
            f"https://gwosc.org/archive/links/{dataset}/{detector}/{start}/{end}/json/"
        )
        raw = fetch(url)
        value = strict_json_object(raw.decode(), label="GWOSC metadata")
        if (
            value.get("dataset") != dataset
            or _integer(value.get("GPSstart")) != start
            or _integer(value.get("GPSend")) != end
            or not isinstance(value.get("strain"), list)
        ):
            raise TransportPreflightError("GWOSC dataset/query mismatch")
        selected = []
        for row in value["strain"]:
            if row.get("format") != "hdf5":
                continue
            parsed = urlsplit(row.get("url", ""))
            if (
                row.get("detector") != detector
                or _integer(row.get("sampling_rate")) != sample_rate
                or parsed.scheme != "https"
                or parsed.netloc != "gwosc.org"
                or not parsed.path.startswith(f"/archive/data/{dataset}/")
                or not parsed.path.endswith(".hdf5")
                or parsed.query
                or parsed.fragment
            ):
                raise TransportPreflightError(
                    "GWOSC detector/rate/file origin mismatch"
                )
            begin = _integer(row.get("GPSstart"))
            duration = _integer(row.get("duration"))
            if duration <= 0:
                raise TransportPreflightError("invalid file duration")
            item = {
                "detector": detector,
                "gps_start": begin,
                "gps_end": begin + duration,
                "sample_rate_hz": sample_rate,
                "url": row["url"],
            }
            if item in selected:
                raise TransportPreflightError("duplicate public file metadata")
            if item["url"] in files and files[item["url"]] != item:
                raise TransportPreflightError("inconsistent public file metadata")
            selected.append(item)
            files[item["url"]] = item
        cursor = start
        for item in sorted(selected, key=lambda x: x["gps_start"]):
            if item["gps_start"] > cursor:
                break
            cursor = max(cursor, item["gps_end"])
        if cursor < end:
            raise TransportPreflightError("public file coverage hole")
        reports.append(
            {
                "detector": detector,
                "gps_start": start,
                "gps_end": end,
                "metadata_url": url,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "files": selected,
            }
        )
    body = {
        "schema_version": 1,
        "status": "PASS_PUBLIC_TRANSPORT_METADATA_ONLY",
        "candidate_dataset": dataset,
        "queried_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent": contract,
        "historical_receipt_sha256": receipt_sha,
        "historical_receipt_seal": historical["manifest_digest"],
        "interval_count": len(reports),
        "unique_file_count": len(files),
        "sample_rate_hz": sample_rate,
        "intervals": reports,
        "public_file_time_coverage_checked": True,
        "historical_release_version_known": False,
        "historical_release_equivalence_checked": False,
        "raw_files_downloaded": False,
        "raw_samples_checked": False,
        "dq_validity_checked": False,
        "score_values_read": False,
        "replacement_bytes_admitted": False,
        "scientific_execution_ready": False,
    }
    return {**body, "report_digest": canonical_json_sha256(body)}


def run_preflight(spec, adapter, *, root, receipt_path, receipt_sha, dataset):
    root = Path(root).resolve()
    path = Path(receipt_path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise TransportPreflightError("absolute non-symlink receipt required")
    diagnosis, payload, missing = missing_intervals(spec, adapter, root)
    contract = diagnosis["input_contract"]
    rate_pointer = adapter.input_preflight_binding().declarations["sample_rate_hz"]
    rate = _integer(_select(payload, rate_pointer))
    data = _read(path)
    report = inspect_transport_metadata(
        receipt_data=data,
        receipt_sha=receipt_sha,
        contract=contract,
        missing=missing,
        sample_rate=rate,
        dataset=dataset,
        fetch=fetch_metadata,
    )
    if (
        _read(path) != data
        or inspect_calibration_inputs(spec, adapter, root=root) != diagnosis
    ):
        raise TransportPreflightError("receipt/calibration changed during queries")
    return report

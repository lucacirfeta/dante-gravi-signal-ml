"""Transport planning rejects drift without fetching scientific input bytes."""

from copy import deepcopy
import hashlib
import json

import pytest

from src.dante_workflow import calibration_transport as transport
from src.dante_workflow.schema import canonical_json_sha256
from tests.test_dante_workflow_calibration_inputs import (
    calibrated as calibrated,
    fixture as fixture,
    make_missing,
    receipt as make_receipt,
)


def encoded(value):
    return json.dumps(value, allow_nan=False).encode()


@pytest.fixture
def case():
    contract = {"path": "config/synthetic.json", "sha256": "a" * 64, "seal": "b" * 64}
    missing = [("H1", 100, 140), ("V1", 200, 240)]
    records = [
        {
            "detector": detector,
            "gps_start": start,
            "gps_end": end,
            "sample_rate_hz": 32,
            "sample_count": (end - start) * 32,
            "file_sha256": "c" * 64,
            "strain_values_sha256": "d" * 64,
        }
        for detector, start, end in missing
    ]
    receipt = {
        "schema_version": 1,
        "status": "COMPLETE_CONTENT_ADDRESSED_INPUTS",
        "protocol_reference": {"path": contract["path"], "sha256": contract["sha256"]},
        "protocol_digest": contract["seal"],
        "records": records,
        "record_count": len(records),
        "record_digest": canonical_json_sha256(records),
        "network_fetch_was_outcome_blind": True,
        "scores_or_labels_accessed_during_fetch": [],
    }

    def metadata(url):
        parts = url.split("/")
        detector, start, end = parts[-5:-2]
        start, end = int(start), int(end)
        return {
            "dataset": "Synthetic_R1",
            "GPSstart": start,
            "GPSend": end,
            "strain": [
                {
                    "detector": detector,
                    "GPSstart": start,
                    "duration": end - start,
                    "sampling_rate": 32,
                    "format": "hdf5",
                    "url": f"https://gwosc.org/archive/data/Synthetic_R1/{detector}_{start}.hdf5",
                }
            ],
        }

    return contract, missing, receipt, metadata


def execute(case, change_receipt=None, change_metadata=None):
    contract, missing, original, metadata = case
    receipt = deepcopy(original)
    if change_receipt:
        change_receipt(receipt)
    receipt["record_digest"] = canonical_json_sha256(receipt["records"])
    receipt["manifest_digest"] = canonical_json_sha256(receipt)
    raw = encoded(receipt)
    calls = []

    def fetch(url):
        calls.append(url)
        value = metadata(url)
        if change_metadata:
            change_metadata(value)
        return encoded(value)

    report = transport.inspect_transport_metadata(
        receipt_data=raw,
        receipt_sha=hashlib.sha256(raw).hexdigest(),
        contract=contract,
        missing=missing,
        sample_rate=32,
        dataset="Synthetic_R1",
        fetch=fetch,
    )
    return report, calls


def test_pass_is_only_public_file_metadata(case):
    report, calls = execute(case)
    assert report["status"] == "PASS_PUBLIC_TRANSPORT_METADATA_ONLY"
    assert report["interval_count"] == 2
    assert report["unique_file_count"] == 2
    assert all(url.endswith("/json/") for url in calls)
    assert all(
        report[key] is False
        for key in (
            "raw_files_downloaded",
            "raw_samples_checked",
            "score_values_read",
            "replacement_bytes_admitted",
            "scientific_execution_ready",
            "dq_validity_checked",
            "historical_release_version_known",
            "historical_release_equivalence_checked",
        )
    )
    body = dict(report)
    digest = body.pop("report_digest")
    assert digest == canonical_json_sha256(body)


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(protocol_digest="e" * 64),
        lambda x: x["protocol_reference"].update(sha256="e" * 64),
        lambda x: x.update(network_fetch_was_outcome_blind=False),
        lambda x: x.update(scores_or_labels_accessed_during_fetch=["score"]),
        lambda x: x.update(record_count=True),
        lambda x: x["records"].pop(),
        lambda x: x["records"].append(x["records"][0]),
        lambda x: x["records"][0].update(detector="L1"),
        lambda x: x["records"][0].update(gps_start=101),
        lambda x: x["records"][0].update(sample_rate_hz=64),
        lambda x: x["records"][0].update(sample_count=1),
        lambda x: x["records"][0].update(strain_values_sha256="unknown"),
    ],
)
def test_receipt_mismatch_before_network(case, change):
    with pytest.raises(transport.TransportPreflightError):
        execute(case, change_receipt=change)


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(dataset="Other_R2"),
        lambda x: x.update(GPSend=141),
        lambda x: x.update(strain=[]),
        lambda x: x["strain"][0].update(detector="L1"),
        lambda x: x["strain"][0].update(sampling_rate=64),
        lambda x: x["strain"][0].update(GPSstart=101),
        lambda x: x["strain"][0].update(duration=39),
        lambda x: x["strain"][0].update(duration=0),
        lambda x: x["strain"][0].update(url="https://foreign.org/file.hdf5"),
        lambda x: x["strain"][0].update(
            url="https://gwosc.org/archive/data/Other_R2/file.hdf5"
        ),
        lambda x: x["strain"].append(x["strain"][0]),
    ],
)
def test_metadata_drift_and_holes_fail(case, change):
    with pytest.raises(transport.TransportPreflightError):
        execute(case, change_metadata=change)


def test_union_not_single_frame_coverage(case):
    def split(value):
        first = value["strain"][0]
        second = dict(first)
        first["duration"] = 20
        second["GPSstart"] += 20
        second["duration"] = 20
        second["url"] = second["url"].replace(".hdf5", "_second.hdf5")
        value["strain"].append(second)

    report, _ = execute(case, change_metadata=split)
    assert report["unique_file_count"] == 4


def test_sha_pin_before_any_get(case):
    contract, missing, receipt, _ = case
    with pytest.raises(transport.TransportPreflightError, match="SHA"):
        transport.inspect_transport_metadata(
            receipt_data=encoded(receipt),
            receipt_sha="0" * 64,
            contract=contract,
            missing=missing,
            sample_rate=32,
            dataset="Synthetic_R1",
            fetch=lambda url: pytest.fail("must not GET before pin validation"),
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://gwosc.org/archive/data/O4a/file.hdf5",
        "https://foreign.org/archive/links/O4a/H1/100/140/json/",
        "http://gwosc.org/archive/links/O4a/H1/100/140/json/",
    ],
)
def test_network_helper_refuses_raw_or_foreign_urls(url):
    with pytest.raises(transport.TransportPreflightError, match="endpoint"):
        transport.fetch_metadata(url)


def test_redirect_handler_never_follows_raw_target():
    assert (
        transport._NoRedirect().redirect_request(
            None, None, 302, "Found", {}, "https://gwosc.org/raw.hdf5"
        )
        is None
    )


def test_frozen_missing_geometry_is_wired(calibrated):
    make_missing(calibrated)
    c = calibrated.base
    diagnosis, _, missing = transport.missing_intervals(c.spec, c.adapter, c.root)
    assert diagnosis["identity_count"] == 2
    assert missing == [("H1", 3, 18)]
    assert not (c.root / "workflow").exists()


def test_complete_binding_not_reacquired(calibrated):
    c = calibrated.base
    with pytest.raises(transport.TransportPreflightError, match="missing-input"):
        transport.missing_intervals(c.spec, c.adapter, c.root)


def test_run_preflight_has_no_raw_fetch_or_admission(calibrated, monkeypatch):
    make_missing(calibrated)
    path, value, write, _ = make_receipt(calibrated)
    value["records"][0]["strain_values_sha256"] = "e" * 64
    sha = write()
    calls = []

    def fetch(url):
        calls.append(url)
        return encoded(
            {
                "dataset": "Synthetic_R1",
                "GPSstart": 3,
                "GPSend": 18,
                "strain": [
                    {
                        "detector": "H1",
                        "sampling_rate": 2,
                        "GPSstart": 0,
                        "duration": 20,
                        "format": "hdf5",
                        "url": "https://gwosc.org/archive/data/Synthetic_R1/H1.hdf5",
                    }
                ],
            }
        )

    monkeypatch.setattr(transport, "fetch_metadata", fetch)
    c = calibrated.base
    report = transport.run_preflight(
        c.spec,
        c.adapter,
        root=c.root,
        receipt_path=path,
        receipt_sha=sha,
        dataset="Synthetic_R1",
    )
    assert len(calls) == 1
    assert report["sample_rate_hz"] == 2
    assert not report["replacement_bytes_admitted"]


def test_concurrent_receipt_drift_refused(calibrated, monkeypatch):
    make_missing(calibrated)
    path, value, write, _ = make_receipt(calibrated)
    value["records"][0]["strain_values_sha256"] = "e" * 64
    sha = write()

    def changed(**kwargs):
        path.write_bytes(b"changed")
        return {"status": "must not escape"}

    monkeypatch.setattr(transport, "inspect_transport_metadata", changed)
    c = calibrated.base
    with pytest.raises(transport.TransportPreflightError, match="changed"):
        transport.run_preflight(
            c.spec,
            c.adapter,
            root=c.root,
            receipt_path=path,
            receipt_sha=sha,
            dataset="Synthetic_R1",
        )

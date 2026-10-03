"""Coverage is transport evidence, never numerical equivalence or admission."""

import hashlib
import json
from pathlib import Path

import pytest

from src.dante_workflow import calibration_raw_transport as transport
from src.dante_workflow.calibration_recovery import sealed


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row(start=100, end=200):
    sha = hashlib.sha256(b"historical").hexdigest()
    return {
        "detector": "H1",
        "gps_start": start,
        "gps_end": end,
        "sha256": sha,
        "physical_copies": [
            {
                "relative_path": f"{start}/H1_{start}_{end}.hdf5",
                "sha256": sha,
                "size_bytes": len(b"historical"),
            }
        ],
    }


def response(start=100, end=200, dataset="TEST", detector="H1", rate=4):
    return {
        "dataset": dataset,
        "GPSstart": start,
        "GPSend": end,
        "strain": [
            {
                "format": "hdf5",
                "GPSstart": start,
                "duration": end - start,
                "detector": detector,
                "sampling_rate": rate,
                "url": f"https://gwosc.org/archive/data/{dataset}/1/frame.hdf5",
            }
        ],
    }


def encoded(value):
    return json.dumps(value).encode()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    mod = "src/dante_workflow/calibration_raw_transport.py"
    path = root / mod
    path.parent.mkdir(parents=True)
    path.write_bytes(Path(transport.__file__).read_bytes())
    manifest = {"path": "manifest.jsonl", "sha256": put(root / "manifest.jsonl", row())}
    protocol = {
        "representation": {"sample_rate_hz": 4},
        "source_references": {"raw_manifest": manifest},
    }
    parent = {"path": "protocol.json", "sha256": put(root / "protocol.json", protocol)}
    profile = {"protocol_parent": parent}
    ref = {"path": "profile.json", "sha256": put(root / "profile.json", profile)}
    report = {
        "status": "BLOCKED_PRODUCTIVE_RAW_FILES",
        "profile_sha256": ref["sha256"],
        "parents": {"protocol_parent": parent},
        "raw_manifest": manifest,
        "scientific_execution_ready": False,
        "input_bytes_ready": False,
        "physical_input_audit": {
            "records": [
                {
                    "detector": "H1",
                    "gps_start": 100,
                    "gps_end": 200,
                    "sha256": row()["sha256"],
                    "declared_copies": 1,
                    "available_copies": [],
                }
            ],
            "missing_logical_span_count": 1,
            "required_logical_span_count": 1,
        },
    }
    report_path = tmp_path / "report.json"
    policy = {
        "schema_version": 1,
        "status": "TRANSPORT_METADATA_ONLY_V1",
        "production_profile": ref,
        "blocked_preflight_sha256": put(report_path, sealed(report)),
        "candidate_dataset": "TEST",
        "metadata_bucket_s": 1000000,
        "source_paths": [mod],
        "boundary": transport.BOUNDARY,
    }
    policy_path = root / "policy.json"
    policy_sha = put(policy_path, policy)
    backup = tmp_path / "backup"
    backup.mkdir()
    monkeypatch.setattr(transport, "fetch_metadata", lambda url: encoded(response()))
    monkeypatch.setattr(
        transport,
        "official_checksums",
        lambda dataset: (b"0123456789abcdef0123456789abcdef  frame.hdf5\n", {}),
    )
    return {
        "root": root,
        "policy_path": policy_path,
        "policy_sha": policy_sha,
        "report_path": report_path,
        "run_dir": tmp_path / "evidence",
        "backup_roots": [backup],
    }


def test_plan_and_independent_local_replay(fixture, monkeypatch):
    plan = transport.execute(**fixture, stage="plan")
    fixture["expected_plan_sha"] = hashlib.sha256(
        (fixture["run_dir"] / "metadata_plan.json").read_bytes()
    ).hexdigest()
    assert plan["inventory"]["required_logical_span_count"] == 1
    assert plan["inventory"]["unique_public_file_count"] == 1
    assert plan["boundary"] == transport.BOUNDARY
    assert plan["backup_audit"][0]["matching_files"] == []
    monkeypatch.setattr(
        transport, "fetch_metadata", lambda _: pytest.fail("second network fetch")
    )
    monkeypatch.setattr(
        transport, "official_checksums", lambda _: pytest.fail("second network fetch")
    )
    verified = transport.execute(**fixture, stage="verify")
    assert verified["status"] == "PASS_VERIFIED_PUBLIC_RAW_METADATA_ONLY"
    assert verified["verification_was_second_fetch"] is False
    with pytest.raises(FileExistsError):
        transport.execute(**fixture, stage="plan")


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("candidate_dataset", "../other"),
        ("metadata_bucket_s", True),
        ("metadata_bucket_s", 0),
        ("status", "PASS_SCIENCE"),
    ],
)
def test_policy_rejection(fixture, field, value):
    policy = json.loads(fixture["policy_path"].read_text())
    policy[field] = value
    fixture["policy_sha"] = put(fixture["policy_path"], policy)
    with pytest.raises(ValueError):
        transport.execute(**fixture, stage="plan")
    assert not fixture["run_dir"].exists()


@pytest.mark.parametrize("field", list(transport.BOUNDARY))
def test_authority_flags_rejected(fixture, field):
    policy = json.loads(fixture["policy_path"].read_text())
    policy["boundary"][field] = not policy["boundary"][field]
    fixture["policy_sha"] = put(fixture["policy_path"], policy)
    with pytest.raises(ValueError):
        transport.execute(**fixture, stage="plan")


def test_parent_hash_rejected(fixture):
    (fixture["root"] / "protocol.json").write_text("{}")
    with pytest.raises(ValueError):
        transport.execute(**fixture, stage="plan")


def test_source_hash_rejected(fixture):
    (fixture["root"] / "src/dante_workflow/calibration_raw_transport.py").write_text(
        "changed"
    )
    with pytest.raises(ValueError):
        transport.execute(**fixture, stage="plan")


@pytest.mark.parametrize(
    "change", ["unknown", "duplicate", "count", "sha", "profile", "seal"]
)
def test_report_inventory_rejected(fixture, change):
    report = json.loads(fixture["report_path"].read_text())
    report.pop("digest")
    audit = report["physical_input_audit"]
    if change == "unknown":
        audit["records"][0]["gps_start"] = 101
    elif change == "duplicate":
        audit["records"].append(audit["records"][0])
    elif change == "count":
        audit["missing_logical_span_count"] = 2
    elif change == "sha":
        audit["records"][0]["sha256"] = "a" * 64
    elif change == "profile":
        report["profile_sha256"] = "b" * 64
    value = sealed(report)
    if change == "seal":
        value["digest"] = "c" * 64
    policy = json.loads(fixture["policy_path"].read_text())
    policy["blocked_preflight_sha256"] = put(fixture["report_path"], value)
    fixture["policy_sha"] = put(fixture["policy_path"], policy)
    with pytest.raises(ValueError):
        transport.execute(**fixture, stage="plan")


def test_backup_exact_and_flat_but_no_recursive_hunt(tmp_path):
    raw = row()
    put(tmp_path / "nested/ignored.json", {})
    path = tmp_path / raw["physical_copies"][0]["relative_path"]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"historical")
    assert transport.backup_audit([raw], [tmp_path])[0]["matching_files"] == [str(path)]
    flat = tmp_path / path.name
    flat.write_bytes(b"historical")
    assert len(transport.backup_audit([raw], [tmp_path])[0]["matching_files"]) == 2
    flat.write_bytes(b"corruption")
    with pytest.raises(ValueError, match="hash/size"):
        transport.backup_audit([raw], [tmp_path])


def test_backup_traversal_rejected(tmp_path):
    value = row()
    value["physical_copies"][0]["relative_path"] = "../outside.hdf5"
    with pytest.raises(ValueError):
        transport.backup_audit([value], [tmp_path])


def test_queries_do_not_drop_cross_bucket_span():
    records = [row(99, 101), row(105, 110), {**row(105, 110), "detector": "L1"}]
    assert transport.queries(records, 100) == [
        ("H1", 99, 101),
        ("H1", 105, 110),
        ("L1", 105, 110),
    ]


@pytest.mark.parametrize(
    "change",
    [
        "dataset",
        "detector",
        "rate",
        "origin",
        "query",
        "url_query",
        "duplicate",
        "duration",
    ],
)
def test_bad_public_metadata(change):
    value = response()
    item = value["strain"][0]
    if change == "dataset":
        value["dataset"] = "OTHER"
    elif change == "detector":
        item["detector"] = "L1"
    elif change == "rate":
        item["sampling_rate"] = 16
    elif change == "origin":
        item["url"] = item["url"].replace("gwosc.org", "example.org")
    elif change == "query":
        value["GPSend"] = 201
    elif change == "url_query":
        item["url"] += "?test=1"
    elif change == "duplicate":
        value["strain"].append(item)
    else:
        item["duration"] = 0
    with pytest.raises(ValueError):
        transport.parse_metadata(encoded(value), "TEST", "H1", 100, 200, 4)


@pytest.mark.parametrize("change", ["hole", "checksum", "inconsistency"])
def test_coverage_and_checksum_fail_closed(change):
    value = response()
    md5 = {"frame.hdf5": "0" * 32}
    responses = [("H1", 100, 200, encoded(value))]
    if change == "hole":
        value["strain"][0]["duration"] = 99
        responses = [("H1", 100, 200, encoded(value))]
    elif change == "checksum":
        md5 = {}
    else:
        changed = response()
        changed["strain"][0]["duration"] = 101
        responses.append(("H1", 100, 200, encoded(changed)))
    with pytest.raises(ValueError):
        transport.assemble([row()], responses, "TEST", 4, md5)


@pytest.mark.parametrize(
    "change",
    [
        "snapshot",
        "authority",
        "claim",
        "inventory",
        "extra",
        "failure",
        "request",
        "policy",
        "pin",
    ],
)
def test_verifier_tamper_rejection(fixture, change):
    transport.execute(**fixture, stage="plan")
    directory = fixture["run_dir"]
    fixture["expected_plan_sha"] = hashlib.sha256(
        (directory / "metadata_plan.json").read_bytes()
    ).hexdigest()
    if change == "snapshot":
        (directory / "metadata_0000.json").write_text("changed")
    elif change in ("authority", "claim", "inventory"):
        plan = json.loads((directory / "metadata_plan.json").read_text())
        plan.pop("digest")
        if change == "authority":
            plan["boundary"]["raw_download_allowed"] = True
        elif change == "claim":
            plan["raw_samples_checked"] = True
        else:
            plan["inventory"]["counts"]["H1"] = True
        put(directory / "metadata_plan.json", sealed(plan))
        fixture["expected_plan_sha"] = hashlib.sha256(
            (directory / "metadata_plan.json").read_bytes()
        ).hexdigest()
    elif change == "pin":
        with (directory / "metadata_plan.json").open("a") as stream:
            stream.write("\n")
    else:
        put(
            directory
            / {
                "extra": "extra.json",
                "failure": "failure.json",
                "request": "request.json",
                "policy": "policy.json",
            }[change],
            {},
        )
    with pytest.raises(ValueError):
        transport.execute(**fixture, stage="verify")


def test_failure_preserved_no_auto_retry(fixture, monkeypatch):
    monkeypatch.setattr(
        transport,
        "fetch_metadata",
        lambda _: (_ for _ in ()).throw(ConnectionError("offline")),
    )
    with pytest.raises(ConnectionError):
        transport.execute(**fixture, stage="plan")
    assert (
        json.loads((fixture["run_dir"] / "failure.json").read_text())["message"]
        == "offline"
    )
    with pytest.raises(ValueError, match="failure"):
        transport.execute(**fixture, stage="verify")
    with pytest.raises(FileExistsError):
        transport.execute(**fixture, stage="plan")

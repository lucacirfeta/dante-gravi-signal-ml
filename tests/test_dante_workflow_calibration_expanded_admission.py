"""Native-only input admission: synthetic bytes, independent readers, fail closed."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from src.dante_workflow import calibration_expanded_admission as admission


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return admission._hash(path)


def reseal(value, field="digest"):
    body = deepcopy(value)
    body.pop(field, None)
    return {**body, field: admission.canonical_json_sha256(body)}


def frame(path, start, values, detector="H1", rate=4):
    with h5py.File(path, "w") as h:
        ds = h.create_dataset("strain/Strain", data=values)
        ds.attrs.update(Xstart=start, Xspacing=1 / rate, Xunits="s", Yunits="strain")
        for name, value in {
            "Detector": detector,
            "GPSstart": start,
            "Duration": len(values) / rate,
        }.items():
            h.create_dataset("meta/" + name, data=value)


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    module = "src/dante_workflow/calibration_expanded_admission.py"
    source = root / module
    source.parent.mkdir(parents=True)
    source.write_bytes(Path(admission.__file__).read_bytes())
    values = np.arange(32, dtype=np.float64)
    originals, files = {}, []
    for start, piece in ((100, values[:16]), (104, values[16:])):
        path = tmp_path / f"frame_{start}.hdf5"
        frame(path, start, piece)
        url = f"https://gwosc.org/archive/data/TEST/1/{path.name}"
        originals[url] = path
        files.append(
            {
                "url": url,
                "detector": "H1",
                "gps_start": start,
                "gps_end": start + 4,
                "sample_rate_hz": 4,
                "official_md5": admission.file_hashes(path)[1],
            }
        )
    prior_values = np.arange(50, 66, dtype=np.float64)
    rows = []
    for catalog, start, sample in (
        (101, 100.25, values[1:17]),
        (102, 100.25, values[1:17]),
        (111, 110, prior_values),
    ):
        rows.append(
            {
                "session_id": "session",
                "detector": "H1",
                "catalog_gps_start": catalog,
                "analysis_gps_start": start + 1,
                "required_padded_interval": [start, start + 4],
                "historical_context_disposition": "NORMAL",
                "raw_strain_sha256": hashlib.sha256(sample.tobytes()).hexdigest(),
            }
        )
    metadata = [
        {k: v for k, v in row.items() if k != "raw_strain_sha256"} for row in rows
    ]
    protocol = {
        "protocol_digest": "a" * 64,
        "representation": {
            "sample_rate_hz": 4,
            "analysis_duration_s": 2,
            "whitening_pad_s": 1,
        },
        "calibration_population": {
            "identity_count": 3,
            "session_detector_counts": {"H1": 1},
        },
    }
    protocol_ref = {
        "path": "protocol.json",
        "sha256": put(root / "protocol.json", protocol),
    }
    prior_path = tmp_path / "old_admission" / "receipt.json"
    prior_sha = put(prior_path, {"immutable": "old receipt"})
    profile = {"protocol_parent": protocol_ref, "admission_sha256": prior_sha}
    profile_ref = {
        "path": "profile.json",
        "sha256": put(root / "profile.json", profile),
    }
    meta_ref = {
        "path": "meta_policy.json",
        "sha256": put(root / "meta_policy.json", {"test": True}),
    }
    historical = tmp_path / "historical_run"
    shard = reseal(
        {
            "run_key": "original",
            "session_id": "session",
            "detector": "H1",
            "row_count": 3,
            "rows": rows,
            "empirical_p99": 0.9,
        },
        "shard_digest",
    )
    put(historical / "sessions/one.json", shard)
    compact = reseal(
        {
            "status": "PASS_COMPLETE_PRIMARY_CALIBRATION",
            "run_key": "original",
            "protocol_digest": protocol["protocol_digest"],
            "external_run_directory": historical.name,
            "row_count": 3,
            "session_detector_count": 1,
            "thresholds": [
                {
                    "session_id": "session",
                    "detector": "H1",
                    "n": 3,
                    "shard": "sessions/one.json",
                    "shard_digest": shard["shard_digest"],
                }
            ],
        },
        "artifact_digest",
    )
    compact_ref = {
        "path": "compact.json",
        "sha256": put(root / "compact.json", compact),
    }
    (historical / "primary_calibration_summary.json").write_bytes(
        (root / "compact.json").read_bytes()
    )
    public = admission.sealed(
        {
            "candidate_dataset": "TEST",
            "backup_audit": [],
            "inventory": {"records": [{"public_files": files}]},
        }
    )
    metadata_dir = tmp_path / "metadata"
    public_sha = put(metadata_dir / "metadata_plan.json", public)
    policy = {
        "schema_version": 1,
        "status": "AUTHOR_APPROVED_CALIBRATION_EXACT_NUMERIC_ADMISSION_V1",
        "identity_rule": "EXACT_NATIVE_NUMERICAL_SHA_NEW_CONTAINER_RECEIPT_CALIBRATION_ONLY",
        "production_profile": profile_ref,
        "metadata_policy": meta_ref,
        "historical_calibration": compact_ref,
        "metadata_plan_sha256": public_sha,
        "boundary": deepcopy(admission.BOUNDARY),
        "container_format": "gwpy_hdf5",
        "series_name_template": "{detector}:GWOSC-16KHZ_R1_STRAIN",
        "transport": {
            "automatic_retry_or_resume": False,
            "maximum_frame_bytes": 536870912,
            "context_container_reserve_bytes": 0,
        },
        "source_paths": [module],
    }
    policy_path = root / "policy.json"
    policy_sha = put(policy_path, policy)
    report = tmp_path / "report.json"
    put(report, {"metadata_only": True})

    def prior_read(**kwargs):
        assert kwargs == {"detector": "H1", "start": 110, "end": 114}
        return SimpleNamespace(series=SimpleNamespace(value=prior_values.copy()))

    prior = SimpleNamespace(
        rows={("H1", 110, 114): {"file_sha256": "b" * 64}}, read=prior_read
    )
    # Synthetic metadata gate/old provider, independently tested in their own suites.
    # The admission functions, SHA pins, native HDF5 and both GWPy readers are real.
    monkeypatch.setattr(
        admission,
        "verify_transport",
        lambda **kw: admission._pinned(
            kw["run_dir"] / "metadata_plan.json", kw["expected_plan_sha"]
        ),
    )
    original_builder = admission.build_plan
    monkeypatch.setattr(
        admission,
        "build_plan",
        lambda **kw: original_builder(
            **kw, population_loader=lambda *a: (metadata, prior)
        ),
    )
    args = dict(
        root=root,
        policy_path=policy_path,
        policy_sha=policy_sha,
        metadata_dir=metadata_dir,
        report_path=report,
        historical_dir=historical,
        prior_receipt=prior_path,
    )

    def download(url, path):
        shutil.copyfile(originals[url], path)

    return SimpleNamespace(
        root=root,
        args=args,
        policy=policy,
        protocol=protocol,
        metadata=metadata,
        prior=prior,
        files=files,
        originals=originals,
        download=download,
        run_dir=tmp_path / "external" / "run",
    )


def recover(case):
    plan = admission.build_plan(**case.args)
    summary = admission.run(
        plan, case.run_dir, root=case.root, downloader=case.download
    )
    return plan, summary


def replay(case):
    return admission.verify(
        case.run_dir,
        root=case.root,
        plan_sha=admission._hash(case.run_dir / "plan.json"),
        summary_sha=admission._hash(case.run_dir / "summary.json"),
    )


def test_shared_population_prior_preserved_and_offline_independent_replay(
    case, monkeypatch
):
    before = Path(case.args["prior_receipt"]).read_bytes()
    plan, summary = recover(case)
    assert plan["identity_count"] == 3
    assert plan["unique_context_count"] == 2
    assert len(plan["new_contexts"]) == len(plan["prior_contexts"]) == 1
    assert len(summary["frames"]) == 2
    assert summary["records"][0]["sample_count"] == 16
    assert plan["new_context_payload_bytes"] == 128
    monkeypatch.setattr(admission, "download", lambda *a: pytest.fail("offline replay"))
    result = replay(case)
    assert result["status"] == "PASS_VERIFIED_CALIBRATION_NATIVE_RAW_ONLY"
    assert result["verification_was_second_fetch"] is False
    put(case.run_dir / "verification.json", result)
    receipt = admission.admit(
        case.run_dir,
        root=case.root,
        plan_sha=admission._hash(case.run_dir / "plan.json"),
        summary_sha=admission._hash(case.run_dir / "summary.json"),
        verification_sha=admission._hash(case.run_dir / "verification.json"),
    )
    assert receipt["status"] == "PASS_ADMITTED_CALIBRATION_EXACT_NATIVE_INPUTS_ONLY"
    assert receipt["boundary"] == admission.BOUNDARY
    assert receipt["boundary"]["scientific_execution_ready"] is False
    assert Path(case.args["prior_receipt"]).read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("status", "PASS"),
        ("identity_rule", "CONTAINER_SHA"),
        ("container_format", "resampled"),
        ("series_name_template", "{detector}:STRAIN"),
    ],
)
def test_policy_rejects_scientific_or_typed_drift(case, field, value):
    policy = deepcopy(case.policy)
    policy[field] = value
    case.args["policy_sha"] = put(case.args["policy_path"], policy)
    with pytest.raises(ValueError, match="policy"):
        admission.build_plan(**case.args)


@pytest.mark.parametrize(
    "field,value",
    [
        ("automatic_retry_or_resume", True),
        ("maximum_frame_bytes", 536870912.0),
        ("context_container_reserve_bytes", True),
        ("context_container_reserve_bytes", -1),
    ],
)
def test_transport_bounds_are_typed_and_no_automatic_resume(case, field, value):
    policy = deepcopy(case.policy)
    policy["transport"][field] = value
    case.args["policy_sha"] = put(case.args["policy_path"], policy)
    with pytest.raises(ValueError):
        admission.build_plan(**case.args)


@pytest.mark.parametrize("field", list(admission.BOUNDARY))
def test_boundary_cannot_be_promoted_or_numeric_boolean(case, field):
    policy = deepcopy(case.policy)
    policy["boundary"][field] = int(policy["boundary"][field])
    case.args["policy_sha"] = put(case.args["policy_path"], policy)
    with pytest.raises(ValueError):
        admission.build_plan(**case.args)


@pytest.mark.parametrize("target", ["source", "protocol", "compact", "prior", "public"])
def test_parent_and_source_drift_rejected_before_network(case, target):
    paths = {
        "source": case.root / case.policy["source_paths"][0],
        "protocol": case.root / "protocol.json",
        "compact": case.root / "compact.json",
        "prior": case.args["prior_receipt"],
        "public": case.args["metadata_dir"] / "metadata_plan.json",
    }
    paths[target].write_bytes(b"changed")
    with pytest.raises(ValueError):
        admission.build_plan(**case.args)
    assert not case.run_dir.exists()


@pytest.mark.parametrize("change", ["duplicate", "geometry", "off_grid", "missing"])
def test_frozen_identity_and_native_grid_rejected(case, change):
    if change == "duplicate":
        case.metadata.append(deepcopy(case.metadata[0]))
    elif change == "geometry":
        case.metadata[0]["analysis_gps_start"] += 1
    elif change == "off_grid":
        case.metadata[0]["analysis_gps_start"] += 0.1
        case.metadata[0]["required_padded_interval"] = [100.35, 104.35]
    else:
        case.metadata.pop()
    with pytest.raises(ValueError):
        admission.build_plan(**case.args)


def test_historical_shard_tamper_not_accepted(case):
    path = case.args["historical_dir"] / "sessions/one.json"
    value = json.loads(path.read_text())
    value["rows"][0]["raw_strain_sha256"] = "0" * 64
    put(path, value)
    with pytest.raises(ValueError, match="shard seal"):
        admission.build_plan(**case.args)


def test_shared_context_hash_disagreement_rejected(case):
    path = case.args["historical_dir"] / "sessions/one.json"
    value = json.loads(path.read_text())
    value["rows"][1]["raw_strain_sha256"] = "0" * 64
    value = reseal(value, "shard_digest")
    put(path, value)
    compact = json.loads((case.root / "compact.json").read_text())
    compact["thresholds"][0]["shard_digest"] = value["shard_digest"]
    compact = reseal(compact, "artifact_digest")
    case.policy["historical_calibration"]["sha256"] = put(
        case.root / "compact.json", compact
    )
    (case.args["historical_dir"] / "primary_calibration_summary.json").write_bytes(
        (case.root / "compact.json").read_bytes()
    )
    case.args["policy_sha"] = put(case.args["policy_path"], case.policy)
    with pytest.raises(ValueError, match="shared context"):
        admission.build_plan(**case.args)


def test_prior_numeric_hash_disagreement_rejected(case):
    case.prior.read = lambda **kw: SimpleNamespace(
        series=SimpleNamespace(value=np.zeros(16))
    )
    with pytest.raises(ValueError, match="prior admitted context"):
        admission.build_plan(**case.args)


@pytest.mark.parametrize("change", ["gap", "detector", "metadata", "collision"])
def test_frame_mapping_is_complete_local_and_unambiguous(case, change):
    plan = admission.build_plan(**case.args)
    contexts = {("H1", 100.25, 104.25): plan["new_contexts"][0]}
    files = deepcopy(case.files)
    if change == "gap":
        files.pop()
    elif change == "detector":
        files[1]["detector"] = "L1"
    elif change == "metadata":
        bad = deepcopy(files[0])
        bad["gps_end"] += 1
        files.append(bad)
    else:
        files[1]["url"] = files[0]["url"].replace("/1/", "/2/")
    with pytest.raises(ValueError):
        admission.map_frames(
            contexts, {"inventory": {"records": [{"public_files": files}]}}
        )


@pytest.mark.parametrize("change", ["detector", "grid", "dtype", "nonfinite", "sha"])
def test_raw_native_mismatch_stops_and_preserves_evidence(case, change):
    plan = admission.build_plan(**case.args)
    first = case.originals[case.files[0]["url"]]
    if change == "sha":
        plan["new_contexts"][0]["historical_strain_values_sha256"] = "0" * 64
    else:
        with h5py.File(first, "a") as h:
            if change == "detector":
                del h["meta/Detector"]
                h.create_dataset("meta/Detector", data="L1")
            elif change == "grid":
                h["strain/Strain"].attrs["Xspacing"] = 0.5
            elif change == "nonfinite":
                h["strain/Strain"][2] = np.nan
            else:
                attrs = dict(h["strain/Strain"].attrs)
                values = h["strain/Strain"][()].astype(np.float32)
                del h["strain/Strain"]
                h.create_dataset("strain/Strain", data=values).attrs.update(attrs)
        plan["frames"][0]["official_md5"] = admission.file_hashes(first)[1]
    row = plan["new_contexts"][0]
    with pytest.raises(ValueError):
        admission.native_slice(row, case.originals)


def test_half_open_fractional_grid_and_cross_frame_exact(case):
    plan = admission.build_plan(**case.args)
    values = admission.native_slice(plan["new_contexts"][0], case.originals)
    np.testing.assert_array_equal(values, np.arange(1, 17, dtype=np.float64))


def test_existing_run_never_resumed(case):
    plan, _ = recover(case)
    with pytest.raises(FileExistsError):
        admission.run(plan, case.run_dir, root=case.root, downloader=case.download)


def test_run_rejects_resealed_plan_before_any_download(case):
    plan = admission.build_plan(**case.args)
    plan["new_contexts"][0]["historical_strain_values_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="independent recovery plan"):
        admission.run(
            reseal(plan),
            case.run_dir,
            root=case.root,
            downloader=lambda *a: pytest.fail("network forbidden"),
        )
    assert not case.run_dir.exists()


@pytest.mark.parametrize("bad", ["md5", "network", "disk", "native"])
def test_run_failure_is_preserved_without_retry_or_success(case, monkeypatch, bad):
    plan = admission.build_plan(**case.args)
    downloader = case.download
    if bad == "md5":

        def downloader(url, path):
            path.write_bytes(b"bad download")
    elif bad == "network":

        def downloader(url, path):
            path.write_bytes(b"partial")
            raise OSError("transport down")
    elif bad == "disk":
        monkeypatch.setattr(
            admission.shutil, "disk_usage", lambda p: SimpleNamespace(free=0)
        )
    else:
        monkeypatch.setattr(
            admission,
            "native_slice",
            lambda *a: (_ for _ in ()).throw(ValueError("native SHA")),
        )
    with pytest.raises((OSError, ValueError)):
        admission.run(plan, case.run_dir, root=case.root, downloader=downloader)
    failure = admission.read_sealed(case.run_dir / "failure.json")
    assert failure["status"] == (
        "FAILED_INFRASTRUCTURE"
        if bad in ("network", "disk")
        else "FAILED_RAW_PROVENANCE_OR_STRUCTURE"
    )
    assert not (case.run_dir / "summary.json").exists()
    assert not (case.run_dir / "controller.lock").exists()
    if bad in ("md5", "network"):
        assert list((case.run_dir / "frames").glob("*.partial"))
    if bad == "native":
        assert len(list((case.run_dir / "frames").glob("*.hdf5"))) == 2


@pytest.mark.parametrize(
    "name", ["controller.lock", "failure.json", "bad.partial", "bad.tmp"]
)
def test_verifier_refuses_unfinished_or_failed_run(case, name):
    recover(case)
    (case.run_dir / name).write_text("preserved evidence")
    with pytest.raises(ValueError, match="lock/failure/partial"):
        replay(case)


@pytest.mark.parametrize("target", ["frame", "context", "receipt", "extra"])
def test_verifier_bytes_receipts_and_inventory(case, target):
    _, summary = recover(case)
    if target == "frame":
        path = case.run_dir / next(iter(summary["frames"].values()))["relative_path"]
    elif target == "context":
        path = case.run_dir / summary["records"][0]["relative_path"]
    elif target == "receipt":
        path = (case.run_dir / summary["records"][0]["relative_path"]).with_suffix(
            ".json"
        )
    else:
        path = case.run_dir / "contexts/extra.json"
    path.write_bytes(b"altered")
    with pytest.raises(ValueError):
        replay(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sample_count", 17),
        ("sample_rate_hz", 4.0),
        ("dtype", "<f4"),
        ("gps_start", 100.5),
    ],
)
def test_resealed_receipt_cannot_reinterpret_samples(case, field, value):
    _, summary = recover(case)
    item = summary["records"][0]
    item[field] = value
    put(
        (case.run_dir / item["relative_path"]).with_suffix(".json"),
        admission.sealed(item),
    )
    put(case.run_dir / "summary.json", reseal(summary))
    with pytest.raises(ValueError):
        replay(case)


@pytest.mark.parametrize("role", ["checkout", "metadata", "history", "prior"])
def test_protected_outputs_never_created(case, role):
    paths = {
        "checkout": case.root,
        "metadata": case.args["metadata_dir"],
        "history": case.args["historical_dir"],
        "prior": case.args["prior_receipt"].parent,
    }
    with pytest.raises(ValueError, match="isolated external"):
        admission.isolated_directory(
            paths[role] / "new",
            case.root,
            case.args["metadata_dir"],
            case.args["historical_dir"],
            case.args["prior_receipt"],
        )


def test_forged_verification_status_never_admitted(case):
    recover(case)
    put(
        case.run_dir / "verification.json",
        admission.sealed({"status": "PASS_VERIFIED_CALIBRATION_NATIVE_RAW_ONLY"}),
    )
    with pytest.raises(ValueError, match="verified evidence differs"):
        admission.admit(
            case.run_dir,
            root=case.root,
            plan_sha=admission._hash(case.run_dir / "plan.json"),
            summary_sha=admission._hash(case.run_dir / "summary.json"),
            verification_sha=admission._hash(case.run_dir / "verification.json"),
        )


def test_source_change_during_plan_detected(case):
    original = case.prior.read

    def changing_reader(**kwargs):
        result = original(**kwargs)
        (case.root / case.policy["source_paths"][0]).write_text("drift during planning")
        return result

    case.prior.read = changing_reader
    with pytest.raises(ValueError):
        admission.build_plan(**case.args)


def test_verifier_uses_independent_reader_not_native_writer(case, monkeypatch):
    recover(case)
    monkeypatch.setattr(
        admission,
        "native_slice",
        lambda *a: pytest.fail("writer must not be verifier oracle"),
    )
    assert replay(case)["status"] == "PASS_VERIFIED_CALIBRATION_NATIVE_RAW_ONLY"


def test_official_frame_drift_during_independent_read_rejected(case, monkeypatch):
    from gwpy.timeseries import TimeSeries

    _, summary = recover(case)
    read = TimeSeries.read
    changed = False

    def drifting_read(path, *args, **kwargs):
        nonlocal changed
        result = read(path, *args, **kwargs)
        if kwargs.get("format") == "hdf5.gwosc" and not changed:
            # Change a sample OUTSIDE the context after the frame was hashed.
            with h5py.File(path, "a") as handle:
                handle["strain/Strain"][0] = -999
            changed = True
        return result

    monkeypatch.setattr(TimeSeries, "read", drifting_read)
    with pytest.raises(ValueError, match="frame changed during replay"):
        replay(case)
    assert len(summary["frames"]) == 2


def test_cli_missing_stage_pins_fail_before_work(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        [
            "recover",
            "--stage",
            "run",
            "--repository-root",
            str(tmp_path),
            "--run-dir",
            str(tmp_path / "missing"),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        admission.main()
    assert exc.value.code == 2
    assert not (tmp_path / "missing").exists()


def test_numerical_mismatch_stops_before_later_frame_download(case, monkeypatch):
    plan = admission.build_plan(**case.args)
    # Unit fixture for scheduling only; full plan integrity is tested above.
    plan["new_contexts"][0].update(
        gps_start=100,
        gps_end=104,
        historical_strain_values_sha256="0" * 64,
        files=[case.files[0]],
    )
    plan = reseal(plan)
    monkeypatch.setattr(admission, "regenerate", lambda *a: plan)
    calls = []

    def downloader(url, path):
        calls.append(url)
        case.download(url, path)

    with pytest.raises(ValueError, match="native numerical SHA"):
        admission.run(plan, case.run_dir, root=case.root, downloader=downloader)
    assert calls == [case.files[0]["url"]]
    assert (
        admission.read_sealed(case.run_dir / "failure.json")["status"]
        == "FAILED_RAW_PROVENANCE_OR_STRUCTURE"
    )

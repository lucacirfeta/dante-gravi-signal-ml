"""Synthetic retained PEM; frozen repository metadata, never historical outcomes.

Main fixture isolates coincidence ancestry. Linked tests run actual 08.12, then
stop at the PEM contract handoff (taxonomy ancestry remains isolated there).
No test claims a whole physical acquisition or a full scientific workflow.
"""

from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.dante_light import o3a_native_pem as pem
from src.dante_light import o3a_raw_acquisition as raw
from src.dante_light.contracts import canonical_json_sha256
from src.dante_light.o3a_native_contract import DQ_SNAPSHOT_REL
from src.dante_workflow import evidence_snapshot as snap
from src.dante_workflow import o3a_pem_verification as verify
from tests import test_dante_workflow_o3a_coincidence_verification as coin_tests

ROOT = Path(__file__).resolve().parents[1]
POLICY = (ROOT / snap.POLICY_REL).read_bytes()
POSIX = pytest.mark.skipif(os.name != "posix", reason="existing POSIX parent locks")
coincidence_evidence = coin_tests.evidence


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def encoded(value):
    return snap._encoded(value)


def seal(value, key="artifact_digest"):
    body = {k: v for k, v in value.items() if k != key}
    return {**body, key: canonical_json_sha256(body)}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value if isinstance(value, bytes) else encoded(value)
    path.write_bytes(payload)
    return payload


def jsonl(rows):
    return b"".join(encoded(row) + b"\n" for row in rows)


def package(members):
    body = {
        "schema_version": 1,
        "status": "FROZEN_RETAINED_EVIDENCE_CAPTURE_PLAN_V1",
        "entries": [
            {
                "name": name,
                "root": name.split("/", 1)[0],
                "relative_path": name.split("/", 1)[1],
                "sha256": sha(payload),
                "size_bytes": len(payload),
            }
            for name, payload in sorted(members.items())
        ],
    }
    plan = encoded(seal(body, "plan_digest"))
    blob = snap.package_snapshot(
        plan_bytes=plan,
        expected_plan_sha256=sha(plan),
        policy_bytes=POLICY,
        members=members,
    )
    return dict(
        snapshot_bytes=blob,
        expected_snapshot_sha256=sha(blob),
        expected_plan_sha256=sha(plan),
    )


def files_for(members):
    pins = package(members)
    view = snap.admit_snapshot(
        pins["snapshot_bytes"],
        expected_sha256=pins["expected_snapshot_sha256"],
        expected_plan_sha256=pins["expected_plan_sha256"],
        policy_bytes=POLICY,
    )
    return verify._SnapshotFiles(view)


def forbidden(*args, **kwargs):
    raise AssertionError("productive/fetch/writer entry point reached")


def block_productive(monkeypatch):
    from src.pipeline_v2_production import pem_coherence_analysis, pem_null_calibration

    for name in (
        "run_native_pem",
        "verify_native_pem",
        "_measure_event",
        "_event_strain",
        "_download_frame",
        "_atomic_json",
        "_atomic_jsonl",
    ):
        monkeypatch.setattr(pem, name, forbidden)
    for module, names in (
        (
            pem_coherence_analysis,
            ("fetch_auxiliary_data", "calculate_coherence_and_plot"),
        ),
        (pem_null_calibration, ("calibrate_event",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)


def copy_sources(root):
    for relative in verify._sources(ROOT):
        write(root / relative, (ROOT / relative).read_bytes())
    write(root / snap.POLICY_REL, POLICY)


def event_for(target, contract, exclusion_digest, directory, *, maximum=0.9):
    """Explicit disposable measurements, not estimated thresholds or real scores."""
    from src.pipeline_v2_production.pem_null_calibration import tier_verdict

    detector, gps = target["detector"], target["gps_start"]
    active = contract["channels"][detector]
    calibrated = target["population"] == "primary"
    shift, zero = (0.7, 0.8) if calibrated else (None, None)
    calibration_spec = None
    if calibrated:
        calibration = {
            "detector": detector,
            "run": "O3a",
            "event_gps": gps,
            "candidate_exclusion_digest": exclusion_digest,
            "candidate_exclusion_population": contract["population"][
                "candidate_exclusion_total"
            ],
            "channels": active,
            "alpha_family_wise": contract["measurement"]["alpha_family_wise"],
            "n_windows": contract["measurement"]["minimum_clean_windows"],
            "threshold_fw": shift,
            "zero_lag_control": {"q99": zero},
        }
        filename = f"null_calibration_{detector}_{gps}.json"
        payload = write(directory / filename, calibration)
        calibration_spec = {
            "filename": filename,
            "sha256": sha(payload),
            "channels": active,
        }
    body = {
        "schema_version": 1,
        "target": target,
        "candidate_exclusion_digest": exclusion_digest,
        "strain_window_sha256": "c" * 64,
        "channels": [
            {
                "aux_channel": channel,
                "data_available": calibrated,
                "max_coherence": maximum if calibrated else None,
                "peak_freq": 50.0 if calibrated else None,
            }
            for channel in active
        ],
        "calibration": calibration_spec,
        "cmax_observed": maximum if calibrated else None,
        "top_channel": active[0] if calibrated else None,
        "threshold_time_shift_q99": shift,
        "threshold_zero_lag_q99": zero,
        "verdict_time_shift": ("COUPLED" if maximum > shift else "NO_CORRELATION")
        if calibrated
        else "UNCALIBRATED",
        "verdict_tier": tier_verdict(maximum, shift, zero)
        if calibrated
        else "UNCALIBRATED",
        "scientific_interpretation": "PEM_DIAGNOSTIC_ONLY_NOT_ASTROPHYSICAL_CONFIRMATION",
    }
    event = seal(body, "event_digest")
    pem._verify_event(
        event,
        target=target,
        run_dir=directory,
        contract=contract,
        exclusion_digest=exclusion_digest,
    )
    write(directory / "events" / f"{target['population']}_{detector}_{gps}.json", event)
    return event


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    root, external = tmp_path / "repo", tmp_path / "parents"
    copy_sources(root)
    contract = json.loads((ROOT / pem.CONTRACT_REL).read_bytes())
    metadata = {
        DQ_SNAPSHOT_REL,
        raw.INVENTORY_REL,
        raw.IMPLEMENTATION_REL,
        raw.ENTRYPOINT_REL,
        *pem.SOURCE_PATHS,
        contract["method_reference"]["path"],
        *(r["path"] for r in contract["parents"].values()),
    }
    for relative in metadata:
        write(root / relative, (ROOT / relative).read_bytes())
    # Source/DQ inventory metadata is real and frozen; target outcomes are not.
    inventory = raw.load_source_inventory(
        root=verify._SnapshotPath(
            files_for({"repository/" + r: (root / r).read_bytes() for r in metadata}),
            "repository",
        )
    )
    coin_contract = json.loads(
        (root / contract["parents"]["coincidence_contract"]["path"]).read_bytes()
    )
    pad = int(coin_contract["measurement"]["whitening_pad_s"])
    duration = int(coin_contract["measurement"]["segment_duration_s"])
    rows, ledgers = [], {"primary": [], "diagnostic": []}
    for detector, offset, label in (
        ("H1", 100, "ROBUST"),
        ("L1", 100, "ROBUST"),
        ("H1", 200, "AMBIGUOUS"),
        ("L1", 200, "BACKGROUND"),
    ):
        frame = raw._inventory_frames(inventory, detector)[0]
        gps = frame["gps_start"] + pad + offset
        row = {
            "detector": detector,
            "gps_start": gps,
            "native_class": label,
            "native_score": 0.5,
            "identity_digest": sha(f"{detector}{gps}".encode()),
            "image_sha256": "b" * 64,
            "raw_context_sha256": "a" * 64,
            "context_sources": [
                {
                    **frame,
                    "detector": detector,
                    "sha256": "a" * 64,
                    "size_bytes": 1234,
                    "used_interval_gps": [gps - pad, gps + duration + pad],
                }
            ],
        }
        rows.append(row)
        if label == "BACKGROUND":
            continue
        bucket = "primary" if label == "ROBUST" else "diagnostic"
        ledgers[bucket].append(
            {
                "detector": detector,
                "gps_start": gps,
                "population": bucket,
                "exceeds_primary_threshold": True,
                "measurement_status": "MEASURED",
                "seed_native_class": label,
                "seed_native_score": row["native_score"],
                "seed_identity_digest": row["identity_digest"],
                "seed_image_sha256": row["image_sha256"],
                "seed_raw_context_sha256": row["raw_context_sha256"],
                "cc_onsource": 0.9,
            }
        )
    class_dir = external / "native_classification_fixture"
    coin_dir = external / "native_coincidence_fixture"
    for directory in (class_dir, coin_dir):
        write(directory / "run.lock", b"")
    class_path = class_dir / "native_classified_candidates.jsonl"
    write(class_path, jsonl(rows))
    classified = seal(
        {
            "status": "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION",
            "run_key": "fixture",
            "row_total": len(rows),
            "output_sha256": sha(class_path.read_bytes()),
            "output_row_digest": canonical_json_sha256(rows),
        }
    )
    write(root / contract["parents"]["classification"]["path"], classified)
    specs = {}
    for bucket, values in ledgers.items():
        path = coin_dir / ("native_coincidence_" + bucket + ".jsonl")
        write(path, jsonl(values))
        specs[bucket] = pem._outputs_spec(path, values)
    coincidence = seal(
        {
            "status": "PASS_VERIFIED_O3A_NATIVE_COINCIDENCE",
            "run_key": "fixture",
            "contract_digest": coin_contract["contract_digest"],
            "outputs": specs,
        }
    )
    write(root / contract["parents"]["coincidence"]["path"], coincidence)
    contract["population"].update(
        primary={"class": "ROBUST", "H1": 1, "L1": 1, "total": 2},
        diagnostic={"class": "AMBIGUOUS", "H1": 1, "L1": 0, "total": 1},
        exact_total=3,
        candidate_exclusion_total=len(rows),
        candidate_exclusion_population="disposable_all_classified_rows",
    )
    for name, reference in contract["parents"].items():
        reference["sha256"] = sha((root / reference["path"]).read_bytes())
        if name in {"classification", "coincidence"}:
            reference["artifact_digest"] = (
                classified if name == "classification" else coincidence
            )["artifact_digest"]
    contract = seal(contract, "contract_digest")
    write(root / pem.CONTRACT_REL, contract)
    members = {
        "repository/" + r: (root / r).read_bytes()
        for r in metadata | {pem.CONTRACT_REL.as_posix()} | set(verify._sources(root))
    }
    members.update(
        {
            "parents/" + p.relative_to(external).as_posix(): p.read_bytes()
            for p in (class_path, *(coin_dir / s["filename"] for s in specs.values()))
        }
    )
    virtual = verify._SnapshotPath(files_for(members), "repository")
    preflight, targets, exclusion = pem.preflight_inputs(
        root=virtual, external_root=verify._SnapshotPath(virtual.files, "parents")
    )
    directory = (
        tmp_path
        / "pem"
        / (contract["output"]["prefix"] + pem._run_key(contract, preflight))
    )
    events = [
        event_for(t, contract, preflight["candidate_exclusion_digest"], directory)
        for t in targets
    ]
    output_specs, counts = {}, {}
    for bucket, values in (
        ("targets", targets),
        ("primary", [e for e in events if e["target"]["population"] == "primary"]),
        (
            "diagnostic",
            [e for e in events if e["target"]["population"] == "diagnostic"],
        ),
    ):
        path = directory / ("native_pem_" + bucket + ".jsonl")
        write(path, jsonl(values))
        output_specs[bucket] = pem._outputs_spec(path, values)
        if bucket != "targets":
            tiers = Counter(e["verdict_tier"] for e in values)
            counts[bucket] = {
                "total": len(values),
                "calibrated": len(values) - tiers["UNCALIBRATED"],
                "uncalibrated": tiers["UNCALIBRATED"],
                "verdict_tier": dict(sorted(tiers.items())),
            }
    summary = seal(
        {
            "schema_version": 1,
            "status": "PASS_COMPLETE_O3A_NATIVE_PEM_V1",
            "run_key": pem._run_key(contract, preflight),
            "contract_digest": contract["contract_digest"],
            "preflight_digest": preflight["preflight_digest"],
            "target_digest": preflight["target_digest"],
            "candidate_exclusion_digest": preflight["candidate_exclusion_digest"],
            "event_summary": counts,
            "outputs": output_specs,
            "transient_raw_purged": True,
            "scientific_boundary": contract["scientific_boundary"],
        }
    )
    write(directory / "native_pem_summary.json", summary)
    compact = seal(
        {
            "status": "PASS_VERIFIED_O3A_NATIVE_PEM_V1",
            "run_key": summary["run_key"],
            "contract_digest": contract["contract_digest"],
            "run_artifact_digest": summary["artifact_digest"],
            "event_summary": counts,
            "scientific_boundary": contract["scientific_boundary"],
        }
    )
    members["repository/" + pem.COMPACT_REL.as_posix()] = write(
        root / pem.COMPACT_REL, compact
    )
    members.update(
        {
            "pem/"
            + directory.name
            + "/"
            + p.relative_to(directory).as_posix(): p.read_bytes()
            for p in directory.rglob("*")
            if p.is_file()
        }
    )
    calls = []

    def parent_gate(*, root, external_root, evidence, stack, **kwargs):
        assert root == virtual_root and external_root == external
        stack.enter_context(verify.parents.decisions._persistent_lock(coin_dir))
        stack.enter_context(verify.parents.decisions._persistent_lock(class_dir))
        evidence.read("fixture_coin_lock", coin_dir / "run.lock")
        evidence.read("fixture_class_lock", class_dir / "run.lock")
        calls.append(kwargs)
        return coincidence, coin_dir

    virtual_root = root
    monkeypatch.setattr(verify.parents, "_coincidence_gate", parent_gate)
    block_productive(monkeypatch)
    args = dict(
        root=root,
        pem_external_root=directory.parent,
        coincidence_external_root=external,
        classification_external_root=external,
        **{
            name + "_external_root": tmp_path / name
            for name in (
                "taxonomy",
                "threshold",
                "rescore",
                "calibration",
                "index",
                "cohort",
                "primary",
            )
        },
    )
    return SimpleNamespace(
        root=root,
        directory=directory,
        members=members,
        args=args,
        contract=contract,
        summary=summary,
        preflight=preflight,
        targets=targets,
        events=events,
        calls=calls,
        coin_dir=coin_dir,
        class_dir=class_dir,
        class_path=class_path,
        exclusion=exclusion,
    )


def run(evidence, members=None, **changes):
    args = {
        **evidence.args,
        **package(evidence.members if members is None else members),
        **changes,
    }
    return verify.verify_pem_evidence(**args)


def disk_snapshot(root):
    return {
        p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


@POSIX
def test_read_only_exact_retained_decisions_and_scoped_receipt(evidence):
    before = disk_snapshot(evidence.root.parent)
    result = run(evidence)
    assert result["legacy_artifact_digest"] == evidence.summary["artifact_digest"]
    assert result["status"] == "PASS_O3A_READ_ONLY_PEM_SNAPSHOT_RETAINED_DECISIONS_ONLY"
    assert len(result["source_bindings"]) == 47
    for name in (
        "full_workflow_verified",
        "pem_writer_exclusion_verified",
        "global_upstream_quiescence_verified",
        "atomic_historical_capture_verified",
        "fresh_sensor_coherence_replayed",
        "fresh_null_calibration_replayed",
        "historical_evidence_mutated",
        "source_fetch_executed",
        "live_pem_output_bytes_checked",
    ):
        assert result[name] is False
    assert "event_summary" not in result and "verdict_tier" not in result
    assert len(evidence.calls) == 1
    assert disk_snapshot(evidence.root.parent) == before


def test_original_contract_preflight_event_readers_use_virtual_bytes(
    evidence, monkeypatch
):
    files = files_for(evidence.members)
    original = pem._verify_event
    observed = []

    def event_check(*args, **kwargs):
        assert isinstance(kwargs["run_dir"], verify._SnapshotPath)
        observed.append(kwargs["target"]["population"])
        return original(*args, **kwargs)

    monkeypatch.setattr(pem, "_verify_event", event_check)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    contract, summary, directory = verify._retained_gate(files)
    assert contract == evidence.contract and summary == evidence.summary
    assert directory.name == evidence.directory.name
    assert sorted(observed) == ["diagnostic", "primary", "primary"]


@pytest.mark.parametrize("maximum", [0.0, 0.7, 0.700000001, 0.8, 0.800000001, 1.0])
def test_original_strict_tier_and_shift_boundaries(evidence, tmp_path, maximum):
    # Use pure construction helper; no original productive measurement invoked.
    event = event_for(
        evidence.targets[0],
        evidence.contract,
        evidence.preflight["candidate_exclusion_digest"],
        tmp_path,
        maximum=maximum,
    )
    pem._verify_event(
        event,
        target=evidence.targets[0],
        run_dir=tmp_path,
        contract=evidence.contract,
        exclusion_digest=evidence.preflight["candidate_exclusion_digest"],
    )
    assert (event["verdict_time_shift"] == "COUPLED") == (maximum > 0.7)


@pytest.mark.parametrize(
    "field,value",
    [
        ("verdict_time_shift", "NO_CORRELATION"),
        ("cmax_observed", 0.0),
        ("top_channel", "L1:missing"),
        ("threshold_time_shift_q99", 0.0),
    ],
)
def test_missing_calibration_never_negative(evidence, field, value):
    event = deepcopy(next(e for e in evidence.events if e["calibration"] is None))
    event[field] = value
    with pytest.raises(ValueError, match="negative"):
        pem._verify_event(
            seal(event, "event_digest"),
            target=event["target"],
            run_dir=verify._SnapshotPath(files_for(evidence.members), "pem")
            / evidence.directory.name,
            contract=evidence.contract,
            exclusion_digest=evidence.preflight["candidate_exclusion_digest"],
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("detector", "V1"),
        ("run", "O4a"),
        ("event_gps", -1),
        ("candidate_exclusion_digest", "0" * 64),
        ("candidate_exclusion_population", 1),
        ("channels", []),
        ("alpha_family_wise", 0.2),
        ("n_windows", 0),
    ],
)
def test_resealed_calibration_identity_drift(evidence, field, value):
    members = deepcopy(evidence.members)
    event = deepcopy(evidence.events[0])
    key = "pem/" + evidence.directory.name + "/" + event["calibration"]["filename"]
    calibration = json.loads(members[key])
    calibration[field] = value
    members[key] = encoded(calibration)
    event["calibration"]["sha256"] = sha(members[key])
    with pytest.raises(ValueError, match="calibration identity"):
        pem._verify_event(
            seal(event, "event_digest"),
            target=event["target"],
            run_dir=verify._SnapshotPath(files_for(members), "pem")
            / evidence.directory.name,
            contract=evidence.contract,
            exclusion_digest=evidence.preflight["candidate_exclusion_digest"],
        )


@pytest.mark.parametrize(
    "fragment",
    [
        "native_pem_summary.json",
        "native_pem_targets.jsonl",
        "native_pem_primary.jsonl",
        "native_pem_diagnostic.jsonl",
        "events/primary_",
        "null_calibration_",
        "repository/config/dante_o3a_native_pem_v1.json",
        "repository/artifacts/dante_light/o3a_native_v1/native_pem.json",
    ],
)
def test_missing_own_evidence_refuses(evidence, fragment):
    members = deepcopy(evidence.members)
    key = next(k for k in members if fragment in k)
    del members[key]
    with pytest.raises((ValueError, KeyError)):
        verify._retained_gate(files_for(members))


@POSIX
@pytest.mark.parametrize(
    "kind", ["extra", "parent", "source", "pin", "failure", "cache"]
)
def test_full_gate_refusals(evidence, kind):
    members = deepcopy(evidence.members)
    changes = {}
    if kind == "extra":
        members["pem/unconsumed.txt"] = b"extra"
    elif kind == "parent":
        evidence.class_path.write_bytes(b"[]\n")
    elif kind == "source":
        path = evidence.root / "src/dante_light/o3a_native_pem.py"
        path.write_bytes(path.read_bytes() + b"\n# altered\n")
    elif kind == "pin":
        changes["expected_snapshot_sha256"] = "0" * 64
    elif kind == "failure":
        write(evidence.directory / "failure.json", {})
    elif kind == "cache":
        write(evidence.directory / "transient_raw/raw.hdf5", b"raw")
    with pytest.raises((ValueError, KeyError, OSError)):
        run(evidence, members, **changes)


@POSIX
def test_owned_outcomes_ignore_live_pem_mutations(evidence, monkeypatch):
    original = verify._retained_gate

    def mutate(files):
        for path in evidence.directory.rglob("*.json"):
            path.write_bytes(b"not the archived measurement")
        return original(files)

    monkeypatch.setattr(verify, "_retained_gate", mutate)
    assert run(evidence)["retained_pem_decisions_replayed"] is True


@POSIX
@pytest.mark.parametrize("kind", ["parent", "failure", "cache"])
def test_final_rehash_and_guards_refuse_mid_replay_change(evidence, monkeypatch, kind):
    original = verify._retained_gate

    def mutate(files):
        result = original(files)
        if kind == "parent":
            evidence.class_path.write_bytes(b"[]\n")
        elif kind == "failure":
            write(evidence.directory / "failure.json", {})
        else:
            write(evidence.directory / "transient_raw/raw.hdf5", b"raw")
        return result

    monkeypatch.setattr(verify, "_retained_gate", mutate)
    with pytest.raises((ValueError, OSError)):
        run(evidence)


@POSIX
def test_parent_locks_held_through_retained_and_rehash(evidence, monkeypatch):
    original = verify._retained_gate

    def probe(files):
        for directory in (evidence.coin_dir, evidence.class_dir):
            with pytest.raises(ValueError, match="busy"):
                with verify.parents.decisions._persistent_lock(directory):
                    pytest.fail("parent lock was not held")
        return original(files)

    monkeypatch.setattr(verify, "_retained_gate", probe)
    run(evidence)
    for directory in (evidence.coin_dir, evidence.class_dir):
        with verify.parents.decisions._persistent_lock(directory):
            pass


@pytest.mark.parametrize(
    "field", ["run_key", "event_summary", "scientific_boundary", "unexpected"]
)
def test_resealed_full_summary_drift(evidence, field):
    members = deepcopy(evidence.members)
    key = "pem/" + evidence.directory.name + "/native_pem_summary.json"
    summary = json.loads(members[key])
    summary[field] = "changed"
    members[key] = encoded(seal(summary))
    with pytest.raises(ValueError, match="full summary"):
        verify._retained_gate(files_for(members))


def test_noncanonical_ledger_and_event_alias_refuse(evidence):
    members = deepcopy(evidence.members)
    key = "pem/" + evidence.directory.name + "/native_pem_primary.jsonl"
    members[key] = b" " + members[key]
    with pytest.raises(ValueError, match="output bytes"):
        verify._retained_gate(files_for(members))
    members = deepcopy(evidence.members)
    key = next(k for k in members if "/events/" in k)
    event = json.loads(members[key])
    event["cmax_observed"] = 0.2
    members[key] = encoded(seal(event, "event_digest"))
    with pytest.raises(ValueError, match="event/grouped"):
        verify._retained_gate(files_for(members))


@pytest.mark.parametrize(
    "unsafe", ["../escape", "/absolute", "a/../../escape", "a\\escape"]
)
def test_virtual_no_live_fallback_or_write(evidence, unsafe):
    root = verify._SnapshotPath(files_for(evidence.members), "repository")
    with pytest.raises(ValueError):
        root / unsafe
    with pytest.raises(ValueError):
        os.fspath(root)
    with pytest.raises(ValueError):
        (root / pem.CONTRACT_REL).open("wb")


def test_frozen_repository_contract_only_virtual_smoke():
    """Frozen metadata only, no historical PEM events/null calibration/results."""
    frozen = json.loads((ROOT / pem.CONTRACT_REL).read_bytes())
    names = {
        pem.CONTRACT_REL.as_posix(),
        *pem.SOURCE_PATHS,
        DQ_SNAPSHOT_REL,
        raw.INVENTORY_REL,
        raw.IMPLEMENTATION_REL,
        raw.ENTRYPOINT_REL,
        frozen["method_reference"]["path"],
        *(ref["path"] for ref in frozen["parents"].values()),
    }
    members = {"repository/" + name: (ROOT / name).read_bytes() for name in names}
    result = pem.load_contract(
        root=verify._SnapshotPath(files_for(members), "repository")
    )
    assert result == frozen
    assert all("native_pem.json" not in name for name in names)


@pytest.mark.parametrize(
    "mutation", ["channels", "maximum", "top", "verdict", "exclusion", "escape"]
)
def test_resealed_event_semantics_refuse(evidence, mutation):
    event = deepcopy(evidence.events[0])
    if mutation == "channels":
        event["channels"][0]["aux_channel"] = "V1:other"
    elif mutation == "maximum":
        event["cmax_observed"] = 0.2
    elif mutation == "top":
        event["top_channel"] = "V1:other"
    elif mutation == "verdict":
        event["verdict_tier"] = "NO_CORRELATION"
    elif mutation == "exclusion":
        event["candidate_exclusion_digest"] = "0" * 64
    else:
        event["calibration"]["filename"] = "../escape.json"
    with pytest.raises(ValueError):
        pem._verify_event(
            seal(event, "event_digest"),
            target=event["target"],
            contract=evidence.contract,
            exclusion_digest=evidence.preflight["candidate_exclusion_digest"],
            run_dir=verify._SnapshotPath(files_for(evidence.members), "pem")
            / evidence.directory.name,
        )


@pytest.mark.parametrize(
    "member,value",
    [
        ("repository/artifacts/dante_light/o3a_native_v1/native_pem.json", "compact"),
        ("pem/additional.json", "extra"),
        ("unknown/path.json", "namespace"),
    ],
)
def test_compact_and_member_closure(evidence, member, value):
    members = deepcopy(evidence.members)
    if value == "compact":
        compact = json.loads(members[member])
        compact["run_artifact_digest"] = "0" * 64
        members[member] = encoded(seal(compact))
    else:
        members[member] = b"{}"
    with pytest.raises(ValueError):
        files = files_for(members)
        for relative in verify._sources(evidence.root):
            files.read("repository", relative)
        verify._retained_gate(files)
        files.complete()


@POSIX
@pytest.mark.parametrize(
    "marker", ["failure.json", "controller.lock", "run.lock", "unfinished.partial"]
)
def test_original_guard_observations(evidence, marker):
    write(evidence.directory / marker, b"")
    with pytest.raises(ValueError, match="failure/lock|partial"):
        run(evidence)


@POSIX
@pytest.mark.parametrize("kind", ["directory", "failure", "cache", "nested_cache"])
def test_unsafe_live_guards_refuse(evidence, tmp_path, kind):
    target = tmp_path / "guard_target"
    target.mkdir()
    if kind == "directory":
        link = tmp_path / "pem_link"
        link.symlink_to(evidence.directory, target_is_directory=True)
        with pytest.raises(ValueError, match="symlink"):
            verify._guards(link)
        return
    if kind == "failure":
        (evidence.directory / "failure.json").symlink_to(target / "missing")
    elif kind == "cache":
        (evidence.directory / "transient_raw").symlink_to(
            target, target_is_directory=True
        )
    else:
        cache = evidence.directory / "transient_raw"
        cache.mkdir()
        (cache / "nested").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink|not empty or safe"):
        run(evidence)


@POSIX
def test_actual_coincidence_parent_handoff(coincidence_evidence, monkeypatch):
    """Actual 08.12 and its locks; taxonomy ancestry isolated by imported fixture.

    This integration deliberately stops before own PEM contract replay, avoiding
    a false full-chain PASS on the scaled upstream fixture's simplified metadata.
    """
    upstream = coincidence_evidence
    copy_sources(upstream.root)
    members = {
        "repository/" + r: (upstream.root / r).read_bytes()
        for r in verify._sources(upstream.root)
    }
    reached = []

    def handoff(*, root):
        assert isinstance(root, verify._SnapshotPath)
        for directory in (
            upstream.directory,
            upstream.class_dir,
            upstream.taxonomy_dir,
        ):
            with pytest.raises(ValueError, match="busy"):
                with verify.parents.decisions._persistent_lock(directory):
                    pytest.fail("upstream lock released early")
        reached.append(True)
        raise RuntimeError("linked fixture intentionally stops at PEM handoff")

    monkeypatch.setattr(pem, "load_contract", handoff)
    block_productive(monkeypatch)
    args = dict(upstream.args)
    args["coincidence_external_root"] = args.pop("external_root")
    args["pem_external_root"] = upstream.root.parent / "pem"
    with pytest.raises(RuntimeError, match="intentionally stops"):
        verify.verify_pem_evidence(**args, **package(members))
    assert reached == [True] and upstream.calls == [True]
    with verify.parents.decisions._persistent_lock(upstream.directory):
        pass


@POSIX
def test_cli_read_only_success_and_fail_closed(evidence, tmp_path, capsys):
    spec = importlib.util.spec_from_file_location(
        "pem_cli", ROOT / "scripts/verify_dante_o3a_pem_evidence.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    pins = package(evidence.members)
    archive = tmp_path / "isolated.zip"
    archive.write_bytes(pins["snapshot_bytes"])
    args = [
        "--repository-root",
        str(evidence.root),
        "--snapshot",
        str(archive),
        "--expected-snapshot-sha256",
        pins["expected_snapshot_sha256"],
        "--expected-plan-sha256",
        pins["expected_plan_sha256"],
    ]
    for name, value in evidence.args.items():
        if name != "root":
            args += ["--" + name.replace("_", "-"), str(value)]
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert (
        result["retained_pem_decisions_replayed"]
        and not result["full_workflow_verified"]
    )
    args[args.index("--expected-plan-sha256") + 1] = "0" * 64
    assert cli.main(args) == 1
    assert json.loads(capsys.readouterr().out)["status"].startswith("FAIL_CLOSED")
    with pytest.raises(SystemExit) as error:
        cli.main(args + ["--run"])
    assert error.value.code == 2


@pytest.mark.skipif(os.name == "posix", reason="Windows refusal only")
def test_unsupported_lock_platform_refuses_before_data():
    names = (
        "pem",
        "coincidence",
        "taxonomy",
        "classification",
        "threshold",
        "rescore",
        "calibration",
        "index",
        "cohort",
        "primary",
    )
    with pytest.raises(ValueError, match="POSIX"):
        verify.verify_pem_evidence(
            root=ROOT,
            snapshot_bytes=b"bad",
            expected_snapshot_sha256="0" * 64,
            expected_plan_sha256="0" * 64,
            **{n + "_external_root": ROOT / "absent" for n in names},
        )

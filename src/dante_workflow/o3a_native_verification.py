"""Separate frozen O3a scan/cohort evidence reconstruction, never scoring.

SQLite mode=ro alone can create WAL/SHM. Immutable reads here require a sealed,
quiescent database without transaction sidecars; transactions are never ignored
or checkpointed. Legacy scientific sources and their globals remain untouched.
"""

from __future__ import annotations

import bisect
from collections import Counter
from contextlib import contextmanager, ExitStack
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3

from .o3a_initial_verification import (
    InitialEvidenceError,
    _Evidence,
    _existing,
    _json,
)
from .o3a_locking import clean_native_parent, hold_native_lock
from .o3a_retained_runtime import load_runtime
from .o3a_scan_copy_admission import select_scan_database, scan_database_filename


def _no_journals(path: Path):
    if any(
        Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
    ):
        raise InitialEvidenceError(
            "SQLite transaction sidecar present; no repair attempted"
        )


def _signature(path: Path):
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


@contextmanager
def immutable_database(path: Path):
    """Read exact standalone DB bytes; never ignore an existing WAL transaction."""
    path = path.resolve(strict=True)
    if not path.is_file():
        raise InitialEvidenceError("SQLite database is not a file")
    _no_journals(path)
    before = _signature(path)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        yield connection
    finally:
        connection.close()
        _no_journals(path)
        if _signature(path) != before:
            raise InitialEvidenceError("SQLite database changed during verification")


def _pin(evidence, name, path, expected):
    from src.dante_light.o3a_raw_download import file_sha256

    digest = file_sha256(path)
    if digest != expected:
        raise InitialEvidenceError(f"evidence hash mismatch: {name}")
    evidence.inputs[name] = {"path": str(path), "sha256": digest}
    return digest


def _load(evidence, name, path, seal="artifact_digest"):
    return evidence.sealed(name, path, seal)


def _loaded(evidence, root, name, relative, value):
    prior = evidence.inputs.get(name)
    if (
        _json(
            evidence.read(
                name, _existing(root, relative), prior["sha256"] if prior else None
            )
        )
        != value
    ):
        raise InitialEvidenceError(f"loaded contract differs from file: {name}")


def _sources(root):
    from src.dante_light.o3a_raw_download import file_sha256

    names = (
        "contracts",
        "o3a_initial_calibration",
        "o3a_initial_thresholds",
        "o3a_initial_calibration_acceptance",
        "o3a_raw_acquisition",
        "o3a_raw_download",
        "o3a_native_contract",
        "o4a_corrected_runtime",
        "o3a_population_geometry",
        "o3a_scale_adequacy",
        "o3a_primary_scan",
        "o3a_native_cohort",
    )
    result = {}
    for name in names:
        module = importlib.import_module("src.dante_light." + name)
        relative = module.__name__.replace(".", "/") + ".py"
        digest = file_sha256(Path(module.__file__))
        if file_sha256(_existing(root, relative)) != digest:
            raise InitialEvidenceError(f"executed helper source mismatch: {relative}")
        result[relative] = digest
    base = Path(__file__).resolve().parents[2]
    for relative in (
        "src/dante_workflow/o3a_initial_verification.py",
        "src/dante_workflow/o3a_native_verification.py",
        "src/dante_workflow/o3a_retained_runtime.py",
        "src/dante_workflow/o3a_locking.py",
        "scripts/verify_dante_o3a_native_evidence.py",
    ):
        result[relative] = file_sha256(base / relative)
    from .o3a_scan_copy_admission import source_bindings

    result.update(source_bindings(base))
    return result


def _scan_gate(*, root, external_root, evidence, stack):
    """Existing verify_primary_scan checks; immutable SQLite and tracked inputs."""
    import numpy as np
    from src.dante_light import o3a_primary_scan as scan
    from src.dante_light.contracts import canonical_json_sha256

    contract = scan.load_scan_contract(root=root)
    _loaded(evidence, root, "scan_contract", scan.CONTRACT_REL, contract)
    runtime = load_runtime(evidence, scan.load_runtime_contract, root=root)
    _loaded(evidence, root, "runtime_contract", scan.RUNTIME_REL, runtime)
    environment = runtime["runtime_environment"]["environment_digest"]
    key = scan._run_key(contract, environment_digest=environment)
    directory = external_root / f"primary_scan_{key}"
    hold_native_lock(directory, evidence=evidence, stack=stack, name="scan")
    saved = _load(
        evidence, "scan_summary", _existing(directory, "primary_scan_summary.json")
    )
    path = _existing(directory, "primary_scan.sqlite")
    path = select_scan_database(evidence, path=path, summary=saved, stack=stack)
    _no_journals(path)
    digest = _pin(evidence, "scan_database", path, saved["database"]["sha256"])
    preflight = scan.load_primary_scan_preflight(
        contract=contract,
        run_dir=directory,
        run_key=key,
        environment_digest=environment,
    )
    if preflight != _load(
        evidence,
        "scan_preflight",
        _existing(directory, "preflight.json"),
        "preflight_digest",
    ):
        raise InitialEvidenceError("loaded scan preflight differs from file")
    identity = scan._run_identity(
        contract,
        run_key=key,
        environment_digest=environment,
        preflight_digest=preflight["preflight_digest"],
    )
    universe = scan.load_identity_universes(root=root)
    inventory = scan.load_source_inventory(root=root)
    from src.dante_light.o3a_population_geometry import MANIFEST_REL
    from src.dante_light.o3a_raw_acquisition import INVENTORY_REL

    _loaded(evidence, root, "scan_geometry", MANIFEST_REL, universe)
    _loaded(evidence, root, "scan_inventory", INVENTORY_REL, inventory)
    counts, candidates = Counter(), Counter()
    with immutable_database(path) as connection:
        observed = connection.execute(
            "SELECT value FROM metadata WHERE key='run_identity'"
        ).fetchone()
        if observed is None or json.loads(observed[0]) != identity:
            raise InitialEvidenceError("O3a primary-scan database identity mismatch")
        token_shape = [int(value) for value in preflight["token_shape"]]
        if len(token_shape) != 3 or token_shape[0] != 1:
            raise InitialEvidenceError("O3a primary-scan preflight token shape changed")
        patches, dimension = token_shape[1:]
        rows = iter(
            connection.execute(
                "SELECT detector,gps_start,primary_score,score_float32_hex,"
                "is_candidate,identity_digest,mil_vector,top_k_indices,"
                "patch_anomaly_scores FROM windows ORDER BY detector,gps_start"
            )
        )
        for detector, gps in scan.iter_role_identities(
            universe, "primary_scan_geometric_universe"
        ):
            actual = next(rows, None)
            if actual is None:
                raise InitialEvidenceError("O3a primary-scan database is truncated")
            (
                actual_detector,
                actual_gps,
                score,
                score_hex,
                candidate_flag,
                identity_digest,
                mil,
                topk,
                patch,
            ) = actual
            score = float(score)
            candidate = score > float(contract["thresholds"]["values"][detector])
            if (
                (actual_detector, int(actual_gps)) != (detector, int(gps))
                or not np.isfinite(score)
                or score_hex != np.float32(score).tobytes().hex()
                or bool(candidate_flag) != candidate
                or identity_digest != scan._identity_digest(detector, int(gps))
                or (candidate and (mil is None or topk is None or patch is None))
                or (
                    not candidate
                    and (mil is not None or topk is not None or patch is not None)
                )
            ):
                raise InitialEvidenceError("O3a primary-scan row contract mismatch")
            if candidate:
                if (
                    len(mil) != dimension * np.dtype(np.float32).itemsize
                    or len(topk)
                    != int(contract["representation"]["top_k"])
                    * np.dtype(np.int32).itemsize
                    or len(patch) != patches * np.dtype(np.float32).itemsize
                ):
                    raise InitialEvidenceError(
                        "O3a primary candidate tensor shape changed"
                    )
                candidates[detector] += 1
            counts[detector] += 1
        if next(rows, None) is not None:
            raise InitialEvidenceError("O3a primary-scan database has extra rows")
        required = {d: [] for d in ("H1", "L1")}
        for detector, gps in scan.iter_role_identities(
            universe, "primary_scan_geometric_universe"
        ):
            required[detector].append(int(gps))
        frame_count = scan._verify_raw_frame_ledger(
            connection,
            required_by_detector=scan._required_frames(
                identities=required, inventory=inventory
            ),
        )
    if dict(counts) != contract["population"]["counts_by_detector"]:
        raise InitialEvidenceError("O3a primary-scan final cardinality changed")
    if frame_count != int(
        contract["population"]["required_source_frames"]["total_count"]
    ):
        raise InitialEvidenceError("O3a primary-scan raw-frame ledger is incomplete")
    transient = directory / str(contract["storage"]["transient_raw_subdirectory"])
    if transient.is_dir() and any(p.is_file() for p in transient.rglob("*")):
        raise InitialEvidenceError("O3a primary-scan transient raw cache is not empty")
    body = {
        "schema_version": scan.SCHEMA_VERSION,
        "status": "PASS_COMPLETE_O3A_PRIMARY_SCAN",
        "run_key": key,
        "contract_digest": contract["contract_digest"],
        "threshold_artifact_digest": contract["parents"]["threshold_artifact"][
            "artifact_digest"
        ],
        "preflight_digest": preflight["preflight_digest"],
        "window_counts": dict(counts),
        "window_total": sum(counts.values()),
        "candidate_counts": {d: int(candidates[d]) for d in ("H1", "L1")},
        "candidate_total": sum(candidates.values()),
        "raw_frame_count": frame_count,
        "database": {
            "filename": scan_database_filename(evidence, path),
            "sha256": digest,
            "size_bytes": path.stat().st_size,
        },
        "invalid_or_silent_drop_count": 0,
        "ci_asymmetry_annotation": contract["ci_asymmetry_annotation"],
        "scientific_boundary": contract["scientific_boundary"],
    }
    expected = {**body, "artifact_digest": canonical_json_sha256(body)}
    if saved != expected:
        raise InitialEvidenceError("O3a primary-scan summary is stale")
    return saved, directory


def _identity_rows(database):
    with immutable_database(database) as connection:
        rows = connection.execute(
            "SELECT detector,gps_start,is_candidate FROM windows ORDER BY detector,gps_start"
        ).fetchall()
    return [(str(d), int(gps), bool(candidate)) for d, gps, candidate in rows]


def _frame_rows(database):
    with immutable_database(database) as connection:
        rows = connection.execute(
            "SELECT detector,gps_start,gps_end,filename,url,sha256,size_bytes "
            "FROM raw_frames ORDER BY detector,gps_start,filename"
        ).fetchall()
    result = {}
    for detector, start, end, filename, url, digest, size in rows:
        key = (str(detector), str(filename))
        if key in result:
            raise InitialEvidenceError("O3a primary raw-frame ledger is duplicated")
        result[key] = {
            "detector": str(detector),
            "gps_start": int(start),
            "gps_end": int(end),
            "filename": str(filename),
            "url": str(url),
            "sha256": str(digest),
            "size_bytes": int(size),
        }
    return result


def _cohort_gate(*, root, external_root, primary_external_root, evidence, stack):
    """Existing verify_native_cohort checks; immutable parent query readers."""
    import numpy as np
    from src.dante_light import o3a_native_cohort as cohort
    from src.dante_light.contracts import canonical_json_sha256

    contract = cohort.load_cohort_contract(root=root)
    _loaded(evidence, root, "cohort_contract", cohort.CONTRACT_REL, contract)
    runtime = load_runtime(evidence, cohort.load_runtime_contract, root=root)
    _loaded(evidence, root, "runtime_contract", cohort.RUNTIME_REL, runtime)
    key = cohort._run_key(
        contract,
        environment_digest=runtime["runtime_environment"]["environment_digest"],
    )
    directory = external_root / f"native_cohort_{key}"
    hold_native_lock(directory, evidence=evidence, stack=stack, name="cohort")
    preflight = _load(
        evidence,
        "cohort_preflight",
        _existing(directory, "preflight.json"),
        "preflight_digest",
    )
    evidence.read(
        "cohort_proposals",
        _existing(directory, preflight["proposal_manifest"]["filename"]),
        preflight["proposal_manifest"]["sha256"],
    )
    if preflight != cohort._load_preflight(
        contract=contract, run_dir=directory, run_key=key
    ):
        raise InitialEvidenceError("loaded cohort preflight differs from file")
    saved = _load(
        evidence, "cohort_summary", _existing(directory, "native_cohort_summary.json")
    )
    if (
        saved.get("status") != "PASS_FROZEN_O3A_NATIVE_COHORT"
        or saved.get("run_key") != key
        or saved.get("contract_digest") != contract["contract_digest"]
        or saved.get("preflight_digest") != preflight["preflight_digest"]
    ):
        raise InitialEvidenceError("O3a native-cohort summary changed")
    payload = evidence.read(
        "cohort_ledger",
        _existing(directory, "native_cohort.jsonl"),
        saved["ledger"]["sha256"],
    )
    rows = [_json(line) for line in payload.splitlines() if line.strip()]
    if canonical_json_sha256(rows) != saved["ledger"]["row_digest"]:
        raise InitialEvidenceError("O3a native-cohort ledger changed")
    target = int(contract["selection"]["target_rows_per_detector"])
    counts = {d: sum(row.get("detector") == d for row in rows) for d in ("H1", "L1")}
    if counts != {"H1": target, "L1": target} or len(rows) != len(counts) * target:
        raise InitialEvidenceError("O3a native-cohort cardinality changed")
    identities = [(str(row["detector"]), int(row["gps_start"])) for row in rows]
    if len(identities) != len(set(identities)):
        raise InitialEvidenceError("O3a native-cohort identities are duplicated")
    scan_summary, scan_dir = _scan_gate(
        root=root, external_root=primary_external_root, evidence=evidence, stack=stack
    )
    database = Path(evidence.inputs["scan_database"]["path"])
    scan_rows = _identity_rows(database)
    lookup = {(d, gps): candidate for d, gps, candidate in scan_rows}
    candidates = sorted({gps for _, gps, candidate in scan_rows if candidate})
    guard = int(contract["selection"]["candidate_guard_start_delta_s"])
    separation = int(contract["selection"]["minimum_same_detector_separation_s"])
    for detector in counts:
        starts = sorted(gps for d, gps in identities if d == detector)
        if any(right - left < separation for left, right in zip(starts, starts[1:])):
            raise InitialEvidenceError("O3a native-cohort separation gate failed")
    frames = _frame_rows(database)
    inventory = cohort.load_source_inventory(root=root)
    from src.dante_light.o3a_raw_acquisition import INVENTORY_REL

    _loaded(evidence, root, "cohort_inventory", INVENTORY_REL, inventory)
    by_detector = {d: cohort._inventory_frames(inventory, d) for d in counts}
    frame_starts = {
        d: [int(f["gps_start"]) for f in values] for d, values in by_detector.items()
    }
    preprocessing = contract["preprocessing"]
    context_samples = (
        int(preprocessing["analysis_duration_s"])
        + 2 * int(preprocessing["whitening_pad_s"])
    ) * int(preprocessing["sample_rate_hz"])
    for row in rows:
        identity = str(row["detector"]), int(row["gps_start"])
        if identity not in lookup or lookup[identity]:
            raise InitialEvidenceError("O3a native-cohort contains a primary candidate")
        gps = identity[1]
        position = bisect.bisect_left(candidates, gps - guard)
        if position < len(candidates) and candidates[position] <= gps + guard:
            raise InitialEvidenceError("O3a native-cohort violates the candidate guard")
        if row.get("quality_disposition") != "PASS_CLEAN":
            raise InitialEvidenceError(
                "O3a native-cohort contains a failed quality row"
            )
        context = _existing(directory, row["raw_context"]["relative_path"])
        _pin(
            evidence, f"context:{identity}", context, row["raw_context"]["file_sha256"]
        )
        shard_path = cohort._shard_path(directory, row)
        shard_path = _existing(directory, shard_path.relative_to(directory).as_posix())
        shard = _load(evidence, f"shard:{identity}", shard_path, "shard_digest")
        shard = cohort._validate_shard(run_dir=directory, row=row, value=shard)
        if {
            k: v
            for k, v in row.items()
            if k not in {"cohort_detector_index", "identity_digest"}
        } != shard:
            raise InitialEvidenceError("O3a native-cohort ledger/shard mismatch")
        values = np.load(context, allow_pickle=False)
        if (
            values.shape != (context_samples,)
            or str(values.dtype) != "float64"
            or not np.isfinite(values).all()
            or hashlib.sha256(values.tobytes()).hexdigest()
            != row["raw_context"]["values_sha256"]
        ):
            raise InitialEvidenceError("O3a native-cohort retained values changed")
        sources = cohort._source_rows_for_context(
            detector=identity[0],
            gps=gps,
            frames=by_detector[identity[0]],
            frame_starts=frame_starts[identity[0]],
            raw_frame_rows=frames,
        )
        if row["context_sources"] != sources or row[
            "context_sources_digest"
        ] != canonical_json_sha256(sources):
            raise InitialEvidenceError("O3a native-cohort source provenance changed")
    if scan_summary["artifact_digest"] != saved["primary_scan_artifact_digest"]:
        raise InitialEvidenceError("O3a native-cohort primary parent changed")
    transient = directory / "transient_raw"
    if transient.is_dir() and any(p.is_file() for p in transient.rglob("*")):
        raise InitialEvidenceError("O3a native-cohort transient cache is not empty")
    return saved, directory


def verify_native_evidence(
    *,
    root: Path,
    external_root: Path,
    stage: str,
    primary_external_root: Path | None = None,
):
    """Reconstruct the existing bounded gate; emit no old summary or compact."""
    from src.dante_light.contracts import canonical_json_sha256

    root, external_root = root.resolve(), external_root.resolve()
    if stage not in {"scan", "cohort"}:
        raise InitialEvidenceError("native stage not yet supported read-only")
    if (stage == "cohort") != (primary_external_root is not None):
        raise InitialEvidenceError("primary external root required only for cohort")
    sources, evidence = _sources(root), _Evidence()
    with ExitStack() as stack:
        if stage == "scan":
            summary, directory = _scan_gate(
                root=root, external_root=external_root, evidence=evidence, stack=stack
            )
        else:
            summary, directory = _cohort_gate(
                root=root,
                external_root=external_root,
                primary_external_root=primary_external_root.resolve(),
                evidence=evidence,
                stack=stack,
            )
        evidence.unchanged()
        for reference in evidence.inputs.values():
            if reference["path"].endswith(".sqlite"):
                _no_journals(Path(reference["path"]))
        for name in ("scan_summary", "cohort_summary"):
            if name in evidence.inputs:
                clean_native_parent(
                    Path(evidence.inputs[name]["path"]).parent, stack=stack
                )
        clean_native_parent(directory, stack=stack)
        if _sources(root) != sources:
            raise InitialEvidenceError("helper sources changed during verification")
        body = {
            "schema_version": 1,
            "status": f"PASS_O3A_READ_ONLY_{stage.upper()}_RECONSTRUCTION_ONLY",
            "verification_policy_id": "o3a-scan-cohort-evidence-read-only-v1",
            "verification_level": "EXISTING_FROZEN_GATE_RECONSTRUCTION",
            "observing_run": "O3a",
            "stage": stage,
            "run_dir": str(directory),
            "legacy_artifact_digest": summary["artifact_digest"],
            "historical_evidence_mutated": False,
            "raw_score_replay_executed": False,
            "encoder_executed": False,
            "threshold_fit_executed": False,
            "source_fetch_executed": False,
            "full_workflow_verified": False,
            "stored_primary_scores_read": True,
            "retained_context_samples_checked": stage == "cohort",
            "sqlite_read_mode": "mode=ro&immutable=1; no transaction sidecars",
            "inputs": evidence.inputs,
            "source_bindings": sources,
        }
        return {**body, "receipt_digest": canonical_json_sha256(body)}

"""Outcome-blind audit of historical O4a GPS identity semantics."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_gps_identity_semantics_audit_v1.json")
OUTPUT_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/gps_identity_semantics_audit_v1.json"
)
DEFAULT_EXTERNAL_ROOT = Path("E:/dante_cache/dante_light/o4a_corrected_v2")
_EPS = 1.0e-9


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _close(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= _EPS


def _pair(value: Iterable[Any]) -> tuple[float, float]:
    items = tuple(float(item) for item in value)
    if len(items) != 2:
        raise ContractError("GPS interval must contain exactly two endpoints")
    return items


def validate_contract(value: Mapping[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    contract = dict(value)
    digest = contract.pop("contract_digest", None)
    if digest != canonical_json_sha256(contract):
        raise ContractError("GPS identity audit contract digest mismatch")
    if (
        value.get("status") != "FROZEN_BEFORE_EXHAUSTIVE_GEOMETRY_AUDIT"
        or value.get("schema_version") != 1
        or not value.get("scientific_boundary", {}).get(
            "candidate_transform_may_not_be_reused_for_calibration"
        )
        or value.get("scientific_boundary", {}).get("inspects_outcomes")
    ):
        raise ContractError("GPS identity audit scientific boundary is invalid")
    for reference in value["inputs"].values():
        path = root / str(reference["path"])
        if not path.is_file() or _sha256_path(path) != str(reference["sha256"]):
            raise ContractError(f"GPS identity audit input provenance mismatch: {path}")
    return dict(value)


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_contract(_read_json(root / CONTRACT_REL), root=root)


def summarize_candidate_geometry(
    entries: Iterable[Mapping[str, Any]],
    missing: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = list(entries)
    edge_rows = list(missing)
    identities: dict[str, tuple[str, float, float]] = {}
    offsets: Counter[str] = Counter()
    geometry_failures = 0
    projected = []
    for row in rows:
        case_id = str(row["case_id"])
        catalog = row["catalog_identity"]
        window = row["window"]
        detector = str(catalog["detector"])
        catalog_gps = float(catalog["gps_start"])
        analysis_gps = float(window["gps_start"])
        if case_id in identities or detector != str(window["detector"]):
            raise ContractError("candidate geometry contains duplicate or mismatched identity")
        identities[case_id] = (detector, catalog_gps, analysis_gps)
        offset = analysis_gps - catalog_gps
        offsets[f"{offset:.1f}"] += 1
        padded = _pair(row["required_padded_interval_gps"])
        if not (
            _close(padded[0], catalog_gps)
            and _close(padded[1], catalog_gps + 40.0)
            and _close(float(window["duration_s"]), 32.0)
            and _close(analysis_gps, catalog_gps + 4.0)
        ):
            geometry_failures += 1
        projected.append((case_id, detector, catalog_gps, analysis_gps, padded))

    edge_offsets: Counter[str] = Counter()
    boundary_offsets: Counter[str] = Counter()
    edge_geometry_failures = 0
    seen_edge: set[str] = set()
    for row in edge_rows:
        case_id = str(row["case_id"])
        if case_id in seen_edge or case_id not in identities:
            raise ContractError("candidate edge cohort is not an exact subset")
        seen_edge.add(case_id)
        detector, expected_catalog, expected_analysis = identities[case_id]
        catalog = row["catalog_identity"]
        window = row["window"]
        catalog_gps = float(catalog["gps_start"])
        analysis_gps = float(window["gps_start"])
        padded = _pair(row["required_padded_interval_gps"])
        components = row["local_stitch"]["components"]
        if not components:
            raise ContractError("candidate edge row has no historical source component")
        historical_end = float(components[0]["file_interval_gps"][1])
        offset = analysis_gps - catalog_gps
        boundary_offset = historical_end - padded[0]
        edge_offsets[f"{offset:.1f}"] += 1
        boundary_offsets[f"{boundary_offset:.1f}"] += 1
        if not (
            detector == str(catalog["detector"]) == str(window["detector"])
            and _close(catalog_gps, expected_catalog)
            and _close(analysis_gps, expected_analysis)
            and _close(offset, 4.0)
            and _close(boundary_offset, 36.0)
        ):
            edge_geometry_failures += 1
    return {
        "rows": len(rows),
        "edge_rows": len(edge_rows),
        "offset_counts_s": dict(sorted(offsets.items())),
        "edge_offset_counts_s": dict(sorted(edge_offsets.items())),
        "edge_historical_boundary_offset_counts_s": dict(
            sorted(boundary_offsets.items())
        ),
        "geometry_failures": geometry_failures,
        "edge_geometry_failures": edge_geometry_failures,
        "geometry_projection_digest": canonical_json_sha256(sorted(projected)),
    }


def summarize_calibration_geometry(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(rows)
    offsets: Counter[str] = Counter()
    dispositions: Counter[str] = Counter()
    edge: Counter[str] = Counter()
    geometry_failures = 0
    seen: set[tuple[int, str, float, float]] = set()
    projected = []
    for row in items:
        session_id = int(row["session_id"])
        detector = str(row["detector"])
        catalog_gps = float(row["catalog_gps_start"])
        analysis_gps = float(row["analysis_gps_start"])
        disposition = str(row["historical_context_disposition"])
        identity = (session_id, detector, catalog_gps, analysis_gps)
        if identity in seen:
            raise ContractError("calibration geometry contains duplicate identity")
        seen.add(identity)
        offset = analysis_gps - catalog_gps
        offsets[f"{offset:.1f}"] += 1
        dispositions[disposition] += 1
        if disposition != "HISTORICAL_FULL_SYMMETRIC_4S":
            edge[f"{detector}/{disposition}"] += 1
        padded = _pair(row["required_padded_interval"])
        historical = _pair(row["historical_context_interval"])
        source = _pair(row["historical_source_span"])
        expected_offset = (
            0.0 if disposition == "HISTORICAL_LEFT_TRUNCATED_4S" else 4.0
        )
        valid_disposition = disposition in {
            "HISTORICAL_FULL_SYMMETRIC_4S",
            "HISTORICAL_LEFT_TRUNCATED_4S",
            "HISTORICAL_RIGHT_TRUNCATED_4S",
        }
        valid = (
            valid_disposition
            and _close(offset, expected_offset)
            and _close(padded[0], analysis_gps - 4.0)
            and _close(padded[1], analysis_gps + 36.0)
        )
        if disposition == "HISTORICAL_FULL_SYMMETRIC_4S":
            valid = valid and _close(historical[1] - historical[0], 40.0)
        elif disposition == "HISTORICAL_LEFT_TRUNCATED_4S":
            valid = (
                valid
                and _close(historical[1] - historical[0], 36.0)
                and _close(catalog_gps, source[0])
            )
        elif disposition == "HISTORICAL_RIGHT_TRUNCATED_4S":
            valid = (
                valid
                and _close(historical[1] - historical[0], 36.0)
                and _close(analysis_gps + 32.0, source[1])
            )
        if not valid:
            geometry_failures += 1
        projected.append(
            (
                session_id,
                detector,
                catalog_gps,
                analysis_gps,
                disposition,
                padded,
                historical,
                source,
            )
        )
    return {
        "rows": len(items),
        "offset_counts_s": dict(sorted(offsets.items())),
        "disposition_counts": dict(sorted(dispositions.items())),
        "edge_counts": dict(sorted(edge.items())),
        "geometry_failures": geometry_failures,
        "geometry_projection_digest": canonical_json_sha256(sorted(projected)),
    }


def _load_calibration_rows(
    compact: Mapping[str, Any], *, external_root: Path
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    run_dir = external_root / str(compact["external_run_directory"])
    rows: list[dict[str, Any]] = []
    shard_hashes: dict[str, str] = {}
    for reference in compact["thresholds"]:
        relative = str(reference["shard"])
        path = run_dir / relative
        value = _read_json(path)
        body = dict(value)
        digest = body.pop("shard_digest", None)
        if digest != canonical_json_sha256(body) or digest != reference["shard_digest"]:
            raise ContractError(f"calibration shard digest mismatch: {path}")
        shard_hashes[relative] = _sha256_path(path)
        rows.extend(value["rows"])
    return rows, shard_hashes


def run_audit(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> dict[str, Any]:
    root = root.resolve()
    contract = load_contract(root)
    inputs = contract["inputs"]
    entries = _read_jsonl(root / inputs["candidate_entries"]["path"])
    missing = _read_jsonl(root / inputs["candidate_missing"]["path"])
    candidate = summarize_candidate_geometry(entries, missing)
    compact = _read_json(root / inputs["calibration_compact"]["path"])
    calibration_rows, shard_hashes = _load_calibration_rows(
        compact, external_root=external_root.resolve()
    )
    calibration = summarize_calibration_geometry(calibration_rows)

    expected = contract["expected_cardinality"]
    acceptance = contract["acceptance"]
    candidate_pass = (
        candidate["rows"] == expected["candidate_rows"]
        and candidate["edge_rows"] == expected["candidate_edge_rows"]
        and candidate["offset_counts_s"]
        == {f"{acceptance['candidate_catalog_offset_s']:.1f}": expected["candidate_rows"]}
        and candidate["edge_offset_counts_s"]
        == {f"{acceptance['candidate_catalog_offset_s']:.1f}": expected["candidate_edge_rows"]}
        and candidate["edge_historical_boundary_offset_counts_s"]
        == {f"{acceptance['candidate_edge_boundary_offset_s']:.1f}": expected["candidate_edge_rows"]}
        and candidate["geometry_failures"] == 0
        and candidate["edge_geometry_failures"] == 0
    )
    calibration_pass = (
        calibration["rows"] == expected["calibration_rows"]
        and calibration["offset_counts_s"]
        == {
            "0.0": expected["calibration_offset_0s"],
            "4.0": expected["calibration_offset_4s"],
        }
        and calibration["edge_counts"] == expected["calibration_by_edge"]
        and calibration["geometry_failures"] == 0
    )
    if not candidate_pass or not calibration_pass:
        raise ContractError("GPS identity semantics audit failed its frozen gates")

    body = {
        "schema_version": 1,
        "status": "PASS_SCOPED_CANDIDATE_PLUS4_WITH_CALIBRATION_EDGE_EXCEPTION",
        "contract_digest": contract["contract_digest"],
        "candidate_catalogue": candidate,
        "primary_calibration": calibration,
        "calibration_external_shards": {
            "count": len(shard_hashes),
            "file_sha256_digest": canonical_json_sha256(shard_hashes),
        },
        "conclusion": {
            "candidate_catalogue_transform": "analysis_gps = catalog_gps + 4 s",
            "candidate_catalogue_transform_scope": "all 10,429 frozen v1 candidate rows, including all 169 candidate file-edge rows",
            "calibration_transform": "geometry-dependent: +0 s at historical left-truncated edges; +4 s otherwise",
            "final_comparison_contract_requirement": "apply +4 s only to the frozen v1 candidate catalogue; never generalize it to calibration identities",
        },
        "references": {
            key: dict(value) for key, value in sorted(inputs.items())
        },
        "scientific_boundary": dict(contract["scientific_boundary"]),
    }
    result = {**body, "artifact_digest": canonical_json_sha256(body)}
    output = root / OUTPUT_REL
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def verify_audit(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> dict[str, Any]:
    output = root.resolve() / OUTPUT_REL
    expected = _read_json(output)
    actual = run_audit(root=root, external_root=external_root)
    if actual != expected:
        raise ContractError("GPS identity semantics audit replay mismatch")
    return actual

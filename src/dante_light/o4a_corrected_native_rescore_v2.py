"""Rescore the corrected O4a candidates and fresh native-calibration v2 cohort."""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing as mp
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_execution import verify_primary_scan
from src.dante_light.o4a_corrected_native_calibration import (
    verify_native_calibration_cohort,
)
from src.dante_light.o4a_corrected_native_index import verify_native_index
from src.dante_light.o4a_corrected_native_rescore import (
    _atomic_json,
    _atomic_jsonl,
    _candidate_rows,
    _float32_hex,
    _initialize_worker,
    _load_jsonl,
    _prepare_row,
    _scorer_manifest,
)
from src.dante_light.o4a_corrected_runtime import load_canonical_runtime_contract
from src.dante_light.o4a_native_provenance import (
    verify_reference_with_reconciliation,
)
from src.dante_light.prefilter_v5_protocol import sha256_path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_corrected_native_rescore_v2.json")
DEFAULT_EXTERNAL_ROOT = Path(
    "E:/dante_cache/dante_light/o4a_corrected_native_rescore_v2"
)
SCHEMA_VERSION = 1


def validate_native_rescore_v2_contract(
    contract: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(contract))
    digest = value.pop("contract_digest", None)
    if digest != canonical_json_sha256(value):
        raise ContractError("corrected native-rescore-v2 contract digest mismatch")
    if int(value.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ContractError("corrected native-rescore-v2 schema changed")
    scientific = value.get("scientific_boundary", {})
    if scientific != {
        "native_calibration_identities_changed": True,
        "primary_candidate_identities_changed": False,
        "preprocessing_changed": False,
        "top_k_changed": False,
        "old_native_scores_read": False,
        "old_native_thresholds_read": False,
        "thresholds_or_classes_computed_in_this_stage": False,
        "historical_artifacts_immutable": True,
    }:
        raise ContractError("corrected native-rescore-v2 scientific boundary changed")
    scoring = value.get("scoring", {})
    gates = value.get("gates", {})
    parent_calibration = value.get("parent_native_calibration", {})
    parent_index = value.get("parent_native_index", {})
    if (
        int(scoring.get("top_k", -1)) != 68
        or scoring.get("output_mode") != "score_only"
        or gates.get("calibration_rows_by_detector") != {"H1": 5000, "L1": 5000}
        or gates.get("candidate_rows_by_detector") != {"H1": 4720, "L1": 6222}
        or int(gates.get("exact_total_rows", -1)) != 20_942
        or gates.get("fail_closed") is not True
        or parent_calibration.get("contract_digest")
        != "b64e44e666a1bd11454db063666b3275d8c0892832d0ec3647ea9733b7f6bf4b"
        or parent_calibration.get("artifact_digest")
        != "88f1083c50c7ff9ad864869c08d3185eadd7cac99872351eb86da225b40252b4"
        or parent_calibration.get("ledger_sha256")
        != "31438cd2d2df2014732467b99cf15dbcffd5f38cddf4784f1dc74fbe5ab47c00"
        or parent_index.get("artifact_digest")
        != "de7c79b1fb3dc7eab2662b728f70b1f51694e33958e2a8460fac04d2b4081274"
        or parent_index.get("index_sha256")
        != "6a24ba02a6925bd5527b804c3ae8aa06b73fc36a654c8a6f789d22a1b3f2403b"
    ):
        raise ContractError("corrected native-rescore-v2 scoring boundary changed")
    for reference in value.get("references", {}).values():
        path = (root / str(reference["path"])).resolve()
        verify_reference_with_reconciliation(
            root=root,
            path=path,
            expected_sha256=str(reference["sha256"]),
            raw_hasher=sha256_path,
        )
    return {"contract_digest": digest, **value}


def load_native_rescore_v2_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_native_rescore_v2_contract(
        json.loads((root / CONTRACT_REL).read_text(encoding="utf-8")), root
    )


def calibration_v2_rows(
    ledger_path: Path, *, contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    source = _load_jsonl(ledger_path)
    forbidden = {
        "primary_score",
        "native_score",
        "score",
        "score_hex",
        "threshold",
        "class",
        "robustness_class",
        "taxonomy",
        "taxonomy_family",
        "disposition",
    }
    if any(forbidden & set(row) for row in source):
        raise ContractError("corrected native-rescore-v2 calibration contains outcomes")
    expected_counts = contract["gates"]["calibration_rows_by_detector"]
    counts = Counter(str(row.get("detector")) for row in source)
    if counts != Counter({name: int(count) for name, count in expected_counts.items()}):
        raise ContractError("corrected native-rescore-v2 calibration cardinality changed")
    rows: list[dict[str, Any]] = []
    for input_index, row in enumerate(source):
        detector = str(row["detector"])
        gps = float(row["gps_start"])
        expected_sources = [
            {
                "relative_path": str(item["source_relative_path"]),
                "block_interval": [float(value) for value in item["block_interval"]],
                "used_interval": [float(value) for value in item["used_interval"]],
                "sha256": str(item["source_sha256"]),
            }
            for item in row["context_sources"]
        ]
        rows.append(
            {
                "input_index": input_index,
                "population": "native_calibration",
                "detector": detector,
                "gps_start": gps,
                "ledger_row_number": int(row["row_number"]),
                "calibration_index": int(row["calibration_index"]),
                "bootstrap_block_index": int(row["bootstrap_block_index"]),
                "expected_image_sha256": str(row["expected_image_sha256"]),
                "identity_digest": str(row["identity_digest"]),
                "frozen_context_sources_digest": canonical_json_sha256(expected_sources),
            }
        )
    return rows


def validate_v2_input_rows(
    rows: Sequence[Mapping[str, Any]], *, contract: Mapping[str, Any]
) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    identities: set[tuple[str, float]] = set()
    for expected_index, row in enumerate(rows):
        if int(row["input_index"]) != expected_index:
            raise ContractError("corrected native-rescore-v2 input order changed")
        detector = str(row["detector"])
        identity = (detector, float(row["gps_start"]))
        if detector not in {"H1", "L1"} or identity in identities:
            raise ContractError("corrected native-rescore-v2 identity is invalid")
        identities.add(identity)
        counts[str(row["population"])][detector] += 1
    expected_calibration = contract["gates"]["calibration_rows_by_detector"]
    expected_candidates = contract["gates"]["candidate_rows_by_detector"]
    if any(
        counts["native_calibration"][detector] != int(expected_calibration[detector])
        or counts["primary_candidate"][detector] != int(expected_candidates[detector])
        for detector in ("H1", "L1")
    ):
        raise ContractError("corrected native-rescore-v2 input cardinality changed")
    return {
        population: {detector: int(counter[detector]) for detector in ("H1", "L1")}
        for population, counter in counts.items()
    }


def _run_key(
    contract: Mapping[str, Any],
    *,
    calibration_summary: Mapping[str, Any],
    index_summary: Mapping[str, Any],
    scan_summary: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> str:
    return canonical_json_sha256(
        {
            "stage": "native_calibration_v2_and_candidate_full_rescore",
            "contract_digest": contract["contract_digest"],
            "calibration_artifact_digest": calibration_summary["artifact_digest"],
            "index_artifact_digest": index_summary["artifact_digest"],
            "primary_scan_artifact_digest": scan_summary["artifact_digest"],
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
        }
    )


def _verified_parents(
    *,
    root: Path,
    primary_external_root: Path,
    native_external_root: Path,
    calibration_external_root: Path,
    index_external_root: Path,
    device: str,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path, dict[str, Any], Path, dict[str, Any]]:
    calibration_summary, calibration_dir = verify_native_calibration_cohort(
        root=root,
        primary_external_root=primary_external_root,
        native_external_root=native_external_root,
        external_root=calibration_external_root,
        device=device,
    )
    index_summary, index_dir = verify_native_index(
        root=root,
        primary_external_root=primary_external_root,
        cohort_external_root=native_external_root,
        external_root=index_external_root,
        device=device,
    )
    scan_summary, scan_dir = verify_primary_scan(
        root=root, external_root=primary_external_root
    )
    runtime = load_canonical_runtime_contract(
        root=root, require_current=True, device=device
    )
    return (
        calibration_summary,
        calibration_dir,
        index_summary,
        index_dir,
        scan_summary,
        scan_dir,
        runtime,
    )


def run_native_rescore_v2(
    *,
    root: Path = ROOT,
    raw_root: Path,
    primary_external_root: Path,
    native_external_root: Path,
    calibration_external_root: Path,
    index_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
    workers: int = 8,
    batch_size: int = 32,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    raw_root = raw_root.resolve()
    contract = load_native_rescore_v2_contract(root)
    execution = contract["execution"]
    if workers != int(execution["workers"]) or batch_size != int(execution["batch_size"]):
        raise ContractError("corrected native-rescore-v2 execution parameters changed")
    (
        calibration_summary,
        calibration_dir,
        index_summary,
        index_dir,
        scan_summary,
        scan_dir,
        runtime,
    ) = _verified_parents(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        native_external_root=native_external_root.resolve(),
        calibration_external_root=calibration_external_root.resolve(),
        index_external_root=index_external_root.resolve(),
        device=device,
    )
    run_key = _run_key(
        contract,
        calibration_summary=calibration_summary,
        index_summary=index_summary,
        scan_summary=scan_summary,
        runtime=runtime,
    )
    run_dir = external_root.resolve() / f"native_rescore_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "native_rescore_summary.json"
    failure_path = run_dir / "failure.json"
    outputs = {
        "native_calibration_H1": run_dir / "native_calibration_H1.jsonl",
        "native_calibration_L1": run_dir / "native_calibration_L1.jsonl",
        "primary_candidate": run_dir / "native_candidates.jsonl",
    }
    if failure_path.is_file():
        raise ContractError("corrected native-rescore-v2 failure artifact is present")
    if summary_path.is_file() or any(path.is_file() for path in outputs.values()):
        return verify_native_rescore_v2(
            root=root,
            primary_external_root=primary_external_root,
            native_external_root=native_external_root,
            calibration_external_root=calibration_external_root,
            index_external_root=index_external_root,
            external_root=external_root,
            device=device,
        )
    identity = {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "calibration_artifact_digest": calibration_summary["artifact_digest"],
        "index_artifact_digest": index_summary["artifact_digest"],
        "primary_scan_artifact_digest": scan_summary["artifact_digest"],
        "runtime_environment_digest": runtime["runtime_environment"][
            "environment_digest"
        ],
        "workers": workers,
        "batch_size": batch_size,
        "device": device,
    }
    _atomic_json(run_dir / "run_identity.json", identity)
    try:
        calibration = calibration_v2_rows(
            calibration_dir / str(calibration_summary["ledger"]["filename"]),
            contract=contract,
        )
        candidates = _candidate_rows(
            scan_dir / "primary_scan.sqlite", offset=len(calibration)
        )
        rows = calibration + candidates
        counts = validate_v2_input_rows(rows, contract=contract)
        index_path = index_dir / str(index_summary["index"]["filename"])
        if sha256_file(index_path) != index_summary["index"]["sha256"]:
            raise ContractError("corrected native-rescore-v2 index hash changed")
        scorer_manifest = run_dir / "scorer_artifact_manifest.json"
        _scorer_manifest(
            scorer_manifest,
            index_path=index_path,
            index_sha256=index_summary["index"]["sha256"],
        )
        from src.core.patch_scorer import PatchScorer

        scorer = PatchScorer(
            index_path,
            device=device,
            k=int(contract["scoring"]["top_k"]),
            expected_sha256=index_summary["index"]["sha256"],
            artifact_manifest_path=scorer_manifest,
            k_ablations=[],
            n_background=0,
        )
        result_rows: list[dict[str, Any]] = []
        manifest_path = root / str(contract["references"]["raw_manifest"]["path"])
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_initialize_worker,
            initargs=(str(manifest_path), str(raw_root)),
        ) as executor:
            for start in range(0, len(rows), batch_size):
                batch_rows = rows[start : start + batch_size]
                prepared = list(
                    executor.map(
                        _prepare_row,
                        [
                            (
                                row,
                                float(contract["preprocessing"]["whitening_pad_s"]),
                                str(contract["preprocessing"]["colormap"]),
                            )
                            for row in batch_rows
                        ],
                    )
                )
                for _image, replay in prepared:
                    expected_context = replay.get("frozen_context_sources_digest")
                    if (
                        expected_context is not None
                        and replay["context_sources_digest"] != expected_context
                    ):
                        raise ContractError(
                            "corrected native-rescore-v2 context provenance mismatch"
                        )
                tokens = scorer.encode_patch_tokens([item[0] for item in prepared])
                scored = scorer.score_patch_tokens(
                    tokens, 1.0, output_mode=str(contract["scoring"]["output_mode"])
                )
                if len(scored) != len(batch_rows):
                    raise ContractError("corrected native-rescore-v2 scorer batch is incomplete")
                for (_image, replay), score_row in zip(prepared, scored, strict=True):
                    score = float(score_row["novelty_score"])
                    replay["native_score"] = score
                    replay["score_float32_hex"] = _float32_hex(score)
                    result_rows.append(replay)
        if len(result_rows) != int(contract["gates"]["exact_total_rows"]):
            raise ContractError("corrected native-rescore-v2 output is incomplete")
        grouped = {
            "native_calibration_H1": [
                row
                for row in result_rows
                if row["population"] == "native_calibration" and row["detector"] == "H1"
            ],
            "native_calibration_L1": [
                row
                for row in result_rows
                if row["population"] == "native_calibration" and row["detector"] == "L1"
            ],
            "primary_candidate": [
                row for row in result_rows if row["population"] == "primary_candidate"
            ],
        }
        for name, path in outputs.items():
            _atomic_jsonl(path, grouped[name])
        output_summary = {
            name: {
                "filename": path.name,
                "row_total": len(grouped[name]),
                "sha256": sha256_file(path),
                "row_digest": canonical_json_sha256(grouped[name]),
                "size_bytes": path.stat().st_size,
            }
            for name, path in outputs.items()
        }
        body = {
            **identity,
            "status": "PASS_COMPLETE_NATIVE_RESCORE_V2",
            "input_counts": counts,
            "row_total": len(result_rows),
            "outputs": output_summary,
            "gates": {
                "calibration_image_hash_mismatches": 0,
                "candidate_image_hash_mismatches": 0,
                "context_provenance_mismatches": 0,
                "context_failures": 0,
                "nonfinite_scores": 0,
                "old_native_scores_read": False,
                "old_native_thresholds_read": False,
            },
        }
        body["artifact_digest"] = canonical_json_sha256(body)
        _atomic_json(summary_path, body)
        return verify_native_rescore_v2(
            root=root,
            primary_external_root=primary_external_root,
            native_external_root=native_external_root,
            calibration_external_root=calibration_external_root,
            index_external_root=index_external_root,
            external_root=external_root,
            device=device,
        )
    except BaseException as exc:
        failure = {
            **identity,
            "status": "FAILED_NATIVE_RESCORE_V2",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        failure["artifact_digest"] = canonical_json_sha256(failure)
        _atomic_json(failure_path, failure)
        raise


def verify_native_rescore_v2(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    native_external_root: Path,
    calibration_external_root: Path,
    index_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_native_rescore_v2_contract(root)
    (
        calibration_summary,
        calibration_dir,
        index_summary,
        _index_dir,
        scan_summary,
        scan_dir,
        runtime,
    ) = _verified_parents(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        native_external_root=native_external_root.resolve(),
        calibration_external_root=calibration_external_root.resolve(),
        index_external_root=index_external_root.resolve(),
        device=device,
    )
    run_key = _run_key(
        contract,
        calibration_summary=calibration_summary,
        index_summary=index_summary,
        scan_summary=scan_summary,
        runtime=runtime,
    )
    run_dir = external_root.resolve() / f"native_rescore_{run_key}"
    if (run_dir / "failure.json").is_file():
        raise ContractError("corrected native-rescore-v2 failure artifact is present")
    summary_path = run_dir / "native_rescore_summary.json"
    if not summary_path.is_file():
        raise ContractError("corrected native-rescore-v2 summary is missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    digest = body.pop("artifact_digest", None)
    expected_gates = {
        "calibration_image_hash_mismatches": 0,
        "candidate_image_hash_mismatches": 0,
        "context_provenance_mismatches": 0,
        "context_failures": 0,
        "nonfinite_scores": 0,
        "old_native_scores_read": False,
        "old_native_thresholds_read": False,
    }
    if (
        digest != canonical_json_sha256(body)
        or summary.get("status") != "PASS_COMPLETE_NATIVE_RESCORE_V2"
        or summary.get("run_key") != run_key
        or summary.get("contract_digest") != contract["contract_digest"]
        or int(summary.get("row_total", -1)) != 20_942
        or summary.get("gates") != expected_gates
    ):
        raise ContractError("corrected native-rescore-v2 summary boundary changed")
    frozen_calibration = calibration_v2_rows(
        calibration_dir / str(calibration_summary["ledger"]["filename"]),
        contract=contract,
    )
    frozen_candidates = _candidate_rows(
        scan_dir / "primary_scan.sqlite", offset=len(frozen_calibration)
    )
    expected = {
        (str(row["detector"]), float(row["gps_start"])): row
        for row in frozen_calibration + frozen_candidates
    }
    seen: set[tuple[str, float]] = set()
    expected_outputs = {
        "native_calibration_H1": 5000,
        "native_calibration_L1": 5000,
        "primary_candidate": 10942,
    }
    for name, expected_count in expected_outputs.items():
        metadata = summary["outputs"][name]
        path = run_dir / str(metadata["filename"])
        if not path.is_file() or sha256_file(path) != metadata["sha256"]:
            raise ContractError("corrected native-rescore-v2 output hash changed")
        rows = _load_jsonl(path)
        if len(rows) != expected_count or canonical_json_sha256(rows) != metadata["row_digest"]:
            raise ContractError("corrected native-rescore-v2 output cardinality changed")
        for row in rows:
            identity = (str(row["detector"]), float(row["gps_start"]))
            frozen = expected.get(identity)
            if (
                identity in seen
                or frozen is None
                or str(row["identity_digest"]) != str(frozen["identity_digest"])
                or str(row["image_sha256"]) != str(frozen["expected_image_sha256"])
                or not np.isfinite(float(row["native_score"]))
                or _float32_hex(float(row["native_score"]))
                != row["score_float32_hex"]
                or len(str(row["raw_context_sha256"])) != 64
                or len(str(row["clean_window_sha256"])) != 64
                or canonical_json_sha256(row["context_sources"])
                != row["context_sources_digest"]
            ):
                raise ContractError("corrected native-rescore-v2 replay changed")
            if (
                row["population"] == "native_calibration"
                and row["context_sources_digest"]
                != row["frozen_context_sources_digest"]
            ):
                raise ContractError("corrected native-rescore-v2 frozen context changed")
            seen.add(identity)
    if len(seen) != 20_942:
        raise ContractError("corrected native-rescore-v2 verification is incomplete")
    return summary, run_dir


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "calibration_v2_rows",
    "load_native_rescore_v2_contract",
    "run_native_rescore_v2",
    "validate_native_rescore_v2_contract",
    "validate_v2_input_rows",
    "verify_native_rescore_v2",
]

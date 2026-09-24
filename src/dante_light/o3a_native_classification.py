"""Apply the frozen detector-local CI rule to every verified O3a seed."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from src.dante_light import o3a_native_thresholds as nt
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_calibration_cohort import _atomic_json, _atomic_jsonl
from src.dante_light.o3a_native_contract import ROOT, RUNTIME_REL
from src.dante_light.o3a_native_rescore import (
    DEFAULT_EXTERNAL_ROOT,
    CONTRACT_REL as RESCORE_CONTRACT_REL,
    _float32_hex,
    load_rescore_contract,
)
from src.dante_light.o3a_raw_download import file_sha256
from src.dante_light.o3a_scale_adequacy import STAGE_CONTRACT_REL, load_stage_contract

CONTRACT_REL = "config/dante_o3a_native_classification_v1.json"
COMPACT_REL = "artifacts/dante_light/o3a_native_v1/native_classification.json"
RULE = "BACKGROUND_BELOW_CI_LOWER_ROBUST_ABOVE_CI_UPPER_AMBIGUOUS_OTHERWISE"
LABELS = ("BACKGROUND", "AMBIGUOUS", "ROBUST")
SOURCE_PATHS = (
    "src/dante_light/o3a_native_classification.py",
    "scripts/run_dante_o3a_native_classification.py",
    "tests/test_dante_o3a_native_classification.py",
)


def build_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Read metadata only; candidate outcomes remain unopened before freeze."""
    stage = load_stage_contract(root=root)
    rescore = load_rescore_contract(root=root)
    threshold_contract = nt.load_threshold_contract(root=root)
    receipt = nt._read_json(root / nt.COMPACT_REL)
    nt._sealed(receipt, "artifact_digest")
    rule = stage["author_decisions"]["native_threshold_statistics"][
        "classification_rule"
    ]
    if rule != RULE:
        raise ContractError("O3a classification rule requires review")
    if (
        receipt["status"] != "PASS_VERIFIED_O3A_NATIVE_THRESHOLDS"
        or receipt["contract_digest"] != threshold_contract["contract_digest"]
        or receipt["method"] != threshold_contract["method"]
        or receipt["native_rescore_artifact_digest"]
        != threshold_contract["parent_rescore"]["artifact_digest"]
        or receipt["scientific_boundary"] != threshold_contract["scientific_boundary"]
    ):
        raise ContractError("O3a classification threshold parent not verified")
    refs = (
        STAGE_CONTRACT_REL,
        RESCORE_CONTRACT_REL,
        nt.CONTRACT_REL,
        nt.COMPACT_REL,
        nt.RESCORE_REL,
        RUNTIME_REL,
    )
    body = {
        "schema_version": 1,
        "status": "FROZEN_O3A_NATIVE_CLASSIFICATION_V1",
        "run": "O3A",
        "rule": rule,
        "boundary_class": "AMBIGUOUS",
        "population": {
            "rows_by_detector": rescore["population"]["candidate_rows_by_detector"],
            "selection": "ALL_FROZEN_PRIMARY_SEEDS",
        },
        "threshold_parent": {
            k: receipt[k]
            for k in (
                "artifact_digest",
                "run_artifact_digest",
                "contract_digest",
                "run_key",
            )
        },
        "rescore_parent": threshold_contract["parent_rescore"],
        "references": {p: file_sha256(root / p) for p in refs},
        "implementation_sources": {p: file_sha256(root / p) for p in SOURCE_PATHS},
        "scientific_boundary": {
            "scores_changed": False,
            "population_changed": False,
            "thresholds_changed": False,
            "detector_pooling": False,
            "taxonomy_performed": False,
            "coincidence_performed": False,
            "pem_performed": False,
            "multiscale_used": False,
            "global_significance_claim": False,
        },
        "output": {
            "summary_filename": "native_classification_summary.json",
            "candidate_filename": "native_classified_candidates.jsonl",
        },
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def freeze_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = build_contract(root=root)
    _atomic_json(root / CONTRACT_REL, value)
    return value


def load_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = nt._read_json(root / CONTRACT_REL)
    if value != build_contract(root=root):
        raise ContractError("O3a classification frozen contract or source changed")
    return value


def classify_score(score: float, *, lower: float, upper: float) -> str:
    if not np.isfinite([score, lower, upper]).all() or lower > upper:
        raise ContractError("O3a classification interval or score invalid")
    return "BACKGROUND" if score < lower else "ROBUST" if score > upper else "AMBIGUOUS"


def classify_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    thresholds: Mapping[str, Any],
    expected_counts: Mapping[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if set(thresholds) != set(expected_counts):
        raise ContractError("O3a classification detector thresholds changed")
    if len(rows) != sum(expected_counts.values()):
        raise ContractError("O3a classification population changed")
    forbidden = {
        "native_class",
        "class",
        "robustness_class",
        "taxonomy",
        "taxonomy_family",
        "disposition",
        "native_threshold_ci_lower",
        "native_threshold_p99",
        "native_threshold_ci_upper",
    }
    identities = set()
    previous = None
    result = []
    counts = {d: Counter() for d in sorted(expected_counts)}
    for ordinal, source in enumerate(rows):
        detector = source.get("detector")
        gps, score = (
            float(source.get("gps_start", np.nan)),
            float(source.get("native_score", np.nan)),
        )
        key = (detector, gps)
        if (
            forbidden.intersection(source)
            or source.get("population") != "primary_candidate"
            or source.get("ordinal") != ordinal
            or detector not in expected_counts
            or not np.isfinite([gps, score]).all()
            or gps <= 0
            or key in identities
            or source.get("score_float32_hex") != _float32_hex(score)
            or not isinstance(source.get("identity_digest"), str)
            or not source["identity_digest"]
            or (previous is not None and key <= previous)
        ):
            raise ContractError("O3a classification identity/order/score changed")
        limit = thresholds[detector]
        lower, point, upper = (float(limit[k]) for k in ("ci_lower", "p99", "ci_upper"))
        if not np.isfinite([lower, point, upper]).all() or not lower <= point <= upper:
            raise ContractError("O3a classification threshold interval invalid")
        label = classify_score(score, lower=lower, upper=upper)
        result.append(
            {
                **source,
                "native_class": label,
                "native_threshold_ci_lower": lower,
                "native_threshold_p99": point,
                "native_threshold_ci_upper": upper,
            }
        )
        counts[detector][label] += 1
        identities.add(key)
        previous = key
    if any(sum(counts[d].values()) != n for d, n in expected_counts.items()):
        raise ContractError("O3a classification detector population changed")
    return result, {
        d: {label: int(counts[d][label]) for label in LABELS} for d in counts
    }


def _run_dir(contract: Mapping[str, Any], external_root: Path) -> Path:
    key = canonical_json_sha256(
        {
            "stage": "o3a_native_classification_v1",
            "contract_digest": contract["contract_digest"],
        }
    )
    return external_root.resolve() / f"native_classification_{key}"


def _verified_inputs(contract: Mapping[str, Any], *, root: Path, external_root: Path):
    # Recompute thresholds and verify the full upstream chain before using seeds.
    threshold, _ = nt.execute_thresholds(
        root=root, external_root=external_root, verify=True
    )
    receipt = nt._read_json(root / nt.COMPACT_REL)
    nt._sealed(receipt, "artifact_digest")
    if (
        receipt["artifact_digest"] != contract["threshold_parent"]["artifact_digest"]
        or threshold["artifact_digest"]
        != contract["threshold_parent"]["run_artifact_digest"]
        or threshold["native_rescore_artifact_digest"]
        != contract["rescore_parent"]["artifact_digest"]
    ):
        raise ContractError("O3a classification verified parent changed")
    path = (
        external_root
        / ("native_rescore_" + contract["rescore_parent"]["run_key"])
        / "primary_candidate.jsonl"
    )
    if (
        file_sha256(path)
        != contract["rescore_parent"]["output_sha256"]["primary_candidate"]
    ):
        raise ContractError("O3a classification candidate input hash changed")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return rows, threshold, file_sha256(path)


def execute(
    *,
    root: Path = ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    verify: bool = False,
) -> tuple[dict[str, Any], Path]:
    contract = load_contract(root=root)
    directory = _run_dir(contract, external_root)
    with nt._lock(directory):
        failure = directory / "failure.json"
        path = directory / contract["output"]["summary_filename"]
        output = directory / contract["output"]["candidate_filename"]
        if failure.exists():
            raise ContractError("O3a classification failure requires review")
        if verify and (not path.exists() or not output.exists()):
            raise ContractError("O3a classification evidence missing")
        try:
            rows, thresholds, source_sha = _verified_inputs(
                contract, root=root, external_root=external_root
            )
            classified, counts = classify_rows(
                rows,
                thresholds=thresholds["thresholds"],
                expected_counts=contract["population"]["rows_by_detector"],
            )
            expected_sha = hashlib.sha256(
                "".join(
                    json.dumps(
                        row, sort_keys=True, separators=(",", ":"), allow_nan=False
                    )
                    + "\n"
                    for row in classified
                ).encode("utf-8")
            ).hexdigest()
            if output.exists():
                if file_sha256(output) != expected_sha:
                    raise ContractError("O3a classification output replay changed")
            else:
                _atomic_jsonl(output, classified)
            if file_sha256(output) != expected_sha:
                raise ContractError("O3a classification output write changed")
            body = {
                "schema_version": 1,
                "status": "PASS_COMPLETE_O3A_NATIVE_CLASSIFICATION",
                "contract_digest": contract["contract_digest"],
                "run_key": directory.name.removeprefix("native_classification_"),
                "threshold_artifact_digest": thresholds["artifact_digest"],
                "runtime_environment_digest": thresholds["runtime_environment_digest"],
                "rescore_artifact_digest": contract["rescore_parent"][
                    "artifact_digest"
                ],
                "rule": contract["rule"],
                "row_total": len(classified),
                "counts_by_detector_and_class": counts,
                "source_sha256": source_sha,
                "output_sha256": expected_sha,
                "output_row_digest": canonical_json_sha256(classified),
                "scientific_boundary": contract["scientific_boundary"],
            }
            summary = {**body, "artifact_digest": canonical_json_sha256(body)}
            if path.exists() and nt._read_json(path) != summary:
                raise ContractError("O3a classification summary replay changed")
            _atomic_json(path, summary)
            if verify:
                compact = {
                    **body,
                    "status": "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION",
                    "external_run_dir_wsl": str(directory),
                    "run_artifact_digest": summary["artifact_digest"],
                    "summary_sha256": file_sha256(path),
                }
                _atomic_json(
                    root / COMPACT_REL,
                    {**compact, "artifact_digest": canonical_json_sha256(compact)},
                )
            return summary, directory
        except BaseException as exc:
            body = {
                "status": "FAILED_O3A_NATIVE_CLASSIFICATION",
                "contract_digest": contract["contract_digest"],
                "run_key": directory.name.removeprefix("native_classification_"),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            _atomic_json(
                failure, {**body, "artifact_digest": canonical_json_sha256(body)}
            )
            raise

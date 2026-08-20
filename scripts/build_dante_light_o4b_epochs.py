#!/usr/bin/env python3
"""Promote O4a-calibrated detector epochs for locked O4b shadow use."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify_c2_bgv3_artifacts as c2  # noqa: E402
from scripts import verify_cqg_validation_artifacts as cqg  # noqa: E402
from src.dante_light.contracts import (  # noqa: E402
    RepresentationContract,
    canonical_json_sha256,
)
from src.dante_light.epoch import REQUIRED_GATES  # noqa: E402


AGG = ROOT / "data" / "production" / "aggregated"
THRESHOLD = AGG / "dsd_thresholds_o4a_idxq4-64_queryq4-64.json"
SHADOW_MANIFEST = ROOT / "config" / "dante_light_o4b_shadow_v2.json"
DQ_SNAPSHOT = ROOT / "config" / "dante_light_o4b_cat1_segments_v1.json"
RECEIPT = ROOT / "artifacts" / "dante_light" / "o4b_epoch_gate_receipt_v2.json"
PROMOTIONS = {
    detector: ROOT / "config" / f"dante_light_o4b_promotion_{detector.lower()}_v2.json"
    for detector in ("H1", "L1")
}
O4A_START_GPS = 1368975618.0
O4A_END_GPS = 1389456018.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def repo_path(raw: str | Path) -> Path:
    return ROOT / Path(str(raw).replace("\\", "/"))


def write_locked(path: Path, payload: dict[str, Any], *, check: bool) -> None:
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    if check:
        if not path.is_file() or path.read_bytes() != encoded:
            raise RuntimeError(f"stale or missing locked artifact: {path}")
        return
    if path.exists() and path.read_bytes() != encoded:
        raise RuntimeError(f"refusing to overwrite divergent artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def _run_gate(name: str, verifier: Callable[[], None]) -> dict[str, str]:
    verifier()
    return {"status": "PASS", "verifier": name}


def verify_inputs() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    threshold = json.loads(THRESHOLD.read_text(encoding="utf-8"))
    manifest = json.loads(SHADOW_MANIFEST.read_text(encoding="utf-8"))
    entries_path = ROOT / manifest["entries_path"]
    if sha256(entries_path) != manifest["entries_file_sha256"]:
        raise RuntimeError("O4b shadow entry-file SHA256 mismatch")
    entries = [
        json.loads(line)
        for line in entries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if manifest.get("status") != "locked_before_scoring":
        raise RuntimeError("O4b shadow manifest is not locked")
    if manifest.get("outcome_fields_used_for_selection") != []:
        raise RuntimeError("O4b shadow selection is not outcome-blind")
    if any(entry.get("expected") for entry in entries):
        raise RuntimeError("O4b shadow entries contain inspected outcomes")
    if threshold.get("run") != "O4a":
        raise RuntimeError("causal source threshold is not O4a")
    for detector in ("H1", "L1"):
        record = threshold["thresholds"][detector]
        if [float(value) for value in record["run_bounds_gps"]] != [
            O4A_START_GPS,
            O4A_END_GPS,
        ]:
            raise RuntimeError(f"{detector} calibration bounds are not frozen O4a")
        ledger_path = repo_path(record["background_ledger_path"])
        ledger = pd.read_csv(ledger_path)
        if len(ledger) != 5000 or float(ledger["gps_start"].max()) > O4A_END_GPS:
            raise RuntimeError(f"{detector} calibration ledger is not causal")
        selected = [
            entry for entry in entries if entry["window"]["detector"] == detector
        ]
        if not selected or min(entry["window"]["gps_start"] for entry in selected) <= O4A_END_GPS:
            raise RuntimeError(f"{detector} evaluation is not after calibration")
    return threshold, manifest, entries


def artifact_paths(
    threshold: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, list[Path]]:
    ledgers = [
        repo_path(threshold["thresholds"][detector]["background_ledger_path"])
        for detector in ("H1", "L1")
    ]
    scores = [
        repo_path(threshold["thresholds"][detector]["background_scores_path"])
        for detector in ("H1", "L1")
    ]
    return {
        "temporal_separation": [THRESHOLD, SHADOW_MANIFEST, DQ_SNAPSHOT],
        "background_quality": [THRESHOLD, *ledgers, *scores],
        "known_glitch_replay": [AGG / "cqg_known_glitch_controls.json"],
        "injection_replay": [
            AGG / "astrophysical_injection_o4a_idxq4-64_queryq4-64.json",
            AGG / "astrophysical_injection_trials_o4a_idxq4-64_queryq4-64.csv",
        ],
        "dsd_transition_audit": [
            AGG / "dsd_transition_audit_o4a_idxq4-64_queryq4-64.json",
            AGG / "Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv",
        ],
        "drift_baseline": [AGG / "cqg_cross_run_domain_shift.json"],
    }


def build(*, check: bool = False) -> dict[str, Any]:
    threshold, manifest, entries = verify_inputs()
    gate_paths = artifact_paths(threshold, manifest)
    for paths in gate_paths.values():
        for path in paths:
            if not path.is_file():
                raise RuntimeError(f"missing epoch-gate artifact: {path}")

    gate_results = {
        "temporal_separation": {"status": "PASS", "verifier": "verify_inputs"},
        "background_quality": _run_gate("c2.verify_p5", c2.verify_p5),
        "known_glitch_replay": _run_gate(
            "cqg.verify_known(final,deep)",
            lambda: cqg.verify_known(pilot=False, deep=True),
        ),
        "injection_replay": _run_gate("c2.verify_p9", c2.verify_p9),
        "dsd_transition_audit": _run_gate("c2._taxonomy", c2._taxonomy),
        "drift_baseline": _run_gate(
            "cqg.verify_domain(final,deep)",
            lambda: cqg.verify_domain(pilot=False, deep=True),
        ),
    }
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": "PASS",
        "purpose": "O4a-calibrated causal epoch gates for O4b shadow evaluation",
        "calibration_bounds_gps": [O4A_START_GPS, O4A_END_GPS],
        "shadow_manifest_sha256": sha256(SHADOW_MANIFEST),
        "gate_results": gate_results,
        "gate_artifacts": {
            gate: [
                {"path": rel(path), "sha256": sha256(path)} for path in paths
            ]
            for gate, paths in gate_paths.items()
        },
        "verifier_source_sha256": {
            rel(ROOT / "scripts" / "verify_c2_bgv3_artifacts.py"): sha256(
                ROOT / "scripts" / "verify_c2_bgv3_artifacts.py"
            ),
            rel(ROOT / "scripts" / "verify_cqg_validation_artifacts.py"): sha256(
                ROOT / "scripts" / "verify_cqg_validation_artifacts.py"
            ),
            rel(Path(__file__)): sha256(Path(__file__)),
        },
    }
    receipt["receipt_sha256"] = canonical_json_sha256(receipt)
    write_locked(RECEIPT, receipt, check=check)

    representation = RepresentationContract.from_reference_manifest(
        ROOT / "config" / "reference_artifacts.json"
    )
    source_sha = sha256(THRESHOLD)
    all_paths = {RECEIPT, THRESHOLD}
    for paths in gate_paths.values():
        all_paths.update(paths)
    artifacts = [
        {"path": rel(path), "sha256": sha256(path)}
        for path in sorted(all_paths, key=lambda item: rel(item))
    ]
    artifact_path_set = {item["path"] for item in artifacts}
    for detector in ("H1", "L1"):
        record = threshold["thresholds"][detector]
        ledger_path = repo_path(record["background_ledger_path"])
        selected = [
            entry for entry in entries if entry["window"]["detector"] == detector
        ]
        gate_artifacts = {
            gate: sorted({rel(RECEIPT), *(rel(path) for path in paths)})
            for gate, paths in gate_paths.items()
        }
        if any(set(paths) - artifact_path_set for paths in gate_artifacts.values()):
            raise RuntimeError("gate-specific artifact binding is incomplete")
        promotion: dict[str, Any] = {
            "schema_version": 1,
            "source_threshold_artifact": {
                "path": rel(THRESHOLD),
                "sha256": source_sha,
            },
            "calibration_ledger": {
                "path": rel(ledger_path),
                "sha256": sha256(ledger_path),
            },
            "epoch": {
                "schema_version": 1,
                "epoch_id": f"o4a-calibrated-o4b-causal-{detector.lower()}-v2",
                "run": "O4B",
                "detector": detector,
                "cutoff_gps": O4A_END_GPS,
                "threshold": float(record["p99"]),
                "threshold_artifact_sha256": source_sha,
                "native_index_sha256": representation.native_index_sha256,
                "causal": True,
            },
            "promotion_evidence": {
                "detector": detector,
                "run": "O4B",
                "calibration_start_gps": O4A_START_GPS,
                "calibration_end_gps": O4A_END_GPS,
                "evaluation_start_gps": min(
                    float(entry["window"]["gps_start"]) for entry in selected
                ),
                "evaluation_end_gps": max(
                    float(entry["window"]["gps_start"])
                    + float(entry["window"]["duration_s"])
                    for entry in selected
                ),
                "gates": {gate: "PASS" for gate in REQUIRED_GATES},
                "gate_artifacts": gate_artifacts,
                "artifacts": artifacts,
            },
        }
        write_locked(PROMOTIONS[detector], promotion, check=check)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    receipt = build(check=args.check)
    print(json.dumps(receipt["gate_results"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

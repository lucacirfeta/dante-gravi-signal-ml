#!/usr/bin/env python3
"""Assemble detector-specific causal DANTE-Light epochs from verified evidence."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.index_contract import sha256_file
from src.dante_light.contracts import (
    ContractError,
    RepresentationContract,
    canonical_json_sha256,
)
from src.dante_light.epoch import verified_epoch_from_promotion


def _root_member(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise ContractError(f"epoch evidence path escapes project root: {relative}")
    return path


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read promotion payload {path}: {exc}") from exc
    if payload.get("schema_version") != 1:
        raise ContractError(f"unsupported promotion payload schema: {path}")
    return payload


def _verified_promotion(
    payload: dict[str, Any],
    *,
    representation: RepresentationContract,
    root: Path,
) -> tuple[str, dict[str, Any], dict[str, str]]:
    source = payload["source_threshold_artifact"]
    source_path = _root_member(root, str(source["path"]))
    source_sha256 = str(source["sha256"]).lower()
    if not source_path.is_file() or sha256_file(source_path) != source_sha256:
        raise ContractError("source threshold artifact SHA256 mismatch")

    ledger = payload["calibration_ledger"]
    ledger_path = _root_member(root, str(ledger["path"]))
    ledger_sha256 = str(ledger["sha256"]).lower()
    if not ledger_path.is_file() or sha256_file(ledger_path) != ledger_sha256:
        raise ContractError("calibration ledger SHA256 mismatch")

    epoch = verified_epoch_from_promotion(
        {
            "epoch": payload["epoch"],
            "promotion_evidence": payload["promotion_evidence"],
        },
        representation=representation,
        root=root,
    )
    if epoch.threshold_artifact_sha256 != source_sha256:
        raise ContractError("epoch threshold provenance mismatch")
    evidence_pairs = {
        (str(item["path"]), str(item["sha256"]).lower())
        for item in payload["promotion_evidence"]["artifacts"]
    }
    for required in (
        (str(source["path"]), source_sha256),
        (str(ledger["path"]), ledger_sha256),
    ):
        if required not in evidence_pairs:
            raise ContractError(
                f"required provenance is absent from promotion evidence: {required[0]}"
            )

    raw_epoch = {
        **asdict(epoch),
        "calibration_ledger_sha256": ledger_sha256,
        "promotion_evidence": payload["promotion_evidence"],
    }
    return epoch.detector, raw_epoch, {
        "path": str(source["path"]),
        "sha256": source_sha256,
    }


def assemble_promoted_epochs(
    promotion_paths: list[str | Path],
    *,
    output_path: str | Path,
    root: str | Path = PROJECT_ROOT,
    reference_manifest: str | Path | None = None,
) -> dict[str, Any]:
    if not promotion_paths:
        raise ContractError("at least one promotion payload is required")
    root = Path(root).resolve()
    manifest = (
        Path(reference_manifest)
        if reference_manifest is not None
        else root / "config/reference_artifacts.json"
    )
    representation = RepresentationContract.from_reference_manifest(manifest)
    epochs: dict[str, dict[str, Any]] = {}
    common_source: dict[str, str] | None = None
    input_sha256: dict[str, str] = {}
    for raw_path in promotion_paths:
        candidate = Path(raw_path)
        path = (
            candidate.resolve()
            if candidate.is_absolute()
            else (root / candidate).resolve()
        )
        if path != root and root not in path.parents:
            raise ContractError(f"promotion payload escapes project root: {raw_path}")
        payload = _read_payload(path)
        detector, epoch, source = _verified_promotion(
            payload, representation=representation, root=root
        )
        if detector in epochs:
            raise ContractError(f"duplicate promoted detector: {detector}")
        if common_source is not None and source != common_source:
            raise ContractError("promoted detectors use different threshold artifacts")
        common_source = source
        epochs[detector] = epoch
        relative_input = path.relative_to(root).as_posix()
        input_sha256[relative_input] = sha256_file(path)

    body: dict[str, Any] = {
        "schema_version": 1,
        "status": "causal_promoted",
        "source_threshold_artifact": common_source,
        "epochs": {detector: epochs[detector] for detector in sorted(epochs)},
        "promotion_inputs_sha256": dict(sorted(input_sha256.items())),
    }
    body["promotion_manifest_sha256"] = canonical_json_sha256(body)

    output = Path(output_path).resolve()
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing != body:
            raise ContractError(f"refusing to overwrite divergent epoch file: {output}")
        return body
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(body, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--promotion",
        action="append",
        type=Path,
        required=True,
        help="Detector promotion payload; repeat for H1/L1.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--reference-manifest", type=Path)
    args = parser.parse_args()
    payload = assemble_promoted_epochs(
        args.promotion,
        output_path=args.output,
        root=args.root,
        reference_manifest=args.reference_manifest,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

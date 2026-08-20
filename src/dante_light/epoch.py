"""Fail-closed validation for promotion of detector-specific causal epochs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from src.core.index_contract import sha256_file
from src.dante_light.contracts import (
    CalibrationEpochContract,
    ContractError,
    RepresentationContract,
)


REQUIRED_GATES = (
    "temporal_separation",
    "background_quality",
    "known_glitch_replay",
    "injection_replay",
    "dsd_transition_audit",
    "drift_baseline",
)


@dataclass(frozen=True, slots=True)
class PromotionEvidence:
    detector: str
    run: str
    calibration_start_gps: float
    calibration_end_gps: float
    evaluation_start_gps: float
    evaluation_end_gps: float
    gates: dict[str, str]
    gate_artifacts: dict[str, tuple[str, ...]]
    artifacts: tuple[tuple[str, str], ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PromotionEvidence":
        return cls(
            detector=str(value["detector"]).upper(),
            run=str(value["run"]).upper(),
            calibration_start_gps=float(value["calibration_start_gps"]),
            calibration_end_gps=float(value["calibration_end_gps"]),
            evaluation_start_gps=float(value["evaluation_start_gps"]),
            evaluation_end_gps=float(value["evaluation_end_gps"]),
            gates={str(key): str(status) for key, status in value["gates"].items()},
            gate_artifacts={
                str(gate): tuple(str(path) for path in paths)
                for gate, paths in value.get("gate_artifacts", {}).items()
            },
            artifacts=tuple(
                (str(item["path"]), str(item["sha256"]).lower())
                for item in value["artifacts"]
            ),
        )

    def validate(self, *, root: str | Path) -> None:
        if not self.calibration_start_gps < self.calibration_end_gps:
            raise ContractError("invalid calibration interval")
        if not self.evaluation_start_gps < self.evaluation_end_gps:
            raise ContractError("invalid evaluation interval")
        if self.calibration_end_gps >= self.evaluation_start_gps:
            raise ContractError("calibration/evaluation intervals overlap or touch")
        missing = [gate for gate in REQUIRED_GATES if self.gates.get(gate) != "PASS"]
        if missing:
            raise ContractError(f"epoch promotion gates are not PASS: {missing}")
        if set(self.gates) != set(REQUIRED_GATES):
            raise ContractError("epoch promotion contains undocumented gates")
        if set(self.gate_artifacts) != set(REQUIRED_GATES):
            raise ContractError("epoch promotion lacks gate-specific provenance")
        declared_paths = {relative for relative, _ in self.artifacts}
        for gate in REQUIRED_GATES:
            paths = self.gate_artifacts[gate]
            if not paths:
                raise ContractError(f"epoch promotion gate has no artifacts: {gate}")
            unknown = sorted(set(paths) - declared_paths)
            if unknown:
                raise ContractError(
                    f"epoch promotion gate references undeclared artifacts: "
                    f"{gate}: {unknown}"
                )
        root = Path(root)
        resolved_root = root.resolve()
        if not self.artifacts:
            raise ContractError("epoch promotion requires verifier artifacts")
        for relative, expected in self.artifacts:
            path = (root / relative).resolve()
            if path != resolved_root and resolved_root not in path.parents:
                raise ContractError(
                    f"epoch evidence path escapes project root: {relative}"
                )
            if not path.is_file():
                raise ContractError(f"missing epoch evidence artifact: {relative}")
            if sha256_file(path) != expected:
                raise ContractError(f"epoch evidence SHA256 mismatch: {relative}")


def verified_epoch_from_promotion(
    payload: dict[str, Any],
    *,
    representation: RepresentationContract,
    root: str | Path,
) -> CalibrationEpochContract:
    evidence = PromotionEvidence.from_dict(payload["promotion_evidence"])
    evidence.validate(root=root)
    epoch = CalibrationEpochContract(**payload["epoch"])
    if not epoch.causal:
        raise ContractError("promoted epoch must declare causal=true")
    if epoch.detector != evidence.detector or epoch.run != evidence.run:
        raise ContractError("epoch and promotion evidence detector/run mismatch")
    if epoch.cutoff_gps != evidence.calibration_end_gps:
        raise ContractError("epoch cutoff must equal calibration end")
    if epoch.native_index_sha256 != representation.native_index_sha256:
        raise ContractError("promoted epoch uses a stale native index")
    return epoch


def load_verified_epoch(
    path: str | Path,
    *,
    representation: RepresentationContract,
    root: str | Path,
) -> CalibrationEpochContract:
    return verified_epoch_from_promotion(
        json.loads(Path(path).read_text(encoding="utf-8")),
        representation=representation,
        root=root,
    )

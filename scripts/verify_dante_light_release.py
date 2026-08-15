#!/usr/bin/env python3
"""Fail-closed release-readiness gates for DANTE-Light."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, RepresentationContract
from src.dante_light.epoch import verified_epoch_from_promotion


SHA256_RE = re.compile(r"[0-9a-f]{64}")
PROTOCOL_PATH = "docs/DANTE_LIGHT_PROSPECTIVE_PROTOCOL.md"


@dataclass(frozen=True, slots=True)
class Gate:
    name: str
    status: str
    detail: str
    required_for: tuple[str, ...]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value.lower()) is not None


def _inside(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    resolved = (root / relative).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"path escapes repository root: {relative}")
    return resolved


def _validate_replay(root: Path, replay: dict[str, Any]) -> tuple[bool, str]:
    try:
        entries = _inside(root, replay["entries_path"])
        if _sha256(entries) != replay["entries_file_sha256"]:
            return False, "replay entries SHA256 mismatch"
        rows = [
            json.loads(line)
            for line in entries.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        windows = {row["window"]["window_id"] for row in rows}
        roles = Counter(role for row in rows for role in row["roles"])
        expected = replay["counts"]
        if len(rows) != expected["entries"]:
            return False, "replay entry count mismatch"
        if len(windows) != expected["unique_windows"]:
            return False, "replay unique-window count mismatch"
        if dict(sorted(roles.items())) != dict(sorted(expected["roles"].items())):
            return False, "replay role counts mismatch"
        if replay.get("status") != "frozen":
            return False, "replay manifest is not frozen"
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return False, f"invalid replay manifest: {exc}"
    return True, f"{len(rows)} cases / {len(windows)} unique windows"


def _flatten(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for repeat in payload["results"] for row in repeat]


def _validate_benchmarks(
    root: Path, replay: dict[str, Any]
) -> tuple[bool, str]:
    paths = {
        "baseline": "benchmarks/dante_light_l0_baseline.json",
        "canonical": "benchmarks/dante_light_l1_score_only_canonical_control.json",
        "shared": "benchmarks/dante_light_l1_score_only_shared.json",
    }
    try:
        payloads = {
            name: json.loads(_inside(root, relative).read_text(encoding="utf-8"))
            for name, relative in paths.items()
        }
        for name, payload in payloads.items():
            coverage = payload["coverage"]
            tolerance = float(payload["golden_score_atol"])
            if payload.get("status") != "complete":
                raise ValueError(f"{name} status is not complete")
            if payload.get("scientific_mode") != "historical_exact_replay":
                raise ValueError(f"{name} scientific mode mismatch")
            if coverage["drops"] != 0 or coverage["failures"]:
                raise ValueError(f"{name} contains drops or failures")
            if int(coverage["measured_windows"]) <= 0:
                raise ValueError(f"{name} has no measured windows")
            if float(payload["numerical_repeat_max_abs_delta"]) > tolerance:
                raise ValueError(f"{name} repeat tolerance failed")
            if float(payload["golden_expected_max_abs_delta"]) > tolerance:
                raise ValueError(f"{name} frozen-score tolerance failed")
            manifest = payload["manifest"]
            if manifest["entries_file_sha256"] != replay["entries_file_sha256"]:
                raise ValueError(f"{name} replay corpus hash mismatch")
            if manifest["manifest_sha256"] != replay["manifest_sha256"]:
                raise ValueError(f"{name} replay manifest identity mismatch")
            jsonl = payload["results_jsonl"]
            jsonl_path = _inside(root, jsonl["path"])
            if _sha256(jsonl_path) != jsonl["sha256"]:
                raise ValueError(f"{name} JSONL SHA256 mismatch")
            row_count = sum(
                bool(line.strip())
                for line in jsonl_path.read_text(encoding="utf-8").splitlines()
            )
            if row_count != int(jsonl["rows"]):
                raise ValueError(f"{name} JSONL row count mismatch")

        canonical = payloads["canonical"]
        shared = payloads["shared"]
        if canonical.get("engine") != "canonical":
            raise ValueError("paired control is not canonical")
        if shared.get("engine") != "shared_encoder_score_only":
            raise ValueError("paired optimized run is not shared score-only")
        if canonical["selection"] != shared["selection"]:
            raise ValueError("paired benchmark selections differ")
        left = _flatten(canonical)
        right = _flatten(shared)
        if len(left) != len(right):
            raise ValueError("paired benchmark result counts differ")
        for control, optimized in zip(left, right, strict=True):
            for key in ("case_id", "window_id", "input_sha256", "repeat"):
                if control[key] != optimized[key]:
                    raise ValueError(f"paired benchmark identity differs at {key}")
            for key in ("primary_score", "native_score"):
                if control[key] != optimized[key]:
                    raise ValueError(f"paired benchmark score differs at {key}")
            if control["primary_top_k_sha256"] != optimized["primary_top_k_sha256"]:
                raise ValueError("paired primary Top-k evidence differs")

        for name in ("canonical", "shared"):
            for relative, expected in payloads[name]["source_sha256"].items():
                if _sha256(_inside(root, relative)) != expected:
                    raise ValueError(f"{name} source SHA256 is stale: {relative}")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return False, f"invalid benchmark evidence: {exc}"
    ratio = shared["throughput_windows_per_s"] / canonical["throughput_windows_per_s"]
    return True, f"paired scores exact; measured throughput ratio {ratio:.4f}"


def _validate_public_bundle(bundle: dict[str, Any]) -> tuple[str, str]:
    if bundle.get("publication_status") != "deposited":
        return "OPEN", "reference bundle has not been deposited/configured"
    url = bundle.get("url")
    parsed = urlparse(url) if isinstance(url, str) else None
    valid = (
        parsed is not None
        and parsed.scheme == "https"
        and bool(parsed.netloc)
        and _is_sha256(bundle.get("sha256"))
    )
    return (
        ("PASS", str(url))
        if valid
        else ("FAIL", "deposited reference bundle has invalid URL or SHA256")
    )


def _validate_causal_epochs(
    root: Path,
    epochs: dict[str, Any],
    representation: RepresentationContract,
) -> tuple[str, str, dict[str, Any]]:
    verified: dict[str, Any] = {}
    missing: list[str] = []
    try:
        source = epochs["source_threshold_artifact"]
        source_path = _inside(root, source["path"])
        if not _is_sha256(source["sha256"]) or _sha256(source_path) != source["sha256"]:
            raise ValueError("source threshold artifact SHA256 mismatch")
        for detector in ("H1", "L1"):
            raw = epochs["epochs"][detector]
            if raw.get("causal") is not True:
                missing.append(detector)
                continue
            evidence = raw.get("promotion_evidence")
            if evidence is None:
                raise ValueError(f"{detector} causal epoch lacks promotion evidence")
            if raw.get("threshold_artifact_sha256") != source["sha256"]:
                raise ValueError(f"{detector} threshold provenance mismatch")
            ledger_sha256 = raw.get("calibration_ledger_sha256")
            evidence_hashes = {item.get("sha256") for item in evidence["artifacts"]}
            if not _is_sha256(ledger_sha256) or ledger_sha256 not in evidence_hashes:
                raise ValueError(f"{detector} calibration ledger is not verified evidence")
            epoch_fields = {
                key: value
                for key, value in raw.items()
                if key not in {"calibration_ledger_sha256", "promotion_evidence"}
            }
            epoch = verified_epoch_from_promotion(
                {"epoch": epoch_fields, "promotion_evidence": evidence},
                representation=representation,
                root=root,
            )
            if epoch.detector != detector:
                raise ValueError(f"{detector} epoch key/detector mismatch")
            verified[detector] = epoch
    except (ContractError, KeyError, OSError, TypeError, ValueError) as exc:
        return "FAIL", f"invalid causal epoch evidence: {exc}", {}
    if missing:
        return (
            "OPEN",
            f"causal promoted epochs missing for {', '.join(missing)}",
            verified,
        )
    return "PASS", "verified causal promotion evidence for H1 and L1", verified


def _validate_public_replay(
    root: Path,
    path: Path,
    *,
    bundle_sha256: str | None,
    replay: dict[str, Any],
) -> tuple[bool, str]:
    if not path.is_file():
        return False, "no public clean-clone replay result exists"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or payload.get("status") != "complete":
            raise ValueError("public replay artifact schema/status mismatch")
        if payload.get("mode") != "clean_clone_public_replay":
            raise ValueError("public replay did not run from the clean-clone mode")
        if payload.get("public_sources_only") is not True:
            raise ValueError("public replay used a non-public source")
        if not _is_sha256(bundle_sha256) or payload.get("reference_bundle_sha256") != bundle_sha256:
            raise ValueError("public replay bundle identity mismatch")
        if payload.get("replay_manifest_sha256") != replay["manifest_sha256"]:
            raise ValueError("public replay manifest identity mismatch")
        if payload.get("replay_entries_file_sha256") != replay["entries_file_sha256"]:
            raise ValueError("public replay corpus identity mismatch")
        coverage = payload["coverage"]
        if int(coverage["windows"]) <= 0:
            raise ValueError("public replay contains no windows")
        if coverage["drops"] != 0 or coverage["failures"]:
            raise ValueError("public replay contains drops or failures")
        exact = payload["exact_replay"]
        tolerance = float(exact["score_atol"])
        if tolerance <= 0 or tolerance > 2e-7:
            raise ValueError("public replay tolerance exceeds frozen bound")
        if float(exact["max_abs_score_delta"]) > tolerance:
            raise ValueError("public replay score equivalence failed")
        if exact["disposition_mismatches"] != 0:
            raise ValueError("public replay disposition equivalence failed")
        artifacts = payload["artifacts"]
        if not artifacts:
            raise ValueError("public replay has no supporting artifacts")
        for item in artifacts:
            artifact = _inside(root, item["path"])
            if not _is_sha256(item["sha256"]) or _sha256(artifact) != item["sha256"]:
                raise ValueError(f"public replay artifact SHA256 mismatch: {item['path']}")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return False, f"invalid public replay evidence: {exc}"
    return True, "public-only clean-clone exact replay verified"


def _validate_prospective(
    root: Path,
    path: Path,
    *,
    bundle_sha256: str | None,
    epochs: dict[str, Any],
) -> tuple[bool, str]:
    if not path.is_file():
        return False, "no locked later-epoch shadow result exists"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or payload.get("status") != "complete":
            raise ValueError("prospective artifact schema/status mismatch")
        if payload.get("mode") != "prospective_shadow" or payload.get("prefilter") != "none":
            raise ValueError("prospective artifact is not exact no-prefilter shadow mode")
        protocol = payload["locked_protocol"]
        if protocol.get("path") != PROTOCOL_PATH:
            raise ValueError("locked protocol path mismatch")
        if protocol.get("sha256") != _sha256(root / PROTOCOL_PATH):
            raise ValueError("locked protocol SHA256 mismatch")
        if not _is_sha256(bundle_sha256) or payload.get("reference_bundle_sha256") != bundle_sha256:
            raise ValueError("public reference-bundle identity mismatch")
        coverage = payload["coverage"]
        if coverage["drops"] != 0 or coverage["duplicate_identities"] != 0:
            raise ValueError("prospective result contains drops or duplicate identities")
        if coverage["failures"]:
            raise ValueError("prospective result contains failures")
        exact = payload["exact_replay"]
        tolerance = float(exact["score_atol"])
        if tolerance <= 0 or tolerance > 2e-7:
            raise ValueError("prospective score tolerance exceeds frozen bound")
        if float(exact["max_abs_score_delta"]) > tolerance:
            raise ValueError("prospective score equivalence failed")
        if exact["disposition_mismatches"] != 0:
            raise ValueError("prospective disposition equivalence failed")
        latency = payload["latency_s"]
        p50, p95, p99 = (float(latency[key]) for key in ("p50", "p95", "p99"))
        objective = float(payload["pre_registered_latency_objective_s"])
        if not all(math.isfinite(value) and value >= 0 for value in (p50, p95, p99)):
            raise ValueError("invalid prospective latency values")
        if not 0 <= p50 <= p95 <= p99 <= objective:
            raise ValueError("prospective latency objective failed")
        for detector in ("H1", "L1"):
            result = payload["detectors"][detector]
            epoch = epochs[detector]
            if result["epoch_id"] != epoch.epoch_id:
                raise ValueError(f"{detector} prospective epoch mismatch")
            if float(result["evaluation_start_gps"]) <= epoch.cutoff_gps:
                raise ValueError(f"{detector} evaluation is not after calibration cutoff")
            if float(result["evaluation_end_gps"]) <= float(result["evaluation_start_gps"]):
                raise ValueError(f"{detector} evaluation interval invalid")
            if int(result["windows"]) <= 0:
                raise ValueError(f"{detector} has no prospective windows")
        artifacts = payload["artifacts"]
        if not artifacts:
            raise ValueError("prospective result has no supporting artifacts")
        for item in artifacts:
            artifact = _inside(root, item["path"])
            if not _is_sha256(item["sha256"]) or _sha256(artifact) != item["sha256"]:
                raise ValueError(f"prospective artifact SHA256 mismatch: {item['path']}")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return False, f"invalid prospective evidence: {exc}"
    return True, "locked exact prospective shadow evidence verified"


def evaluate_gates(root: Path = ROOT) -> list[Gate]:
    root = Path(root)
    try:
        config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
        reference = json.loads(
            (root / "config/reference_artifacts.json").read_text(encoding="utf-8")
        )
        replay = json.loads(
            (root / "config/dante_light_replay_v1.json").read_text(encoding="utf-8")
        )
        epochs = json.loads(
            (root / "config/dante_light_epochs_v1.json").read_text(encoding="utf-8")
        )
        representation = RepresentationContract.from_reference_manifest(
            root / "config/reference_artifacts.json"
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [Gate("configuration", "FAIL", str(exc), ("development", "public-replay", "operational"))]

    replay_ok, replay_detail = _validate_replay(root, replay)
    benchmark_ok, benchmark_detail = _validate_benchmarks(root, replay)
    bundle = reference["reference_bundle"]
    public_status, public_detail = _validate_public_bundle(bundle)
    public_replay_path = root / "artifacts/dante_light/public_replay_validation_v1.json"
    public_replay_ok, public_replay_detail = _validate_public_replay(
        root,
        public_replay_path,
        bundle_sha256=bundle.get("sha256"),
        replay=replay,
    )
    causal_status, causal_detail, verified_epochs = _validate_causal_epochs(
        root, epochs, representation
    )
    prospective_path = root / "artifacts/dante_light/prospective_validation_v1.json"
    prospective_ok, prospective_detail = _validate_prospective(
        root,
        prospective_path,
        bundle_sha256=bundle.get("sha256"),
        epochs=verified_epochs,
    )
    docs_ok = all(
        (root / path).is_file()
        for path in ("docs/DANTE_LIGHT.md", PROTOCOL_PATH, "CLI_REFERENCE.md")
    ) and "dante-light-replay" in (root / "README.md").read_text(encoding="utf-8")

    return [
        Gate(
            "opt_in_default",
            "PASS" if config["dante_light"]["enabled"] is False else "FAIL",
            "canonical pipeline remains default and Light is disabled",
            ("development", "public-replay", "operational"),
        ),
        Gate(
            "frozen_replay",
            "PASS" if replay_ok else "FAIL",
            replay_detail,
            ("development", "public-replay", "operational"),
        ),
        Gate(
            "canonical_and_exact_benchmarks",
            "PASS" if benchmark_ok else "FAIL",
            benchmark_detail,
            ("development", "public-replay", "operational"),
        ),
        Gate(
            "user_documentation",
            "PASS" if docs_ok else "FAIL",
            "README, CLI reference, tutorial and prospective protocol are present",
            ("development", "public-replay", "operational"),
        ),
        Gate(
            "public_reference_bundle",
            public_status,
            public_detail,
            ("public-replay", "operational"),
        ),
        Gate(
            "public_clean_clone_replay",
            "PASS"
            if public_replay_ok
            else ("OPEN" if not public_replay_path.is_file() else "FAIL"),
            public_replay_detail,
            ("public-replay", "operational"),
        ),
        Gate(
            "causal_detector_epochs",
            causal_status,
            causal_detail,
            ("operational",),
        ),
        Gate(
            "prospective_validation",
            "PASS" if prospective_ok else ("OPEN" if not prospective_path.is_file() else "FAIL"),
            prospective_detail,
            ("operational",),
        ),
    ]


def verify(stage: str, root: Path = ROOT) -> tuple[bool, list[Gate]]:
    gates = evaluate_gates(root)
    required = [gate for gate in gates if stage in gate.required_for]
    return all(gate.status == "PASS" for gate in required), gates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("development", "public-replay", "operational"),
        default="development",
    )
    args = parser.parse_args()
    passed, gates = verify(args.stage)
    for gate in gates:
        marker = "required" if args.stage in gate.required_for else "informational"
        print(f"{gate.status} {gate.name} [{marker}] - {gate.detail}")
    print(f"RESULT {args.stage}: {'PASS' if passed else 'NOT_READY'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

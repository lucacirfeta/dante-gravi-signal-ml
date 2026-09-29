"""Read frozen comparative-PEM background strain without network fallback."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_o4a_common_pem_acquisition import sealed_json
from src.dante_light import o3a_o4a_common_pem_background as background_module
from src.dante_light.o3a_o4a_common_pem_background import OfficialBackgroundReader
from src.dante_light.o3a_o4a_common_pem_gate import (
    load_background_source_contract,
    parse_official_frame_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
BINDING_PATH = "config/dante_o3a_o4a_common_pem_background_input_binding_v1.json"
SPAN_CONFIG_PATH = "config/dante_o3a_o4a_common_pem_span_replay_v1.json"
SPAN_SOURCE_FILES = (
    SPAN_CONFIG_PATH,
    "src/dante_light/o3a_o4a_common_pem_span_replay.py",
    "scripts/run_dante_o3a_o4a_common_pem_span_replay.py",
)
ACQUISITION_SOURCE_FILES = (
    "config/dante_o3a_o4a_common_pem_background_acquisition_v2.json",
    "scripts/preflight_dante_o3a_o4a_common_pem_background.py",
    "scripts/run_dante_o3a_o4a_common_pem_background_acquisition.py",
    "scripts/run_dante_o3a_o4a_common_pem_background_acquisition_v2.py",
    "src/dante_light/o3a_o4a_common_pem_acquisition.py",
    "src/dante_light/o3a_o4a_common_pem_acquisition_v2.py",
    "src/dante_light/o3a_o4a_common_pem_background.py",
    "src/dante_light/o3a_o4a_common_pem_gate.py",
)


class VerifiedSpanReader:
    """Bind one target to its sealed four-hour span and published frames."""

    def __init__(
        self,
        span_run_dir: Path,
        acquisition_run_dir: Path,
        *,
        run: str,
        detector: str,
        target_gps: int,
    ) -> None:
        if run not in ("O3a", "O4a") or detector not in ("H1", "L1"):
            raise ContractError("common PEM background target identity invalid")
        if type(target_gps) is not int:
            raise ContractError("common PEM background target GPS invalid")
        self.span_dir = span_run_dir.resolve(strict=True)
        self.acquisition_dir = acquisition_run_dir.resolve(strict=True)
        if (
            self.span_dir.parent.name != "background_span_replay"
            or self.acquisition_dir.parent.name != "background_acquisition"
            or self.span_dir.parent.parent != self.acquisition_dir.parent.parent
            or self.span_dir.parent.parent.name != "o3a_o4a_common_pem_v1"
            or any(
                (directory / name).exists()
                for directory in (self.span_dir, self.acquisition_dir)
                for name in ("failure.json", "controller.lock")
            )
        ):
            raise ContractError("common PEM background source root/health changed")
        binding = json.loads((ROOT / BINDING_PATH).read_text(encoding="utf-8"))
        plan = sealed_json(self.span_dir / "plan.json")
        summary = sealed_json(self.span_dir / "summary.json")
        acquisition_plan = sealed_json(self.acquisition_dir / "plan.json")
        acquisition_summary = sealed_json(self.acquisition_dir / "summary.json")
        if (
            binding.get("schema_version") != 1
            or binding.get("contract_id")
            != "dante-o3a-o4a-common-pem-background-input-binding-v1"
            or binding.get("status") != "FROZEN_LOCAL_STRAIN_INPUT_ONLY_NO_PEM_OUTCOMES"
            or binding.get("transport_policy")
            != "VERIFIED_OFFICIAL_FRAME_BYTES_LOCAL_ONLY_NO_DOWNLOAD"
            or binding.get("scientific_boundary")
            != {
                "background_strain_samples_only": True,
                "five_channel_null_opened": False,
                "paired_pem_outcomes_opened": False,
                "global_significance_claim": False,
            }
            or self.span_dir.name != f"background_spans_{plan['receipt_digest']}"
            or plan["receipt_digest"] != binding["span_run_key"]
            or summary["receipt_digest"] != binding["span_summary_digest"]
            or summary.get("status") != "PASS_BACKGROUND_SPAN_REPLAY_COMPLETE_ONLY"
            or summary.get("plan_digest") != plan["receipt_digest"]
            or summary.get("span_counts") != binding["expected_spans"]
            or plan.get("status") != "FROZEN_BACKGROUND_SPAN_REPLAY_NO_PEM_OUTCOMES"
            or plan.get("contract_digest")
            != canonical_json_sha256(
                json.loads((ROOT / SPAN_CONFIG_PATH).read_text(encoding="utf-8"))
            )
            or plan.get("source_sha256")
            != {path: sha256_file(ROOT / path) for path in SPAN_SOURCE_FILES}
            or self.acquisition_dir.name
            != f"background_acquisition_v2_{acquisition_plan['receipt_digest']}"
            or acquisition_plan["receipt_digest"] != binding["acquisition_run_key"]
            or acquisition_plan.get("source_sha256")
            != {path: sha256_file(ROOT / path) for path in ACQUISITION_SOURCE_FILES}
            or acquisition_summary["receipt_digest"]
            != binding["acquisition_summary_digest"]
            or acquisition_summary.get("status")
            != "PASS_ACQUIRED_BACKGROUND_FRAME_BYTES_V2_ONLY"
            or acquisition_summary.get("plan_digest")
            != acquisition_plan["receipt_digest"]
            or plan.get("parent_plan_digest") != acquisition_plan["receipt_digest"]
            or plan.get("parent_summary_digest")
            != acquisition_summary["receipt_digest"]
            or any(
                plan["spans"][label] != acquisition_plan["runs"][label]["spans"]
                or len(plan["spans"][label]) != binding["expected_spans"][label]
                for label in ("O3a", "O4a")
            )
        ):
            raise ContractError("common PEM background parent seal changed")
        matching = [
            row
            for row in plan["spans"][run]
            if row["detector"] == detector and row["gps_start"] == target_gps
        ]
        if len(matching) != 1:
            raise ContractError("common PEM background target span missing/duplicated")
        self.span = matching[0]
        self.run = run
        self.detector = detector
        self.target_gps = target_gps
        self.receipt_path = (
            self.span_dir / "receipts" / f"{run}_{detector}_{target_gps}.json"
        )
        background = load_background_source_contract(root=ROOT)
        source = background["sources"][run]
        manifest_bytes = (
            self.acquisition_dir / f"{run}_strain_hdf_md5.txt"
        ).read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != source["manifest_sha256"]:
            raise ContractError("common PEM background manifest bytes changed")
        manifest = parse_official_frame_manifest(
            manifest_bytes,
            release=source["release"],
            frame_duration_s=source["frame_duration_s"],
        )
        self.reader = OfficialBackgroundReader(
            source=source,
            manifest=manifest,
            cache_dir=self.acquisition_dir / "frames",
        )

    def __call__(self, detector: str, start: int, end: int) -> Any:
        if (
            detector != self.detector
            or type(start) is not int
            or type(end) is not int
            or [start, end] != self.span["interval_gps"]
        ):
            raise ContractError("common PEM background interval is not frozen")
        receipt = sealed_json(self.receipt_path)
        if (
            receipt.get("status") != "PASS_BACKGROUND_SPAN_REPLAY_ONLY"
            or receipt.get("run") != self.run
            or receipt.get("target_gps") != self.target_gps
            or receipt.get("background", {}).get("detector") != detector
            or receipt.get("background", {}).get("interval_gps") != [start, end]
        ):
            raise ContractError("common PEM background span receipt changed")
        with patch.object(
            background_module,
            "_download_official",
            side_effect=ContractError("common PEM verified background frame missing"),
        ):
            series = self.reader(detector, start, end)
        if self.reader.receipts.pop() != receipt["background"]:
            raise ContractError("common PEM background numerical replay changed")
        return series

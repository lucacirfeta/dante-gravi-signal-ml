"""Read only the sealed native auxiliary samples for one comparative PEM target.

This is a transport adapter: resampling and coherence remain in the unchanged
historical PEM core. A missing or altered local series never triggers NDS2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_o4a_common_pem_acquisition import sealed_json
from src.dante_light.o3a_o4a_common_pem_aux_samples import data_path, verify_series

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = "config/dante_o3a_o4a_common_pem_aux_samples_v1.json"
BINDING_PATH = "config/dante_o3a_o4a_common_pem_aux_input_binding_v1.json"
SOURCE_FILES = (
    CONFIG_PATH,
    "src/dante_light/o3a_o4a_common_pem_aux_samples.py",
    "scripts/run_dante_o3a_o4a_common_pem_aux_samples.py",
)


class VerifiedAuxiliaryReader:
    """Expose exactly one target's event/background NDS2 intervals from disk."""

    def __init__(
        self,
        run_dir: Path,
        *,
        run: str,
        detector: str,
        target_gps: int,
        channels: list[str],
    ) -> None:
        if run not in ("O3a", "O4a") or detector not in ("H1", "L1"):
            raise ContractError("common PEM auxiliary target identity invalid")
        if type(target_gps) is not int or len(channels) != 5 or len(set(channels)) != 5:
            raise ContractError("common PEM auxiliary target/channel identity invalid")
        if any(not name.startswith(f"{detector}:") for name in channels):
            raise ContractError("common PEM auxiliary detector channel changed")
        self.run_dir = run_dir.resolve(strict=True)
        if (
            self.run_dir.parent.name != "aux_samples"
            or self.run_dir.parent.parent.name != "o3a_o4a_common_pem_v1"
        ):
            raise ContractError("common PEM auxiliary source root changed")
        if (self.run_dir / "failure.json").exists() or (
            self.run_dir / "controller.lock"
        ).exists():
            raise ContractError("common PEM auxiliary source active or failed")
        if list(self.run_dir.rglob("*.partial*")):
            raise ContractError("common PEM auxiliary source contains partial files")
        plan = sealed_json(self.run_dir / "plan.json")
        summary = sealed_json(self.run_dir / "summary.json")
        config = json.loads((ROOT / CONFIG_PATH).read_text(encoding="utf-8"))
        binding = json.loads((ROOT / BINDING_PATH).read_text(encoding="utf-8"))
        if (
            binding.get("schema_version") != 1
            or binding.get("contract_id")
            != "dante-o3a-o4a-common-pem-aux-input-binding-v1"
            or binding.get("status") != "FROZEN_TRANSPORT_INPUT_ONLY_NO_PEM_OUTCOMES"
            or binding.get("transport_policy")
            != "VERIFIED_NATIVE_FLOAT32_LOCAL_ONLY_NO_NDS2_FALLBACK"
            or binding.get("scientific_boundary")
            != {
                "historical_coherence_and_null_core_unchanged": True,
                "five_channel_null_opened": False,
                "paired_pem_outcomes_opened": False,
                "global_significance_claim": False,
            }
            or self.run_dir.name != f"aux_samples_{plan['receipt_digest']}"
            or plan["receipt_digest"] != binding["parent_aux_samples_run_key"]
            or summary["receipt_digest"] != binding["parent_aux_samples_summary_digest"]
            or plan.get("status") != "FROZEN_AUX_NATIVE_SAMPLE_PLAN_ONLY"
            or plan.get("contract_digest") != canonical_json_sha256(config)
            or plan.get("parent_plan_digest") != config["parent_availability_run_key"]
            or plan.get("parent_plan_digest")
            != binding["parent_aux_availability_run_key"]
            or plan.get("parent_summary_digest")
            != config["parent_availability_summary_digest"]
            or plan.get("source_sha256")
            != {path: sha256_file(ROOT / path) for path in SOURCE_FILES}
            or summary.get("status") != "PASS_AUX_NATIVE_SAMPLES_COMPLETE_ONLY"
            or summary.get("plan_digest") != plan["receipt_digest"]
            or summary.get("series_count") != len(plan["series"])
            or summary.get("expected_sample_bytes") != plan["expected_sample_bytes"]
            or len(list((self.run_dir / "receipts").glob("*.json")))
            != len(plan["series"])
            or len(list((self.run_dir / "data").glob("*.npy"))) != len(plan["series"])
        ):
            raise ContractError("common PEM auxiliary sample parent seal changed")
        self.host = plan["nds_host"]
        self.chunk_seconds = int(plan["execution"]["chunk_seconds"])
        self._specs: dict[tuple[str, int, int], dict[str, Any]] = {}
        for spec in plan["series"]:
            if spec["run"] != run or spec["detector"] != detector:
                continue
            left, right = spec["interval_gps"]
            roles = {
                use["role"] for use in spec["uses"] if use["target_gps"] == target_gps
            }
            if not roles:
                continue
            if spec["channel"] not in channels or not roles <= {
                "event",
                "background",
            }:
                raise ContractError("common PEM auxiliary target use changed")
            key = (spec["channel"], left, right)
            if key in self._specs:
                raise ContractError("common PEM auxiliary target interval duplicated")
            self._specs[key] = spec
        uses = [
            (spec["channel"], use["role"])
            for spec in self._specs.values()
            for use in spec["uses"]
            if use["target_gps"] == target_gps
        ]
        if len(uses) != len(set(uses)) or set(uses) != {
            (name, role) for name in channels for role in ("event", "background")
        }:
            raise ContractError("common PEM auxiliary target intervals incomplete")

    def fetch(self, channel: str, *, start: int, end: int, host: str) -> Any:
        """Match the historical ``TimeSeries.fetch`` signature, without network."""
        if (
            type(start) is not int
            or type(end) is not int
            or end <= start
            or host != self.host
        ):
            raise ContractError("common PEM auxiliary source request changed")
        spec = self._specs.get((channel, start, end))
        if spec is None:
            raise ContractError("common PEM auxiliary interval is not frozen")
        path = data_path(self.run_dir, spec)
        receipt = sealed_json(self.run_dir / "receipts" / f"{spec['key']}.json")
        verify_series(
            spec, receipt, run_dir=self.run_dir, chunk_seconds=self.chunk_seconds
        )
        data = np.load(path, mmap_mode="r", allow_pickle=False)
        from gwpy.timeseries import TimeSeries

        return TimeSeries(
            data,
            t0=start,
            sample_rate=spec["sample_rate_hz"],
            unit=receipt["unit"],
            name=channel,
        )


def verify_target_bindings(
    *, auxiliary_run_dir: Path, availability_run_dir: Path
) -> int:
    """Check all frozen target/role/channel bindings without reading PEM outcomes."""
    binding = json.loads((ROOT / BINDING_PATH).read_text(encoding="utf-8"))
    availability = sealed_json(availability_run_dir / "plan.json")
    summary = sealed_json(availability_run_dir / "summary.json")
    requirements = availability.get("requirements")
    if (
        availability["receipt_digest"] != binding["parent_aux_availability_run_key"]
        or summary.get("status") != "PASS_AUX_METADATA_COVERAGE_COMPLETE_ONLY"
        or summary.get("plan_digest") != availability["receipt_digest"]
        or summary.get("receipt_count") != binding["target_context_count"]
        or not isinstance(requirements, list)
        or len(requirements) != binding["target_context_count"]
    ):
        raise ContractError("common PEM auxiliary target population changed")
    identities: set[tuple[str, str, int]] = set()
    for row in requirements:
        identity = (row["run"], row["detector"], row["target_gps"])
        if identity in identities:
            raise ContractError("common PEM auxiliary target duplicated")
        identities.add(identity)
        reader = VerifiedAuxiliaryReader(
            auxiliary_run_dir,
            run=row["run"],
            detector=row["detector"],
            target_gps=row["target_gps"],
            channels=row["channels"],
        )
        for role in ("event", "background"):
            left, right = row[f"{role}_interval_gps"]
            if any(
                (channel, left, right) not in reader._specs
                for channel in row["channels"]
            ):
                raise ContractError("common PEM auxiliary interval mapping changed")
    return len(identities)

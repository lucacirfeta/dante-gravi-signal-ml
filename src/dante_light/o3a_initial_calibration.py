"""Outcome-blind O3a initial-calibration selector.

The module freezes an exact preselection plan from public DQ geometry only.
Raw acceptance is specified but deliberately not executed here.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_contract import ROOT
from src.dante_light.o3a_population_geometry import load_identity_universes
from src.dante_light.o3a_scale_adequacy import load_stage_contract


CONTRACT_REL = "config/dante_o3a_initial_calibration_selector_v1.json"
PLAN_REL = "config/dante_o3a_initial_calibration_plan_v1.json"
IMPLEMENTATION_REL = "src/dante_light/o3a_initial_calibration.py"
ENTRYPOINT_REL = "scripts/freeze_dante_o3a_initial_calibration.py"
SCHEMA_VERSION = 1
BLOCK_LENGTH = 17
STRATUM_COUNT = 295
TARGET_ROWS = 5_000


@dataclass(frozen=True)
class ProposalBlock:
    detector: str
    dq_segment_index: int
    starts: tuple[int, ...]

    @property
    def first(self) -> int:
        return self.starts[0]

    @property
    def last(self) -> int:
        return self.starts[-1]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def build_selector_contract(*, root: Path = ROOT) -> dict[str, Any]:
    stage = load_stage_contract(root=root)
    universes = load_identity_universes(root=root)
    initial = stage["author_decisions"]["initial_calibration_and_scan"]
    statistics = stage["author_decisions"]["native_threshold_statistics"]
    if initial["calibration_selection"] != (
        "OUTCOME_BLIND_HASH_STRATIFIED_COMPLETE_RUN_BLOCKS"
    ):
        raise ContractError("O3a initial-calibration selection contract changed")
    if int(statistics["block_length_rows"]) != BLOCK_LENGTH:
        raise ContractError("O3a calibration block length changed")
    if int(initial["calibration_rows_per_detector"]) != TARGET_ROWS:
        raise ContractError("O3a initial-calibration row target changed")

    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "AUTHOR_APPROVED_O3A_INITIAL_CALIBRATION_SELECTOR",
        "approval_date": "2026-09-19",
        "run": "O3A",
        "detectors": list(universes["detectors"]),
        "parents": {
            "stage_contract": {
                "path": "config/dante_o3a_native_v1_stage_contract.json",
                "sha256": _sha256_file(
                    root / "config/dante_o3a_native_v1_stage_contract.json"
                ),
                "contract_digest": stage["contract_digest"],
            },
            "identity_universes": {
                "path": "config/dante_o3a_native_v1_identity_universes.json",
                "sha256": _sha256_file(
                    root / "config/dante_o3a_native_v1_identity_universes.json"
                ),
                "manifest_digest": universes["manifest_digest"],
            },
        },
        "implementation": {
            "path": IMPLEMENTATION_REL,
            "sha256": _sha256_file(root / IMPLEMENTATION_REL),
            "entrypoint_path": ENTRYPOINT_REL,
            "entrypoint_sha256": _sha256_file(root / ENTRYPOINT_REL),
        },
        "selection": {
            "source_role": "initial_calibration_proposal_universe",
            "window_duration_s": int(initial["analysis_duration_s"]),
            "window_stride_s": int(initial["window_stride_s"]),
            "complete_symmetric_context_s": int(initial["whitening_pad_s"]),
            "candidate_block_length_rows": BLOCK_LENGTH,
            "candidate_blocks_may_cross_dq_segments": False,
            "candidate_blocks_are_non_overlapping_within_segment": True,
            "chronological_stratum_count": STRATUM_COUNT,
            "stratum_boundaries": (
                "for stratum i over N chronological candidate blocks: "
                "[floor(i*N/295), floor((i+1)*N/295))"
            ),
            "priority_encoding": (
                "ASCII selector_contract_digest|detector|stratum_index|"
                "comma-separated-integer-window-starts"
            ),
            "priority_hash": "SHA256",
            "priority_order": "ascending_digest_then_first_gps_start",
            "provisional_block_rank_per_stratum": 0,
            "accepted_blocks_required_per_detector": STRATUM_COUNT,
            "planned_rows_per_detector": TARGET_ROWS,
            "planned_rows_before_truncation": STRATUM_COUNT * BLOCK_LENGTH,
            "output_order": "detector_then_stratum_then_window_start",
            "point_estimate_rows": TARGET_ROWS,
            "bootstrap_complete_blocks": TARGET_ROWS // BLOCK_LENGTH,
            "bootstrap_rows": (TARGET_ROWS // BLOCK_LENGTH) * BLOCK_LENGTH,
            "point_only_tail_rows": TARGET_ROWS % BLOCK_LENGTH,
        },
        "raw_acceptance": {
            "executed_by_this_freeze": False,
            "block_atomic": True,
            "required": [
                "exact raw coverage for the complete symmetric context",
                "finite raw samples at the canonical sample rate",
                "finite canonical whitening output before analysis crop",
                "finite canonical Q-transform image",
                "finite frozen-DINOv2 patch tokens",
                "finite primary O3b-K275 score",
            ],
            "score_value_or_class_may_affect_acceptance": False,
            "excess_power_veto_applied": False,
            "failure_fallback": (
                "try the next ascending-hash candidate in the same stratum"
            ),
            "cross_stratum_reallocation_allowed": False,
            "stratum_exhaustion_action": "FAIL_CLOSED",
        },
        "execution_boundary": {
            "public_geometry_only": True,
            "preselection_plan_allowed": True,
            "strain_access_allowed": False,
            "raw_acceptance_execution_allowed": False,
            "scoring_allowed": False,
            "threshold_fitting_allowed": False,
            "outcomes_read": False,
        },
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_selector_contract(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    expected = build_selector_contract(root=root)
    if dict(value) != expected:
        raise ContractError("O3a initial-calibration selector contract mismatch")
    return dict(value)


def load_selector_contract(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / CONTRACT_REL
    if not path.is_file():
        raise ContractError("O3a initial-calibration selector contract is absent")
    return validate_selector_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def _candidate_blocks(
    universes: Mapping[str, Any], detector: str
) -> list[ProposalBlock]:
    role = universes["roles"]["initial_calibration_proposal_universe"]
    stride = int(role["stride_s"])
    blocks: list[ProposalBlock] = []
    for item in role["ranges_by_detector"][detector]:
        first = int(item["first_gps_start"])
        count = int(item["count"])
        starts = tuple(first + offset * stride for offset in range(count))
        for offset in range(0, len(starts), BLOCK_LENGTH):
            chunk = starts[offset : offset + BLOCK_LENGTH]
            if len(chunk) == BLOCK_LENGTH:
                blocks.append(
                    ProposalBlock(
                        detector=detector,
                        dq_segment_index=int(item["dq_segment_index"]),
                        starts=chunk,
                    )
                )
    blocks.sort(key=lambda block: (block.first, block.last, block.dq_segment_index))
    return blocks


def _strata(
    blocks: Sequence[ProposalBlock], count: int = STRATUM_COUNT
) -> list[list[ProposalBlock]]:
    if len(blocks) < count:
        raise ContractError(
            f"only {len(blocks)} candidate blocks are available for {count} strata"
        )
    result: list[list[ProposalBlock]] = []
    for index in range(count):
        left = index * len(blocks) // count
        right = (index + 1) * len(blocks) // count
        stratum = list(blocks[left:right])
        if not stratum:
            raise ContractError(f"O3a calibration stratum {index} is empty")
        result.append(stratum)
    if sum(len(stratum) for stratum in result) != len(blocks):
        raise ContractError("O3a calibration strata do not partition the pool")
    return result


def _priority(
    *, contract_digest: str, detector: str, stratum_index: int, block: ProposalBlock
) -> str:
    starts = ",".join(str(value) for value in block.starts)
    value = f"{contract_digest}|{detector}|{stratum_index}|{starts}"
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _ranked_strata(
    *, contract: Mapping[str, Any], universes: Mapping[str, Any], detector: str
) -> list[list[tuple[str, ProposalBlock]]]:
    result: list[list[tuple[str, ProposalBlock]]] = []
    for stratum_index, blocks in enumerate(_strata(_candidate_blocks(universes, detector))):
        ranked = [
            (
                _priority(
                    contract_digest=str(contract["contract_digest"]),
                    detector=detector,
                    stratum_index=stratum_index,
                    block=block,
                ),
                block,
            )
            for block in blocks
        ]
        ranked.sort(key=lambda item: (item[0], item[1].first))
        result.append(ranked)
    return result


def iter_planned_identities(
    value: Mapping[str, Any], detector: str | None = None
) -> Iterator[tuple[str, int]]:
    detectors: Iterable[str] = [detector] if detector else value["detectors"]
    for current in detectors:
        for block in value["detector_plans"][current]["selected_blocks"]:
            first = int(block["first_gps_start"])
            count = int(block["output_row_count"])
            stride = int(value["selection"]["window_stride_s"])
            for offset in range(count):
                yield current, first + offset * stride


def _priority_stream_digest(
    detector: str, ranked: Sequence[Sequence[tuple[str, ProposalBlock]]]
) -> str:
    digest = hashlib.sha256()
    for stratum_index, candidates in enumerate(ranked):
        for rank, (priority, block) in enumerate(candidates):
            digest.update(
                (
                    f"{detector}|{stratum_index}|{rank}|{priority}|"
                    f"{block.first}|{block.last}|{block.dq_segment_index}\n"
                ).encode("ascii")
            )
    return digest.hexdigest()


def _identity_stream_digest(rows: Iterable[tuple[str, int]]) -> str:
    digest = hashlib.sha256()
    for detector, gps in rows:
        digest.update(f"O3A|{detector}|{gps}|32\n".encode("ascii"))
    return digest.hexdigest()


def build_initial_calibration_plan(*, root: Path = ROOT) -> dict[str, Any]:
    contract = load_selector_contract(root=root)
    universes = load_identity_universes(root=root)
    detector_plans: dict[str, Any] = {}
    for detector in contract["detectors"]:
        ranked = _ranked_strata(
            contract=contract,
            universes=universes,
            detector=detector,
        )
        selected_blocks = []
        remaining_rows = TARGET_ROWS
        for stratum_index, candidates in enumerate(ranked):
            priority, block = candidates[0]
            output_rows = min(BLOCK_LENGTH, remaining_rows)
            selected_blocks.append(
                {
                    "stratum_index": stratum_index,
                    "stratum_candidate_count": len(candidates),
                    "candidate_rank_in_stratum": 0,
                    "selection_priority_sha256": priority,
                    "dq_segment_index": block.dq_segment_index,
                    "first_gps_start": block.first,
                    "last_gps_start": block.last,
                    "candidate_block_row_count": BLOCK_LENGTH,
                    "output_row_count": output_rows,
                }
            )
            remaining_rows -= output_rows
        if remaining_rows != 0:
            raise ContractError(
                f"O3a initial-calibration {detector} plan is incomplete"
            )
        block_count = sum(len(candidates) for candidates in ranked)
        stratum_sizes = [len(candidates) for candidates in ranked]
        detector_plans[detector] = {
            "candidate_block_count": block_count,
            "candidate_window_count": block_count * BLOCK_LENGTH,
            "discarded_segment_tail_window_count": (
                int(
                    universes["roles"][
                        "initial_calibration_proposal_universe"
                    ]["counts_by_detector"][detector]
                )
                - block_count * BLOCK_LENGTH
            ),
            "stratum_count": len(ranked),
            "minimum_stratum_candidate_count": min(stratum_sizes),
            "maximum_stratum_candidate_count": max(stratum_sizes),
            "candidate_priority_stream_sha256": _priority_stream_digest(
                detector, ranked
            ),
            "selected_blocks": selected_blocks,
            "selected_candidate_blocks": len(selected_blocks),
            "planned_rows": TARGET_ROWS,
            "bootstrap_rows": (TARGET_ROWS // BLOCK_LENGTH) * BLOCK_LENGTH,
            "point_only_tail_rows": TARGET_ROWS % BLOCK_LENGTH,
        }

    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_OUTCOME_BLIND_O3A_INITIAL_CALIBRATION_PLAN",
        "run": "O3A",
        "detectors": list(contract["detectors"]),
        "selector_contract": {
            "path": CONTRACT_REL,
            "sha256": _sha256_file(root / CONTRACT_REL),
            "contract_digest": contract["contract_digest"],
        },
        "identity_universes": contract["parents"]["identity_universes"],
        "selection": contract["selection"],
        "raw_acceptance": contract["raw_acceptance"],
        "detector_plans": detector_plans,
        "strain_data_accessed": False,
        "outcome_data_accessed": False,
        "raw_acceptance_executed": False,
    }
    ordered_stream_digest = _identity_stream_digest(
        iter_planned_identities(body)
    )
    complete_body = {
        **body,
        "ordered_planned_identity_stream_sha256": ordered_stream_digest,
    }
    return {
        **complete_body,
        "plan_digest": canonical_json_sha256(complete_body),
    }


def validate_initial_calibration_plan(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    expected = build_initial_calibration_plan(root=root)
    if dict(value) != expected:
        raise ContractError("O3a initial-calibration plan mismatch")
    return dict(value)


def load_initial_calibration_plan(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / PLAN_REL
    if not path.is_file():
        raise ContractError("O3a initial-calibration plan is absent")
    return validate_initial_calibration_plan(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def write_initial_calibration_freeze(*, root: Path = ROOT) -> dict[str, Any]:
    contract = build_selector_contract(root=root)
    _write_json(root / CONTRACT_REL, contract)
    plan = build_initial_calibration_plan(root=root)
    _write_json(root / PLAN_REL, plan)
    return plan


__all__ = [
    "CONTRACT_REL",
    "PLAN_REL",
    "build_initial_calibration_plan",
    "build_selector_contract",
    "iter_planned_identities",
    "load_initial_calibration_plan",
    "load_selector_contract",
    "validate_initial_calibration_plan",
    "validate_selector_contract",
    "write_initial_calibration_freeze",
]

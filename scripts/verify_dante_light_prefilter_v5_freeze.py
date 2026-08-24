#!/usr/bin/env python3
"""Fail-closed verifier for the public DANTE-Light v5 freeze."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v5_power import analyze_power, load_power_config
from src.dante_light.prefilter_v5_protocol import load_protocol, sha256_path
from src.dante_light.prefilter_v5_seal import validate_identity_manifest, verify_unopened_seal


def _reference(reference: dict[str, str]) -> Path:
    path = ROOT / reference["path"]
    candidates = {sha256_path(path)} if path.is_file() else set()
    try:
        candidates.add(hashlib.sha256(subprocess.check_output(
            ["git", "show", f"HEAD:{reference['path']}"], cwd=ROOT,
            stderr=subprocess.DEVNULL,
        )).hexdigest())
    except (OSError, subprocess.SubprocessError):
        pass
    if reference["sha256"] not in candidates:
        raise ContractError(f"v5 reference mismatch: {reference['path']}")
    return path


def verify() -> dict[str, object]:
    config, design = load_power_config(); recomputed = analyze_power(config, design)
    power_path = ROOT / "artifacts/dante_light/prefilter_l4_v5_design/confirmation_power_analysis_v5.json"
    if json.loads(power_path.read_text(encoding="utf-8")) != recomputed:
        raise ContractError("v5 power artifact does not recompute exactly")
    protocol = load_protocol(ROOT / "config/dante_light_prefilter_protocol_v5.json", root=ROOT)
    header = json.loads((ROOT / "config/dante_light_prefilter_splits_v5.json").read_text(encoding="utf-8"))
    for reference in header["source_references"]:
        _reference(reference)
    _reference(header["protocol_reference"]); _reference(header["selection_code_reference"]); entries_path = _reference(header["entries_reference"])
    if header["manifest_digest"] != canonical_json_sha256({key: value for key, value in header.items() if key != "manifest_digest"}):
        raise ContractError("v5 public split header digest mismatch")
    rows = [json.loads(line) for line in entries_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    complete = dict(header); complete.pop("entries_reference"); complete["rows"] = rows; complete["manifest_digest"] = canonical_json_sha256({key: value for key, value in complete.items() if key != "manifest_digest"})
    validate_identity_manifest(complete)
    seal = json.loads((ROOT / "config/dante_light_prefilter_v5_confirmation_seal.json").read_text(encoding="utf-8"))
    for reference in seal["code_references"].values():
        _reference(reference)
    _reference(seal["public_split_header_reference"]); _reference(seal["public_split_entries_reference"]); trial_path = _reference(seal["injection_trials_reference"])
    access_path = ROOT / "config/dante_light_prefilter_v5_confirmation_access.jsonl"; access = access_path.read_bytes() if access_path.exists() else b""
    verify_unopened_seal(complete, seal, access_log_bytes=access)
    if set(seal["protected_endpoints"]) != set(design["confirmation"]["protected_endpoints"]):
        raise ContractError("v5 seal endpoint scope differs from the protocol")
    counts = Counter((row["partition"], row["role"], row["detector"], row["morphology"]) for row in rows)
    o4a_blocks = defaultdict(set); background_per_block = Counter(); known_blocks = defaultdict(set)
    for row in rows:
        block = int(float(row["window"]["gps_start"]) // int(design["signal"]["gps_block_duration_s"]))
        if row["window"]["run"] == "O4A":
            o4a_blocks[(row["detector"], row["partition"])].add(block)
            if row["role"] == "background":
                background_per_block[(row["detector"], row["partition"], block)] += 1
        elif row["role"] == "known_glitch":
            known_blocks[(row["detector"], row["partition"])].add(block)
    blocks = design["partition_contract"]["blocks_per_detector"]; per_block = design["partition_contract"]["background_windows_per_block"]; protected = design["partition_contract"]["protected_per_detector_stratum"]
    for detector in design["signal"]["detectors"]:
        for partition in ("training", "development", "confirmation"):
            if sum(value for (part, role, det, _), value in counts.items() if part == partition and role == "background" and det == detector) != int(blocks[partition]) * int(per_block[partition]):
                raise ContractError(f"v5 background count changed for {detector}/{partition}")
            if len(o4a_blocks[(detector, partition)]) != int(blocks[partition]):
                raise ContractError(f"v5 O4a block count changed for {detector}/{partition}")
            if {value for (det, part, _), value in background_per_block.items() if det == detector and part == partition} != {int(per_block[partition])}:
                raise ContractError(f"v5 windows-per-background-block changed for {detector}/{partition}")
        for partition in ("development", "confirmation"):
            if counts[(partition, "robust_candidate", detector, "DANTE_ROBUST")] != int(protected["robust_candidate"][partition]):
                raise ContractError("v5 ROBUST count changed")
            for morphology in design["partition_contract"]["known_glitch_morphologies"]:
                if counts[(partition, "known_glitch", detector, morphology)] != int(protected["known_glitch"][partition]):
                    raise ContractError("v5 known-glitch count changed")
            if len(known_blocks[(detector, partition)]) != len(design["partition_contract"]["known_glitch_morphologies"]) * int(protected["known_glitch"][partition]):
                raise ContractError("v5 known-glitch detector/GPS blocks are reused")
            systems = [*design["waveforms"]["legacy_comparability"]["systems"], design["waveforms"]["aligned_tidal_nsbh_stress"]["system"]]
            for system in systems:
                if counts[(partition, "injection", detector, system)] != int(protected["injection"][partition]):
                    raise ContractError("v5 injection count changed")
    trials = [json.loads(line) for line in trial_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(trials) != 2 * 2 * 4 * 90 or any(trial["trial_digest"] != canonical_json_sha256({key: value for key, value in trial.items() if key != "trial_digest"}) for trial in trials):
        raise ContractError("v5 injection trial ledger mismatch")
    stress = [trial for trial in trials if trial["population"] == "aligned_tidal_nsbh_stress"]
    if any(trial["approximant"] != "IMRPhenomNSBH" or trial["spin_2z"] != 0.0 for trial in stress):
        raise ContractError("v5 IMRPhenomNSBH chi_NS contract changed")
    robust_families = Counter((row["detector"], row["partition"], row["stratum"]["taxonomy_family"]) for row in rows if row["role"] == "robust_candidate")
    if set(family for _, _, family in robust_families) != {"Family_01"}:
        raise ContractError("v5 ROBUST family-scope disclosure changed")
    subprocess.run(["git", "cat-file", "-e", f"{seal['freeze_commit']}^{{commit}}"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if any(token in json.dumps(rows).lower() for token in ('"score"', '"feature"', '"snr"', '"outcome"', '"cost_s"')):
        raise ContractError("outcome-bearing field leaked into v5 identities")
    return {"status": "PASS_IDENTITY_ONLY_NOT_OPENED", "rows": len(rows), "trials": len(trials), "confirmation_access_log_sha256": hashlib.sha256(access).hexdigest(), "protocol_digest": protocol["protocol_digest"]}


if __name__ == "__main__":
    try:
        print(json.dumps(verify(), indent=2, sort_keys=True))
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(2)

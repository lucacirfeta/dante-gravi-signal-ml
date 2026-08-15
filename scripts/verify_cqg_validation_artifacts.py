"""Fail-closed verifier for the additional CQG validation artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "production" / "aggregated"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_complete(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != "complete":
        raise RuntimeError(f"{path}: status is not complete")
    return value


def assert_hash(path_text: str, expected: str) -> Path:
    path = ROOT / path_text
    observed = sha256(path)
    if observed != expected:
        raise RuntimeError(f"hash mismatch {path}: {observed} != {expected}")
    return path


def verify_domain(*, pilot: bool, deep: bool) -> None:
    from scripts import validate_cross_run_domain_shift as module

    suffix = "_pilot" if pilot else ""
    path = OUT / f"cqg_cross_run_domain_shift{suffix}.json"
    value = load_complete(path)
    n = int(value["n_per_run_detector"])
    seed = int(next(iter(value["detectors"].values()))["seed"])
    for item in value["token_caches"]:
        cache = assert_hash(item["path"], item["sha256"])
        identity = item["identity"]
        if not module.cache_identity_is_compatible(
            identity,
            identity["run"],
            identity["detector"],
            n,
            seed,
        ):
            raise RuntimeError(f"domain cache identity mismatch: {cache}")
        with np.load(cache, allow_pickle=False) as encoded:
            cached_identity = json.loads(str(encoded["identity_json"].item()))
            gps, tokens = encoded["gps"], encoded["tokens"]
        if (
            cached_identity != identity
            or gps.shape != (n,)
            or tokens.shape != (n, 1369, 384)
            or len(np.unique(gps)) != n
            or not np.all(np.isfinite(tokens))
        ):
            raise RuntimeError(f"invalid domain token cache: {cache}")
    if deep:
        for detector, expected in value["detectors"].items():
            observed = module.analyse_detector(detector, n, seed, 8)
            if observed != expected:
                raise RuntimeError(
                    f"domain metric reconstruction mismatch: {detector}"
                )
    print(f"PASS domain {'pilot' if pilot else 'final'}")


def verify_known(*, pilot: bool, deep: bool) -> None:
    from scripts import validate_known_glitch_controls as module

    suffix = "_pilot" if pilot else ""
    path = OUT / f"cqg_known_glitch_controls{suffix}.json"
    value = load_complete(path)
    seed = int(value["selection"]["seed"])
    n_per_class = int(value["selection"]["n_per_class"])
    for detector, record in value["detectors"].items():
        for cache in record["token_caches"].values():
            assert_hash(cache["path"], cache["sha256"])
        assert_hash(record["catalog"]["path"], record["catalog"]["sha256"])
        all_clean = np.asarray(
            record["clean_gps"]["train"] + record["clean_gps"]["held_out"]
        )
        query_gps = np.asarray(
            [event["event_time"] for event in record["manifest"]]
        )
        if np.min(np.abs(query_gps[:, None] - all_clean[None, :])) < module.GUARD_S:
            raise RuntimeError(f"known-control GPS leakage: {detector}")
        if module.manifest_digest(record["manifest"]) != record["manifest_sha256"]:
            raise RuntimeError(f"known-control manifest mismatch: {detector}")
        if deep:
            observed = module.analyse_detector(
                detector,
                domain_n=len(all_clean),
                n_per_class=n_per_class,
                seed=seed,
                batch_size=8,
            )
            if observed != record:
                raise RuntimeError(
                    f"known-control reconstruction mismatch: {detector}"
                )
    print(f"PASS known {'pilot' if pilot else 'final'}")


def verify_absorption(*, pilot: bool) -> None:
    from scripts import run_cqg_absorption_matrix as module

    suffix = "_pilot" if pilot else ""
    path = OUT / f"cqg_absorption_matrix{suffix}.json"
    value = load_complete(path)
    cells = []
    if len(value["cell_artifacts"]) != len(value["cells"]):
        raise RuntimeError("absorption cell/artifact count mismatch")
    for artifact, embedded in zip(value["cell_artifacts"], value["cells"]):
        cell_path = assert_hash(artifact["path"], artifact["sha256"])
        for cache in artifact["token_caches"].values():
            assert_hash(cache["path"], cache["sha256"])
        segment_cache = artifact["whitened_segment_cache"]
        assert_hash(segment_cache["path"], segment_cache["sha256"])
        cell = json.loads(cell_path.read_text(encoding="utf-8"))
        if cell != embedded:
            raise RuntimeError(f"embedded absorption cell mismatch: {cell_path}")
        module.validate_cell(cell)
        cells.append(cell)
    if module.summarize_cells(cells) != value["summary"]:
        raise RuntimeError("absorption matrix summary mismatch")
    print(f"PASS absorption {'pilot' if pilot else 'final'}")


def verify_robustness(*, pilot: bool) -> None:
    from scripts import run_cqg_robustness_replicates as module

    suffix = "_pilot" if pilot else ""
    path = OUT / f"cqg_robustness_replicates{suffix}.json"
    value = load_complete(path)
    assert_hash(value["background"]["path"], value["background"]["sha256"])
    assert_hash(value["near_boundary"]["path"], value["near_boundary"]["sha256"])
    if value["unconditioned"] is not None:
        assert_hash(
            value["unconditioned"]["token_cache"],
            value["unconditioned"]["token_cache_sha256"],
        )
    for axis_index, (axis, record) in enumerate(value["axes"].items()):
        artifacts = [
            item for item in value["model_artifacts"] if item["axis"] == axis
        ]
        if len(artifacts) != len(record["configurations"]):
            raise RuntimeError(f"robustness model count mismatch: {axis}")
        population_scores: dict[str, list[np.ndarray]] = {
            name: [] for name in record["populations"]
        }
        for artifact in artifacts:
            cache = assert_hash(artifact["path"], artifact["sha256"])
            with np.load(cache, allow_pickle=False) as model:
                identity = json.loads(str(model["identity_json"].item()))
                if identity["source_sha256"] != value["source_sha256"]:
                    raise RuntimeError(f"stale robustness model: {cache}")
                for population in population_scores:
                    scores = model[f"scores_{population}"]
                    if not np.all(np.isfinite(scores)):
                        raise RuntimeError(f"non-finite robustness scores: {cache}")
                    population_scores[population].append(scores)
        for population, expected in record["populations"].items():
            observed = module.summarize_score_matrix(
                np.stack(population_scores[population]),
                seed=42 + 1000 * (axis_index + 1),
            )
            if observed != expected:
                raise RuntimeError(
                    f"robustness summary mismatch: {axis}/{population}"
                )
    print(f"PASS robustness {'pilot' if pilot else 'final'}")


def verify_reviewer_extensions() -> None:
    from scripts import run_dsd_block_length_sensitivity as block_module
    from scripts import run_gw_autoencoder_baseline as autoencoder_module

    block_path = OUT / f"dsd_block_length_sensitivity_o4a_{block_module.REP}.json"
    block = load_complete(block_path)
    if int(block["bootstrap_replicates_per_cell"]) < 200_000:
        raise RuntimeError("block-sensitivity artifact is not the final replication")
    if block["block_lengths"] != [8, 17, 32, 64]:
        raise RuntimeError("block-sensitivity grid mismatch")
    taxonomy_path = assert_hash(
        block["sources"]["taxonomy"]["path"],
        block["sources"]["taxonomy"]["sha256"],
    )
    assert_hash(
        block["sources"]["thresholds"]["path"],
        block["sources"]["thresholds"]["sha256"],
    )
    for source in block["sources"]["background_scores"].values():
        assert_hash(source["path"], source["sha256"])
    taxonomy = pd.read_csv(taxonomy_path).rename(
        columns={
            "native_score_idxq4_64_queryq4_64": "dsd_score",
            "robustness_class_idxq4_64_queryq4_64": "dsd_class",
        }
    )
    production = taxonomy["dsd_class"].astype(str).to_numpy(dtype="U10")
    for scheme in block["schemes"].values():
        for cell in scheme.values():
            limits = {
                detector: (float(value["ci_lower"]), float(value["ci_upper"]))
                for detector, value in cell["thresholds"].items()
            }
            labels = block_module.classify_population(taxonomy, limits)
            if block_module.summarize_transition(production, labels) != cell[
                "transition_from_production"
            ]:
                raise RuntimeError("block-sensitivity transition mismatch")

    ae_path = OUT / f"gw_autoencoder_baseline_o4a_{autoencoder_module.REP}.json"
    autoencoder = load_complete(ae_path)
    for key in ("thresholds", "taxonomy", "candidate_feature_cache", "scores"):
        source = autoencoder["sources"][key]
        assert_hash(source["path"], source["sha256"])
    for source in autoencoder["sources"]["backgrounds"].values():
        assert_hash(source["feature_cache"], source["feature_cache_sha256"])
        assert_hash(source["selection_ledger"], source["selection_ledger_sha256"])
        assert_hash(
            source["upstream_calibration_ledger"],
            source["upstream_calibration_ledger_sha256"],
        )
        selected = pd.read_csv(ROOT / source["selection_ledger"])
        upstream = pd.read_csv(ROOT / source["upstream_calibration_ledger"])
        selected_keys = set(zip(selected["detector"], selected["gps_start"]))
        upstream_keys = set(zip(upstream["detector"], upstream["gps_start"]))
        if not selected_keys.issubset(upstream_keys):
            raise RuntimeError("autoencoder background is not an upstream-ledger subset")
    scores = pd.read_csv(autoencoder["sources"]["scores"]["path"])
    if len(scores) != int(autoencoder["n_candidates"]):
        raise RuntimeError("autoencoder score count mismatch")
    if not scores["candidate_key"].is_unique:
        raise RuntimeError("autoencoder candidate keys are not unique")
    percentile_columns = [
        f"autoencoder_percentile_seed_{seed}" for seed in autoencoder["seeds"]
    ]
    values = scores[percentile_columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
        raise RuntimeError("invalid autoencoder percentile scores")
    reconstructed_mean = values.mean(axis=1)
    observed_mean = scores["autoencoder_percentile_mean"].to_numpy(dtype=float)
    if not np.allclose(
        reconstructed_mean,
        observed_mean,
        rtol=0,
        atol=1e-15,
    ):
        raise RuntimeError("autoencoder mean score mismatch")
    labels = scores["robustness_class_idxq4_64_queryq4_64"].astype(str).to_numpy()
    observed_auc = autoencoder_module._auc(observed_mean, labels == "ROBUST")
    expected_auc = float(autoencoder["metrics"]["pooled"]["auc_robust_vs_ambiguous"])
    if not np.isclose(observed_auc, expected_auc, rtol=0, atol=1e-15):
        raise RuntimeError("autoencoder pooled AUC mismatch")
    print("PASS reviewer extensions final")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("domain", "known", "absorption", "robustness", "reviewer", "all"),
        default="all",
    )
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument(
        "--shallow",
        action="store_true",
        help="Skip deterministic model reconstruction for domain/known controls.",
    )
    args = parser.parse_args()
    stages = (
        ("domain", "known", "absorption", "robustness", "reviewer")
        if args.stage == "all"
        else (args.stage,)
    )
    for stage in stages:
        if stage == "domain":
            verify_domain(pilot=args.pilot, deep=not args.shallow)
        elif stage == "known":
            verify_known(pilot=args.pilot, deep=not args.shallow)
        elif stage == "absorption":
            verify_absorption(pilot=args.pilot)
        elif stage == "robustness":
            verify_robustness(pilot=args.pilot)
        elif stage == "reviewer":
            if args.pilot:
                raise RuntimeError("reviewer extensions have no pilot artifact")
            verify_reviewer_extensions()


if __name__ == "__main__":
    main()

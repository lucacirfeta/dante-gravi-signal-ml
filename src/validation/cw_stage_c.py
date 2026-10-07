"""Isolated descriptive inference on retained synthetic Stage A RGB pairs.

No preprocessing, strain acquisition, flags, thresholds or equivalence test.
The historical index is a diagnostic comparator, not an approved 16k reference.
"""

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pin(path, expected):
    if sha256(path) != expected:
        raise ValueError(f"provenance mismatch: {path}")


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def top_k_mean(values, k):
    a = np.asarray(values, dtype=np.float64)
    if a.ndim != 1 or not 0 < k <= len(a) or not np.isfinite(a).all():
        raise ValueError("invalid top-k input")
    return float(np.partition(a, len(a) - k)[-k:].mean())


def paired_metrics(base, injected, base_score, injected_score, k, centroid_norm):
    if base.shape != injected.shape or base.ndim != 2:
        raise ValueError("patch correspondence mismatch")
    distances = np.linalg.norm(
        injected.astype(np.float64) - base.astype(np.float64), axis=1
    )
    if not np.isfinite(distances).all():
        raise ValueError("nonfinite tokens")
    bound = centroid_norm * top_k_mean(distances, k)
    delta = float(injected_score - base_score)
    return {
        "signed_score_delta": delta,
        "patch_l2_mean": float(distances.mean()),
        "patch_l2_max": float(distances.max()),
        "patch_top_k_l2_bound": bound,
        # Exact-arithmetic bound; retain any float32 arithmetic excess as observed,
        # without introducing a new tolerance or scientific acceptance threshold.
        "arithmetic_bound_excess": max(0.0, abs(delta) - bound),
    }


def summarize(rows, keys):
    groups = {}
    for row in rows:
        key = tuple(row[name] for name in keys)
        groups.setdefault(key, []).append(row)
    result = []
    names = (
        "signed_score_delta",
        "patch_l2_mean",
        "patch_l2_max",
        "patch_top_k_l2_bound",
        "arithmetic_bound_excess",
    )
    for key, members in sorted(groups.items()):
        record = dict(zip(keys, key))
        record["noises"] = len(members)
        for name in names:
            a = np.array([m[name] for m in members])
            record[name] = {
                "median": float(np.median(a)),
                "minimum": float(a.min()),
                "maximum": float(a.max()),
            }
        result.append(record)
    return result


def select_inputs(parent, stage_a):
    from src.validation.cw_stage_a import task_grid

    rows = []
    for task in task_grid(stage_a):
        if task["kind"] == "pair":
            continue
        receipt_path = parent / "receipts" / f"{task['id']}.json"
        receipt = json.loads(receipt_path.read_text())
        for name in ("id", "kind", "noise", "pulsar", "dose", "phase"):
            if name in task and receipt.get(name) != task[name]:
                raise ValueError("parent task identity mismatch")
        for expected, actual in zip(
            task["components"], receipt["components"], strict=True
        ):
            if any(actual[name] != value for name, value in expected.items()):
                raise ValueError("parent component identity mismatch")
        receipt["receipt_sha256"] = sha256(receipt_path)
        rows.append(receipt)
    baselines = {r["noise"]: r for r in rows if r["kind"] == "baseline"}
    for row in rows:
        if row["kind"] == "single":
            base = baselines[row["noise"]]
            if (
                row["baseline_id"] != base["id"]
                or row["baseline_sha256"] != base["arrays_sha256"]
            ):
                raise ValueError("canonical same-noise baseline binding mismatch")
    return rows


def validate_output(output, configured_root):
    import subprocess
    import sys

    target, namespace = Path(output).resolve(), Path(configured_root).resolve()
    if (
        sys.platform != "linux"
        or target.parent != namespace
        or not namespace.is_relative_to("/home")
    ):
        raise ValueError("isolated native Linux output required")
    probe = namespace
    while not probe.exists():
        probe = probe.parent
    filesystem = subprocess.check_output(
        ["findmnt", "-n", "-o", "FSTYPE", "-T", str(probe)], text=True
    ).strip()
    if filesystem != "ext4":
        raise ValueError("ext4 output required")


def run(config_path, output, expected_config, expected_module):
    import torch
    from src.core.model_loader import load_dinov2_model, python_source_tree_sha256
    from src.core.patch_scorer import PatchScorer
    from src.dante_light.o4a_corrected_runtime import capture_runtime_environment

    root = Path(__file__).resolve().parents[2]
    output, config_path = Path(output), Path(config_path)
    pin(config_path, expected_config)
    pin(Path(__file__), expected_module)
    c = json.loads(config_path.read_text())
    validate_output(output, c["output_root"])
    if (
        c["schema"] != "dante_cw_stage_c_v1"
        or c["acceptance_threshold"] is not None
        or c["equivalence_claim_allowed"]
    ):
        raise ValueError("descriptive scope required")
    parent = Path(c["parent_root"])
    protocol = json.loads(
        (root / "config/dante_o4a_corrected_protocol_v4.json").read_text()
    )
    rep = protocol["representation"]
    science = json.loads(
        (root / "config/dante_workflow_expanded_calibration_v1.json").read_text()
    )["scientific_source_pins"]

    def guard():
        pin(config_path, expected_config)
        pin(Path(__file__), expected_module)
        for path, expected in {**c["pinned_files"], **science}.items():
            pin(root / path, expected)
        pin(parent / "summary.json", c["parent_summary_sha256"])
        pin(parent / "verification.json", c["parent_verification_sha256"])

    guard()
    if output.exists():
        raise FileExistsError("fresh output required; no resume or overwrite")
    import shutil

    if shutil.disk_usage(output.parent).free < c["operations"]["minimum_free_bytes"]:
        raise ValueError("insufficient free space")
    stage_a = json.loads((root / "config/dante_cw_stage_a_v1.json").read_text())
    rows = select_inputs(parent, stage_a)
    baselines_expected = stage_a["noise"]["realizations"]
    singles_expected = (
        baselines_expected
        * len(stage_a["probes"]["frequencies_hz"])
        * len(stage_a["probes"]["doses"])
        * len(stage_a["probes"]["phase_radians"])
    )
    if (
        len(rows) != baselines_expected + singles_expected
        or sum(r["kind"] == "baseline" for r in rows) != baselines_expected
    ):
        raise ValueError("complete inherited population required")
    rows.sort(key=lambda r: (r["kind"] != "baseline", r["id"]))
    model = load_dinov2_model(
        "cuda",
        manifest_path=root / "config/reference_artifacts.json",
        artifact_id=rep["model_artifact_id"],
        allow_download=False,
    )
    provenance = model.dante_model_provenance
    for name, key in (
        ("weights_sha256", "weights_sha256"),
        ("revision", "model_revision"),
        ("source_python_tree_sha256", "model_source_sha256"),
    ):
        if provenance[name] != rep[key]:
            raise ValueError("model differs from frozen representation")
    manifest = json.loads((root / "config/reference_artifacts.json").read_text())
    candidates = [
        x
        for x in manifest["reference_indices"].values()
        if x["sha256"] == rep["primary_index_sha256"]
    ]
    if len(candidates) != 1:
        raise ValueError("unique inherited primary index required")
    index = root / candidates[0]["path"]
    scorer = PatchScorer(
        index,
        device="cuda",
        k=rep["top_k"],
        k_ablations=[],
        n_background=0,
        expected_sha256=rep["primary_index_sha256"],
        artifact_manifest_path=root / "config/reference_artifacts.json",
        model=model,
    )
    norm = float(
        np.linalg.norm(scorer.centroids.cpu().numpy().astype(np.float64), axis=1).max()
    )
    runtime = capture_runtime_environment("cuda")
    output.mkdir()
    (output / "tokens").mkdir()
    # Newly observed, pre-forward input bindings; the historical parent summary
    # does not itself seal a per-receipt inventory. Do not conflate the two.
    write_json(output / "inputs.json", rows)
    lock = output / "controller.lock"
    write_json(lock, {"stage": "descriptive_inference"})
    baselines, scores, results, inventory = {}, {}, [], []

    def image(row):
        path = parent / "arrays" / f"{row['id']}.npz"
        pin(path, row["arrays_sha256"])
        with np.load(path, allow_pickle=False) as data:
            rgb = data["rgb"]
        if rgb.dtype != np.uint8 or rgb.shape != tuple(rep["image_shape"]):
            raise ValueError("uint8 RGB geometry mismatch")
        return rgb

    def encode(images):
        tokens = scorer.encode_patch_tokens(images)
        values = scorer.score_patch_tokens(
            tokens, float("inf"), output_mode="score_only"
        )
        arrays = tokens.cpu().numpy()
        values = [x["novelty_score"] for x in values]
        if not np.isfinite(arrays).all() or not np.isfinite(values).all():
            raise ValueError("nonfinite inference output")
        return arrays, values

    try:
        batch_size = protocol["execution_parameters"]["primary_calibration"][
            "batch_size"
        ]
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            tokens, batch_scores = encode([image(row) for row in batch])
            for row, token, score in zip(batch, tokens, batch_scores, strict=True):
                path = output / "tokens" / f"{row['id']}.npy"
                with path.open("xb") as stream:
                    np.save(stream, token, allow_pickle=False)
                inventory.append(
                    {
                        "id": row["id"],
                        "parent_receipt_sha256": row["receipt_sha256"],
                        "parent_arrays_sha256": row["arrays_sha256"],
                        "tokens_sha256": sha256(path),
                        "score": score,
                    }
                )
                if row["kind"] == "baseline":
                    baselines[row["id"]] = token
                    scores[row["id"]] = score
                else:
                    bid = row["baseline_id"]
                    base_row = next(x for x in rows if x["id"] == bid)
                    if row["baseline_sha256"] != base_row["arrays_sha256"]:
                        raise ValueError("paired baseline binding mismatch")
                    results.append(
                        {
                            **{
                                k: row[k]
                                for k in ("id", "noise", "pulsar", "dose", "phase")
                            },
                            **paired_metrics(
                                baselines[bid],
                                token,
                                scores[bid],
                                score,
                                rep["top_k"],
                                norm,
                            ),
                        }
                    )
            progress = {"completed": start + len(batch), "total": len(rows)}
            (output / "progress.json").write_text(json.dumps(progress))
        baseline_rows = [r for r in rows if r["kind"] == "baseline"]
        independent = []
        for a, b in itertools.combinations(baseline_rows, 2):
            independent.append(
                {
                    "noise_a": a["noise"],
                    "noise_b": b["noise"],
                    **paired_metrics(
                        baselines[a["id"]],
                        baselines[b["id"]],
                        scores[a["id"]],
                        scores[b["id"]],
                        rep["top_k"],
                        norm,
                    ),
                }
            )
        selected = baseline_rows[: c["repeatability"]["baseline_count"]]
        repeats = []
        for row in selected:
            for repetition in range(2):
                token, score = encode([image(row)])
                path = output / "tokens" / f"repeat_{row['id']}_{repetition}.npy"
                with path.open("xb") as stream:
                    np.save(stream, token[0], allow_pickle=False)
                repeats.append(
                    {
                        "id": row["id"],
                        "batch": 1,
                        "repetition": repetition,
                        "tokens_sha256": sha256(path),
                        **paired_metrics(
                            baselines[row["id"]],
                            token[0],
                            scores[row["id"]],
                            score[0],
                            rep["top_k"],
                            norm,
                        ),
                    }
                )
        token, score = encode([image(row) for row in selected])
        for row, value, s in zip(selected, token, score, strict=True):
            path = output / "tokens" / f"repeat_{row['id']}_joint.npy"
            with path.open("xb") as stream:
                np.save(stream, value, allow_pickle=False)
            repeats.append(
                {
                    "id": row["id"],
                    "batch": len(selected),
                    "tokens_sha256": sha256(path),
                    **paired_metrics(
                        baselines[row["id"]],
                        value,
                        scores[row["id"]],
                        s,
                        rep["top_k"],
                        norm,
                    ),
                }
            )
        guard()
        pin(index, rep["primary_index_sha256"])
        pin(provenance["weights_path"], rep["weights_sha256"])
        if (
            python_source_tree_sha256(provenance["source"])
            != rep["model_source_sha256"]
            or capture_runtime_environment("cuda") != runtime
        ):
            raise ValueError("model/runtime changed during inference")
        for row in rows:
            pin(parent / "receipts" / f"{row['id']}.json", row["receipt_sha256"])
        write_json(output / "measurements.json", results)
        write_json(output / "inventory.json", inventory)
        write_json(output / "independent_noise.json", independent)
        write_json(output / "repeatability.json", repeats)
        write_json(
            output / "freeze.json",
            {
                "config_sha256": expected_config,
                "module_sha256": expected_module,
                "script_sha256": sha256(root / "scripts/run_dante_cw_stage_c.py"),
                "parent_summary_sha256": c["parent_summary_sha256"],
                "parent_verification_sha256": c["parent_verification_sha256"],
                "pinned_files": c["pinned_files"],
                "scientific_source_pins": science,
            },
        )
        summary = {
            "status": "COMPLETE_DESCRIPTIVE_SYNTHETIC_INFERENCE_ONLY",
            "images": len(rows),
            "paired_arms": len(results),
            "independent_noises": len(baselines),
            "independent_noise_pairs": len(independent),
            "runtime": runtime,
            "model": provenance,
            "reference_sha256": rep["primary_index_sha256"],
            "top_k": rep["top_k"],
            "batch_size": batch_size,
            "summaries": summarize(results, ("pulsar", "dose", "phase")),
            "real_CW_validated": False,
            "O4b_ready": False,
            "equivalence": False,
            "artifacts_sha256": {
                name: sha256(output / name)
                for name in (
                    "inputs.json",
                    "freeze.json",
                    "measurements.json",
                    "inventory.json",
                    "independent_noise.json",
                    "repeatability.json",
                )
            },
        }
        write_json(output / "summary.json", summary)
        return summary["status"]
    except BaseException as exc:
        write_json(
            output / "failure.json", {"type": type(exc).__name__, "message": str(exc)}
        )
        raise
    finally:
        lock.unlink()
        torch.cuda.empty_cache()

"""Offline, bounded fresh scoring qualification; historical entrypoints unchanged."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

from .calibration_admission import _pinned
from .calibration_contexts import AdmittedContextProvider, replay as preprocess_replay
from .calibration_recovery import read_sealed, sealed, write_json
from .input_coverage import InputCoverageError
from .input_preflight import _file, _hash
from .schema_v2 import strict_json_object


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def compare_runtime(frozen, observed):
    """Driver-only metadata drift, never numerical equivalence across drivers."""
    from src.dante_light.contracts import canonical_json_sha256

    for value in (frozen, observed):
        body = copy.deepcopy(value)
        digest = body.pop("environment_digest", None)
        if digest != canonical_json_sha256(body):
            raise InputCoverageError("runtime seal changed")
        driver = body.get("cuda_device", {}).get("driver_version")
        if not isinstance(driver, str) or not driver.strip():
            raise InputCoverageError("driver provenance missing")
    normalized = copy.deepcopy(observed)
    normalized.pop("environment_digest")
    normalized["cuda_device"]["driver_version"] = frozen["cuda_device"][
        "driver_version"
    ]
    normalized["environment_digest"] = canonical_json_sha256(normalized)
    if _encoded(normalized) != _encoded(frozen):
        raise InputCoverageError("runtime differs beyond driver metadata")
    return {
        "frozen_environment_digest": frozen["environment_digest"],
        "observed_environment_digest": observed["environment_digest"],
        "frozen_driver": frozen["cuda_device"]["driver_version"],
        "observed_driver": observed["cuda_device"]["driver_version"],
        "driver_changed": frozen["cuda_device"]["driver_version"]
        != observed["cuda_device"]["driver_version"],
        "historical_numerical_equivalence_proved": False,
    }


def load_policy(path, sha):
    path = _pinned(path, sha)
    value = strict_json_object(path.read_text(), label="scoring replay policy")
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("status") != "AUTHOR_APPROVED_BOUNDED_FRESH_SCORING_REPLAY_V1"
        or value.get("ignored_metadata_fields") != ["cuda_device.driver_version"]
        or value.get("other_runtime_fields")
        != "exact_frozen_equality_after_validated_digest_normalization"
        or value.get("during_replay_runtime") != "exact_observed_fingerprint_stability"
        or value.get("token_comparison")
        != "exact_same_runtime_bytes_independent_forward"
        or value.get("score_comparison")
        != "independent_numpy_float64_cosine_top_k_mean"
        or value.get("decision_labels")
        != "disabled_and_discarded_infinite_api_placeholder_not_a_scientific_threshold"
        or not value.get("boundary")
        or any(v is not False for v in value["boundary"].values())
    ):
        raise InputCoverageError("unsupported scoring replay policy or boundary")
    return value


def _sources(root, policy):
    paths = policy["source_paths"]
    if not paths or len(paths) != len(set(paths)):
        raise InputCoverageError("source inventory missing or duplicated")
    result = {p: _hash(_file(root, p)) for p in paths}
    if result.get("src/dante_workflow/scoring_replay.py") != _hash(Path(__file__)):
        raise InputCoverageError("executed scoring harness differs from checkout")
    return result


def compare_numerics(tokens, independent_tokens, centroids, scores, *, k, atol, rtol):
    """CPU float64 oracle, not a historical score replay or statistical test."""
    import numpy as np

    tokens = np.asarray(tokens)
    independent_tokens = np.asarray(independent_tokens)
    centroids = np.asarray(centroids)
    scores = np.asarray(scores, dtype=np.float64)
    if (
        tokens.dtype != np.dtype("float32")
        or independent_tokens.dtype != tokens.dtype
        or tokens.ndim != 3
        or independent_tokens.shape != tokens.shape
        or tokens.shape[0] == 0
        or centroids.ndim != 2
        or centroids.shape[0] == 0
        or tokens.shape[2] != centroids.shape[1]
        or type(k) is not int
        or not 0 < k <= tokens.shape[1]
        or scores.shape != (tokens.shape[0],)
        or not all(
            np.isfinite(a).all()
            for a in (tokens, independent_tokens, centroids, scores)
        )
        or not np.isfinite([atol, rtol]).all()
        or atol < 0
        or rtol < 0
    ):
        raise InputCoverageError("invalid numerical grid, finite values or tolerance")
    if tokens.tobytes() != independent_tokens.tobytes():
        raise InputCoverageError("independent encoder token mismatch")
    centers = centroids.astype(np.float64)
    norms = np.linalg.norm(centers, axis=-1, keepdims=True)
    if (norms == 0).any():
        raise InputCoverageError("zero reference centroid")
    centers /= norms
    # Tokens are already normalized by the unchanged production encoder.
    # Re-normalizing them here would test a different formula.
    anomaly = 1 - (tokens.astype(np.float64) @ centers.T).max(axis=-1)
    oracle = np.partition(anomaly, anomaly.shape[1] - k, axis=1)[:, -k:].mean(axis=1)
    errors = np.abs(scores - oracle)
    if not np.less_equal(errors, atol + rtol * np.abs(oracle)).all():
        raise InputCoverageError("independent scoring formula exceeds frozen tolerance")
    return oracle, errors


def replay(provider, *, policy_path, policy_sha, preprocessing_path):
    import numpy as np
    import torch
    import torch.nn.functional as functional
    from PIL import Image
    from src.core.model_loader import load_dinov2_model, python_source_tree_sha256
    from src.core.patch_producer import _worker_preprocess
    from src.core.patch_scorer import PatchScorer
    from src.dante_light.o4a_corrected_runtime import (
        capture_runtime_environment,
        load_canonical_runtime_contract,
    )

    root = provider.root
    policy = load_policy(policy_path, policy_sha)
    sources = _sources(root, policy)
    parents = {}
    parent_paths = {}
    for key in (
        "tolerance_parent",
        "protocol_parent",
        "runtime_parent",
        "artifact_manifest",
    ):
        ref = policy[key]
        parent_paths[key] = _pinned(_file(root, ref["path"]), ref["sha256"])
        parents[key] = strict_json_object(parent_paths[key].read_text(), label=key)
    if provider.receipt_sha != policy["admission_sha256"]:
        raise InputCoverageError("scoring admission differs from approved input")
    preprocessing_path = _pinned(
        preprocessing_path, policy["preprocessing_receipt_sha256"]
    )
    previous = read_sealed(preprocessing_path)
    if provider.receipt["parent"] != policy["protocol_parent"]:
        # Admission parent also carries its seal field/digest; compare its pins.
        ref = provider.receipt["parent"]
        if any(ref.get(k) != v for k, v in policy["protocol_parent"].items()):
            raise InputCoverageError("admission protocol parent differs")
    rep = parents["protocol_parent"]["representation"]
    execution = parents["protocol_parent"]["execution_parameters"][
        "primary_calibration"
    ]
    tolerance = parents["tolerance_parent"]["benchmark"]["equivalence"]
    frozen = load_canonical_runtime_contract(root=root, require_current=False)
    if frozen != parents["runtime_parent"]:
        raise InputCoverageError("runtime parent differs from canonical reader")
    observed = capture_runtime_environment(execution["device"])
    qualification = compare_runtime(frozen["runtime_environment"], observed)
    if preprocess_replay(provider) != previous:
        raise InputCoverageError("full preprocessing replay differs from pinned gate")
    images = []
    keys = sorted(provider.rows)
    if len(keys) != previous["record_count"] or len(previous["rows"]) != len(keys):
        raise InputCoverageError("bounded input identity cardinality differs")
    for key, prior in zip(keys, previous["rows"], strict=True):
        if key != (prior["detector"], prior["gps_start"], prior["gps_end"]):
            raise InputCoverageError("preprocessing identity differs")
        series = provider.read(detector=key[0], start=key[1], end=key[2]).series
        gps, image = _worker_preprocess(
            series.value,
            key[1],
            1 / rep["sample_rate_hz"],
            str(series.name),
            prior["analysis_start"],
            prior["analysis_end"],
            True,
        )
        if (
            gps != prior["analysis_start"]
            or image is None
            or _bytes_sha(image) != prior["image_sha256"]
        ):
            raise InputCoverageError(
                "scoring input image differs from verified preprocessing"
            )
        images.append(image)
    manifest = parent_paths["artifact_manifest"]
    model = load_dinov2_model(
        execution["device"],
        manifest_path=manifest,
        artifact_id=rep["model_artifact_id"],
        allow_download=False,
    )
    provenance = model.dante_model_provenance
    if any(
        provenance[k] != rep[r]
        for k, r in (
            ("weights_sha256", "weights_sha256"),
            ("revision", "model_revision"),
            ("source_python_tree_sha256", "model_source_sha256"),
        )
    ):
        raise InputCoverageError("model representation differs")
    indices = [
        r
        for r in parents["artifact_manifest"]["reference_indices"].values()
        if r["sha256"] == rep["primary_index_sha256"]
    ]
    if len(indices) != 1:
        raise InputCoverageError("unique frozen reference index required")
    index = (
        manifest.parent
        / parents["artifact_manifest"]["artifact_root"]
        / indices[0]["path"]
    ).resolve()
    _pinned(index, rep["primary_index_sha256"])
    with np.load(index, allow_pickle=False) as data:
        centroids = data["embeddings"].copy()
    scorer = PatchScorer(
        index,
        device=execution["device"],
        k=rep["top_k"],
        k_ablations=[],
        n_background=0,
        expected_sha256=rep["primary_index_sha256"],
        artifact_manifest_path=manifest,
        model=model,
    )
    rows = []
    batch_size = execution["batch_size"]
    if type(batch_size) is not int or batch_size <= 0:
        raise InputCoverageError("invalid configured batch size")
    for start in range(0, len(images), batch_size):
        batch = images[start : start + batch_size]
        with torch.no_grad():
            tokens = scorer.encode_patch_tokens(batch)
            transformed = torch.stack(
                [scorer.transform(Image.fromarray(i)) for i in batch]
            ).to(scorer.device)
            if list(transformed.shape[-2:]) != rep["encoder_input_size"]:
                raise InputCoverageError("encoder input geometry differs")
            direct = functional.normalize(
                model.forward_features(transformed)["x_norm_patchtokens"], p=2, dim=-1
            )
            # score_only API needs a threshold; no scientific threshold is fitted
            # or used. Infinity disables labels and labels are never retained.
            scores = [
                r["novelty_score"]
                for r in scorer.score_patch_tokens(
                    tokens, float("inf"), output_mode="score_only"
                )
            ]
        cpu = tokens.cpu().numpy()
        oracle, errors = compare_numerics(
            cpu,
            direct.cpu().numpy(),
            centroids,
            scores,
            k=rep["top_k"],
            atol=tolerance["score_atol"],
            rtol=tolerance["score_rtol"],
        )
        for offset, score in enumerate(scores):
            prior = previous["rows"][start + offset]
            rows.append(
                {
                    "detector": prior["detector"],
                    "gps_start": prior["gps_start"],
                    "gps_end": prior["gps_end"],
                    "image_sha256": prior["image_sha256"],
                    "token_sha256": _bytes_sha(cpu[offset]),
                    "token_shape": list(cpu[offset].shape),
                    "score": score,
                    "oracle_score": float(oracle[offset]),
                    "absolute_error": float(errors[offset]),
                }
            )
        del tokens, direct, transformed
    if capture_runtime_environment(execution["device"]) != observed:
        raise InputCoverageError("runtime changed during scoring replay")
    if _sources(root, policy) != sources:
        raise InputCoverageError("scoring sources changed")
    load_policy(policy_path, policy_sha)
    _pinned(preprocessing_path, policy["preprocessing_receipt_sha256"])
    for key, path in parent_paths.items():
        _pinned(path, policy[key]["sha256"])
    _pinned(provider.receipt_path, provider.receipt_sha)
    for detector, start, end in keys:
        provider.read(detector=detector, start=start, end=end)
    _pinned(index, rep["primary_index_sha256"])
    _pinned(provenance["weights_path"], rep["weights_sha256"])
    if (
        python_source_tree_sha256(Path(provenance["source"]))
        != rep["model_source_sha256"]
    ):
        raise InputCoverageError("model source changed")
    return sealed(
        {
            "schema_version": 1,
            "status": "PASS_BOUNDED_FRESH_SCORING_REPLAY_ONLY",
            "policy_sha256": policy_sha,
            "admission_sha256": provider.receipt_sha,
            "preprocessing_receipt_sha256": policy["preprocessing_receipt_sha256"],
            "parents": {k: policy[k] for k in parent_paths},
            "source_hashes": sources,
            "runtime": observed,
            "runtime_qualification": qualification,
            "model_provenance": provenance,
            "index_sha256": rep["primary_index_sha256"],
            "score_tolerance": {k: tolerance[k] for k in ("score_atol", "score_rtol")},
            "record_count": len(rows),
            "rows": rows,
            "boundary": policy["boundary"],
            "verification_was_second_fetch": False,
        }
    )


def _bytes_sha(value):
    return hashlib.sha256(value.tobytes()).hexdigest()


def main(argv=None):
    from .adapters import build_adapter
    from .schema import load_workflow_spec

    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "repository-root",
        "config",
        "policy",
        "receipt",
        "preprocessing-receipt",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    if args.require_installed and Path(__file__).resolve().is_relative_to(root):
        parser.error("installed harness required")
    if (args.expected is None) != (args.expected_sha256 is None) or (
        args.require_installed and args.expected is None
    ):
        parser.error("pinned expected evidence required")
    if str(root) not in sys.path:
        sys.path.append(
            str(root)
        )  # Only pinned scientific src.core comes from checkout.
    policy = load_policy(args.policy, args.policy_sha256)
    spec = load_workflow_spec(args.config.resolve(), root=root)
    provider = AdmittedContextProvider(
        spec,
        build_adapter(spec),
        root=root,
        receipt_path=args.receipt,
        receipt_sha=policy["admission_sha256"],
    )
    output = args.output
    protected = (
        root,
        provider.directory.resolve(),
        provider.receipt_path.parent.resolve(),
        args.preprocessing_receipt.parent.resolve(),
    )
    if (
        not output.is_absolute()
        or output.exists()
        or any(p.is_symlink() for p in (output, *output.parents))
        or any(output.resolve().is_relative_to(p) for p in protected)
    ):
        parser.error("new external output outside preserved evidence required")
    result = replay(
        provider,
        policy_path=args.policy,
        policy_sha=args.policy_sha256,
        preprocessing_path=args.preprocessing_receipt,
    )
    if args.expected is not None:
        expected = _pinned(args.expected, args.expected_sha256)
        if result != read_sealed(expected):
            raise InputCoverageError("installed scoring replay differs from checkout")
        _pinned(expected, args.expected_sha256)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x"):
        pass
    write_json(output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "record_count": result["record_count"],
                "digest": result["digest"],
                "output": str(output),
                "installed_replay": args.require_installed,
                "harness_module": str(Path(__file__).resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

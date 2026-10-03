"""Driver-only qualification and independent encoder/scoring refusals."""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from src.dante_workflow import scoring_replay as gate
from src.dante_workflow.calibration_recovery import _hash
from src.dante_workflow.input_coverage import InputCoverageError


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config/dante_workflow_scoring_replay_v1.json"


def environment(driver="original"):
    from src.dante_light.contracts import canonical_json_sha256

    body = {
        "cuda_device": {"driver_version": driver, "capability": [12, 0]},
        "packages": {"torch": "synthetic"},
        "python": {"version": "synthetic"},
    }
    return {**body, "environment_digest": canonical_json_sha256(body)}


def reseal(value):
    from src.dante_light.contracts import canonical_json_sha256

    value.pop("environment_digest", None)
    value["environment_digest"] = canonical_json_sha256(value)
    return value


@pytest.mark.parametrize("driver", ["original", "newer", "arbitrary-future-version"])
def test_driver_updates_are_provenance_not_version_pins(driver):
    result = gate.compare_runtime(environment(), environment(driver))
    assert result["observed_driver"] == driver
    assert result["driver_changed"] == (driver != "original")
    assert result["historical_numerical_equivalence_proved"] is False


@pytest.mark.parametrize("fault", ["package", "python", "gpu", "extra", "type"])
def test_no_non_driver_drift_even_with_valid_seal(fault):
    current = environment("updated")
    if fault == "package":
        current["packages"]["torch"] = "changed"
    elif fault == "python":
        current["python"]["version"] = "changed"
    elif fault == "gpu":
        current["cuda_device"]["capability"] = [11, 0]
    elif fault == "extra":
        current["extra"] = "changed"
    else:
        current["cuda_device"]["capability"] = [12.0, 0]
    with pytest.raises(InputCoverageError, match="beyond driver"):
        gate.compare_runtime(environment(), reseal(current))


@pytest.mark.parametrize("which", ["frozen", "observed"])
def test_both_runtime_seals_required(which):
    old, new = environment(), environment("updated")
    (old if which == "frozen" else new)["environment_digest"] = "0" * 64
    with pytest.raises(InputCoverageError, match="seal"):
        gate.compare_runtime(old, new)


@pytest.mark.parametrize("driver", [None, "", " ", 617, False])
def test_missing_or_non_string_driver_refused(driver):
    with pytest.raises(InputCoverageError, match="provenance"):
        gate.compare_runtime(environment(), environment(driver))


def test_versioned_policy_and_upstream_tolerance_unchanged():
    policy = gate.load_policy(POLICY, _hash(POLICY))
    parent = ROOT / policy["tolerance_parent"]["path"]
    assert _hash(parent) == policy["tolerance_parent"]["sha256"]
    tol = json.loads(parent.read_text())["benchmark"]["equivalence"]
    assert tol["score_rtol"] == 0
    assert "score_atol" not in policy
    assert policy["boundary"]["productive_runtime_contract_changed"] is False
    assert gate._sources(ROOT, policy)["src/dante_workflow/scoring_replay.py"] == _hash(
        Path(gate.__file__)
    )


@pytest.mark.parametrize(
    "fault", ["schema", "driver", "boundary", "labels", "tokens", "scoring", "runtime"]
)
def test_no_policy_promotion_or_comparison_relaxation(tmp_path, fault):
    value = json.loads(POLICY.read_text())
    if fault == "schema":
        value["schema_version"] = True
    elif fault == "driver":
        value["ignored_metadata_fields"].append("packages.torch")
    elif fault == "boundary":
        value["boundary"]["o4b_launch_allowed"] = True
    elif fault == "labels":
        value["decision_labels"] = "classify"
    elif fault == "tokens":
        value["token_comparison"] = "approximate"
    elif fault == "scoring":
        value["score_comparison"] = "production_self_comparison"
    else:
        value["during_replay_runtime"] = "ignore"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(value))
    with pytest.raises(InputCoverageError, match="policy"):
        gate.load_policy(path, _hash(path))


def test_policy_file_hash_required():
    with pytest.raises(InputCoverageError):
        gate.load_policy(POLICY, "0" * 64)


@pytest.fixture
def numerical():
    tokens = np.array([[[1, 0], [0, 1], [-1, 0], [0, -1]]], dtype=np.float32)
    centers = np.array([[2, 0]], dtype=np.float32)
    return tokens, tokens.copy(), centers, np.array([1.5])


def test_independent_cosine_top_k_not_global_statistic(numerical):
    oracle, errors = gate.compare_numerics(*numerical, k=2, atol=0, rtol=0)
    assert oracle.tolist() == [1.5]
    assert errors.tolist() == [0]


@pytest.mark.parametrize(
    "fault",
    [
        "tokens",
        "dtype",
        "shape",
        "centers",
        "zero",
        "scores",
        "nan",
        "k",
        "atol",
        "rtol",
    ],
)
def test_numerical_mismatch_never_qualified(numerical, fault):
    tokens, direct, centers, scores = numerical
    k, atol, rtol = 2, 0.0, 0.0
    if fault == "tokens":
        direct[0, 0, 0] += 0.01
    elif fault == "dtype":
        tokens = tokens.astype(np.float64)
    elif fault == "shape":
        direct = direct[:, :1]
    elif fault == "centers":
        centers = centers[:, :1]
    elif fault == "zero":
        centers[:] = 0
    elif fault == "scores":
        scores[:] += 0.01
    elif fault == "nan":
        tokens[0, 0, 0] = np.nan
    elif fault == "k":
        k = True
    elif fault == "atol":
        atol = -1
    else:
        rtol = float("inf")
    with pytest.raises(InputCoverageError):
        gate.compare_numerics(
            tokens, direct, centers, scores, k=k, atol=atol, rtol=rtol
        )


def test_tolerance_boundary_inclusive_and_no_posthoc_extension(numerical):
    tokens, direct, centers, scores = numerical
    # Deliberately synthetic exact binary tolerance, not production config.
    scores += 0.125
    gate.compare_numerics(tokens, direct, centers, scores, k=2, atol=0.125, rtol=0)
    with pytest.raises(InputCoverageError, match="frozen tolerance"):
        gate.compare_numerics(tokens, direct, centers, scores, k=2, atol=0.124, rtol=0)


def test_existing_encoder_and_score_only_consumer_against_oracle():
    import torch
    import torch.nn.functional as functional
    from PIL import Image
    from src.core.patch_scorer import PatchScorer

    class SyntheticModel(torch.nn.Module):
        def forward_features(self, tensor):
            return {"x_norm_patchtokens": tensor.flatten(2).transpose(1, 2)}

    scorer = PatchScorer.__new__(PatchScorer)
    scorer.device = torch.device("cpu")
    scorer.model = SyntheticModel().eval()
    scorer.transform = lambda image: torch.tensor(
        np.asarray(image).copy(), dtype=torch.float32
    ).permute(2, 0, 1)
    scorer.k = 2
    scorer.k_ablations = []
    centers = np.array([[1, 2, 3], [-1, 1, 2]], dtype=np.float32)
    scorer.centroids = functional.normalize(torch.tensor(centers), p=2, dim=-1)
    images = [np.arange(12, dtype=np.uint8).reshape(2, 2, 3) + 1]
    tokens = scorer.encode_patch_tokens(images)
    tensor = torch.stack([scorer.transform(Image.fromarray(i)) for i in images])
    direct = functional.normalize(
        scorer.model.forward_features(tensor)["x_norm_patchtokens"], p=2, dim=-1
    )
    output = scorer.score_patch_tokens(tokens, float("inf"), output_mode="score_only")
    assert all(r["is_novel"] is False for r in output)
    policy = gate.load_policy(POLICY, _hash(POLICY))
    tol = json.loads((ROOT / policy["tolerance_parent"]["path"]).read_text())[
        "benchmark"
    ]["equivalence"]
    gate.compare_numerics(
        tokens.numpy(),
        direct.numpy(),
        centers,
        [r["novelty_score"] for r in output],
        k=scorer.k,
        atol=tol["score_atol"],
        rtol=tol["score_rtol"],
    )


@pytest.mark.parametrize("fault", ["missing", "duplicated", "executed"])
def test_source_inventory_and_executed_identity_refused(fault):
    policy = deepcopy(json.loads(POLICY.read_text()))
    if fault == "missing":
        policy["source_paths"] = []
    elif fault == "duplicated":
        policy["source_paths"] *= 2
    else:
        policy["source_paths"].remove("src/dante_workflow/scoring_replay.py")
    with pytest.raises(InputCoverageError):
        gate._sources(ROOT, policy)


def test_installed_mode_refuses_checkout_before_measurement():
    arguments = []
    for key in (
        "repository-root",
        "config",
        "policy",
        "receipt",
        "preprocessing-receipt",
        "output",
    ):
        arguments.extend(
            ["--" + key, str(ROOT if key == "repository-root" else POLICY)]
        )
    arguments.extend(["--policy-sha256", _hash(POLICY), "--require-installed"])
    with pytest.raises(SystemExit) as stopped:
        gate.main(arguments)
    assert stopped.value.code == 2


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Complete synthetic harness wiring, no live inputs/model downloads."""
    from types import SimpleNamespace
    import torch
    import torch.nn.functional as functional
    from src.core import model_loader, patch_producer, patch_scorer
    from src.dante_light import o4a_corrected_runtime as runtime
    from src.dante_workflow.calibration_recovery import sealed, write_json

    root = tmp_path / "root"
    root.mkdir()
    code = root / "src/dante_workflow/scoring_replay.py"
    code.parent.mkdir(parents=True)
    code.write_bytes(Path(gate.__file__).read_bytes())
    image = np.arange(12, dtype=np.uint8).reshape(2, 2, 3) + 1
    prior = sealed(
        {
            "record_count": 1,
            "rows": [
                {
                    "detector": "H1",
                    "gps_start": 100,
                    "gps_end": 104,
                    "analysis_start": 101,
                    "analysis_end": 103,
                    "image_sha256": gate._bytes_sha(image),
                }
            ],
        }
    )
    previous = tmp_path / "previous.json"
    write_json(previous, prior)
    admission = tmp_path / "admission.json"
    admission.write_text("synthetic admitted input")
    weights = tmp_path / "weights"
    weights.write_bytes(b"synthetic weights")
    centers = np.array([[1, 2, 3], [-1, 1, 2]], dtype=np.float32)
    index = root / "index.npz"
    np.savez(index, embeddings=centers)
    rep = dict(
        sample_rate_hz=2,
        model_artifact_id="synthetic",
        top_k=2,
        model_revision="synthetic",
        model_source_sha256="synthetic-tree",
        weights_sha256=_hash(weights),
        primary_index_sha256=_hash(index),
        encoder_input_size=[2, 2],
    )
    contract = {
        "representation": rep,
        "execution_parameters": {
            "primary_calibration": {"device": "cpu", "batch_size": 1}
        },
    }
    policy = json.loads(POLICY.read_text())
    parents = {
        "protocol_parent": contract,
        "runtime_parent": {"runtime_environment": environment()},
        "artifact_manifest": {
            "artifact_root": ".",
            "reference_indices": {
                "synthetic": {"sha256": _hash(index), "path": "index.npz"}
            },
        },
        "tolerance_parent": {
            "benchmark": {"equivalence": {"score_atol": 0.000001, "score_rtol": 0}}
        },
    }
    for key, value in parents.items():
        path = root / (key + ".json")
        path.write_text(json.dumps(value))
        policy[key] = {"path": path.name, "sha256": _hash(path)}
    policy["source_paths"] = ["src/dante_workflow/scoring_replay.py"]
    policy["admission_sha256"] = _hash(admission)
    policy["preprocessing_receipt_sha256"] = _hash(previous)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy))
    provider = SimpleNamespace(
        root=root,
        receipt_sha=_hash(admission),
        receipt_path=admission,
        receipt={"parent": policy["protocol_parent"]},
        rows={("H1", 100, 104): {}},
        read=lambda **kwargs: SimpleNamespace(
            series=SimpleNamespace(value=np.ones(8), name="H1")
        ),
    )
    monkeypatch.setattr(gate, "preprocess_replay", lambda provider: prior)
    monkeypatch.setattr(
        patch_producer, "_worker_preprocess", lambda *args: (101, image.copy())
    )
    monkeypatch.setattr(
        runtime,
        "load_canonical_runtime_contract",
        lambda **kwargs: parents["runtime_parent"],
    )
    monkeypatch.setattr(
        runtime, "capture_runtime_environment", lambda device: environment("updated")
    )
    monkeypatch.setattr(
        model_loader, "python_source_tree_sha256", lambda path: "synthetic-tree"
    )

    class Model(torch.nn.Module):
        def forward_features(self, tensor):
            return {"x_norm_patchtokens": tensor.flatten(2).transpose(1, 2)}

    model = Model().eval()
    model.dante_model_provenance = {
        "weights_sha256": _hash(weights),
        "weights_path": str(weights),
        "source_python_tree_sha256": "synthetic-tree",
        "source": str(tmp_path),
        "revision": "synthetic",
    }
    calls = []

    def loader(*args, **kwargs):
        calls.append(kwargs)
        return model

    monkeypatch.setattr(model_loader, "load_dinov2_model", loader)
    original = patch_scorer.PatchScorer

    def scorer_factory(*args, **kwargs):
        scorer = original.__new__(original)
        scorer.device = torch.device("cpu")
        scorer.model = model
        scorer.k = kwargs["k"]
        scorer.k_ablations = []
        scorer.transform = lambda i: torch.tensor(
            np.asarray(i).copy(), dtype=torch.float32
        ).permute(2, 0, 1)
        scorer.centroids = functional.normalize(torch.tensor(centers), p=2, dim=-1)
        return scorer

    monkeypatch.setattr(patch_scorer, "PatchScorer", scorer_factory)
    return SimpleNamespace(
        provider=provider,
        policy_path=policy_path,
        policy_sha=_hash(policy_path),
        previous=previous,
        prior=prior,
        model=model,
        weights=weights,
        runtime=runtime,
        calls=calls,
        producer=patch_producer,
        image=image,
    )


def run_harness(c):
    return gate.replay(
        c.provider,
        policy_path=c.policy_path,
        policy_sha=c.policy_sha,
        preprocessing_path=c.previous,
    )


def test_complete_harness_freezes_inputs_runtime_offline_and_scoped_receipt(harness):
    result = run_harness(harness)
    assert result["status"] == "PASS_BOUNDED_FRESH_SCORING_REPLAY_ONLY"
    assert result["record_count"] == 1
    assert result["rows"][0]["detector"] == "H1"
    assert "is_novel" not in result["rows"][0]
    assert result["runtime_qualification"]["driver_changed"] is True
    assert harness.calls[0]["allow_download"] is False
    assert all(v is False for v in result["boundary"].values())


@pytest.mark.parametrize(
    "fault",
    ["preprocessing", "identity", "image", "model", "end_runtime", "weights", "policy"],
)
def test_complete_harness_stops_on_parent_input_model_or_runtime_drift(
    harness, monkeypatch, fault
):
    c = harness
    if fault == "preprocessing":
        monkeypatch.setattr(gate, "preprocess_replay", lambda provider: {})
    elif fault == "identity":
        c.provider.rows = {("L1", 100, 104): {}}
    elif fault == "image":
        monkeypatch.setattr(
            c.producer, "_worker_preprocess", lambda *args: (101, c.image * 0)
        )
    elif fault == "model":
        c.model.dante_model_provenance["revision"] = "different"
    elif fault == "end_runtime":
        values = iter([environment("updated"), environment("changed-again")])
        monkeypatch.setattr(
            c.runtime, "capture_runtime_environment", lambda device: next(values)
        )
    else:
        original = c.model.forward_features

        def mutate(tensor):
            (c.weights if fault == "weights" else c.policy_path).write_bytes(b"changed")
            return original(tensor)

        monkeypatch.setattr(c.model, "forward_features", mutate)
    with pytest.raises(InputCoverageError):
        run_harness(c)

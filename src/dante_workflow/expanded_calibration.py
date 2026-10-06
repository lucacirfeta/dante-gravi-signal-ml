"""Fresh isolated full calibration; frozen scientific primitives, no promotion."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import re
import subprocess

from .calibration_admission import _pinned
from .calibration_recovery import read_sealed, sealed, write_json
from .expanded_context_replay import independent_values, isolated, quiet, record
from .expanded_preprocessing_replay import image_check, independent_image, paths
from .expanded_production import bind as productive_bind
from .input_coverage import InputCoverageError
from .input_preflight import _file, _hash
from .schema_v2 import strict_json_object
from .scoring_replay import compare_numerics, compare_runtime, load_policy


SOURCES = (
    "src/dante_workflow/expanded_calibration.py",
    "scripts/replay_dante_workflow_expanded_calibration.py",
)
RULE = "full frozen per-session-detector identity multiset and GPS-ordered configured batches; fresh native preprocessing and scoring; inherited p99/historical replay; no old score, threshold or shard transplant"
BOUNDARY = {
    "isolated_full_calibration_only": True,
    "default_provider_replaced": False,
    "historical_scores_or_thresholds_reused": False,
    "candidate_scan_allowed": False,
    "o4b_launch_allowed": False,
    "physical_data_quality_certified": False,
}


def source_audit(root, freeze):
    if not isinstance(freeze, str) or not re.fullmatch(r"[0-9a-f]{40}", freeze):
        raise InputCoverageError("full calibration source freeze required")
    hashes = {}
    for name in SOURCES:
        data = subprocess.run(
            ["git", "show", f"{freeze}:{name}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        hashes[name] = hashlib.sha256(data).hexdigest()
        _pinned(_file(root, name), hashes[name])
    if hashes[SOURCES[0]] != _hash(Path(__file__)):
        raise InputCoverageError("executed calibration differs from freeze")
    return hashes


def load_contract(path, sha):
    c = strict_json_object(_pinned(path, sha).read_text(), label="full calibration")
    if (
        type(c.get("schema_version")) is not int
        or c["schema_version"] != 1
        or c.get("status") != "FULL_ISOLATED_EXPANDED_CALIBRATION_V1"
        or c.get("source_paths") != list(SOURCES)
        or c.get("measurement_rule") != RULE
        or c.get("automatic_resume") is not False
        or c.get("boundary") != BOUNDARY
        or any(type(v) is not bool for v in c["boundary"].values())
        or c.get("same_runtime_replay_rule")
        != "inherit scoring_replay.main pinned expected sealed equality; no new tolerance"
    ):
        raise InputCoverageError("unsupported full calibration contract")
    return c


def population(rows, protocol, allowed):
    """Keep every historical session membership; never deduplicate contexts."""
    from src.dante_light.o4a_corrected_protocol import _digest_rows

    rep, expected = protocol["representation"], protocol["calibration_population"]
    digest, count = _digest_rows(rows)
    if (digest, count) != (
        expected["identity_jsonl_sha256"],
        expected["identity_count"],
    ):
        raise InputCoverageError("frozen full identity ledger differs")
    grouped, seen, contexts, replay = defaultdict(list), set(), set(), Counter()
    pad, duration = rep["whitening_pad_s"], rep["analysis_duration_s"]
    for r in rows:
        identity = r["session_id"], r["detector"], r["catalog_gps_start"]
        key = r["detector"], *r["required_padded_interval"]
        if (
            identity in seen
            or key not in allowed
            or key[1] != r["analysis_gps_start"] - pad
            or key[2] != r["analysis_gps_start"] + duration + pad
            or r["replay_disposition"]
            not in ("REQUIRE_EXACT_REPLAY", "CORRECTED_CONTEXT_NO_REPLAY")
        ):
            raise InputCoverageError(
                "duplicate/invalid calibration identity or geometry"
            )
        seen.add(identity)
        contexts.add(key)
        grouped[(r["session_id"], r["detector"])].append(r)
        replay[f"{r['detector']}/{r['replay_disposition']}"] += 1
    if (
        contexts != set(allowed)
        or dict(replay) != expected["replay_disposition_counts"]
    ):
        raise InputCoverageError(
            "calibration context union or replay population differs"
        )
    sessions = Counter(k[1] for k in grouped)
    if dict(sessions) != expected["session_detector_counts"]:
        raise InputCoverageError("per-session-detector population differs")
    for group in grouped.values():
        group.sort(key=lambda r: r["catalog_gps_start"])
    return dict(sorted(grouped.items()))


def percentile(scores, estimator):
    import numpy as np

    # Parse the pinned estimator, never infer a percentile from chat/defaults.
    match = re.fullmatch(
        r"numpy\.percentile\(scores, ([0-9]+(?:\.[0-9]+)?)\)", estimator
    )
    if match is None or not 0 <= float(match[1]) <= 100:
        raise InputCoverageError("unsupported pinned percentile estimator")
    a = np.asarray(scores, dtype=np.float64)
    if a.ndim != 1 or not a.size or not np.isfinite(a).all():
        raise InputCoverageError("invalid fresh threshold population")
    return float(np.percentile(a, float(match[1])))


def historical_check(row, score, atol):
    import numpy as np

    if not np.isfinite(score) or not np.isfinite(atol) or atol < 0:
        raise InputCoverageError("invalid historical replay input")
    if row["replay_disposition"] == "REQUIRE_EXACT_REPLAY":
        value = np.frombuffer(
            bytes.fromhex(row["historical_score_float32_hex"]), dtype=np.float32
        )
        if (
            value.shape != (1,)
            or not np.isfinite(value).all()
            or abs(score - float(value[0])) > atol
        ):
            raise InputCoverageError(
                "inherited historical full-context score replay failed"
            )
    elif row["replay_disposition"] != "CORRECTED_CONTEXT_NO_REPLAY":
        raise InputCoverageError("unsupported historical replay scope")


def prepare(
    *, contract_path, contract_sha, source_freeze, productive_dir, productive_kwargs
):
    root = Path(productive_kwargs["parent_args"]["root"]).resolve()
    c = load_contract(contract_path, contract_sha)
    sources = source_audit(root, source_freeze)
    provider, productive = productive_bind(**productive_kwargs)
    directory = Path(productive_dir).resolve()
    quiet(directory)
    p = c["productive_parent"]
    if (
        productive_kwargs["profile_sha"] != p["profile_sha256"]
        or productive_kwargs["source_freeze"] != p["source_freeze"]
    ):
        raise InputCoverageError("productive profile/freeze differs")
    pins = {Path(contract_path): contract_sha}
    for name in ("preflight", "verification"):
        pins[directory / (name + ".json")] = p[name + "_sha256"]
    for path, sha in pins.items():
        _pinned(path, sha)
    preflight = read_sealed(directory / "preflight.json")
    verified = read_sealed(directory / "verification.json")
    expected_verified = sealed(
        dict(
            status="PASS_VERIFIED_ISOLATED_EXPANDED_PRODUCTIVE_INPUT_BINDING_ONLY",
            preflight_sha256=p["preflight_sha256"],
            preflight_digest=productive["digest"],
            binding=productive,
            context_count=productive["context_count"],
            identity_count=productive["identity_count"],
            boundary=productive["boundary"],
        )
    )
    if productive != preflight or verified != expected_verified:
        raise InputCoverageError("verified productive prerequisite differs")
    q = c["qualification_policy"]
    policy_path = _pinned(_file(root, q["path"]), q["sha256"])
    policy = load_policy(policy_path, q["sha256"])
    pins[policy_path] = q["sha256"]
    parents = {}
    for role in (
        "protocol_parent",
        "tolerance_parent",
        "runtime_parent",
        "artifact_manifest",
    ):
        ref = policy[role]
        path = _pinned(_file(root, ref["path"]), ref["sha256"])
        pins[path] = ref["sha256"]
        parents[role] = strict_json_object(path.read_text(), label=role)
    protocol = parents["protocol_parent"]
    method = productive["preprocessing_binding"]["method"]
    if (
        protocol["representation"] != method["representation"]
        or protocol["execution_parameters"]["primary_calibration"]
        != method["execution_parameters"]
    ):
        raise InputCoverageError("productive scientific geometry differs")
    required = set(policy["source_paths"]) | {
        "src/dante_light/o4a_corrected_protocol.py",
        "src/dante_light/o4a_dependency_audit.py",
        "src/dante_light/o4a_corrected_execution.py",
        "src/dante_light/evidence.py",
    }
    if set(c["scientific_source_pins"]) != required:
        raise InputCoverageError("incomplete scientific source inventory")
    for name, sha in {**c["scientific_source_pins"], **sources}.items():
        pins[_file(root, name)] = sha
    for ref in protocol["calibration_population"]["source_hdf5_references"]:
        _pinned(_file(root, ref["path"]), ref["sha256"])
    for path, sha in pins.items():
        _pinned(path, sha)
    from src.dante_light.o4a_corrected_protocol import iter_calibration_identities

    rows = list(iter_calibration_identities(root))
    groups = population(rows, protocol, provider.allowed)
    engine = Engine(root, policy, parents, protocol)
    binding = sealed(
        dict(
            status="FULL_CALIBRATION_BINDING",
            contract_sha256=contract_sha,
            source_freeze=source_freeze,
            source_hashes=sources,
            scientific_source_pins=c["scientific_source_pins"],
            productive=productive,
            qualification_policy_sha256=q["sha256"],
            runtime=engine.runtime,
            runtime_qualification=engine.qualification,
            model_provenance=engine.provenance,
            identity_count=len(rows),
            context_count=len(provider.allowed),
            session_detector_count=len(groups),
            boundary=BOUNDARY,
        )
    )
    return dict(
        provider=provider,
        groups=groups,
        protocol=protocol,
        engine=engine,
        pins=pins,
        binding=binding,
        productive_dir=directory,
        preprocessing_dir=Path(productive_kwargs["preprocessing_dir"]),
        root=root,
        contract=c,
    )


class Engine:
    def __init__(self, root, policy, parents, protocol):
        import numpy as np
        from src.core.model_loader import load_dinov2_model
        from src.core.patch_scorer import PatchScorer
        from src.dante_light.o4a_corrected_runtime import (
            capture_runtime_environment,
            load_canonical_runtime_contract,
        )

        self.rep = protocol["representation"]
        self.device = protocol["execution_parameters"]["primary_calibration"]["device"]
        frozen = load_canonical_runtime_contract(root=root, require_current=False)
        if frozen != parents["runtime_parent"]:
            raise InputCoverageError("canonical runtime parent differs")
        self.runtime = capture_runtime_environment(self.device)
        self.qualification = compare_runtime(
            frozen["runtime_environment"], self.runtime
        )
        self.tolerance = parents["tolerance_parent"]["benchmark"]["equivalence"]
        from src.dante_light.evidence import SCORE_ATOL

        if self.tolerance["score_atol"] != SCORE_ATOL:
            raise InputCoverageError("historical and frozen score tolerance differ")
        manifest = _file(root, policy["artifact_manifest"]["path"])
        self.model = load_dinov2_model(
            self.device,
            manifest_path=manifest,
            artifact_id=self.rep["model_artifact_id"],
            allow_download=False,
        )
        self.provenance = self.model.dante_model_provenance
        for key, expected in (
            ("weights_sha256", "weights_sha256"),
            ("revision", "model_revision"),
            ("source_python_tree_sha256", "model_source_sha256"),
        ):
            if self.provenance[key] != self.rep[expected]:
                raise InputCoverageError("frozen model representation differs")
        m = parents["artifact_manifest"]
        candidates = [
            r
            for r in m["reference_indices"].values()
            if r["sha256"] == self.rep["primary_index_sha256"]
        ]
        if len(candidates) != 1:
            raise InputCoverageError("unique frozen index required")
        self.index = (
            manifest.parent / m["artifact_root"] / candidates[0]["path"]
        ).resolve()
        _pinned(self.index, self.rep["primary_index_sha256"])
        with np.load(self.index, allow_pickle=False) as a:
            self.centroids = a["embeddings"].copy()
        self.scorer = PatchScorer(
            self.index,
            device=self.device,
            k=self.rep["top_k"],
            k_ablations=[],
            n_background=0,
            expected_sha256=self.rep["primary_index_sha256"],
            artifact_manifest_path=manifest,
            model=self.model,
        )
        self.guard()

    def guard(self):
        from src.core.model_loader import python_source_tree_sha256
        from src.dante_light.o4a_corrected_runtime import capture_runtime_environment

        if capture_runtime_environment(self.device) != self.runtime:
            raise InputCoverageError("observed scoring runtime changed")
        _pinned(self.index, self.rep["primary_index_sha256"])
        _pinned(Path(self.provenance["weights_path"]), self.rep["weights_sha256"])
        if (
            python_source_tree_sha256(Path(self.provenance["source"]))
            != self.rep["model_source_sha256"]
        ):
            raise InputCoverageError("model source changed")

    def score(self, images):
        import torch
        import torch.nn.functional as functional
        from PIL import Image

        self.guard()
        with torch.no_grad():
            tokens = self.scorer.encode_patch_tokens(images)
            inputs = torch.stack(
                [self.scorer.transform(Image.fromarray(i)) for i in images]
            ).to(self.scorer.device)
            if list(inputs.shape[-2:]) != self.rep["encoder_input_size"]:
                raise InputCoverageError("encoder input geometry differs")
            direct = functional.normalize(
                self.model.forward_features(inputs)["x_norm_patchtokens"], p=2, dim=-1
            )
            scores = [
                float(r["novelty_score"])
                for r in self.scorer.score_patch_tokens(
                    tokens, float("inf"), output_mode="score_only"
                )
            ]
        cpu = tokens.cpu().numpy()
        oracle, errors = compare_numerics(
            cpu,
            direct.cpu().numpy(),
            self.centroids,
            scores,
            k=self.rep["top_k"],
            atol=self.tolerance["score_atol"],
            rtol=self.tolerance["score_rtol"],
        )
        result = [
            dict(
                score=score,
                token_sha256=hashlib.sha256(cpu[i].tobytes()).hexdigest(),
                token_shape=list(cpu[i].shape),
                oracle_score=float(oracle[i]),
                absolute_error=float(errors[i]),
            )
            for i, score in enumerate(scores)
        ]
        self.guard()
        return result


def guard(state):
    quiet(state["productive_dir"])
    state["provider"].guard()
    for path, sha in state["pins"].items():
        _pinned(path, sha)


def images(state, batch, stage, pool):
    import numpy as np
    from src.core.patch_producer import _worker_preprocess

    provider = state["provider"]
    native = provider.delegate
    rep = state["protocol"]["representation"]
    prepared = []
    for row in batch:
        key = row["detector"], *row["required_padded_interval"]
        guard(state)
        if stage == "run":
            context = provider.read(detector=key[0], start=key[1], end=key[2])
            values = np.ascontiguousarray(context.series.value)
            name = str(context.series.name)
            future = pool.submit(
                _worker_preprocess,
                values,
                key[1],
                1 / rep["sample_rate_hz"],
                name,
                row["analysis_gps_start"],
                row["analysis_gps_start"] + rep["analysis_duration_s"],
                True,
            )
        else:
            values = independent_values(native, key)
            name = native.expected_names[key]
            future = None
        proof = record(native, key, values)
        guard(state)
        prepared.append((row, key, values, name, proof, future))
    output = []
    proofs = []
    for row, key, values, name, proof, future in prepared:
        if stage == "run":
            gps, image = future.result()
            if gps != int(row["analysis_gps_start"]):
                raise InputCoverageError("worker label differs")
        else:
            image = independent_image(values, key, name, rep)
        image = image_check(image, rep)
        receipt_path, image_path = paths(state["preprocessing_dir"], key)
        retained = read_sealed(receipt_path)
        _pinned(image_path, retained["image_file_sha256"])
        saved = image_check(np.load(image_path, allow_pickle=False), rep)
        if (
            proof != retained["native_context"]
            or not np.array_equal(image, saved)
            or hashlib.sha256(image.tobytes()).hexdigest()
            != retained["image_values_sha256"]
        ):
            raise InputCoverageError(
                "fresh calibration image/native differs from full preprocessing"
            )
        output.append(image)
        proofs.append(dict(native=proof, image_sha256=retained["image_values_sha256"]))
        guard(state)
    return output, proofs


def execute(*, stage, run_dir, prepare_kwargs, summary_sha=None):
    state = prepare(**prepare_kwargs)
    provider = state["provider"]
    directory = isolated(run_dir, provider.delegate)
    for parent in (
        state["productive_dir"],
        state["preprocessing_dir"],
        Path(prepare_kwargs["productive_kwargs"]["parent_args"]["method_path"])
        .resolve()
        .parent,
        Path(
            prepare_kwargs["productive_kwargs"]["parent_args"]["native_dir"]
        ).resolve(),
    ):
        if directory.is_relative_to(parent) or parent.is_relative_to(directory):
            raise InputCoverageError("calibration output overlaps preserved parent")
    binding = state["binding"]
    if stage == "run":
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "sessions").mkdir()
        write_json(directory / "binding.json", binding)
    elif stage == "verify":
        quiet(directory)
        if (directory / "verification.json").exists():
            raise InputCoverageError("verification already exists")
        expected = read_sealed(_pinned(directory / "summary.json", summary_sha))
        if read_sealed(directory / "binding.json") != binding:
            raise InputCoverageError("calibration binding differs")
    else:
        raise InputCoverageError("unsupported calibration stage")
    lock = directory / "controller.lock"
    with lock.open("x") as f:
        json.dump(
            dict(pid=os.getpid(), stage=stage, binding_digest=binding["digest"]), f
        )
    try:
        params = state["protocol"]["execution_parameters"]["primary_calibration"]
        if any(
            type(params[k]) is not int or params[k] < 1
            for k in ("workers", "batch_size")
        ):
            raise InputCoverageError("invalid configured calibration execution")
        refs = []
        completed = 0
        with ProcessPoolExecutor(
            max_workers=params["workers"], mp_context=mp.get_context("spawn")
        ) as pool:
            for (session, detector), rows in state["groups"].items():
                records = []
                for offset in range(0, len(rows), params["batch_size"]):
                    batch = rows[offset : offset + params["batch_size"]]
                    image_batch, proofs = images(state, batch, stage, pool)
                    numerical = state["engine"].score(image_batch)
                    if len(numerical) != len(batch):
                        raise InputCoverageError("score cardinality differs")
                    for row, proof, numeric in zip(
                        batch, proofs, numerical, strict=True
                    ):
                        historical_check(
                            row,
                            numeric["score"],
                            state["engine"].tolerance["score_atol"],
                        )
                        records.append(
                            dict(
                                session_id=session,
                                detector=detector,
                                catalog_gps_start=row["catalog_gps_start"],
                                analysis_gps_start=row["analysis_gps_start"],
                                replay_disposition=row["replay_disposition"],
                                **proof,
                                **numeric,
                            )
                        )
                    completed += len(batch)
                    write_json(
                        directory / f"progress.{stage}.json",
                        sealed(
                            dict(
                                stage=stage,
                                binding_digest=binding["digest"],
                                completed_identities=completed,
                                expected_identities=binding["identity_count"],
                            )
                        ),
                    )
                estimator = state["protocol"]["calibration_population"][
                    "recalibration"
                ]["estimator"]
                shard = sealed(
                    dict(
                        status="COMPLETE_FRESH_SESSION_CALIBRATION",
                        session_id=session,
                        detector=detector,
                        binding_digest=binding["digest"],
                        record_count=len(records),
                        threshold_rule=estimator,
                        empirical_p99=percentile(
                            [r["score"] for r in records], estimator
                        ),
                        rows=records,
                    )
                )
                path = directory / "sessions" / f"{session}_{detector}.json"
                if stage == "run":
                    write_json(path, shard)
                elif read_sealed(path) != shard:
                    raise InputCoverageError(
                        "full same-runtime calibration shard replay differs"
                    )
                refs.append(
                    dict(
                        session_id=session,
                        detector=detector,
                        record_count=len(records),
                        shard=path.name,
                        digest=shard["digest"],
                        sha256=_hash(path),
                    )
                )
        if {p.name for p in (directory / "sessions").iterdir()} != {
            r["shard"] for r in refs
        }:
            raise InputCoverageError("extra/missing calibration session receipt")
        guard(state)
        state["engine"].guard()
        _, final = productive_bind(**prepare_kwargs["productive_kwargs"])
        if final != binding["productive"]:
            raise InputCoverageError("productive parent changed")
        source_audit(state["root"], prepare_kwargs["source_freeze"])
        if completed != binding["identity_count"]:
            raise InputCoverageError("incomplete full calibration")
        result = sealed(
            dict(
                status="PASS_COMPLETE_ISOLATED_EXPANDED_CALIBRATION_ONLY",
                binding=binding,
                identity_count=completed,
                context_count=binding["context_count"],
                session_detector_count=len(refs),
                sessions=refs,
                boundary=BOUNDARY,
                verification_was_second_fetch=False,
            )
        )
        if stage == "verify":
            if result != expected:
                raise InputCoverageError(
                    "full same-runtime sealed calibration replay differs"
                )
            _pinned(directory / "summary.json", summary_sha)
            result = sealed(
                dict(
                    status="PASS_VERIFIED_ISOLATED_EXPANDED_CALIBRATION_ONLY",
                    binding=binding,
                    summary_sha256=summary_sha,
                    summary_digest=expected["digest"],
                    identity_count=completed,
                    context_count=binding["context_count"],
                    session_detector_count=len(refs),
                    boundary=BOUNDARY,
                    verification_was_second_fetch=False,
                    independent_dispatch="h5py native/unchanged scientific primitives plus independent model forward and numpy oracle",
                )
            )
        write_json(
            directory / ("summary.json" if stage == "run" else "verification.json"),
            result,
        )
        return result
    except Exception as exc:
        write_json(
            directory / "failure.json",
            sealed(
                dict(
                    status="FAILED_ISOLATED_EXPANDED_CALIBRATION",
                    stage=stage,
                    error_type=type(exc).__name__,
                    message=str(exc),
                    automatic_resume=False,
                    boundary=BOUNDARY,
                )
            ),
        )
        raise
    finally:
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("run", "verify"), required=True)
    for name in (
        "repository-root",
        "contract",
        "profile",
        "productive-dir",
        "recovery-dir",
        "native-dir",
        "binding",
        "method",
        "preprocessing-dir",
        "run-dir",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in (
        "contract-sha256",
        "source-freeze",
        "profile-sha256",
        "productive-source-freeze",
        "binding-sha256",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--summary-sha256")
    a = parser.parse_args(argv)
    if a.stage == "verify" and a.summary_sha256 is None:
        parser.error("standalone verify requires pinned summary")
    result = execute(
        stage=a.stage,
        run_dir=a.run_dir,
        summary_sha=a.summary_sha256,
        prepare_kwargs=dict(
            contract_path=a.contract,
            contract_sha=a.contract_sha256,
            source_freeze=a.source_freeze,
            productive_dir=a.productive_dir,
            productive_kwargs=dict(
                profile_path=a.profile,
                profile_sha=a.profile_sha256,
                source_freeze=a.productive_source_freeze,
                preprocessing_dir=a.preprocessing_dir,
                parent_args=dict(
                    root=a.repository_root,
                    recovery_dir=a.recovery_dir,
                    native_dir=a.native_dir,
                    binding_path=a.binding,
                    binding_sha=a.binding_sha256,
                    method_path=a.method,
                ),
            ),
        ),
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "identity_count",
                    "context_count",
                    "session_detector_count",
                )
            }
        )
    )
    return 0

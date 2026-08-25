"""Outcome-blind wavelet-scattering feasibility support for DANTE-Light v5."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256


AUDIT_ID = "dante-light-l4-prefilter-v5-scattering-feasibility"
CONFIG_STATUS = "FEASIBILITY_ONLY_NOT_A_V5_PROTOCOL"
ARTIFACT_STATUS = "COMPLETE_FEASIBILITY_ONLY_NOT_SELECTED"
SHA256_LENGTH = 64


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_digest(payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("config_digest", None)
    return canonical_json_sha256(body)


def validate_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    if value.get("schema_version") != 1:
        raise ContractError("scattering feasibility requires schema version 1")
    if value.get("audit_id") != AUDIT_ID or value.get("status") != CONFIG_STATUS:
        raise ContractError("unexpected scattering feasibility identity or status")
    if value.get("config_digest") != config_digest(value):
        raise ContractError("scattering feasibility config digest mismatch")

    boundary = value.get("scientific_boundary", {})
    forbidden = (
        "may_access_development_outcomes",
        "may_access_o4b",
        "may_access_reserved_confirmation",
        "may_access_teacher_scores",
        "may_freeze_v5",
        "may_select_scattering",
        "routing_enabled",
    )
    if any(boundary.get(key) is not False for key in forbidden):
        raise ContractError("scattering feasibility permits a protected or promotable action")
    if boundary.get("allowed_inputs") != [
        "deterministic synthetic probes",
        "unlabelled random arrays",
    ]:
        raise ContractError("scattering feasibility input boundary changed")

    dependency = value.get("dependency", {})
    if (
        dependency.get("distribution") != "kymatio"
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(dependency.get("version", "")))
        or dependency.get("license") != "BSD-3-Clause"
        or dependency.get("execution_scope") != "isolated_wsl_only_not_production"
        or dependency.get("production_dependency_added") is not False
    ):
        raise ContractError("scattering dependency contract changed")
    wheel = dependency.get("wheel", {})
    if (
        not str(wheel.get("filename", "")).endswith(".whl")
        or len(str(wheel.get("sha256", ""))) != SHA256_LENGTH
    ):
        raise ContractError("scattering wheel provenance is incomplete")

    signal = value.get("input_contract", {})
    if (
        int(signal.get("sample_rate_hz", 0)) <= 0
        or not math.isfinite(float(signal.get("duration_s", 0.0)))
        or float(signal.get("duration_s", 0.0)) <= 0.0
        or signal.get("dtype") not in {"float32", "float64"}
        or int(signal.get("batch_size", 0)) <= 0
    ):
        raise ContractError("scattering input contract changed")
    if signal.get("outcome_blind_probes") != [
        "white_noise",
        "centered_impulse",
        "linear_chirp",
    ]:
        raise ContractError("scattering probes changed")

    transform = value.get("transform", {})
    required_transform_keys = {
        "J", "Q", "T", "average", "backend", "device", "frontend",
        "max_order", "out_type", "oversampling",
    }
    q_values = transform.get("Q", [])
    if (
        set(transform) != required_transform_keys
        or int(transform.get("J", 0)) <= 0
        or not isinstance(q_values, list)
        or len(q_values) != 2
        or any(int(item) <= 0 for item in q_values)
        or int(transform.get("T", 0)) != 2 ** int(transform["J"])
        or transform.get("average") is not True
        or transform.get("backend") != "torch"
        or transform.get("device") != "cpu"
        or transform.get("frontend") != "torch"
        or int(transform.get("max_order", 0)) not in {1, 2}
        or transform.get("out_type") != "array"
        or int(transform.get("oversampling", -1)) < 0
    ):
        raise ContractError("scattering transform contract is invalid")

    benchmark = value.get("benchmark", {})
    if (
        int(benchmark.get("batch_size", 0)) != 1
        or int(benchmark.get("repetitions", 0)) <= 0
        or int(benchmark.get("warmup_repetitions", -1)) < 0
        or int(benchmark.get("determinism_repetitions", 0)) < 2
        or float(benchmark.get("determinism_rtol", -1.0)) != 0.0
        or float(benchmark.get("determinism_atol", -1.0)) != 0.0
        or benchmark.get("paired_control") != "contiguous_input_clone"
        or benchmark.get("paired_order")
        != "alternating_scattering_first_control_first"
    ):
        raise ContractError("scattering benchmark contract is invalid")
    return value


def load_config(path: Path) -> dict[str, Any]:
    return validate_config(json.loads(path.read_text(encoding="utf-8")))


def synthetic_probes(config: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """Create deterministic outcome-blind float32 inputs."""

    contract = config["input_contract"]
    sample_rate = int(contract["sample_rate_hz"])
    count = int(round(float(contract["duration_s"]) * sample_rate))
    rng = np.random.default_rng(int(contract["seed"]))
    noise = rng.standard_normal(count).astype(np.float32)
    impulse = np.zeros(count, dtype=np.float32)
    impulse[count // 2] = np.float32(1.0)

    chirp_config = contract["synthetic_chirp"]
    start = float(chirp_config["start_s"])
    duration = float(chirp_config["duration_s"])
    time_axis = np.arange(count, dtype=np.float64) / sample_rate
    selected = (time_axis >= start) & (time_axis < start + duration)
    local_time = time_axis[selected] - start
    rate = (float(chirp_config["f1_hz"]) - float(chirp_config["f0_hz"])) / duration
    phase = 2.0 * np.pi * (
        float(chirp_config["f0_hz"]) * local_time + 0.5 * rate * local_time**2
    )
    chirp = np.zeros(count, dtype=np.float32)
    chirp[selected] = np.cos(phase).astype(np.float32)
    probes = {
        "white_noise": noise,
        "centered_impulse": impulse,
        "linear_chirp": chirp,
    }
    if any(array.shape != (count,) or array.dtype != np.float32 for array in probes.values()):
        raise ContractError("scattering synthetic probe contract failed")
    if any(not np.all(np.isfinite(array)) for array in probes.values()):
        raise ContractError("scattering synthetic probe is non-finite")
    return probes


def load_scattering_class() -> tuple[type[Any], dict[str, Any]]:
    """Load the public API or record the exact scoped compatibility fallback."""

    public_error: dict[str, str] | None = None
    try:
        module = importlib.import_module("kymatio.torch")
        cls = getattr(module, "Scattering1D")
        strategy = "public_kymatio_torch_api"
    except (ImportError, AttributeError) as exc:
        message = str(exc)
        if "sph_harm" in message and "scipy.special" in message:
            reason = "SCIPY_SPECIAL_SPH_HARM_UNAVAILABLE"
        else:
            reason = "PUBLIC_KYMATIO_TORCH_IMPORT_FAILED"
        public_error = {"type": type(exc).__name__, "reason": reason}
        module = importlib.import_module(
            "kymatio.scattering1d.frontend.torch_frontend"
        )
        cls = getattr(module, "ScatteringTorch1D")
        strategy = "scoped_internal_1d_frontend_compatibility_fallback"
    return cls, {
        "strategy": strategy,
        "public_import_succeeded": public_error is None,
        "public_import_error": public_error,
    }


def instantiate_scattering(config: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    cls, import_status = load_scattering_class()
    transform = config["transform"]
    contract = config["input_contract"]
    count = int(round(float(contract["duration_s"]) * int(contract["sample_rate_hz"])))
    model = cls(
        J=int(transform["J"]),
        shape=count,
        Q=tuple(int(value) for value in transform["Q"]),
        T=int(transform["T"]),
        max_order=int(transform["max_order"]),
        oversampling=int(transform["oversampling"]),
        out_type=str(transform["out_type"]),
        backend=str(transform["backend"]),
    )
    return model.eval(), import_status


def array_sha256(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


def timing_summary(values: list[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size == 0 or not np.all(np.isfinite(array)):
        raise ContractError("invalid scattering timing ledger")
    if np.any(array <= 0.0):
        raise ContractError("scattering timing samples must be positive")
    return {
        "count": int(array.size),
        "mean_s": float(np.mean(array)),
        "median_s": float(np.median(array)),
        "p95_s": float(np.quantile(array, 0.95)),
        "minimum_s": float(np.min(array)),
        "maximum_s": float(np.max(array)),
    }


def validate_artifact(
    artifact: Mapping[str, Any], *, config: Mapping[str, Any]
) -> dict[str, Any]:
    value = dict(artifact)
    declared = value.pop("artifact_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("scattering feasibility artifact digest mismatch")
    if value.get("status") != ARTIFACT_STATUS:
        raise ContractError("unexpected scattering feasibility artifact status")
    if value.get("candidate_selected") is not False or value.get("protocol_frozen") is not False:
        raise ContractError("scattering feasibility was promoted")
    if value.get("routing_enabled") is not False:
        raise ContractError("scattering feasibility enabled routing")
    access = value.get("outcome_access", {})
    if any(access.get(key) != [] for key in (
        "development_outcomes",
        "reserved_confirmation",
        "o4b",
        "teacher_scores",
    )):
        raise ContractError("scattering feasibility accessed protected outcomes")
    if value.get("transform") != config["transform"]:
        raise ContractError("scattering artifact transform/config mismatch")
    if value.get("input_contract") != config["input_contract"]:
        raise ContractError("scattering artifact input/config mismatch")
    dependency = value.get("dependency", {})
    if dependency.get("wheel") != config["dependency"]["wheel"]:
        raise ContractError("scattering wheel provenance mismatch")
    if dependency.get("production_dependency_added") is not False:
        raise ContractError("scattering entered production dependencies")
    if dependency.get("imported_version") != config["dependency"]["version"]:
        raise ContractError("scattering imported dependency version mismatch")
    if dependency.get("installed_metadata_license") != config["dependency"]["license"]:
        raise ContractError("scattering installed dependency license mismatch")

    determinism = value.get("determinism", {})
    if determinism.get("all_repetitions_bitwise_equal") is not True:
        raise ContractError("scattering output is not bitwise deterministic")
    expected_repeats = int(config["benchmark"]["determinism_repetitions"])
    for probe in determinism.get("probes", {}).values():
        hashes = probe.get("output_sha256_by_repetition", [])
        if len(hashes) != expected_repeats or len(set(hashes)) != 1:
            raise ContractError("scattering determinism ledger mismatch")
        if probe.get("all_finite") is not True:
            raise ContractError("scattering output is non-finite")
        shape = probe.get("output_shape", [])
        if (
            len(shape) != 3
            or shape[0] != 1
            or int(np.prod(shape)) != int(probe.get("coefficient_count", -1))
            or probe.get("output_dtype") != config["input_contract"]["dtype"]
        ):
            raise ContractError("scattering output shape or dtype mismatch")

    timing = value.get("timing", {})
    ledger = timing.get("paired_batch1_cpu_ledger", [])
    if len(ledger) != int(config["benchmark"]["repetitions"]):
        raise ContractError("scattering timing repetition count mismatch")
    scattering_samples = [float(row["scattering_s"]) for row in ledger]
    control_samples = [float(row["control_s"]) for row in ledger]
    deltas = [left - right for left, right in zip(scattering_samples, control_samples)]
    expected = {
        "scattering": timing_summary(scattering_samples),
        "control": timing_summary(control_samples),
        "paired_delta": timing_summary(deltas),
    }
    for group, summary in expected.items():
        recorded = timing["summary"][group]
        if recorded["count"] != summary["count"]:
            raise ContractError(f"scattering timing count mismatch: {group}")
        for key in ("mean_s", "median_s", "p95_s", "minimum_s", "maximum_s"):
            if not math.isclose(float(recorded[key]), float(summary[key]), rel_tol=1e-12, abs_tol=1e-15):
                raise ContractError(f"scattering timing summary mismatch: {group}.{key}")
    return dict(artifact)

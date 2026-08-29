"""Canonical runtime contract for the corrected O4a reconstruction.

The scientific protocol fixes what is measured.  This companion contract
fixes the numerical toolchain used to evaluate it, so a replay cannot mix
Windows and WSL/CUDA results under the same run identity.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Mapping

import numpy as np
import torch

from src.dante_light.contracts import (
    ContractError,
    RepresentationContract,
    canonical_json_sha256,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_REL = "config/dante_o4a_corrected_runtime_v1.json"
SCHEMA_VERSION = 1
RUNTIME_ID = "dante-o4a-corrected-wsl-cuda-runtime-v1"
PACKAGE_NAMES = (
    "astropy",
    "gwpy",
    "h5py",
    "matplotlib",
    "numpy",
    "pillow",
    "scipy",
    "torch",
    "torchvision",
)


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ContractError(f"canonical O4a runtime dependency is absent: {name}") from exc


def _nvidia_driver_version() -> str:
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError("canonical O4a runtime cannot fingerprint the NVIDIA driver") from exc
    values = sorted({line.strip() for line in output.splitlines() if line.strip()})
    if len(values) != 1:
        raise ContractError("canonical O4a runtime has an ambiguous NVIDIA driver")
    return values[0]


def capture_runtime_environment(device: str = "cuda") -> dict[str, Any]:
    """Return the complete scoring-relevant runtime fingerprint."""

    if device != "cuda" or not torch.cuda.is_available():
        raise ContractError("corrected O4a canonical scoring requires CUDA")
    executable = Path(sys.executable)
    if not executable.is_file():
        raise ContractError("canonical O4a Python executable is not hashable")
    environment = {
        "operating_system": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "wsl": platform.system() == "Linux"
            and "microsoft" in platform.release().lower(),
        },
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "compiler": platform.python_compiler(),
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        },
        "packages": {name: _package_version(name) for name in PACKAGE_NAMES},
        "torch": {
            "version": torch.__version__,
            "git_version": torch.version.git_version,
            "cuda_runtime": torch.version.cuda,
            "cudnn_version": torch.backends.cudnn.version(),
            "default_dtype": str(torch.get_default_dtype()),
            "float32_matmul_precision": torch.get_float32_matmul_precision(),
            "deterministic_algorithms_enabled": torch.are_deterministic_algorithms_enabled(),
            "cudnn_deterministic": torch.backends.cudnn.deterministic,
            "cudnn_benchmark": torch.backends.cudnn.benchmark,
            "cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
            "cudnn_allow_tf32": torch.backends.cudnn.allow_tf32,
        },
        "cuda_device": {
            "request": device,
            "name": torch.cuda.get_device_name(0),
            "capability": list(torch.cuda.get_device_capability(0)),
            "device_count": torch.cuda.device_count(),
            "driver_version": _nvidia_driver_version(),
        },
        "numpy_version": np.__version__,
    }
    return {
        **environment,
        "environment_digest": canonical_json_sha256(environment),
    }


def build_canonical_runtime_contract(
    *, root: Path = ROOT, device: str = "cuda"
) -> dict[str, Any]:
    environment = capture_runtime_environment(device)
    if not environment["operating_system"]["wsl"]:
        raise ContractError("the corrected O4a canonical runtime must be frozen inside WSL")
    representation = RepresentationContract.from_reference_manifest(
        root / "config/reference_artifacts.json"
    ).to_dict()
    scorer = {
        "runtime_environment_digest": environment["environment_digest"],
        "representation": representation,
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_CANONICAL_WSL_CUDA_RUNTIME",
        "runtime_id": RUNTIME_ID,
        "runtime_environment": environment,
        "scorer_fingerprint": {
            **scorer,
            "fingerprint_digest": canonical_json_sha256(scorer),
        },
        "scientific_boundary": {
            "numerical_toolchain_only": True,
            "score_tolerance_changed": False,
            "thresholds_changed": False,
            "calibration_population_changed": False,
            "windows_scoring_allowed": False,
            "cross_environment_shard_reuse_allowed": False,
        },
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_canonical_runtime_contract(
    value: Mapping[str, Any],
    *,
    root: Path = ROOT,
    require_current: bool = False,
    device: str = "cuda",
) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("contract_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("corrected O4a runtime contract self-digest mismatch")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "FROZEN_CANONICAL_WSL_CUDA_RUNTIME"
        or value.get("runtime_id") != RUNTIME_ID
        or not value["runtime_environment"]["operating_system"]["wsl"]
        or value["runtime_environment"]["cuda_device"]["request"] != "cuda"
    ):
        raise ContractError("corrected O4a runtime contract is not canonical WSL/CUDA")
    environment = dict(value["runtime_environment"])
    environment_digest = environment.pop("environment_digest", None)
    if environment_digest != canonical_json_sha256(environment):
        raise ContractError("corrected O4a runtime environment digest mismatch")
    representation = RepresentationContract.from_reference_manifest(
        root / "config/reference_artifacts.json"
    ).to_dict()
    scorer = dict(value["scorer_fingerprint"])
    scorer_digest = scorer.pop("fingerprint_digest", None)
    if (
        scorer_digest != canonical_json_sha256(scorer)
        or scorer.get("runtime_environment_digest") != environment_digest
        or scorer.get("representation") != representation
    ):
        raise ContractError("corrected O4a scorer fingerprint mismatch")
    if require_current and capture_runtime_environment(device) != value["runtime_environment"]:
        raise ContractError(
            "STOP_ENVIRONMENT_MISMATCH: corrected O4a scoring requires the frozen WSL runtime"
        )
    return dict(value)


def load_canonical_runtime_contract(
    *, root: Path = ROOT, require_current: bool = False, device: str = "cuda"
) -> dict[str, Any]:
    path = root / OUTPUT_REL
    if not path.is_file():
        raise ContractError("corrected O4a canonical runtime contract is absent")
    return validate_canonical_runtime_contract(
        json.loads(path.read_text(encoding="utf-8")),
        root=root,
        require_current=require_current,
        device=device,
    )


def write_canonical_runtime_contract(
    *, path: Path | None = None, root: Path = ROOT, device: str = "cuda"
) -> dict[str, Any]:
    value = build_canonical_runtime_contract(root=root, device=device)
    target = path or (root / OUTPUT_REL)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, target)
    return value

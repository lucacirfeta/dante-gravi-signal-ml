#!/usr/bin/env python3
"""Run an allowlisted artifact verifier against the frozen runtime identity.

This administrative wrapper exists only for verifying already-produced artifacts.
It cannot invoke any scientific run, build, or freeze selector.  The underlying
verifier still replays its normal hashes, cardinalities, provenance, and numeric
gates; only the comparison with the currently installed NVIDIA driver is skipped.
"""

from __future__ import annotations

import copy
from pathlib import Path
import runpy
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError  # noqa: E402
from src.dante_light import o4a_corrected_runtime as runtime_contract  # noqa: E402


_ALLOWED_VERIFIERS = {
    "scripts/run_dante_o4a_corrected.py": "verify-native-index",
    "scripts/run_dante_o4a_native_calibration.py": "verify",
    "scripts/run_dante_o4a_native_rescore_v2.py": "verify",
    "scripts/run_dante_o4a_native_thresholds.py": "verify",
    "scripts/run_dante_o4a_native_classification.py": "verify",
    "scripts/run_dante_o4a_native_taxonomy.py": "verify",
    "scripts/run_dante_o4a_native_coincidence.py": "verify",
    "scripts/run_dante_o4a_native_pem.py": "verify",
}


def _validate_verifier_argv(argv: Sequence[str]) -> tuple[Path, list[str]]:
    if not argv:
        raise ContractError("existing-artifact verifier script is absent")
    script = argv[0].replace("\\", "/")
    expected_stage = _ALLOWED_VERIFIERS.get(script)
    if expected_stage is None:
        raise ContractError("existing-artifact verifier is not allowlisted")
    arguments = list(argv[1:])
    if arguments.count("--stage") != 1:
        raise ContractError("existing-artifact verifier requires one explicit stage")
    position = arguments.index("--stage")
    if position + 1 >= len(arguments) or arguments[position + 1] != expected_stage:
        raise ContractError("existing-artifact verifier selector is not allowlisted")
    if any(argument.startswith("--stage=") for argument in arguments):
        raise ContractError("existing-artifact verifier selector is ambiguous")
    path = (ROOT / script).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise ContractError("existing-artifact verifier escapes the repository") from exc
    if not path.is_file():
        raise ContractError("existing-artifact verifier script is missing")
    return path, arguments


def run_existing_verifier(argv: Sequence[str]) -> int:
    script, arguments = _validate_verifier_argv(argv)
    frozen = runtime_contract.load_canonical_runtime_contract(
        root=ROOT, require_current=False, device="cuda"
    )
    frozen_environment = copy.deepcopy(frozen["runtime_environment"])
    original_capture = runtime_contract.capture_runtime_environment

    def _frozen_capture(device: str = "cuda") -> dict:
        if device != "cuda":
            raise ContractError("existing-artifact verification requires frozen CUDA identity")
        return copy.deepcopy(frozen_environment)

    original_argv = sys.argv
    runtime_contract.capture_runtime_environment = _frozen_capture
    sys.argv = [str(script), *arguments]
    try:
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            if exc.code is None:
                return 0
            if isinstance(exc.code, int):
                return exc.code
            raise ContractError(str(exc.code)) from exc
        return 0
    finally:
        sys.argv = original_argv
        runtime_contract.capture_runtime_environment = original_capture


def main(argv: Sequence[str] | None = None) -> int:
    return run_existing_verifier(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())

"""Path-only adapter for the verified corrected O4a command set."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import AdapterError, StageAdapter, StageCommand, WorkflowPaths
from ..state import ArtifactReceipt


_CACHE_DIRECTORIES = {
    "primary": "o4a_corrected_v2",
    "cohort": "o4a_corrected_native_v1",
    "index": "o4a_corrected_native_index_v1",
    "native_calibration": "o4a_corrected_native_calibration_v2",
    "rescore": "o4a_corrected_native_rescore_v2",
    "thresholds": "o4a_corrected_native_thresholds_v1",
    "classification": "o4a_corrected_native_classification_v1",
    "taxonomy": "o4a_corrected_native_taxonomy_v1",
    "coincidence": "o4a_corrected_native_coincidence_v1",
    "pem": "o4a_corrected_native_pem_v1",
    "comparison": "o4a_corrected_final_comparison_v2",
}


@dataclass(frozen=True, slots=True)
class _CommandDefinition:
    script: str
    run_selector: tuple[str, ...]
    verify_selector: tuple[str, ...]
    root_arguments: tuple[tuple[str, str], ...] = ()
    raw_root: bool = False
    device: bool = False


_DEFINITIONS = {
    "PREFLIGHT": _CommandDefinition(
        "scripts/verify_dante_light_release.py",
        ("--stage", "operational"),
        ("--stage", "operational"),
    ),
    "ACQUIRE": _CommandDefinition(
        "scripts/run_dante_o4a_corrected.py",
        ("--stage", "acquire"),
        ("--stage", "verify-inputs"),
        (("--external-root", "primary"),),
    ),
    "CALIBRATE": _CommandDefinition(
        "scripts/run_dante_o4a_corrected.py",
        ("--stage", "calibrate-primary"),
        ("--stage", "verify-calibration"),
        (("--external-root", "primary"),),
        raw_root=True,
        device=True,
    ),
    "SCAN": _CommandDefinition(
        "scripts/run_dante_o4a_corrected.py",
        ("--stage", "scan-primary"),
        ("--stage", "verify-scan"),
        (("--external-root", "primary"),),
        raw_root=True,
        device=True,
    ),
    "COHORT": _CommandDefinition(
        "scripts/run_dante_o4a_corrected.py",
        ("--stage", "freeze-native-cohort"),
        ("--stage", "verify-native-cohort"),
        (
            ("--external-root", "primary"),
            ("--native-external-root", "cohort"),
        ),
        raw_root=True,
    ),
    "INDEX": _CommandDefinition(
        "scripts/run_dante_o4a_corrected.py",
        ("--stage", "build-native-index"),
        ("--stage", "verify-native-index"),
        (
            ("--external-root", "primary"),
            ("--native-external-root", "cohort"),
            ("--native-index-external-root", "index"),
        ),
        raw_root=True,
        device=True,
    ),
    "NATIVE_CALIBRATION": _CommandDefinition(
        "scripts/run_dante_o4a_native_calibration.py",
        ("--stage", "freeze"),
        ("--stage", "verify"),
        (
            ("--primary-external-root", "primary"),
            ("--native-external-root", "cohort"),
            ("--external-root", "native_calibration"),
        ),
        raw_root=True,
        device=True,
    ),
    "RESCORE": _CommandDefinition(
        "scripts/run_dante_o4a_native_rescore_v2.py",
        ("--stage", "run"),
        ("--stage", "verify"),
        (
            ("--primary-external-root", "primary"),
            ("--native-external-root", "cohort"),
            ("--calibration-external-root", "native_calibration"),
            ("--index-external-root", "index"),
            ("--external-root", "rescore"),
        ),
        raw_root=True,
        device=True,
    ),
    "THRESHOLDS": _CommandDefinition(
        "scripts/run_dante_o4a_native_thresholds.py",
        ("--stage", "run"),
        ("--stage", "verify"),
        (
            ("--primary-external-root", "primary"),
            ("--native-external-root", "cohort"),
            ("--calibration-external-root", "native_calibration"),
            ("--index-external-root", "index"),
            ("--rescore-external-root", "rescore"),
            ("--external-root", "thresholds"),
        ),
        device=True,
    ),
    "CLASSIFY": _CommandDefinition(
        "scripts/run_dante_o4a_native_classification.py",
        ("--stage", "run"),
        ("--stage", "verify"),
        (
            ("--primary-external-root", "primary"),
            ("--native-external-root", "cohort"),
            ("--calibration-external-root", "native_calibration"),
            ("--index-external-root", "index"),
            ("--rescore-external-root", "rescore"),
            ("--threshold-external-root", "thresholds"),
            ("--external-root", "classification"),
        ),
        device=True,
    ),
    "TAXONOMY": _CommandDefinition(
        "scripts/run_dante_o4a_native_taxonomy.py",
        ("--stage", "run"),
        ("--stage", "verify"),
        (
            ("--primary-external-root", "primary"),
            ("--classification-external-root", "classification"),
            ("--external-root", "taxonomy"),
        ),
        device=True,
    ),
    "COINCIDENCE": _CommandDefinition(
        "scripts/run_dante_o4a_native_coincidence.py",
        ("--stage", "run"),
        ("--stage", "verify"),
        (
            ("--primary-external-root", "primary"),
            ("--classification-external-root", "classification"),
            ("--index-external-root", "index"),
            ("--external-root", "coincidence"),
        ),
        raw_root=True,
        device=True,
    ),
    "PEM": _CommandDefinition(
        "scripts/run_dante_o4a_native_pem.py",
        ("--stage", "run"),
        ("--stage", "verify"),
        (
            ("--coincidence-external-root", "coincidence"),
            ("--classification-external-root", "classification"),
            ("--external-root", "pem"),
        ),
        raw_root=True,
    ),
    "COMPARE": _CommandDefinition(
        "scripts/run_dante_o4a_final_comparison.py",
        ("--stage", "run"),
        ("--stage", "verify"),
        (("--external-root", "comparison"),),
    ),
    "REPORT": _CommandDefinition(
        "scripts/run_dante_o4a_final_impact_attribution.py",
        (),
        (),
    ),
}


class O4aCorrectedAdapter(StageAdapter):
    """Build exact corrected-O4a CLI calls with no metric translation."""

    @staticmethod
    def cache_roots(paths: WorkflowPaths) -> dict[str, Path]:
        return {
            name: paths.cache_root / directory
            for name, directory in _CACHE_DIRECTORIES.items()
        }

    def build_command(
        self, stage: str, action: str, paths: WorkflowPaths
    ) -> StageCommand:
        if action not in {"run", "verify"}:
            raise AdapterError(f"unsupported stage action: {action}")
        try:
            definition = _DEFINITIONS[stage]
            self.spec.stage(stage)
        except (KeyError, ValueError) as exc:
            raise AdapterError(f"unsupported corrected O4a stage: {stage}") from exc
        script_path = paths.repository_root / definition.script
        if not script_path.is_file():
            raise AdapterError(f"corrected O4a CLI is absent: {script_path}")
        selector = (
            definition.run_selector if action == "run" else definition.verify_selector
        )
        argv = [self.python_executable, definition.script, *selector]
        roots = self.cache_roots(paths)
        for flag, root_name in definition.root_arguments:
            argv.extend((flag, str(roots[root_name])))
        if definition.raw_root:
            argv.extend(("--raw-root", str(paths.raw_root)))
        if definition.device:
            argv.extend(("--device", "cuda"))
        command = StageCommand(
            stage=stage,
            action=action,
            argv=tuple(argv),
            cwd=paths.repository_root,
            scientific_config_digests=self.scientific_digests_for_stage(stage),
        )
        if action == "verify":
            self.assert_verify_command_matches_contract(command)
        return command

    def index_window_manifest_receipt(
        self, cohort_ledger: Path
    ) -> ArtifactReceipt:
        """Bind INDEX consumption to the already frozen cohort ledger bytes."""

        return self.artifact_receipt("index_window_manifest", cohort_ledger)

    def cohort_manifest_receipt_from_verifier(
        self, verifier_payload: Mapping[str, Any]
    ) -> ArtifactReceipt:
        """Resolve the verified cohort ledger without opening scientific rows."""

        run_dir = verifier_payload.get("run_dir")
        ledger = verifier_payload.get("ledger")
        if not isinstance(run_dir, str) or not run_dir.strip():
            raise AdapterError("cohort verifier did not declare a run directory")
        if not isinstance(ledger, Mapping):
            raise AdapterError("cohort verifier did not declare a ledger")
        filename = ledger.get("filename")
        declared_sha256 = ledger.get("sha256")
        if not isinstance(filename, str) or not filename.strip():
            raise AdapterError("cohort verifier ledger filename is absent")
        if Path(filename).name != filename:
            raise AdapterError("cohort verifier ledger filename is not a basename")
        if not isinstance(declared_sha256, str):
            raise AdapterError("cohort verifier ledger digest is absent")
        path = Path(run_dir).resolve() / filename
        receipt = self.artifact_receipt("native_cohort_manifest", path)
        if receipt.sha256 != declared_sha256:
            raise AdapterError(
                "cohort verifier ledger digest does not match the resolved bytes"
            )
        return receipt

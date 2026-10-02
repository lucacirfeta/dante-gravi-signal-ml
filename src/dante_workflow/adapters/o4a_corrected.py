"""Path-only adapter for the verified corrected O4a command set."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import AdapterError, StageAdapter, StageCommand, WorkflowPaths
from ..schema import WorkflowSpec
from ..input_preflight import InputPreflightBinding
from ..input_coverage import InputCoverageBinding, InputCoverageError
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
    static_verify: bool = False


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
        static_verify=True,
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
        static_verify=True,
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
        static_verify=True,
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
        static_verify=True,
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
        static_verify=True,
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
        static_verify=True,
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
        static_verify=True,
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
        static_verify=True,
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

    observing_run = "O4a"
    detectors = ("H1", "L1")

    def __init__(
        self, spec: WorkflowSpec, *, python_executable: str = "python"
    ) -> None:
        if spec.adapter != "o4a_corrected":
            raise AdapterError("O4a adapter requires the o4a_corrected contract")
        if spec.graph_profile is not None:
            profile = spec.graph_profile
            if (
                profile.observing_run != self.observing_run
                or profile.detectors != self.detectors
            ):
                raise AdapterError(
                    "O4a adapter cannot execute another run/detector profile"
                )
            if {stage.name for stage in spec.stages} != set(_DEFINITIONS):
                raise AdapterError("O4a adapter requires its complete executable graph")
        super().__init__(spec, python_executable=python_executable)

    @staticmethod
    def cache_roots(paths: WorkflowPaths) -> dict[str, Path]:
        return {
            name: paths.cache_root / directory
            for name, directory in _CACHE_DIRECTORIES.items()
        }

    def input_preflight_binding(self) -> InputPreflightBinding:
        return InputPreflightBinding(
            config_ref="protocol",
            seal_field="protocol_digest",
            declarations={
                "analysis_duration_s": ("representation", "analysis_duration_s"),
                "sample_rate_hz": ("representation", "sample_rate_hz"),
                "left_context_s": ("scientific_change", "left_context_s"),
                "right_context_s": ("scientific_change", "right_context_s"),
                "incomplete_context": ("scientific_change", "incomplete_context"),
                "population_scope": (
                    "scientific_boundary",
                    "population_is_frozen_local_raw_mirror",
                ),
                "scan_identity_sha256": (
                    "scan_population",
                    "eligible_identity_jsonl_sha256",
                ),
                "calibration_identity_sha256": (
                    "calibration_population",
                    "identity_jsonl_sha256",
                ),
            },
            references={
                role: ("source_references", role)
                for role in (
                    "raw_manifest",
                    "dq_snapshot",
                    "canonical_runtime",
                    "reference_artifacts",
                    "raw_window_validity_audit",
                )
            },
        )

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
        if action == "verify" and definition.static_verify:
            argv = [
                self.python_executable,
                "scripts/verify_dante_existing.py",
                definition.script,
                *selector,
            ]
        else:
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

    def input_coverage_binding(self) -> InputCoverageBinding:
        return InputCoverageBinding(
            population="FROZEN_PRIMARY_SCAN_LOCAL_MIRROR",
            selection_policy="ORIGINAL_SELECTOR_CONTEXT_AND_RETAINED_RAW_VALIDITY_NO_NEW_DQ_FILTER",
            expected_counts=("scan_population", "eligible_counts"),
            expected_identity_sha256=(
                "scan_population",
                "eligible_identity_jsonl_sha256",
            ),
            references={
                name: ("source_references", name)
                for name in ("protocol_implementation", "overlapping_raw_span_audit")
            },
            window_fields={
                "detector": ("detector",),
                "analysis_start": ("analysis_gps_start",),
                "duration": ("duration_s",),
                "context_interval": ("required_padded_interval",),
            },
            manifest_fields={
                "detector": ("detector",),
                "start": ("gps_start",),
                "end": ("gps_end",),
            },
        )

    def iter_input_coverage(self, root: Path):
        # Load the unchanged scientific selector from the explicit checkout.
        # No protocol rebuilding, calibration HDF5, runtime/CUDA probe or writer.
        import importlib
        import sys

        original_path = sys.path[:]
        try:
            sys.path.insert(0, str(root.resolve()))
            module = importlib.import_module("src.dante_light.o4a_corrected_protocol")
        except ImportError as exc:
            raise InputCoverageError(
                "coverage replay requires the existing scientific environment"
            ) from exc
        finally:
            sys.path[:] = original_path
        if (
            Path(module.__file__).resolve()
            != root.resolve() / "src/dante_light/o4a_corrected_protocol.py"
        ):
            raise InputCoverageError(
                "coverage selector was imported from another checkout"
            )
        return module.iter_scan_identities(root)

    def index_window_manifest_receipt(self, cohort_ledger: Path) -> ArtifactReceipt:
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

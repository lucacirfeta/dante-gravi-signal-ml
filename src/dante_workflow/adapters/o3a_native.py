"""Native O3a CLI/receipt interface, not an enabled complete-workflow profile.

The adapter factory deliberately does not register this interface yet. Initial
acquisition/acceptance verification and a complete production graph are separate
gates. Constructing commands never executes them or approves new science.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .base import AdapterError, StageAdapter, StageCommand, WorkflowPaths
from ..schema import WorkflowSpec, canonical_json_sha256
from ..state import ArtifactReceipt


@dataclass(frozen=True, slots=True)
class NativeCommandDefinition:
    script: str
    config_path: str
    run_selector: tuple[str, ...] = ()
    verify_selector: tuple[str, ...] = ("--verify",)


NATIVE_COMMANDS = MappingProxyType(
    {
        "COHORT": NativeCommandDefinition(
            "scripts/run_dante_o3a_native_cohort.py",
            "config/dante_o3a_native_cohort_v1.json",
        ),
        "INDEX": NativeCommandDefinition(
            "scripts/run_dante_o3a_native_index.py",
            "config/dante_o3a_native_index_v1.json",
        ),
        "NATIVE_CALIBRATION": NativeCommandDefinition(
            "scripts/freeze_dante_o3a_native_calibration_cohort.py",
            "config/dante_o3a_native_calibration_cohort_v1.json",
        ),
        "RESCORE": NativeCommandDefinition(
            "scripts/run_dante_o3a_native_rescore.py",
            "config/dante_o3a_native_rescore_v3.json",
            ("--run",),
        ),
        "THRESHOLDS": NativeCommandDefinition(
            "scripts/run_dante_o3a_native_thresholds.py",
            "config/dante_o3a_native_thresholds_v1.json",
            ("--run",),
        ),
        "CLASSIFY": NativeCommandDefinition(
            "scripts/run_dante_o3a_native_classification.py",
            "config/dante_o3a_native_classification_v1.json",
            ("--run",),
        ),
        "TAXONOMY": NativeCommandDefinition(
            "scripts/run_dante_o3a_native_taxonomy.py",
            "config/dante_o3a_native_taxonomy_v1.json",
            ("--run",),
        ),
        "COINCIDENCE": NativeCommandDefinition(
            "scripts/run_dante_o3a_native_coincidence.py",
            "config/dante_o3a_native_coincidence_v2.json",
            ("--run",),
        ),
        "PEM": NativeCommandDefinition(
            "scripts/run_dante_o3a_native_pem.py",
            "config/dante_o3a_native_pem_v1.json",
            ("--stage", "run"),
            ("--stage", "verify"),
        ),
    }
)


class O3aNativeAdapter(StageAdapter):
    """Existing native interfaces only; factory activation remains gated."""

    observing_run = "O3a"
    detectors = ("H1", "L1")

    def __init__(self, spec: WorkflowSpec, *, python_executable: str = "python"):
        profile = spec.graph_profile
        if (
            spec.schema_version != 2
            or spec.adapter != "o3a_native_diagnostic"
            or profile is None
            or profile.observing_run != self.observing_run
            or profile.detectors != self.detectors
        ):
            raise AdapterError(
                "native O3a interface requires an explicit v2 O3a H1/L1 profile"
            )
        if not spec.stages or any(
            stage.name not in NATIVE_COMMANDS for stage in spec.stages
        ):
            raise AdapterError("unsupported native O3a graph stage")
        for stage in spec.stages:
            definition = NATIVE_COMMANDS[stage.name]
            bound_paths = {
                spec.scientific_configs[name].path for name in stage.config_refs
            }
            if definition.config_path not in bound_paths:
                raise AdapterError(
                    f"native O3a stage config binding differs: {stage.name}"
                )
            expected = ("python", definition.script, *definition.verify_selector)
            if stage.verifier_command != expected:
                raise AdapterError(f"native O3a verifier prefix differs: {stage.name}")
        super().__init__(spec, python_executable=python_executable)

    def build_command(
        self, stage: str, action: str, paths: WorkflowPaths
    ) -> StageCommand:
        if action not in {"run", "verify"}:
            raise AdapterError(f"unsupported native O3a action: {action}")
        try:
            definition = NATIVE_COMMANDS[stage]
            self.spec.stage(stage)
        except (KeyError, ValueError) as exc:
            raise AdapterError(f"unsupported native O3a stage: {stage}") from exc
        if not (paths.repository_root / definition.script).is_file():
            raise AdapterError(f"native O3a CLI is absent: {definition.script}")
        selector = (
            definition.run_selector if action == "run" else definition.verify_selector
        )
        native_root = paths.cache_root / "o3a_native_v1"
        argv = [
            self.python_executable,
            definition.script,
            *selector,
            "--external-root",
            str(native_root),
        ]
        if stage == "COHORT":
            argv.extend(
                (
                    "--primary-external-root",
                    str(native_root),
                    "--raw-root",
                    str(paths.raw_root),
                )
            )
        command = StageCommand(
            stage,
            action,
            tuple(argv),
            paths.repository_root,
            self.scientific_digests_for_stage(stage),
        )
        if action == "verify":
            self.assert_verify_command_matches_contract(command)
        return command

    def index_window_manifest_receipt(self, cohort_ledger: Path) -> ArtifactReceipt:
        """Record the exact input; actual consumption still requires INDEX verify."""
        return self.artifact_receipt("index_window_manifest", cohort_ledger)

    def cohort_manifest_receipt_from_verifier(
        self, verifier_payload: Mapping[str, Any]
    ) -> ArtifactReceipt:
        summary = verifier_payload.get("summary")
        directory = verifier_payload.get("run_dir")
        if (
            not isinstance(summary, Mapping)
            or not isinstance(directory, str)
            or not directory.strip()
        ):
            raise AdapterError(
                "native O3a cohort verifier must declare nested summary and run_dir"
            )
        body = dict(summary)
        declared = body.pop("artifact_digest", None)
        try:
            actual = canonical_json_sha256(body)
        except (TypeError, ValueError) as exc:
            raise AdapterError("native O3a cohort summary is not finite JSON") from exc
        if (
            declared != actual
            or summary.get("status") != "PASS_FROZEN_O3A_NATIVE_COHORT"
        ):
            raise AdapterError("native O3a cohort summary seal/status is invalid")
        ledger = summary.get("ledger")
        if not isinstance(ledger, Mapping):
            raise AdapterError("native O3a cohort ledger declaration is absent")
        filename = ledger.get("filename")
        if (
            not isinstance(filename, str)
            or not filename.strip()
            or filename in {".", ".."}
            or any(character in filename for character in ("/", "\\", ":"))
        ):
            raise AdapterError("native O3a cohort ledger filename must be a basename")
        root = Path(directory).resolve()
        path = (root / filename).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise AdapterError(
                "native O3a cohort ledger path escapes run directory"
            ) from exc
        receipt = self.artifact_receipt("native_cohort_manifest", path)
        if receipt.sha256 != ledger.get("sha256"):
            raise AdapterError(
                "native O3a cohort ledger digest differs from resolved bytes"
            )
        return receipt

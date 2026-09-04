"""Adapter boundary between orchestration and existing scientific CLIs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..schema import WorkflowSpec, canonical_json_sha256
from ..state import ArtifactReceipt


class AdapterError(RuntimeError):
    """Raised when a stage cannot be represented without changing its CLI."""


@dataclass(frozen=True, slots=True)
class WorkflowPaths:
    repository_root: Path
    raw_root: Path
    cache_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_root", self.repository_root.resolve())
        object.__setattr__(self, "raw_root", self.raw_root.resolve())
        object.__setattr__(self, "cache_root", self.cache_root.resolve())


@dataclass(frozen=True, slots=True)
class StageCommand:
    stage: str
    action: str
    argv: tuple[str, ...]
    cwd: Path
    scientific_config_digests: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.action not in {"run", "verify"}:
            raise ValueError("stage command action must be run or verify")
        if not self.argv or any(not token for token in self.argv):
            raise ValueError("stage command argv must contain non-empty tokens")
        object.__setattr__(self, "cwd", self.cwd.resolve())
        object.__setattr__(
            self,
            "scientific_config_digests",
            MappingProxyType(dict(self.scientific_config_digests)),
        )

    @property
    def command_digest(self) -> str:
        return canonical_json_sha256(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        value = {
            "stage": self.stage,
            "action": self.action,
            "argv": list(self.argv),
            "cwd": str(self.cwd),
            "scientific_config_digests": dict(self.scientific_config_digests),
        }
        if include_digest:
            value["command_digest"] = self.command_digest
        return value


class StageAdapter(ABC):
    """Construct commands and receipts without interpreting scientific data."""

    def __init__(self, spec: WorkflowSpec, *, python_executable: str = "python") -> None:
        if not python_executable.strip():
            raise ValueError("python_executable must be non-empty")
        self.spec = spec
        self.python_executable = python_executable

    @abstractmethod
    def build_command(
        self, stage: str, action: str, paths: WorkflowPaths
    ) -> StageCommand:
        """Return the unchanged scientific CLI plus path-only arguments."""

    def scientific_digests_for_stage(self, stage: str) -> Mapping[str, str]:
        stage_spec = self.spec.stage(stage)
        return MappingProxyType(
            {
                name: self.spec.scientific_configs[name].sha256
                for name in stage_spec.config_refs
            }
        )

    @staticmethod
    def artifact_receipt(name: str, path: Path) -> ArtifactReceipt:
        path = path.resolve()
        if not path.is_file():
            raise AdapterError(f"stage artifact is absent: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return ArtifactReceipt(name=name, path=str(path), sha256=digest.hexdigest())

    def assert_verify_command_matches_contract(self, command: StageCommand) -> None:
        if command.action != "verify":
            raise AdapterError("only verifier commands can be checked against the contract")
        expected = self.spec.stage(command.stage).verifier_command
        actual_prefix = command.argv[: len(expected)]
        normalized = ("python", *actual_prefix[1:])
        if normalized != expected:
            raise AdapterError(
                f"stage {command.stage} verifier diverges from the frozen workflow spec"
            )

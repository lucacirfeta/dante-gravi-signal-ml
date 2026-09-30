"""Workflow adapters for existing, independently verified DANTE engines."""

from .base import AdapterError, StageAdapter, StageCommand, WorkflowPaths
from .o4a_corrected import O4aCorrectedAdapter
from ..schema import WorkflowSpec


def build_adapter(
    spec: WorkflowSpec, *, python_executable: str = "python"
) -> StageAdapter:
    """Dispatch only the contract's implemented adapter, never an O4a fallback."""

    if spec.adapter == "o4a_corrected":
        return O4aCorrectedAdapter(spec, python_executable=python_executable)
    raise AdapterError(f"unsupported workflow adapter: {spec.adapter!r}")

__all__ = [
    "AdapterError",
    "O4aCorrectedAdapter",
    "StageAdapter",
    "StageCommand",
    "WorkflowPaths",
    "build_adapter",
]

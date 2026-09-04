"""Run the frozen DANTE workflow without interpreting scientific outcomes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

from .adapters import O4aCorrectedAdapter, StageCommand, WorkflowPaths
from .schema import WorkflowSpec, canonical_json_sha256
from .state import (
    ArtifactReceipt,
    ExecutionLease,
    WorkflowLedger,
)


WORKFLOW_RUNS_DIRECTORY = "workflow_productization_v1"


class OrchestrationError(RuntimeError):
    """Raised when orchestration cannot preserve the frozen workflow contract."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    exit_status: int
    stdout: str
    stderr: str

    def __post_init__(self) -> None:
        if isinstance(self.exit_status, bool) or not isinstance(self.exit_status, int):
            raise ValueError("command exit status must be an integer")
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise ValueError("command output must be text")


CommandRunner = Callable[[StageCommand], CommandResult]


def subprocess_runner(command: StageCommand) -> CommandResult:
    completed = subprocess.run(
        command.argv,
        cwd=command.cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(value, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def repository_source_identity(repository_root: Path) -> dict[str, str]:
    """Bind a workflow run to both HEAD and tracked worktree modifications."""

    try:
        head = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        diff = subprocess.run(
            ("git", "diff", "--binary", "HEAD", "--"),
            cwd=repository_root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise OrchestrationError("could not bind workflow to the Git source tree") from exc
    if len(head) != 40 or any(character not in "0123456789abcdef" for character in head):
        raise OrchestrationError("Git HEAD is not a full lowercase commit identity")
    return {
        "git_head": head,
        "tracked_worktree_diff_sha256": _sha256_bytes(diff),
    }


class WorkflowOrchestrator:
    """Persistent, UI-independent worker for one frozen workflow contract."""

    def __init__(
        self,
        *,
        spec: WorkflowSpec,
        adapter: O4aCorrectedAdapter,
        paths: WorkflowPaths,
        runner: CommandRunner = subprocess_runner,
        source_identity: Mapping[str, str] | None = None,
        workflow_root: Path | None = None,
    ) -> None:
        if adapter.spec != spec:
            raise OrchestrationError("adapter and workflow specification differ")
        self.spec = spec
        self.adapter = adapter
        self.paths = paths
        self.runner = runner
        self.source_identity = dict(
            source_identity or repository_source_identity(paths.repository_root)
        )
        if not self.source_identity or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.source_identity.items()
        ):
            raise OrchestrationError("source identity must be a non-empty text mapping")
        self.commands = {
            stage: {
                action: adapter.build_command(stage, action, paths)
                for action in ("run", "verify")
            }
            for stage in spec.topological_stage_names()
        }
        self.run_contract = {
            "workflow_id": spec.workflow_id,
            "workflow_contract_digest": spec.contract_digest,
            "source_identity": self.source_identity,
            "paths": {
                "repository_root": str(paths.repository_root),
                "raw_root": str(paths.raw_root),
                "cache_root": str(paths.cache_root),
            },
            "stage_commands": {
                stage: {
                    action: command.command_digest
                    for action, command in actions.items()
                }
                for stage, actions in self.commands.items()
            },
        }
        self.run_key = canonical_json_sha256(self.run_contract)
        base = (workflow_root or paths.cache_root / WORKFLOW_RUNS_DIRECTORY).resolve()
        self.run_dir = base / f"workflow_{self.run_key}"
        self.ledger = WorkflowLedger.open(
            self.run_dir,
            spec=spec,
            run_key=self.run_key,
        )
        contract_path = self.run_dir / "run_contract.json"
        if contract_path.is_file():
            try:
                persisted = json.loads(contract_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise OrchestrationError("persisted run contract is corrupt") from exc
            if persisted != self.run_contract:
                raise OrchestrationError("persisted run contract does not match run key")
        else:
            _atomic_json(contract_path, self.run_contract)

    @classmethod
    def corrected_o4a(
        cls,
        *,
        spec: WorkflowSpec,
        paths: WorkflowPaths,
        runner: CommandRunner = subprocess_runner,
        source_identity: Mapping[str, str] | None = None,
        workflow_root: Path | None = None,
    ) -> "WorkflowOrchestrator":
        return cls(
            spec=spec,
            adapter=O4aCorrectedAdapter(spec),
            paths=paths,
            runner=runner,
            source_identity=source_identity,
            workflow_root=workflow_root,
        )

    def plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "WORKFLOW_PLAN",
            "workflow_id": self.spec.workflow_id,
            "run_key": self.run_key,
            "run_dir": str(self.run_dir),
            "contract_digest": self.spec.contract_digest,
            "stages": [
                {
                    "name": stage.name,
                    "dependencies": [
                        {
                            "stage": dependency.stage,
                            "gate": dependency.gate,
                            **(
                                {"artifact": dependency.artifact}
                                if dependency.artifact is not None
                                else {}
                            ),
                        }
                        for dependency in stage.dependencies
                    ],
                    "run_command_digest": self.commands[stage.name][
                        "run"
                    ].command_digest,
                    "verify_command_digest": self.commands[stage.name][
                        "verify"
                    ].command_digest,
                }
                for stage in self.spec.stages
            ],
        }

    def status(self) -> dict[str, Any]:
        stages: list[dict[str, Any]] = []
        for stage in self.spec.stages:
            state = self.ledger.stage_status(stage.name)
            item: dict[str, Any] = {"name": stage.name, "status": state}
            if state == "VERIFIED":
                item["artifacts"] = [
                    self.ledger.latest_verified_artifact(
                        stage.name, output
                    ).to_dict()
                    for output in stage.expected_outputs
                ]
            stages.append(item)
        return {
            "schema_version": 1,
            "status": "WORKFLOW_STATUS",
            "workflow_id": self.spec.workflow_id,
            "run_key": self.run_key,
            "run_dir": str(self.run_dir),
            "next_incomplete_stage": self.ledger.next_incomplete_stage(),
            "stages": stages,
        }

    @staticmethod
    def _json_object(text: str) -> dict[str, Any] | None:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def _record_index_window_manifest(
        self, lease: ExecutionLease, attempt: Any
    ) -> None:
        cohort = self.ledger.latest_verified_artifact(
            "COHORT", "native_cohort_manifest"
        )
        receipt = self.adapter.index_window_manifest_receipt(Path(cohort.path))
        if receipt.sha256 != cohort.sha256:
            raise OrchestrationError(
                "INDEX window manifest differs from the verified cohort bytes"
            )
        self.ledger.record_artifact(lease, attempt, receipt)

    def _stage_receipt(
        self,
        *,
        stage: str,
        attempt_id: str,
        run_result: CommandResult,
        verify_result: CommandResult,
        attempt_dir: Path,
    ) -> Path:
        verifier_payload = self._json_object(verify_result.stdout)
        receipt = {
            "schema_version": 1,
            "status": "VERIFIED_STAGE_RECEIPT",
            "workflow_id": self.spec.workflow_id,
            "run_key": self.run_key,
            "contract_digest": self.spec.contract_digest,
            "stage": stage,
            "attempt_id": attempt_id,
            "run_command_digest": self.commands[stage]["run"].command_digest,
            "verify_command_digest": self.commands[stage]["verify"].command_digest,
            "run_exit_status": run_result.exit_status,
            "verify_exit_status": verify_result.exit_status,
            "logs": {
                name: {
                    "path": str(attempt_dir / name),
                    "sha256": _sha256_file(attempt_dir / name),
                }
                for name in (
                    "run.stdout.txt",
                    "run.stderr.txt",
                    "verify.stdout.txt",
                    "verify.stderr.txt",
                )
            },
            **(
                {"verified_run_dir": verifier_payload["run_dir"]}
                if verifier_payload is not None
                and isinstance(verifier_payload.get("run_dir"), str)
                else {}
            ),
        }
        path = attempt_dir / "verified_stage_receipt.json"
        _atomic_json(path, receipt)
        return path

    def _execute_stage(self, lease: ExecutionLease, stage: str) -> dict[str, Any]:
        if self.ledger.stage_status(stage) == "VERIFIED":
            return {"stage": stage, "status": "SKIPPED_VERIFIED"}
        attempt = self.ledger.start_attempt(lease, stage)
        attempt_dir = self.run_dir / "attempts" / stage.lower() / attempt.attempt_id
        terminal = False
        try:
            attempt_dir.mkdir(parents=True, exist_ok=False)
            if stage == "INDEX":
                self._record_index_window_manifest(lease, attempt)
            run_result = self.runner(self.commands[stage]["run"])
            _write_text(attempt_dir / "run.stdout.txt", run_result.stdout)
            _write_text(attempt_dir / "run.stderr.txt", run_result.stderr)
            if run_result.exit_status != 0:
                self.ledger.finish_attempt(
                    lease,
                    attempt,
                    exit_status=run_result.exit_status,
                    verifier_verdict="NOT_RUN",
                )
                terminal = True
                return {"stage": stage, "status": "FAILED", "phase": "run"}
            verify_result = self.runner(self.commands[stage]["verify"])
            _write_text(attempt_dir / "verify.stdout.txt", verify_result.stdout)
            _write_text(attempt_dir / "verify.stderr.txt", verify_result.stderr)
            if verify_result.exit_status != 0:
                self.ledger.finish_attempt(
                    lease,
                    attempt,
                    exit_status=verify_result.exit_status,
                    verifier_verdict="FAIL",
                )
                terminal = True
                return {"stage": stage, "status": "FAILED", "phase": "verify"}

            receipt_path = self._stage_receipt(
                stage=stage,
                attempt_id=attempt.attempt_id,
                run_result=run_result,
                verify_result=verify_result,
                attempt_dir=attempt_dir,
            )
            expected = set(self.spec.stage(stage).expected_outputs)
            if stage == "COHORT":
                payload = self._json_object(verify_result.stdout)
                if payload is None:
                    raise OrchestrationError("COHORT verifier did not emit JSON")
                manifest = self.adapter.cohort_manifest_receipt_from_verifier(payload)
                self.ledger.record_artifact(lease, attempt, manifest)
                expected.remove("native_cohort_manifest")
            if stage == "INDEX":
                expected.remove("index_window_manifest")
            for output in sorted(expected):
                self.ledger.record_artifact(
                    lease,
                    attempt,
                    ArtifactReceipt(
                        name=output,
                        path=str(receipt_path),
                        sha256=_sha256_file(receipt_path),
                    ),
                )
            self.ledger.finish_attempt(
                lease, attempt, exit_status=0, verifier_verdict="PASS"
            )
            terminal = True
            return {"stage": stage, "status": "VERIFIED"}
        except KeyboardInterrupt:
            self.ledger.interrupt_attempt(
                lease, attempt, reason="CONTROLLED_WORKER_INTERRUPT"
            )
            terminal = True
            raise
        except Exception as exc:
            if not terminal:
                self.ledger.finish_attempt(
                    lease, attempt, exit_status=-1, verifier_verdict="FAIL"
                )
            raise OrchestrationError(f"stage {stage} orchestration failed") from exc

    def execute(
        self,
        *,
        through_stage: str | None = None,
        repair_stage: str | None = None,
    ) -> dict[str, Any]:
        ordered = self.spec.topological_stage_names()
        if through_stage is not None and through_stage not in ordered:
            raise OrchestrationError(f"unknown through stage: {through_stage}")
        if repair_stage is not None and repair_stage not in ordered:
            raise OrchestrationError(f"unknown repair stage: {repair_stage}")
        if through_stage is not None and repair_stage is not None:
            raise OrchestrationError("through-stage and repair-stage are mutually exclusive")
        if repair_stage is not None:
            if self.ledger.stage_status(repair_stage) == "VERIFIED":
                raise OrchestrationError("repair stage is already verified")
            selected: Sequence[str] = (repair_stage,)
        else:
            stop = ordered.index(through_stage) + 1 if through_stage else len(ordered)
            selected = ordered[:stop]

        lease = self.ledger.acquire_lease()
        results: list[dict[str, Any]] = []
        try:
            for stage in selected:
                result = self._execute_stage(lease, stage)
                results.append(result)
                if result["status"] == "FAILED":
                    break
        finally:
            if self.ledger.lease_path.is_file():
                self.ledger.release_lease(lease)
        return {
            "schema_version": 1,
            "status": "WORKFLOW_EXECUTION",
            "workflow_id": self.spec.workflow_id,
            "run_key": self.run_key,
            "results": results,
            "workflow_status": self.status(),
        }

    def verify_completed(self) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for stage in self.spec.topological_stage_names():
            if self.ledger.stage_status(stage) != "VERIFIED":
                continue
            result = self.runner(self.commands[stage]["verify"])
            results.append(
                {
                    "stage": stage,
                    "verdict": "PASS" if result.exit_status == 0 else "FAIL",
                    "exit_status": result.exit_status,
                }
            )
            if result.exit_status != 0:
                break
        return {
            "schema_version": 1,
            "status": "WORKFLOW_REVERIFICATION",
            "workflow_id": self.spec.workflow_id,
            "run_key": self.run_key,
            "verdict": (
                "PASS"
                if results
                and all(result["verdict"] == "PASS" for result in results)
                else "FAIL"
            ),
            "results": results,
        }

"""Bounded public technical replay; never a corrected O4a release receipt."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.artifact_manager import download_reference_bundle, install_reference_bundle  # noqa: E402
from src.dante_light.contracts import ContractError, canonical_json_sha256  # noqa: E402
from src.dante_light.evidence import (  # noqa: E402
    atomic_json, build_public_replay_evidence, git_checkout_provenance, validate_run_directory,
)
from src.dante_light.sources.files import ReplayManifestSource  # noqa: E402

CONFIG = ROOT / "config/dante_workflow_public_smoke_v1.json"
SCOPE = "technical_public_replay_not_corrected_o4a_release"


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load_config(path=CONFIG, root=ROOT):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(config) != {"schema_version", "scope", "role", "limit_per_detector", "timeout_seconds", "engines", "references"}:
        raise ContractError("unknown or missing smoke config fields")
    if config["schema_version"] != 1 or config["scope"] != SCOPE:
        raise ContractError("unsupported smoke scope")
    if config["engines"] != ["canonical", "shared_encoder_score_only"] or config["role"] != "background_stratified":
        raise ContractError("unsupported smoke engines or role")
    for name in ("limit_per_detector", "timeout_seconds"):
        if type(config[name]) is not int or config[name] <= 0:
            raise ContractError(f"invalid {name}")
    required = {"config/dante_light_replay_v1.json", "config/dante_light_replay_v1.jsonl", "config/dante_light_epochs_v1.json", "config/reference_artifacts.json"}
    if set(config["references"]) != required:
        raise ContractError("smoke reference set changed")
    for relative, digest in config["references"].items():
        if sha(root / relative) != digest:
            raise ContractError(f"smoke reference mismatch: {relative}")
    return config


@contextmanager
def exclusive_lock(directory):
    """OS-owned lock: released on process death, persistent file is not a lease."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "execution.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def verify_files(files, root=ROOT):
    for relative, digest in files.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or sha(path) != digest:
            raise ContractError(f"smoke artifact changed or absent: {relative}")


def replay_command(config, directory, engine, device):
    return [sys.executable, "main.py", "dante-light-replay", "--output-dir", str(directory),
            "--role", config["role"], "--limit-per-detector", str(config["limit_per_detector"]),
            "--engine", engine, "--device", device, "--strain-source", "gwosc-only",
            "--cat1-mode", "gwosc"]


def run(mode, device):
    config = load_config()
    checkout = git_checkout_provenance(ROOT)
    tasks = ReplayManifestSource(ROOT / "config/dante_light_replay_v1.json", root=ROOT).tasks(
        roles={config["role"]}, limit_per_detector=config["limit_per_detector"],
    )
    packages = {}
    for name in ("torch", "torchvision", "gwpy", "gwosc", "numpy", "scipy", "h5py", "matplotlib", "astropy", "pillow"):
        packages[name] = importlib.metadata.version(name)
    identity = {"config": config, "commit": checkout["commit"], "device": device,
                "python": sys.version, "executable_sha256": sha(sys.executable),
                "platform": platform.platform(), "packages": packages,
                "windows": [task.window.to_dict() for task in tasks]}
    key = canonical_json_sha256(identity)
    directory = ROOT / "artifacts/dante_workflow/public_smoke_v1" / key
    if mode == "plan":
        return {"status": "SMOKE_PLAN", "scope": SCOPE, "run_key": key, "identity": identity}
    with exclusive_lock(directory):
        receipt_path = directory / "technical_receipt.json"
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt["identity"] != identity or receipt["scope"] != SCOPE:
                raise ContractError("smoke identity changed")
            verify_files(receipt["files"])
            return {"status": "SKIPPED_VERIFIED_TECHNICAL_SMOKE", "run_key": key, "receipt": str(receipt_path)}
        if mode == "verify":
            raise ContractError("technical smoke receipt is absent")
        bundle = download_reference_bundle(directory / "reference_bundle.zip")
        install_reference_bundle(bundle, project_root=ROOT)
        selected = {}
        for engine in config["engines"]:
            checkpoint = directory / f"{engine}.json"
            if checkpoint.exists():
                saved = json.loads(checkpoint.read_text(encoding="utf-8"))
                verify_files(saved["files"])
                selected[engine] = ROOT / saved["directory"]
                validate_run_directory(selected[engine], root=ROOT, expected_engine=engine, prospective=False)
                continue
            attempt = directory / engine / uuid.uuid4().hex
            attempt.mkdir(parents=True)
            try:
                with (attempt / "stdout.log").open("w") as out, (attempt / "stderr.log").open("w") as err:
                    subprocess.run(replay_command(config, attempt, engine, device), cwd=ROOT,
                                   stdout=out, stderr=err, check=True, timeout=config["timeout_seconds"])
                verified = validate_run_directory(attempt, root=ROOT, expected_engine=engine, prospective=False)
                if set(verified.records) != {task.window.window_id for task in tasks}:
                    raise ContractError("smoke selected identities mismatch")
                files = {p.relative_to(ROOT).as_posix(): sha(p) for p in attempt.iterdir() if p.is_file()}
                atomic_json(checkpoint, {"directory": attempt.relative_to(ROOT).as_posix(), "files": files})
                selected[engine] = attempt
            except Exception as exc:
                atomic_json(attempt / "failure.json", {"status": "FAILED_TECHNICAL_SMOKE", "error_type": type(exc).__name__, "error": str(exc)})
                raise
        evidence_path = directory / "paired_replay_evidence.json"
        evidence = build_public_replay_evidence(selected["canonical"], selected["shared_encoder_score_only"],
                                               bundle_path=bundle, output_path=evidence_path, root=ROOT, mode="public")
        report = directory / "report.md"
        report.write_text(f"# Technical public smoke\n\nPASS: {evidence['coverage']['windows']} public windows, paired existing engines.\n\n"
                          "Not a corrected O4a release, full 15-stage validation, fresh-install proof, or scientific discovery.\n"
                          "No calibration or threshold estimation was performed. Legacy replay decisions are not corrected O4a classifications.\n",
                          encoding="utf-8", newline="\n")
        files = {p.relative_to(ROOT).as_posix(): sha(p) for p in (evidence_path, report, bundle)}
        for engine in config["engines"]:
            checkpoint = directory / f"{engine}.json"
            files[checkpoint.relative_to(ROOT).as_posix()] = sha(checkpoint)
            files.update(json.loads(checkpoint.read_text())["files"])
        atomic_json(receipt_path, {"status": "PASS_TECHNICAL_SMOKE", "scope": SCOPE, "identity": identity, "files": files})
        return {"status": "PASS_TECHNICAL_SMOKE", "run_key": key, "receipt": str(receipt_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("plan", "local", "verify"), default="plan")
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.mode, args.device), indent=2))
        return 0
    except (OSError, ValueError, ContractError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError) as exc:
        print(json.dumps({"status": "TECHNICAL_SMOKE_ERROR", "error_type": type(exc).__name__, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

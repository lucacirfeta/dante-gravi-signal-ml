"""Isolated byte-copy/I/O probe. Never executes or qualifies scientific stages."""

import argparse
import json
from pathlib import Path
import shutil
import time

from .calibration_admission import _pinned
from .calibration_recovery import read_sealed, sealed
from .expanded_context_replay import quiet
from .input_preflight import _hash


BOUNDARY = {
    "io_probe_only": True,
    "scientific_execution_ready": False,
    "full_calibration_verified": False,
    "default_provider_replaced": False,
    "o4b_launch_allowed": False,
}


def confined(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("absolute non-symlink path required")
    return path.resolve()


def separate(source, workspace):
    source, workspace = confined(source), confined(workspace)
    if (
        source == workspace
        or source.is_relative_to(workspace)
        or workspace.is_relative_to(source)
    ):
        raise ValueError("probe workspace overlaps preserved source")
    return source, workspace


def new_report(path, body):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(sealed(body), stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def inventory(directory):
    """Full byte inventory, not a scientific sample or metadata-hash substitute."""
    quiet(directory)
    rows = []
    for path in sorted(directory.rglob("*")):
        confined(path)
        if path.is_file():
            rows.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": _hash(path),
                }
            )
        elif not path.is_dir():
            raise ValueError("non-regular source entry")
    if not rows:
        raise ValueError("empty source inventory")
    quiet(directory)
    return rows


def load_policy(root, config, config_sha):
    policy = json.loads(_pinned(confined(config), config_sha).read_text())
    if (
        type(policy.get("schema_version")) is not int
        or policy.get("schema_version") != 1
        or policy.get("status") != "ISOLATED_STORAGE_PROBE_V1"
        or policy.get("boundary") != BOUNDARY
        or any(type(v) is not bool for v in policy["boundary"].values())
        or type(policy.get("repetitions")) is not int
        or policy["repetitions"] < 1
    ):
        raise ValueError("invalid I/O-only policy")
    root = confined(root)
    for ref in policy["source_pins"]:
        _pinned(root_file(root, ref["path"]), ref["sha256"])
    # Inherit verified parent hashes from the unmodified productive profile.
    ref = policy["productive_profile"]
    profile = json.loads(
        _pinned(root_file(root, ref["path"]), ref["sha256"]).read_text()
    )
    parent = profile["preprocessing_parent"]
    source, workspace = separate(policy["source_directory"], policy["workspace"])
    quiet(source)
    for name in ("summary", "verification"):
        _pinned(source / f"{name}.json", parent[f"{name}_sha256"])
        evidence = read_sealed(source / f"{name}.json")
        expected = {
            "summary": "PASS_COMPLETE_EXPANDED_CALIBRATION_PREPROCESSING_ONLY",
            "verification": "PASS_VERIFIED_EXPANDED_CALIBRATION_PREPROCESSING_ONLY",
        }[name]
        if evidence.get("status") != expected:
            raise ValueError("verified preprocessing parent required")
    return policy


def root_file(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("policy reference escapes repository")
    path = confined(root / relative)
    if not path.is_relative_to(root):
        raise ValueError("policy reference escapes repository")
    return path


def layout(directory):
    return sorted(
        confined(p).relative_to(directory).as_posix()
        for p in directory.rglob("*")
        if p.is_dir()
    )


def mirror(source, workspace):
    """New-only destination; interruption/failure stays on disk, never resumed."""
    source, workspace = separate(source, workspace)
    quiet(source)
    workspace.mkdir(parents=True, exist_ok=False)
    target = workspace / "parent"
    target.mkdir()
    try:
        rows = inventory(source)
        directories = layout(source)
        for relative in directories:
            confined(target / relative).mkdir(parents=True, exist_ok=True)
        required = sum(r["size_bytes"] for r in rows)
        if shutil.disk_usage(workspace).free <= required:
            raise ValueError("insufficient space for complete byte mirror")
        for row in rows:
            original = source / row["path"]
            copy = confined(target / row["path"])
            _pinned(original, row["sha256"])
            with original.open("rb") as reader, copy.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
            _pinned(copy, row["sha256"])
            _pinned(original, row["sha256"])
        if inventory(source) != rows or inventory(target) != rows:
            raise ValueError("mirror/source changed during copy")
        if layout(source) != directories or layout(target) != directories:
            raise ValueError("directory inventory differs")
        new_report(
            workspace / "mirror.json",
            {
                "status": "BYTE_IDENTICAL_IO_MIRROR_ONLY",
                "source": str(source),
                "target": str(target),
                "rows": rows,
                "directories": directories,
                "total_bytes": required,
                "boundary": BOUNDARY,
            },
        )
    except BaseException as exc:
        new_report(
            workspace / "failure.json",
            {"error": type(exc).__name__, "message": str(exc), "boundary": BOUNDARY},
        )
        raise
    return len(rows), required


def _measure(source, workspace, repetitions):
    source, workspace = separate(source, workspace)
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("positive repetition count required")
    if (workspace / "failure.json").exists() or (
        workspace / "measurement.json"
    ).exists():
        raise ValueError("failed/already measured probe is immutable")
    receipt = read_sealed(workspace / "mirror.json")
    target = confined(workspace / "parent")
    if (
        receipt.get("status") != "BYTE_IDENTICAL_IO_MIRROR_ONLY"
        or receipt.get("boundary") != BOUNDARY
        or receipt.get("source") != str(source)
        or receipt.get("target") != str(target)
    ):
        raise ValueError("mirror binding differs")
    samples = []
    for iteration in range(repetitions):
        # Alternating order, cache state uncontrolled: do not call this cold I/O.
        arms = [("original", source), ("mirror", target)]
        if iteration % 2:
            arms.reverse()
        for label, directory in arms:
            if layout(directory) != receipt["directories"]:
                raise ValueError("directory layout differs")
            if inventory(directory) != receipt["rows"]:
                raise ValueError("complete byte inventory differs")
            start = time.perf_counter()
            quiet(directory)  # SAME frozen guard; no combined/cached substitute.
            guard_seconds = time.perf_counter() - start
            start = time.perf_counter()
            current = inventory(directory)
            inventory_seconds = time.perf_counter() - start
            if current != receipt["rows"]:
                raise ValueError("bytes changed during measurement")
            samples.append(
                {
                    "iteration": iteration,
                    "arm": label,
                    "quiet_seconds": guard_seconds,
                    "full_inventory_seconds": inventory_seconds,
                }
            )
    for directory in (source, target):
        if layout(directory) != receipt["directories"]:
            raise ValueError("final directory layout differs")
        if inventory(directory) != receipt["rows"]:
            raise ValueError("final byte inventory differs")
    new_report(
        workspace / "measurement.json",
        {
            "status": "MEASURED_IO_ONLY_NOT_SCIENTIFIC_QUALIFICATION",
            "mirror_digest": receipt["digest"],
            "samples": samples,
            "cache_state": "uncontrolled; no cold-cache claim",
            "boundary": BOUNDARY,
        },
    )
    return samples


def measure(source, workspace, repetitions):
    source, workspace = separate(source, workspace)
    try:
        return _measure(source, workspace, repetitions)
    except BaseException as exc:
        if (
            workspace.is_dir()
            and not (workspace / "failure.json").exists()
            and not (workspace / "measurement.json").exists()
        ):
            new_report(
                workspace / "failure.json",
                {
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "boundary": BOUNDARY,
                },
            )
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("mirror", "measure"), required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    args = parser.parse_args(argv)
    policy = load_policy(args.repository_root, args.config, args.config_sha256)
    if args.stage == "mirror":
        count, size = mirror(policy["source_directory"], policy["workspace"])
        print(f"BYTE_MIRROR_ONLY files={count} bytes={size}")
    else:
        result = measure(
            policy["source_directory"], policy["workspace"], policy["repetitions"]
        )
        print(f"IO_ONLY samples={len(result)} scientific_execution_ready=False")
    return 0

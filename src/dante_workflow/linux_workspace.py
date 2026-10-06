"""Parallel byte snapshots for native Linux; no scientific stage or hash waiver."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import time

from .calibration_recovery import read_sealed, sealed, write_json
from .input_preflight import _hash


def checked(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("absolute non-symlink snapshot path required")
    return path


def relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("confined relative snapshot path required")
    return path


def virtual_path(value):
    """Validate a logical mount name without dereferencing its original alias."""
    path = Path(value)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or not any(path.is_relative_to(Path(p)) for p in ("/mnt/c", "/mnt/e"))
    ):
        raise ValueError("snapshot virtual source must be on declared C/E roots")
    return path


def tree(source, excluded=()):
    """Scandir avoids repeated resolve/stat RPCs for every metadata ancestor."""
    source = checked(source)

    def walk(directory, prefix):
        with os.scandir(directory) as entries:
            for entry in entries:
                if not prefix.parts and entry.name in excluded:
                    continue
                if entry.is_symlink():
                    raise ValueError("snapshot source contains a symlink")
                name = prefix / entry.name
                if entry.is_dir(follow_symlinks=False):
                    yield from walk(Path(entry.path), name)
                elif entry.is_file(follow_symlinks=False):
                    yield name.as_posix(), entry.stat(follow_symlinks=False).st_size
                else:
                    raise ValueError("snapshot only accepts regular files")

    yield from walk(source, PurePosixPath())


def copy_file(source, target, expected=None):
    """Hash the exact copied stream and reread destination; never normalize bytes."""
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as reader, target.open("xb") as writer:
        before = os.fstat(reader.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("snapshot source is not regular")
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
        after = os.fstat(reader.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) or size != before.st_size:
        raise ValueError("source changed during snapshot")
    sha = digest.hexdigest()
    if (expected is not None and sha != expected) or _hash(target) != sha:
        raise ValueError("snapshot byte hash mismatch")
    return {"size_bytes": size, "sha256": sha}


def read_policy(config, sha):
    config = checked(config)
    if _hash(config) != sha:
        raise ValueError("Linux snapshot configuration hash mismatch")
    policy = json.loads(config.read_text())
    if (
        policy.get("schema_version") != 1
        or policy.get("status") != "NATIVE_LINUX_BYTE_PREPARATION_ONLY_V1"
    ):
        raise ValueError("unsupported Linux preparation authority")
    root, workspace = checked(policy["repository_root"]), checked(policy["workspace"])
    if workspace.is_relative_to(root) or root.is_relative_to(workspace):
        raise ValueError("snapshot must be outside the preserved checkout")
    existing = workspace.parent
    while not existing.exists():
        existing = existing.parent
    result = subprocess.run(
        ["findmnt", "-T", str(existing), "-n", "-o", "FSTYPE"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() != "ext4":
        raise ValueError("snapshot destination must be native ext4")
    for name in ("protocol", "calibration_contract"):
        if _hash(root / relative(policy[name])) != policy[name + "_sha256"]:
            raise ValueError("frozen preparation parent differs")
    params = json.loads((root / policy["protocol"]).read_text())
    workers = params["execution_parameters"]["primary_calibration"]["workers"]
    if type(workers) is not int or workers < 1:
        raise ValueError("invalid configured worker count")
    return policy, root, workspace, workers


def recipe(policy, root):
    """Opaque required files only, excluding unrelated outputs and unused frames."""
    entries = {}

    def add(source, virtual=None, expected=None, size=None):
        source = Path(source)
        virtual = virtual_path(virtual if virtual is not None else source)
        if virtual in entries:
            old = entries[virtual]
            if source != old["source"] or (
                expected and old["expected"] not in (None, expected)
            ):
                raise ValueError("conflicting snapshot source")
            old["expected"] = expected or old["expected"]
            return
        # Tree entries were already checked with scandir. Avoid two extra
        # Windows metadata RPCs per file; copy_file still rejects leaf links.
        if size is None and (source.is_symlink() or not source.is_file()):
            raise ValueError(f"required snapshot source absent/link: {source}")
        entries[virtual] = dict(
            source=source,
            expected=expected,
            size=size if size is not None else source.stat().st_size,
        )

    tracked = (
        subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
        )
        .stdout.decode()
        .split("\0")
    )
    for name in filter(None, tracked):
        add(root / relative(name))
    for name, size in tree(root / ".git"):
        add(root / ".git" / name, size=size)
    for item in policy["trees"]:
        source, virtual = (
            checked(item["source"]),
            virtual_path(item.get("virtual", item["source"])),
        )
        for name, size in tree(source, item.get("exclude_top", [])):
            add(source / name, virtual / name, size=size)
    for item in policy["files"]:
        add(checked(item["source"]), expected=item.get("sha256"))
    protocol = json.loads((root / policy["protocol"]).read_text())
    for name in ("protocol", "calibration_contract"):
        add(root / relative(policy[name]), expected=policy[name + "_sha256"])
    for ref in protocol["source_references"].values():
        if ref["path"].startswith("artifacts/"):
            add(root / relative(ref["path"]), expected=ref["sha256"])
    for ref in protocol["calibration_population"]["source_hdf5_references"]:
        add(root / relative(ref["path"]), expected=ref["sha256"])
    # Freeze every scientific source exactly as used by the existing contract.
    calibration = json.loads((root / policy["calibration_contract"]).read_text())
    for name, sha in calibration["scientific_source_pins"].items():
        add(root / relative(name), expected=sha)
    # Bind all required native container bytes to the already admitted records.
    recovery = checked(policy["recovery_directory"])
    admission = read_sealed(recovery / "admission.json")
    for row in admission["records"]:
        add(recovery / relative(row["relative_path"]), expected=row["file_sha256"])
    # Reuse the complete proven image copy, but check every copied file again.
    image_source = checked(policy["image_mirror"])
    image_receipt = read_sealed(image_source.parent / "mirror.json")
    if image_receipt["digest"] != policy["image_mirror_digest"]:
        raise ValueError("verified image mirror differs")
    original = checked(policy["image_virtual_directory"])
    for row in image_receipt["rows"]:
        name = relative(row["path"])
        add(image_source / name, original / name, expected=row["sha256"])
    return entries


def source_audit(root, freeze):
    for name in (
        "src/dante_workflow/linux_workspace.py",
        "scripts/prepare_dante_workflow_linux.py",
    ):
        data = subprocess.run(
            ["git", "show", f"{freeze}:{name}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        if hashlib.sha256(data).hexdigest() != _hash(root / name):
            raise ValueError("Linux preparation source differs from freeze")


def prepare(config, sha, source_freeze=None):
    policy, root, workspace, workers = read_policy(config, sha)
    if source_freeze is not None:
        source_audit(root, source_freeze)
    # New-only claim first; interrupted preparation is preserved, not resumed.
    workspace.mkdir(exist_ok=False)
    started = time.monotonic()
    try:
        entries = recipe(policy, root)
        required = sum(r["size"] for r in entries.values())
        if required > policy["maximum_snapshot_bytes"]:
            raise ValueError("snapshot exceeds checked host backing disk budget")
        if shutil.disk_usage(workspace).free < required * 2:
            raise ValueError("insufficient native snapshot free space reserve")
        rows = []
        done_bytes = 0
        last = 0.0
        write_json(
            workspace / "inventory.json",
            sealed(
                dict(
                    status="PLANNED_NATIVE_SNAPSHOT_ONLY",
                    files=len(entries),
                    bytes=required,
                    copy_workers=workers,
                    excluded_unused_inputs=policy["excluded_unused_inputs"],
                    scientific_run_started=False,
                )
            ),
        )

        def copy(entry):
            virtual, ref = entry
            target = workspace / "snapshot" / virtual.relative_to("/")
            result = copy_file(ref["source"], target, ref["expected"])
            return dict(path=str(virtual), **result)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for row in pool.map(copy, sorted(entries.items()), chunksize=1):
                rows.append(row)
                done_bytes += row["size_bytes"]
                now = time.monotonic()
                if now - last >= 10:
                    write_json(
                        workspace / "progress.prepare.json",
                        sealed(
                            dict(
                                stage="prepare",
                                files=len(rows),
                                total_files=len(entries),
                                bytes=done_bytes,
                                total_bytes=required,
                                elapsed_seconds=now - started,
                                copy_workers=workers,
                            )
                        ),
                    )
                    last = now
        if _hash(config) != sha:
            raise ValueError("snapshot configuration changed")
        if source_freeze is not None:
            source_audit(root, source_freeze)
        write_json(
            workspace / "snapshot.json",
            sealed(
                dict(
                    status="BYTE_IDENTICAL_NATIVE_REQUIRED_INPUT_SNAPSHOT_ONLY",
                    configuration_sha256=sha,
                    source_freeze=source_freeze,
                    files=len(rows),
                    bytes=done_bytes,
                    rows=rows,
                    copy_workers=workers,
                    scientific_run_started=False,
                    scientific_equivalence_verified=False,
                    default_provider_replaced=False,
                )
            ),
        )
        return 0
    except BaseException as exc:
        write_json(
            workspace / "failure.json",
            sealed(
                dict(
                    status="FAILED_NATIVE_PREPARATION_NO_RESUME",
                    error=type(exc).__name__,
                    message=str(exc),
                    scientific_run_started=False,
                )
            ),
        )
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--source-freeze", required=True)
    args = parser.parse_args(argv)
    return prepare(args.config, args.config_sha256, args.source_freeze)

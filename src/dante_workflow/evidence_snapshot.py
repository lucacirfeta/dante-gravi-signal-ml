"""Isolated retained byte evidence, not a scientific or live-quiescence gate.

Expected member hashes must come from an externally pinned capture plan, never
from an automatic scan of mutable origins. Admission detaches the entire blob;
consumers subsequently read owned immutable bytes without filesystem access.
Capture checks detect divergent observations, not absence of concurrent writers.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Mapping
import zipfile

from .o3a_initial_verification import InitialEvidenceError, _json

POLICY_REL = "config/dante_workflow_evidence_snapshot_v1.json"
BOUNDARY = {
    "live_writer_exclusion": False,
    "atomic_historical_capture": False,
    "scientific_parent_closure_verified": False,
    "pem_replayed": False,
    "fresh_sensor_or_null_replay": False,
    "full_workflow_verified": False,
    "historical_artifacts_modified": False,
}


class SnapshotError(InitialEvidenceError):
    """Unsafe, incomplete or unbound byte evidence; never repaired."""


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _encoded(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SnapshotError("invalid externally pinned SHA256")
    return value


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise SnapshotError("unexpected snapshot schema keys")


def _name(value):
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", value) is None
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise SnapshotError("unsafe snapshot member name")
    for part in PurePosixPath(value).parts:
        if part.casefold() in {
            "failure.json",
            "failures.json",
            "controller.lock",
            "run.lock",
        } or part.casefold().endswith((".part", ".partial", ".tmp")):
            raise SnapshotError("failure/lock/partial member not admissible")
    return value


def load_policy(payload: bytes) -> dict:
    value = _json(payload)
    _keys(
        value,
        {
            "schema_version",
            "status",
            "format",
            "consumer_isolation",
            "capture_consistency",
            "capture_platform",
            "limits",
            "boundary",
        },
    )
    expected = {
        "schema_version": 1,
        "status": "FROZEN_ISOLATED_EVIDENCE_SNAPSHOT_POLICY_V1",
        "format": "zip_stored_no_extraction",
        "consumer_isolation": "owned_immutable_bytes",
        "capture_consistency": "externally_pinned_expected_byte_closure",
        "capture_platform": "posix_descriptor_relative_nofollow",
        "boundary": BOUNDARY,
    }
    if any(value[key] != item for key, item in expected.items()):
        raise SnapshotError("snapshot policy semantics changed")
    if type(value["schema_version"]) is not int:
        raise SnapshotError("invalid snapshot schema version")
    _keys(value["boundary"], BOUNDARY)
    if any(type(item) is not bool for item in value["boundary"].values()):
        raise SnapshotError("invalid snapshot boundary types")
    _keys(
        value["limits"],
        {
            "member_count",
            "member_bytes",
            "total_member_bytes",
            "archive_bytes",
            "manifest_bytes",
        },
    )
    if any(type(item) is not int or item <= 0 for item in value["limits"].values()):
        raise SnapshotError("invalid snapshot resource limits")
    return value


def _entries(rows, policy):
    if not isinstance(rows, list) or not rows:
        raise SnapshotError("empty or invalid declared byte closure")
    limits = policy["limits"]
    if len(rows) > limits["member_count"]:
        raise SnapshotError("snapshot member count exceeds policy")
    names, locations = set(), set()
    total = 0
    for row in rows:
        _keys(row, {"name", "root", "relative_path", "sha256", "size_bytes"})
        name, root, relative = (
            _name(row["name"]),
            _name(row["root"]),
            _name(row["relative_path"]),
        )
        if "/" in root:
            raise SnapshotError("root identifier is not a single component")
        location = (root.casefold(), relative.casefold())
        if name.casefold() in names or location in locations:
            raise SnapshotError("duplicate snapshot name or source binding")
        names.add(name.casefold())
        locations.add(location)
        _digest(row["sha256"])
        size = row["size_bytes"]
        if type(size) is not int or size < 0 or size > limits["member_bytes"]:
            raise SnapshotError("invalid or oversized snapshot member")
        total += size
    if total > limits["total_member_bytes"]:
        raise SnapshotError("snapshot byte total exceeds policy")
    if [row["name"] for row in rows] != sorted(row["name"] for row in rows):
        raise SnapshotError("snapshot declaration must have canonical name order")
    return rows


def load_capture_plan(payload: bytes, *, expected_sha256: str, policy: dict):
    if _sha(payload) != _digest(expected_sha256):
        raise SnapshotError("capture plan external hash mismatch")
    if len(payload) > policy["limits"]["manifest_bytes"]:
        raise SnapshotError("capture plan exceeds policy")
    value = _json(payload)
    _keys(value, {"schema_version", "status", "entries", "plan_digest"})
    body = {key: item for key, item in value.items() if key != "plan_digest"}
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["status"] != "FROZEN_RETAINED_EVIDENCE_CAPTURE_PLAN_V1"
        or value["plan_digest"] != _sha(_encoded(body))
    ):
        raise SnapshotError("invalid capture plan seal/status")
    _entries(value["entries"], policy)
    return value


def package_snapshot(
    *,
    plan_bytes: bytes,
    expected_plan_sha256: str,
    policy_bytes: bytes,
    members: Mapping[str, bytes],
) -> bytes:
    """Pure packaging of pinned bytes; no claim about capture provenance."""
    policy = load_policy(policy_bytes)
    plan = load_capture_plan(
        plan_bytes, expected_sha256=expected_plan_sha256, policy=policy
    )
    rows = plan["entries"]
    if set(members) != {row["name"] for row in rows}:
        raise SnapshotError("missing or additional snapshot members")
    owned = []
    for row in rows:
        content = members[row["name"]]
        if not isinstance(content, bytes):
            raise SnapshotError("snapshot member must be immutable bytes")
        if len(content) != row["size_bytes"] or _sha(content) != row["sha256"]:
            raise SnapshotError("snapshot expected member hash/size mismatch")
        owned.append((row["name"], content))
    body = {
        "schema_version": 1,
        "status": "SEALED_ISOLATED_EVIDENCE_BYTES_ONLY_V1",
        "plan_sha256": expected_plan_sha256,
        "policy_sha256": _sha(policy_bytes),
        "entries": rows,
        "boundary": BOUNDARY,
    }
    manifest = _encoded({**body, "snapshot_digest": _sha(_encoded(body))})
    if len(manifest) > policy["limits"]["manifest_bytes"]:
        raise SnapshotError("snapshot manifest exceeds policy")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in [
            ("manifest.json", manifest),
            ("capture_plan.json", plan_bytes),
        ] + [("members/" + name, content) for name, content in owned]:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFREG | 0o400) << 16
            archive.writestr(info, payload)
    result = output.getvalue()
    if len(result) > policy["limits"]["archive_bytes"]:
        raise SnapshotError("snapshot archive exceeds policy")
    return result


@dataclass(frozen=True, slots=True)
class RetainedSnapshot:
    """Detached byte view. JSON/receipts are fresh copies, never live paths."""

    _members: tuple[tuple[str, bytes], ...]
    _manifest: bytes
    archive_sha256: str

    def read(self, name: str) -> bytes:
        _name(name)
        for candidate, content in self._members:
            if candidate == name:
                return content
        raise SnapshotError("undeclared snapshot member")

    def json(self, name: str) -> dict:
        return _json(self.read(name))

    def manifest(self) -> dict:
        return _json(self._manifest)

    def receipt(self) -> dict:
        value = self.manifest()
        body = {
            "schema_version": 1,
            "status": "PASS_ISOLATED_SNAPSHOT_BYTES_ONLY_V1",
            "archive_sha256": self.archive_sha256,
            "snapshot_digest": value["snapshot_digest"],
            "plan_sha256": value["plan_sha256"],
            "policy_sha256": value["policy_sha256"],
            "member_count": len(self._members),
            "total_member_bytes": sum(len(content) for _, content in self._members),
            "consumer_isolation": "owned_immutable_bytes",
            "boundary": dict(BOUNDARY),
        }
        return {**body, "receipt_digest": _sha(_encoded(body))}


def admit_snapshot(
    payload: bytes,
    *,
    expected_sha256: str,
    expected_plan_sha256: str,
    policy_bytes: bytes,
) -> RetainedSnapshot:
    """Portable pure admission; does not extract or consult mutable origins."""
    if not isinstance(payload, bytes):
        raise SnapshotError("snapshot archive must be immutable bytes")
    policy = load_policy(policy_bytes)
    if len(payload) > policy["limits"]["archive_bytes"]:
        raise SnapshotError("snapshot archive exceeds policy")
    if _sha(payload) != _digest(expected_sha256):
        raise SnapshotError("snapshot external archive hash mismatch")
    _digest(expected_plan_sha256)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > policy["limits"]["member_count"] + 2:
                raise SnapshotError("invalid snapshot archive cardinality")
            for info in infos:
                limit = policy["limits"][
                    "manifest_bytes"
                    if info.filename in {"manifest.json", "capture_plan.json"}
                    else "member_bytes"
                ]
                if (
                    info.compress_type != zipfile.ZIP_STORED
                    or info.flag_bits & 1
                    or not stat.S_ISREG(info.external_attr >> 16)
                    or info.file_size < 0
                    or info.file_size > limit
                    or info.compress_size != info.file_size
                ):
                    raise SnapshotError("unsafe snapshot archive member")
            if infos[0].filename != "manifest.json":
                raise SnapshotError("snapshot manifest missing or misplaced")
            manifest_bytes = archive.read(infos[0])
            manifest = _json(manifest_bytes)
            _keys(
                manifest,
                {
                    "schema_version",
                    "status",
                    "plan_sha256",
                    "policy_sha256",
                    "entries",
                    "boundary",
                    "snapshot_digest",
                },
            )
            body = {k: v for k, v in manifest.items() if k != "snapshot_digest"}
            if (
                type(manifest["schema_version"]) is not int
                or manifest["schema_version"] != 1
                or manifest["status"] != "SEALED_ISOLATED_EVIDENCE_BYTES_ONLY_V1"
                or manifest["plan_sha256"] != expected_plan_sha256
                or manifest["policy_sha256"] != _sha(policy_bytes)
                or manifest["boundary"] != BOUNDARY
                or any(type(v) is not bool for v in manifest["boundary"].values())
                or manifest["snapshot_digest"] != _sha(_encoded(body))
            ):
                raise SnapshotError("snapshot manifest identity/seal/boundary changed")
            rows = _entries(manifest["entries"], policy)
            if [info.filename for info in infos] != [
                "manifest.json",
                "capture_plan.json",
            ] + ["members/" + row["name"] for row in rows]:
                raise SnapshotError("extra, duplicate or unordered archive entries")
            plan = load_capture_plan(
                archive.read(infos[1]),
                expected_sha256=expected_plan_sha256,
                policy=policy,
            )
            if rows != plan["entries"]:
                raise SnapshotError("snapshot closure differs from pinned capture plan")
            owned = []
            for info, row in zip(infos[2:], rows, strict=True):
                content = archive.read(info)
                if len(content) != row["size_bytes"] or _sha(content) != row["sha256"]:
                    raise SnapshotError("snapshot member byte hash/size mismatch")
                owned.append((row["name"], content))
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
        raise SnapshotError("invalid snapshot archive bytes") from error
    return RetainedSnapshot(tuple(owned), manifest_bytes, expected_sha256)


def _signature(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def read_capture_file(path: Path, *, size: int) -> bytes:
    """POSIX component-relative open; refuse links, specials and observed drift."""
    if (
        os.name != "posix"
        or os.open not in os.supports_dir_fd
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
    ):
        raise SnapshotError("descriptor-relative capture unsupported on this platform")
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise SnapshotError("capture origin must be an explicit absolute safe path")
    descriptors = []
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        directory = os.open("/", flags | os.O_DIRECTORY)
        descriptors.append(directory)
        for part in path.parts[1:-1]:
            directory = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            descriptors.append(directory)
        leaf = path.name
        before_path = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
        descriptor = os.open(leaf, flags, dir_fd=directory)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size != size
            or _signature(before) != _signature(before_path)
        ):
            raise SnapshotError("unsafe or changed snapshot origin")
        chunks, remaining = [], size + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        result = b"".join(chunks)
        if (
            len(result) != size
            or _signature(os.fstat(descriptor)) != _signature(before)
            or _signature(os.stat(leaf, dir_fd=directory, follow_symlinks=False))
            != _signature(before)
        ):
            raise SnapshotError("snapshot origin changed during capture")
        return result
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def capture_snapshot(
    *,
    plan_bytes: bytes,
    expected_plan_sha256: str,
    policy_bytes: bytes,
    roots: Mapping[str, Path],
) -> bytes:
    """Pinned closure only; final reread is not historical writer exclusion."""
    policy = load_policy(policy_bytes)
    plan = load_capture_plan(
        plan_bytes, expected_sha256=expected_plan_sha256, policy=policy
    )
    if set(roots) != {row["root"] for row in plan["entries"]}:
        raise SnapshotError("capture roots incomplete or additional")
    origins = {}
    members = {}
    for row in plan["entries"]:
        root = Path(roots[row["root"]])
        if not root.is_absolute() or ".." in root.parts:
            raise SnapshotError("capture root must be explicit and absolute")
        path = root / row["relative_path"]
        if path in origins.values():
            raise SnapshotError("duplicate physical capture origin")
        content = read_capture_file(path, size=row["size_bytes"])
        if _sha(content) != row["sha256"]:
            raise SnapshotError("capture origin does not match pinned member hash")
        members[row["name"]] = content
        origins[row["name"]] = path
    for row in plan["entries"]:
        if (
            _sha(read_capture_file(origins[row["name"]], size=row["size_bytes"]))
            != row["sha256"]
        ):
            raise SnapshotError("capture origin changed before isolation")
    return package_snapshot(
        plan_bytes=plan_bytes,
        expected_plan_sha256=expected_plan_sha256,
        policy_bytes=policy_bytes,
        members=members,
    )


def read_snapshot_blob(path: Path, *, maximum: int) -> bytes:
    """Bounded regular-file admission; pure consumers do not retain this path."""
    path = Path(path)
    if not path.is_absolute() or any(part == ".." for part in path.parts):
        raise SnapshotError("snapshot blob path must be explicit and absolute")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise SnapshotError("unsafe snapshot blob path")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise SnapshotError("snapshot blob is not a single-link regular file")
    if before.st_size > maximum:
        raise SnapshotError("snapshot blob exceeds policy")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        if _signature(os.fstat(descriptor)) != _signature(before):
            raise SnapshotError("snapshot blob changed before admission")
        chunks, remaining = [], before.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if (
            len(payload) != before.st_size
            or _signature(os.fstat(descriptor)) != _signature(before)
            or _signature(path.lstat()) != _signature(before)
        ):
            raise SnapshotError("snapshot blob changed during admission")
        return payload
    finally:
        os.close(descriptor)


def publish_snapshot(path: Path, payload: bytes, *, roots: Mapping[str, Path]):
    """New output only, outside input roots; no overwrite/repair/removal."""
    if os.name != "posix" or os.open not in os.supports_dir_fd:
        raise SnapshotError(
            "descriptor-relative publication unsupported on this platform"
        )
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or path.is_symlink():
        raise SnapshotError("snapshot output must be an explicit safe absolute path")
    parent = path.parent.resolve(strict=True)
    if parent != path.parent:
        raise SnapshotError("snapshot output parent must not traverse links")
    target = parent / path.name
    for root in roots.values():
        if target.is_relative_to(Path(root).resolve(strict=True)):
            raise SnapshotError("snapshot output overlaps capture input root")
    directories = []
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
        directory = os.open("/", flags)
        directories.append(directory)
        for part in parent.parts[1:]:
            directory = os.open(part, flags, dir_fd=directory)
            directories.append(directory)
        before = os.fstat(directory)
        if (before.st_dev, before.st_ino) != (
            parent.stat().st_dev,
            parent.stat().st_ino,
        ):
            raise SnapshotError("snapshot publication directory changed")
        descriptor = os.open(
            target.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o400,
            dir_fd=directory,
        )
        try:
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise SnapshotError(
                        "snapshot publication failed; preserve incomplete output"
                    )
                remaining = remaining[written:]
            os.fsync(descriptor)
            current = parent.stat()
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                raise SnapshotError(
                    "snapshot publication directory changed; preserve output"
                )
        finally:
            os.close(descriptor)
    finally:
        for descriptor in reversed(directories):
            os.close(descriptor)

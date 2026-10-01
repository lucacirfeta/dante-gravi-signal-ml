"""Snapshot byte isolation/refusal only; no historical PEM evidence is read."""

from contextlib import nullcontext
from dataclasses import FrozenInstanceError
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

import pytest

from src.dante_workflow import evidence_snapshot as snap

ROOT = Path(__file__).resolve().parents[1]
POLICY = (ROOT / snap.POLICY_REL).read_bytes()
POSIX = pytest.mark.skipif(os.name != "posix", reason="POSIX nofollow capture only")


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def plan_for(members, *, changes=None):
    rows = [
        {
            "name": name,
            "root": "origin",
            "relative_path": name,
            "sha256": sha(payload),
            "size_bytes": len(payload),
        }
        for name, payload in sorted(members.items())
    ]
    if changes:
        changes(rows)
    body = {
        "schema_version": 1,
        "status": "FROZEN_RETAINED_EVIDENCE_CAPTURE_PLAN_V1",
        "entries": rows,
    }
    return encoded({**body, "plan_digest": sha(encoded(body))})


@pytest.fixture
def sample():
    members = {"context.json": b'{"value":1}', "ledger.txt": b"fixture\n"}
    plan = plan_for(members)
    blob = snap.package_snapshot(
        plan_bytes=plan,
        expected_plan_sha256=sha(plan),
        policy_bytes=POLICY,
        members=members,
    )
    return members, plan, blob


def admitted(sample, *, blob=None, policy=POLICY, digest=None, plan_digest=None):
    _, plan, original = sample
    value = original if blob is None else blob
    return snap.admit_snapshot(
        value,
        expected_sha256=sha(value) if digest is None else digest,
        expected_plan_sha256=sha(plan) if plan_digest is None else plan_digest,
        policy_bytes=policy,
    )


def rewrite(blob, *, change=None, add=None, info_change=None):
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(blob)) as source,
        zipfile.ZipFile(output, "w") as target,
    ):
        for old in source.infolist():
            info = zipfile.ZipInfo(old.filename)
            info.external_attr = old.external_attr
            info.compress_type = old.compress_type
            payload = source.read(old)
            if change:
                payload = change(old.filename, payload)
            if info_change:
                info_change(info)
            target.writestr(info, payload)
        if add:
            info = zipfile.ZipInfo(add)
            info.external_attr = (stat.S_IFREG | 0o400) << 16
            target.writestr(info, b"extra")
    return output.getvalue()


def reseal(payload, mutate):
    value = json.loads(payload)
    mutate(value)
    value.pop("snapshot_digest", None)
    value["snapshot_digest"] = sha(encoded(value))
    return encoded(value)


def test_policy_and_deterministic_package(sample):
    members, plan, blob = sample
    assert snap.load_policy(POLICY)["consumer_isolation"] == "owned_immutable_bytes"
    assert (
        snap.package_snapshot(
            plan_bytes=plan,
            expected_plan_sha256=sha(plan),
            policy_bytes=POLICY,
            members=members,
        )
        == blob
    )
    view = admitted(sample)
    assert view.read("ledger.txt") == members["ledger.txt"]
    receipt = view.receipt()
    assert receipt["status"] == "PASS_ISOLATED_SNAPSHOT_BYTES_ONLY_V1"
    assert receipt["member_count"] == len(members)
    assert receipt["total_member_bytes"] == sum(map(len, members.values()))
    assert receipt["boundary"] == snap.BOUNDARY
    assert all(value is False for value in receipt["boundary"].values())
    assert not any(key in receipt for key in ("score", "verdict", "null", "members"))


def test_consumers_are_detached_and_do_not_touch_filesystem(sample, monkeypatch):
    view = admitted(sample)

    def forbidden(*args, **kwargs):
        raise AssertionError("live filesystem access after admission")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    assert view.json("context.json") == {"value": 1}
    value = view.json("context.json")
    value["value"] = 500
    manifest = view.manifest()
    manifest["entries"].clear()
    receipt = view.receipt()
    receipt["boundary"]["pem_replayed"] = True
    assert view.json("context.json") == {"value": 1}
    assert len(view.manifest()["entries"]) == 2
    assert view.receipt()["boundary"]["pem_replayed"] is False
    with pytest.raises(FrozenInstanceError):
        view.archive_sha256 = "0" * 64
    with pytest.raises(snap.SnapshotError, match="undeclared"):
        view.read("missing.json")


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "C:/drive",
        "a\\b",
        "a//b",
        "a/./b",
        "a/../b",
        "failure.json",
        "a/controller.lock",
        "a/run.lock",
        "a/x.partial",
        "a/X.PART",
        "x.tmp",
        "",
        "has space",
        "a\x00b",
    ],
)
def test_unsafe_member_names_refused(name):
    plan = plan_for({name: b"x"})
    with pytest.raises(snap.SnapshotError):
        snap.load_capture_plan(
            plan, expected_sha256=sha(plan), policy=snap.load_policy(POLICY)
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda rows: rows.append(dict(rows[0])),
        lambda rows: rows.append({**rows[0], "name": "CONTEXT.JSON"}),
        lambda rows: rows[0].update(size_bytes=True),
        lambda rows: rows[0].update(size_bytes=-1),
        lambda rows: rows[0].update(sha256="g" * 64),
        lambda rows: rows[0].update(root="a/b"),
        lambda rows: rows[0].update(unexpected=True),
        lambda rows: rows.reverse(),
    ],
)
def test_invalid_capture_plan_rows(sample, change):
    plan = plan_for(sample[0], changes=change)
    with pytest.raises(snap.SnapshotError):
        snap.load_capture_plan(
            plan, expected_sha256=sha(plan), policy=snap.load_policy(POLICY)
        )


def test_external_plan_pin_and_seal_required(sample):
    _, plan, _ = sample
    with pytest.raises(snap.SnapshotError, match="external hash"):
        snap.load_capture_plan(
            plan, expected_sha256="0" * 64, policy=snap.load_policy(POLICY)
        )
    value = json.loads(plan)
    value["plan_digest"] = "0" * 64
    changed = encoded(value)
    with pytest.raises(snap.SnapshotError, match="seal/status"):
        snap.load_capture_plan(
            changed, expected_sha256=sha(changed), policy=snap.load_policy(POLICY)
        )


@pytest.mark.parametrize(
    "members", [{}, {"extra": b"x"}, {"context.json": bytearray(b"x")}]
)
def test_incomplete_or_mutable_package_members(sample, members):
    _, plan, _ = sample
    with pytest.raises(snap.SnapshotError):
        snap.package_snapshot(
            plan_bytes=plan,
            expected_plan_sha256=sha(plan),
            policy_bytes=POLICY,
            members=members,
        )


def test_mutable_exact_members_refused(sample):
    members, plan, _ = sample
    changed = {**members, "context.json": bytearray(members["context.json"])}
    with pytest.raises(snap.SnapshotError, match="immutable"):
        snap.package_snapshot(
            plan_bytes=plan,
            expected_plan_sha256=sha(plan),
            policy_bytes=POLICY,
            members=changed,
        )


@pytest.mark.parametrize(
    "field",
    [
        "member_count",
        "member_bytes",
        "total_member_bytes",
        "archive_bytes",
        "manifest_bytes",
    ],
)
def test_resource_limits_enforced(sample, field):
    policy = json.loads(POLICY)
    policy["limits"][field] = 1
    with pytest.raises(snap.SnapshotError):
        snap.package_snapshot(
            plan_bytes=sample[1],
            expected_plan_sha256=sha(sample[1]),
            policy_bytes=encoded(policy),
            members=sample[0],
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(consumer_isolation="copied_writable_directory"),
        lambda value: value["boundary"].update(live_writer_exclusion=True),
        lambda value: value["boundary"].update(live_writer_exclusion=0),
        lambda value: value["limits"].update(member_count=True),
        lambda value: value.update(schema_version=True),
    ],
)
def test_policy_semantics_cannot_be_weakened(change):
    value = json.loads(POLICY)
    change(value)
    with pytest.raises(snap.SnapshotError):
        snap.load_policy(encoded(value))


def test_changed_bytes_rejected_even_with_resealed_manifest_and_archive(sample):
    _, _, blob = sample

    def change(name, payload):
        if name == "members/context.json":
            return b'{"value":2}'
        if name == "manifest.json":
            return reseal(
                payload, lambda v: v["entries"][0].update(sha256=sha(b'{"value":2}'))
            )
        return payload

    with pytest.raises(snap.SnapshotError, match="pinned capture plan"):
        admitted(sample, blob=rewrite(blob, change=change))


@pytest.mark.parametrize(
    "extra", ["unexpected.json", "../escape", "members/context.json"]
)
def test_extra_duplicate_or_escaping_archive_entries(sample, extra):
    with (
        pytest.warns(UserWarning) if extra == "members/context.json" else nullcontext()
    ):
        blob = rewrite(sample[2], add=extra)
    with pytest.raises(snap.SnapshotError):
        admitted(sample, blob=blob)


@pytest.mark.parametrize(
    "alter",
    [
        lambda info: setattr(info, "compress_type", zipfile.ZIP_DEFLATED),
        lambda info: setattr(info, "external_attr", (stat.S_IFLNK | 0o777) << 16),
        lambda info: setattr(info, "external_attr", (stat.S_IFDIR | 0o700) << 16),
    ],
)
def test_compression_and_link_archive_entries_refused(sample, alter):
    with pytest.raises(snap.SnapshotError, match="unsafe"):
        admitted(sample, blob=rewrite(sample[2], info_change=alter))


def test_external_archive_plan_and_policy_pins(sample):
    with pytest.raises(snap.SnapshotError, match="external archive"):
        admitted(sample, digest="0" * 64)
    with pytest.raises(snap.SnapshotError, match="identity/seal"):
        admitted(sample, plan_digest="0" * 64)
    policy = json.loads(POLICY)
    policy["limits"]["member_count"] -= 1
    with pytest.raises(snap.SnapshotError, match="identity/seal"):
        admitted(sample, policy=encoded(policy))
    with pytest.raises(snap.SnapshotError, match="immutable bytes"):
        admitted(sample, blob=bytearray(sample[2]))
    with pytest.raises(snap.SnapshotError, match="invalid snapshot archive"):
        admitted(sample, blob=b"not zip")


def test_duplicate_json_and_nonfinite_refused(sample):
    for content in (b'{"a":1,"a":2}', b'{"a":NaN}'):
        members = {"invalid.json": content}
        plan = plan_for(members)
        blob = snap.package_snapshot(
            plan_bytes=plan,
            expected_plan_sha256=sha(plan),
            policy_bytes=POLICY,
            members=members,
        )
        view = admitted((members, plan, blob))
        with pytest.raises(snap.InitialEvidenceError):
            view.json("invalid.json")


def origins(tmp_path, members):
    root = tmp_path / "origin"
    root.mkdir()
    for name, content in members.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


@POSIX
def test_capture_then_origin_mutation_does_not_mutate_snapshot(sample, tmp_path):
    members, plan, _ = sample
    root = origins(tmp_path, members)
    blob = snap.capture_snapshot(
        plan_bytes=plan,
        expected_plan_sha256=sha(plan),
        policy_bytes=POLICY,
        roots={"origin": root},
    )
    (root / "context.json").write_bytes(b"changed")
    (root / "ledger.txt").unlink()
    assert admitted(sample, blob=blob).read("context.json") == members["context.json"]


@POSIX
@pytest.mark.parametrize("kind", ["symlink", "ancestor_symlink", "hardlink", "fifo"])
def test_unsafe_capture_origins_refused(sample, tmp_path, kind):
    members, plan, _ = sample
    root = origins(tmp_path, members)
    target = root / "context.json"
    if kind == "ancestor_symlink":
        linked = tmp_path / "alias"
        linked.symlink_to(root, target_is_directory=True)
        root = linked
    elif kind == "hardlink":
        os.link(target, tmp_path / "hardlink")
    else:
        target.unlink()
        if kind == "symlink":
            other = tmp_path / "other"
            other.write_bytes(members["context.json"])
            target.symlink_to(other)
        else:
            os.mkfifo(target)
    with pytest.raises((OSError, snap.SnapshotError)):
        snap.capture_snapshot(
            plan_bytes=plan,
            expected_plan_sha256=sha(plan),
            policy_bytes=POLICY,
            roots={"origin": root},
        )


@POSIX
def test_capture_mid_read_mutation_refused(sample, tmp_path, monkeypatch):
    root = origins(tmp_path, sample[0])
    old_read = os.read
    modified = False

    def read(fd, size):
        nonlocal modified
        payload = old_read(fd, size)
        if not modified:
            modified = True
            (root / "context.json").write_bytes(b'{"value":2}')
        return payload

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(snap.SnapshotError, match="changed"):
        snap.capture_snapshot(
            plan_bytes=sample[1],
            expected_plan_sha256=sha(sample[1]),
            policy_bytes=POLICY,
            roots={"origin": root},
        )


@POSIX
def test_capture_final_rehash_refuses_later_origin_change(
    sample, tmp_path, monkeypatch
):
    root = origins(tmp_path, sample[0])
    old_read = snap.read_capture_file
    calls = 0

    def read(path, *, size):
        nonlocal calls
        payload = old_read(path, size=size)
        calls += 1
        if calls == 2:
            (root / "context.json").write_bytes(b'{"value":2}')
        return payload

    monkeypatch.setattr(snap, "read_capture_file", read)
    with pytest.raises(snap.SnapshotError, match="changed before isolation"):
        snap.capture_snapshot(
            plan_bytes=sample[1],
            expected_plan_sha256=sha(sample[1]),
            policy_bytes=POLICY,
            roots={"origin": root},
        )


@POSIX
def test_publish_exclusive_outside_inputs(sample, tmp_path):
    root = origins(tmp_path, sample[0])
    target = tmp_path / "snapshot.zip"
    snap.publish_snapshot(target, sample[2], roots={"origin": root})
    assert target.read_bytes() == sample[2]
    with pytest.raises(FileExistsError):
        snap.publish_snapshot(target, b"overwrite", roots={"origin": root})
    assert target.read_bytes() == sample[2]
    with pytest.raises(snap.SnapshotError, match="overlaps"):
        snap.publish_snapshot(root / "snapshot.zip", sample[2], roots={"origin": root})


def test_blob_admission_bounds(sample, tmp_path):
    path = tmp_path / "snapshot.zip"
    path.write_bytes(sample[2])
    assert snap.read_snapshot_blob(path, maximum=len(sample[2])) == sample[2]
    with pytest.raises(snap.SnapshotError, match="exceeds"):
        snap.read_snapshot_blob(path, maximum=1)


def cli(*arguments):
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts/dante_evidence_snapshot.py"),
            *map(str, arguments),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_cli_verify_no_output_or_origin_access(sample, tmp_path):
    path = tmp_path / "snapshot.zip"
    path.write_bytes(sample[2])
    before = path.read_bytes()
    result = cli(
        "verify",
        "--snapshot",
        path,
        "--expected-sha256",
        sha(before),
        "--expected-plan-sha256",
        sha(sample[1]),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["status"] == "PASS_ISOLATED_SNAPSHOT_BYTES_ONLY_V1"
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
    denied = cli(
        "verify",
        "--snapshot",
        path,
        "--expected-sha256",
        "0" * 64,
        "--expected-plan-sha256",
        sha(sample[1]),
    )
    assert denied.returncode == 1
    assert json.loads(denied.stdout)["status"] == "FAIL_CLOSED_ISOLATED_SNAPSHOT_BYTES"


@POSIX
def test_cli_capture_and_no_overwrite(sample, tmp_path):
    root = origins(tmp_path, sample[0])
    plan = tmp_path / "plan.json"
    plan.write_bytes(sample[1])
    output = tmp_path / "snapshot.zip"
    arguments = (
        "capture",
        "--plan",
        plan,
        "--expected-plan-sha256",
        sha(sample[1]),
        "--root",
        f"origin={root}",
        "--output",
        output,
    )
    result = cli(*arguments)
    assert result.returncode == 0, result.stderr + result.stdout
    receipt = json.loads(result.stdout)
    assert receipt["archive_sha256"] == sha(output.read_bytes())
    assert cli(*arguments).returncode == 1


def test_cli_verify_rejects_productive_arguments():
    assert cli("verify", "--root", "origin=/tmp", "--output", "/tmp/no").returncode == 2


@pytest.mark.skipif(os.name == "posix", reason="Windows refusal contract")
def test_windows_capture_refuses_before_read(tmp_path):
    with pytest.raises(snap.SnapshotError, match="unsupported"):
        snap.read_capture_file(tmp_path / "absent", size=1)

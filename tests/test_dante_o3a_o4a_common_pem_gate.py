"""Synthetic public-DQ equality gates for the paired PEM follow-up."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from gwosc import timeline

from src.dante_light import o3a_o4a_common_pem_gate as gate
from src.dante_light.contracts import ContractError


def test_frozen_background_source_binds_parent_inputs() -> None:
    contract = gate.load_background_source_contract()
    assert contract["contract_digest"] == (
        "c974bfb7ee83ad699bf01c2543075de27f38a772c8b76ebea775e0ec25f53fd7"
    )
    assert set(contract["sources"]) == {"O3a", "O4a"}
    assert contract["sources"]["O3a"]["required_unique_frames_preflight"] == 47
    assert contract["sources"]["O4a"]["required_unique_frames_preflight"] == 278


def test_background_source_rejects_changed_manifest_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.read_text

    def changed(path: Path, *args, **kwargs) -> str:
        value = original(path, *args, **kwargs)
        if path.name == "dante_o3a_o4a_common_pem_background_v1.json":
            document = json.loads(value)
            document["sources"]["O3a"]["manifest_sha256"] = "0" * 64
            return json.dumps(document)
        return value

    monkeypatch.setattr(Path, "read_text", changed)
    with pytest.raises(ContractError, match="source contract digest changed"):
        gate.load_background_source_contract()


def _snapshot() -> dict:
    return {
        "query_bounds_gps": [0, 100],
        "detectors": ["H1", "L1"],
        "segments": {"H1": [[0, 10], [20, 30]], "L1": [[3, 18]]},
    }


def test_o3a_cat1_equivalence_requires_both_public_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = _snapshot()
    queried: list[str] = []
    monkeypatch.setattr(gate, "load_dq_snapshot", lambda *, root: snapshot)

    def get_segments(flag: str, start: int, end: int):
        queried.append(flag)
        assert (start, end) == (0, 100)
        return snapshot["segments"][flag[:2]]

    monkeypatch.setattr(timeline, "get_segments", get_segments)
    receipt = gate.verify_o3a_cat1_equivalence(root=tmp_path)
    assert receipt == {
        "status": "PASS_CAT1_EQUIVALENCE",
        "detectors": {
            "H1": {"segment_count": 2, "livetime_s": 20},
            "L1": {"segment_count": 1, "livetime_s": 15},
        },
    }
    assert queried == ["H1_CBC_CAT1", "H1_BURST_CAT1", "L1_CBC_CAT1", "L1_BURST_CAT1"]


def test_o3a_cat1_equivalence_rejects_burst_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = _snapshot()
    monkeypatch.setattr(gate, "load_dq_snapshot", lambda *, root: snapshot)
    monkeypatch.setattr(
        timeline,
        "get_segments",
        lambda flag, start, end: (
            [[3, 17]] if flag == "L1_BURST_CAT1" else snapshot["segments"][flag[:2]]
        ),
    )
    with pytest.raises(ContractError, match="L1 public CBC/BURST CAT1 differs"):
        gate.verify_o3a_cat1_equivalence(root=tmp_path)


@pytest.mark.parametrize("release", ["O3a_4KHZ_R1", "O4a_4KHZ_R1"])
def test_official_frame_manifest_plans_gap_free_background(release: str) -> None:
    lines = [
        f"{'a' * 32}  H1/0/H-H1_GWOSC_{release}-{start}-4096.hdf5"
        for start in (0, 4096, 8192)
    ]
    manifest = gate.parse_official_frame_manifest(
        ("\n".join(lines) + "\n").encode("ascii"),
        release=release,
        frame_duration_s=4096,
    )
    pieces = gate.plan_background_frames(
        detector="H1",
        start=200,
        end=8400,
        manifest=manifest,
        frame_duration_s=4096,
    )
    assert [row["used_interval_gps"] for row in pieces] == [
        [200, 4096],
        [4096, 8192],
        [8192, 8400],
    ]
    assert [row["md5"] for row in pieces] == ["a" * 32] * 3


def test_official_background_frame_gap_fails_closed() -> None:
    release = "O3a_4KHZ_R1"
    rows = [
        f"{'a' * 32}  H1/0/H-H1_GWOSC_{release}-{start}-4096.hdf5"
        for start in (0, 8192)
    ]
    manifest = gate.parse_official_frame_manifest(
        "\n".join(rows).encode("ascii"), release=release, frame_duration_s=4096
    )
    with pytest.raises(ContractError, match="frames have a gap"):
        gate.plan_background_frames(
            detector="H1",
            start=200,
            end=8400,
            manifest=manifest,
            frame_duration_s=4096,
        )


def test_official_background_manifest_rejects_duplicate_and_wrong_release() -> None:
    line = f"{'a' * 32}  L1/0/L-L1_GWOSC_O4a_4KHZ_R1-0-4096.hdf5"
    with pytest.raises(ContractError, match="duplicated"):
        gate.parse_official_frame_manifest(
            (line + "\n" + line).encode("ascii"),
            release="O4a_4KHZ_R1",
            frame_duration_s=4096,
        )
    with pytest.raises(ContractError, match="release is invalid"):
        gate.parse_official_frame_manifest(
            line.encode("ascii"), release="O3a_4KHZ_R1", frame_duration_s=4096
        )


def test_o3a_manifest_validates_but_ignores_virgo_rows() -> None:
    lines = [
        f"{'a' * 32}  V1/0/V-V1_GWOSC_O3a_4KHZ_R1-0-4096.hdf5",
        f"{'b' * 32}  H1/0/H-H1_GWOSC_O3a_4KHZ_R1-0-4096.hdf5",
    ]
    rows = gate.parse_official_frame_manifest(
        "\n".join(lines).encode("ascii"),
        release="O3a_4KHZ_R1",
        frame_duration_s=4096,
    )
    assert set(rows) == {("H1", 0)}

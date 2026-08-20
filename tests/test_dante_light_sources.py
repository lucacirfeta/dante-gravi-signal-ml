from __future__ import annotations

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, FailClosedReason, WindowIdentity
from src.dante_light.executor import DeferredWindow
from src.dante_light.sources import ReplayManifestSource, StrainPacket, WindowAssembler


def test_replay_source_balances_preflight_limit_per_detector(tmp_path) -> None:
    import hashlib
    import json

    entries = []
    for detector in ("H1", "L1"):
        for offset in range(3):
            window = WindowIdentity("O4B", detector, 3000 + offset * 32, 32)
            entries.append(
                {
                    "case_id": f"{detector}-{offset}",
                    "roles": ["shadow"],
                    "window": window.to_dict(),
                }
            )
    encoded = "".join(json.dumps(row) + "\n" for row in entries).encode()
    entries_path = tmp_path / "entries.jsonl"
    entries_path.write_bytes(encoded)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "entries_path": "entries.jsonl",
                "entries_file_sha256": hashlib.sha256(encoded).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    source = ReplayManifestSource(manifest, root=tmp_path)

    tasks = source.tasks(limit_per_detector=1)

    assert [task.window.detector for task in tasks] == ["H1", "L1"]
    with pytest.raises(ValueError, match="mutually exclusive"):
        source.tasks(limit=1, limit_per_detector=1)


def packet(second: int, *, value: float | None = None, cat1: bool = True):
    return StrainPacket(
        run="O4A",
        detector="H1",
        gps_start=second,
        sample_rate_hz=4096,
        samples=np.full(4096, second if value is None else value, dtype=np.float64),
        calibrated=True,
        cat1=cat1,
    )


def test_packet_assembler_reorders_and_matches_direct_samples() -> None:
    assembler = WindowAssembler(max_packets=8)
    assembler.add(packet(101))
    assembler.add(packet(100))
    assembler.add(packet(100))
    assembled = assembler.assemble(WindowIdentity("O4A", "H1", 100, 2))
    expected = np.concatenate([packet(100).samples, packet(101).samples])
    np.testing.assert_array_equal(assembled, expected)


def test_packet_assembler_fails_closed_on_gap_dq_and_divergent_duplicate() -> None:
    gap = WindowAssembler(max_packets=4)
    gap.add(packet(100))
    with pytest.raises(DeferredWindow) as missing:
        gap.assemble(WindowIdentity("O4A", "H1", 100, 2))
    assert missing.value.reason is FailClosedReason.INCOMPLETE_DATA

    dq = WindowAssembler(max_packets=4)
    dq.add(packet(100, cat1=False))
    with pytest.raises(DeferredWindow) as bad_dq:
        dq.assemble(WindowIdentity("O4A", "H1", 100, 1))
    assert bad_dq.value.reason is FailClosedReason.MISSING_CAT1

    duplicate = WindowAssembler(max_packets=4)
    duplicate.add(packet(100, value=1.0))
    with pytest.raises(ContractError, match="divergent duplicate"):
        duplicate.add(packet(100, value=2.0))


def test_replay_file_source_deduplicates_shared_window_roles() -> None:
    source = ReplayManifestSource(
        "config/dante_light_replay_v1.json", root="."
    )
    forum = source.tasks(roles={"forum_candidate", "candidate_non_background"})
    ids = [task.window.window_id for task in forum]
    assert len(ids) == len(set(ids))
    exact = [task for task in forum if "forum_candidate" in task.payload["roles"]]
    assert len(exact) == 1
    assert exact[0].window.gps_start == 1382955232.0

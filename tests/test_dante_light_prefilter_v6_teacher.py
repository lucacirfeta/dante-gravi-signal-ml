from __future__ import annotations

import copy
import hashlib

import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v5_protocol import ROOT
from src.dante_light.prefilter_v5_teacher import PreparedTeacherInput
from src.dante_light.prefilter_v6_teacher import (
    build_teacher_ledger,
    phase_b_windows,
    verify_teacher_ledger_summary,
)


def test_v6_teacher_identities_are_exactly_phase_b() -> None:
    rows = phase_b_windows(root=ROOT)
    assert len(rows) == 2880
    assert len({row["window"]["window_id"] for row in rows}) == 2880
    assert {row["detector"] for row in rows} == {"H1", "L1"}
    assert {row["subset"] for row in rows} == {"fit", "internal_validation"}
    assert all(row["window"]["run"] == "O4A" for row in rows)


def test_v6_teacher_smoke_is_block_atomic_and_resumable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = phase_b_windows(root=ROOT)
    contract = {
        "teacher_contract_digest": "a" * 64,
        "identity_count": len(rows),
        "block_count": 360,
        "identity_digest": "b" * 64,
    }
    monkeypatch.setattr(
        "src.dante_light.prefilter_v6_teacher.load_teacher_contract",
        lambda *args, **kwargs: contract,
    )
    source = ROOT / "src/dante_light/prefilter_v6_teacher.py"
    references = {
        "teacher_implementation": {
            "path": source.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
    }

    def prepare(window):
        clean = np.full(32, window.gps_start % 11, dtype=np.float32)
        image = np.full((4, 4, 3), int(window.gps_start) % 251, dtype=np.uint8)
        return PreparedTeacherInput(
            image=image,
            clean_strain=clean,
            raw_strain_sha256="c" * 64,
            clean_strain_sha256=hashlib.sha256(clean.tobytes()).hexdigest(),
            image_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
            timings={"test_s": 0.0},
        )

    def score(images):
        return [float(image[0, 0, 0]) / 255.0 for image in images], {"test_s": 0.0}

    kwargs = dict(
        root=ROOT,
        contract=contract,
        cache_root=tmp_path / "cache",
        artifact_path=tmp_path / "summary.json",
        code_references=references,
        prepare=prepare,
        score=score,
        workers=2,
        limit_blocks=1,
    )
    first = build_teacher_ledger(**kwargs)
    second = build_teacher_ledger(**kwargs)
    assert first == second
    assert first["status"] == "SMOKE_ONLY"
    assert first["row_count"] == 8
    assert first["phase_c_rows_accessed"] == []
    assert first["phase_d_rows_accessed"] == []
    assert first["o4b_rows_accessed"] == []
    verified = verify_teacher_ledger_summary(
        first,
        root=ROOT,
        cache_root=tmp_path / "cache",
        require_complete=False,
    )
    assert verified["status"] == "PASS_SMOKE_ONLY"


def test_v6_teacher_summary_rejects_protected_access() -> None:
    summary = {
        "artifact_digest": "not-used",
        "phase_c_rows_accessed": ["forbidden"],
    }
    with pytest.raises((ContractError, FileNotFoundError)):
        verify_teacher_ledger_summary(
            copy.deepcopy(summary),
            root=ROOT,
            cache_root=ROOT,
        )

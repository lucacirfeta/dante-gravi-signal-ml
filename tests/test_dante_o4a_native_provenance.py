from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_native_provenance import (
    RECONCILIATION_REL,
    canonical_source_sha256,
    load_reconciliation,
    validate_reconciliation,
    verify_reference_with_reconciliation,
)


ROOT = Path(__file__).resolve().parents[1]


def _resign(payload: dict) -> dict:
    body = deepcopy(payload)
    body.pop("record_digest", None)
    payload["record_digest"] = canonical_json_sha256(body)
    return payload


def test_real_reconciliation_is_git_and_content_verified() -> None:
    record = load_reconciliation(root=ROOT, verify_git=True)

    assert record["status"] == "PASS_PROVENANCE_RECONCILED"
    assert record["scientific_boundary"]["rerun_required"] is False
    assert len(record["canonical_replay"]["rows"]) == 12


def test_canonical_source_hash_is_line_ending_portable(tmp_path: Path) -> None:
    expected = "alpha\nbeta\ngamma\n"
    variants = {
        "lf.py": expected,
        "crlf.py": expected.replace("\n", "\r\n"),
        "cr.py": expected.replace("\n", "\r"),
    }
    hashes = set()
    for name, text in variants.items():
        path = tmp_path / name
        path.write_bytes(text.encode("utf-8"))
        hashes.add(canonical_source_sha256(path))

    assert len(hashes) == 1


def test_scientific_boundary_tampering_fails_closed() -> None:
    payload = json.loads((ROOT / RECONCILIATION_REL).read_text(encoding="utf-8"))
    payload["scientific_boundary"]["scores_changed"] = True
    _resign(payload)

    with pytest.raises(ContractError, match="self-digest"):
        validate_reconciliation(payload, root=ROOT)


def test_only_frozen_historical_pair_is_reconciled() -> None:
    patch_producer = ROOT / "src/core/patch_producer.py"
    verify_reference_with_reconciliation(
        root=ROOT,
        path=patch_producer,
        expected_sha256=(
            "2c20d4e89b48060986770127bf41c2d860d22efc4f98f430cb152cfb71f39dcf"
        ),
    )

    with pytest.raises(ContractError, match="reference mismatch"):
        verify_reference_with_reconciliation(
            root=ROOT,
            path=patch_producer,
            expected_sha256="0" * 64,
        )

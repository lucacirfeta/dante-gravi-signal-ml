from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "paper_draft" / "v6_paper" / "tools" / "check_manuscript_claims.py"
)
if not MODULE_PATH.is_file():
    pytest.skip(
        "private paper workspace is not included in the public checkout",
        allow_module_level=True,
    )
SPEC = importlib.util.spec_from_file_location("check_manuscript_claims", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)

TRANSITION_MODULE_PATH = ROOT / "scripts" / "build_dsd_representation_transition.py"
TRANSITION_SPEC = importlib.util.spec_from_file_location(
    "build_dsd_representation_transition", TRANSITION_MODULE_PATH
)
assert TRANSITION_SPEC is not None and TRANSITION_SPEC.loader is not None
TRANSITION = importlib.util.module_from_spec(TRANSITION_SPEC)
sys.modules[TRANSITION_SPEC.name] = TRANSITION
TRANSITION_SPEC.loader.exec_module(TRANSITION)


def _contract() -> dict:
    return {
        "manuscript_contract": {
            "forbidden_fragments": [
                "changes 41 apparent positives to 12 confirmed endpoints"
            ],
            "required_fragments_all": ["48", "10"],
            "required_scope_terms": ["boundary-conditioned"],
        }
    }


def test_checker_rejects_legacy_pem_sentence() -> None:
    text = """
    The boundary-conditioned sample is reported. A quiet null
    changes 41 apparent positives to 12 confirmed endpoints. Values 48 and 10.
    """
    findings = CHECKER.check_text("fixture", text, _contract())
    assert any(item.kind == "forbidden" for item in findings)


def test_checker_accepts_current_counts_and_scope() -> None:
    text = """
    The boundary-conditioned sample is reported. The time-shift endpoint has
    48 positives, of which 10 survive the two-null rule.
    """
    assert CHECKER.check_text("fixture", text, _contract()) == []


def test_normalization_catches_line_wrapped_fragment() -> None:
    text = """
    changes 41 apparent positives
    to 12 confirmed endpoints; values 48 and 10 are also shown in a table.
    The analysis is boundary-conditioned.
    """
    findings = CHECKER.check_text("fixture", text, _contract())
    assert [item.kind for item in findings] == ["forbidden"]


def test_master_contract_artifact_hashes_are_current() -> None:
    contract = CHECKER.load_contract(CHECKER.DEFAULT_CONTRACT)
    assert CHECKER.verify_artifact_hashes(contract) == []


def test_detector_aware_transition_reconstructs_current_matrix() -> None:
    artifact = TRANSITION.build_artifact()
    assert artifact["paired_total"] == 10_372
    assert artifact["changed_dispositions"] == 4_676
    assert artifact["restored_total"] == 57
    assert artifact["transition_matrix"] == {
        "ROBUST": {"ROBUST": 2914, "AMBIGUOUS": 14, "BACKGROUND": 9},
        "AMBIGUOUS": {"ROBUST": 1666, "AMBIGUOUS": 68, "BACKGROUND": 39},
        "BACKGROUND": {"ROBUST": 1759, "AMBIGUOUS": 1188, "BACKGROUND": 2714},
        "UNKNOWN": {"ROBUST": 0, "AMBIGUOUS": 0, "BACKGROUND": 1},
    }


def test_saved_detector_aware_transition_is_current() -> None:
    reconstructed = TRANSITION.build_artifact()
    saved = json.loads(TRANSITION.OUTPUT.read_text(encoding="utf-8"))
    assert saved == reconstructed


def test_cqg_transition_table_rejects_one_stale_cell() -> None:
    contract = CHECKER.load_contract(CHECKER.DEFAULT_CONTRACT)
    good = r"""
    \robust & 2,914 & 14 & 9 \\
    \ambiguous & 1,666 & 68 & 39 \\
    \background & 1,759 & 1,188 & 2,714 \\
    UNKNOWN & 0 & 0 & 1 \\
    """
    assert CHECKER.check_cqg_transition_table(good, contract) == []
    bad = good.replace("2,714", "2,713")
    findings = CHECKER.check_cqg_transition_table(bad, contract)
    assert len(findings) == 1
    assert findings[0].kind == "stale-transition-row"


def test_cqg_cover_requires_exact_manuscript_title() -> None:
    manuscript = r"\title{Detector-Dependent Domain Shift with DANTE}"
    matching = "Research Paper ``Detector-Dependent Domain Shift with DANTE''"
    stale = "Research Paper ``An older title''"
    assert CHECKER.verify_cqg_cover_title(manuscript, matching) == []
    assert CHECKER.verify_cqg_cover_title(manuscript, stale)

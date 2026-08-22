"""Fail-closed consistency checks for the two v6 manuscripts.

This checker deliberately validates only exact numerical/textual contracts.
Scientific interpretation remains a human review task.  The machine-readable
contract is ``codex_research_notes/MASTER_NUMBERS_V6.yaml``.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT = (
    ROOT
    / "paper_draft"
    / "v6_paper"
    / "codex_research_notes"
    / "MASTER_NUMBERS_V6.yaml"
)
PAPERS = {
    "arxiv": ROOT / "paper_draft" / "v6_paper" / "arxiv_v6" / "main.tex",
    "cqg": ROOT / "paper_draft" / "v6_paper" / "cqg_v6" / "main.tex",
}
CQG_COVER = ROOT / "paper_draft" / "v6_paper" / "cqg_v6" / "cover_letter.tex"


@dataclass(frozen=True)
class Finding:
    paper: str
    kind: str
    fragment: str


def _normalized(text: str) -> str:
    """Normalize whitespace without hiding punctuation or numeric changes."""

    return re.sub(r"\s+", " ", text).strip()


def load_contract(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"contract is not a mapping: {path}")
    required = {"schema_version", "artifacts", "metrics", "manuscript_contract"}
    missing = required.difference(value)
    if missing:
        raise ValueError(f"contract is missing keys: {sorted(missing)}")
    return value


def check_text(paper: str, text: str, contract: dict) -> list[Finding]:
    normalized = _normalized(text)
    rules = contract["manuscript_contract"]
    findings: list[Finding] = []
    for fragment in rules.get("forbidden_fragments", []):
        if _normalized(str(fragment)) in normalized:
            findings.append(Finding(paper, "forbidden", str(fragment)))
    for fragment in rules.get("required_fragments_all", []):
        if _normalized(str(fragment)) not in normalized:
            findings.append(Finding(paper, "missing-required", str(fragment)))
    for fragment in rules.get("required_scope_terms", []):
        if _normalized(str(fragment)).lower() not in normalized.lower():
            findings.append(Finding(paper, "missing-scope", str(fragment)))
    return findings


def verify_artifact_hashes(contract: dict) -> list[str]:
    errors: list[str] = []
    for name, record in contract["artifacts"].items():
        path = ROOT / record["path"]
        if not path.is_file():
            errors.append(f"{name}: missing artifact {path}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record["sha256"]:
            errors.append(
                f"{name}: SHA256 mismatch expected={record['sha256']} actual={digest}"
            )
    return errors


def _load_json_artifact(contract: dict, name: str) -> dict:
    import json

    record = contract["artifacts"].get(name)
    if not isinstance(record, dict):
        raise ValueError(f"contract has no artifact record {name!r}")
    value = json.loads((ROOT / record["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"artifact {name!r} is not a JSON object")
    return value


def verify_transition_contract(contract: dict) -> list[str]:
    """Cross-check the master metrics against the transition JSON."""

    try:
        artifact = _load_json_artifact(contract, "representation_transition")
    except (OSError, ValueError) as exc:
        return [str(exc)]
    errors: list[str] = []
    population = contract["metrics"].get("population", {})
    if population.get("changed_dispositions") != artifact.get(
        "changed_dispositions"
    ):
        errors.append(
            "representation transition changed_dispositions disagrees with metrics"
        )
    if population.get("candidates_total") != artifact.get("current_total"):
        errors.append("representation transition current_total disagrees with metrics")
    return errors


def check_cqg_transition_table(text: str, contract: dict) -> list[Finding]:
    """Require every cell of the final detector-aware transition matrix."""

    artifact = _load_json_artifact(contract, "representation_transition")
    matrix = artifact["transition_matrix"]
    labels = {
        "ROBUST": r"\robust",
        "AMBIGUOUS": r"\ambiguous",
        "BACKGROUND": r"\background",
        "UNKNOWN": "UNKNOWN",
    }
    normalized = _normalized(text)
    findings: list[Finding] = []
    for row in artifact["matrix_row_order"]:
        values = [matrix[row][column] for column in artifact["matrix_column_order"]]
        fragment = " & ".join(
            [labels[row], *(f"{value:,}" for value in values)]
        )
        if _normalized(fragment) not in normalized:
            findings.append(Finding("cqg", "stale-transition-row", fragment))
    return findings


def _extract_title(text: str) -> str:
    match = re.search(r"\\title\{([^{}]+)\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("CQG manuscript has no simple \\title{...} command")
    return _normalized(match.group(1))


def verify_cqg_cover_title(manuscript_text: str, cover_text: str) -> list[str]:
    try:
        title = _extract_title(manuscript_text)
    except ValueError as exc:
        return [str(exc)]
    if title not in _normalized(cover_text):
        return ["CQG cover letter does not contain the exact manuscript title"]
    return []


def selected_papers(selection: str) -> Iterable[tuple[str, Path]]:
    if selection == "all":
        return PAPERS.items()
    return ((selection, PAPERS[selection]),)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check v6 manuscript numbers and scope language."
    )
    parser.add_argument("--paper", choices=("arxiv", "cqg", "all"), required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--verify-artifacts",
        action="store_true",
        help="also reconstruct every SHA256 recorded in the contract",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = load_contract(args.contract)
    errors: list[str] = []
    if args.verify_artifacts:
        errors.extend(verify_artifact_hashes(contract))
        errors.extend(verify_transition_contract(contract))

    findings: list[Finding] = []
    paper_texts: dict[str, str] = {}
    for paper, path in selected_papers(args.paper):
        if not path.is_file():
            errors.append(f"{paper}: missing manuscript {path}")
            continue
        paper_texts[paper] = path.read_text(encoding="utf-8")
        findings.extend(check_text(paper, paper_texts[paper], contract))

    if "cqg" in paper_texts:
        try:
            findings.extend(check_cqg_transition_table(paper_texts["cqg"], contract))
        except (OSError, ValueError, KeyError) as exc:
            errors.append(f"CQG transition table check failed: {exc}")
        if not CQG_COVER.is_file():
            errors.append(f"cqg: missing cover letter {CQG_COVER}")
        else:
            errors.extend(
                verify_cqg_cover_title(
                    paper_texts["cqg"], CQG_COVER.read_text(encoding="utf-8")
                )
            )

    for error in errors:
        print(f"ERROR {error}")
    for finding in findings:
        print(f"FAIL {finding.paper} {finding.kind}: {finding.fragment}")

    if errors or findings:
        print(
            f"CLAIM_CHECK=FAIL errors={len(errors)} findings={len(findings)}",
            file=sys.stderr,
        )
        return 1
    print(
        f"CLAIM_CHECK=PASS papers={args.paper} "
        f"artifacts={'verified' if args.verify_artifacts else 'not-requested'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

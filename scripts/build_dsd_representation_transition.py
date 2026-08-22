"""Build the detector-aware Q32/Q64 -> Q64/Q64 transition artifact.

The historical catalogue contains the mismatched Q32-index/Q64-query
disposition.  The current catalogue contains the detector-aware coherent
Q64/Q64 disposition.  This module joins them on the scientific identity
``(detector, gps_start)`` and emits the exact table used by the papers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CURRENT = (
    ROOT
    / "data"
    / "production"
    / "aggregated"
    / "Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"
)
HISTORICAL = (
    ROOT
    / "data"
    / "production"
    / "aggregated"
    / "archive"
    / "detector_dedup_bug_20260805"
    / "Master_Taxonomy_O4a_idxq4-64_queryq4-64.pre_detector_aware.csv"
)
OUTPUT = (
    ROOT
    / "data"
    / "production"
    / "aggregated"
    / "dsd_representation_transition_detector_aware.json"
)

KEY_COLUMNS = ["detector", "gps_start"]
MISMATCHED_COLUMN = "robustness_class"
COHERENT_COLUMN = "robustness_class_idxq4_64_queryq4_64"
ROW_ORDER = ["ROBUST", "AMBIGUOUS", "BACKGROUND", "UNKNOWN"]
COLUMN_ORDER = ["ROBUST", "AMBIGUOUS", "BACKGROUND"]

EXPECTED = {
    "current_total": 10_429,
    "paired_total": 10_372,
    "restored_total": 57,
    "changed_dispositions": 4_676,
    "current_class_counts": {
        "ROBUST": 6_365,
        "AMBIGUOUS": 1_275,
        "BACKGROUND": 2_789,
    },
    "restored_class_counts": {
        "ROBUST": 26,
        "AMBIGUOUS": 5,
        "BACKGROUND": 26,
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_unique(frame: pd.DataFrame, label: str) -> None:
    duplicated = frame.duplicated(KEY_COLUMNS, keep=False)
    if duplicated.any():
        sample = frame.loc[duplicated, KEY_COLUMNS].head(5).to_dict("records")
        raise ValueError(f"{label} has duplicate detector+GPS keys: {sample}")


def _class_counts(values: pd.Series) -> dict[str, int]:
    counts = values.value_counts(dropna=False).to_dict()
    return {label: int(counts.get(label, 0)) for label in COLUMN_ORDER}


def build_artifact(
    current_path: Path = CURRENT,
    historical_path: Path = HISTORICAL,
) -> dict:
    current = pd.read_csv(current_path)
    historical = pd.read_csv(historical_path)

    required_current = set(KEY_COLUMNS + [COHERENT_COLUMN, MISMATCHED_COLUMN])
    required_historical = set(KEY_COLUMNS + [MISMATCHED_COLUMN])
    missing_current = required_current.difference(current.columns)
    missing_historical = required_historical.difference(historical.columns)
    if missing_current or missing_historical:
        raise ValueError(
            "missing transition columns: "
            f"current={sorted(missing_current)} "
            f"historical={sorted(missing_historical)}"
        )

    _require_unique(current, "current taxonomy")
    _require_unique(historical, "historical taxonomy")

    current_classes = set(current[COHERENT_COLUMN].dropna().astype(str))
    if not current_classes.issubset(COLUMN_ORDER):
        raise ValueError(f"unexpected coherent classes: {sorted(current_classes)}")
    if not current[MISMATCHED_COLUMN].equals(current[COHERENT_COLUMN]):
        raise ValueError("current robustness_class alias is not the coherent class")

    paired = historical[KEY_COLUMNS + [MISMATCHED_COLUMN]].merge(
        current[KEY_COLUMNS + [COHERENT_COLUMN]],
        on=KEY_COLUMNS,
        how="left",
        validate="one_to_one",
    )
    missing = int(paired[COHERENT_COLUMN].isna().sum())
    if missing:
        raise ValueError(f"historical keys missing from current taxonomy: {missing}")

    historical_classes = set(paired[MISMATCHED_COLUMN].dropna().astype(str))
    if not historical_classes.issubset(ROW_ORDER):
        raise ValueError(
            f"unexpected mismatched classes: {sorted(historical_classes)}"
        )

    matrix_frame = pd.crosstab(
        paired[MISMATCHED_COLUMN], paired[COHERENT_COLUMN]
    ).reindex(index=ROW_ORDER, columns=COLUMN_ORDER, fill_value=0)
    matrix = {
        row: {column: int(matrix_frame.loc[row, column]) for column in COLUMN_ORDER}
        for row in ROW_ORDER
    }
    changed = int(
        (paired[MISMATCHED_COLUMN] != paired[COHERENT_COLUMN]).sum()
    )

    paired_keys = historical[KEY_COLUMNS].assign(_paired=True)
    restored = current.merge(
        paired_keys, on=KEY_COLUMNS, how="left", validate="one_to_one"
    )
    restored = restored.loc[restored["_paired"].isna()].copy()

    artifact = {
        "schema_version": 1,
        "status": "final",
        "experiment": "detector_aware_representation_contract_transition",
        "key_columns": KEY_COLUMNS,
        "mismatched_representation": "idxq4-32_queryq4-64",
        "coherent_representation": "idxq4-64_queryq4-64",
        "mismatched_class_column": MISMATCHED_COLUMN,
        "coherent_class_column": COHERENT_COLUMN,
        "source": {
            "historical_taxonomy": {
                "path": historical_path.relative_to(ROOT).as_posix(),
                "sha256": sha256(historical_path),
            },
            "current_taxonomy": {
                "path": current_path.relative_to(ROOT).as_posix(),
                "sha256": sha256(current_path),
            },
        },
        "current_total": int(len(current)),
        "paired_total": int(len(paired)),
        "paired_missing": missing,
        "restored_total": int(len(restored)),
        "changed_dispositions": changed,
        "current_class_counts": _class_counts(current[COHERENT_COLUMN]),
        "restored_class_counts": _class_counts(restored[COHERENT_COLUMN]),
        "transition_matrix": matrix,
        "matrix_row_order": ROW_ORDER,
        "matrix_column_order": COLUMN_ORDER,
    }
    validate_expected(artifact)
    return artifact


def validate_expected(artifact: dict) -> None:
    for field in ("current_total", "paired_total", "restored_total", "changed_dispositions"):
        if artifact[field] != EXPECTED[field]:
            raise ValueError(
                f"{field} drift: expected={EXPECTED[field]} actual={artifact[field]}"
            )
    for field in ("current_class_counts", "restored_class_counts"):
        if artifact[field] != EXPECTED[field]:
            raise ValueError(
                f"{field} drift: expected={EXPECTED[field]} actual={artifact[field]}"
            )
    matrix_total = sum(
        value
        for row in artifact["transition_matrix"].values()
        for value in row.values()
    )
    if matrix_total != artifact["paired_total"]:
        raise ValueError(
            f"transition matrix total mismatch: {matrix_total} != {artifact['paired_total']}"
        )


def serialized(artifact: dict) -> str:
    return json.dumps(artifact, indent=2, sort_keys=True) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build/check the detector-aware representation transition."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless the saved artifact equals a fresh reconstruction",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact = build_artifact()
    expected_text = serialized(artifact)
    if args.check:
        if not args.output.is_file():
            print(f"ERROR missing transition artifact: {args.output}", file=sys.stderr)
            return 1
        actual_text = args.output.read_text(encoding="utf-8")
        if actual_text != expected_text:
            print(
                f"ERROR stale transition artifact: {args.output}", file=sys.stderr
            )
            return 1
        print(
            "TRANSITION_CHECK=PASS "
            f"paired={artifact['paired_total']} "
            f"changed={artifact['changed_dispositions']} "
            f"restored={artifact['restored_total']}"
        )
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected_text, encoding="utf-8")
    print(
        f"WROTE {args.output} paired={artifact['paired_total']} "
        f"changed={artifact['changed_dispositions']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

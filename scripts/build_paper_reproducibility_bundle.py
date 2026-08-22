"""Build the portable evidence bundle supporting the DANTE v6 manuscripts.

The bundle is deliberately allowlisted.  It contains final numerical artefacts,
per-trial tables, provenance records, manuscript sources, figures and the
verification code needed to audit published numbers.  It excludes raw GWOSC
strain, auxiliary-channel downloads, model/token caches, credentials, pilot
outputs and archived stale artefacts.

Text files are made portable in the bundle copy only.  Machine-local absolute
paths are replaced with explicit repository-relative or
``GWOSC_RAW_DATA_NOT_BUNDLED`` markers.  ``SOURCE_PROVENANCE.json`` records the
source and bundled SHA256 for every file, so this transformation is auditable.
Source artefacts in the repository are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

import yaml


ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper_draft" / "v6_paper"
RELEASE = PAPER / "release" / "v6_reproducibility"
ZIP_PATH = PAPER / "release" / "dante_v6_reproducibility.zip"
MASTER = PAPER / "codex_research_notes" / "MASTER_NUMBERS_V6.yaml"
README = RELEASE / "README.md"

TEXT_SUFFIXES = {".bib", ".csv", ".json", ".md", ".py", ".tex", ".txt", ".yaml", ".yml"}
FORBIDDEN_PARTS = {"archive", ".corrupt", "cache", "credentials", "raw"}
FORBIDDEN_NAME_FRAGMENTS = ("pilot", "stale", "backup")
HISTORICAL_TRANSITION_BASELINE = (
    "data/production/aggregated/archive/detector_dedup_bug_20260805/"
    "Master_Taxonomy_O4a_idxq4-64_queryq4-64.pre_detector_aware.csv"
)
ABSOLUTE_PATTERNS = (
    re.compile(rb"[A-Za-z]:\\\\(?:Users|home)\\\\", re.IGNORECASE),
    re.compile(rb"[A-Za-z]:\\(?:Users|home)\\", re.IGNORECASE),
    re.compile(rb"/mnt/[a-z]/", re.IGNORECASE),
    re.compile(rb"/home/[^/]+/", re.IGNORECASE),
)

STATIC_ALLOWLIST = (
    "paper_draft/v6_paper/LAB_NOTEBOOK.md",
    "paper_draft/v6_paper/codex_research_notes/MASTER_NUMBERS_V6.yaml",
    "paper_draft/v6_paper/codex_research_notes/CLAIM_LEDGER.md",
    "paper_draft/v6_paper/codex_research_notes/CQG_REFERENCE_AUDIT_2026-08-07.md",
    "paper_draft/v6_paper/codex_research_notes/FREQUENCY_BAND_AUDIT_CORRECTION_2026-08-07.md",
    "paper_draft/v6_paper/codex_research_notes/FINAL_REPORTING_COMPLETION_2026-08-12.md",
    "paper_draft/v6_paper/arxiv_v6/main.tex",
    "paper_draft/v6_paper/arxiv_v6/references.bib",
    "paper_draft/v6_paper/cqg_v6/main.tex",
    "paper_draft/v6_paper/cqg_v6/references.bib",
    "paper_draft/v6_paper/cqg_v6/cover_letter.tex",
    "paper_draft/v6_paper/tools/check_manuscript_claims.py",
    "paper_draft/v6_paper/tools/generate_paper_figures.py",
    "paper_draft/v6_paper/tools/generate_candidate_and_method_figures.py",
    "scripts/build_dsd_representation_transition.py",
    "scripts/build_paper_reproducibility_bundle.py",
    "scripts/run_dsd_block_length_sensitivity.py",
    "scripts/run_gw_autoencoder_baseline.py",
    "scripts/verify_c2_bgv3_artifacts.py",
    "scripts/verify_cqg_validation_artifacts.py",
    "tests/test_dsd_block_length_sensitivity.py",
    "tests/test_gw_autoencoder_baseline.py",
    "tests/test_manuscript_claim_checker.py",
    "tests/test_paper_reproducibility_bundle.py",
    "tests/test_patch_axis_mapping.py",
    "tests/test_v6_candidate_figures.py",
    "data/production/aggregated/Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv",
    HISTORICAL_TRANSITION_BASELINE,
    "data/production/aggregated/dsd_scores_o4a_idxq4-64_queryq4-64.csv",
    "data/production/aggregated/whitening_context_scores_o4a_idxq4-64_queryq4-64.csv",
    "data/production/aggregated/whitening_context_scoring_failures_o4a_idxq4-64_queryq4-64.csv",
    "data/production/aggregated/astrophysical_injection_trials_o4a_idxq4-64_queryq4-64.csv",
    "data/production/aggregated/catalog_cross_match_events_circular_shift_v2_idxq4-64_queryq4-64_o4a.csv",
    "data/production/aggregated/catalog_cross_match_manifest_circular_shift_v2_idxq4-64_queryq4-64_o4a.json",
    "data/production/aggregated/catalog_cross_match_null_circular_shift_v2_idxq4-64_queryq4-64_o4a.csv",
    "data/production/aggregated/pem/idxq4-64_queryq4-64/coherence_report.csv",
    "data/production/aggregated/pem/idxq4-64_queryq4-64/pem_family_wise_verdicts.csv",
    "data/production/aggregated/pem/idxq4-64_queryq4-64/pem_provenance_manifest.json",
    "data/production/aggregated/pem/idxq4-64_queryq4-64/selected_targets.csv",
    "data/production/aggregated/pem/idxq4-64_queryq4-64/selection_manifest.json",
    "data/production/aggregated/pem/idxq4-64_queryq4-64/environment_pem_o4a_idxq4-64_queryq4-64.json",
    "data/production/aggregated/pem/idxq4-64_queryq4-64/source_state_pem_o4a_idxq4-64_queryq4-64.zip",
    "data/production/aggregated/candidate_case_L1_1382955228_idxq4-64_queryq4-64.json",
    "data/production/aggregated/characterize_L1_1382955232.json",
    "data/production/aggregated/Multiscale_Profile_O4a_idxq4-64_queryq4-64.csv",
    "data/production/aggregated/environment_astrophysical_injection_o4a_idxq4-64_queryq4-64.json",
    "data/production/aggregated/environment_blind_spot_map_centered_q64_v3_o4a.json",
    "data/production/aggregated/environment_catalog_cross_match_circular_shift_v2_idxq4-64_queryq4-64_o4a.json",
    "data/production/aggregated/environment_coincidence_physical_o4a.json",
    "data/production/aggregated/environment_dsd_index_stability_o4a_idxq4-64_queryq4-64.json",
    "data/production/aggregated/environment_dsd_k_sensitivity_o4a_idxq4-64_queryq4-64.json",
    "data/production/aggregated/environment_dsd_threshold_mc_error_o4a_idxq4-64_queryq4-64.json",
    "data/production/aggregated/environment_dsd_transition_o4a_idxq4-64_queryq4-64.json",
    "data/production/aggregated/environment_inter_session_recurrence_o4a_idxq4-64_queryq4-64.json",
    "data/production/aggregated/environment_pca_baseline_o4a_idxq4-64_queryq4-64.json",
    "data/production/aggregated/environment_whitening_context_sensitivity_o4a_idxq4-64_queryq4-64.json",
    "data/production/aggregated/pem/idxq4-64_queryq4-64/environment_pem_c2_bgv3_o4a_idxq4-64_queryq4-64.json",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(raw: str | Path) -> str:
    value = PurePosixPath(str(raw).replace("\\", "/"))
    if value.is_absolute() or ".." in value.parts:
        raise RuntimeError(f"unsafe bundle path: {raw}")
    lower = [part.lower() for part in value.parts]
    # The detector-aware transition has one immutable pre-fix taxonomy as an
    # explicit scientific input.  It is the sole archived path eligible for
    # the evidence bundle; all other archived outputs remain fail-closed.
    if any(part in FORBIDDEN_PARTS for part in lower) and value.as_posix() != HISTORICAL_TRANSITION_BASELINE:
        raise RuntimeError(f"forbidden bundle path component: {raw}")
    name = value.name.lower()
    if any(fragment in name for fragment in FORBIDDEN_NAME_FRAGMENTS):
        raise RuntimeError(f"pilot/stale/backup file is not eligible: {raw}")
    return value.as_posix()


def _portable_text(data: bytes) -> tuple[bytes, bool]:
    text = data.decode("utf-8")
    original = text
    root_win = str(ROOT)
    root_posix = ROOT.as_posix()
    replacements = (
        (root_win + "\\", ""),
        (root_win.replace("\\", "\\\\") + "\\\\", ""),
        (root_posix + "/", ""),
        ("/mnt/c/Users/atafe/PycharmProjects/dante-gravi-signal-ml/", ""),
        ("E:\\o4a\\", "GWOSC_RAW_DATA_NOT_BUNDLED/"),
        ("E:\\\\o4a\\\\", "GWOSC_RAW_DATA_NOT_BUNDLED/"),
        ("/mnt/e/o4a/", "GWOSC_RAW_DATA_NOT_BUNDLED/"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    text = re.sub(r"C:\\Users\\atafe\\[^\s\"']+", "<LOCAL_PATH>", text, flags=re.IGNORECASE)
    text = re.sub(r"C:\\\\Users\\\\atafe\\\\[^\s\"']+", "<LOCAL_PATH>", text, flags=re.IGNORECASE)
    text = re.sub(r"/home/[^/]+/", "<LOCAL_HOME>/", text, flags=re.IGNORECASE)
    text = re.sub(r"/mnt/[a-z]/", "<LOCAL_MOUNT>/", text, flags=re.IGNORECASE)
    encoded = text.encode("utf-8")
    for pattern in ABSOLUTE_PATTERNS:
        if pattern.search(encoded):
            raise RuntimeError(f"machine-local absolute path remains after portability rewrite: {pattern.pattern!r}")
    return encoded, text != original


def _eligible_bytes(path: Path) -> tuple[bytes, bool]:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data, rewritten = _portable_text(data)
        if path.suffix.lower() == ".json":
            value = json.loads(data.decode("utf-8"))
            if isinstance(value, dict) and str(value.get("status", "")).lower() in {
                "pilot", "stale", "incomplete", "failed",
            }:
                raise RuntimeError(f"non-final JSON status in {path}")
        return data, rewritten
    return data, False


def source_paths() -> list[str]:
    master = yaml.safe_load(MASTER.read_text(encoding="utf-8"))
    paths = set(STATIC_ALLOWLIST)
    for record in master["artifacts"].values():
        path = _safe_relative(record["path"])
        source = ROOT / path
        if sha256_file(source) != record["sha256"]:
            raise RuntimeError(f"MASTER hash mismatch: {path}")
        paths.add(path)

    absorption = json.loads((ROOT / master["artifacts"]["cqg_absorption_matrix"]["path"]).read_text(encoding="utf-8"))
    for record in absorption["cell_artifacts"]:
        path = _safe_relative(record["path"])
        if sha256_file(ROOT / path) != record["sha256"]:
            raise RuntimeError(f"absorption-cell hash mismatch: {path}")
        paths.add(path)

    def add_hashed(record: dict[str, str], label: str) -> None:
        path = _safe_relative(record["path"])
        if sha256_file(ROOT / path) != record["sha256"]:
            raise RuntimeError(f"{label} hash mismatch: {path}")
        paths.add(path)

    block = json.loads(
        (ROOT / master["artifacts"]["block_length_sensitivity"]["path"])
        .read_text(encoding="utf-8")
    )
    add_hashed(block["sources"]["thresholds"], "block thresholds")
    add_hashed(block["sources"]["taxonomy"], "block taxonomy")
    for detector, record in block["sources"]["background_scores"].items():
        add_hashed(record, f"block {detector} background")

    autoencoder = json.loads(
        (ROOT / master["artifacts"]["gw_autoencoder_baseline"]["path"])
        .read_text(encoding="utf-8")
    )
    for name in ("thresholds", "taxonomy", "candidate_feature_cache", "scores"):
        add_hashed(autoencoder["sources"][name], f"autoencoder {name}")
    for detector, record in autoencoder["sources"]["backgrounds"].items():
        for name, hash_name in (
            ("feature_cache", "feature_cache_sha256"),
            ("selection_ledger", "selection_ledger_sha256"),
            ("upstream_calibration_ledger", "upstream_calibration_ledger_sha256"),
        ):
            add_hashed(
                {"path": record[name], "sha256": record[hash_name]},
                f"autoencoder {detector} {name}",
            )

    pem_dir = ROOT / "data/production/aggregated/pem/idxq4-64_queryq4-64"
    nulls = sorted(pem_dir.glob("null_calibration_*.json"))
    if len(nulls) != 141:
        raise RuntimeError(f"expected 141 final PEM null files, found {len(nulls)}")
    paths.update(path.relative_to(ROOT).as_posix() for path in nulls)

    for manuscript, minimum_figures in (("arxiv_v6", 9), ("cqg_v6", 9)):
        text = (PAPER / manuscript / "main.tex").read_text(encoding="utf-8")
        figure_names = sorted(set(re.findall(
            r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+\.png)\}", text
        )))
        if len(figure_names) < minimum_figures:
            raise RuntimeError(
                f"expected at least {minimum_figures} referenced {manuscript} figures, "
                f"found {len(figure_names)}"
            )
        figures = [PAPER / manuscript / "img" / name for name in figure_names]
        missing = [path for path in figures if not path.is_file()]
        if missing:
            raise RuntimeError(f"missing manuscript figures: {missing}")
        paths.update(path.relative_to(ROOT).as_posix() for path in figures)

    result = sorted(_safe_relative(path) for path in paths)
    for path in result:
        source = ROOT / path
        if not source.is_file():
            raise FileNotFoundError(source)
    return result


def expected_payload() -> tuple[dict[str, bytes], list[dict[str, object]]]:
    payload: dict[str, bytes] = {}
    provenance: list[dict[str, object]] = []
    for relative in source_paths():
        source = ROOT / relative
        data, rewritten = _eligible_bytes(source)
        payload[relative] = data
        provenance.append({
            "path": relative,
            "source_size": source.stat().st_size,
            "source_sha256": sha256_file(source),
            "bundle_size": len(data),
            "bundle_sha256": sha256_bytes(data),
            "portable_text_rewrite": rewritten,
        })
    return payload, provenance


def _manifest(payload: dict[str, bytes]) -> bytes:
    lines = [f"{sha256_bytes(data)}  {path}" for path, data in sorted(payload.items())]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _zip_bytes(path: Path, payload: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)


def build(release: Path = RELEASE, zip_path: Path = ZIP_PATH) -> None:
    if not README.is_file() and release == RELEASE:
        raise FileNotFoundError(README)
    payload, provenance = expected_payload()
    readme_source = README if release == RELEASE else README
    readme_data, _ = _portable_text(readme_source.read_bytes())
    payload["README.md"] = readme_data
    provenance_data = (json.dumps({
        "schema_version": 1,
        "source_root_not_bundled": True,
        "files": provenance,
    }, indent=2, sort_keys=True) + "\n").encode("utf-8")
    payload["SOURCE_PROVENANCE.json"] = provenance_data
    payload["MANIFEST.sha256"] = _manifest(payload)

    release.mkdir(parents=True, exist_ok=True)
    expected_names = set(payload)
    existing = {
        path.relative_to(release).as_posix()
        for path in release.rglob("*") if path.is_file()
    }
    unexpected = existing - expected_names
    if unexpected:
        raise RuntimeError(f"unexpected files already present in release directory: {sorted(unexpected)}")
    for relative, data in payload.items():
        target = release / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _zip_bytes(zip_path, payload)


def check(release: Path = RELEASE, zip_path: Path = ZIP_PATH) -> None:
    payload, provenance = expected_payload()
    readme_data, _ = _portable_text(README.read_bytes())
    payload["README.md"] = readme_data
    payload["SOURCE_PROVENANCE.json"] = (json.dumps({
        "schema_version": 1,
        "source_root_not_bundled": True,
        "files": provenance,
    }, indent=2, sort_keys=True) + "\n").encode("utf-8")
    payload["MANIFEST.sha256"] = _manifest(payload)
    actual_names = {
        path.relative_to(release).as_posix()
        for path in release.rglob("*") if path.is_file()
    }
    if actual_names != set(payload):
        raise RuntimeError(f"release file-set mismatch: missing={sorted(set(payload)-actual_names)}, extra={sorted(actual_names-set(payload))}")
    for relative, expected in payload.items():
        observed = (release / relative).read_bytes()
        if observed != expected:
            raise RuntimeError(f"release drift: {relative}")
    with zipfile.ZipFile(zip_path) as archive:
        if set(archive.namelist()) != set(payload):
            raise RuntimeError("ZIP file-set mismatch")
        for relative, expected in payload.items():
            if archive.read(relative) != expected:
                raise RuntimeError(f"ZIP content drift: {relative}")
    print(f"BUNDLE_CHECK=PASS files={len(payload)} zip_sha256={sha256_file(zip_path)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify an existing bundle without modifying it")
    args = parser.parse_args()
    if args.check:
        check()
    else:
        build()
        check()


if __name__ == "__main__":
    main()

from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
import json

from src.dante_light.contracts import WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_splits import write_prefilter_splits
from src.dante_light.prefilter_v2_protocol import (
    load_prefilter_v2_protocol,
)
from src.dante_light.prefilter_v2_splits import build_prefilter_v2_splits


def _row(run, detector, gps, role, morphology, partition, *, gravityspy_id=None):
    row = {
        "cohort_id": f"{role}:{detector}:{morphology}:{gps}",
        "role": role,
        "detector": detector,
        "morphology": morphology,
        "retention_target": role != "background",
        "window": WindowIdentity(run, detector, gps).to_dict(),
        "partition": partition,
        "partition_priority": hashlib.sha256(str(gps).encode("ascii")).hexdigest(),
    }
    if gravityspy_id is not None:
        row["gravityspy_id"] = gravityspy_id
    return row


def _cohort(role, rows, seed):
    rows = sorted(rows, key=lambda row: row["cohort_id"])
    body = {"role": role, "seed": seed, "sources": [], "rows": rows}
    return {
        **body,
        "split_sha256": canonical_json_sha256(body),
        "counts": {
            "total": len(rows),
            "development": sum(row["partition"] == "development" for row in rows),
            "evaluation": sum(row["partition"] == "evaluation" for row in rows),
        },
    }


def _write_fixture(tmp_path):
    seed = 12345
    roles = {role: [] for role in ("background", "robust_candidate", "known_glitch", "injection")}
    gps = 1_000_000_000.0
    for detector_index, detector in enumerate(("H1", "L1")):
        offset = detector_index * 10_000_000
        for index in range(200):
            roles["background"].append(_row("O4A", detector, gps + offset + index * 32, "background", "clean_background", "development"))
        for partition, count, base in (("development", 20, 1_000_000), ("evaluation", 20, 2_000_000)):
            for index in range(count):
                roles["robust_candidate"].append(_row("O4A", detector, gps + offset + base + index * 32, "robust_candidate", "unknown", partition))
        for morphology_index, morphology in enumerate(("Blip", "KoiFish", "ScatteredLight")):
            for partition, count, base in (("development", 12, 3_000_000), ("evaluation", 18, 4_000_000)):
                for index in range(count):
                    event_gps = gps + offset + base + morphology_index * 100_000 + index * 32
                    roles["known_glitch"].append(_row("O3B", detector, event_gps, "known_glitch", morphology, partition, gravityspy_id=f"base-{detector}-{morphology}-{partition}-{index}"))
        for morphology_index, morphology in enumerate(("BBH_30_30", "BBH_10_10", "NSBH_10_1.4")):
            for partition, count, base in (("development", 35, 5_000_000), ("evaluation", 90, 6_000_000)):
                for index in range(count):
                    roles["injection"].append(_row("O4A", detector, gps + offset + base + morphology_index * 100_000 + index * 32, "injection", morphology, partition))
    split = {
        "schema_version": 1,
        "status": "locked_before_feature_extraction",
        "seed": seed,
        "outcome_fields_used_for_partition": [],
        "cohorts": {role: _cohort(role, rows, seed) for role, rows in roles.items()},
    }
    split["artifact_digest"] = canonical_json_sha256(split)
    base_path = tmp_path / "config" / "base.json"
    write_prefilter_splits(split, base_path)

    taxonomy_path = tmp_path / "data" / "taxonomy.csv"
    taxonomy_path.parent.mkdir(parents=True)
    with taxonomy_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["gps_start", "detector", "robustness_class"])
        writer.writeheader()
        for detector_index, detector in enumerate(("H1", "L1")):
            for index in range(20):
                writer.writerow({"gps_start": int(gps + detector_index * 10_000_000 + 7_000_000 + index * 64), "detector": detector, "robustness_class": "ROBUST"})

    catalog_paths = {}
    for detector_index, detector in enumerate(("H1", "L1")):
        path = tmp_path / "data" / f"catalog_{detector}.csv"
        catalog_paths[detector] = path
        with path.open("w", newline="", encoding="utf-8") as stream:
            fields = ["event_time", "ifo", "ml_label", "ml_confidence", "snr", "gravityspy_id"]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for morphology_index, label in enumerate(("Blip", "Koi_Fish", "Scattered_Light")):
                for index in range(50):
                    writer.writerow({
                        "event_time": gps + detector_index * 10_000_000 + 8_000_000 + morphology_index * 100_000 + index * 64,
                        "ifo": detector,
                        "ml_label": label,
                        "ml_confidence": 0.99,
                        "snr": 12.0,
                        "gravityspy_id": f"new-{detector}-{label}-{index}",
                    })
    controls_path = tmp_path / "data" / "production" / "aggregated" / "cqg_known_glitch_controls.json"
    controls_path.parent.mkdir(parents=True)
    controls_path.write_text(json.dumps({"detectors": {detector: {"clean_gps": {"train": [100.0], "held_out": [200.0]}} for detector in ("H1", "L1")}}), encoding="utf-8")

    protocol_payload = deepcopy(dict(load_prefilter_v2_protocol().payload))
    protocol_payload["cohort_split_seed"] = seed
    base_rules = protocol_payload["cohort_augmentation"]["base_split"]
    base_rules.update({
        "path": "config/base.json",
        "sha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
        "entries_sha256": hashlib.sha256(base_path.with_suffix(".jsonl").read_bytes()).hexdigest(),
    })
    robust_rules = protocol_payload["cohort_augmentation"]["robust_candidate"]
    robust_rules.update({"source_path": "data/taxonomy.csv", "source_sha256": hashlib.sha256(taxonomy_path.read_bytes()).hexdigest()})
    known_rules = protocol_payload["cohort_augmentation"]["known_glitch"]
    known_rules["catalog_paths"] = {detector: f"data/catalog_{detector}.csv" for detector in ("H1", "L1")}
    known_rules["catalog_sha256"] = {detector: hashlib.sha256(path.read_bytes()).hexdigest() for detector, path in catalog_paths.items()}
    protocol_payload.pop("protocol_digest")
    protocol_payload["protocol_digest"] = canonical_json_sha256(protocol_payload)
    protocol_path = tmp_path / "config" / "protocol.json"
    protocol_path.write_text(json.dumps(protocol_payload), encoding="utf-8")
    return load_prefilter_v2_protocol(protocol_path)


def test_v2_split_augments_development_without_changing_evaluation(tmp_path):
    protocol = _write_fixture(tmp_path)
    calls = []

    def preflight(window):
        calls.append(window.window_id)
        return {"strain_sha256": "a" * 64, "sample_rate_hz": 4096}

    result = build_prefilter_v2_splits(root=tmp_path, protocol=protocol, preflight=preflight)
    assert result["status"] == "availability_screened_before_feature_extraction"
    assert result["feature_values_used_for_partition"] == []
    assert result["exact_scores_used_for_partition"] == []
    assert result["cohorts"]["robust_candidate"]["counts"] == {"total": 90, "development": 50, "evaluation": 40}
    assert result["cohorts"]["known_glitch"]["counts"] == {"total": 258, "development": 150, "evaluation": 108}
    assert result["cohorts"]["injection"]["counts"]["evaluation"] == 540
    assert len(calls) == 88
    assert all(row["window"]["run"] != "O4B" for cohort in result["cohorts"].values() for row in cohort["rows"] if row["partition"] == "development")


def test_v2_split_backfills_availability_failure_without_outcomes(tmp_path):
    protocol = _write_fixture(tmp_path)
    count = 0

    def preflight(window):
        nonlocal count
        count += 1
        if count == 1:
            raise RuntimeError("synthetic availability failure")
        return {"strain_sha256": "b" * 64}

    result = build_prefilter_v2_splits(root=tmp_path, protocol=protocol, preflight=preflight)
    failures = result["availability_preflight"]["robust_candidate_failures"]
    assert len(failures) == 1
    assert failures[0]["error_type"] == "RuntimeError"
    assert result["cohorts"]["robust_candidate"]["counts"]["development"] == 50

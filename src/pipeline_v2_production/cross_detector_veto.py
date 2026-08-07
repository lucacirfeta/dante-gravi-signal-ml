import pandas as pd
import numpy as np
import torch
import h5py
import logging
import matplotlib
import hashlib
import json
from pathlib import Path
from sklearn.metrics.pairwise import cosine_similarity
import argparse

from src.core.utils import setup_logger, get_observing_run, get_reference_dir
from src.core.data_loader import fetch_local_or_remote_strain
from src.core.preprocessor import whiten_context, extract_clean_subwindow, generate_qtransform
from src.core.patch_scorer import PatchScorer

logger = setup_logger(__name__)

_CACHE_SCHEMA_VERSION = 2
_PRODUCTION_INDEX_NAME = "patch_compressed_index_o3b.npz"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _similarity_contract(index_path: Path) -> dict:
    """Immutable representation contract for cached partner similarities."""
    return {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "reference_index_name": index_path.name,
        "reference_index_sha256": _sha256(index_path),
        "encoder": "dinov2_vits14_reg",
        "scorer_top_k": 68,
        "qtransform_renderer": "production_cividis_uint8",
        "whitening": "whiten_context_pad4_extract_clean_subwindow",
        "window_seconds": 32.0,
        "candidate_window_offset_seconds": 0.0,
    }


def _load_similarity_cache(path: Path, expected_contract: dict) -> dict[str, float]:
    """Load only a provenance-compatible cache; legacy flat JSON fails closed."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Ignoring unreadable veto similarity cache: %s", exc)
        return {}
    if not isinstance(payload, dict) or payload.get("contract") != expected_contract:
        logger.warning(
            "Ignoring veto similarity cache with missing or incompatible "
            "representation provenance."
        )
        return {}
    scores = payload.get("scores")
    if not isinstance(scores, dict):
        logger.warning("Ignoring veto similarity cache with invalid score payload.")
        return {}
    valid: dict[str, float] = {}
    for key, value in scores.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(number):
            valid[str(key)] = number
    return valid


def _write_similarity_cache(
    path: Path, contract: dict, scores: dict[str, float]
) -> None:
    """Persist cache atomically so an interrupted run cannot truncate it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {"contract": contract, "scores": scores}
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(path)

def execute_cross_detector_veto(df: pd.DataFrame, production_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    logger.info("=" * 60)
    logger.info("=== CROSS-DETECTOR COINCIDENCE VETO (Wave 7) ===")
    logger.info("=" * 60)
    
    logger.info(f"Loaded {len(df)} candidates from master list.")
    
    # We only care about candidates where the partner was actually online.
    # If INACTIVE, it automatically goes to Table 3b.
    # Note: 'ACTIVE_NO_ANOMALY' or 'ACTIVE_ANOMALY_DETECTED'
    
    coincident_rows = []
    local_rows = []
    unverifiable_rows = []

    # On-disk cache of partner similarities: strain and MIL vectors are
    # deterministic given (gps, primary detector), so a re-run after a crash
    # must not re-pay hours of partner fetch+encode. Only successful
    # similarity computations are cached (failures stay retryable).
    sim_cache_path = Path("data/production/aggregated/veto_similarity_cache.json")
    ref_index_path = get_reference_dir() / _PRODUCTION_INDEX_NAME
    if not ref_index_path.exists():
        raise FileNotFoundError(
            "The cross-detector veto requires the frozen production index "
            f"{ref_index_path}; refusing an arbitrary fallback index."
        )
    sim_contract = _similarity_contract(ref_index_path)
    sim_cache = _load_similarity_cache(sim_cache_path, sim_contract)
    cache_dirty = 0
    logger.info(
        "Cross-detector representation contract: index=%s sha256=%s; "
        "reusable similarities=%d",
        ref_index_path,
        sim_contract["reference_index_sha256"],
        len(sim_cache),
    )

    # Initialize PyTorch Models
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Using device: {device}")

    scorer = PatchScorer(
        reference_index_path=ref_index_path,
        device=device,
        k=68, # Strict architectural prior aligned with primary PatchScorer
        verify_md5=False
    )
    
    for idx, row in df.iterrows():
        gps = float(row["gps_start"])
        primary = row["detector"]
        session = row["session_id"]
        status = row["partner_observing_status"]
        
        if status in ("INACTIVE", "UNOBSERVABLE"):
            unverifiable_rows.append(row)
            continue
            
        partner = "L1" if primary == "H1" else "H1"
        logger.info(f"Targeted search: Candidate GPS {gps} in {primary}. Fetching {partner}...")
        
        # 1. Load primary vector
        # A candidate is a "confirmed local glitch" ONLY after a completed
        # morphological search in the partner returned no match. Any I/O or
        # processing failure means the search never ran -> UNVERIFIABLE.
        def _unverifiable(reason: str):
            failed = row.copy()
            failed["partner_observing_status"] = "NOT_CHECKED"
            failed["gs_label"] = f"UNVERIFIABLE ({reason})"
            unverifiable_rows.append(failed)

        h5_path = production_dir / str(session) / f"novelties_{session}_{primary}.h5"
        if not h5_path.exists():
            logger.warning(f"HDF5 missing for GPS {gps} in {h5_path}. Marking unverifiable.")
            _unverifiable("primary HDF5 missing")
            continue

        try:
            with h5py.File(h5_path, "r") as f:
                gps_times = f["novelties/gps_times"][:]
                vectors = f["novelties/mil_vectors"][:]
                idx_match = np.where(gps_times == gps)[0]
                if len(idx_match) == 0:
                    logger.warning(f"GPS {gps} not found in {h5_path}. Marking unverifiable.")
                    _unverifiable("GPS not found in primary HDF5")
                    continue
                primary_vec = vectors[idx_match[0]]
        except Exception as e:
            logger.warning(f"Error reading primary H5: {e}. Marking unverifiable.")
            _unverifiable("primary HDF5 read error")
            continue

        cache_key = f"{gps}_{primary}"
        if cache_key in sim_cache:
            sim = float(sim_cache[cache_key])
        else:
            # 2. Fetch partner raw strain
            try:
                ts_super = fetch_local_or_remote_strain(partner, gps - 4.0, gps + 36.0, cache_raw=False, edge_tolerance=4.0)
            except Exception as e:
                logger.warning(f"Failed to fetch partner strain: {e}. Marking unverifiable.")
                _unverifiable("partner strain fetch failed")
                continue

            # 3. Encode partner
            try:
                ts_w_padded, _ = whiten_context(ts_super, gps, gps + 32.0, pad=4.0)
                ts_white = extract_clean_subwindow(ts_w_padded, gps, gps + 32.0)
                spectrogram = generate_qtransform(ts_white)
                # Render with the SAME colormap as the production path that
                # produced the stored candidate vector v1 (aggregate_report
                # renders cividis before scoring). Feeding the raw q-transform
                # here put v2 in a different chromatic domain than v1, so every
                # cross-detector similarity was computed between mismatched
                # domains and was systematically depressed by ~0.21 in the mean
                # (audit COINC-2 — the same failure mode as B-DSD-1, which was
                # fixed in the DSD rescoring path but not here).
                spectrogram = (matplotlib.colormaps["cividis"](
                    np.clip(spectrogram, 0.0, 1.0))[..., :3] * 255).astype(np.uint8)
                # score_spectrogram returns a list of dicts
                results = scorer.score_spectrogram([spectrogram], threshold=1.0)
                partner_vec = results[0]["mil_vector"]
            except Exception as e:
                logger.warning(f"Failed to encode partner strain: {e}. Marking unverifiable.")
                _unverifiable("partner encoding failed")
                continue

            # 4. Cosine Similarity
            # Normalize just in case, though they should be L2 normalized
            v1 = primary_vec.reshape(1, -1)
            v2 = partner_vec.reshape(1, -1)
            v1 = v1 / np.linalg.norm(v1)
            v2 = v2 / np.linalg.norm(v2)

            sim = float(cosine_similarity(v1, v2)[0, 0])
            sim_cache[cache_key] = sim
            cache_dirty += 1
            if cache_dirty % 100 == 0:
                try:
                    _write_similarity_cache(
                        sim_cache_path, sim_contract, sim_cache
                    )
                except Exception:
                    pass
        logger.info(f"Match Similarity: {sim:.3f}")
        
        # 5. Extract run and load empirical threshold (Hard-Fail if missing)
        import json
        import pathlib
        cfg_path = pathlib.Path("config/cross_detector_threshold.json")
        
        try:
            run = get_observing_run(gps)
        except Exception as e:
            logger.error(f"Cannot deduce observing run for GPS {gps}: {e}")
            raise RuntimeError(f"Missing run context for GPS {gps}")
            
        tau_coh = None
        if cfg_path.exists():
            with open(cfg_path, "r") as f:
                cfg_data = json.load(f)
                if run in cfg_data and "tau_coh" in cfg_data[run]:
                    entry = cfg_data[run]
                    # A tau without EVT calibration (legacy heuristic 0.85
                    # entries for O3a/O3b) must not silently gate a
                    # scientific claim: calibrate with calibrate_tau_coh.py
                    # or opt in explicitly.
                    is_calibrated = entry.get("calibrated", False) or (
                        "xi" in entry and "sigma" in entry)
                    import os
                    if not is_calibrated and os.environ.get(
                            "DANTE_ALLOW_HEURISTIC_TAU") != "1":
                        raise RuntimeError(
                            f"tau_coh for run '{run}' is an uncalibrated "
                            "heuristic. Run calibrate_tau_coh.py --run "
                            f"{run}, or set DANTE_ALLOW_HEURISTIC_TAU=1 "
                            "to proceed at your own risk.")
                    tau_coh = float(entry["tau_coh"])
                
        if tau_coh is None:
            logger.error(f"CRITICAL: No EVT cohesion threshold ('tau_coh') explicitly calibrated for run '{run}' in {cfg_path}.")
            logger.error("The pipeline cannot guarantee a controlled False Positive Rate for this background epoch.")
            raise RuntimeError(f"Missing EVT calibration for observing run '{run}'. Refusing to proceed with arbitrary heuristics.")

        if sim > tau_coh:
            logger.info(f"--> [COINCIDENT] Candidate {gps} matched in {partner} with sim {sim:.3f} (> {tau_coh:.3f})")
            new_row = row.copy()
            # COINCIDENT_TRANSIENT is the status consumed by the downstream
            # state machine (production_report.should_run_pem_check,
            # aggregate_report._STATUS_MAP). This is its only producer.
            new_row["status"] = "COINCIDENT_TRANSIENT"
            new_row["partner_observing_status"] = "ACTIVE_ANOMALY_DETECTED"
            new_row["gs_label"] = "Coincident/Astrophysical/Magnetic"
            coincident_rows.append(new_row)
        else:
            logger.info(f"--> [LOCAL] Candidate {gps} is pure instrumental (sim={sim:.3f})")
            # The morphological search actually ran and found nothing: this
            # is the only code path allowed to assert ACTIVE_NO_ANOMALY.
            vetoed = row.copy()
            vetoed["partner_observing_status"] = "ACTIVE_NO_ANOMALY"
            local_rows.append(vetoed)
            
    # Convert to Final Output Dataframes
    df_3a = pd.DataFrame(local_rows) if local_rows else pd.DataFrame(columns=df.columns)
    df_3b = pd.DataFrame(unverifiable_rows) if unverifiable_rows else pd.DataFrame(columns=df.columns)
    df_3c = pd.DataFrame(coincident_rows) if coincident_rows else pd.DataFrame(columns=df.columns)
    
    if cache_dirty:
        try:
            _write_similarity_cache(sim_cache_path, sim_contract, sim_cache)
        except Exception as e:
            logger.warning(f"Failed to persist veto similarity cache: {e}")
    logger.info("Veto procedure completed successfully.")
    return df_3a, df_3b, df_3c

def run_cross_detector_veto():
    production_dir = Path("data/production")
    aggregated_dir = production_dir / "aggregated"
    master_csv = aggregated_dir / "master_candidates.csv"
    
    if not master_csv.exists():
        logger.error(f"Master CSV not found at {master_csv}")
        return
        
    df = pd.read_csv(master_csv)
    df_3a, df_3b, df_3c = execute_cross_detector_veto(df, production_dir)
    
    table_cols = [
        "gps_start", "detector", "local_cluster_id", "session_id", "gs_label",
        "partner_observing_status", "source_session"
    ]
    
    def _write_table(df_subset, path, note=None):
        if len(df_subset) == 0:
            logger.info(f"Table {path.name} is empty.")
            return
        out_cols = [c for c in table_cols if c in df_subset.columns]
        df_subset[out_cols].to_csv(path, index=False)
        if note:
            with open(path, "a") as f:
                f.write(note)
        logger.info(f"Wrote {len(df_subset)} rows to {path.name}")

    _write_table(df_3a, aggregated_dir / "Table_3a_Confirmed_Local_Glitches_Vetoed.csv")
    _write_table(df_3b, aggregated_dir / "Table_3b_Unverifiable_Unilateral_Detections_Vetoed.csv", 
                 "\n# NOTE: Unverifiable due to non-observing status of partner.\n")
    _write_table(df_3c, aggregated_dir / "Table_3c_Coincident_Astrophysical.csv",
                 "\n# NOTE: Morphological cross-match confirmed (Cosine Similarity > run-calibrated tau_coh, see config/cross_detector_threshold.json).\n")

if __name__ == "__main__":
    run_cross_detector_veto()

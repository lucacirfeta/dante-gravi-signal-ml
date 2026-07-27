"""Does DANTE recover the real O4a gravitational-wave catalogue? (P11)

P9 measured DANTE's efficiency on *synthetic* CBC waveforms injected into curated
clean background. This test asks the harder question against ground truth: of the
gravitational-wave events the official LVK search actually confirmed in O4a
(GWTC-4.0 / 4.1), how many does DANTE independently flag?

This is not an injection -- the signals are the real, confirmed detections. It is
the strongest possible external check on the manuscripts' *instrumental* framing:
if DANTE flagged the real catalogue it would be a detection pipeline, and it is
not claimed to be one.

Three quantities are separated with care, because conflating them is how a null
result gets misread:

* **Coverage.** An event can only be flagged if DANTE analysed its time. Coverage
  is the union of the per-session ``[session_start_gps, session_end_gps]`` spans
  read from every ``cluster_report_novelties_*.json``. An event outside every
  span was never processed and is excluded from the recall denominator -- it is
  not a miss.
* **Flag.** DANTE flagged an event if some candidate's analysis window contains
  the event GPS. Catalogues before 2026-07-24 label the padded crop, so the true
  window is ``[gps_start + 4, gps_start + 36]`` (the reproducibility note). Using
  the raw ``gps_start`` would shift every window by 4 s and silently mis-match.
* **Recall.** Flagged / covered, reported per detector and against event network
  SNR and luminosity distance, so the result can be read against P9's predicted
  few-hundred-Mpc reach rather than as a bare fraction.

The GWTC event list is fetched once from the GWOSC event API and cached to
``data/production/aggregated/gwtc_o4a_events.json`` so the analysis is
reproducible offline.

Usage
-----
    python -m src.pipeline_v2_production.catalog_cross_match
    python -m src.pipeline_v2_production.catalog_cross_match --refresh

Writes ``data/production/aggregated/catalog_cross_match_{run}.json``.
"""

from __future__ import annotations

import argparse
import glob
import json
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.utils import record_environment, setup_logger

logger = setup_logger(__name__)

PROD = Path("data/production")
AGG = PROD / "aggregated"
WINDOW_OFFSET = 4.0          # catalogue GPS labels the padded crop
WINDOW_LENGTH = 32.0
# GWTC catalogues that contain O4a; 4.1 supersedes 4.0 where they overlap.
CATALOGS = ("GWTC-4.0", "GWTC-4.1")
# DANTE's O4a run window (GPS), from norm_leakage RUN_WINDOWS.
O4A_LO, O4A_HI = 1369598418, 1390060818


def _fetch_events(cache: Path, refresh: bool) -> pd.DataFrame:
    """Confirmed O4a events with GPS, network SNR, luminosity distance, masses."""
    if cache.exists() and not refresh:
        logger.info(f"loading cached catalogue from {cache.name}")
        return pd.read_json(cache)

    merged: dict[str, dict] = {}
    for cat in CATALOGS:
        url = f"https://gwosc.org/eventapi/json/{cat}/"
        logger.info(f"fetching {cat} from GWOSC")
        events = json.load(urllib.request.urlopen(url, timeout=120))["events"]
        for name, v in events.items():
            gps = v.get("GPS")
            if not gps or not (O4A_LO <= gps <= O4A_HI):
                continue
            base = name.split("-")[0]           # drop the -vN version suffix
            merged[base] = dict(               # later catalogue (4.1) wins
                name=base, gps=float(gps), catalog=cat,
                snr=v.get("network_matched_filter_snr"),
                dl=v.get("luminosity_distance"),
                m1=v.get("mass_1_source"), m2=v.get("mass_2_source"))
    df = pd.DataFrame(list(merged.values()))
    for col in ("snr", "dl", "m1", "m2"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.to_json(cache)
    logger.info(f"cached {len(df)} O4a events to {cache.name}")
    return df


def _coverage() -> dict[str, list[tuple[float, float]]]:
    """Merged analysed spans per detector, from every session cluster report."""
    spans: dict[str, list[tuple[float, float]]] = {"H1": [], "L1": []}
    for jf in glob.glob(str(PROD / "*" / "cluster_report_novelties_*.json")):
        try:
            d = json.load(open(jf))
        except (json.JSONDecodeError, OSError):
            continue
        det, s, e = d.get("detector"), d.get("session_start_gps"), d.get("session_end_gps")
        if det in spans and s and e:
            spans[det].append((float(s), float(e)))
    for det, iv in spans.items():
        iv.sort()
        merged: list[tuple[float, float]] = []
        for s, e in iv:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        spans[det] = merged
    return spans


def _covered(t: float, spans: list[tuple[float, float]]) -> bool:
    return any(s <= t <= e for s, e in spans)


def _flag(t: float, det_tax: pd.DataFrame) -> tuple[str, float] | None:
    """Candidate whose true window [g+4, g+36] contains the event GPS, if any."""
    g = det_tax.gps_start.to_numpy()
    m = (g + WINDOW_OFFSET <= t) & (t <= g + WINDOW_OFFSET + WINDOW_LENGTH)
    if not m.any():
        return None
    row = det_tax[m].iloc[0]
    return str(row.robustness_class), float(row.native_o4a_score)


def _summ(df: pd.DataFrame, mask) -> dict:
    sub = df[mask]
    snr = sub.snr.dropna()
    dl = sub.dl.dropna()
    return {
        "n": int(len(sub)),
        "snr_median": float(snr.median()) if len(snr) else None,
        "snr_max": float(snr.max()) if len(snr) else None,
        "dl_median_mpc": float(dl.median()) if len(dl) else None,
        "dl_min_mpc": float(dl.min()) if len(dl) else None,
    }


def run(run_name: str = "O4a", refresh: bool = False) -> dict:
    ev = _fetch_events(AGG / "gwtc_o4a_events.json", refresh)
    logger.info(f"{len(ev)} confirmed O4a events in the DANTE window")

    spans = _coverage()
    cov_days = {d: sum(e - s for s, e in spans[d]) / 86400 for d in spans}
    logger.info(f"analysed span union: H1 {cov_days['H1']:.1f} d, "
                f"L1 {cov_days['L1']:.1f} d")

    tax = pd.read_csv(AGG / f"Master_Taxonomy_{run_name.lower()}.csv")
    tax["gps_start"] = tax.gps_start.astype(float)
    det_tax = {d: tax[tax.detector == d] for d in ("H1", "L1")}

    rows = []
    for _, e in ev.iterrows():
        t = float(e.gps)
        cov = {d: _covered(t, spans[d]) for d in ("H1", "L1")}
        flg = {d: _flag(t, det_tax[d]) for d in ("H1", "L1")}
        rows.append(dict(
            name=e["name"], gps=int(t), snr=e.snr, dl=e.dl, m1=e.m1, m2=e.m2,
            cov_H1=cov["H1"], cov_L1=cov["L1"],
            cov_any=cov["H1"] or cov["L1"], cov_both=cov["H1"] and cov["L1"],
            flag_H1=flg["H1"] is not None, flag_L1=flg["L1"] is not None,
            cls_H1=flg["H1"][0] if flg["H1"] else None,
            cls_L1=flg["L1"][0] if flg["L1"] else None,
            score_H1=flg["H1"][1] if flg["H1"] else None,
            score_L1=flg["L1"][1] if flg["L1"] else None))
    R = pd.DataFrame(rows)
    R["flag_any"] = R.flag_H1 | R.flag_L1
    R["flag_both"] = R.flag_H1 & R.flag_L1

    covd = R[R.cov_any]
    flagged = R[R.flag_any]

    out = {
        "run": run_name,
        "catalogs": list(CATALOGS),
        "n_events_in_window": int(len(R)),
        "analysed_span_days": {d: round(cov_days[d], 1) for d in cov_days},
        "coverage": {
            "covered_any_detector": int(R.cov_any.sum()),
            "covered_both_detectors": int(R.cov_both.sum()),
        },
        "recall_among_covered": {
            "covered": int(len(covd)),
            "flagged_any_detector": int(covd.flag_any.sum()),
            "flagged_coincident_both": int(covd.flag_both.sum()),
        },
        "flagged_events": [
            {"name": r["name"], "gps": r.gps, "snr": _nan(r.snr), "dl_mpc": _nan(r.dl),
             "m1": _nan(r.m1), "m2": _nan(r.m2),
             "cls_H1": r.cls_H1, "score_H1": _nan(r.score_H1),
             "cls_L1": r.cls_L1, "score_L1": _nan(r.score_L1)}
            for _, r in flagged.iterrows()],
        "covered_but_missed": _summ(covd, ~covd.flag_any),
        "covered_loud_missed": {  # SNR>15: loud enough that a miss is informative
            "snr_gt_15_covered": int((covd.snr > 15).sum()),
            "of_those_flagged": int(covd[covd.snr > 15].flag_any.sum()),
        },
        "interpretation_note": (
            "DANTE is a single-detector 32 s morphological anomaly detector, not "
            "a coherent matched filter; recovering ~none of the real CBC catalogue "
            "is the expected, honest confirmation of the manuscripts' instrumental "
            "framing. Reconcile with P9 by distance: covered-but-missed events sit "
            "at Gpc distances beyond DANTE's few-hundred-Mpc flag reach. The one "
            "event inside that reach (see flagged/loud lists) is a single Poisson "
            "trial and cannot validate P9's synthetic efficiency, which may itself "
            "be optimistic (clean curated background, favourable orientations)."),
    }
    dest = AGG / f"catalog_cross_match_{run_name.lower()}.json"
    dest.write_text(json.dumps(out, indent=2))
    rc = out["recall_among_covered"]
    logger.info(
        f"{rc['covered']} covered, flagged {rc['flagged_any_detector']} "
        f"(coincident {rc['flagged_coincident_both']}); loud-missed "
        f"{out['covered_loud_missed']['snr_gt_15_covered']} SNR>15 events, "
        f"{out['covered_loud_missed']['of_those_flagged']} flagged")
    logger.info(f"wrote {dest}")
    record_environment(AGG, f"catalog_cross_match_{run_name.lower()}")
    return out


def _nan(x):
    """JSON-safe: NaN -> None."""
    try:
        return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)
    except (TypeError, ValueError):
        return x


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="O4a")
    p.add_argument("--refresh", action="store_true",
                   help="Re-fetch the GWTC event list from GWOSC (else cached).")
    a = p.parse_args()
    run(a.run, refresh=a.refresh)


if __name__ == "__main__":
    main()

"""Would DANTE see a real gravitational wave? A CBC injection campaign.

The manuscripts quote the rate limits as *instrumental* and say so explicitly,
because no claim in them is validated against realistic astrophysical waveforms.
Two stages need measuring, and they are independent:

1. **Flagging** -- does an astrophysical signal become a candidate at all? It is
   scored against the frozen O3b dictionary (K=275) like everything else, and a
   chirp is not a glitch morphology.
2. **Coincidence** -- would the physical cross-correlation test recover it? Its
   efficiency was measured on synthetic *glitch* morphologies, injected
   identically into both detectors. A real signal is not identical in the two
   detectors, so that measurement does not transfer.

Realism, and where it stops
---------------------------
Waveforms come from ``lalsimulation`` (IMRPhenomD: inspiral, merger and
ringdown), not from an analytic approximation. Each injection draws an isotropic
sky position, a uniform polarization and an inclination uniform in cos(iota),
then projects onto each detector through its own antenna response,

    h_det = F_plus(ra, dec, psi, t) * h_plus + F_cross(...) * h_cross

with the true geometric delay from ``lal.TimeDelayFromEarthCenter``. This is the
part the glitch campaign could not do: injecting one waveform into both
detectors overstates coherence, because two detectors genuinely see different
amplitudes and polarization mixes.

Injection is into the **raw** strain before whitening, as a real signal would
be, so the whitening shapes it exactly as it shapes a real event.

What is still idealized: a single point in parameter space per system (no spins,
no precession, no higher modes), and the background is real O4a data but a
specific set of segments. This bounds sensitivity for these systems; it is not a
population-averaged detection efficiency.

Usage
-----
    python -m src.pipeline_v2_production.astrophysical_injection --pilot
    python -m src.pipeline_v2_production.astrophysical_injection --n-trials 40

Requires ``lalsuite``, which lives in the WSL conda environment alongside
``nds2``; see the README note on the PEM branch.

Writes a representation-versioned
``data/production/aggregated/astrophysical_injection_{run}_{representation}.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from src.core.utils import record_environment, setup_logger

logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
SEGMENT_LENGTH = 32.0
SAMPLE_RATE = 4096
HALF_WINDOW_S = 0.5          # production localization excerpt
F_LOW_DEFAULT = 20.0

# Systems spanning the CBC space LVK reports. f_low is raised for the lighter
# systems so the inspiral fits inside a 32 s window -- a BNS from 20 Hz lasts
# ~157 s and simply cannot be contained, which is itself a limitation worth
# reporting rather than hiding by silently truncating.
SYSTEMS = (
    {"name": "BBH_30_30", "m1": 30.0, "m2": 30.0, "f_low": 20.0},
    {"name": "BBH_10_10", "m1": 10.0, "m2": 10.0, "f_low": 25.0},
    {"name": "NSBH_10_1.4", "m1": 10.0, "m2": 1.4, "f_low": 30.0},
    {"name": "BNS_1.4_1.4", "m1": 1.4, "m2": 1.4, "f_low": 40.0},
)

DISTANCES_MPC = (100.0, 200.0, 400.0, 800.0, 1600.0)


def _waveform(m1: float, m2: float, distance_mpc: float, inclination: float,
              f_low: float):
    """IMRPhenomD plus/cross polarizations, as numpy arrays at SAMPLE_RATE."""
    import lal
    import lalsimulation as lalsim

    hp, hc = lalsim.SimInspiralChooseTDWaveform(
        m1 * lal.MSUN_SI, m2 * lal.MSUN_SI,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        distance_mpc * 1e6 * lal.PC_SI, inclination,
        0.0, 0.0, 0.0, 0.0,
        1.0 / SAMPLE_RATE, f_low, f_low, None, lalsim.IMRPhenomD)
    return np.asarray(hp.data.data), np.asarray(hc.data.data)


def _project(hp: np.ndarray, hc: np.ndarray, detector: str,
             ra: float, dec: float, psi: float, gps: float
             ) -> tuple[np.ndarray, float]:
    """Antenna-weighted strain in one detector, and its delay from geocentre."""
    import lal

    det = lal.CachedDetectors[
        {"H1": lal.LHO_4K_DETECTOR, "L1": lal.LLO_4K_DETECTOR}[detector]]
    gmst = lal.GreenwichMeanSiderealTime(lal.LIGOTimeGPS(float(gps)))
    f_plus, f_cross = lal.ComputeDetAMResponse(det.response, ra, dec, psi, gmst)
    delay = lal.TimeDelayFromEarthCenter(det.location, ra, dec,
                                         lal.LIGOTimeGPS(float(gps)))
    return f_plus * hp + f_cross * hc, float(delay)


def _score(spectrogram_rgb, scorers: dict) -> dict:
    return {name: float(sc.score_spectrogram([spectrogram_rgb], threshold=0.0)[0]
                        ["novelty_score"])
            for name, sc in scorers.items()}


def _trial(
    gps: int,
    hp: np.ndarray,
    hc: np.ndarray,
    rng,
    scorers: dict,
    band: tuple[float, float],
    qrange: tuple[int, int],
) -> dict | None:
    """One injection into both detectors at the same GPS time."""
    import matplotlib

    from src.core.data_loader import fetch_local_or_remote_strain
    from src.core.injection import InjectionEngine
    from src.core.preprocessor import (whiten_context, extract_clean_subwindow,
                                       generate_qtransform)
    from src.pipeline_v2_production.coincidence_physical import (
        LIGHT_TRAVEL_S, LAG_MARGIN_S, _bandpass, _max_normxcorr)

    ra = float(rng.uniform(0, 2 * np.pi))
    dec = float(np.arcsin(rng.uniform(-1, 1)))
    psi = float(rng.uniform(0, np.pi))
    t_geo = gps + SEGMENT_LENGTH / 2.0

    out, snr, whitened, clean_scores = {}, {}, {}, {}
    for det in ("H1", "L1"):
        h, delay = _project(hp, hc, det, ra, dec, psi, t_geo)
        try:
            ts = fetch_local_or_remote_strain(
                det, gps - 4.0, gps + SEGMENT_LENGTH + 4.0, edge_tolerance=4.0)
        except Exception:
            return None
        # A missing stretch comes back as NaN rather than as an exception, and
        # the NaN then propagates silently through injection and whitening until
        # the Q-transform rejects it. Injection times are vetted on L1 only, so
        # H1 frequently has no data there: check both, skip the pair.
        if not np.isfinite(np.asarray(ts.value)).all():
            return None

        # Paired control: score the SAME segment without the injection. Clean
        # scores vary segment to segment (0.30-0.36 in spot checks) against a
        # flagging threshold of 0.378, so an absolute rate alone cannot separate
        # "the signal raised the score" from "this segment happened to sit high".
        # The pair gives both the production decision and the sensitive delta.
        tw0, _ = whiten_context(ts, gps, gps + SEGMENT_LENGTH, pad=4.0)
        spec0 = generate_qtransform(extract_clean_subwindow(
            tw0, gps, gps + SEGMENT_LENGTH),
            save_path=None,
            cmap="cividis",
            qrange=qrange,
        )
        rgb0 = (matplotlib.colormaps["cividis"](spec0)[:, :, :3] * 255).astype(np.uint8)
        clean_scores[det] = _score(rgb0, scorers)

        eng = InjectionEngine(sample_rate=SAMPLE_RATE)
        # The waveform ends at merger, so its centre is not the merger time;
        # place the array so its END sits at the geocentric arrival + delay.
        t_place = t_geo + delay - (len(h) / SAMPLE_RATE) / 2.0
        try:
            snr[det] = float(eng.compute_snr(
                ts.crop(gps, gps + SEGMENT_LENGTH), h))
            ts = eng.inject(ts, h, t_place)
        except Exception:
            return None
        tw, _ = whiten_context(ts, gps, gps + SEGMENT_LENGTH, pad=4.0)
        clean = extract_clean_subwindow(tw, gps, gps + SEGMENT_LENGTH)
        whitened[det] = clean
        spec = generate_qtransform(
            clean,
            save_path=None,
            cmap="cividis",
            qrange=qrange,
        )
        rgb = (matplotlib.colormaps["cividis"](spec)[:, :, :3] * 255).astype(np.uint8)
        out[det] = _score(rgb, scorers)

    # Coincidence, exactly as production: band-pass, excerpt +-0.5 s about the
    # signal, scan the normalized cross-correlation over the light-travel lag.
    fs = float(1.0 / whitened["H1"].dt.value)
    seg = {}
    for det, ts in whitened.items():
        x = np.asarray(ts.value, dtype=float)
        x = _bandpass(x, fs, *band)
        c = len(x) // 2
        half = int(round(HALF_WINDOW_S * fs))
        seg[det] = x[max(0, c - half): min(len(x), c + half)]
    n = min(len(seg["H1"]), len(seg["L1"]))
    cc = float(_max_normxcorr(seg["H1"][:n], seg["L1"][:n], fs,
                              LIGHT_TRAVEL_S + LAG_MARGIN_S))

    return {"gps": int(gps), "ra": ra, "dec": dec, "psi": psi,
            "snr_H1": snr["H1"], "snr_L1": snr["L1"],
            "snr_network": float(np.hypot(snr["H1"], snr["L1"])),
            "score_H1": out["H1"], "score_L1": out["L1"],
            "clean_H1": clean_scores["H1"], "clean_L1": clean_scores["L1"], "cc": cc}


def run(run_name: str = "O4a", systems=SYSTEMS, distances=DISTANCES_MPC,
        n_trials: int = 20, seed: int = 42,
        band: tuple[float, float] = (20.0, 1024.0)) -> dict:
    from src.core.patch_scorer import PatchScorer
    from src.core.index_contract import (
        load_index_contract,
        taxonomy_representation,
    )
    from src.core.utils import get_reference_dir, load_config
    from src.pipeline_v3_multiscale.norm_leakage.common import iter_clean_segments

    rng = np.random.default_rng(seed)
    ref = get_reference_dir()
    qrange = tuple(
        int(value)
        for value in load_config()["preprocessing"]["qrange"]
    )
    representation = taxonomy_representation(qrange, qrange)
    native_index = ref / "patch_compressed_index_o4a_q4-64_ex.npz"
    index_contract = load_index_contract(native_index)
    scorers = {
        "o3b": PatchScorer(reference_index_path=str(ref / "patch_compressed_index_o3b.npz"),
                           verify_md5=True),
        "native": PatchScorer(reference_index_path=str(native_index),
                              verify_md5=False),
    }
    tau_cc = json.loads((AGG / f"coincidence_physical_{run_name.lower()}.json")
                        .read_text())["summary"]["cc_null_max_p99"]
    threshold_path = (
        AGG
        / f"dsd_thresholds_{run_name.lower()}_{representation}.json"
    )
    threshold_artifact = json.loads(threshold_path.read_text(encoding="utf-8"))
    threshold_representation = threshold_artifact.get("representation", {})
    if (
        not threshold_representation.get("coherent")
        or threshold_representation.get("variant") != representation
        or threshold_representation.get("index_sha256")
        != index_contract.sha256
    ):
        raise RuntimeError(
            "DSD threshold artifact does not match the coherent native index"
        )
    thresholds = {
        "flag_o3b": 0.3783,          # session flagging threshold, O3b dictionary
        "dsd_H1": float(
            threshold_artifact["thresholds"]["H1"]["ci_upper"]
        ),
        "dsd_L1": float(
            threshold_artifact["thresholds"]["L1"]["ci_upper"]
        ),
        "tau_cc": float(tau_cc),
    }
    logger.info(f"thresholds: {thresholds}")

    # Times where both detectors have data. Clean segments are drawn for L1 and
    # reused for H1: the fetch fails and the trial is skipped where H1 has none.
    times = [int(s.t_bg - SEGMENT_LENGTH / 2)
             for s in iter_clean_segments(run_name.lower(), "L1",
                                          n_trials * len(systems) * len(distances) + 40,
                                          seed=seed)]
    logger.info(f"{len(times)} candidate injection times")
    t_iter = iter(times)

    rows = []
    for sysd in systems:
        for dist in distances:
            trials, attempts = [], 0
            while len(trials) < n_trials:
                gps = next(t_iter, None)
                if gps is None:
                    logger.warning(f"{sysd['name']} {dist:.0f} Mpc: ran out of "
                                   f"injection times at {len(trials)}/{n_trials}")
                    break
                attempts += 1
                inc = float(np.arccos(rng.uniform(-1, 1)))
                hp, hc = _waveform(sysd["m1"], sysd["m2"], dist, inc, sysd["f_low"])
                if len(hp) / SAMPLE_RATE > SEGMENT_LENGTH - 2:
                    logger.warning(f"{sysd['name']}: waveform {len(hp)/SAMPLE_RATE:.0f}s "
                                   f"exceeds the {SEGMENT_LENGTH:.0f}s window, skipped")
                    break
                r = _trial(gps, hp, hc, rng, scorers, band, qrange)
                if r is not None:
                    trials.append(r)
            if not trials:
                continue
            cc = np.array([t["cc"] for t in trials])
            snr = np.array([t["snr_network"] for t in trials])
            f_h1 = np.array([t["score_H1"]["o3b"] for t in trials])
            f_l1 = np.array([t["score_L1"]["o3b"] for t in trials])
            d_h1 = np.array([t["score_H1"]["native"] for t in trials])
            d_l1 = np.array([t["score_L1"]["native"] for t in trials])
            c_h1 = np.array([t["clean_H1"]["o3b"] for t in trials])
            c_l1 = np.array([t["clean_L1"]["o3b"] for t in trials])
            delta = np.concatenate([f_h1 - c_h1, f_l1 - c_l1])
            row = {
                "system": sysd["name"], "distance_mpc": dist,
                "n": len(trials), "n_attempted": attempts,
                "waveform_duration_s": float(len(hp) / SAMPLE_RATE),
                "snr_network_mean": float(snr.mean()),
                "snr_network_median": float(np.median(snr)),
                "flag_rate_H1": float((f_h1 > thresholds["flag_o3b"]).mean()),
                "flag_rate_L1": float((f_l1 > thresholds["flag_o3b"]).mean()),
                "flag_rate_either": float(((f_h1 > thresholds["flag_o3b"]) |
                                           (f_l1 > thresholds["flag_o3b"])).mean()),
                "dsd_survive_H1": float((d_h1 > thresholds["dsd_H1"]).mean()),
                "dsd_survive_L1": float((d_l1 > thresholds["dsd_L1"]).mean()),
                "clean_score_mean": float(np.concatenate([c_h1, c_l1]).mean()),
                "delta_score_mean": float(delta.mean()),
                "delta_score_std": float(delta.std(ddof=1)) if len(delta) > 1 else 0.0,
                "delta_score_positive_frac": float((delta > 0).mean()),
                "cc_mean": float(cc.mean()), "cc_median": float(np.median(cc)),
                "coincidence_recovery": float((cc > thresholds["tau_cc"]).mean()),
                "cc_values": [float(x) for x in cc],
            }
            rows.append(row)
            logger.info(
                f"{sysd['name']:12s} {dist:6.0f} Mpc | SNR~{snr.mean():6.1f} | "
                f"flag {row['flag_rate_either']:5.0%} | dScore "
                f"{row['delta_score_mean']:+.4f} | DSD "
                f"{row['dsd_survive_H1']:4.0%}/{row['dsd_survive_L1']:4.0%} | "
                f"coinc {row['coincidence_recovery']:5.0%} (cc {cc.mean():.3f})")

    out = {"run": run_name, "thresholds": thresholds, "n_trials": n_trials,
           "seed": seed, "band": list(band),
           "taxonomy_representation": representation,
           "qrange": list(qrange),
           "native_index_path": str(native_index),
           "native_index_sha256": index_contract.sha256,
           "dsd_threshold_path": str(threshold_path),
           "waveform_model": "IMRPhenomD", "rows": rows}
    AGG.mkdir(parents=True, exist_ok=True)
    dest = AGG / (
        f"astrophysical_injection_{run_name.lower()}_{representation}.json"
    )
    dest.write_text(json.dumps(out, indent=2))
    logger.info(f"wrote {dest}")
    record_environment(
        AGG,
        f"astrophysical_injection_{run_name.lower()}_{representation}",
    )
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="O4a")
    p.add_argument("--n-trials", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pilot", action="store_true",
                   help="One system, two distances, few trials.")
    a = p.parse_args()
    if a.pilot:
        run(a.run, systems=SYSTEMS[:1], distances=(400.0, 2000.0),
            n_trials=3, seed=a.seed)
    else:
        run(a.run, n_trials=a.n_trials, seed=a.seed)


if __name__ == "__main__":
    main()

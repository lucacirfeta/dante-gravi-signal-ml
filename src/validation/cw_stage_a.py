"""Isolated, descriptive synthetic CW probes; never a production method.

All measured quantities and grids come from the approved versioned contract.
The Q-transform is invoked by the inherited generate_qtransform itself; a
TimeSeries subclass observes its return, without a second scientific algorithm.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
import os
import platform
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from multiprocessing import get_context
from pathlib import Path

import numpy as np
from scipy.integrate import quad
from scipy.signal import periodogram


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, data):
    """Atomic administrative metadata only; scientific arrays are exclusive."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")
    temporary.replace(path)


def load_contract(path):
    c = json.loads(Path(path).read_text(encoding="utf-8"))
    n, p = c["noise"], c["probes"]
    if n["context_seconds"] != n["analysis_seconds"] + 2 * n["pad_seconds"]:
        raise ValueError("incomplete padding geometry")
    if n["synthesis_seconds"] <= n["context_seconds"]:
        raise ValueError("synthesis must exceed extracted context")
    if n["dc_nyquist"] != "zero" or n["generator"] != "PCG64_SeedSequence_children":
        raise ValueError("unsupported synthesis convention")
    if c["diagnostic"]["acceptance_threshold"] is not None:
        raise ValueError("descriptive Stage A has no acceptance threshold")
    if not p["stationary_only"] or c["diagnostic"]["zero_padding"]:
        raise ValueError("unsupported scientific convention")
    if len(task_grid(c)) != c["expected_contexts"]:
        raise ValueError("workload cardinality mismatch")
    return c


def task_grid(c):
    tasks = []
    p = c["probes"]
    for noise in range(c["noise"]["realizations"]):
        tasks.append({"kind": "baseline", "noise": noise, "components": []})
        for pulsar, f in enumerate(p["frequencies_hz"]):
            for dose in p["doses"]:
                for phase in p["phase_radians"]:
                    tasks.append({"kind": "single", "noise": noise, "pulsar": pulsar,
                                  "dose": dose, "phase": phase,
                                  "components": [{"f": f, "dose": dose, "phase": phase}]})
        for pulsar in p["pair_ids"]:
            for separation in p["pair_separations_hz"]:
                center = p["frequencies_hz"][pulsar]
                tasks.append({"kind": "pair", "noise": noise, "pulsar": pulsar,
                              "separation": separation,
                              "components": [{"f": center + sign * separation / 2,
                                              "dose": p["pair_component_dose"],
                                              "phase": p["pair_component_phase"]}
                                             for sign in (-1, 1)]})
    for index, task in enumerate(tasks):
        task["id"] = f"{index:05d}"
    return tasks


def model_psd(frequencies, c):
    import lalsimulation

    model = getattr(lalsimulation, c["noise"]["model"])
    lower = c["noise"]["low_flat_hz"]
    values = np.asarray([model(max(float(f), lower)) for f in np.atleast_1d(frequencies)])
    if not np.isfinite(values).all() or not (values > 0).all():
        raise ValueError("nonpositive or nonfinite design PSD")
    return values


def synthesize(psd, fs, rng):
    """Numpy irfft: interior Re/Im variance N*fs*S_one_sided/4."""
    count = 2 * (len(psd) - 1)
    spectrum = (rng.standard_normal(len(psd)) + 1j * rng.standard_normal(len(psd)))
    spectrum *= np.sqrt(count * fs * psd / 4)
    spectrum[0] = spectrum[-1] = 0
    return np.fft.irfft(spectrum, n=count)


def diagnostic_psd(values, c):
    d = c["diagnostic"]
    return periodogram(values, fs=c["noise"]["sample_rate_hz"], window=d["window"],
                       detrend=d["detrend"], scaling=d["scaling"],
                       return_onesided=d["return_onesided"], nfft=len(values))


def band_power(f, psd, center, width):
    if len(f) < 2 or not np.isfinite(psd).all():
        raise ValueError("invalid spectral profile")
    df = f[1] - f[0]
    left = np.maximum(f - df / 2, f[0])
    right = np.minimum(f + df / 2, f[-1])
    overlap = np.maximum(0, np.minimum(right, center + width / 2)
                         - np.maximum(left, center - width / 2))
    return float(np.sum(psd * overlap))


def noise_band_power(center, c):
    """Quadrature of the known model; scale first to avoid tiny abs units.

    scipy quad defaults apply to a dimensionless integrand; reported error is
    numerical integration error, not a physical uncertainty/acceptance margin.
    """
    scale = float(model_psd([center], c)[0])
    half = c["probes"]["band_hz"] / 2
    value, error = quad(lambda f: float(model_psd([f], c)[0]) / scale,
                        center - half, center + half)
    return value * scale, error * scale


def make_tone(component, c):
    n = c["noise"]
    fs = n["sample_rate_hz"]
    t = np.arange(int(n["context_seconds"] * fs)) / fs - n["pad_seconds"]
    unit = np.sin(2 * np.pi * component["f"] * t + component["phase"])
    start = int(n["pad_seconds"] * fs)
    stop = start + int(n["analysis_seconds"] * fs)
    f, psd = diagnostic_psd(unit[start:stop], c)
    unit_power = band_power(f, psd, component["f"], c["probes"]["band_hz"])
    target, error = noise_band_power(component["f"], c)
    if not np.isfinite(unit_power) or unit_power <= 0:
        raise ValueError("invalid tone dose denominator")
    amplitude = np.sqrt(component["dose"] * target / unit_power)
    return amplitude * unit, {**component, "amplitude": float(amplitude),
                             "model_noise_band_power": target,
                             "quadrature_error": error,
                             "target_line_band_power": component["dose"] * target}


def paired_metrics(base_power, injected_power, dose):
    if not np.isfinite([base_power, injected_power, dose]).all() or base_power <= 0 or dose <= 0:
        raise ValueError("invalid paired denominator or power")
    delta = injected_power - base_power
    excess = delta / base_power
    return {"P_base": base_power, "P_injected": injected_power,
            "delta_P": delta, "E": excess, "G": excess / dose}


def image_difference(base, injected):
    if base.shape != injected.shape or base.dtype != np.uint8 or injected.dtype != np.uint8:
        raise ValueError("RGB geometry/dtype mismatch")
    return float(np.mean(np.abs(injected.astype(np.int16) - base.astype(np.int16))) / 255)


def preprocess(values, c):
    from gwpy.timeseries import TimeSeries
    from matplotlib import colormaps
    from scipy.ndimage import zoom

    from src.core.preprocessor import extract_clean_subwindow, generate_qtransform, whiten_context

    class ObservedTimeSeries(TimeSeries):
        def q_transform(self, *args, **kwargs):
            result = super().q_transform(*args, **kwargs)
            self.observed_q = result
            return result

    n, p = c["noise"], c["preprocessing"]
    fs = n["sample_rate_hz"]
    if len(values) != int(fs * n["context_seconds"]) or not np.isfinite(values).all():
        raise ValueError("invalid synthetic complete context")
    series = TimeSeries(values, sample_rate=fs, t0=-n["pad_seconds"])
    whitened, pad = whiten_context(series, 0, n["analysis_seconds"], pad=n["pad_seconds"])
    if pad["left"] or pad["right"] or float(whitened.sample_rate.value) != fs:
        raise ValueError("padding/rate preservation failed")
    clean = extract_clean_subwindow(whitened, 0, n["analysis_seconds"])
    if float(clean.sample_rate.value) != fs or len(clean) != int(fs * n["analysis_seconds"]):
        raise ValueError("clean rate/length mismatch")
    observed = ObservedTimeSeries(clean.value, sample_rate=fs, t0=0)
    scalar = generate_qtransform(observed, qrange=tuple(p["qrange"]), frange=tuple(p["frange"]),
                                 output_size=tuple(p["output_size"]), cmap=p["colormap"])
    q = observed.observed_q
    qvalues = np.asarray(q.value, dtype=np.float64)
    qf, qt = np.asarray(q.frequencies.value), np.asarray(q.times.value)
    if qvalues.shape != (len(qt), len(qf)):
        raise ValueError("unexpected native Q axis layout")
    rgb = (colormaps[p["colormap"]](scalar)[:, :, :3] * 255).astype(np.uint8)
    f, psd = diagnostic_psd(clean.value, c)
    arrays = {"spectral_f_hz": f, "spectral_psd": psd, "rgb": rgb, "scalar_q": scalar,
              "native_q_frequency_hz": qf, "native_q_time_s": qt,
              "native_q_mean_frequency_profile": qvalues.mean(axis=0),
              "native_q_max_frequency_profile": qvalues.max(axis=0),
              "resized_q_frequency_hz": zoom(qf, scalar.shape[1] / len(qf), order=1),
              "resized_q_time_s": zoom(qt, scalar.shape[0] / len(qt), order=1),
              "resized_q_mean_frequency_profile": scalar.mean(axis=0),
              "resized_q_max_frequency_profile": scalar.max(axis=0)}
    if any(not np.isfinite(value).all() for value in arrays.values()):
        raise ValueError("nonfinite preprocessing diagnostic")
    return arrays


def audit(c, root):
    from gwpy.timeseries import TimeSeries
    from gwpy.signal import filter_design

    from src.core.utils import load_config

    inherited = load_config()["preprocessing"]
    for key in ("f_low", "f_high", "qrange", "frange", "output_size", "colormap"):
        if inherited[key] != c["preprocessing"][key]:
            raise ValueError(f"inherited scientific config mismatch: {key}")
    for relative, expected in c["inherited_sha256"].items():
        if sha256(root / relative) != expected:
            raise ValueError(f"source provenance mismatch: {relative}")
    versions = {key: importlib.metadata.version(key) for key in c["runtime_versions"]}
    if versions != c["runtime_versions"]:
        raise ValueError(f"runtime mismatch: {versions}")
    p, n = c["preprocessing"], c["noise"]
    low, high, fs = p["f_low"], p["f_high"], n["sample_rate_hz"]
    # Same inherited formula, for reporting coefficients, never filtering here.
    stops = (max(low * 2 / 3, 0.1), min(high * 1.5, fs / 2 * 0.99))
    zeros, poles, gain = filter_design.bandpass(low, high, fs, fstop=stops)
    def complex_rows(values):
        return [[float(x.real), float(x.imag)] for x in values]
    return {"versions": versions, "python": sys.version, "platform": platform.platform(),
            "whiten_signature": str(inspect.signature(TimeSeries.whiten)),
            "bandpass_signature": str(inspect.signature(TimeSeries.bandpass)),
            "filter_design_signature": str(inspect.signature(filter_design.bandpass)),
            "filter_z": complex_rows(zeros), "filter_p": complex_rows(poles),
            "filter_gain": float(gain), "filter_order": len(poles), "stop_hz": stops}


def _worker(payload):
    task, config_path, output, noise_hash, baseline_id = payload
    c = load_contract(config_path)
    output = Path(output)
    noise_path = output / "noise" / f"{task['noise']:02d}.npy"
    if sha256(noise_path) != noise_hash:
        raise ValueError("paired noise identity mismatch")
    noise = np.load(noise_path, allow_pickle=False)
    values = noise.copy()
    components = []
    for component in task["components"]:
        tone, metadata = make_tone(component, c)
        values += tone
        components.append(metadata)
    arrays = preprocess(values, c)
    receipt = {**task, "components": components, "noise_sha256": noise_hash,
               "input_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
               "temporal_units": "post_whitening_units_squared_per_Hz",
               "Q_units": "GWpy_median_normalized_energy_then_per_image_minmax",
               "overlapping_pair_bands_independent": False}
    if task["kind"] != "baseline":
        baseline_path = output / "arrays" / f"{baseline_id}.npz"
        with np.load(baseline_path, allow_pickle=False) as base:
            receipt["baseline_id"] = baseline_id
            receipt["baseline_sha256"] = sha256(baseline_path)
            receipt["rgb_difference"] = image_difference(base["rgb"], arrays["rgb"])
            receipt["bands"] = []
            for component in components:
                center, width = component["f"], c["probes"]["band_hz"]
                pb = band_power(base["spectral_f_hz"], base["spectral_psd"], center, width)
                pi = band_power(arrays["spectral_f_hz"], arrays["spectral_psd"], center, width)
                receipt["bands"].append({"center_hz": center, "width_hz": width,
                                         **paired_metrics(pb, pi, component["dose"])})
    path = output / "arrays" / f"{task['id']}.npz"
    with path.open("xb") as stream:
        np.savez(stream, **arrays)
    receipt["arrays_sha256"] = sha256(path)
    write_json(output / "receipts" / f"{task['id']}.json", receipt)
    return task["id"]


def worker_count(c):
    available = next(int(line.split()[1]) * 1024 for line in
                     Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))
    op = c["operations"]
    memory_workers = (available - op["reserve_memory_bytes"]) // op["worker_memory_budget_bytes"]
    if memory_workers < 1:
        raise ValueError("insufficient available memory")
    return min(len(os.sched_getaffinity(0)), memory_workers)


def summarize(receipts):
    groups = {}
    for r in receipts:
        if r["kind"] != "single":
            continue
        key = (r["pulsar"], r["dose"], r["phase"])
        groups.setdefault(key, []).append(r)
    rows = []
    for (pulsar, dose, phase), group in sorted(groups.items()):
        row = {"pulsar": pulsar, "dose": dose, "phase": phase, "noises": len(group)}
        for metric in ("P_base", "P_injected", "delta_P", "E", "G", "rgb_difference"):
            values = [r[metric] if metric == "rgb_difference" else r["bands"][0][metric] for r in group]
            row[metric] = {"median": float(np.median(values)), "minimum": float(np.min(values)),
                           "maximum": float(np.max(values))}
        rows.append(row)
    return rows


def verify_artifacts(output, c):
    """Read-only all-artifact integrity/cardinality, not a numerical rerun."""
    output = Path(output)
    tasks = task_grid(c)
    expected = {task["id"] for task in tasks}
    if {p.name for p in (output / "noise").glob("*.npy")} != {
            f"{i:02d}.npy" for i in range(c["noise"]["realizations"])}:
        raise ValueError("noise cardinality mismatch")
    if {p.stem for p in (output / "receipts").glob("*.json")} != expected:
        raise ValueError("receipt cardinality/identity mismatch")
    if {p.stem for p in (output / "arrays").glob("*.npz")} != expected:
        raise ValueError("array cardinality/identity mismatch")
    noises = {i: sha256(output / "noise" / f"{i:02d}.npy") for i in range(c["noise"]["realizations"])}
    baselines = {t["noise"]: t["id"] for t in tasks if t["kind"] == "baseline"}
    receipts = []
    for task in tasks:
        r = json.loads((output / "receipts" / f"{task['id']}.json").read_text())
        if any(r[k] != v for k, v in task.items() if k != "components"):
            raise ValueError("receipt task binding mismatch")
        if len(r["components"]) != len(task["components"]) or any(
                any(actual[k] != value for k, value in expected_component.items())
                for actual, expected_component in zip(r["components"], task["components"], strict=True)):
            raise ValueError("receipt component binding mismatch")
        path = output / "arrays" / f"{task['id']}.npz"
        if sha256(path) != r["arrays_sha256"] or noises[task["noise"]] != r["noise_sha256"]:
            raise ValueError("artifact integrity mismatch")
        with np.load(path, allow_pickle=False) as data:
            if any(not np.isfinite(data[k]).all() for k in data.files):
                raise ValueError("nonfinite retained arrays")
            if data["rgb"].shape != (*c["preprocessing"]["output_size"], 3):
                raise ValueError("RGB geometry mismatch")
            if task["kind"] != "baseline":
                if len(r["bands"]) != len(task["components"]):
                    raise ValueError("component band cardinality mismatch")
                bp = output / "arrays" / f"{baselines[task['noise']]}.npz"
                if r["baseline_id"] != baselines[task["noise"]] or sha256(bp) != r["baseline_sha256"]:
                    raise ValueError("baseline identity mismatch")
                with np.load(bp, allow_pickle=False) as base:
                    if image_difference(base["rgb"], data["rgb"]) != r["rgb_difference"]:
                        raise ValueError("RGB metric mismatch")
                    for component, band in zip(r["components"], r["bands"], strict=True):
                        pb = band_power(base["spectral_f_hz"], base["spectral_psd"],
                                        component["f"], c["probes"]["band_hz"])
                        pi = band_power(data["spectral_f_hz"], data["spectral_psd"],
                                        component["f"], c["probes"]["band_hz"])
                        if any(band[k] != v for k, v in paired_metrics(pb, pi, component["dose"]).items()):
                            raise ValueError("retained spectral metric mismatch")
        receipts.append(r)
    if list(output.rglob("*.tmp")) or (output / "failure.json").exists():
        raise ValueError("incomplete/failure artifacts present")
    return {"status": "PASS_RETAINED_ARTIFACT_INTEGRITY_ONLY", "contexts": len(receipts),
            "independent_noises": len(noises), "summaries": summarize(receipts),
            "numerical_preprocessing_replay": False, "CW_equivalence": False}


def run(config_path, output, expected_config_sha, expected_source_sha):
    root = Path(__file__).resolve().parents[2]
    config_path, output = Path(config_path).resolve(), Path(output).resolve()
    c = load_contract(config_path)
    if sha256(config_path) != expected_config_sha or sha256(Path(__file__)) != expected_source_sha:
        raise ValueError("execution freeze mismatch")
    if sys.platform != "linux" or str(output).startswith("/mnt/"):
        raise ValueError("run requires native Linux filesystem")
    if not output.is_relative_to(Path(c["operations"]["output_root"])):
        raise ValueError("output outside isolated namespace")
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < c["operations"]["minimum_free_disk_bytes"]:
        raise ValueError("insufficient free disk")
    runtime = audit(c, root)
    script_sha = sha256(root / "scripts/run_dante_cw_stage_a.py")
    workers = worker_count(c)
    output.mkdir(exist_ok=False)
    for directory in ("noise", "arrays", "receipts"):
        (output / directory).mkdir()
    lock = output / "controller.lock"
    lock.write_text(str(os.getpid()), encoding="ascii")
    try:
        write_json(output / "freeze.json", {"config_sha256": expected_config_sha,
                   "module_sha256": expected_source_sha, "script_sha256": script_sha,
                   "runtime": runtime, "workers": workers,
                   "started_utc": datetime.now(timezone.utc).isoformat(), "scope": c["scope"]})
        n = c["noise"]
        fs = n["sample_rate_hz"]
        count = int(fs * n["synthesis_seconds"])
        f = np.fft.rfftfreq(count, 1 / fs)
        psd = model_psd(f, c)
        hashes = {}
        seeds = np.random.SeedSequence(n["seed"]).spawn(n["realizations"])
        for i, seed in enumerate(seeds):
            noise = synthesize(psd, fs, np.random.Generator(np.random.PCG64(seed)))
            start = int((n["synthesis_seconds"] - n["context_seconds"]) * fs / 2)
            noise = noise[start:start + int(n["context_seconds"] * fs)]
            path = output / "noise" / f"{i:02d}.npy"
            with path.open("xb") as stream:
                np.save(stream, noise, allow_pickle=False)
            hashes[i] = sha256(path)
        tasks = task_grid(c)
        baselines = {t["noise"]: t["id"] for t in tasks if t["kind"] == "baseline"}
        completed = 0
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
            for baseline_phase in (True, False):
                selected = [t for t in tasks if (t["kind"] == "baseline") == baseline_phase]
                payloads = [(t, str(config_path), str(output), hashes[t["noise"]],
                             baselines[t["noise"]]) for t in selected]
                for identity in pool.map(_worker, payloads, chunksize=1):
                    completed += 1
                    write_json(output / "progress.run.json", {"completed": completed,
                               "expected": len(tasks), "last_id": identity, "workers": workers,
                               "updated_utc": datetime.now(timezone.utc).isoformat()})
        # Repeat cheap source/runtime boundary audit, not scientific recomputation.
        audit(c, root)
        if sha256(config_path) != expected_config_sha or sha256(Path(__file__)) != expected_source_sha:
            raise ValueError("final execution freeze mismatch")
        if sha256(root / "scripts/run_dante_cw_stage_a.py") != script_sha:
            raise ValueError("final script freeze mismatch")
        verification = verify_artifacts(output, c)
        write_json(output / "verification.json", verification)
        write_json(output / "summary.json", {"status": "COMPLETE_DESCRIPTIVE_SYNTHETIC_STAGE_A_ONLY",
                   "contexts": completed, "independent_noises": n["realizations"],
                   "verification_sha256": sha256(output / "verification.json"),
                   "ended_utc": datetime.now(timezone.utc).isoformat(), "scope": c["scope"],
                   "O4b_ready": False, "real_CW_validated": False})
    except BaseException as error:
        write_json(output / "failure.json", {"type": type(error).__name__, "message": str(error),
                   "utc": datetime.now(timezone.utc).isoformat()})
        raise
    finally:
        lock.unlink()
    return output

"""One-event five-channel PEM measurement for the paired diagnostic follow-up.

Both run adapters supply verified event strain; the historical coherence and
window-bootstrap null functions remain the sole measurement implementations.
This module does not select targets or turn a diagnostic into significance.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_o4a_common_pem_aux_reader import VerifiedAuxiliaryReader
from src.dante_light.o3a_o4a_common_pem_span_reader import VerifiedSpanReader
from src.pipeline_v2_production import pem_null_calibration as null_core
from src.pipeline_v2_production.pem_coherence_analysis import (
    calculate_coherence_and_plot,
    fetch_auxiliary_data,
)
from src.pipeline_v2_production.pem_null_calibration import (
    calibrate_event,
    tier_verdict,
)


def _require_complete_series(
    series: Any, *, start: int, end: int, minimum_sample_rate: float, label: str
) -> None:
    """Reject partial, low-bandwidth or nonfinite NDS/GWOSC responses."""
    try:
        t0 = float(series.t0.value)
        t1 = t0 + float(series.duration.value)
        sample_rate = float(series.sample_rate.value)
        values = np.asarray(series.value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ContractError(
            f"common PEM {label} has no complete time-series metadata"
        ) from exc
    if (
        not np.isfinite((t0, t1, sample_rate)).all()
        or t0 != start
        or t1 != end
        or sample_rate <= 0
        or sample_rate < minimum_sample_rate
        or values.ndim != 1
        or values.size != (end - start) * sample_rate
        or not np.isfinite(values).all()
    ):
        raise ContractError(f"common PEM {label} has incomplete or invalid coverage")


def measure_event(
    target: Mapping[str, Any],
    *,
    run: str,
    comparison: Mapping[str, Any],
    execution: Mapping[str, Any],
    run_dir: Path,
    auxiliary_run_dir: Path,
    background_span_run_dir: Path,
    background_acquisition_run_dir: Path,
    candidate_exclusion_gps: Sequence[float],
    strain_reader: Callable[[], tuple[Any, str]],
) -> dict[str, Any]:
    """Use only sealed local auxiliary and strain-background input."""
    try:
        detector = str(target["detector"])
        gps = float(target["gps_start"])
        channels = comparison["method"]["channels"][detector]
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("common PEM target binding invalid") from exc
    if not np.isfinite(gps) or gps != int(gps):
        raise ContractError("common PEM target GPS is not a finite integer")
    auxiliary_reader = VerifiedAuxiliaryReader(
        auxiliary_run_dir,
        run=run,
        detector=detector,
        target_gps=int(gps),
        channels=channels,
    )
    background_reader = VerifiedSpanReader(
        background_span_run_dir,
        background_acquisition_run_dir,
        run=run,
        detector=detector,
        target_gps=int(gps),
    )
    return _measure_event(
        target,
        run=run,
        comparison=comparison,
        execution=execution,
        run_dir=run_dir,
        candidate_exclusion_gps=candidate_exclusion_gps,
        strain_reader=strain_reader,
        background_strain_reader=background_reader,
        auxiliary_fetch=auxiliary_reader.fetch,
    )


def _measure_event(
    target: Mapping[str, Any],
    *,
    run: str,
    comparison: Mapping[str, Any],
    execution: Mapping[str, Any],
    run_dir: Path,
    candidate_exclusion_gps: Sequence[float],
    strain_reader: Callable[[], tuple[Any, str]],
    background_strain_reader: Callable[[str, int, int], Any],
    auxiliary_fetch: Callable[..., Any],
) -> dict[str, Any]:
    """Measure one target, failing closed unless all five channels enter the null."""
    if run not in ("O3a", "O4a"):
        raise ContractError("common PEM run is not O3a or O4a")
    detector = str(target["detector"])
    if detector not in ("H1", "L1"):
        raise ContractError("common PEM detector is not H1 or L1")
    gps = float(target["gps_start"])
    if not np.isfinite(gps) or gps != int(gps):
        raise ContractError("common PEM target GPS is not a finite integer")
    method = comparison["method"]
    measurement = method["measurement"]
    channels = method["channels"][detector]
    if (
        len(channels) != 5
        or len(set(channels)) != 5
        or any(not channel.startswith(f"{detector}:") for channel in channels)
    ):
        raise ContractError("common PEM exact detector-channel set is invalid")
    exclusion = np.asarray(candidate_exclusion_gps, dtype=np.float64)
    exclusion_spec = comparison["runs"][run]["candidate_exclusion"]
    if (
        exclusion.ndim != 1
        or not np.isfinite(exclusion).all()
        or len(exclusion) != exclusion_spec["expected_count"]
        or canonical_json_sha256(exclusion.tolist()) != exclusion_spec["digest"]
    ):
        raise ContractError("common PEM full candidate-exclusion ledger changed")

    strain, central_sha = strain_reader()
    start = int(gps)
    end = start + int(measurement["event_window_s"])
    minimum_sample_rate = 2 * float(measurement["frequency_band_hz"][1])
    _require_complete_series(
        strain,
        start=start,
        end=end,
        minimum_sample_rate=minimum_sample_rate,
        label="event strain",
    )
    if (
        not isinstance(central_sha, str)
        or len(central_sha) != 64
        or any(character not in "0123456789abcdef" for character in central_sha)
    ):
        raise ContractError("common PEM event strain digest is invalid")
    event_cache = run_dir / "event_aux_cache"
    if event_cache.exists() and any(event_cache.iterdir()):
        raise ContractError("common PEM event auxiliary cache is not fresh")
    rows: list[dict[str, Any]] = []
    host = str(execution["nds_host"])
    retry_count = int(execution["aux_fetch_retries"])
    backoff = float(execution["aux_fetch_backoff_base_s"])
    if retry_count < 1 or not np.isfinite(backoff) or backoff < 1:
        raise ContractError("common PEM auxiliary fetch policy is invalid")
    for channel in channels:
        auxiliary = None
        for attempt in range(retry_count):
            with patch.object(
                null_core.TimeSeries, "fetch", side_effect=auxiliary_fetch
            ):
                auxiliary = fetch_auxiliary_data(
                    channel,
                    start,
                    end,
                    event_cache,
                    host,
                )
            if auxiliary is not None:
                break
            if attempt + 1 < retry_count:
                time.sleep(backoff**attempt)
        if auxiliary is None:
            raise ContractError(
                f"common PEM event auxiliary channel unavailable: {channel}"
            )
        _require_complete_series(
            auxiliary,
            start=start,
            end=end,
            minimum_sample_rate=0,
            label=f"event auxiliary {channel}",
        )
        observed = calculate_coherence_and_plot(
            strain,
            auxiliary,
            channel,
            detector,
            int(gps),
            run_dir,
            fftlength=float(measurement["coherence_fftlength_s"]),
            freq_bounds=tuple(measurement["frequency_band_hz"]),
            threshold=1.0,
            save_plot=False,
        )
        coherence = float(observed["max_coherence"])
        peak_freq = float(observed["peak_freq"])
        low, high = (float(bound) for bound in measurement["frequency_band_hz"])
        if (
            not np.isfinite(coherence)
            or not np.isfinite(peak_freq)
            or not low <= peak_freq <= high
        ):
            raise ContractError(f"common PEM event coherence unavailable: {channel}")
        rows.append(
            {
                "aux_channel": channel,
                "data_available": True,
                "max_coherence": coherence,
                "peak_freq": peak_freq,
            }
        )

    null_path = run_dir / f"null_calibration_{detector}_{int(gps)}.json"
    if null_path.exists():
        raise ContractError(
            "common PEM null already exists without a verified resume receipt"
        )
    background_cache = run_dir / "background_aux_cache"
    if background_cache.exists() and any(background_cache.iterdir()):
        raise ContractError("common PEM background auxiliary cache is not fresh")

    def verified_background(det: str, left: int, right: int) -> Any:
        series = background_strain_reader(det, left, right)
        _require_complete_series(
            series,
            start=left,
            end=right,
            minimum_sample_rate=minimum_sample_rate,
            label="background strain",
        )
        return series

    original_aux_fetch = null_core._fetch_aux_block

    def verified_background_aux(
        channel: str,
        left: int,
        right: int,
        nds_host: str,
        max_fs: float | None = None,
    ) -> Any:
        if channel not in channels or nds_host != host:
            raise ContractError("common PEM background auxiliary source changed")
        auxiliary = original_aux_fetch(channel, left, right, nds_host, max_fs=max_fs)
        # The historical PEM core legitimately uses 512 Hz line channels.
        # Require complete finite coverage, but preserve each channel's
        # original bandwidth and the core's own Nyquist-limited statistic.
        _require_complete_series(
            auxiliary,
            start=left,
            end=right,
            minimum_sample_rate=0,
            label=f"background auxiliary {channel}",
        )
        return auxiliary

    # The historical core uses module globals for its background strain reader
    # and auxiliary cache. Scope both to this single-event process so no old
    # local strain or channel cache can enter the new five-channel null.
    with (
        patch.object(null_core, "fetch_strain_data", verified_background),
        patch.object(null_core, "_fetch_aux_block", verified_background_aux),
        patch.object(null_core, "NULL_CACHE", background_cache),
        patch.object(null_core.TimeSeries, "fetch", side_effect=auxiliary_fetch),
    ):
        calibration = calibrate_event(
            detector,
            gps,
            list(channels),
            run=run,
            block_s=float(measurement["background_block_s"]),
            alpha=float(measurement["alpha_family_wise"]),
            nds_host=host,
            n_boot=int(measurement["bootstrap_resamples"]),
            seed=int(measurement["seed"]),
            purge_cache=bool(execution["ephemeral_background_cache_purged"]),
            pem_dir=run_dir,
            candidate_gps=exclusion,
            candidate_exclusion_digest=exclusion_spec["digest"],
        )
    if background_cache.exists() and any(background_cache.iterdir()):
        raise ContractError("common PEM background auxiliary cache was not purged")
    span = calibration.get("background_span")
    if (
        calibration.get("detector") != detector
        or calibration.get("run") != run
        or float(calibration.get("event_gps")) != gps
        or calibration.get("channels") != channels
        or calibration.get("m_channels") != len(channels)
        or calibration.get("candidate_exclusion_population") != len(exclusion)
        or calibration.get("candidate_exclusion_digest") != exclusion_spec["digest"]
        or calibration.get("alpha_family_wise") != measurement["alpha_family_wise"]
        or calibration.get("n_windows", 0) < measurement["minimum_clean_windows"]
        or not isinstance(span, (list, tuple))
        or len(span) != 2
        or not all(isinstance(value, (int, float)) for value in span)
        or span[1] - span[0] != measurement["background_block_s"]
        or not null_path.is_file()
    ):
        raise ContractError("common PEM background null is incomplete or mismatched")
    top = max(rows, key=lambda row: row["max_coherence"])
    cmax = float(top["max_coherence"])
    threshold_shift = float(calibration["threshold_fw"])
    threshold_zero = float(calibration["zero_lag_control"]["q99"])
    if not np.isfinite((threshold_shift, threshold_zero)).all():
        raise ContractError("common PEM background thresholds are nonfinite")
    return {
        "schema_version": 1,
        "run": run,
        "target": dict(target),
        "candidate_exclusion_digest": exclusion_spec["digest"],
        "strain_window_sha256": central_sha,
        "channels": rows,
        "calibration": {
            "filename": null_path.name,
            "sha256": sha256_file(null_path),
            "channels": calibration["channels"],
        },
        "cmax_observed": cmax,
        "top_channel": top["aux_channel"],
        "threshold_time_shift_q99": threshold_shift,
        "threshold_zero_lag_q99": threshold_zero,
        "verdict_time_shift": (
            "COUPLED" if cmax > threshold_shift else "NO_CORRELATION"
        ),
        "verdict_tier": tier_verdict(cmax, threshold_shift, threshold_zero),
        "scientific_interpretation": "PEM_DIAGNOSTIC_ONLY_NOT_ASTROPHYSICAL_CONFIRMATION",
    }

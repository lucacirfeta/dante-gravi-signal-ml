"""Admitted context provider and bounded unchanged preprocessing replay."""

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys

from .calibration_admission import _pinned, inspect_admitted_inputs
from .calibration_recovery import read_sealed, sealed, samples_from_frames, write_json
from .input_coverage import InputCoverageError, _read
from .input_preflight import _file, _hash
from .schema_v2 import strict_json_object


class AdmittedContextProvider:
    """Read exact admitted intervals, never substitute another detector/span."""

    def __init__(self, spec, adapter, *, root, receipt_path, receipt_sha):
        self.root = Path(root).resolve()
        self.receipt_path = _pinned(receipt_path, receipt_sha)
        self.receipt_sha = receipt_sha
        self.readiness = inspect_admitted_inputs(
            spec,
            adapter,
            root=self.root,
            receipt_path=self.receipt_path,
            receipt_sha=receipt_sha,
        )
        self.receipt = read_sealed(self.receipt_path)
        self.directory = Path(self.receipt["recovery_directory"])
        self.rows = {
            (r["detector"], r["gps_start"], r["gps_end"]): r
            for r in self.receipt["records"]
        }
        if len(self.rows) != self.receipt["record_count"]:
            raise InputCoverageError("duplicate admitted context identity")

    def read(self, *, detector, start, end):
        import numpy as np
        from gwpy.timeseries import TimeSeries
        from src.core.patch_producer import CompleteContext, ContextSource

        if (
            not isinstance(detector, str)
            or type(start) not in (int, float)
            or type(end) not in (int, float)
            or (detector, start, end) not in self.rows
        ):
            raise InputCoverageError("exact admitted detector/interval required")
        _pinned(self.receipt_path, self.receipt_sha)
        row = self.rows[detector, start, end]
        path = _file(self.directory, row["relative_path"])
        _pinned(path, row["file_sha256"])
        series = TimeSeries.read(path, format="hdf5")
        values = np.ascontiguousarray(series.value)
        digest = hashlib.sha256(values.tobytes()).hexdigest()
        if (
            float(series.t0.value) != start
            or float(series.sample_rate.value) != row["sample_rate_hz"]
            or values.dtype.str != row["dtype"]
            or values.shape != (row["sample_count"],)
            or len(values) != (end - start) * row["sample_rate_hz"]
            or not np.isfinite(values).all()
            or digest != row["strain_values_sha256"]
            or digest != row["historical_strain_values_sha256"]
        ):
            raise InputCoverageError("admitted context numerical/grid identity changed")
        _pinned(path, row["file_sha256"])
        _pinned(self.receipt_path, self.receipt_sha)
        return CompleteContext(
            series=series,
            sources=(
                ContextSource(
                    path=path,
                    block_start=start,
                    block_end=end,
                    used_start=start,
                    used_end=end,
                    sha256=row["file_sha256"],
                ),
            ),
        )


def _sources(root):
    paths = (
        "src/dante_workflow/calibration_contexts.py",
        "src/core/patch_producer.py",
        "src/core/preprocessor.py",
        "src/core/utils.py",
        "src/core/data_loader.py",
        "config.yaml",
    )
    pins = {p: _hash(_file(root, p)) for p in paths}
    if _hash(Path(__file__)) != pins[paths[0]]:
        raise InputCoverageError("executed provider differs from checkout source")
    return pins


def replay(provider, *, worker=None):
    """No scorer/encoder; compare identical preprocessing on two raw read paths."""
    import numpy as np
    from src.core.utils import load_config

    root = provider.root
    before = _sources(root)
    ref = provider.receipt["parent"]
    parent_path = _file(root, ref["path"])
    _pinned(parent_path, ref["sha256"])
    parent = strict_json_object(_read(parent_path).decode(), label="input parent")
    rep = parent["representation"]
    pre = load_config()["preprocessing"]
    if (
        list(pre["qrange"]) != rep["query_qrange"]
        or list(pre["frange"]) != rep["frequency_range_hz"]
        or list(pre["output_size"]) != rep["image_shape"][:2]
        or pre["colormap"] != rep["colormap"]
    ):
        raise InputCoverageError("preprocessing defaults differ from parent contract")
    if worker is None:
        from src.core.patch_producer import _worker_preprocess

        worker = _worker_preprocess
    plan = read_sealed(provider.directory / "plan.json")
    summary = read_sealed(provider.directory / "summary.json")
    frame_paths = {
        url: _file(provider.directory, r["path"])
        for url, r in summary["frames"].items()
    }
    for url, path in frame_paths.items():
        _pinned(path, summary["frames"][url]["sha256"])
    intervals = {
        (r["detector"], r["gps_start"], r["gps_end"]): r
        for r in plan["report"]["intervals"]
    }
    if set(intervals) != set(provider.rows):
        raise InputCoverageError("numerical replay population differs")
    rows = []
    for key, row in sorted(provider.rows.items()):
        if row["sample_rate_hz"] != rep["sample_rate_hz"]:
            raise InputCoverageError("provider sample rate differs from parent")
        analysis_start = key[1] + rep["whitening_pad_s"]
        analysis_end = analysis_start + rep["analysis_duration_s"]
        if analysis_end + rep["whitening_pad_s"] != key[2]:
            raise InputCoverageError("provider context differs from frozen padding")
        context = provider.read(detector=key[0], start=key[1], end=key[2])
        values = np.ascontiguousarray(context.series.value)
        direct = samples_from_frames(intervals[key], frame_paths, row["sample_rate_hz"])
        if values.dtype != direct.dtype or values.tobytes() != direct.tobytes():
            raise InputCoverageError("provider differs from independent native slice")
        images = []
        for raw in (values, direct):
            gps, image = worker(
                raw,
                key[1],
                1 / row["sample_rate_hz"],
                str(context.series.name),
                analysis_start,
                analysis_end,
                True,
            )
            if (
                gps != analysis_start
                or image is None
                or image.shape != tuple(rep["image_shape"])
                or image.dtype != np.dtype("uint8")
            ):
                raise InputCoverageError("unchanged PatchProducer consumer failed")
            images.append(image)
        if images[0].tobytes() != images[1].tobytes():
            raise InputCoverageError("provider/direct preprocessing mismatch")
        rows.append(
            {
                "detector": key[0],
                "gps_start": key[1],
                "gps_end": key[2],
                "analysis_start": analysis_start,
                "analysis_end": analysis_end,
                "raw_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                "image_sha256": hashlib.sha256(images[0].tobytes()).hexdigest(),
                "sample_count": len(values),
                "image_shape": list(images[0].shape),
                "source_container_sha256": context.sources[0].sha256,
            }
        )
    for url, path in frame_paths.items():
        _pinned(path, summary["frames"][url]["sha256"])
    _pinned(provider.receipt_path, provider.receipt_sha)
    _pinned(parent_path, ref["sha256"])
    if _sources(root) != before:
        raise InputCoverageError("numerical replay sources changed")
    return sealed(
        {
            "schema_version": 1,
            "status": "PASS_ADMITTED_CONTEXT_PREPROCESSING_ONLY",
            "admission_sha256": provider.receipt_sha,
            "admission_digest": provider.receipt["digest"],
            "parent": ref,
            "rows": rows,
            "record_count": len(rows),
            "source_hashes": before,
            "scientific_execution_ready": False,
            "score_values_read": False,
            "encoder_or_scorer_executed": False,
            "all_calibration_contexts_measured": False,
            "verification_was_second_fetch": False,
            "runtime": {
                name: version(name)
                for name in ("numpy", "gwpy", "h5py", "scipy", "matplotlib")
            },
        }
    )


def main(argv=None):
    from .adapters import build_adapter
    from .schema import load_workflow_spec

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    if args.require_installed and Path(__file__).resolve().is_relative_to(root):
        parser.error("installed provider required, checkout import refused")
    if (args.expected is None) != (args.expected_sha256 is None):
        parser.error("expected evidence path and SHA required together")
    if args.require_installed and args.expected is None:
        parser.error("installed replay requires pinned expected evidence")
    if str(root) not in sys.path:
        sys.path.append(
            str(root)
        )  # Scientific src.core only; workflow stays installed.
    spec = load_workflow_spec(args.config.resolve(), root=root)
    provider = AdmittedContextProvider(
        spec,
        build_adapter(spec),
        root=root,
        receipt_path=args.receipt,
        receipt_sha=args.receipt_sha256,
    )
    output = args.output
    if (
        not output.is_absolute()
        or output.exists()
        or any(p.is_symlink() for p in (output, *output.parents))
        or output.resolve().is_relative_to(root)
        or output.resolve().is_relative_to(provider.directory.resolve())
        or output.resolve().is_relative_to(provider.receipt_path.parent.resolve())
    ):
        parser.error("new external output outside preserved evidence required")
    result = replay(provider)
    if args.expected is not None:
        expected_path = _pinned(args.expected, args.expected_sha256)
        if result != read_sealed(expected_path):
            raise InputCoverageError("installed numerical replay differs from checkout")
        _pinned(expected_path, args.expected_sha256)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x"):
        pass
    write_json(output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "record_count": result["record_count"],
                "digest": result["digest"],
                "output": str(output),
                "provider_module": str(Path(__file__).resolve()),
                "installed_replay": args.require_installed,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

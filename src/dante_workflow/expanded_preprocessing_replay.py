"""Full padded calibration preprocessing, without encoders, scores or thresholds."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
from importlib.metadata import version
import json
import multiprocessing as mp
import os
from pathlib import Path
import re
import subprocess
import sys
import warnings

from .calibration_admission import _pinned
from .calibration_expanded_admission import same
from .calibration_recovery import read_sealed, sealed, write_json
from .expanded_context_replay import bind as native_bind
from .expanded_context_replay import independent_values, isolated, quiet, record
from .expanded_preprocessing_binding import preflight
from .input_coverage import InputCoverageError
from .input_preflight import _file, _hash
from .schema import canonical_json_sha256
from .schema_v2 import strict_json_object


SOURCES = (
    "src/dante_workflow/expanded_preprocessing_replay.py",
    "scripts/replay_dante_workflow_expanded_preprocessing.py",
)
BOUNDARY = {
    "full_calibration_context_preprocessing_only": True,
    "physical_data_quality_certified": False,
    "full_calibration_verified": False,
    "default_provider_replaced": False,
    "score_values_read": False,
    "o4b_launch_allowed": False,
}
MEASUREMENT = "all admitted unique full finite native contexts; unchanged PatchProducer worker images; standalone h5py reader and explicit inherited component-chain reconstruction; exact uint8 equality, no threshold or sampling"
POPULATION = "retain every frozen calibration identity and context; no new DQ/scan exclusion; invalid input or preprocessing failure stops instead of skipping"
STORAGE = "fresh local NPY uint8 RGB and sealed per-context receipts; never historical shards or images"


def runtime():
    return {
        "python": sys.version,
        "packages": {
            name: version(name)
            for name in ("numpy", "scipy", "gwpy", "matplotlib", "astropy", "h5py")
        },
    }


def source_audit(root, freeze):
    if not isinstance(freeze, str) or not re.fullmatch(r"[0-9a-f]{40}", freeze):
        raise InputCoverageError("full preprocessing source freeze required")
    result = {}
    for name in SOURCES:
        data = subprocess.run(
            ["git", "show", f"{freeze}:{name}"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        result[name] = hashlib.sha256(data).hexdigest()
        _pinned(_file(root, name), result[name])
    if _hash(Path(__file__)) != result[SOURCES[0]]:
        raise InputCoverageError("executed preprocessing replay differs from freeze")
    return result


def bind(
    *,
    root,
    contract_path,
    contract_sha,
    source_freeze,
    recovery_dir,
    native_dir,
    binding_path,
    binding_sha,
    method_path,
):
    root = Path(root).resolve()
    contract_path = _pinned(contract_path, contract_sha)
    contract = strict_json_object(
        contract_path.read_text(), label="full preprocessing replay"
    )
    if (
        type(contract.get("schema_version")) is not int
        or contract["schema_version"] != 1
        or contract.get("status") != "FULL_EXPANDED_CALIBRATION_PREPROCESSING_REPLAY_V1"
        or contract.get("source_paths") != list(SOURCES)
        or not same(contract.get("boundary"), BOUNDARY)
        or contract.get("measurement_rule") != MEASUREMENT
        or contract.get("population_rule") != POPULATION
        or contract.get("image_storage_rule") != STORAGE
        or contract.get("automatic_resume") is not False
    ):
        raise InputCoverageError("unsupported full preprocessing authority")
    sources = source_audit(root, source_freeze)
    ref = contract["method_contract"]
    method_path = _pinned(method_path, ref["evidence_sha256"])
    expected = read_sealed(method_path)
    kwargs = dict(
        root=root,
        contract_path=_file(root, ref["path"]),
        contract_sha=ref["sha256"],
        source_freeze=ref["source_freeze"],
        recovery_dir=recovery_dir,
        native_dir=native_dir,
        binding_path=binding_path,
        binding_sha=binding_sha,
    )
    method = preflight(**kwargs)
    if not same(method, expected):
        raise InputCoverageError("inherited method/input evidence differs")
    method_contract = strict_json_object(
        _pinned(kwargs["contract_path"], ref["sha256"]).read_text(),
        label="method parent",
    )
    native = method_contract["native_replay"]
    provider, native_binding = native_bind(
        root=root,
        contract_path=_file(root, native["contract_path"]),
        contract_sha=native["contract_sha256"],
        recovery_dir=recovery_dir,
        binding_path=binding_path,
        binding_sha=binding_sha,
        freeze=native["source_freeze"],
    )
    if native_binding["digest"] != method["native_binding_digest"]:
        raise InputCoverageError("native binding changed")
    extra = contract["additional_runtime_source_pins"]
    if set(extra) != {"src/core/utils.py", "src/core/data_loader.py"}:
        raise InputCoverageError("incomplete preprocessing runtime source inventory")
    for name, sha in extra.items():
        _pinned(_file(root, name), sha)
    # Import paths must belong to the bound checkout, not another installed copy.
    from src.core import patch_producer, preprocessor, utils, data_loader

    for module in (patch_producer, preprocessor, utils, data_loader):
        name = Path(module.__file__).resolve().relative_to(root).as_posix()
        pin = extra.get(name) or next(
            (
                r["current_sha256"]
                for r in method["qualified_sources"].values()
                if r["path"] == name
            ),
            None,
        )
        if pin is None:
            raise InputCoverageError("unbound loaded preprocessing module")
        _pinned(Path(module.__file__), pin)
    import yaml

    config_ref = method["qualified_sources"]["runtime_config"]
    config = yaml.safe_load(
        _pinned(
            _file(root, config_ref["path"]), config_ref["current_sha256"]
        ).read_text()
    )
    if not same(preprocessor._CFG, config):
        raise InputCoverageError("loaded preprocessing config differs from bound bytes")
    for row in method["qualified_sources"].values():
        _pinned(_file(root, row["path"]), row["current_sha256"])
    for name, sha in extra.items():
        _pinned(_file(root, name), sha)
    _pinned(method_path, ref["evidence_sha256"])
    _pinned(contract_path, contract_sha)
    if source_audit(root, source_freeze) != sources:
        raise InputCoverageError("preprocessing sources changed during binding")
    return provider, sealed(
        dict(
            contract_sha256=contract_sha,
            source_freeze=source_freeze,
            source_hashes=sources,
            additional_runtime_source_pins=extra,
            method_sha256=ref["evidence_sha256"],
            method=method,
            runtime=runtime(),
            boundary=BOUNDARY,
        )
    )


def image_check(image, representation):
    import numpy as np

    if (
        image is None
        or not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or list(image.shape) != representation["image_shape"]
    ):
        raise InputCoverageError("preprocessing failed or image geometry/dtype differs")
    return np.ascontiguousarray(image)


def independent_image(values, key, name, representation):
    """Separate dispatch chain using frozen primitives, not a second algorithm."""
    import numpy as np
    import matplotlib.pyplot as plt
    from gwpy.timeseries import TimeSeries
    from src.core.preprocessor import (
        whiten_context,
        extract_clean_subwindow,
        generate_qtransform,
    )

    rate, pad = representation["sample_rate_hz"], representation["whitening_pad_s"]
    begin, end = key[1] + pad, key[2] - pad
    series = TimeSeries(values, t0=key[1], dt=1 / rate, name=name)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        filtered, padding = whiten_context(series, begin, end, pad=pad)
        tolerance = max(1 / rate, np.finfo(np.float64).eps)
        if any(
            padding[k] < pad - tolerance for k in ("effective_left", "effective_right")
        ):
            raise InputCoverageError("independent preprocessing padding incomplete")
        clean = extract_clean_subwindow(filtered, begin, end)
        if (
            float(clean.t0.value) != begin
            or len(clean) != representation["analysis_duration_s"] * rate
        ):
            raise InputCoverageError("independent clean analysis grid differs")
        q = generate_qtransform(
            clean,
            qrange=tuple(representation["query_qrange"]),
            frange=tuple(representation["frequency_range_hz"]),
            output_size=tuple(representation["image_shape"][:2]),
            save_path=None,
            cmap=representation["colormap"],
        )
        image = (plt.get_cmap(representation["colormap"])(q)[:, :, :3] * 255).astype(
            np.uint8
        )
    return image_check(image, representation)


def paths(directory, key):
    stem = canonical_json_sha256(key)
    return directory / "contexts" / (stem + ".json"), directory / "images" / (
        stem + ".npy"
    )


def receipt(native_record, image, image_path, rep):
    return sealed(
        dict(
            native_context=native_record,
            analysis_gps_start=native_record["gps_start"] + rep["whitening_pad_s"],
            analysis_gps_end=native_record["gps_end"] - rep["whitening_pad_s"],
            image_shape=list(image.shape),
            image_dtype=image.dtype.str,
            image_values_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
            image_file_sha256=_hash(image_path),
            image_relative_path="images/" + image_path.name,
        )
    )


def measure(provider, key, rep):
    import numpy as np

    context = provider.read(detector=key[0], start=key[1], end=key[2])
    native_record = record(provider, key, context.series.value)
    return (
        native_record,
        np.ascontiguousarray(context.series.value),
        str(context.series.name),
    )


def aggregate(binding, records):
    return sealed(
        dict(
            status="PASS_COMPLETE_EXPANDED_CALIBRATION_PREPROCESSING_ONLY",
            binding=binding,
            record_count=len(records),
            records_sha256=canonical_json_sha256(records),
            all_frozen_contexts_preprocessed=True,
            population_reduced=False,
            new_dq_filter_applied=False,
            boundary=BOUNDARY,
        )
    )


def execute(*, stage, run_dir, binding_kwargs, summary_sha=None):
    import numpy as np

    provider, binding = bind(**binding_kwargs)
    directory = isolated(run_dir, provider)
    for name in ("native_dir", "method_path"):
        if name in binding_kwargs:
            parent = Path(binding_kwargs[name]).resolve()
            if name == "method_path":
                parent = parent.parent
            if directory.is_relative_to(parent) or parent.is_relative_to(directory):
                raise InputCoverageError(
                    "separate output outside preserved preprocessing parents required"
                )
    method = binding["method"]
    rep = method["representation"]
    params = method["execution_parameters"]
    workers, batch_size = params["workers"], params["batch_size"]
    if any(type(x) is not int or x < 1 for x in (workers, batch_size)):
        raise InputCoverageError("inherited execution geometry invalid")
    if stage == "run":
        directory.mkdir(parents=True, exist_ok=False)
        for sub in ("contexts", "images"):
            (directory / sub).mkdir()
        write_json(directory / "binding.json", binding)
    elif stage == "verify":
        quiet(directory)
        if (directory / "verification.json").exists():
            raise InputCoverageError("verification already exists; no duplicate")
        expected = read_sealed(_pinned(directory / "summary.json", summary_sha))
        if not same(read_sealed(_file(directory, "binding.json")), binding):
            raise InputCoverageError("frozen preprocessing binding differs")
    else:
        raise InputCoverageError("unsupported preprocessing stage")
    lock = directory / "controller.lock"
    with lock.open("x") as stream:
        json.dump(
            {"pid": os.getpid(), "stage": stage, "binding_digest": binding["digest"]},
            stream,
        )
    try:
        records = []
        keys = sorted(provider.allowed)
        if stage == "run":
            from src.core.patch_producer import _worker_preprocess

            with ProcessPoolExecutor(
                max_workers=workers, mp_context=mp.get_context("spawn")
            ) as pool:
                for offset in range(0, len(keys), batch_size):
                    prepared = []
                    for key in keys[offset : offset + batch_size]:
                        native_record, values, name = measure(provider, key, rep)
                        begin, end = (
                            key[1] + rep["whitening_pad_s"],
                            key[2] - rep["whitening_pad_s"],
                        )
                        prepared.append(
                            (
                                key,
                                native_record,
                                begin,
                                pool.submit(
                                    _worker_preprocess,
                                    values,
                                    key[1],
                                    1 / rep["sample_rate_hz"],
                                    name,
                                    begin,
                                    end,
                                    True,
                                ),
                            )
                        )
                    for key, native_record, begin, future in prepared:
                        gps, image = future.result()
                        if gps != int(begin):
                            raise InputCoverageError(
                                "worker returned wrong analysis label"
                            )
                        image = image_check(image, rep)
                        json_path, image_path = paths(directory, key)
                        temp = image_path.with_suffix(".npy.partial")
                        with temp.open("xb") as stream:
                            np.save(stream, image, allow_pickle=False)
                        temp.replace(image_path)
                        row = receipt(native_record, image, image_path, rep)
                        write_json(json_path, row)
                        records.append(row)
                    progress(directory, stage, binding, len(records), len(keys))
        else:
            for key in keys:
                values = independent_values(provider, key)
                native_record = record(provider, key, values)
                json_path, image_path = paths(directory, key)
                retained = read_sealed(
                    _file(directory, json_path.relative_to(directory).as_posix())
                )
                _pinned(
                    _file(directory, image_path.relative_to(directory).as_posix()),
                    retained["image_file_sha256"],
                )
                saved = image_check(np.load(image_path, allow_pickle=False), rep)
                rebuilt = independent_image(
                    values, key, provider.expected_names[key], rep
                )
                if not np.array_equal(saved, rebuilt) or not same(
                    receipt(native_record, rebuilt, image_path, rep), retained
                ):
                    raise InputCoverageError(
                        "independent full preprocessing image differs"
                    )
                records.append(retained)
                progress(directory, stage, binding, len(records), len(keys))
        for sub, index in (("contexts", 0), ("images", 1)):
            if {p.name for p in (directory / sub).iterdir()} != {
                paths(directory, key)[index].name for key in keys
            }:
                raise InputCoverageError("extra/missing preprocessing receipts/images")
        _, final = bind(**binding_kwargs)
        if not same(final, binding):
            raise InputCoverageError("preprocessing parent/source/runtime changed")
        result = aggregate(binding, records)
        if stage == "verify":
            if not same(expected, result):
                raise InputCoverageError("independent preprocessing aggregate differs")
            _pinned(directory / "summary.json", summary_sha)
            result = sealed(
                dict(
                    status="PASS_VERIFIED_EXPANDED_CALIBRATION_PREPROCESSING_ONLY",
                    binding=binding,
                    summary_sha256=summary_sha,
                    summary_digest=result["digest"],
                    record_count=len(records),
                    independent_reader="h5py retained native container",
                    independent_dispatch="explicit chain using SAME frozen scientific primitives, not an independent implementation",
                    verification_was_second_fetch=False,
                    boundary=BOUNDARY,
                )
            )
        write_json(
            directory / ("summary.json" if stage == "run" else "verification.json"),
            result,
        )
        return result
    except Exception as exc:
        write_json(
            directory / "failure.json",
            sealed(
                dict(
                    status="FAILED_EXPANDED_PREPROCESSING_REPLAY",
                    stage=stage,
                    error_type=type(exc).__name__,
                    message=str(exc),
                    binding_digest=binding["digest"],
                    automatic_resume=False,
                )
            ),
        )
        raise
    finally:
        lock.unlink()


def progress(directory, stage, binding, completed, expected):
    write_json(
        directory / f"progress.{stage}.json",
        sealed(
            dict(
                stage=stage,
                binding_digest=binding["digest"],
                completed_contexts=completed,
                expected_contexts=expected,
            )
        ),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("run", "verify"), required=True)
    for name in (
        "repository-root",
        "contract",
        "recovery-dir",
        "native-dir",
        "binding",
        "method",
        "run-dir",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("contract-sha256", "binding-sha256", "source-freeze"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--summary-sha256")
    args = parser.parse_args(argv)
    if (args.stage == "verify") != (args.summary_sha256 is not None):
        parser.error("summary SHA required only for standalone verify")
    result = execute(
        stage=args.stage,
        run_dir=args.run_dir,
        summary_sha=args.summary_sha256,
        binding_kwargs=dict(
            root=args.repository_root,
            contract_path=args.contract,
            contract_sha=args.contract_sha256,
            source_freeze=args.source_freeze,
            recovery_dir=args.recovery_dir,
            native_dir=args.native_dir,
            binding_path=args.binding,
            binding_sha=args.binding_sha256,
            method_path=args.method,
        ),
    )
    print(
        json.dumps(
            {k: result[k] for k in ("status", "record_count", "digest")}, sort_keys=True
        )
    )
    return 0

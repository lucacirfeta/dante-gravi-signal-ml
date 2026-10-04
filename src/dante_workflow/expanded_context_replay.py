"""Full-domain native consumer replay; no preprocessing or scientific scoring."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .calibration_admission import _directory, _pinned
from .calibration_expanded_admission import same
from .calibration_recovery import read_sealed, sealed, write_json
from .expanded_context_provider import ExpandedCalibrationContextProvider, preflight
from .input_coverage import InputCoverageError
from .input_preflight import _file, _hash
from .schema import canonical_json_sha256
from .schema_v2 import strict_json_object


BOUNDARY = {
    "full_native_consumer_replay_only": True,
    "preprocessing_verified": False,
    "full_context_validity_verified": False,
    "full_calibration_verified": False,
    "default_provider_replaced": False,
    "scientific_execution_ready": False,
    "o4b_launch_allowed": False,
}
RULE = "all admitted exact contexts through unchanged consumer; independent h5py container replay; no sampling, fallback or second fetch"
SOURCES = (
    "src/dante_workflow/expanded_context_replay.py",
    "scripts/replay_dante_workflow_expanded_contexts.py",
    "src/dante_workflow/expanded_context_provider.py",
    "src/dante_workflow/calibration_contexts.py",
    "src/dante_workflow/calibration_expanded_admission.py",
    "src/dante_workflow/calibration_recovery.py",
    "src/dante_workflow/calibration_admission.py",
    "src/dante_workflow/input_preflight.py",
    "src/dante_workflow/schema.py",
    "src/dante_workflow/schema_v2.py",
)


def source_audit(root, freeze):
    if not isinstance(freeze, str) or not re.fullmatch(r"[0-9a-f]{40}", freeze):
        raise InputCoverageError("full source freeze commit required")
    hashes = {}
    for name in SOURCES:
        historical = subprocess.run(
            ["git", "show", f"{freeze}:{name}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        sha = hashlib.sha256(historical).hexdigest()
        _pinned(_file(root, name), sha)
        hashes[name] = sha
    if _hash(Path(__file__)) != hashes[SOURCES[0]]:
        raise InputCoverageError("executed replay differs from frozen checkout")
    return hashes


def bind(
    *,
    root,
    contract_path,
    contract_sha,
    recovery_dir,
    binding_path,
    binding_sha,
    freeze,
):
    root = _directory(root).resolve()
    contract_path = _pinned(contract_path, contract_sha)
    contract = strict_json_object(contract_path.read_text(), label="native replay")
    version = contract.get("schema_version")
    if (
        type(version) is not int
        or version not in (1, 2)
        or contract.get("status") != f"FULL_EXPANDED_NATIVE_CONSUMER_REPLAY_V{version}"
        or not same(contract.get("boundary"), BOUNDARY)
        or contract.get("replay_rule") != RULE
        or contract.get("source_paths") != list(SOURCES)
        or contract.get("automatic_resume") is not False
    ):
        raise InputCoverageError("unsupported native replay authority")
    sources = source_audit(root, freeze)
    ref = contract["consumer_contract"]
    kwargs = dict(
        root=root,
        contract_path=_file(root, ref["path"]),
        contract_sha=ref["sha256"],
        run_dir=recovery_dir,
    )
    expected = read_sealed(_pinned(binding_path, binding_sha))
    if not same(preflight(**kwargs), expected):
        raise InputCoverageError("parent consumer binding differs")
    provider = ExpandedCalibrationContextProvider(**kwargs)
    if provider.schema_version != version:
        raise InputCoverageError("replay/consumer version mismatch")
    return provider, sealed(
        {
            "contract_sha256": contract_sha,
            "binding_sha256": binding_sha,
            "source_freeze": freeze,
            "source_hashes": sources,
            "identity_count": provider.identity_count,
            "identity_counts": provider.identity_counts,
            "unique_context_count": len(provider.allowed),
            "context_keys_sha256": canonical_json_sha256(sorted(provider.allowed)),
            "parent_evidence_sha256": provider.evidence_sha256,
            **(
                {
                    "series_names_sha256": canonical_json_sha256(
                        expected["prior_series_names"]
                    )
                }
                if version == 2
                else {}
            ),
            "boundary": BOUNDARY,
        }
    )


def isolated(path, provider):
    path = _directory(path).resolve()
    plan = read_sealed(provider.directory / "plan.json")
    protected = [
        provider.root,
        provider.directory,
        provider.prior.receipt_path.parent.resolve(),
    ]
    protected += [
        Path(plan[k]).resolve() for k in ("historical_directory", "metadata_directory")
    ]
    if any(path.is_relative_to(p) or p.is_relative_to(path) for p in protected):
        raise InputCoverageError("separate external replay directory required")
    return path


def container(provider, key):
    owner = provider if key in provider.rows else provider.prior
    row = owner.rows[key]
    path = _pinned(_file(owner.directory, row["relative_path"]), row["file_sha256"])
    return path, row


def record(provider, key, values):
    import numpy as np

    planned = provider.planned[key]
    values = np.ascontiguousarray(values)
    _, row = container(provider, key)
    sha = hashlib.sha256(values.tobytes()).hexdigest()
    if (
        values.dtype.str != row["dtype"]
        or values.shape != (planned["sample_count"],)
        or not np.isfinite(values).all()
        or sha != planned["historical_strain_values_sha256"]
    ):
        raise InputCoverageError("full consumer native values differ")
    return sealed(
        {
            "detector": key[0],
            "gps_start": key[1],
            "gps_end": key[2],
            "sample_rate_hz": planned["sample_rate_hz"],
            "sample_count": planned["sample_count"],
            "dtype": values.dtype.str,
            "strain_values_sha256": sha,
            "container_sha256": row["file_sha256"],
            "origin": "expanded" if key in provider.rows else "prior",
            **(
                {"series_name": provider.expected_names[key]}
                if getattr(provider, "schema_version", 1) == 2
                else {}
            ),
        }
    )


def independent_values(provider, key):
    """Separate h5py path, never consumer.read or GWPy TimeSeries.read."""
    import h5py
    import numpy as np

    path, row = container(provider, key)
    with h5py.File(path, "r") as stream:
        datasets = []
        stream.visititems(
            lambda _, obj: (
                datasets.append(obj) if isinstance(obj, h5py.Dataset) else None
            )
        )
        if len(datasets) != 1:
            raise InputCoverageError("ambiguous retained native HDF5 dataset")
        dataset = datasets[0]
        if getattr(provider, "schema_version", 1) == 2:
            name = dataset.attrs.get("name")
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            if name != provider.expected_names[key]:
                raise InputCoverageError("independent HDF5 series name differs")
        if (
            float(dataset.attrs.get("x0", float("nan"))) != key[1]
            or float(dataset.attrs.get("dx", float("nan"))) != 1 / row["sample_rate_hz"]
            or dataset.shape != (row["sample_count"],)
            or dataset.dtype.str != row["dtype"]
        ):
            raise InputCoverageError("independent HDF5 native grid differs")
        values = np.ascontiguousarray(dataset[:])
    _pinned(path, row["file_sha256"])
    return values


def receipt_path(directory, key):
    return directory / "contexts" / (canonical_json_sha256(key) + ".json")


def aggregate(provider, binding, records):
    return sealed(
        {
            "status": "PASS_COMPLETE_EXPANDED_NATIVE_CONSUMER_ONLY",
            "binding": binding,
            "record_count": len(records),
            "records_sha256": canonical_json_sha256(records),
            "all_expanded_contexts_read_through_consumer": True,
            "verification_was_second_fetch": False,
            "boundary": BOUNDARY,
        }
    )


def quiet(directory):
    if (
        any((directory / p).exists() for p in ("controller.lock", "failure.json"))
        or any(directory.rglob("*.partial"))
        or any(directory.rglob("*.tmp"))
    ):
        raise InputCoverageError("replay has active/failed/incomplete evidence")


def execute(*, stage, run_dir, binding_kwargs, summary_sha=None):
    provider, binding = bind(**binding_kwargs)
    directory = isolated(run_dir, provider)
    if stage == "run":
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "contexts").mkdir()
        write_json(directory / "binding.json", binding)
    elif stage == "verify":
        quiet(directory)
        if (directory / "verification.json").exists():
            raise InputCoverageError("verification already exists; do not duplicate")
        expected = read_sealed(_pinned(directory / "summary.json", summary_sha))
        if not same(read_sealed(directory / "binding.json"), binding):
            raise InputCoverageError("frozen replay binding differs")
    else:
        raise InputCoverageError("unsupported replay stage")
    lock = directory / "controller.lock"
    with lock.open("x") as stream:
        json.dump(
            {"pid": os.getpid(), "stage": stage, "binding_digest": binding["digest"]},
            stream,
        )
    try:
        records = []
        for key in sorted(provider.allowed):
            if stage == "run":
                context = provider.read(detector=key[0], start=key[1], end=key[2])
                row = record(provider, key, context.series.value)
                write_json(receipt_path(directory, key), row)
            else:
                row = record(provider, key, independent_values(provider, key))
                retained_receipt = _file(
                    directory,
                    receipt_path(directory, key).relative_to(directory).as_posix(),
                )
                if not same(read_sealed(retained_receipt), row):
                    raise InputCoverageError("independent context receipt differs")
            records.append(row)
            write_json(
                directory / f"progress.{stage}.json",
                sealed(
                    {
                        "stage": stage,
                        "binding_digest": binding["digest"],
                        "completed_contexts": len(records),
                        "expected_contexts": len(provider.allowed),
                    }
                ),
            )
        if {p.name for p in (directory / "contexts").iterdir()} != {
            receipt_path(directory, key).name for key in provider.allowed
        }:
            raise InputCoverageError("extra/missing replay context receipts")
        # No cached receipt guard: all parent/source binding checks repeat at end.
        _, final_binding = bind(**binding_kwargs)
        if not same(final_binding, binding):
            raise InputCoverageError("replay parent/source changed during read")
        result = aggregate(provider, binding, records)
        if stage == "verify":
            if not same(expected, result):
                raise InputCoverageError("independent full replay summary differs")
            _pinned(directory / "summary.json", summary_sha)
            result = sealed(
                {
                    "status": "PASS_VERIFIED_EXPANDED_NATIVE_CONSUMER_ONLY",
                    "summary_sha256": summary_sha,
                    "summary_digest": result["digest"],
                    "record_count": len(records),
                    "binding": binding,
                    "independent_reader": "h5py retained native container",
                    "verification_was_second_fetch": False,
                    "boundary": BOUNDARY,
                }
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
                {
                    "status": "FAILED_EXPANDED_NATIVE_CONSUMER_REPLAY",
                    "stage": stage,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "binding_digest": binding["digest"],
                    "automatic_resume": False,
                }
            ),
        )
        raise
    finally:
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("run", "verify"), required=True)
    for name in ("repository-root", "contract", "recovery-dir", "binding", "run-dir"):
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
            recovery_dir=args.recovery_dir,
            binding_path=args.binding,
            binding_sha=args.binding_sha256,
            freeze=args.source_freeze,
        ),
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "record_count": result["record_count"],
                "digest": result["digest"],
            },
            sort_keys=True,
        )
    )
    return 0

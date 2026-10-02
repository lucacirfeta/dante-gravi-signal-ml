"""Retained native PEM decisions from isolated bytes, with read-only parents.

Not a fresh coherence/null replay. The original productive verifier is never
called. No archived Python is executed; source bytes bind installed helpers.
"""

from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
import hashlib
import importlib
import io
from pathlib import Path, PurePosixPath

from . import evidence_snapshot as snapshots
from . import o3a_coincidence_verification as parents
from .o3a_retained_runtime import new_evidence, receipt_fields
from .o3a_locking import clean_native_parent
from .o3a_initial_verification import InitialEvidenceError, _existing, _json


class _SnapshotFiles:
    def __init__(self, view):
        self.view, self.used, self.locations = view, set(), {}
        for row in view.manifest()["entries"]:
            key = (row["root"], row["relative_path"])
            if row["root"] not in {"repository", "parents", "pem"} or row[
                "name"
            ] != "/".join(key):
                raise InitialEvidenceError("PEM snapshot namespace/name changed")
            self.locations[key] = row["name"]

    def read(self, namespace, relative):
        key = (namespace, relative)
        if key not in self.locations:
            raise InitialEvidenceError("PEM snapshot required member missing")
        name = self.locations[key]
        self.used.add(name)
        return self.view.read(name)

    def complete(self):
        if self.used != set(self.locations.values()):
            raise InitialEvidenceError(
                "PEM snapshot has unconsumed/additional evidence"
            )


class _SnapshotPath:
    """Only operations required by original pure readers; no live fallback."""

    def __init__(self, files, namespace, relative=""):
        self.files, self.namespace, self.relative = files, namespace, relative

    def __truediv__(self, child):
        child = child.as_posix() if isinstance(child, (Path, PurePosixPath)) else child
        snapshots._name(child)
        return _SnapshotPath(
            self.files, self.namespace, "/".join(filter(None, (self.relative, child)))
        )

    def __eq__(self, other):
        return isinstance(other, _SnapshotPath) and (
            self.files is other.files
            and self.namespace == other.namespace
            and self.relative == other.relative
        )

    def __fspath__(self):
        raise InitialEvidenceError("snapshot paths cannot become live filesystem paths")

    def __str__(self):
        return f"snapshot:{self.namespace}/{self.relative}"

    @property
    def name(self):
        return PurePosixPath(self.relative).name

    @property
    def parent(self):
        relative = str(PurePosixPath(self.relative).parent)
        return _SnapshotPath(
            self.files, self.namespace, "" if relative == "." else relative
        )

    def resolve(self):
        return self

    def is_relative_to(self, other):
        return (
            isinstance(other, _SnapshotPath)
            and self.files is other.files
            and self.namespace == other.namespace
            and (
                not other.relative
                or self.relative == other.relative
                or self.relative.startswith(other.relative + "/")
            )
        )

    def relative_to(self, other):
        from src.dante_light.o3a_native_contract import ROOT

        if isinstance(other, _SnapshotPath):
            if not self.is_relative_to(other):
                raise InitialEvidenceError("escaping snapshot relative reference")
            return PurePosixPath(self.relative[len(other.relative) :].lstrip("/"))
        # Existing inventory _parent_binding uses the original ROOT constant.
        # It is a logical namespace anchor, never a filesystem redirect.
        if self.namespace != "repository" or other != ROOT:
            raise InitialEvidenceError("unsupported snapshot logical root")
        return PurePosixPath(self.relative)

    def is_file(self):
        return (self.namespace, self.relative) in self.files.locations

    def read_bytes(self):
        return self.files.read(self.namespace, self.relative)

    def read_text(self, encoding="utf-8"):
        payload = self.read_bytes()
        if self.relative.endswith(".json"):
            _json(payload)
        elif self.relative.endswith(".jsonl"):
            for line in payload.splitlines():
                if line:
                    _json(line)
        return payload.decode(encoding)

    def open(self, mode="r", encoding="utf-8"):
        if mode == "rb":
            return io.BytesIO(self.read_bytes())
        if mode == "r":
            return io.StringIO(self.read_text(encoding=encoding))
        raise InitialEvidenceError("snapshot is read-only")


def _sources(root):
    from src.dante_light.o3a_raw_download import file_sha256

    result = parents._sources(root)
    for name in (
        "src.dante_light.o3a_native_pem",
        "src.pipeline_v2_production.pem_coherence_analysis",
        "src.pipeline_v2_production.pem_null_calibration",
    ):
        module = importlib.import_module(name)
        relative = name.replace(".", "/") + ".py"
        digest = file_sha256(Path(module.__file__))
        if file_sha256(_existing(root, relative)) != digest:
            raise InitialEvidenceError("executed PEM helper source mismatch")
        result[relative] = digest
    base = Path(__file__).resolve().parents[2]
    for relative in (
        "src/dante_workflow/evidence_snapshot.py",
        "scripts/dante_evidence_snapshot.py",
        "src/dante_workflow/o3a_pem_verification.py",
        "scripts/verify_dante_o3a_pem_evidence.py",
    ):
        result[relative] = file_sha256(base / relative)
    return result


def _guards(directory):
    if directory.is_symlink():
        raise InitialEvidenceError("PEM guard directory is a symlink")
    if any(
        (directory / name).is_symlink()
        for name in ("failure.json", "failures.json", "controller.lock", "run.lock")
    ):
        raise InitialEvidenceError("PEM failure/lock guard is a symlink")
    parents.decisions.scores._clean(directory)
    cache = directory / "transient_raw"
    if cache.is_symlink() or any(
        p.is_file() or p.is_symlink() for p in cache.rglob("*")
    ):
        raise InitialEvidenceError("PEM transient raw cache is not empty or safe")


def _retained_gate(files):
    from src.dante_light import o3a_native_pem as pem
    from src.dante_light.contracts import canonical_json_sha256

    root = _SnapshotPath(files, "repository")
    contract = pem.load_contract(root=root)
    preflight, targets, exclusion = pem.preflight_inputs(
        root=root, external_root=_SnapshotPath(files, "parents")
    )
    key = pem._run_key(contract, preflight)
    directory = _SnapshotPath(files, "pem") / (contract["output"]["prefix"] + key)
    summary = _json((directory / "native_pem_summary.json").read_bytes())
    pem._sealed(summary, "artifact_digest")
    observed, specs = {}, {}
    for bucket, filename in (
        ("targets", "native_pem_targets.jsonl"),
        ("primary", "native_pem_primary.jsonl"),
        ("diagnostic", "native_pem_diagnostic.jsonl"),
    ):
        path = directory / filename
        payload = path.read_bytes()
        rows = [_json(line) for line in payload.splitlines() if line]
        # Whole original canonical JSONL bytes, not only parsed row equality.
        canonical = b"".join(snapshots._encoded(row) + b"\n" for row in rows)
        if payload != canonical:
            raise InitialEvidenceError("PEM original output bytes changed")
        specs[bucket] = pem._outputs_spec(path, rows)
        observed[bucket] = rows
    if observed["targets"] != targets or summary["outputs"] != specs:
        raise InitialEvidenceError("PEM frozen targets/output specification changed")
    by_key = {(r["population"], r["detector"], r["gps_start"]): r for r in targets}
    if (
        len(by_key) != len(targets)
        or len(exclusion) != contract["population"]["candidate_exclusion_total"]
    ):
        raise InitialEvidenceError("PEM target/exclusion accounting changed")
    seen, event_summary = set(), {}
    for bucket in ("primary", "diagnostic"):
        events = observed[bucket]
        for event in events:
            target = event["target"]
            identity = target["population"], target["detector"], target["gps_start"]
            if (
                target["population"] != bucket
                or identity in seen
                or by_key.get(identity) != target
            ):
                raise InitialEvidenceError("PEM event identity/role changed")
            seen.add(identity)
            event_path = (
                directory
                / "events"
                / f"{bucket}_{target['detector']}_{target['gps_start']}.json"
            )
            if _json(event_path.read_bytes()) != event:
                raise InitialEvidenceError("PEM retained event/grouped ledger changed")
            pem._verify_event(
                event,
                target=target,
                run_dir=directory,
                contract=contract,
                exclusion_digest=preflight["candidate_exclusion_digest"],
            )
        counts = Counter(event["verdict_tier"] for event in events)
        if len(events) != contract["population"][bucket]["total"]:
            raise InitialEvidenceError("PEM separate population total changed")
        event_summary[bucket] = {
            "total": len(events),
            "calibrated": len(events) - counts["UNCALIBRATED"],
            "uncalibrated": counts["UNCALIBRATED"],
            "verdict_tier": dict(sorted(counts.items())),
        }
    if seen != set(by_key):
        raise InitialEvidenceError("PEM event accounting incomplete")
    body = {
        "schema_version": 1,
        "status": "PASS_COMPLETE_O3A_NATIVE_PEM_V1",
        "run_key": key,
        "contract_digest": contract["contract_digest"],
        "preflight_digest": preflight["preflight_digest"],
        "target_digest": preflight["target_digest"],
        "candidate_exclusion_digest": preflight["candidate_exclusion_digest"],
        "event_summary": event_summary,
        "outputs": specs,
        "transient_raw_purged": True,
        "scientific_boundary": contract["scientific_boundary"],
    }
    if summary != {**body, "artifact_digest": canonical_json_sha256(body)}:
        raise InitialEvidenceError("PEM full summary replay changed")
    body = {
        "status": "PASS_VERIFIED_O3A_NATIVE_PEM_V1",
        "run_key": key,
        "contract_digest": contract["contract_digest"],
        "run_artifact_digest": summary["artifact_digest"],
        "event_summary": event_summary,
        "scientific_boundary": contract["scientific_boundary"],
    }
    if _json((root / pem.COMPACT_REL).read_bytes()) != {
        **body,
        "artifact_digest": canonical_json_sha256(body),
    }:
        raise InitialEvidenceError("PEM original verified compact replay changed")
    return contract, summary, directory


def verify_pem_evidence(
    *,
    snapshot_bytes,
    expected_snapshot_sha256,
    expected_plan_sha256,
    root,
    pem_external_root,
    coincidence_external_root,
    taxonomy_external_root,
    classification_external_root,
    threshold_external_root,
    rescore_external_root,
    calibration_external_root,
    index_external_root,
    cohort_external_root,
    primary_external_root,
    allow_retained_driver_drift=False,
):
    from src.dante_light import o3a_native_pem as pem
    from src.dante_light.contracts import canonical_json_sha256

    parents.decisions._fcntl()
    root = root.resolve()
    evidence = new_evidence(
        root, allow_retained_driver_drift=allow_retained_driver_drift
    )
    before = _sources(root)
    policy = evidence.read("snapshot_policy", _existing(root, snapshots.POLICY_REL))
    view = snapshots.admit_snapshot(
        snapshot_bytes,
        expected_sha256=expected_snapshot_sha256,
        expected_plan_sha256=expected_plan_sha256,
        policy_bytes=policy,
    )
    files = _SnapshotFiles(view)
    parent_arguments = {
        "external_root": rescore_external_root.resolve(),
        **{
            name + "_external_root": value.resolve()
            for name, value in (
                ("calibration", calibration_external_root),
                ("index", index_external_root),
                ("cohort", cohort_external_root),
                ("primary", primary_external_root),
            )
        },
    }
    with ExitStack() as stack:
        _, coin_directory = parents._coincidence_gate(
            root=root,
            external_root=coincidence_external_root.resolve(),
            taxonomy_external_root=taxonomy_external_root.resolve(),
            classification_external_root=classification_external_root.resolve(),
            threshold_external_root=threshold_external_root.resolve(),
            parent_arguments=parent_arguments,
            evidence=evidence,
            stack=stack,
        )
        # Every archived repository byte is checked against current installed
        # source/contract/compact evidence. No archived implementation executes.
        for namespace, relative in files.locations:
            if namespace == "repository":
                payload = view.read(files.locations[(namespace, relative)])
                if (
                    evidence.read(
                        "pem_repository:" + relative,
                        _existing(root, relative),
                        hashlib.sha256(payload).hexdigest(),
                    )
                    != payload
                ):
                    raise InitialEvidenceError(
                        "PEM snapshot repository binding changed"
                    )
        for relative, digest in before.items():
            if hashlib.sha256(files.read("repository", relative)).hexdigest() != digest:
                raise InitialEvidenceError(
                    "PEM snapshot executed source binding changed"
                )
        virtual_root = _SnapshotPath(files, "repository")
        contract = pem.load_contract(root=virtual_root)
        coin = _json(
            (virtual_root / contract["parents"]["coincidence"]["path"]).read_bytes()
        )
        classified = _json(
            (virtual_root / contract["parents"]["classification"]["path"]).read_bytes()
        )
        expected_parents = {
            (
                f"native_coincidence_{coin['run_key']}/{coin['outputs'][bucket]['filename']}"
            ): coin_directory / coin["outputs"][bucket]["filename"]
            for bucket in ("primary", "diagnostic")
        }
        class_name = f"native_classification_{classified['run_key']}"
        expected_parents[class_name + "/native_classified_candidates.jsonl"] = (
            classification_external_root.resolve()
            / class_name
            / "native_classified_candidates.jsonl"
        )
        if {
            relative
            for namespace, relative in files.locations
            if namespace == "parents"
        } != set(expected_parents):
            raise InitialEvidenceError("PEM snapshot parent ledger closure changed")
        for relative, path in expected_parents.items():
            payload = files.read("parents", relative)
            if (
                evidence.read(
                    "pem_parent:" + relative, path, hashlib.sha256(payload).hexdigest()
                )
                != payload
            ):
                raise InitialEvidenceError("PEM snapshot parent ledger binding changed")
        preflight, _, _ = pem.preflight_inputs(
            root=virtual_root, external_root=_SnapshotPath(files, "parents")
        )
        directory_name = contract["output"]["prefix"] + pem._run_key(
            contract, preflight
        )
        snapshots._name(directory_name)
        if "/" in directory_name:
            raise InitialEvidenceError("PEM run directory must be a single name")
        live_directory = pem_external_root.resolve() / directory_name
        _guards(live_directory)
        contract, summary, _ = _retained_gate(files)
        files.complete()
        evidence.unchanged()
        _guards(live_directory)
        parents._empty_cache(coin_directory)
        for name in (
            "scan_summary",
            "cohort_summary",
            "index_summary",
            "calibration_summary",
            "rescore_summary",
        ):
            if name in evidence.inputs:
                clean_native_parent(
                    Path(evidence.inputs[name]["path"]).parent, stack=stack
                )
        for reference in evidence.inputs.values():
            if reference["path"].endswith(".sqlite"):
                parents.decisions.scores.parents._no_journals(Path(reference["path"]))
        if _sources(root) != before:
            raise InitialEvidenceError("PEM helper sources changed during verification")
        body = {
            "schema_version": 1,
            "status": "PASS_O3A_READ_ONLY_PEM_SNAPSHOT_RETAINED_DECISIONS_ONLY",
            "observing_run": "O3a",
            "stage": "pem",
            "legacy_artifact_digest": summary["artifact_digest"],
            "contract_digest": contract["contract_digest"],
            "snapshot_receipt": view.receipt(),
            "source_bindings": before,
            "inputs": evidence.inputs,
            "pem_measurement_evidence_from_snapshot": True,
            "retained_pem_decisions_replayed": True,
            "actual_read_only_coincidence_parent_executed": True,
            "live_pem_guard_observations_only": True,
            "live_pem_output_bytes_checked": False,
            "pem_writer_exclusion_verified": False,
            "global_upstream_quiescence_verified": False,
            "atomic_historical_capture_verified": False,
            "fresh_sensor_coherence_replayed": False,
            "fresh_null_calibration_replayed": False,
            "source_fetch_executed": False,
            "historical_evidence_mutated": False,
            "full_workflow_verified": False,
            **receipt_fields(evidence),
        }
        return {**body, "receipt_digest": canonical_json_sha256(body)}

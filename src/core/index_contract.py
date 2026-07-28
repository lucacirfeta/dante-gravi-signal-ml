"""Scientific representation contract for DANTE reference indices.

The Q-transform range is part of the statistical representation, not an
implementation detail. An index and every query calibrated against it must
therefore carry an explicit, machine-readable Q-range contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

LEGACY_NATIVE_QRANGE = (4, 32)


def normalize_qrange(value) -> tuple[int, int]:
    """Validate and normalize a two-element Q-transform range."""
    if value is None or len(value) != 2:
        raise ValueError("qrange must contain exactly Q_MIN and Q_MAX")
    q_min, q_max = int(value[0]), int(value[1])
    if q_min <= 0 or q_max <= q_min:
        raise ValueError(f"Invalid qrange {(q_min, q_max)}")
    return q_min, q_max


def qrange_tag(qrange) -> str:
    """Filesystem-safe representation tag, e.g. ``q4-64``."""
    q_min, q_max = normalize_qrange(qrange)
    return f"q{q_min}-{q_max}"


def _decode_meta(raw: Any) -> dict:
    if isinstance(raw, np.ndarray):
        raw = raw.item()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError(f"Index meta must decode to a dict, got {type(raw)!r}")
    return raw


def read_index_metadata(path: str | Path) -> dict:
    """Read the JSON metadata embedded in an NPZ reference index."""
    path = Path(path)
    with np.load(path, allow_pickle=False) as data:
        if "meta" not in data.files:
            return {}
        return _decode_meta(data["meta"])


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class IndexContract:
    path: Path
    qrange: tuple[int, int]
    metadata: dict
    sha256: str
    declared: bool
    legacy_inferred: bool

    @property
    def tag(self) -> str:
        return qrange_tag(self.qrange)


def taxonomy_representation(
    index_qrange,
    query_qrange=None,
) -> str:
    """Version tag shared by a DSD index, taxonomy, scores, and analyses."""
    index_qrange = normalize_qrange(index_qrange)
    query_qrange = normalize_qrange(
        index_qrange if query_qrange is None else query_qrange
    )
    return (
        f"idx{qrange_tag(index_qrange)}_"
        f"query{qrange_tag(query_qrange)}"
    )


def _resolve_recorded_path(value: str | Path) -> Path:
    """Resolve artifact paths written on either Windows or WSL.

    Scientific JSONs are shared across the Windows host and WSL.  A relative
    path persisted with Windows backslashes must not become a different literal
    filename when the same audit is consumed on Linux.
    """
    text = str(value).replace("\\", "/")
    path = Path(text)
    if path.is_absolute():
        return path.resolve()
    if (
        len(text) >= 3
        and text[1] == ":"
        and text[2] == "/"
    ):
        # POSIX Path does not recognize a Windows drive as absolute. Under WSL
        # the stable translation is /mnt/<drive>/<rest>.
        path = Path("/mnt") / text[0].lower() / text[3:]
        return path.resolve()
    return (Path.cwd() / path).resolve()


@dataclass(frozen=True)
class TaxonomyContract:
    """Resolved DSD taxonomy and the exact columns safe for scientific use."""

    path: Path
    run_name: str
    representation: str
    class_column: str
    score_column: str
    audit_path: Path | None
    audit: dict
    legacy: bool

    @property
    def cache_tag(self) -> str:
        return self.representation


def load_taxonomy_contract(
    aggregated_dir: str | Path,
    run_name: str,
    *,
    index_qrange=None,
    query_qrange=None,
    taxonomy_path: str | Path | None = None,
    allow_legacy: bool = False,
    require_complete_audit: bool = True,
) -> TaxonomyContract:
    """Resolve a taxonomy without silently using legacy DSD classes.

    The historical ``robustness_class`` and ``native_o4a_score`` columns were
    produced in a Q32-index/Q64-query score space. They remain available only
    through the explicit ``allow_legacy`` audit escape hatch. Normal scientific
    consumers must load the representation-versioned taxonomy and its matching
    DSD transition audit.
    """
    aggregated_dir = Path(aggregated_dir)
    if index_qrange is None:
        from src.core.utils import load_config

        index_qrange = tuple(
            int(value)
            for value in load_config()["preprocessing"]["qrange"]
        )
    index_qrange = normalize_qrange(index_qrange)
    query_qrange = normalize_qrange(
        index_qrange if query_qrange is None else query_qrange
    )
    representation = taxonomy_representation(index_qrange, query_qrange)
    variant_column = representation.replace("-", "_")
    class_column = f"robustness_class_{variant_column}"
    score_column = f"native_score_{variant_column}"
    expected_path = aggregated_dir / (
        f"Master_Taxonomy_{run_name}_{representation}.csv"
    )
    path = Path(taxonomy_path) if taxonomy_path is not None else expected_path

    if not path.exists():
        if not allow_legacy:
            raise RuntimeError(
                "Coherent DSD taxonomy is missing. Refusing legacy "
                f"robustness classes: {path}"
            )
        legacy_path = (
            Path(taxonomy_path)
            if taxonomy_path is not None
            else aggregated_dir / f"Master_Taxonomy_{run_name}.csv"
        )
        if not legacy_path.exists():
            raise FileNotFoundError(legacy_path)
        return TaxonomyContract(
            path=legacy_path,
            run_name=run_name,
            representation="legacy_idxq4-32_queryq4-64",
            class_column="robustness_class",
            score_column="native_o4a_score",
            audit_path=None,
            audit={},
            legacy=True,
        )

    audit_path = aggregated_dir / (
        f"dsd_transition_audit_{run_name.lower()}_{representation}.json"
    )
    audit = {}
    if require_complete_audit:
        if not audit_path.exists():
            raise RuntimeError(
                f"Matching DSD transition audit is missing: {audit_path}"
            )
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        rep = audit.get("representation", {})
        if (
            not audit.get("experiment_run")
            or not rep.get("coherent")
            or rep.get("variant") != representation
        ):
            raise RuntimeError(
                f"DSD audit does not certify coherent {representation}"
            )
        if int(audit.get("total_failed", -1)) != 0:
            raise RuntimeError(
                "DSD audit contains failed candidate evaluations; refusing "
                "an incomplete scientific population"
            )
        artifact = audit.get("taxonomy_artifact")
        if artifact and _resolve_recorded_path(artifact) != path.resolve():
            raise RuntimeError(
                "DSD audit taxonomy artifact does not match the requested "
                f"file: {artifact} != {path}"
            )

    return TaxonomyContract(
        path=path,
        run_name=run_name,
        representation=representation,
        class_column=class_column,
        score_column=score_column,
        audit_path=audit_path if require_complete_audit else None,
        audit=audit,
        legacy=False,
    )


def load_taxonomy_view(
    aggregated_dir: str | Path,
    run_name: str,
    **contract_kwargs,
):
    """Load a validated taxonomy with representation-neutral DSD aliases."""
    import pandas as pd

    contract = load_taxonomy_contract(
        aggregated_dir,
        run_name,
        **contract_kwargs,
    )
    frame = pd.read_csv(contract.path)
    missing = {
        contract.class_column,
        contract.score_column,
        "gps_start",
        "detector",
    }.difference(frame.columns)
    if missing:
        raise RuntimeError(
            f"Taxonomy {contract.path} lacks columns: {sorted(missing)}"
        )
    frame = frame.copy()
    frame["dsd_class"] = frame[contract.class_column].astype(str)
    frame["dsd_score"] = pd.to_numeric(
        frame[contract.score_column],
        errors="coerce",
    )
    if frame["dsd_class"].eq("NOT_EVALUATED").any():
        raise RuntimeError(
            f"Taxonomy {contract.path} contains NOT_EVALUATED candidates"
        )
    if not np.isfinite(frame["dsd_score"].to_numpy(dtype=float)).all():
        raise RuntimeError(
            f"Taxonomy {contract.path} contains non-finite DSD scores"
        )
    if contract.audit:
        expected = int(contract.audit.get("total_evaluated", -1))
        if expected != len(frame):
            raise RuntimeError(
                f"Taxonomy rows {len(frame)} != audited evaluations {expected}"
            )
    return frame, contract


def load_index_contract(
    path: str | Path,
    *,
    allow_legacy_inference: bool = False,
) -> IndexContract:
    """Load an index contract, refusing silent representation inference.

    Historical native indices predate the contract and are known from the
    frozen builder history to use Q=[4,32]. They may be opened only through
    the explicit ``allow_legacy_inference`` escape hatch, which is recorded in
    the returned contract.
    """
    path = Path(path)
    metadata = read_index_metadata(path)
    declared = "qrange" in metadata
    legacy_inferred = False
    if declared:
        qrange = normalize_qrange(metadata["qrange"])
    elif allow_legacy_inference:
        qrange = LEGACY_NATIVE_QRANGE
        legacy_inferred = True
    else:
        raise RuntimeError(
            f"{path} has no qrange contract. Refusing a silent Q32/Q64 "
            "cross-representation comparison. Rebuild a versioned index or "
            "enable the explicit legacy audit mode."
        )
    return IndexContract(
        path=path,
        qrange=qrange,
        metadata=metadata,
        sha256=sha256_file(path),
        declared=declared,
        legacy_inferred=legacy_inferred,
    )


def validate_native_index(
    path: str | Path,
    *,
    expected_qrange: tuple[int, int],
    expected_k: int,
    expected_detector: str = "both",
) -> dict:
    """Validate a versioned native index before scientific scoring."""
    contract = load_index_contract(path)
    expected_qrange = normalize_qrange(expected_qrange)
    if contract.qrange != expected_qrange:
        raise RuntimeError(
            f"Index qrange {contract.qrange} != expected {expected_qrange}"
        )

    with np.load(contract.path, allow_pickle=False) as data:
        required = {"embeddings", "labels", "meta"}
        missing = required.difference(data.files)
        if missing:
            raise RuntimeError(f"Index lacks required arrays: {sorted(missing)}")
        embeddings = np.asarray(data["embeddings"], dtype=np.float64)
        labels = np.asarray(data["labels"])
        raw = (
            np.asarray(data["raw_embeddings_sample"], dtype=np.float64)
            if "raw_embeddings_sample" in data.files
            else np.empty((0, embeddings.shape[1] if embeddings.ndim == 2 else 0))
        )

    if embeddings.shape != (int(expected_k), 384):
        raise RuntimeError(
            f"Index embeddings shape {embeddings.shape} != "
            f"({expected_k}, 384)"
        )
    if labels.shape[0] != expected_k:
        raise RuntimeError(
            f"Index labels length {labels.shape[0]} != K={expected_k}"
        )
    if not np.isfinite(embeddings).all():
        raise RuntimeError("Index embeddings contain non-finite values")
    norms = np.linalg.norm(embeddings, axis=1)
    max_norm_error = float(np.max(np.abs(norms - 1.0)))
    if max_norm_error > 1e-4:
        raise RuntimeError(
            f"Index centroids are not L2-normalized; max error "
            f"{max_norm_error:.3g}"
        )

    metadata = contract.metadata
    if int(metadata.get("K", -1)) != expected_k:
        raise RuntimeError(
            f"Index metadata K={metadata.get('K')} != {expected_k}"
        )
    if str(metadata.get("detector")) != expected_detector:
        raise RuntimeError(
            f"Index detector={metadata.get('detector')!r} != "
            f"{expected_detector!r}"
        )
    n_segments = int(metadata.get("n_segments", 0))
    if n_segments < 1:
        raise RuntimeError("Index metadata has no positive n_segments")

    if raw.size:
        if raw.ndim != 2 or raw.shape[1] != 384:
            raise RuntimeError(
                f"Raw embedding sample has invalid shape {raw.shape}"
            )
        if not np.isfinite(raw).all():
            raise RuntimeError("Raw embedding sample contains non-finite values")
        raw_norm_error = float(
            np.max(np.abs(np.linalg.norm(raw, axis=1) - 1.0))
        )
        if raw_norm_error > 1e-4:
            raise RuntimeError(
                "Raw embedding sample is not L2-normalized; max error "
                f"{raw_norm_error:.3g}"
            )
    else:
        raw_norm_error = None

    times_path = contract.path.with_suffix(".t_bg.json")
    if not times_path.exists():
        raise RuntimeError(f"Index background-time sidecar missing: {times_path}")
    used_times = json.loads(times_path.read_text(encoding="utf-8"))
    if not isinstance(used_times, list) or len(used_times) != n_segments:
        raise RuntimeError(
            f"Background-time sidecar length "
            f"{len(used_times) if isinstance(used_times, list) else 'invalid'} "
            f"!= n_segments={n_segments}"
        )

    return {
        "path": str(contract.path),
        "sha256": contract.sha256,
        "qrange": list(contract.qrange),
        "K": int(expected_k),
        "embedding_dimension": 384,
        "n_segments": n_segments,
        "n_raw_embeddings": int(raw.shape[0]),
        "max_centroid_norm_error": max_norm_error,
        "max_raw_norm_error": raw_norm_error,
        "background_times_path": str(times_path),
    }

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

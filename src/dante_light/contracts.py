"""Schema-v1 scientific contracts for the opt-in DANTE-Light path.

Light is a triage layer.  Its vocabulary deliberately excludes the offline
``ROBUST``, ``AMBIGUOUS`` and ``BACKGROUND`` classes.  Invalid or incomplete
inputs produce a scoreless ``DEFER`` record rather than a numerical result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA_VERSION = 1
_DETECTOR_RE = re.compile(r"^[A-Z][0-9]$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised when an object would violate a DANTE-Light contract."""


class LightDisposition(str, Enum):
    ESCALATE = "ESCALATE"
    AUDIT_SAMPLE = "AUDIT_SAMPLE"
    NOT_ESCALATED = "NOT_ESCALATED"
    DEFER = "DEFER"


class FailClosedReason(str, Enum):
    MISSING_CAT1 = "MISSING_CAT1"
    INCOMPLETE_DATA = "INCOMPLETE_DATA"
    STALE_INDEX = "STALE_INDEX"
    UNKNOWN_REPRESENTATION = "UNKNOWN_REPRESENTATION"
    MISSING_CALIBRATION = "MISSING_CALIBRATION"
    NON_CAUSAL_EPOCH = "NON_CAUSAL_EPOCH"
    CALIBRATION_LOOKAHEAD = "CALIBRATION_LOOKAHEAD"
    DETECTOR_MISMATCH = "DETECTOR_MISMATCH"
    RUN_MISMATCH = "RUN_MISMATCH"
    NONFINITE_INPUT = "NONFINITE_INPUT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def _finite_positive(value: float, name: str, *, allow_zero: bool = False) -> float:
    value = float(value)
    lower_ok = value >= 0.0 if allow_zero else value > 0.0
    if not math.isfinite(value) or not lower_ok:
        relation = "non-negative" if allow_zero else "positive"
        raise ContractError(f"{name} must be finite and {relation}: {value!r}")
    return value


def _sha256(value: str, name: str) -> str:
    normalized = str(value).lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ContractError(f"{name} must be a lowercase SHA256 digest")
    return normalized


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class WindowIdentity:
    run: str
    detector: str
    gps_start: float
    duration_s: float = 32.0
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        run = str(self.run).strip().upper()
        detector = str(self.detector).strip().upper()
        if not run or not re.fullmatch(r"^[A-Z][A-Z0-9]*$", run):
            raise ContractError(f"invalid observing-run identifier: {self.run!r}")
        if not _DETECTOR_RE.fullmatch(detector):
            raise ContractError(f"invalid detector identifier: {self.detector!r}")
        if int(self.schema_version) != SCHEMA_VERSION:
            raise ContractError(
                f"unsupported window schema {self.schema_version}; expected {SCHEMA_VERSION}"
            )
        object.__setattr__(self, "run", run)
        object.__setattr__(self, "detector", detector)
        object.__setattr__(
            self, "gps_start", _finite_positive(self.gps_start, "gps_start", allow_zero=True)
        )
        object.__setattr__(
            self, "duration_s", _finite_positive(self.duration_s, "duration_s")
        )

    @property
    def window_id(self) -> str:
        # ``float.hex`` preserves the exact IEEE-754 identity across JSON
        # formatting choices while the public representation remains numeric.
        identity = {
            "schema_version": self.schema_version,
            "run": self.run,
            "detector": self.detector,
            "gps_start_hex": self.gps_start.hex(),
            "duration_s_hex": self.duration_s.hex(),
        }
        return f"dlw1-{canonical_json_sha256(identity)[:24]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "window_id": self.window_id,
            "run": self.run,
            "detector": self.detector,
            "gps_start": self.gps_start,
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WindowIdentity":
        identity = cls(
            run=str(value["run"]),
            detector=str(value["detector"]),
            gps_start=float(value["gps_start"]),
            duration_s=float(value["duration_s"]),
            schema_version=int(value.get("schema_version", SCHEMA_VERSION)),
        )
        declared = value.get("window_id")
        if declared is not None and declared != identity.window_id:
            raise ContractError(
                f"window_id mismatch: {declared!r} != {identity.window_id!r}"
            )
        return identity


@dataclass(frozen=True, slots=True)
class RepresentationContract:
    variant: str
    sample_rate_hz: int
    analysis_duration_s: float
    whitening_pad_s: float
    query_qrange: tuple[int, int]
    frequency_range_hz: tuple[int, int]
    image_shape: tuple[int, int, int]
    colormap: str
    encoder_input_size: tuple[int, int]
    top_k: int
    model_artifact_id: str
    model_revision: str
    model_source_sha256: str
    weights_sha256: str
    primary_index_sha256: str
    native_index_sha256: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError(f"unsupported representation schema {self.schema_version}")
        if not self.variant or not re.fullmatch(r"^[a-z0-9_-]+$", self.variant):
            raise ContractError(f"invalid representation variant: {self.variant!r}")
        qmin, qmax = (int(value) for value in self.query_qrange)
        if qmin <= 0 or qmax <= qmin:
            raise ContractError(f"invalid Q range: {self.query_qrange!r}")
        fmin, fmax = (int(value) for value in self.frequency_range_hz)
        if fmin <= 0 or fmax <= fmin:
            raise ContractError(f"invalid frequency range: {self.frequency_range_hz!r}")
        if int(self.sample_rate_hz) != 4096:
            raise ContractError("DANTE-Light schema 1 requires 4096 Hz strain")
        if float(self.analysis_duration_s) != 32.0:
            raise ContractError("DANTE-Light schema 1 requires 32 s analysis windows")
        if float(self.whitening_pad_s) != 4.0:
            raise ContractError("DANTE-Light schema 1 requires 4 s whitening padding")
        if tuple(int(value) for value in self.image_shape) != (256, 256, 3):
            raise ContractError(
                "DANTE-Light schema 1 permits only canonical 256x256x3 images"
            )
        if self.colormap != "cividis":
            raise ContractError("DANTE-Light schema 1 permits only cividis rendering")
        if tuple(int(value) for value in self.encoder_input_size) != (518, 518):
            raise ContractError("DANTE-Light schema 1 requires 518x518 DINO input")
        if int(self.top_k) != 68:
            raise ContractError("DANTE-Light schema 1 requires exact Top-68 pooling")
        if not re.fullmatch(r"^[0-9a-f]{40}$", self.model_revision):
            raise ContractError("model_revision must be a full 40-character Git SHA")
        for name in (
            "model_source_sha256",
            "weights_sha256",
            "primary_index_sha256",
            "native_index_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(self, "query_qrange", (qmin, qmax))
        object.__setattr__(self, "frequency_range_hz", (fmin, fmax))
        object.__setattr__(self, "sample_rate_hz", int(self.sample_rate_hz))
        object.__setattr__(self, "analysis_duration_s", float(self.analysis_duration_s))
        object.__setattr__(self, "whitening_pad_s", float(self.whitening_pad_s))
        object.__setattr__(
            self, "image_shape", tuple(int(value) for value in self.image_shape)
        )
        object.__setattr__(
            self,
            "encoder_input_size",
            tuple(int(value) for value in self.encoder_input_size),
        )
        object.__setattr__(self, "top_k", int(self.top_k))

    @property
    def contract_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "variant": self.variant,
            "sample_rate_hz": self.sample_rate_hz,
            "analysis_duration_s": self.analysis_duration_s,
            "whitening_pad_s": self.whitening_pad_s,
            "query_qrange": list(self.query_qrange),
            "frequency_range_hz": list(self.frequency_range_hz),
            "image_shape": list(self.image_shape),
            "colormap": self.colormap,
            "encoder_input_size": list(self.encoder_input_size),
            "top_k": self.top_k,
            "model_artifact_id": self.model_artifact_id,
            "model_revision": self.model_revision,
            "model_source_sha256": self.model_source_sha256,
            "weights_sha256": self.weights_sha256,
            "primary_index_sha256": self.primary_index_sha256,
            "native_index_sha256": self.native_index_sha256,
        }
        if include_digest:
            value["contract_sha256"] = self.contract_sha256
        return value

    @classmethod
    def from_reference_manifest(
        cls, manifest_path: str | Path = "config/reference_artifacts.json"
    ) -> "RepresentationContract":
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        model = payload["models"]["dinov2_vits14_reg"]
        primary = payload["reference_indices"]["o3b_production_k275"]
        native = payload["reference_indices"]["o4a_native_q4_64_k1216"]
        return cls(
            variant="idxq4-64_queryq4-64",
            sample_rate_hz=4096,
            analysis_duration_s=32.0,
            whitening_pad_s=4.0,
            query_qrange=(4, 64),
            frequency_range_hz=(20, 2048),
            image_shape=(256, 256, 3),
            colormap="cividis",
            encoder_input_size=(518, 518),
            top_k=68,
            model_artifact_id="dinov2_vits14_reg",
            model_revision=model["revision"],
            model_source_sha256=model["source_python_tree_sha256"],
            weights_sha256=model["weights_sha256"],
            primary_index_sha256=primary["sha256"],
            native_index_sha256=native["sha256"],
        )


@dataclass(frozen=True, slots=True)
class CalibrationEpochContract:
    epoch_id: str
    run: str
    detector: str
    cutoff_gps: float
    threshold: float
    threshold_artifact_sha256: str
    native_index_sha256: str
    causal: bool
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError(f"unsupported epoch schema {self.schema_version}")
        if not re.fullmatch(r"^[a-z0-9][a-z0-9_.-]*$", self.epoch_id):
            raise ContractError(f"invalid epoch_id: {self.epoch_id!r}")
        window = WindowIdentity(
            run=self.run,
            detector=self.detector,
            gps_start=self.cutoff_gps,
            duration_s=1.0,
        )
        object.__setattr__(self, "run", window.run)
        object.__setattr__(self, "detector", window.detector)
        object.__setattr__(self, "cutoff_gps", window.gps_start)
        object.__setattr__(
            self, "threshold", _finite_positive(self.threshold, "threshold", allow_zero=True)
        )
        object.__setattr__(
            self,
            "threshold_artifact_sha256",
            _sha256(self.threshold_artifact_sha256, "threshold_artifact_sha256"),
        )
        object.__setattr__(
            self,
            "native_index_sha256",
            _sha256(self.native_index_sha256, "native_index_sha256"),
        )

    def incompatibility(
        self,
        window: WindowIdentity,
        representation: RepresentationContract,
        *,
        prospective: bool,
    ) -> FailClosedReason | None:
        if window.run != self.run:
            return FailClosedReason.RUN_MISMATCH
        if window.detector != self.detector:
            return FailClosedReason.DETECTOR_MISMATCH
        if representation.native_index_sha256 != self.native_index_sha256:
            return FailClosedReason.STALE_INDEX
        if prospective and not self.causal:
            return FailClosedReason.NON_CAUSAL_EPOCH
        if prospective and window.gps_start <= self.cutoff_gps:
            return FailClosedReason.CALIBRATION_LOOKAHEAD
        return None


@dataclass(frozen=True, slots=True)
class PreflightState:
    cat1: bool
    data_complete: bool
    index_integrity: bool
    representation_supported: bool
    dependency_available: bool = True


def evaluate_preflight(state: PreflightState) -> FailClosedReason | None:
    """Return the first deterministic fail-closed reason, or ``None``."""
    ordered = (
        (state.cat1, FailClosedReason.MISSING_CAT1),
        (state.data_complete, FailClosedReason.INCOMPLETE_DATA),
        (state.index_integrity, FailClosedReason.STALE_INDEX),
        (
            state.representation_supported,
            FailClosedReason.UNKNOWN_REPRESENTATION,
        ),
        (state.dependency_available, FailClosedReason.DEPENDENCY_UNAVAILABLE),
    )
    return next((reason for passed, reason in ordered if not passed), None)


@dataclass(frozen=True, slots=True)
class LightRecord:
    window: WindowIdentity
    representation_sha256: str
    disposition: LightDisposition
    epoch_id: str | None = None
    scores: tuple[tuple[str, float], ...] = field(default_factory=tuple)
    defer_reason: FailClosedReason | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError(f"unsupported record schema {self.schema_version}")
        object.__setattr__(
            self,
            "representation_sha256",
            _sha256(self.representation_sha256, "representation_sha256"),
        )
        disposition = LightDisposition(self.disposition)
        object.__setattr__(self, "disposition", disposition)
        reason = (
            None if self.defer_reason is None else FailClosedReason(self.defer_reason)
        )
        object.__setattr__(self, "defer_reason", reason)
        names: set[str] = set()
        normalized_scores: list[tuple[str, float]] = []
        for name, raw in self.scores:
            if not name or name in names:
                raise ContractError(f"invalid or duplicate score name: {name!r}")
            value = float(raw)
            if not math.isfinite(value):
                raise ContractError(f"score {name!r} is non-finite")
            names.add(name)
            normalized_scores.append((str(name), value))
        normalized_scores.sort()
        object.__setattr__(self, "scores", tuple(normalized_scores))

        if disposition is LightDisposition.DEFER:
            if reason is None:
                raise ContractError("DEFER requires an explicit fail-closed reason")
            if normalized_scores:
                raise ContractError("DEFER records must not contain scores")
        elif reason is not None:
            raise ContractError("non-DEFER records must not contain a defer reason")

    @classmethod
    def deferred(
        cls,
        window: WindowIdentity,
        representation: RepresentationContract,
        reason: FailClosedReason,
        *,
        epoch_id: str | None = None,
    ) -> "LightRecord":
        return cls(
            window=window,
            representation_sha256=representation.contract_sha256,
            disposition=LightDisposition.DEFER,
            epoch_id=epoch_id,
            defer_reason=reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "window": self.window.to_dict(),
            "representation_sha256": self.representation_sha256,
            "epoch_id": self.epoch_id,
            "disposition": self.disposition.value,
            "scores": dict(self.scores),
            "defer_reason": (
                None if self.defer_reason is None else self.defer_reason.value
            ),
        }

"""Transport-neutral strain packet and exact window assembly contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

import numpy as np

from src.dante_light.contracts import ContractError, FailClosedReason, WindowIdentity
from src.dante_light.executor import DeferredWindow


@dataclass(frozen=True, slots=True)
class StrainPacket:
    run: str
    detector: str
    gps_start: int
    sample_rate_hz: int
    samples: np.ndarray
    calibrated: bool
    cat1: bool

    def __post_init__(self) -> None:
        identity = WindowIdentity(
            self.run, self.detector, float(self.gps_start), duration_s=1.0
        )
        object.__setattr__(self, "run", identity.run)
        object.__setattr__(self, "detector", identity.detector)
        if self.sample_rate_hz != 4096:
            raise ContractError("DANTE-Light packets require 4096 Hz")
        values = np.asarray(self.samples, dtype=np.float64)
        if values.shape != (self.sample_rate_hz,):
            raise ContractError("each packet must contain exactly one second")
        if not np.all(np.isfinite(values)):
            raise ContractError("packet contains non-finite strain")
        frozen = np.ascontiguousarray(values)
        frozen.setflags(write=False)
        object.__setattr__(self, "samples", frozen)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.samples.tobytes()).hexdigest()


class WindowAssembler:
    """Accept reordered packets, reject divergent duplicates, never fill gaps."""

    def __init__(self, *, max_packets: int = 256):
        if max_packets <= 0:
            raise ValueError("max_packets must be positive")
        self.max_packets = max_packets
        self._packets: dict[tuple[str, str, int], StrainPacket] = {}

    def add(self, packet: StrainPacket) -> None:
        key = (packet.run, packet.detector, packet.gps_start)
        previous = self._packets.get(key)
        if previous is not None:
            if (
                previous.sha256 != packet.sha256
                or previous.calibrated != packet.calibrated
                or previous.cat1 != packet.cat1
            ):
                raise ContractError("divergent duplicate strain packet")
            return
        if len(self._packets) >= self.max_packets:
            raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
        self._packets[key] = packet

    def assemble(self, window: WindowIdentity) -> np.ndarray:
        if not float(window.gps_start).is_integer() or not float(
            window.duration_s
        ).is_integer():
            raise ContractError("packet assembly requires integer-second windows")
        seconds = range(
            int(window.gps_start), int(window.gps_start + window.duration_s)
        )
        packets = [
            self._packets.get((window.run, window.detector, second))
            for second in seconds
        ]
        if any(packet is None for packet in packets):
            raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
        complete = [packet for packet in packets if packet is not None]
        if not all(packet.calibrated for packet in complete):
            raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
        if not all(packet.cat1 for packet in complete):
            raise DeferredWindow(FailClosedReason.MISSING_CAT1)
        return np.concatenate([packet.samples for packet in complete])

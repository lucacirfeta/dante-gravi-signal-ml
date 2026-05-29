"""Structured logging utilities for gravi-signal-ml.

Provides JSON Lines formatting, PhaseTracker for timing and metrics,
and contextual loggers.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any


class StructuredFormatter(logging.Formatter):
    """JSON Lines formatter for structured logging.
    
    Produces one JSON object per log line, injecting UTC timestamp,
    level, message, and any extra context parameters attached to the record.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage()
        }
        
        # Add context metadata if present in record
        for key in ["session_id", "run", "detector", "phase", "gps_start", "gps_end", "n_processed", "n_total", "elapsed_seconds"]:
            if hasattr(record, key):
                val = getattr(record, key)
                if val is not None:
                    log_obj[key] = val
                    
        return json.dumps(log_obj)


class PhaseTracker:
    """Tracks the start and end of a pipeline phase, logging quantitative data.
    
    Args:
        logger: The logging.Logger or LoggerAdapter instance to use.
        phase: Name of the phase (e.g. 'scan', 'encode').
        session_id: Session identifier.
        run: Observing run (e.g. 'O4a').
        detector: Detector identifier (e.g. 'H1').
    """
    
    def __init__(
        self,
        logger: logging.Logger | logging.LoggerAdapter,
        phase: str,
        session_id: str | None = None,
        run: str | None = None,
        detector: str | None = None,
    ) -> None:
        self.logger = logger
        self.phase = phase
        self.session_id = session_id
        self.run = run
        self.detector = detector
        self.start_time: float | None = None
        self.gps_start: int | None = None

    def _get_extra(self) -> dict[str, Any]:
        """Return the extra kwargs for contextual logging."""
        extra = {"phase": self.phase}
        if self.session_id:
            extra["session_id"] = self.session_id
        if self.run:
            extra["run"] = self.run
        if self.detector:
            extra["detector"] = self.detector
        if self.gps_start is not None:
            extra["gps_start"] = self.gps_start
        return extra

    def start(self, gps_start: int | None = None) -> None:
        """Mark the start of the phase.
        
        Args:
            gps_start: Optional starting GPS time for this phase.
        """
        self.start_time = time.time()
        self.gps_start = gps_start
        extra = self._get_extra()
        
        msg = f"Phase '{self.phase}' started."
        if gps_start is not None:
            msg += f" GPS start: {gps_start}"
            
        self.logger.info(msg, extra=extra)

    def end(self, gps_end: int | None = None, n_processed: int | None = None, n_total: int | None = None) -> None:
        """Mark the end of the phase and log summary metrics.
        
        Args:
            gps_end: Optional ending GPS time for this phase.
            n_processed: Number of elements processed.
            n_total: Total number of elements expected/available.
        """
        elapsed = time.time() - self.start_time if self.start_time else 0.0
        extra = self._get_extra()
        
        # Add end specific metrics to extra for JSON structure
        if gps_end is not None:
            extra["gps_end"] = gps_end
        if n_processed is not None:
            extra["n_processed"] = n_processed
        if n_total is not None:
            extra["n_total"] = n_total
        extra["elapsed_seconds"] = elapsed
            
        parts = [f"Phase '{self.phase}' completed in {elapsed:.1f}s."]
        
        if n_processed is not None:
            parts.append(f"Processed: {n_processed}")
            if n_total is not None:
                parts.append(f"/ {n_total}")
                
        if self.gps_start is not None and gps_end is not None:
            parts.append(f"GPS window: {self.gps_start} - {gps_end}")
            
        self.logger.info(" ".join(parts), extra=extra)


class ContextLoggerAdapter(logging.LoggerAdapter):
    """Adapter to automatically inject context parameters into log records."""
    def process(self, msg: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        if "extra" not in kwargs:
            kwargs["extra"] = {}
        # Merge self.extra into kwargs["extra"], prioritizing kwargs["extra"]
        for k, v in self.extra.items():
            if k not in kwargs["extra"] and v is not None:
                kwargs["extra"][k] = v
        return msg, kwargs


def get_phase_logger(
    name: str,
    session_id: str | None = None,
    run: str | None = None,
    detector: str | None = None,
    phase: str | None = None,
) -> logging.LoggerAdapter:
    """Get a logger wrapped with the standard pipeline context.
    
    Args:
        name: Logger name (e.g. __name__).
        session_id: Session identifier.
        run: Observing run.
        detector: Detector identifier.
        phase: Current pipeline phase name.
        
    Returns:
        A ContextLoggerAdapter that automatically injects the context metadata.
    """
    logger = logging.getLogger(name)
    extra = {}
    if session_id:
        extra["session_id"] = session_id
    if run:
        extra["run"] = run
    if detector:
        extra["detector"] = detector
    if phase:
        extra["phase"] = phase
        
    return ContextLoggerAdapter(logger, extra)

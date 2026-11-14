"""Application diagnostics written beside the project/executable as plain text.

The log records lifecycle, API timings, hardware/runtime facts and processing stages.
It deliberately never records request bodies, image pixels, OCR text, translations,
HTTP headers, or update tokens.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger("t4.diagnostics")
_LOCK = threading.Lock()
_CONFIGURED = False
_LOG_PATH: Path | None = None


def _primary_path() -> Path:
    override = os.environ.get("T4_LOG_FILE")
    if override:
        return Path(override).expanduser()
    # Packaged app: beside T4Translate.exe. Source/development: repository root.
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
        root = Path(__file__).resolve().parents[2]
    return root / "T4Translate-diagnostics.txt"


def _fallback_path() -> Path:
    data = os.environ.get("T4_DATA_DIR")
    root = Path(data).expanduser() if data else Path.home() / "T4Translate"
    return root / "T4Translate-diagnostics.txt"


def configure() -> Path | None:
    """Initialize UTF-8 rotating log; fall back to the writable app-data directory."""
    global _CONFIGURED, _LOG_PATH
    with _LOCK:
        if _CONFIGURED:
            return _LOG_PATH
        _CONFIGURED = True
        _LOGGER.setLevel(logging.INFO)
        _LOGGER.propagate = False
        candidates = [_primary_path(), _fallback_path()]
        seen: set[Path] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(
                    candidate, maxBytes=8 * 1024 * 1024, backupCount=4, encoding="utf-8"
                )
                handler.setFormatter(logging.Formatter(
                    "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
                ))
                _LOGGER.addHandler(handler)
                _LOG_PATH = candidate
                break
            except OSError:
                continue
        if _LOG_PATH is None:
            _LOGGER.addHandler(logging.NullHandler())
            return None

    log_event(
        "diagnostics.ready",
        file=str(_LOG_PATH),
        os=platform.platform(),
        python=sys.version.split()[0],
        executable=sys.executable,
        cwd=os.getcwd(),
        frozen=bool(getattr(sys, "frozen", False)),
    )
    return _LOG_PATH


def log_file() -> str | None:
    """Return the active log path (primary project/executable path or fallback)."""
    path = configure()
    return str(path) if path else None


def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Write one structured, UTF-8 line; callers must not pass user text or secrets."""
    configure()
    try:
        message = json.dumps({"event": event, **fields}, ensure_ascii=False, default=str)
    except Exception:  # pragma: no cover - final safeguard for diagnostics only
        message = json.dumps({"event": event, "fields": "<unserializable>"})
    _LOGGER.log(level, message)


def log_exception(event: str, **fields: Any) -> None:
    """Write structured failure context and traceback without interrupting the app."""
    configure()
    try:
        message = json.dumps({"event": event, **fields}, ensure_ascii=False, default=str)
    except Exception:  # pragma: no cover
        message = json.dumps({"event": event})
    _LOGGER.exception(message)


def system_metrics() -> dict[str, Any]:
    """Capture snapshot of process and system memory and CPU."""
    try:
        import psutil

        proc = psutil.Process()
        proc_mem = proc.memory_info()
        vm = psutil.virtual_memory()
        return {
            "processRssMb": round(proc_mem.rss / (1024 * 1024), 2),
            "processCpuPercent": proc.cpu_percent(interval=None),
            "systemAvailableRamMb": round(vm.available / (1024 * 1024), 2),
            "systemTotalRamMb": round(vm.total / (1024 * 1024), 2),
            "systemUsedRamPercent": vm.percent,
            "systemCpuPercent": psutil.cpu_percent(interval=None),
        }
    except Exception:
        return {}


STAGE_BY_OPERATION: dict[str, str] = {
    "ocr": "STAGE_1",
    "clean": "STAGE_3",
    "render": "STAGE_4",
    "layout": "STAGE_4",
}


def log_stage(stage: str, step: str, summary: str, level: int = logging.INFO, **fields: Any) -> None:
    """Record high-signal, non-spammy diagnostic milestone with live resource metrics."""
    prefix = stage.lower().replace("_", "")
    log_event(
        f"{prefix}.{step.lower()}",
        level=level,
        stage=stage,
        step=step,
        summary=summary,
        systemMetrics=system_metrics(),
        **fields,
    )


def log_stage1(step: str, summary: str, **fields: Any) -> None:
    """Record high-signal, non-spammy diagnostic milestone for Stage 1."""
    log_stage("STAGE_1", step, summary, **fields)


class ProgressLogger:
    """Throttle sub-step progress logs on stage transitions, percent steps, or wall time."""

    def __init__(
        self,
        event: str,
        job_id: str | None = None,
        *,
        min_percent_step: int = 10,
        min_seconds: float = 10.0,
    ) -> None:
        self.event = event
        self.job_id = job_id
        self.min_percent_step = min_percent_step
        self.min_seconds = min_seconds
        self.started = time.perf_counter()
        self.last_stage: str | None = None
        self.last_percent = -1
        self.last_at = time.monotonic()

    def record(self, fraction: float, stage: str | None = None, **extra: Any) -> None:
        percent = int(max(0.0, min(1.0, fraction)) * 100)
        now = time.monotonic()
        if (
            stage != self.last_stage
            or percent >= self.last_percent + self.min_percent_step
            or now - self.last_at >= self.min_seconds
        ):
            payload: dict[str, Any] = {
                "stage": stage,
                "percent": percent,
                "elapsedMs": round((time.perf_counter() - self.started) * 1000, 1),
                "sinceLastMs": round((now - self.last_at) * 1000, 1),
            }
            if self.job_id is not None:
                payload["jobId"] = self.job_id
            for key, value in extra.items():
                if value is not None:
                    payload[key] = value
            log_event(self.event, **payload)
            self.last_stage = stage
            self.last_percent = percent
            self.last_at = now


def clear_log() -> bool:
    """Clear active diagnostics log files to begin a fresh test session."""
    global _CONFIGURED, _LOGGER
    cleared = False
    with _LOCK:
        for handler in list(_LOGGER.handlers):
            try:
                handler.close()
                _LOGGER.removeHandler(handler)
            except Exception:
                pass
        _CONFIGURED = False
    for path in (_primary_path(), _fallback_path()):
        try:
            if path.is_file():
                path.unlink()
                cleared = True
        except Exception:
            pass
    return cleared

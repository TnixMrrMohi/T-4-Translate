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

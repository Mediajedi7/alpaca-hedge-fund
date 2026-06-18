"""Consistent logging: console (unbuffered for Docker) + per-run file in output/logs."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from core.config import ROOT

_LOG_DIR = ROOT / "output" / "logs"
_configured = False


def get_logger(name: str) -> logging.Logger:
    global _configured
    if not _configured:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
        fh = logging.FileHandler(_LOG_DIR / "meridian.log")
        handlers.append(fh)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=handlers,
        )
        _configured = True
    return logging.getLogger(name)

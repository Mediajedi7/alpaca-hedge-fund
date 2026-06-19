"""On/off switch for Monday auto-execution.

State lives in a file under cache/ (excluded from deploys, shared by both containers via
the volume mount), so the dashboard toggle and the cron job agree and the setting
survives redeploys. When the flag file is absent, the config default applies.
"""
from __future__ import annotations

from pathlib import Path

from core.config import cfg

_FLAG = Path("cache/auto_execute.flag")
_ON = {"1", "on", "true", "yes"}


def is_enabled() -> bool:
    if _FLAG.exists():
        return _FLAG.read_text().strip().lower() in _ON
    return bool(cfg.get("execution.auto_execute_enabled", True))


def set_enabled(on: bool) -> None:
    _FLAG.parent.mkdir(parents=True, exist_ok=True)
    _FLAG.write_text("on" if on else "off")

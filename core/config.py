"""Config + secrets loading. config.yaml is the single source of truth for all
tunables; secrets come from .env. Import `cfg` for parameters, `env()` for secrets."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


class _Cfg:
    """Dotted-path access into config.yaml, e.g. cfg.get('risk.veto.gross_max')."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def __getitem__(self, path: str) -> Any:
        val = self.get(path, _MISSING)
        if val is _MISSING:
            raise KeyError(f"config key not found: {path}")
        return val

    @property
    def raw(self) -> dict[str, Any]:
        return self._data


_MISSING = object()
cfg = _Cfg(_load())


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {name} (set it in .env)")
    return val

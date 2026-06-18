"""Cost tracking with a hard per-run ceiling. Reads response.usage after every
call and converts the four token buckets to USD via config pricing. Aborts the
run (raises CostCeilingExceeded) once the ceiling is crossed."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.config import cfg
from core.log import get_logger

log = get_logger("cost_tracker")


class CostCeilingExceeded(RuntimeError):
    pass


@dataclass
class CostTracker:
    ceiling_usd: float = field(default_factory=lambda: float(cfg.get("analysis.cost_ceiling_usd", 25.0)))
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    def _price(self, model: str) -> dict:
        pricing = cfg.get("analysis.pricing", {})
        return pricing.get(model) or {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30}

    def record(self, model: str, usage) -> float:
        """Add one response's usage. Returns the marginal cost of this call."""
        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cr = getattr(usage, "cache_read_input_tokens", 0) or 0
        p = self._price(model)
        cost = (inp * p["input"] + out * p["output"]
                + cw * p["cache_write"] + cr * p["cache_read"]) / 1_000_000

        self.input_tokens += inp
        self.output_tokens += out
        self.cache_write_tokens += cw
        self.cache_read_tokens += cr
        self.cost_usd += cost
        self.calls += 1
        return cost

    def check_ceiling(self) -> None:
        if self.cost_usd > self.ceiling_usd:
            raise CostCeilingExceeded(
                f"Cost ${self.cost_usd:.2f} exceeded ceiling ${self.ceiling_usd:.2f}")

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cost_usd": round(self.cost_usd, 4),
            "ceiling_usd": self.ceiling_usd,
        }

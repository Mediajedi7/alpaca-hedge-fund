"""Shared analyzer scaffold: bundles the API client, cost tracker, and cache, and
provides run_cached() — the cache-check → ceiling-check → call → parse → store flow
every analyzer uses."""
from __future__ import annotations

from dataclasses import dataclass

from analysis import cache
from analysis.api_client import APIClient, extract_json
from analysis.cost_tracker import CostTracker
from core.log import get_logger

log = get_logger("analysis")


@dataclass
class AnalysisContext:
    client: APIClient
    tracker: CostTracker

    @classmethod
    def create(cls, model: str | None = None) -> "AnalysisContext":
        tracker = CostTracker()
        return cls(client=APIClient(model=model, tracker=tracker), tracker=tracker)


def run_cached(ctx: AnalysisContext, analyzer: str, ticker: str, artifact_id: str,
               system: str, user: str, max_tokens: int | None = None) -> dict | None:
    """Cached Claude call. Returns parsed JSON dict, or None on parse failure."""
    hit = cache.get(analyzer, ticker, artifact_id)
    if hit is not None:
        log.info("%s/%s cache hit", analyzer, ticker)
        return hit

    ctx.tracker.check_ceiling()  # abort before spending more if already over
    text = ctx.client.complete(system, user, max_tokens=max_tokens)
    ctx.tracker.check_ceiling()  # and after, so the run stops promptly

    result = extract_json(text)
    if result is None:
        return None
    cache.put(analyzer, ticker, artifact_id, result)
    return result

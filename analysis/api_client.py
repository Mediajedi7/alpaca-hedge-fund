"""Anthropic SDK wrapper. Prompt caching on every system prompt, SDK-managed
retry/backoff on 429/5xx, robust JSON extraction, and a cheap token estimator."""
from __future__ import annotations

import json
import re

import anthropic

from core.config import cfg, env
from core.log import get_logger

log = get_logger("api_client")


class APIClient:
    def __init__(self, model: str | None = None, tracker=None):
        self.model = model or cfg.get("analysis.model", "claude-sonnet-4-6")
        self.tracker = tracker
        self._client = anthropic.Anthropic(
            api_key=env("ANTHROPIC_API_KEY", required=True),
            max_retries=5,  # SDK retries 429 + 5xx with exponential backoff
        )

    def complete(self, system: str, user: str, max_tokens: int | None = None) -> str:
        """One JSON-analysis call. System prompt is cached (ephemeral). Returns text."""
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens or int(cfg.get("analysis.max_tokens", 3000)),
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        if self.tracker is not None:
            self.tracker.record(self.model, resp.usage)
        return "".join(b.text for b in resp.content if b.type == "text")


# --- JSON extraction ----------------------------------------------------------

_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def extract_json(text: str):
    """Parse JSON from a model response: raw, ```json fenced, or prose-wrapped."""
    if not text:
        return None
    text = text.strip()
    # 1) raw
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2) fenced
    m = _FENCE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3) prose-wrapped: first balanced {...} or [...]
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    log.warning("could not extract JSON from response (%d chars)", len(text))
    return None


def estimate_tokens(text: str) -> int:
    """Cheap heuristic (~4 chars/token) for cost prediction without an API call."""
    return max(1, len(text) // 4)

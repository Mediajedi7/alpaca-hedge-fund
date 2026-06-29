---
name: project-state
description: Meridian hedge-fund build status — Layer 1 done, resume at Layer 2 (Scoring Engine)
metadata:
  type: project
---

**Meridian Capital Partners** — long/short equity hedge fund, dedicated Alpaca **paper**
account, 7-layer build. Repo `Mediajedi7/alpaca-hedge-fund`, runs in NAS container
`alpaca-hedge-fund` (`/volume2/Docker/AlpacaHedgeFund`). Completely separate from the
`alpaca-paper-trading` day-trader project — never mix code/data/creds.

As of 2026-06-18: **ALL 7 LAYERS COMPLETE & verified** (Data, Scoring, AI, Portfolio,
Risk, Execution, Reporting/Dashboard). Latest commit `6ecd445`. All keys in `.env`.

Two NAS containers run: `alpaca-hedge-fund` (supercronic — 17:15 daily scoring +
5-min intraday risk monitor) and `alpaca-hedge-fund-dashboard` (Streamlit :8502, LAN-only,
blended JARVIS theme; reach via jarvis.mediajedi.net on VPN). Execution is human-in-the-loop.

Full detail + operational follow-ups in repo `CLAUDE.md`. Open the next session in
`/Users/tommy/Workspace/alpaca-hedge-fund` so it auto-loads. The system now runs; future
work is operation/iteration (e.g. autoresearch-style optimization), not initial build.

**Restart cleanly:** open the session in `/Users/tommy/Workspace/alpaca-hedge-fund` so the
repo `CLAUDE.md` (full conventions, gotchas, deploy recipe) auto-loads.

Still needed eventually: fresh Alpaca paper keys (`ALPACA_API_KEY`/`ALPACA_SECRET_KEY` in
`.env`) for Layer 6, `ANTHROPIC_API_KEY` for Layer 3. FMP Premium key + SEC email already set.

Key facts (full detail in repo `CLAUDE.md`): config.yaml = single source of truth; FMP uses
the new `stable` API (v3 dead); yfinance must be ≥1.4.1; deploy via rsync with
`--rsync-path=/usr/bin/rsync` + `IdentitiesOnly=yes`; nightly cron points at not-yet-built
`run_scoring.py` (errors harmlessly until Layer 2). TODO: make `fcf_yield` TTM in Layer 2 Value.

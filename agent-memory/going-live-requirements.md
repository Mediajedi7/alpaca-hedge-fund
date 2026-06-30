---
name: going-live-requirements
description: SIP market-data subscription is a hard requirement before any live Alpaca cutover
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d3a8e0f-c959-4ff8-8471-c230088e3735
---

When Tommy says we're moving to a **live Alpaca account**, treat the **SIP
market-data subscription as a hard prerequisite** — raise it immediately and
gate the cutover on it. Do NOT do it preemptively; he explicitly said "fix
nothing now" (2026-06-29). Only act when he announces the live move.

**Why:** execution sets limit prices off the data feed. The free IEX feed
yields usable two-sided quotes for only ~1/20 names (many 9%+ spreads / no
ask), so the executor falls back to `stale-ref ± marketable_offset` and fills
poorly (a real paper run filled 62%; sells only 46%). Widening
`marketable_offset` is a fine *paper* workaround (Alpaca simulates fills) but on
live it means crossing the spread for real on every trade. SIP (full NBBO,
Alpaca "Algo Trader Plus", ~$99/mo) keeps limits tight AND fills.

**Also note:** the data feed is independent of paper-vs-live — going live does
not auto-grant SIP (separate subscription; code defaults to IEX in
`execution/broker.py`). Live additionally needs `config fund.mode: live` + the
typed confirmation already in the broker. The canonical version of this lives in
CLAUDE.md ("Going live — HARD PREREQUISITE"). Related: [[project-state]].

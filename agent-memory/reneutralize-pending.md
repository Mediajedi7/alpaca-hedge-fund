---
name: reneutralize-pending
description: "PENDING: re-neutralize the hedge-fund book (drifted to +32% net long) during market hours"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d3a8e0f-c959-4ff8-8471-c230088e3735
---

**Pending action — do during market hours (9:30–16:00 ET).** The alpaca-hedge-fund
book drifted to **+32% net long** (target +5%, hard cap +15%) after Monday
2026-06-29's partial fills (shorts didn't fill on the sparse IEX feed). Tommy
approved re-neutralizing (2026-06-30, market was closed so it was deferred).

**Prep already done (2026-06-30):** `execution.marketable_offset` widened
0.003 → 0.01 (commit bb2cb66) so sells/shorts actually fill. Paper-safe.

**Steps when market is open:**
1. Confirm market open (broker clock).
2. `run_execution.py --dry-run` — fresh plan (was ~30 trades → projected net +7.3%).
3. `run_execution.py --execute` — re-neutralize. Supervised (Tommy wanted eyes on it).
4. Verify live net exposure dropped from +32% toward ~+7%; re-run once if only partial fill.

Couldn't auto-schedule a reminder (trigger API 404 on 2026-06-30). Related:
[[going-live-requirements]] (SIP still required for live), [[project-state]].

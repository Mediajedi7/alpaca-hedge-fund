---
name: dashboard-theme-reload
description: Dashboard theme.py/CSS edits need a container restart — runOnSave only hot-reloads app.py
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d3a8e0f-c959-4ff8-8471-c230088e3735
---

Changes to `dashboard/theme.py` (the CSS via `theme.css()`) — and other imported
modules — do NOT reliably take effect from `git pull` alone. The dashboard runs
Streamlit with `--server.runOnSave`, which reruns the main script `app.py` but
does **not** consistently hot-reload imported modules, so `theme.py` keeps its
old CSS in the running process.

**How to apply:** after deploying a `theme.py` (or other imported-module) change,
restart the dashboard container so it loads fresh:
`./nas.sh "docker exec alpaca-hedge-fund sh -c 'cd /app && git pull --ff-only' && docker restart alpaca-hedge-fund-dashboard"`.
Edits to `app.py` itself DO reload via runOnSave (no restart needed).

**Why this matters:** three mobile-CSS fixes appeared to "do nothing" (2026-06-29)
purely because the new `theme.py` never loaded — the restart, not the selector
change, is what finally made it work. When a CSS/theme change seems ignored,
suspect a stale module before iterating on selectors. Related: deployment notes
in CLAUDE.md, [[project-state]].

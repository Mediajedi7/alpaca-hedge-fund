---
name: login-page-todo
description: "Pending: Tommy wants to fix some items on the dashboard login page (deferred)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d3a8e0f-c959-4ff8-8471-c230088e3735
---

Tommy wants to fix some items on the dashboard **login page** — deferred on
2026-06-29, to look at "tomorrow" (~2026-06-30). Specific items not yet given;
ask him what he wants changed when we pick it up.

The login page is rendered by `dashboard/auth.py` (`require_login()` →
`auth_stage == "creds"` form: username/password, optional TOTP/email code,
"remember this device"). Reminder: `theme.py`/CSS changes need a dashboard
container restart to take effect — see [[dashboard-theme-reload]].

---
name: commit-by-default
description: "Tommy wants code changes committed AND pushed by default, without asking each time"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 9d3a8e0f-c959-4ff8-8471-c230088e3735
---

Tommy prefers that completed changes always be committed **and pushed** —
don't leave work uncommitted, and don't ask whether to commit or push.

**Why:** He stated "we should always commit" and then "always push" after being
asked each time. Push = deploy for this project, and he wants the live NAS
dashboard updated without a confirmation step.

**How to apply:** After finishing a coherent change, commit it to `main` and
`git push` (the project's deploy model is `git push` → NAS auto-pulls `main`,
so branching is not expected here — see [[project-state]]). For dashboard/app
changes, also force an immediate pull so it's live now:
`./nas.sh "docker exec alpaca-hedge-fund sh -c 'cd /app && git pull --ff-only'"`.
Still verify changes before pushing (e.g. the headless AppTest against the
running container) — push-by-default does not mean skip verification.

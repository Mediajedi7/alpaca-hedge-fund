#!/bin/sh
# Weekly full refresh — runs Sunday evening (see crontab) so the book is fresh Monday.
#
#   1. run_scoring.py     full Layer-1 data refresh (incl. SEC filings, insider Form 4,
#                         13F institutional) + re-score all 503 names.
#   2. run_analysis.py    Claude qualitative overlay on the candidates (PAID; hard-capped
#                         at analysis.cost_ceiling_usd).
#   3. run_portfolio.py   rebuild the beta-neutral MVO target book.
#
# Execution stays MANUAL — this job never places trades. Review + execute Monday.
#
# On ANY failure (e.g. the NAS rebooted mid-run, as happened 2026-06-21) it emails an
# alert so a half-finished refresh doesn't silently leave a stale book for Monday.
cd /app
LOG=/app/output/logs/weekly_refresh.log
STEP="startup"

# notify <subject> <body> — best-effort; never aborts the script (send_email returns bool)
notify() {
    python3 -c "import sys; from core.notify import send_email; send_email(sys.argv[1], sys.argv[2])" \
        "$1" "$2" >> "$LOG" 2>&1
}

on_exit() {
    code=$?
    if [ "$code" -ne 0 ]; then
        echo "===== weekly refresh FAILED at [$STEP] (exit $code) $(date '+%F %T %Z') =====" >> "$LOG"
        notify "[Mediajedi HF] Weekly refresh FAILED — book NOT rebuilt" \
"The Sunday weekly refresh did NOT finish.

Failed step : $STEP (exit code $code)
Consequence : the target book was NOT rebuilt, so Monday's auto-execution may trade on
              STALE data (the Monday job also warns if the book is too old).

Check output/logs/weekly_refresh.log on the NAS, then re-run scripts/weekly_refresh.sh."
    fi
}
trap on_exit EXIT

set -e
echo "===== weekly refresh START $(date '+%F %T %Z') =====" >> "$LOG"
STEP="run_scoring (data refresh + score)"
python3 run_scoring.py   >> "$LOG" 2>&1
STEP="run_analysis (Claude overlay)"
python3 run_analysis.py  >> "$LOG" 2>&1
STEP="run_portfolio (rebuild book)"
python3 run_portfolio.py >> "$LOG" 2>&1
STEP="done"
echo "===== weekly refresh DONE  $(date '+%F %T %Z') =====" >> "$LOG"

notify "[Mediajedi HF] Weekly refresh complete — book rebuilt for Monday" \
"The Sunday weekly refresh finished cleanly:
  - full data refresh (filings / insider / 13F)
  - Claude analysis overlay
  - beta-neutral target book rebuilt

Monday's auto-execution will trade the fresh book."

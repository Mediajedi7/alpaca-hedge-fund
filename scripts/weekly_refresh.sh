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
# Emails a styled alert (scripts/refresh_alert.py) on success and on ANY failure, so a
# half-finished refresh (e.g. the NAS reboot on 2026-06-21) doesn't silently leave a
# stale book for Monday.
cd /app
LOG=/app/output/logs/weekly_refresh.log
STEP="startup"

on_exit() {
    code=$?
    if [ "$code" -ne 0 ]; then
        echo "===== weekly refresh FAILED at [$STEP] (exit $code) $(date '+%F %T %Z') =====" >> "$LOG"
        python3 -m scripts.refresh_alert fail "$STEP" "$code" >> "$LOG" 2>&1
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
python3 -m scripts.refresh_alert ok >> "$LOG" 2>&1

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
set -e
cd /app
LOG=/app/output/logs/weekly_refresh.log
echo "===== weekly refresh START $(date '+%Y-%m-%d %H:%M:%S %Z') =====" >> "$LOG"
python3 run_scoring.py   >> "$LOG" 2>&1
python3 run_analysis.py  >> "$LOG" 2>&1
python3 run_portfolio.py >> "$LOG" 2>&1
echo "===== weekly refresh DONE  $(date '+%Y-%m-%d %H:%M:%S %Z') =====" >> "$LOG"

#!/bin/sh
set -e

mkdir -p /app/output/logs /app/cache

# If a command was passed (e.g. the dashboard service runs streamlit), exec it.
if [ "$#" -gt 0 ]; then
  exec "$@"
fi

# Default: run the cron daemon for the daily scoring job.
exec supercronic /app/crontab

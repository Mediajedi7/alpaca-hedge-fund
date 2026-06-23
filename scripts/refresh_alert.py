"""Styled weekly-refresh alert email, called by scripts/weekly_refresh.sh.

  python3 -m scripts.refresh_alert ok
  python3 -m scripts.refresh_alert fail "<step>" "<exit_code>"
"""
import sys
from datetime import date

from core.notify import html_email, send_email

TAG = "[Mediajedi HF]"


def main() -> None:
    status = sys.argv[1] if len(sys.argv) > 1 else "fail"
    step = sys.argv[2] if len(sys.argv) > 2 else "?"
    code = sys.argv[3] if len(sys.argv) > 3 else "?"
    when = date.today().isoformat()

    if status == "ok":
        inner = ("<p>The Sunday weekly refresh finished cleanly:</p>"
                 "<div class='note'>&bull; full data refresh (filings / insider / 13F)<br>"
                 "&bull; Claude analysis overlay<br>"
                 "&bull; beta-neutral target book rebuilt</div>"
                 "<p>Monday's auto-execution will trade the fresh book.</p>")
        send_email(f"{TAG} {when} — weekly refresh complete",
                   "Weekly refresh complete — book rebuilt for Monday.",
                   html=html_email("Weekly refresh complete", inner, subtitle=when))
    else:
        inner = (f"<p>The Sunday weekly refresh <b>did not finish.</b></p>"
                 f"<div class='note'>Failed step: <b>{step}</b> (exit code {code})</div>"
                 "<p>The target book was <b>NOT rebuilt</b>, so Monday's auto-execution may "
                 "trade on stale data (the Monday job also warns if the book is too old). "
                 "Check <code>output/logs/weekly_refresh.log</code> on the NAS, then re-run "
                 "<code>scripts/weekly_refresh.sh</code>.</p>")
        send_email(f"{TAG} {when} — weekly refresh FAILED — book NOT rebuilt",
                   f"Weekly refresh FAILED at {step} (exit {code}) — book NOT rebuilt.",
                   html=html_email("Weekly refresh FAILED", inner, subtitle=when,
                                   banner="REFRESH FAILED", banner_class="alert-banner"))


if __name__ == "__main__":
    main()

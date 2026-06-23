"""Email notifications via the SMTP2GO account (shared smtp.* config + SMTP_PASSWORD).

Used for operational alerts (e.g. Monday auto-execution confirmations). Recipient is
notify.email_to, falling back to auth.otp_email_to. No-ops (returns False) if SMTP is
unconfigured, so callers never crash on a missing password.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from core.config import cfg, env
from core.log import get_logger

log = get_logger("notify")


def send_email(subject: str, body: str, to: str | None = None, html: str | None = None) -> bool:
    """Send an email. If `html` is given, send a multipart/alternative (plain `body` +
    HTML), so clients show the styled version and `body` is the text fallback."""
    host = cfg.get("smtp.host", "mail.smtp2go.com")
    port = int(cfg.get("smtp.port", 2525))
    user = cfg.get("smtp.user", "")
    sender = cfg.get("smtp.from", user)
    to = to or cfg.get("notify.email_to") or cfg.get("auth.otp_email_to", "")
    pw = env("SMTP_PASSWORD")
    if not (pw and to and user):
        log.warning("SMTP not configured — skipping email %r", subject)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        log.info("sent email %r to %s", subject, to)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("email send failed: %s", e)
        return False


# --------------------------------------------------------------------------- HTML template
# Shared styling for all Mediajedi emails (light card, green accents, dark-header tables,
# mobile-stacking) — mirrors the day-trader emails.
STYLE = """
<style>
  * { box-sizing: border-box; }
  body { margin:0; padding:0; font-family: Arial, sans-serif; font-size:15px;
         color:#222; background:#f5f5f5; -webkit-text-size-adjust:100%; }
  .wrapper { width:100%; background:#f5f5f5; padding:12px 0; }
  .container { max-width:640px; margin:0 auto; background:#fff; border-radius:8px;
               padding:20px 16px; box-shadow:0 2px 8px rgba(0,0,0,0.1); }
  .paper-banner { background:#fff3cd; border:1px solid #ffc107; border-radius:6px;
                  padding:10px 14px; margin-bottom:16px; font-size:13px; font-weight:bold;
                  color:#856404; text-align:center; }
  .alert-banner { background:#fdecea; border:1px solid #c62828; border-radius:6px;
                  padding:10px 14px; margin-bottom:16px; font-size:13px; font-weight:bold;
                  color:#922; text-align:center; }
  h1 { color:#1a1a2e; font-size:20px; border-bottom:2px solid #4CAF50;
       padding-bottom:8px; margin:0 0 6px; }
  .date { color:#777; font-size:13px; margin:0 0 16px; }
  h2 { color:#1a1a2e; font-size:15px; margin-top:24px; margin-bottom:8px;
       border-left:4px solid #4CAF50; padding-left:10px; }
  p { line-height:1.55; }
  .stats-grid { display:table; width:100%; border-collapse:collapse; background:#f0f7f0;
                border:1px solid #c8e6c9; border-radius:6px; margin:12px 0; }
  .stat-cell { display:table-cell; padding:12px 14px; vertical-align:top;
               border-right:1px solid #c8e6c9; }
  .stat-cell:last-child { border-right:none; }
  .stat-label { font-size:11px; color:#555; text-transform:uppercase;
                letter-spacing:0.5px; margin-bottom:4px; }
  .stat-value { font-size:20px; font-weight:bold; color:#2e7d32; }
  .stat-value.red { color:#c62828; }
  .stat-sub { font-size:12px; color:#777; margin-top:2px; }
  table { width:100%; border-collapse:collapse; margin-top:4px; }
  th { background:#1a1a2e; color:#fff; padding:9px 10px; text-align:left; font-size:12px; }
  td { padding:8px 10px; border-bottom:1px solid #eee; font-size:13px; }
  tr:last-child td { border-bottom:none; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .green { color:#2e7d32; font-weight:bold; }
  .red { color:#c62828; font-weight:bold; }
  .letter { background:#fafafa; border-left:4px solid #4CAF50; border-radius:0 6px 6px 0;
            padding:12px 16px; margin:8px 0; color:#333; }
  .letter p { margin:0 0 10px; }
  .note { background:#fafafa; border:1px solid #eee; border-radius:6px; padding:12px 14px; }
  .footer { margin-top:28px; font-size:11px; color:#aaa; border-top:1px solid #eee;
            padding-top:12px; text-align:center; }
  .footer a { color:#4CAF50; text-decoration:none; }
  @media only screen and (max-width:480px) {
    .container { padding:14px 10px; border-radius:0; }
    h1 { font-size:17px; }
    .stats-grid { display:block; }
    .stat-cell { display:block; border-right:none; border-bottom:1px solid #c8e6c9; }
    .stat-cell:last-child { border-bottom:none; }
  }
</style>
"""


def html_email(title: str, inner_html: str, subtitle: str = "",
               banner: str = "PAPER TRADING · simulated funds",
               banner_class: str = "paper-banner") -> str:
    """Wrap inner content in the shared Mediajedi email shell (header, banner, footer)."""
    ban = f'<div class="{banner_class}">{banner}</div>' if banner else ""
    sub = f'<p class="date">{subtitle}</p>' if subtitle else ""
    return (f"<html><head>{STYLE}</head><body><div class=\"wrapper\"><div class=\"container\">"
            f"{ban}<h1>{title}</h1>{sub}{inner_html}"
            "<div class=\"footer\">Mediajedi Hedge Fund · "
            "<a href=\"https://jarvis.mediajedi.net\">open dashboard</a><br>"
            "Not investment advice. Paper-trading simulation.</div>"
            "</div></div></body></html>")

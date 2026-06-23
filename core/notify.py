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

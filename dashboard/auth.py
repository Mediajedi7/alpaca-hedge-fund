"""In-app login gate with MFA + a 30-day trusted-device.

Active only when AUTH_PASSWORD_HASH is set in .env (so local/LAN stays open until you
configure it). Flow:

  1. username + password
  2. second factor — emailed one-time code (mfa: email) or authenticator TOTP
     (mfa: totp / fallback when SMTP isn't configured)
  3. optional "remember this device for N days" — sets a *signed* cookie so future
     sessions on the same browser skip sign-in entirely (both password and code).

The device cookie is read from the request headers (st.context.headers) and written
with extra_streamlit_components' CookieManager. The cookie value is HMAC-signed with a
server-only secret, so it can't be forged or extended client-side.

Serve behind HTTPS (reverse proxy / tunnel) so the password isn't sent in cleartext —
app-level auth does not provide transport security.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

import streamlit as st
import streamlit.components.v1 as components

from core.config import cfg, env

_COOKIE = "mhf_device"


# --------------------------------------------------------------------------- config
def _configured() -> bool:
    return bool(env("AUTH_PASSWORD_HASH"))


def _smtp_ready() -> bool:
    return bool(env("SMTP_PASSWORD") and cfg.get("smtp.user") and cfg.get("auth.otp_email_to"))


def _mfa_mode() -> str:
    """email when configured+ready, else totp when a secret exists, else none."""
    want = (cfg.get("auth.mfa", "email") or "email").lower()
    if want == "email" and _smtp_ready():
        return "email"
    return "totp" if env("AUTH_TOTP_SECRET") else "none"


# --------------------------------------------------------------------------- creds
def _creds_ok(user: str, password: str) -> bool:
    if not hmac.compare_digest(user or "", env("AUTH_USER") or ""):
        return False
    pw_hash = hashlib.sha256((password or "").encode()).hexdigest()
    return hmac.compare_digest(pw_hash, env("AUTH_PASSWORD_HASH") or "")


def _totp_ok(code: str) -> bool:
    secret = env("AUTH_TOTP_SECRET")
    if not secret:
        return False
    import pyotp
    return pyotp.TOTP(secret).verify((code or "").strip(), valid_window=1)


# ---------------------------------------------------------------- trusted device cookie
def _device_secret() -> bytes:
    # server-side only; never sent to the client
    return ("mhf-device|" + (env("AUTH_PASSWORD_HASH") or "")).encode()


def _sign_device(expiry: int) -> str:
    sig = hmac.new(_device_secret(), str(expiry).encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{sig}"


def _device_token_valid(token: str) -> bool:
    try:
        exp_s, sig = (token or "").split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return False
    good = hmac.new(_device_secret(), exp_s.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and exp > int(time.time())


def _device_trusted() -> bool:
    """Read + validate the signed device cookie straight from the request headers."""
    try:
        raw = st.context.headers.get("Cookie", "") or ""
    except Exception:  # noqa: BLE001
        return False
    for part in raw.split(";"):
        part = part.strip()
        if part.startswith(_COOKIE + "="):
            return _device_token_valid(part[len(_COOKIE) + 1:])
    return False


def _queue_remember() -> None:
    """Queue the signed device cookie; it's written next render by _flush_pending_cookie()."""
    days = int(cfg.get("auth.remember_device_days", 30))
    st.session_state["_pending_cookie"] = _sign_device(int(time.time()) + days * 86400)


def _flush_pending_cookie() -> None:
    """Write a queued device cookie via JS on a normal (non-rerun) render.

    Setting a cookie and immediately calling st.rerun() drops it — the writer never
    reaches the browser. So we queue on the login run and write on the next render
    (when the app is showing), which is not followed by an immediate rerun.
    """
    tok = st.session_state.pop("_pending_cookie", None)
    if not tok:
        return
    max_age = int(cfg.get("auth.remember_device_days", 30)) * 86400
    components.html(
        f"""<script>
        (function() {{
          var c = "{_COOKIE}={tok}; max-age={max_age}; path=/; samesite=Lax"
                  + (location.protocol === 'https:' ? '; secure' : '');
          for (var w of [window.top, window.parent, window]) {{
            try {{ w.document.cookie = c; break; }} catch (e) {{}}
          }}
        }})();
        </script>""",
        height=0,
    )


# --------------------------------------------------------------------------- email OTP
def _send_otp(code: str) -> bool:
    from core.notify import html_email, send_email
    ttl = int(cfg.get("auth.otp_ttl_minutes", 10))
    inner = (
        "<p>Your one-time sign-in code is:</p>"
        "<div class='stats-grid'><div class='stat-cell' style='text-align:center'>"
        f"<div class='stat-value' style='font-size:32px;letter-spacing:6px;color:#1a1a2e'>{code}</div>"
        "</div></div>"
        f"<p>It expires in {ttl} minutes. If you didn't try to sign in, ignore this email "
        "and consider changing the dashboard password.</p>")
    return send_email(
        f"Mediajedi Hedge Fund sign-in code: {code}",
        f"Your JARVIS one-time sign-in code is {code}. It expires in {ttl} minutes.",
        to=cfg.get("auth.otp_email_to") or None,
        html=html_email("Sign-in code", inner, banner=""))


def _issue_otp() -> bool:
    code = f"{secrets.randbelow(1_000_000):06d}"
    if not _send_otp(code):
        return False
    st.session_state.otp_hash = hashlib.sha256(code.encode()).hexdigest()
    st.session_state.otp_exp = time.time() + int(cfg.get("auth.otp_ttl_minutes", 10)) * 60
    return True


def _otp_ok(code: str) -> bool:
    h = st.session_state.get("otp_hash")
    exp = st.session_state.get("otp_exp", 0)
    if not h or time.time() > exp:
        return False
    return hmac.compare_digest(hashlib.sha256((code or "").strip().encode()).hexdigest(), h)


def _mask(addr: str) -> str:
    name, _, dom = (addr or "").partition("@")
    if not dom:
        return "your email"
    shown = name[0] + "***" if name else "***"
    return f"{shown}@{dom}"


# --------------------------------------------------------------------------- the gate
def _throttle(msg: str) -> None:
    st.session_state.auth_fails = st.session_state.get("auth_fails", 0) + 1
    time.sleep(min(5, st.session_state.auth_fails))  # slow brute force
    st.error(msg)


def require_login() -> None:
    """Block the app with a login screen until authenticated. No-op if unconfigured."""
    _flush_pending_cookie()  # write any queued device cookie (runs on this render, incl. while authed)

    if not _configured() or st.session_state.get("authed"):
        return

    # A remembered (trusted) device skips sign-in entirely — no password, no code.
    if _device_trusted():
        st.session_state.authed = True
        return

    st.session_state.setdefault("auth_fails", 0)
    st.session_state.setdefault("auth_stage", "creds")
    mode = _mfa_mode()

    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        st.markdown('<div class="jarvis" style="font-size:64px;text-align:center">JARVIS</div>'
                    '<div class="subtitle" style="text-align:center">Mediajedi Hedge Fund — Sign in</div>',
                    unsafe_allow_html=True)

        # ---- stage 1: credentials ----
        if st.session_state.auth_stage == "creds":
            with st.form("login", clear_on_submit=False):
                user = st.text_input("Username")
                pw = st.text_input("Password", type="password")
                code = (st.text_input("Authenticator code", max_chars=6, placeholder="123456")
                        if mode == "totp" else None)
                remember = st.checkbox(
                    f"Remember this device for {int(cfg.get('auth.remember_device_days', 30))} days "
                    "(skip sign-in on this browser)")
                ok = st.form_submit_button("Continue", type="primary", use_container_width=True)
            if ok:
                if not _creds_ok(user, pw):
                    _throttle("Invalid username or password.")
                    st.stop()
                st.session_state.auth_fails = 0
                st.session_state.auth_remember = remember
                # no second factor configured -> straight in
                if mode == "none":
                    st.session_state.authed = True
                    if remember:
                        _queue_remember()
                    st.rerun()
                if mode == "totp":
                    if _totp_ok(code):
                        st.session_state.authed = True
                        if remember:
                            _queue_remember()
                        st.rerun()
                    _throttle("Invalid authenticator code.")
                    st.stop()
                # mode == email -> send a code, advance to stage 2
                if _issue_otp():
                    st.session_state.auth_stage = "otp"
                    st.rerun()
                else:
                    st.error("Couldn't send the email code — SMTP isn't configured. "
                             "Use your authenticator app or contact the admin.")

        # ---- stage 2: emailed one-time code ----
        else:
            st.info(f"We emailed a 6-digit code to **{_mask(cfg.get('auth.otp_email_to', ''))}**. "
                    f"It expires in {int(cfg.get('auth.otp_ttl_minutes', 10))} minutes.")
            with st.form("otp", clear_on_submit=False):
                code = st.text_input("Email code", max_chars=6, placeholder="123456")
                ok = st.form_submit_button("Verify", type="primary", use_container_width=True)
            c1, c2 = st.columns(2)
            if c1.button("Resend code", use_container_width=True):
                _issue_otp()
                st.toast("New code sent.")
            if c2.button("Start over", use_container_width=True):
                st.session_state.auth_stage = "creds"
                st.rerun()
            if ok:
                if _otp_ok(code):
                    st.session_state.authed = True
                    st.session_state.auth_stage = "creds"
                    if st.session_state.get("auth_remember"):
                        _queue_remember()
                    st.session_state.pop("otp_hash", None)
                    st.rerun()
                else:
                    _throttle("Invalid or expired code.")
    st.stop()

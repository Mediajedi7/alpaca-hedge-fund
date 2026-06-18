"""In-app login gate with TOTP 2FA. Active only when AUTH_PASSWORD_HASH is set in
.env (so local/LAN stays open until you configure it). Requires username + password
+ a 6-digit authenticator-app code. Generate credentials with scripts/setup_auth.py.

NOTE: serve behind HTTPS (reverse proxy / tunnel) so the password isn't sent in
cleartext — app-level auth does not provide transport security."""
from __future__ import annotations

import hashlib
import hmac
import time

import streamlit as st

from core.config import env


def _configured() -> bool:
    return bool(env("AUTH_PASSWORD_HASH"))


def _check(user: str, password: str, code: str) -> bool:
    if not hmac.compare_digest(user or "", env("AUTH_USER") or ""):
        return False
    pw_hash = hashlib.sha256((password or "").encode()).hexdigest()
    if not hmac.compare_digest(pw_hash, env("AUTH_PASSWORD_HASH") or ""):
        return False
    secret = env("AUTH_TOTP_SECRET")
    if secret:
        import pyotp
        if not pyotp.TOTP(secret).verify((code or "").strip(), valid_window=1):
            return False
    return True


def require_login() -> None:
    """Block the app with a login screen until authenticated. No-op if unconfigured."""
    if not _configured() or st.session_state.get("authed"):
        return

    st.session_state.setdefault("auth_fails", 0)
    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        st.markdown('<div class="jarvis" style="font-size:64px;text-align:center">JARVIS</div>'
                    '<div class="subtitle" style="text-align:center">Mediajedi Hedge Fund — Sign in</div>',
                    unsafe_allow_html=True)
        with st.form("login", clear_on_submit=False):
            user = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            code = st.text_input("2FA code", max_chars=6, placeholder="123456")
            ok = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if ok:
            if _check(user, pw, code):
                st.session_state.authed = True
                st.session_state.auth_fails = 0
                st.rerun()
            else:
                st.session_state.auth_fails += 1
                time.sleep(min(5, st.session_state.auth_fails))  # throttle brute force
                st.error("Invalid credentials or 2FA code.")
    st.stop()

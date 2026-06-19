"""Verify the dashboard auth gate is active for a fresh (unauthenticated) session."""
from streamlit.testing.v1 import AppTest

from core.config import env
from dashboard import auth

print("AUTH configured:", auth._configured(), "| AUTH_USER:", env("AUTH_USER"))

at = AppTest.from_file("dashboard/app.py", default_timeout=60)
at.run()  # fresh session, NOT authenticated
labels = [t.label for t in at.text_input]
btns = [b.label for b in at.button]
print("login inputs:", labels)
print("nav/page buttons present:", any("PORTFOLIO" in b for b in btns))
gated = ("Username" in labels) and not any("PORTFOLIO" in b for b in btns)
print("GATED (login shown, app hidden):", gated)

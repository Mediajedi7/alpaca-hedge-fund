"""Generate dashboard login credentials + a TOTP 2FA secret.

Usage (run in the container, interactive):
  docker exec -it alpaca-hedge-fund sh -c 'cd /app && python3 -m scripts.setup_auth <username>'

Prints the three lines to paste into .env, plus a QR code to scan in your
authenticator app (Google Authenticator / Authy / 1Password)."""
import getpass
import hashlib
import sys

import pyotp
import qrcode

user = sys.argv[1] if len(sys.argv) > 1 else input("Username: ")
pw = sys.argv[2] if len(sys.argv) > 2 else getpass.getpass("Password: ")
secret = pyotp.random_base32()
uri = pyotp.TOTP(secret).provisioning_uri(name=user, issuer_name="Mediajedi Hedge Fund — JARVIS")

print("\n=== Add these lines to .env ===")
print(f"AUTH_USER={user}")
print(f"AUTH_PASSWORD_HASH={hashlib.sha256(pw.encode()).hexdigest()}")
print(f"AUTH_TOTP_SECRET={secret}")
print("\n=== Scan this QR in your authenticator app ===")
qr = qrcode.QRCode(border=1)
qr.add_data(uri)
qr.print_ascii(invert=True)
print(f"\n(or enter the secret manually: {secret})")
print("\nThen restart the dashboard. Login requires username + password + the 6-digit code.")

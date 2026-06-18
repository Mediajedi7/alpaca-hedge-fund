# Exposing the JARVIS dashboard at jarvis.mediajedi.net (Synology + Let's Encrypt)

Path chosen: Synology DSM reverse proxy + Let's Encrypt TLS. Keeps mediajedi.net DNS
on Microsoft (email untouched). Trade-off: exposes the home IP + an inbound port.

**Do these in order. Step 1 (auth) before any port is opened.**

## 1. Turn on the login + 2FA FIRST
```
./nas.sh "docker exec -it alpaca-hedge-fund sh -c 'cd /app && python3 -m scripts.setup_auth <username>'"
```
Add the printed `AUTH_USER` / `AUTH_PASSWORD_HASH` / `AUTH_TOTP_SECRET` to
`/volume2/Docker/AlpacaHedgeFund/.env`, scan the QR in your authenticator app, then:
```
./nas.sh "cd /volume2/Docker/AlpacaHedgeFund && docker compose restart dashboard"
```
Confirm the login screen appears on the LAN (http://10.0.1.6:8502) before continuing.

## 2. DNS — add the A record (Microsoft 365 DNS manager)
- Host: `jarvis`  ·  Type: `A`  ·  Value: `47.197.216.50`  ·  TTL: low (e.g. 5 min)
- ⚠️ Residential IPs can change. If it does, this record must be updated. Options:
  set a low TTL and update manually, ask your ISP for a static IP, or use a DDNS
  service that can update Microsoft DNS. (A Cloudflare Tunnel would avoid this entirely.)

## 3. Router — port forward to the Synology (10.0.1.6)
- TCP `443` → 10.0.1.6:443  (HTTPS)
- TCP `80`  → 10.0.1.6:80   (Let's Encrypt HTTP-01 challenge + renewals only)
- Do NOT forward 8502 directly.

## 4. DSM — Let's Encrypt certificate
Control Panel → Security → Certificate → Add → "Get a certificate from Let's Encrypt"
- Domain name: `jarvis.mediajedi.net`  ·  Email: yours
- (Needs port 80 reachable from the internet for the challenge.)

## 5. DSM — Reverse Proxy
Control Panel → Login Portal → Advanced → Reverse Proxy → Create:
- **Source:** HTTPS · `jarvis.mediajedi.net` · port `443`
- **Destination:** HTTP · `localhost` · port `8502`
- **Custom Header tab → Create → WebSocket** (REQUIRED — Streamlit uses WebSockets;
  without this the page loads but never connects)
- Assign the Let's Encrypt cert to this hostname (Security → Certificate → Settings →
  set `jarvis.mediajedi.net` to use the new cert).

## 6. Harden (DSM → Security)
- Firewall: allow 80/443 from the internet; restrict everything else.
- Enable Auto Block + Account Protection.
- Keep the dashboard's in-app login + 2FA on (step 1) — it's your real gate.

## 7. Verify
Browse https://jarvis.mediajedi.net → should show the JARVIS login screen over a valid
cert. Log in with username + password + 6-digit code.

### Troubleshooting
- Page loads but spins / "Please wait…": WebSocket header not set on the reverse proxy (step 5).
- If login/XSRF misbehaves behind the proxy, add to `.streamlit/config.toml`:
  `[server]` `enableCORS = false` and `enableXsrfProtection = false` (then restart dashboard).
- Cert won't issue: port 80 not reachable from the internet (ISP block or forward missing).

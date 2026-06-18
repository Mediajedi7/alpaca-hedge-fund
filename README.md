# Meridian Capital Partners

A long/short equity hedge-fund system trading a **dedicated Alpaca paper account**.
Built as 7 layers; runs in a Docker container on the NAS. Completely separate from the
day-trader project — no shared code, data, or credentials.

## Architecture (7 layers)

| Layer | Dir | Purpose |
|-------|-----|---------|
| 1 | `data/` | Data ingestion — universe, prices, fundamentals (FMP), SEC, 13-F, short interest, estimates, earnings calendar → SQLite |
| 2 | `factors/` | Scoring engine — 8 factors / 27 sub-factors, 0–100 sector-percentile ranks |
| 3 | `analysis/` | Claude AI qualitative analysis + 60/40 combined score |
| 4 | `portfolio/` | Portfolio construction — MVO and conviction-tilt optimizers |
| 5 | `risk/` | Barra-style factor risk model + absolute-veto pre-trade checks + circuit breakers |
| 6 | `execution/` | Alpaca paper execution, slippage tracking, short-availability |
| 7 | `reporting/` + `dashboard/` | Reports, LP letters, Streamlit dashboard (JARVIS) |

All tunables and risk limits live in **`config.yaml`** (single source of truth). Secrets in `.env` (gitignored).

## Data sources
- **FMP (Premium)** — quarterly fundamentals + ratios (primary), yfinance fallback
- **yfinance** — OHLCV, short interest, analyst estimates, earnings calendar
- **SEC EDGAR** — 10-K/10-Q/8-K, Form 4 insider, 13-F institutional
- Earnings-call transcripts are **not** ingested (FMP Ultimate-only); Layer 3 earnings analyzer stays dormant.

## Deployment (NAS container)
- NAS dir: `/volume2/Docker/AlpacaHedgeFund` → mounted `/app`
- Container: `meridian-fund` (supercronic cron) + `meridian-dashboard` (Streamlit, LAN-only :8502)
- Daily scoring: weekdays 17:15 ET via supercronic (`crontab`)
- Helper: `./nas.sh "<cmd>"`

```bash
# Build & start the scheduler service on the NAS
./nas.sh "cd /volume2/Docker/AlpacaHedgeFund && docker compose up -d --build fund"
# Start the dashboard (after Layer 7 exists)
./nas.sh "cd /volume2/Docker/AlpacaHedgeFund && docker compose up -d dashboard"
```

## Safety
- **Paper only.** Live mode requires `mode: live` in config **and** a typed confirmation in `execution/broker.py`.
- The dashboard is interactive (places paper orders, calls Claude) — **LAN-only, never port-forwarded**.

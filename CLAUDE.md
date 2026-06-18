# Meridian Capital Partners — Project Memory (alpaca-hedge-fund)

Long/short equity hedge-fund system on a **dedicated Alpaca paper account**.
Built as 7 layers (see `docs/BUILD_PLAN.md`). Runs in a Docker container on the NAS.

## ⚠️ Separation rule
This project is **completely separate** from the `alpaca-paper-trading` "day trader"
project. **No shared code, data, strategies, or credentials.** Do not pull anything
from that project unless Tommy explicitly says to. Both are paper accounts (the
live/paper rule still applies — never touch live from here).

## STATUS — resume here
- **Layer 1 (Data Infrastructure): COMPLETE & verified live in-container.** All 7
  sources work. Committed: `4152f83`.
- **NEXT: Layer 2 (Scoring Engine)** — 8 factors / 27 sub-factors, 0–100 percentile
  rank within GICS sector. Full spec in `docs/BUILD_PLAN.md` §2. Factor weights and
  the `revisions_min_snapshot_days`, `no_data_score` knobs are already in `config.yaml`.
- Layers 3–7 not started.

## Architecture / conventions
- **`config.yaml` is the single source of truth** for every tunable and risk limit.
  Never hardcode these elsewhere — read via `core.config.cfg.get("dotted.path")`.
  Ownership notes in config matter (e.g. earnings 50% size-cut is applied ONCE by
  Layer 5 risk, NOT also by Layer 4; optimizer beta cap 0.15 vs veto 0.20 are
  intentionally different).
- Secrets in `.env` (gitignored): `FMP_API_KEY`, `ANTHROPIC_API_KEY`,
  `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` (still NEEDED — fresh paper account),
  `SEC_USER_AGENT_EMAIL` (tommy@tktechservices.com).
- `core/`: `config.py` (yaml+dotenv loader), `db.py` (SQLite, **WAL + busy_timeout**
  for concurrent dashboard-read / job-write), `log.py`.
- SQLite DB: `cache/meridian.db` (volume-mounted on NAS, not in git).
- Run modules as packages from repo root: `python3 -m data.<module>` (needs `core` on path).
- Layer entry points: `run_data.py` (L1), later `run_scoring.py` (L2), `run_analysis.py`,
  `run_execution.py`.

## Data-source gotchas (learned the hard way — apply to day-trader too)
- **FMP legacy `/api/v3/` API is fully deprecated (403).** Use the new `stable` API:
  `https://financialmodelingprep.com/stable/<endpoint>?symbol=AAPL&apikey=...`.
  Field change: dividends = `netDividendsPaid` (was `dividendsPaid`).
- **yfinance must be ≥ 1.4.1** — 0.2.x is broken vs current Yahoo ("no timezone found").
  1.x pulls `curl_cffi`.
- **SEC Form 4**: submissions `primaryDocument` is the XSLT-rendered HTML
  (`xslF345X06/form4.xml`); fetch the **raw XML basename** (`form4.xml`) for parsing.
- **13-F lists CUSIPs, not tickers.** Mapped via FMP `stable/profile` `cusip` field,
  restricted to the S&P 500 universe (`universe_cusip` table). Fund CIKs are in
  `config.yaml` (verified against EDGAR).
- yfinance short-interest updates ~bi-monthly (FINRA), not truly daily; 13-F lags ~45d;
  revisions factor is degenerate (=50) until ~30 days of estimate snapshots accumulate.
- TODO: stored `fcf_yield` uses single-quarter FCF — switch to TTM when building the
  Layer 2 Value factor (which recomputes FCF yield from EV anyway).

## Deployment (NAS) — see also README.md
- GitHub: `Mediajedi7/alpaca-hedge-fund` (private). `gh` auth in keyring (no token in URL).
- NAS: Synology `10.0.1.6`, key `~/.ssh/claude_nas`. Project dir
  `/volume2/Docker/AlpacaHedgeFund` → mounted `/app`. Helper: `./nas.sh "<cmd>"`.
- Container `alpaca-hedge-fund` (supercronic scheduler, running) + future
  `alpaca-hedge-fund-dashboard` (Streamlit :8502, **LAN-only, never port-forward**).
- **Deploy = rsync the working tree, then run in-container.** The rsync needs these
  exact opts (NAS quirks): absolute key path, `--rsync-path=/usr/bin/rsync`,
  `IdentitiesOnly=yes` (else SSH falls back to password and fails):
  ```
  rsync -az --rsync-path=/usr/bin/rsync \
    -e "ssh -i /Users/tommy/.ssh/claude_nas -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=no" \
    --exclude '.git' --exclude 'cache' --exclude 'output' --exclude '__pycache__' --exclude '.DS_Store' --exclude '.venv' \
    ./ admin@10.0.1.6:/volume2/Docker/AlpacaHedgeFund/
  ```
- Test fast against the running container: `./nas.sh "docker exec alpaca-hedge-fund sh -c 'cd /app && python3 -m data.<module> AAPL'"`.
- Rebuild image only when `requirements.txt` changes:
  `./nas.sh "cd /volume2/Docker/AlpacaHedgeFund && docker compose build fund"`.
- **Cron caveat:** `crontab` runs `run_scoring.py --no-filings --no-13f` weekdays 17:15 ET,
  which doesn't exist until Layer 2 — it errors nightly until then (harmless). Optionally
  point it at `run_data.py --no-filings --no-13f` in the meantime.

## Full-universe runtime
Tested on small subsets. A full 503-ticker run is slow (yfinance `.info` ≈ 500 calls,
FMP fundamentals ≈ 2000 calls). Expect 20–40+ min; the daily job uses `--no-filings --no-13f`.

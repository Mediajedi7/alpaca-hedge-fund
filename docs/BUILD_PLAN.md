# Mediajedi Hedge Fund — 7-Layer Build Plan

Condensed from Tommy's 7 original prompts. Numeric parameters live in `config.yaml`
(single source of truth); this doc preserves structure/intent. **ALL 7 LAYERS DONE.**

## 1. Data Infrastructure — DONE
5 source groups → SQLite (`cache/meridian.db`): universe (S&P500 + benchmarks/sector
ETFs/macro), market data (OHLCV 3yr incremental), fundamentals (FMP stable, 24 ratios,
quarterly+annual), SEC (10-K/10-Q/8-K + Form 4 insider w/ CEO-CFO & cluster flags),
13-F institutional (9 funds, CUSIP→ticker), short interest, analyst estimates, earnings
calendar. Entry: `run_data.py` (`--no-filings --no-13f --forms --tickers`).

## 2. Scoring Engine — DONE
8 factors / 27 sub-factors. **Every score = 0–100 percentile rank WITHIN GICS sector.**
Equal-weight sub-factors within each parent, then sector-percentile. Composite weights
in `config.yaml: factors.weights`. No data → sector median (50).

1. **Momentum** (6): 12-1m return (skip recent 1m), 6m return, 3m return, acceleration
   (recent 3m − older 3m), 52w-high proximity (price/52w-high, George&Hwang), relative
   strength vs sector ETF (6m stock − 6m sector-ETF return).
2. **Value** (6): forward earnings yield (1/fwd P/E), book-to-price, FCF yield, EV/EBITDA
   (invert), shareholder yield (TTM buybacks+divs / mktcap), sales-to-EV (rev/EV).
3. **Quality** (8): ROE stability (std of 12Q ROE, invert), gross margin level, GM trend
   (latest − 4Q ago), D/E (invert), CFO/NI, accruals ratio ((NI−CFO)/TA, invert),
   **Piotroski F-Score** (1–9 binary; green ≥7, amber ≤3), **Altman Z**
   `1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MktCap/TL + 1.0·Sales/TA`
   (>2.99 safe/green, 1.81–2.99 grey, <1.81 distress/amber).
4. **Growth** (5): rev growth YoY, earnings growth YoY, rev-growth acceleration
   (latest YoY − 4Q-ago YoY), R&D intensity (R&D/rev), FCF growth YoY.
5. **Estimate Revisions** (3): 30/60/90-day change in consensus next-Q EPS. Degenerate
   (=50) until ~30 days of snapshots (`factors.revisions_min_snapshot_days`).
6. **Short Interest** (3): short %float, days-to-cover, change vs prior. LONGS: declining
   SI scores higher. SHORTS: increasing SI scores higher.
7. **Insider** (3): net $ flow 90d (Form 4), CEO/CFO open-market buys weighted 3×,
   cluster-buy bonus. Count codes P/S only; ignore A/M/F. No data → 50.
   (Helpers ready: `data.sec_data.insider_summary`.)
8. **Institutional** (3): # tracked funds holding, net Δ aggregate holdings vs prior Q,
   multi-fund simultaneous-open flag (≥3). (Helper: `data.institutional.institutional_summary`.)

Output: per-ticker sub-scores + 8 parent scores + composite, stored for Layers 3/4.

## 3. AI Analysis (Claude) — CODE COMPLETE (live test pending key)
Anthropic SDK, model `config.analysis.model` (use latest Sonnet), prompt caching on system
prompts, cost tracker w/ $25 ceiling, analysis cache (TTL 30d). Analyzers: earnings-call
(NEEDS transcripts — **FMP Premium has none; Ultimate-only → analyzer stays dormant**),
filing/forensic (8Q fundamentals), risk (10-K Risk Factors), insider. Sector ranking +
combined score (60% quant / 40% Claude avg; 100% quant if no Claude, no penalty). Markdown
reports per candidate. Entry `run_analysis.py --estimate-cost --ticker --sector`.

## 4. Portfolio Construction — DONE
Two optimizers. **MVO** (`portfolio/mvo_optimizer.py`): scipy SLSQP, maximize μᵀw − λwᵀΣw;
expected return = composite linear (100→+15%/yr, 0→−15%/yr); 120d cov (later replaced by
Layer 5 factor-cov — **write against a covariance-provider interface**); constraints from
config (long/short gross targets, per-position min/max, |portfolio β|≤0.15, |sector net|≤5%,
single-side sector ≤25%); fall back to conviction on non-convergence. **Conviction-tilt**
(`portfolio/optimizer.py`): equal-weight base, top-5%→1.5×, top-10%→1.25×, liquidity ≤5%
ADV, half-size if earnings ≤5d, beta-adjust, sector-neutral. **Transaction costs**: commission
0 + spread (5% of avg H-L range) + impact (0.10·√(size/ADV)·dailyVolBps), fed into MVO.

## 5. Risk Management (ABSOLUTE VETO) — DONE
**Barra factor model** (`risk/factor_risk_model.py`): daily cross-sectional regression on
z-scored factor exposures → factor returns, factor cov, specific var; portfolio factor/specific
var, MCTR (flag MCTR% > 1.5× weight%); feed predicted cov (XFXᵀ+diag) to Layer 4.
**Pre-trade veto** (`risk/pre_trade.py`, 8 checks, ANY fail = reject; closing trades always
approved; log every rejection): halt lock, earnings blackout (5d=50% cut — applied HERE only),
liquidity ≤5% ADV, position ≤5% AUM, sector ≤25%, gross ≤165% & net [−10,+15]%, |net β|≤0.20,
pairwise corr ≤0.80. **Circuit breakers** (on $ losses): daily >1.5%→size-down 30%,
daily >2.5%→close-all-today, weekly >4%→size-down 30%, drawdown >8%→kill-switch (lock file,
`--clear-halt`), single position >3% NAV→force-close.

## 6. Execution (Alpaca paper) — DONE
`execution/broker.py`: alpaca-py, **hardcode paper base URL**; live requires `mode: live`
AND typed "YES I UNDERSTAND THE RISKS"; sync state on startup; backoff. `executor.py`:
per trade → veto → short-availability → limit `close·(1±0.001)` → chunk >2% ADV → 120s TIF →
poll 5s → cancel+retry (3×) → record signal_price. `costs.py` slippage (fill−signal)/signal
·1e4 bps, 30d rolling avg/median/p95/$ + worst 5. `short_check.py` shortable/easy_to_borrow,
cache 7d. `order_manager.py` pending/partial/filled/cancelled, SIGINT→cancel pending keep
positions. Entry `run_execution.py --dry-run|--execute`.

## 7. Reporting + Dashboard — DONE
**Reporting**: daily P&L attribution (beta/sector/factor/alpha → `output/daily_attribution.csv`),
position attribution (FIFO, Spearman score↔return), win/loss slices, sector-relative alpha,
turnover + FIFO tax (ST 37% / LT 20%), markdown tear sheet, Claude weekly commentary (JARVIS,
Fridays), daily LP letter. **Streamlit dashboard** :8502 (LAN-only), JARVIS persona, theme in
`config.dashboard.theme`, 6 pages (I Portfolio/cover, II Research, III Risk, IV Performance,
V Execution, VI Letter), auto-refresh 5min during market hours. Daily automation = supercronic
cron (replaces the macOS launchd plist in the original prompt).

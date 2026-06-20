"""Mediajedi Hedge Fund — JARVIS dashboard (Streamlit, LAN-only :8502).
6 pages: Portfolio cover, Research, Risk, Performance, Execution, Investors Letter."""
from __future__ import annotations

import os
import sys

# `streamlit run dashboard/app.py` puts dashboard/ on sys.path, not the repo root —
# add the repo root so `core`, `reporting`, etc. import cleanly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calendar
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis import cache
from core.config import cfg
from core.db import get_conn
from dashboard import theme
from reporting import analytics, attribution, jarvis, metrics

st.set_page_config(page_title="JARVIS — Mediajedi Hedge Fund", layout="wide", page_icon="◆")
st.markdown(theme.css(), unsafe_allow_html=True)

from dashboard import auth  # noqa: E402
auth.require_login()  # gates the app when AUTH_* is configured in .env

NAV = [("I", "PORTFOLIO"), ("II", "RESEARCH"), ("III", "RISK"),
       ("IV", "PERFORMANCE"), ("V", "EXECUTION"), ("VI", "LETTER")]
if "page" not in st.session_state:
    st.session_state.page = 0
if "jarvis_history" not in st.session_state:
    st.session_state.jarvis_history = []

page = st.session_state.page

# Tab-bar nav at the top, divider beneath it. Button-based (reruns in place, same
# Streamlit session), so login/auth persists across navigation — no page reload.
_nc = st.columns(len(NAV))
for _i, (_rn, _lab) in enumerate(NAV):
    if _nc[_i].button(f"{_rn}  {_lab}", key=f"nav_{_i}", use_container_width=True,
                      type="primary" if st.session_state.page == _i else "secondary"):
        st.session_state.page = _i
        st.rerun()
st.divider()

# auto-refresh during market hours
now = datetime.now()
if cfg.get("dashboard.market_open", "09:30") <= now.strftime("%H:%M") <= cfg.get("dashboard.market_close", "16:00") \
        and now.weekday() < 5:
    st.markdown(f'<meta http-equiv="refresh" content="{cfg.get("dashboard.refresh_secs", 300)}">',
                unsafe_allow_html=True)


def _q(sql, params=()):
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def _asof(table="scores"):
    with get_conn() as conn:
        r = conn.execute(f"SELECT MAX(asof_date) d FROM {table}").fetchone()
    return r["d"] if r else None


# ---------------- PAGE I: PORTFOLIO (cover) ----------------
@st.cache_data(ttl=30, show_spinner=False)
def _account():
    """Live Alpaca paper account snapshot (cached briefly)."""
    from execution.broker import Broker
    a = Broker().account()
    return {"equity": float(a.equity), "last_equity": float(a.last_equity), "cash": float(a.cash)}


def page_portfolio():
    m = jarvis.metrics()
    left, right = st.columns([44, 56], gap="large")
    with left:
        st.markdown('<div class="jarvis">JARVIS</div>'
                    '<div class="subtitle">Long / Short Hedge Fund Analyst</div>', unsafe_allow_html=True)
        q = st.text_input("ask", placeholder="Ask anything…", label_visibility="collapsed")
        asked = st.button("ASK JARVIS", type="primary")

        # live Alpaca paper account: balance + running P&L
        try:
            from reporting import pnl
            a = _account()
            basis = pnl.cost_basis()                       # seed +/- net deposits/withdrawals
            day = pnl.today_pnl(a["equity"], a["last_equity"])
            tot = pnl.total_pnl(a["equity"])
            dpct = (day / a["last_equity"] * 100) if a["last_equity"] else 0.0
            tpct = (tot / basis * 100) if basis else 0.0
            dcol = theme.LONG if day >= 0 else theme.SHORT
            tcol = theme.LONG if tot >= 0 else theme.SHORT
            st.markdown(
                '<div class="acct">'
                f'<div><div class="al">Account balance</div><div class="av">${a["equity"]:,.0f}</div>'
                f'<div class="as">${a["cash"]:,.0f} cash</div></div>'
                f'<div><div class="al">Today P&amp;L</div><div class="av" style="color:{dcol}">{day:+,.0f}</div>'
                f'<div class="as" style="color:{dcol}">{dpct:+.2f}%</div></div>'
                f'<div><div class="al">Total P&amp;L</div><div class="av" style="color:{tcol}">{tot:+,.0f}</div>'
                f'<div class="as" style="color:{tcol}">{tpct:+.2f}% on ${basis:,.0f} invested</div></div>'
                '</div>', unsafe_allow_html=True)
        except Exception as e:  # noqa: BLE001
            st.caption(f"Live account data unavailable: {e}")

        if asked and q:
            with st.spinner("JARVIS analyzing…"):
                ans = jarvis.ask(q, st.session_state.jarvis_history)
            st.session_state.jarvis_history += [{"role": "user", "content": q},
                                                {"role": "assistant", "content": ans}]

        # latest exchange rendered inline (question label + answer card)
        hist = st.session_state.jarvis_history
        if hist:
            last_q = next((t["content"] for t in reversed(hist) if t["role"] == "user"), "")
            last_a = next((t["content"] for t in reversed(hist) if t["role"] == "assistant"), "")
            body = last_a.replace("\n\n", "</p><p>").replace("\n", "<br>")
            st.markdown(f'<div class="ask-q">{last_q}</div>'
                        f'<div class="ask-a"><p>{body}</p></div>', unsafe_allow_html=True)

        items = [("Universe", m["universe"]), ("Long Cand.", m["long_candidates"]),
                 ("Short Cand.", m["short_candidates"]), ("Positions", m["positions"]),
                 ("Crowding", m["crowding"]), ("Insider Events", m["insider_events"]),
                 ("CEO/CFO Buys", m["ceo_buys"]), ("Cluster Buys", m["cluster_buys"]),
                 ("VIX", m["vix"]), ("Earnings · 7d", m["earnings_7d"])]
        st.markdown(theme.metrics_grid(items), unsafe_allow_html=True)

        st.markdown(
            '<div class="about">'
            '<div class="h">What JARVIS does</div>'
            '<p>An autonomous <b>long/short equity</b> analyst that turns the S&amp;P 500 into a '
            'market-neutral book — and explains every call. It runs a seven-layer pipeline daily:</p>'
            '<ol>'
            '<li><b>Scores</b> every name on 8 factors (momentum, value, quality, growth, revisions, '
            'short interest, insider &amp; institutional), ranked within its sector.</li>'
            '<li><b>Reads</b> 10-Ks, insider filings and risk factors with Claude for a qualitative overlay.</li>'
            '<li><b>Builds</b> the long/short book via mean-variance optimization with conviction tilts.</li>'
            '<li><b>Vetoes</b> trades against hard risk limits (beta, sector, liquidity, earnings) and circuit breakers.</li>'
            '<li><b>Executes</b> on Alpaca paper and reports — performance, attribution and a daily investors’ letter.</li>'
            '</ol>'
            '</div>', unsafe_allow_html=True)
    with right:
        uri = theme.robot_data_uri()
        if uri:
            st.markdown(f'<div class="robot" style="background-image:url({uri})"></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="robot fallback"><span class="accent mono" '
                        'style="font-size:40px;opacity:.45">◆ ◆ ◆</span></div>', unsafe_allow_html=True)


# ---------------- PAGE II: RESEARCH ----------------
FACS = ["momentum", "value", "quality", "growth", "revisions", "short_interest", "insider", "institutional"]
FAC_LABELS = ["Momentum", "Value", "Quality", "Growth", "Revisions", "Short Interest", "Insider", "Institutional"]


@st.cache_data(ttl=300, show_spinner=False)
def _target_for(method: str, asof: str):
    from portfolio import mvo_optimizer, optimizer as conv
    if method == "mvo":
        w, b, s, _ = mvo_optimizer.optimize()
    else:
        w, b, s = conv.construct_portfolio()
    sectors = {t: s.loc[t, "sector"] for t in w if t in s.index}
    return w, b, sectors


def _last_closes(tickers):
    if not tickers:
        return {}
    qs = ",".join("?" * len(tickers))
    df = _q(f"SELECT ticker, MAX(date) d, close FROM daily_prices WHERE ticker IN ({qs}) GROUP BY ticker", tickers)
    return dict(zip(df["ticker"], df["close"]))


def _render_analysis(t, cl):
    from analysis.base import AnalysisContext
    from run_analysis import analyze_ticker
    if not cl:
        if st.button("Analyze with Claude", key=f"an_{t}"):
            with st.spinner("Claude analyzing…"):
                analyze_ticker(AnalysisContext.create(), t)
            st.rerun()
        return
    f, r, ins = cl.get("filing"), cl.get("risk"), cl.get("insider")
    if f:
        st.markdown(f'<div class="an-h">Forensic financial — health {f.get("balance_sheet_score","?")}/10</div>',
                    unsafe_allow_html=True)
        st.write(f.get("one_line_summary", ""))
        if f.get("red_flags"):
            st.caption("Red flags: " + "; ".join(f["red_flags"][:3]))
    if r:
        st.markdown(f'<div class="an-h">10-K risk factors — severity {r.get("risk_severity","?")}</div>',
                    unsafe_allow_html=True)
        st.write(r.get("one_line_summary", ""))
    if ins:
        st.markdown(f'<div class="an-h">Insider activity — {ins.get("signal_strength","?")} '
                    f'(conf {ins.get("confidence","?")})</div>', unsafe_allow_html=True)
        st.write(ins.get("one_line_summary", ""))
    if st.button("Re-run Claude analysis", key=f"rr_{t}"):
        with get_conn() as conn:
            conn.execute("DELETE FROM analysis_results WHERE ticker=?", (t,))
        with st.spinner("Re-running…"):
            analyze_ticker(AnalysisContext.create(), t)
        st.rerun()


def _candidate(t, w, b, sc, prices, aum):
    weight, beta, price = w[t], b.get(t, 1.0), prices.get(t)
    shares = round(weight * aum / price) if price else 0
    notional = abs(shares * (price or 0))
    comp = sc.loc[t, "composite"] if t in sc.index else 0
    pio = sc.loc[t, "piotroski"] if t in sc.index else None
    alt = sc.loc[t, "altman_z"] if t in sc.index else None
    sector = sc.loc[t, "sector"] if t in sc.index else "?"
    zone = "safe" if (alt or 0) > 2.99 else "grey zone" if (alt or 0) >= 1.81 else "distress"
    col = theme.LONG if weight > 0 else theme.SHORT
    st.markdown(
        f'<div class="cand"><span class="sc" style="color:{col}">{comp:.0f}</span>'
        f'<span class="tkr">{t}</span> <span class="badge">{sector}</span>'
        f'<div class="meta">{abs(shares)} sh · ${notional:,.0f} · {abs(weight):.1%} · β {beta:.2f}</div>'
        f'<div class="fund">Piotroski {int(pio) if pio is not None else "—"}/9 · '
        f'<span class="amber">Altman-Z {alt:.1f}</span> · {zone}</div></div>'
        if alt is not None else
        f'<div class="cand"><span class="sc" style="color:{col}">{comp:.0f}</span>'
        f'<span class="tkr">{t}</span> <span class="badge">{sector}</span></div>',
        unsafe_allow_html=True)
    cl = cache.all_for_ticker(t)
    with st.expander(f"{t} — Claude analysis" if cl else f"{t} — analyze with Claude"):
        _render_analysis(t, cl)


def page_research():
    asof = _asof()
    method = "mvo"  # set after we read the radio below; placeholder for KPI cost calc

    # --- KPI cards ---
    m = jarvis.metrics()
    fdf = _q(f"SELECT {','.join(FACS)} FROM scores WHERE asof_date=?", (asof,))
    disp = fdf.std().sort_values(ascending=False)
    corr = fdf.corr().abs()
    pairs = int(((corr.values > 0.85).sum() - len(FACS)) // 2)
    sectors = int(_q("SELECT COUNT(DISTINCT sector) c FROM universe").iloc[0]["c"])
    kpis = [("Universe size", m["universe"], f"{sectors} sectors", "#f3f5fb"),
            ("Long candidates", m["long_candidates"], "top quintile per sector", theme.LONG),
            ("Short candidates", m["short_candidates"], "bottom quintile per sector", theme.SHORT),
            ("Highest-dispersion factor", FAC_LABELS[FACS.index(disp.index[0])], f"σ {disp.iloc[0]:.1f}", theme.ACCENT),
            ("Crowding warnings", pairs, "factor pairs flagged", theme.LONG if pairs == 0 else theme.SHORT)]
    for c, (l, v, s, col) in zip(st.columns(5), kpis):
        c.markdown(f'<div class="kpi"><div class="l">{l}</div>'
                   f'<div class="v" style="color:{col}">{v}</div><div class="s">{s}</div></div>',
                   unsafe_allow_html=True)

    # --- optimizer toggle ---
    st.write("")
    o1, o2, o3 = st.columns([34, 33, 33])
    with o1:
        st.markdown('<div class="l" style="color:#7e879f;letter-spacing:.12em">PORTFOLIO OPTIMIZER</div>',
                    unsafe_allow_html=True)
        method = st.radio("opt", ["mvo", "conviction"], horizontal=True, label_visibility="collapsed")
        st.caption("MVO: Markowitz, factor-cov, net-of-cost. Conviction: top-N equal-weight + tilts.")
    w, b, sectors_map = _target_for(method, asof)
    from portfolio import transaction_costs
    tc = transaction_costs.estimate(list(w))
    avg_bps = sum(d["total_bps"] for d in tc.values()) / max(len(tc), 1)
    o2.markdown(f'<div class="kpi"><div class="l">Active method</div>'
                f'<div class="v" style="color:{theme.ACCENT};font-size:30px">{method.upper()}</div>'
                f'<div class="s">Toggle changes the target used for sizing below.</div></div>', unsafe_allow_html=True)
    o3.markdown(f'<div class="kpi"><div class="l">Avg est. trade cost</div>'
                f'<div class="v">{avg_bps:.1f} bps</div>'
                f'<div class="s">spread + sqrt market impact, per-name</div></div>', unsafe_allow_html=True)

    # --- heatmap ---
    top = _q(f"SELECT ticker,{','.join(FACS)} FROM scores WHERE asof_date=? ORDER BY composite DESC LIMIT 30", (asof,))
    bot = _q(f"SELECT ticker,{','.join(FACS)} FROM scores WHERE asof_date=? ORDER BY composite ASC LIMIT 30", (asof,))
    heat = pd.concat([top, bot])
    if not heat.empty:
        fig = go.Figure(go.Heatmap(z=heat[FACS].values, x=FAC_LABELS, y=heat["ticker"],
                                   colorscale=[[0, theme.SHORT], [0.5, "#16203a"], [1, theme.LONG]], zmid=50))
        fig.update_layout(height=760, template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)", title="Factor scoring heatmap (top + bottom by composite)",
                          yaxis=dict(autorange="reversed"), margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # --- candidate cards ---
    sc = _q(f"SELECT ticker,composite,sector,piotroski,altman_z FROM scores WHERE asof_date=?", (asof,)).set_index("ticker")
    aum = float(cfg.get("portfolio.aum", 1_000_000))
    longs = sorted([t for t in w if w[t] > 0], key=lambda t: -w[t])[:10]
    shorts = sorted([t for t in w if w[t] < 0], key=lambda t: w[t])[:10]
    prices = _last_closes(longs + shorts)

    lc, sccol = st.columns(2)
    with lc:
        st.markdown('<div class="an-h">TOP 10 LONG CANDIDATES</div>', unsafe_allow_html=True)
        for t in longs:
            _candidate(t, w, b, sc, prices, aum)
    with sccol:
        st.markdown('<div class="an-h">TOP 10 SHORT CANDIDATES</div>', unsafe_allow_html=True)
        for t in shorts:
            _candidate(t, w, b, sc, prices, aum)

    # --- manual override (backstop for the automated Monday run) ---
    st.markdown("---")
    st.markdown("**Manual override**")
    from execution import autoexec_state
    auto_on = autoexec_state.is_enabled()
    st.caption(
        f"Trading is automated — the Monday 9:45 ET job is currently "
        f"{'🟢 ON' if auto_on else '⚪ OFF'} (toggle on the Execution page). Use this only to "
        "trade off-cycle: a missed Monday, or while auto is off. It places the *current* "
        "target book (the same one the automation uses), veto- and kill-switch-gated.")
    if st.button("Preview orders (dry-run)", use_container_width=False):
        from execution import executor
        with st.spinner("Pre-trade veto → dry-run…"):
            st.json(executor.run(dry_run=True))
    confirm = st.checkbox("I authorize placing PAPER orders now")
    if st.button("Execute now (manual override) →", type="primary", disabled=not confirm):
        from execution import executor
        with st.spinner("Pre-trade veto → Alpaca…"):
            st.json(executor.run(dry_run=False))


# ---------------- PAGE III: RISK ----------------
CORR_SCALE = [[0.0, "#6b1f4d"], [0.35, "#152036"], [0.7, "#1f7a6b"], [1.0, "#1bd1a5"]]
STRESS = {
    "crisis_2008": {"mkt": -0.20, "f": {"momentum": -0.03, "quality": 0.02}},
    "covid_2020": {"mkt": -0.18, "f": {"momentum": -0.02, "value": -0.03}},
    "rate_hikes_2022": {"mkt": -0.06, "f": {"growth": -0.04, "value": 0.03}},
    "sector_shock": {"mkt": -0.02, "f": {"institutional": -0.02}},
    "momentum_reversal": {"mkt": 0.0, "f": {"momentum": -0.06}},
    "short_squeeze": {"mkt": 0.01, "f": {"short_interest": -0.05}},
}


@st.cache_resource(show_spinner=False)
def _frm(asof: str):
    from risk.factor_risk_model import FactorRiskModel
    return FactorRiskModel().fit()


def _cb_bar(label, current, thresh):
    pct = min(1.0, abs(current) / thresh) if thresh else 0
    color = theme.SHORT if current <= -thresh else "#e0a106" if pct >= 0.5 else theme.LONG
    return (f'<div style="margin:12px 0"><div style="display:flex;justify-content:space-between;'
            f'font-size:13px;color:#aeb6cc"><span>{label}</span>'
            f'<span class="mono">{current:+.2%} of {thresh:.2%}</span></div>'
            f'<div style="background:#1b2438;border-radius:6px;height:9px;margin-top:5px">'
            f'<div style="width:{pct * 100:.0f}%;background:{color};height:9px;border-radius:6px"></div></div></div>')


def _credit_z():
    h = _q("SELECT adj_close FROM daily_prices WHERE ticker='HYG' ORDER BY date")["adj_close"].pct_change()
    t = _q("SELECT adj_close FROM daily_prices WHERE ticker='TLT' ORDER BY date")["adj_close"].pct_change()
    spread = (t - h).dropna()  # TLT outperforming HYG = credit stress (spreads widening)
    if len(spread) < 40:
        return None
    recent = spread.tail(10).mean()
    return float((recent - spread.mean()) / spread.std())


def page_risk():
    from risk.pre_trade import halt_active
    cb = cfg.get("risk.circuit_breakers", {})
    eq, rets = metrics.daily_nav(), metrics.returns()
    daily = float(rets.iloc[-1]) if len(rets) else 0.0
    weekly = (float(eq.iloc[-1] / eq.iloc[-6] - 1) if len(eq) > 6
              else float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) > 1 else 0.0)
    dd = metrics.drawdown()[1]
    level = ("HALT", theme.SHORT) if halt_active() else \
        ("WARN", "#e0a106") if (daily <= -cb["daily_loss_size_down"]["threshold"]
                                or weekly <= -cb["weekly_loss_size_down"]["threshold"]) else ("OK", theme.LONG)
    bars = (_cb_bar("Daily loss (warn at -1.5%)", daily, cb["daily_loss_size_down"]["threshold"])
            + _cb_bar("Daily loss (halt at -2.5%)", daily, cb["daily_loss_close_all"]["threshold"])
            + _cb_bar("Weekly loss (warn at -4%)", weekly, cb["weekly_loss_size_down"]["threshold"])
            + _cb_bar("Drawdown (KILL at -8%)", dd, cb["drawdown_kill_switch"]["threshold"]))
    st.markdown(f'<div class="card"><div class="l" style="letter-spacing:.14em">CIRCUIT BREAKERS · LEVEL '
                f'<span style="color:{level[1]}">{level[0]}</span></div>{bars}'
                f'<div class="mono" style="color:#8a93ad;margin-top:8px">Active actions: —</div></div>',
                unsafe_allow_html=True)

    # tail-risk KPIs
    v, _ = jarvis.vix()
    vchg = _q("SELECT adj_close FROM daily_prices WHERE ticker='^VIX' ORDER BY date DESC LIMIT 2")["adj_close"]
    vchg = (vchg.iloc[0] / vchg.iloc[1] - 1) if len(vchg) > 1 else 0.0
    cz = _credit_z()
    k = [("VIX", f"{v:.1f}" if v else "—", f"chg {vchg:+.2%}", theme.LONG if vchg <= 0 else theme.SHORT),
         ("Credit spread (HYG-TLT, z-score)", f"{cz:+.2f}σ" if cz is not None else "—",
          "positive = spreads widening", theme.SHORT if (cz or 0) > 0 else theme.LONG),
         ("Active gross-down actions", "—", "applied", "#f3f5fb")]
    for c, (l, val, s, col) in zip(st.columns(3), k):
        c.markdown(f'<div class="kpi"><div class="l">{l}</div><div class="v" style="color:{col}">{val}</div>'
                   f'<div class="s">{s}</div></div>', unsafe_allow_html=True)

    tp = _q("SELECT ticker,weight,sector,beta FROM target_portfolio "
            "WHERE asof_date=(SELECT MAX(asof_date) FROM target_portfolio)")
    if tp.empty:
        st.info("Build a target portfolio on the Research page to populate the risk model.")
        return
    w = dict(zip(tp.ticker, tp.weight))
    betas = dict(zip(tp.ticker, tp.beta.fillna(1.0)))
    aum = float(cfg.get("portfolio.aum", 1_000_000))

    try:
        frm = _frm(_asof())
        dec = frm.decompose(w)
        fc = frm.factor_contributions(w)
    except Exception as e:  # noqa: BLE001
        st.warning(f"Factor risk model unavailable: {e}")
        return

    # risk decomposition donut + vols
    st.write("")
    g1, g2, g3 = st.columns([34, 33, 33])
    fshare = dec["factor_share"] or 0
    donut = go.Figure(go.Pie(labels=["Factor (systematic)", "Specific"],
                             values=[dec["factor_var"], dec["specific_var"]], hole=.62, sort=False,
                             marker_colors=[theme.LONG, "#3b7fd1"], textinfo="label+percent"))
    donut.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", height=260,
                        showlegend=False, margin=dict(t=30, b=0, l=0, r=0), title="Risk decomposition")
    g1.plotly_chart(donut, use_container_width=True)
    g2.markdown(f'<div class="kpi"><div class="l">Total ann. vol</div><div class="v">{dec["annual_vol"]:.2%}</div>'
                f'<div class="s">predicted, factor-model based</div></div>', unsafe_allow_html=True)
    g3.markdown(f'<div class="kpi"><div class="l">Factor vol</div>'
                f'<div class="v" style="color:{theme.LONG}">{(dec["factor_var"] ** 0.5):.2%}</div>'
                f'<div class="s">{fshare:.0%} of variance</div></div>', unsafe_allow_html=True)

    # factor risk contributions + MCTR top 12
    cL, cR = st.columns(2)
    rows = ""
    for fac, d in sorted(fc.items(), key=lambda kv: -abs(kv[1]["share"])):
        sh = d["share"]
        rows += (f'<div style="display:flex;align-items:center;gap:10px;margin:8px 0">'
                 f'<span style="width:110px">{fac}</span>'
                 f'<span class="mono" style="width:80px;color:#8a93ad">exp {d["exposure"]:+.2f}</span>'
                 f'<div style="flex:1;background:#1b2438;border-radius:5px;height:8px">'
                 f'<div style="width:{min(100, abs(sh) * 100):.0f}%;background:{theme.LONG};height:8px;border-radius:5px"></div></div>'
                 f'<span class="mono" style="width:64px;text-align:right">{sh:+.1%}</span></div>')
    cL.markdown(f'<div class="card"><div class="l">FACTOR RISK CONTRIBUTIONS</div>'
                f'<div class="s" style="margin-bottom:8px">Each factor\'s share of total factor variance</div>'
                f'{rows}</div>', unsafe_allow_html=True)

    mrows = ""
    flags = set(dec["disproportionate_risk_flags"])
    for t, mp in sorted(dec["mctr_pct"].items(), key=lambda kv: -abs(kv[1]))[:12]:
        side = "L" if w.get(t, 0) > 0 else "S"
        scol = theme.LONG if side == "L" else theme.SHORT
        fire = " 🔥" if t in flags else ""
        mrows += (f'<div style="display:flex;align-items:center;gap:10px;margin:8px 0">'
                  f'<span style="width:70px"><b style="color:{scol}">{side}</b> {t}</span>'
                  f'<span class="mono" style="width:64px;color:#8a93ad">wt {abs(w.get(t, 0)):.1%}</span>'
                  f'<div style="flex:1;background:#1b2438;border-radius:5px;height:8px">'
                  f'<div style="width:{min(100, abs(mp) * 100):.0f}%;background:{scol};height:8px;border-radius:5px"></div></div>'
                  f'<span class="mono" style="width:74px;text-align:right">{mp:+.1%}{fire}</span></div>')
    cR.markdown(f'<div class="card"><div class="l">MARGINAL RISK CONTRIBUTORS — TOP 12</div>'
                f'<div class="s" style="margin-bottom:8px">Position MCTR · 🔥 = &gt;1.5× its weight in risk</div>'
                f'{mrows}</div>', unsafe_allow_html=True)

    # factor exposure spread + stress test
    sL, sR = st.columns(2)
    sc = _q(f"SELECT ticker,{','.join(FACS)} FROM scores WHERE asof_date=?", (_asof(),)).set_index("ticker")
    longs = [t for t in w if w[t] > 0 and t in sc.index]
    shorts = [t for t in w if w[t] < 0 and t in sc.index]
    spread = {FAC_LABELS[i]: (sc.loc[longs, f].mean() - sc.loc[shorts, f].mean())
              for i, f in enumerate(FACS)} if longs and shorts else {}
    if spread:
        ss = pd.Series(spread).sort_values()
        fig = go.Figure(go.Bar(x=ss.values, y=ss.index, orientation="h", marker_color=theme.LONG))
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", height=320,
                          title="Factor exposure spread — Long − Short (percentile pts)",
                          margin=dict(l=10, r=10, t=40, b=10))
        sL.plotly_chart(fig, use_container_width=True)

    Z, znames = frm.standardized_exposures(list(w))
    zb = np.array([betas.get(t, 1.0) for t in znames])
    zw = np.array([w[t] for t in znames])
    stress_rows = []
    for name, sh in STRESS.items():
        fvec = np.array([sh["f"].get(f, 0.0) for f in FACS])
        ret = zb * sh["mkt"] + Z @ fvec
        pnl = zw * aum * ret
        total = float(pnl.sum())
        long_pnl = float(pnl[zw > 0].sum())
        short_pnl = float(pnl[zw < 0].sum())
        stress_rows.append({"scenario": name, "P&L $": f"${total:,.0f}", "P&L %": f"{total / aum:+.2%}",
                            "Long $": f"${long_pnl:,.0f}", "Short $": f"${short_pnl:,.0f}"})
    sR.markdown('<div class="l" style="margin-bottom:6px">STRESS SCENARIOS</div>', unsafe_allow_html=True)
    sR.dataframe(pd.DataFrame(stress_rows), use_container_width=True, hide_index=True, height=260)

    # 60-day correlation heatmap + effective bets
    from portfolio import inputs
    book_tk = [t for t in w]
    r60 = inputs.returns(book_tk, 60).dropna(axis=1, how="any")
    if r60.shape[1] > 2:
        labels = [f"{t} ({'L' if w.get(t, 0) > 0 else 'S'})" for t in r60.columns]
        corr = r60.corr()
        fig = go.Figure(go.Heatmap(z=corr.values, x=labels, y=labels, colorscale=CORR_SCALE, zmin=-0.3, zmax=1))
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", height=560,
                          title="60-day return correlation", yaxis=dict(autorange="reversed"),
                          margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

        def eff_bets(cols):
            sub = r60[[c for c in cols if c in r60.columns]]
            if sub.shape[1] < 2:
                return sub.shape[1], 0.0
            cm = sub.corr().values
            eig = np.linalg.eigvalsh(cm)
            eig = eig[eig > 1e-9]
            ne = (eig.sum() ** 2) / np.square(eig).sum()
            avg = cm[np.triu_indices_from(cm, 1)].mean()
            return ne, avg
        ln, la = eff_bets(longs)
        sn, sa = eff_bets(shorts)
        e1, e2 = st.columns(2)
        e1.markdown(f'<div class="card"><div class="l">LONG BOOK DIVERSIFICATION</div>'
                    f'<div class="v" style="font-size:30px"><span class="mono">{ln:.2f}</span> '
                    f'<span class="s">effective bets / {len(longs)} positions</span></div>'
                    f'<div class="s">avg corr {la:.2f}</div></div>', unsafe_allow_html=True)
        e2.markdown(f'<div class="card"><div class="l">SHORT BOOK DIVERSIFICATION</div>'
                    f'<div class="v" style="font-size:30px"><span class="mono">{sn:.2f}</span> '
                    f'<span class="s">effective bets / {len(shorts)} positions</span></div>'
                    f'<div class="s">avg corr {sa:.2f}</div></div>', unsafe_allow_html=True)


# ---------------- PAGE IV: PERFORMANCE ----------------
RET_SCALE = [[0.0, theme.SHORT], [0.5, "#16203a"], [1.0, theme.LONG]]


def _kpi(col, label, value, sub, color="#f3f5fb"):
    col.markdown(f'<div class="kpi"><div class="l">{label}</div>'
                 f'<div class="v" style="color:{color}">{value}</div><div class="s">{sub}</div></div>',
                 unsafe_allow_html=True)


def page_performance():
    eq = metrics.daily_nav()
    # equity curve
    st.markdown("**Equity curve (rebased to 100)**")
    if len(eq) > 1:
        reb = eq / eq.iloc[0] * 100
        spy = metrics.spy_rebased(eq.index[0].date())
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=reb.index, y=reb.values, name="Portfolio",
                                 line=dict(color=theme.ACCENT, width=3)))
        if not spy.empty:
            fig.add_trace(go.Scatter(x=spy.index, y=spy.values, name="SPY",
                                     line=dict(color="#aeb6cc", width=1.5, dash="dot")))
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          height=340, margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(x=0.99, y=0.99, xanchor="right"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Equity history accrues as the intraday monitor records NAV (just launched).")

    # monthly returns heatmap | drawdown area
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Monthly returns (%)**")
        mr = metrics.monthly_returns()
        ytd = metrics.summary().get("total_return", 0) or 0
        cols, vals = [], []
        if not mr.empty:
            row = mr.iloc[-1]
            for mo in row.index:
                if pd.notna(row[mo]):
                    cols.append(calendar.month_abbr[int(mo)]); vals.append(float(row[mo]))
        cols.append("YTD"); vals.append(float(ytd))
        hm = go.Figure(go.Heatmap(z=[vals], x=cols, y=["2026"], colorscale=RET_SCALE, zmid=0,
                                  text=[[f"{v:+.1%}" for v in vals]], texttemplate="%{text}",
                                  colorbar=dict(tickformat=".0%")))
        hm.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", height=300,
                         margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(hm, use_container_width=True)
    with c2:
        st.markdown("**Drawdown (%)**")
        dd, _ = metrics.drawdown()
        if not dd.empty:
            fig = go.Figure(go.Scatter(x=dd.index, y=dd.values * 100, fill="tozeroy",
                                       line=dict(color=theme.SHORT), fillcolor="rgba(192,57,43,.35)"))
            fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              height=300, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No drawdown history yet.")

    # P&L attribution | rolling sharpe
    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**Daily P&L attribution (%)**")
        a = attribution.daily_attribution()
        if a:
            bars = go.Figure(go.Bar(x=["Beta", "Sector", "Factor", "Alpha"],
                                    y=[a["beta"] * 100, a["sector"] * 100, a["factor"] * 100, a["alpha_residual"] * 100],
                                    marker_color=["#3b7fd1", theme.ACCENT, "#e0a106", theme.LONG],
                                    text=[f"{a['beta']:+.2%}", f"{a['sector']:+.2%}", f"{a['factor']:+.2%}",
                                          f"{a['alpha_residual']:+.2%}"], textposition="outside"))
            bars.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                               height=300, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(bars, use_container_width=True)
    with c4:
        st.markdown("**Rolling 60-day Sharpe ratio**")
        r = metrics.returns()
        if len(r) >= 10:
            win = min(60, len(r))
            rs = r.rolling(win).apply(lambda x: x.mean() / x.std() * (252 ** 0.5) if x.std() else 0)
            fig = go.Figure(go.Scatter(x=rs.index, y=rs.values, line=dict(color=theme.ACCENT)))
            fig.add_hline(y=1.0, line_dash="dot", line_color="#8a93ad")
            fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              height=300, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Needs ~60 days of returns.")

    # sector-relative alpha | total card
    sra = attribution.sector_relative_alpha()
    c5, c6 = st.columns([68, 32])
    with c5:
        st.markdown("**Sector-relative performance — stock selection alpha (90d)**")
        if sra["sectors"]:
            s = pd.Series(sra["sectors"]).sort_values()
            fig = go.Figure(go.Bar(x=s.values * 100, y=s.index, orientation="h",
                                   marker_color=[theme.LONG if v > 0 else theme.SHORT for v in s.values],
                                   text=[f"{v:+.2%}" for v in s.values], textposition="outside"))
            fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              height=420, margin=dict(l=10, r=10, t=10, b=30),
                              xaxis_title="Contribution to book stock-selection alpha (%)")
            st.plotly_chart(fig, use_container_width=True)
    _kpi(c6, "Total stock-selection α (90d)", f"{sra['total_alpha']:+.2%}",
         f"winners {sra['winners']} · losers {sra['losers']}", theme.LONG if sra['total_alpha'] >= 0 else theme.SHORT)

    # turnover cards
    t = analytics.turnover(30)
    tax = analytics.tax_estimate()
    tk = st.columns(4, gap="medium")
    _kpi(tk[0], "Turnover (30d)", f"{t['turnover']:.1%}", f"{analytics.roundtrips().__len__()} round-trips · ${t['notional']:,.0f} notional")
    _kpi(tk[1], "Annualized turnover", f"{t['annualized']*100:.0f}%", "30d window × 12.17")
    _kpi(tk[2], "Vs. budget", f"{t['annualized']*100:.0f}% / {t['budget']*100:.0f}%",
         "annualized / budget", theme.LONG if t['vs_budget'] <= 0 else theme.SHORT)
    _kpi(tk[3], "Est. tax (realized YTD)", f"${tax['est_tax']:,.0f}", "ST/LT realized gains")

    # transaction-cost cards
    tp = _q("SELECT ticker FROM target_portfolio WHERE asof_date=(SELECT MAX(asof_date) FROM target_portfolio)")
    from execution import costs
    from portfolio import transaction_costs
    est = 0.0
    if not tp.empty:
        d = transaction_costs.estimate(list(tp.ticker))
        est = sum(x["total_bps"] for x in d.values()) / max(len(d), 1)
    slip = costs.slippage_stats()
    ck = st.columns(3, gap="medium")
    _kpi(ck[0], "Avg estimated cost", f"{est:.1f} bps", "MVO model: spread + sqrt impact")
    _kpi(ck[1], "Avg actual slippage", f"{slip['avg_bps']:+.1f} bps", f"over {slip['n']} orders, last 30d",
         theme.SHORT if slip['avg_bps'] > 0 else theme.LONG)
    _kpi(ck[2], "Model error", f"{slip['avg_bps'] - est:+.1f} bps", "actual vs estimate")

    # --- withdrawable earnings: profit above invested capital, net of the tax reserve ---
    from reporting import pnl
    try:
        acct = _account()
        profit = pnl.total_pnl(acct["equity"])           # equity - cost basis
        tax_owed = float(tax.get("est_tax", 0.0))         # `tax` computed in the turnover cards above
        withdrawable = max(0.0, profit - tax_owed)
        wk = st.columns(3, gap="medium")
        _kpi(wk[0], "Total profit", f"${profit:,.0f}", "equity − capital invested",
             theme.LONG if profit >= 0 else theme.SHORT)
        _kpi(wk[1], "Est. tax reserve", f"${tax_owed:,.0f}", "realized gains YTD")
        _kpi(wk[2], "Withdrawable earnings", f"${withdrawable:,.0f}",
             "profit after tax · principal kept", theme.ACCENT)
        st.caption(f"This is profit you could take while keeping your invested capital "
                   f"(${pnl.cost_basis():,.0f}) and a tax reserve intact. Actually moving it out "
                   f"is also capped by settled cash (${acct['cash']:,.0f}) — the book is ~fully "
                   "invested, so you'd sell to raise cash first.")
    except Exception as e:  # noqa: BLE001
        st.caption(f"Withdrawable figure unavailable: {e}")

    # --- cash flows (deposits / withdrawals) — keep P&L accurate across transfers ---
    with st.expander(f"Cash flows — log a deposit / withdrawal  ·  net so far ${pnl.net_flows():,.0f}"):
        st.caption("Record money you add to or pull out of the account so Total P&L reflects "
                   "*strategy performance*, not transfers. (Paper account = mostly for testing now.)")
        f1, f2, f3 = st.columns([30, 40, 30])
        kind = f1.selectbox("Type", ["Withdrawal", "Deposit"])
        amt = f2.number_input("Amount ($)", min_value=0.0, step=500.0, value=0.0)
        note = f3.text_input("Note", placeholder="optional")
        if st.button("Record cash flow", disabled=amt <= 0):
            pnl.record(-amt if kind == "Withdrawal" else amt, note)
            st.cache_data.clear()
            st.rerun()
        hist = pnl.history(10)
        if hist:
            st.dataframe(pd.DataFrame(hist).rename(columns={"ts": "when", "amount": "amount ($)"}),
                         use_container_width=True, hide_index=True)

    # win/loss + weekly commentary
    wl = analytics.win_loss()
    if wl["n"] == 0:
        st.markdown(theme.card("<div class='l'>WIN/LOSS ANALYSIS</div>"
                               "Need closed round-trips before win-rate stats are meaningful."), unsafe_allow_html=True)
    else:
        st.markdown(theme.card(f"<div class='l'>WIN/LOSS ANALYSIS</div>n={wl['n']} · win rate "
                               f"{wl['win_rate']:.0%} · P/L ratio {wl['pl_ratio']}"), unsafe_allow_html=True)

    st.markdown("**Claude weekly commentary**")
    if st.button("Generate weekly commentary"):
        with st.spinner("JARVIS writing…"):
            txt = jarvis.weekly_commentary(regenerate=True)
        st.markdown(theme.card(txt.replace("\n", "<br>")), unsafe_allow_html=True)
    else:
        cached = jarvis._one("SELECT content FROM jarvis_commentary ORDER BY created_at DESC LIMIT 1")
        st.markdown(theme.card(cached["content"].replace("\n", "<br>") if cached
                               else "Click <b>Generate</b> for the JARVIS weekly commentary."), unsafe_allow_html=True)


# ---------------- PAGE V: EXECUTION ----------------
def page_execution():
    from execution import autoexec_state, costs

    # Monday auto-execution on/off (no cron editing; state persists across deploys)
    cur = autoexec_state.is_enabled()
    tnew = st.toggle(
        "Monday auto-execution", value=cur,
        help="ON: the Monday 9:45 ET job auto-places the rebuilt book (veto- and "
             "kill-switch-gated, sized off live equity) and emails you. OFF: it's paused "
             "and you execute manually.")
    if tnew != cur:
        autoexec_state.set_enabled(tnew)
        st.rerun()
    st.caption(("🟢 Auto-execution **ON** — next run Monday 9:45 AM ET."
                if tnew else "⚪ Auto-execution **OFF** — paused; run manually."))

    s = costs.slippage_stats()
    notional30 = _q("SELECT COALESCE(SUM(notional),0) n FROM orders WHERE fill_price IS NOT NULL "
                    "AND ts>=datetime('now','-30 day')").iloc[0]["n"]
    db_total = int(_q("SELECT COUNT(*) c FROM orders WHERE fill_price IS NOT NULL").iloc[0]["c"])

    open_list, alpaca_err = [], None
    try:
        from execution.broker import Broker
        broker = Broker()
        open_list = broker.open_orders()
    except Exception as e:  # noqa: BLE001
        alpaca_err = str(e)

    k = st.columns(4)
    _kpi(k[0], "Filled orders (last 30d)", s["n"], f"total notional ${notional30:,.0f}")
    _kpi(k[1], "Avg slippage", f"{s['avg_bps']:.1f} bps", f"p95 {s['p95_bps']:.1f} bps")
    _kpi(k[2], "Total slippage cost (30d)", f"${s['total_dollar_cost']:,.0f}", "positive = cost to fund",
         theme.SHORT if s['total_dollar_cost'] > 0 else theme.LONG)
    _kpi(k[3], "Open orders", len(open_list), f"{db_total} filled in DB total")

    # open orders
    st.write("")
    if alpaca_err:
        st.markdown(theme.card(f"<div class='l'>OPEN ORDERS</div>Alpaca unavailable: {alpaca_err}"), unsafe_allow_html=True)
    elif not open_list:
        st.markdown(theme.card("<div class='l'>OPEN ORDERS</div>"
                               "<span class='mono' style='color:#8a93ad'>No pending orders.</span>"), unsafe_allow_html=True)
    else:
        oo = pd.DataFrame([{"submitted_at": str(o.submitted_at), "ticker": o.symbol, "side": str(o.side.value),
                            "qty": float(o.qty), "limit": float(o.limit_price or 0),
                            "filled": float(o.filled_qty or 0), "status": str(o.status.value)} for o in open_list])
        st.markdown("<div class='l'>OPEN ORDERS</div>", unsafe_allow_html=True)
        st.dataframe(oo, use_container_width=True, hide_index=True)

    # recent trades
    st.markdown("<div class='l' style='margin-top:8px'>RECENT TRADES — LAST 200</div>", unsafe_allow_html=True)
    recent = _q("SELECT ts AS submitted_at, ticker, side AS action, shares AS qty, limit_price, "
                "fill_price, slippage_bps FROM orders ORDER BY ts DESC LIMIT 200")
    st.dataframe(recent, use_container_width=True, height=360, hide_index=True)

    # worst fills + short availability + daily notional turnover
    w1, w2 = st.columns(2)
    with w1:
        st.markdown("<div class='l'>WORST 5 FILLS</div>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(costs.worst_fills(5)), use_container_width=True, hide_index=True)
    with w2:
        st.markdown("<div class='l'>SHORT AVAILABILITY (current shorts)</div>", unsafe_allow_html=True)
        sa = _q("SELECT s.ticker, s.shortable, s.easy_to_borrow FROM short_availability s "
                "JOIN target_portfolio t ON t.ticker=s.ticker AND t.weight<0 "
                "WHERE t.asof_date=(SELECT MAX(asof_date) FROM target_portfolio)")
        st.dataframe(sa if not sa.empty else pd.DataFrame({"info": ["no short-availability data cached"]}),
                     use_container_width=True, hide_index=True)

    st.markdown("<div class='l' style='margin-top:8px'>DAILY NOTIONAL TURNOVER</div>", unsafe_allow_html=True)
    dnt = _q("SELECT substr(ts,1,10) AS date, COUNT(*) AS orders, ROUND(SUM(notional),0) AS notional "
             "FROM orders WHERE fill_price IS NOT NULL GROUP BY date ORDER BY date DESC LIMIT 30")
    st.dataframe(dnt if not dnt.empty else pd.DataFrame({"info": ["no fills yet"]}),
                 use_container_width=True, hide_index=True)


# ---------------- PAGE VI: LETTER ----------------
def page_letter():
    st.markdown("## Daily Investors' Letter")
    doc_id = f"MHF-IM-{date.today():%Y-%m%d}"
    aum = "—"
    try:
        from execution.broker import Broker
        aum = f"${float(Broker().equity()):,.0f}"
    except Exception:  # noqa: BLE001
        pass
    head = (f"<div class='card'><div style='display:flex;justify-content:space-between'>"
            f"<div><b style='font-size:20px'>{cfg.get('fund.name')}</b><br>"
            f"<span class='badge'>Domicile: {cfg.get('fund.domicile')}</span> "
            f"<span class='badge'>Inception: {cfg.get('fund.inception')}</span> "
            f"<span class='badge'>AUM: {aum}</span></div>"
            f"<div style='text-align:right'><span class='badge'>{doc_id}</span><br>"
            f"<span class='badge'>{date.today():%Y-%m-%d}</span></div></div>"
            f"<div class='pill' style='background:{theme.SHORT};margin-top:8px'>CONFIDENTIAL • INVESTORS ONLY</div></div>")
    st.markdown(head, unsafe_allow_html=True)

    regen = st.button("Regenerate letter")
    with st.spinner("JARVIS composing…" if regen else "Loading…"):
        body = jarvis.lp_letter(regenerate=regen)
    st.markdown(theme.card("Dear Investors,<br><br>" + body.replace("Dear Investors,", "").replace("Dear Limited Partners,", "").strip().replace("\n", "<br>")
                           + "<br><br>—<br><b>JARVIS</b><br><span class='badge'>Mediajedi Hedge Fund</span>"
                           + "<br><br><span class='badge'>This letter is for informational purposes only and does not "
                             "constitute investment advice or an offer to sell securities. Past performance is not "
                             "indicative of future results. Paper-trading simulation.</span>"), unsafe_allow_html=True)


PAGE_FNS = [page_portfolio, page_research, page_risk, page_performance, page_execution, page_letter]
try:
    PAGE_FNS[page]()
except Exception as e:  # noqa: BLE001
    st.error(f"Page error: {e}")

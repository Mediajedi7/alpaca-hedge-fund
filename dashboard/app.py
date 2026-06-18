"""Meridian Capital Partners — JARVIS dashboard (Streamlit, LAN-only :8502).
6 pages: Portfolio cover, Research, Risk, Performance, Execution, LP Letter."""
from __future__ import annotations

import os
import sys

# `streamlit run dashboard/app.py` puts dashboard/ on sys.path, not the repo root —
# add the repo root so `core`, `reporting`, etc. import cleanly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

st.set_page_config(page_title="JARVIS — Meridian Capital", layout="wide", page_icon="◆")
st.markdown(theme.css(), unsafe_allow_html=True)

NAV = [("I", "PORTFOLIO"), ("II", "RESEARCH"), ("III", "RISK"),
       ("IV", "PERFORMANCE"), ("V", "EXECUTION"), ("VI", "LETTER")]
try:
    page = int(st.query_params.get("page", 0))
except (TypeError, ValueError):
    page = 0
page = max(0, min(page, len(NAV) - 1))
if "jarvis_history" not in st.session_state:
    st.session_state.jarvis_history = []

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
def page_portfolio():
    m = jarvis.metrics()
    left, right = st.columns([44, 56], gap="large")
    with left:
        st.markdown('<div class="jarvis">JARVIS</div>'
                    '<div class="subtitle">Long / Short Hedge Fund Analyst</div>', unsafe_allow_html=True)
        q = st.text_input("ask", placeholder="Ask anything…", label_visibility="collapsed")
        asked = st.button("ASK JARVIS", type="primary")

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


def _candidate(t, w, b, sc, prices, aum, decisions):
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
    a, rj, rs = st.columns(3)
    if a.button("Approve", key=f"ap_{t}", type="primary", use_container_width=True):
        decisions[t] = "approved"
    if rj.button("Reject", key=f"rj_{t}", use_container_width=True):
        decisions[t] = "rejected"
    if rs.button("Reset", key=f"rs_{t}", use_container_width=True):
        decisions.pop(t, None)
    if t in decisions:
        st.caption(f"→ {decisions[t].upper()}")
    cl = cache.all_for_ticker(t)
    with st.expander(f"{t} — Claude analysis" if cl else f"{t} — analyze with Claude"):
        _render_analysis(t, cl)


def page_research():
    asof = _asof()
    decisions = st.session_state.setdefault("decisions", {})
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
            _candidate(t, w, b, sc, prices, aum, decisions)
    with sccol:
        st.markdown('<div class="an-h">TOP 10 SHORT CANDIDATES</div>', unsafe_allow_html=True)
        for t in shorts:
            _candidate(t, w, b, sc, prices, aum, decisions)

    # --- execute approved ---
    st.markdown("---")
    n_app = sum(1 for v in decisions.values() if v == "approved")
    n_rej = sum(1 for v in decisions.values() if v == "rejected")
    st.caption(f"Approved {n_app} · Rejected {n_rej} (rejected names are dropped from the target)")
    confirm = st.checkbox("I authorize placing PAPER orders")
    if st.button("Build target & Execute (paper) →", type="primary", disabled=not confirm):
        from portfolio import construct
        from execution import executor
        keep = {t: wt for t, wt in w.items() if decisions.get(t) != "rejected"}
        construct.store_target(method, keep, b, sc.assign(score=sc["composite"]))
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
def page_performance():
    st.markdown("## Performance")
    m = metrics.summary()
    for c, (lab, key) in zip(st.columns(5), [("NAV", "nav"), ("Total ret", "total_return"),
                             ("Ann vol", "ann_vol"), ("Sharpe", "sharpe"), ("Max DD", "max_drawdown")]):
        c.markdown(theme.metric(lab, m.get(key, "—")), unsafe_allow_html=True)

    eq = metrics.daily_nav()
    if len(eq) > 1:
        reb = eq / eq.iloc[0] * 100
        spy = metrics.spy_rebased(eq.index[0].date())
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=reb.index, y=reb.values, name="Fund", line=dict(color=theme.ACCENT)))
        if not spy.empty:
            fig.add_trace(go.Scatter(x=spy.index, y=spy.values, name="SPY", line=dict(color="#8a93ad")))
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", height=320,
                          title="Equity vs SPY (rebased 100)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Equity history accrues as the intraday monitor records NAV (just launched).")

    a = attribution.daily_attribution()
    if a:
        bars = go.Figure(go.Bar(x=["Beta", "Sector", "Factor", "Alpha"],
                                y=[a["beta"], a["sector"], a["factor"], a["alpha_residual"]],
                                marker_color=[theme.ACCENT, "#6b7aa8", "#9aa4bf", theme.LONG]))
        bars.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", height=280,
                           title="Daily P&L attribution")
        st.plotly_chart(bars, use_container_width=True)

    sra = attribution.sector_relative_alpha()
    t = analytics.turnover(30)
    wl = analytics.win_loss()
    c1, c2, c3 = st.columns(3)
    c1.markdown(theme.card(f"<b>Sector-relative alpha (90d)</b><br>Total: <span class='mono'>{sra['total_alpha']:+.2%}</span>"
                           f"<br>Winners {sra['winners']} · Losers {sra['losers']}"), unsafe_allow_html=True)
    c2.markdown(theme.card(f"<b>Turnover</b><br>30d {t['turnover']:.1%} · ann {t['annualized']:.1f}x"
                           f"<br>budget {t['budget']}x ({t['vs_budget']:+.1f})"), unsafe_allow_html=True)
    c3.markdown(theme.card(f"<b>Win/Loss</b><br>n={wl['n']} · win {wl['win_rate'] if wl['win_rate'] is not None else '—'}"
                           f"<br>P/L ratio {wl['pl_ratio'] if wl['pl_ratio'] is not None else '—'}"), unsafe_allow_html=True)

    st.markdown("#### Weekly commentary")
    if st.button("Generate weekly commentary (Claude)"):
        with st.spinner("JARVIS writing…"):
            st.markdown(theme.card(jarvis.weekly_commentary(regenerate=True).replace("\n", "<br>")), unsafe_allow_html=True)
    else:
        cached = jarvis._one("SELECT content FROM jarvis_commentary ORDER BY created_at DESC LIMIT 1")
        if cached:
            st.markdown(theme.card(cached["content"].replace("\n", "<br>")), unsafe_allow_html=True)


# ---------------- PAGE V: EXECUTION ----------------
def page_execution():
    st.markdown("## Execution")
    from execution import costs
    s = costs.slippage_stats()
    for c, (lab, v) in zip(st.columns(4), [("Filled (30d)", s["n"]), ("Avg slip bps", s["avg_bps"]),
                           ("Total slip $", s["total_dollar_cost"]), ("Worst bps", s["p95_bps"])]):
        c.markdown(theme.metric(lab, v), unsafe_allow_html=True)

    st.markdown("#### Recent trades")
    recent = _q("SELECT ts,ticker,side,shares,limit_price,fill_price,slippage_bps,status FROM orders "
                "ORDER BY ts DESC LIMIT 200")
    st.dataframe(recent, use_container_width=True, height=300)

    st.markdown("#### Worst 5 fills")
    st.dataframe(pd.DataFrame(costs.worst_fills(5)), use_container_width=True)

    with st.expander("Live Alpaca positions / open orders"):
        try:
            from execution.broker import Broker
            b = Broker()
            pos = b.positions()
            st.write({s: {"qty": p.qty, "mv": p.market_value, "uPL": p.unrealized_pl}
                      for s, p in pos.items()} or "No open positions")
        except Exception as e:  # noqa: BLE001
            st.warning(f"Alpaca unavailable: {e}")


# ---------------- PAGE VI: LETTER ----------------
def page_letter():
    st.markdown("## Limited Partner Letter")
    doc_id = f"MCP-IM-{date.today():%Y-%m%d}"
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
            f"<div class='pill' style='background:{theme.SHORT};margin-top:8px'>CONFIDENTIAL • LIMITED PARTNERS ONLY</div></div>")
    st.markdown(head, unsafe_allow_html=True)

    regen = st.button("Regenerate letter")
    with st.spinner("JARVIS composing…" if regen else "Loading…"):
        body = jarvis.lp_letter(regenerate=regen)
    st.markdown(theme.card("Dear Limited Partners,<br><br>" + body.replace("Dear Limited Partners,", "").strip().replace("\n", "<br>")
                           + "<br><br>—<br><b>JARVIS</b><br><span class='badge'>Meridian Capital Partners</span>"
                           + "<br><br><span class='badge'>This letter is for informational purposes only and does not "
                             "constitute investment advice or an offer to sell securities. Past performance is not "
                             "indicative of future results. Paper-trading simulation.</span>"), unsafe_allow_html=True)


PAGE_FNS = [page_portfolio, page_research, page_risk, page_performance, page_execution, page_letter]
try:
    PAGE_FNS[page]()
except Exception as e:  # noqa: BLE001
    st.error(f"Page error: {e}")

# fixed bottom pill nav (query-param links — true bottom bar like the reference)
nav_html = '<div class="navbar">' + "".join(
    f'<a target="_self" href="?page={i}" class="{"active" if i == page else ""}">'
    f'<span class="rn">{rn}</span>{label}</a>' for i, (rn, label) in enumerate(NAV)
) + "</div>"
st.markdown(nav_html, unsafe_allow_html=True)

"""Operational health check: data freshness, execution readiness, broker, target veto."""
from core.db import get_conn
from execution import autoexec_state
from risk.pre_trade import halt_active, screen_target


def q1(sql):
    with get_conn() as c:
        r = c.execute(sql).fetchone()
        return r[0] if r else None


print("== DATA ==")
print("latest scores  :", q1("SELECT MAX(asof_date) FROM scores"))
print("latest prices  :", q1("SELECT MAX(date) FROM daily_prices"))
asof = q1("SELECT MAX(asof_date) FROM target_portfolio")
n = q1("SELECT COUNT(*) FROM target_portfolio WHERE asof_date=(SELECT MAX(asof_date) FROM target_portfolio)")
print("target book    :", asof, f"({n} names)")

print("\n== EXECUTION READINESS ==")
print("HALT lock      :", "ACTIVE (blocks trading)" if halt_active() else "clear")
print("auto-exec      :", "ON" if autoexec_state.is_enabled() else "OFF")

equity = None
try:
    from execution.broker import Broker
    b = Broker()
    a = b.account()
    equity = float(a.equity)
    print(f"alpaca         : status={a.status} equity=${equity:,.2f} cash=${float(a.cash):,.2f}")
    print("market open    :", b.is_market_open())
except Exception as e:  # noqa: BLE001
    print("alpaca         : ERROR", e)

try:
    with get_conn() as c:
        rows = c.execute("SELECT ticker,weight,beta,sector FROM target_portfolio WHERE asof_date=?",
                         (asof,)).fetchall()
    w = {r["ticker"]: r["weight"] for r in rows}
    betas = {r["ticker"]: (r["beta"] if r["beta"] is not None else 1.0) for r in rows}
    sec = {r["ticker"]: r["sector"] for r in rows}
    scr = screen_target(w, betas, sec, aum=equity or 100_000)
    agg = scr["aggregate"]
    ok = all(agg[k] for k in ("gross_ok", "net_ok", "net_beta_ok", "sector_ok"))
    print(f"target veto    : {'PASS' if ok else 'FAIL'} "
          f"(approved {len(scr['approved'])}, net_beta {agg['net_beta']:.3f}, gross {agg['gross']:.2f})")
except Exception as e:  # noqa: BLE001
    print("target veto    : ERROR", e)

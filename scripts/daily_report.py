"""Daily report email — runs 5:00 PM ET weekdays (same time as the day-trader EOD).

Summarises the live paper book: balance, today's P&L, total P&L (cash-flow aware),
book exposure (gross/net/beta), and the day's biggest movers. HTML styled to match the
day-trader emails (light card, green accents, dark-header tables, mobile-stacking).

  python3 -m scripts.daily_report            # build + send
  python3 -m scripts.daily_report --dry-run  # build + print, do not send
"""
from __future__ import annotations

import argparse
from datetime import date

from core.log import get_logger
from core.notify import send_email
from execution.broker import Broker
from portfolio import inputs
from reporting import pnl

log = get_logger("daily_report")

# Styling mirrored from the day-trader EOD email (light theme, email-tested).
STYLE = """
<style>
  * { box-sizing: border-box; }
  body { margin:0; padding:0; font-family: Arial, sans-serif; font-size:15px;
         color:#222; background:#f5f5f5; -webkit-text-size-adjust:100%; }
  .wrapper { width:100%; background:#f5f5f5; padding:12px 0; }
  .container { max-width:640px; margin:0 auto; background:#fff; border-radius:8px;
               padding:20px 16px; box-shadow:0 2px 8px rgba(0,0,0,0.1); }
  .paper-banner { background:#fff3cd; border:1px solid #ffc107; border-radius:6px;
                  padding:10px 14px; margin-bottom:16px; font-size:13px; font-weight:bold;
                  color:#856404; text-align:center; }
  h1 { color:#1a1a2e; font-size:20px; border-bottom:2px solid #4CAF50;
       padding-bottom:8px; margin:0 0 6px; }
  .date { color:#777; font-size:13px; margin:0 0 16px; }
  h2 { color:#1a1a2e; font-size:15px; margin-top:24px; margin-bottom:8px;
       border-left:4px solid #4CAF50; padding-left:10px; }
  .stats-grid { display:table; width:100%; border-collapse:collapse; background:#f0f7f0;
                border:1px solid #c8e6c9; border-radius:6px; margin:12px 0; }
  .stat-cell { display:table-cell; padding:12px 14px; vertical-align:top;
               border-right:1px solid #c8e6c9; }
  .stat-cell:last-child { border-right:none; }
  .stat-label { font-size:11px; color:#555; text-transform:uppercase;
                letter-spacing:0.5px; margin-bottom:4px; }
  .stat-value { font-size:20px; font-weight:bold; color:#2e7d32; }
  .stat-value.red { color:#c62828; }
  .stat-sub { font-size:12px; color:#777; margin-top:2px; }
  table { width:100%; border-collapse:collapse; margin-top:4px; }
  th { background:#1a1a2e; color:#fff; padding:9px 10px; text-align:left; font-size:12px; }
  td { padding:8px 10px; border-bottom:1px solid #eee; font-size:13px; }
  tr:last-child td { border-bottom:none; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .green { color:#2e7d32; font-weight:bold; }
  .red { color:#c62828; font-weight:bold; }
  .footer { margin-top:28px; font-size:11px; color:#aaa; border-top:1px solid #eee;
            padding-top:12px; text-align:center; }
  .footer a { color:#4CAF50; text-decoration:none; }
  @media only screen and (max-width:480px) {
    .container { padding:14px 10px; border-radius:0; }
    h1 { font-size:17px; }
    .stats-grid { display:block; }
    .stat-cell { display:block; border-right:none; border-bottom:1px solid #c8e6c9; }
    .stat-cell:last-child { border-bottom:none; }
  }
</style>
"""


def _cls(v):
    return "green" if v >= 0 else "red"


def _movers_table(rows) -> str:
    body = ""
    for sym, p in rows:
        side = "LONG" if p.qty > 0 else "SHORT"
        body += (f"<tr><td><b>{sym}</b></td><td>{side}</td>"
                 f"<td class='num'>${abs(p.market_value):,.0f}</td>"
                 f"<td class='num {_cls(p.unrealized_pl)}'>{p.unrealized_pl:+,.0f}</td></tr>")
    return ("<table><tr><th>Ticker</th><th>Side</th><th>Mkt value</th>"
            f"<th style='text-align:right'>Unreal. P&amp;L</th></tr>{body}</table>")


def build() -> tuple[str, str, str]:
    """Return (subject, plain_text, html)."""
    b = Broker()
    a = b.account()
    pos = b.positions()
    eq, le = float(a.equity), float(a.last_equity)
    day = pnl.today_pnl(eq, le)
    tot = pnl.total_pnl(eq)
    basis = pnl.cost_basis()
    dpct = (day / le * 100) if le else 0.0
    tpct = (tot / basis * 100) if basis else 0.0

    betas = inputs.betas(list(pos))
    gross = sum(abs(p.market_value) for p in pos.values())
    net = sum(p.market_value for p in pos.values())
    nbeta = sum((p.market_value / eq) * betas.get(s, 1.0) for s, p in pos.items()) if eq else 0.0
    upl = sum(p.unrealized_pl for p in pos.values())
    nL = sum(1 for p in pos.values() if p.qty > 0)
    nS = sum(1 for p in pos.values() if p.qty < 0)

    ranked = sorted(pos.items(), key=lambda x: x[1].unrealized_pl)
    losers = ranked[:5]
    winners = ranked[::-1][:5]

    today = date.today().strftime("%A, %B %-d, %Y")
    subject = f"[Mediajedi HF] Daily Report {date.today():%Y-%m-%d} — {day:+,.0f} ({dpct:+.2f}%)"

    html = f"""<html><head>{STYLE}</head><body><div class="wrapper"><div class="container">
      <div class="paper-banner">PAPER TRADING · simulated funds</div>
      <h1>Mediajedi Hedge Fund — Daily Report</h1>
      <p class="date">{today}</p>
      <div class="stats-grid">
        <div class="stat-cell"><div class="stat-label">Account balance</div>
          <div class="stat-value">${eq:,.0f}</div><div class="stat-sub">${float(a.cash):,.0f} cash</div></div>
        <div class="stat-cell"><div class="stat-label">Today's P&amp;L</div>
          <div class="stat-value {_cls(day)}">{day:+,.0f}</div><div class="stat-sub">{dpct:+.2f}%</div></div>
        <div class="stat-cell"><div class="stat-label">Total P&amp;L</div>
          <div class="stat-value {_cls(tot)}">{tot:+,.0f}</div><div class="stat-sub">{tpct:+.2f}% on ${basis:,.0f}</div></div>
      </div>
      <h2>Book</h2>
      <div class="stats-grid">
        <div class="stat-cell"><div class="stat-label">Positions</div><div class="stat-value">{len(pos)}</div><div class="stat-sub">{nL}L / {nS}S</div></div>
        <div class="stat-cell"><div class="stat-label">Gross</div><div class="stat-value">{gross/eq:.2f}x</div><div class="stat-sub">${gross:,.0f}</div></div>
        <div class="stat-cell"><div class="stat-label">Net</div><div class="stat-value">{net/eq:+.1%}</div><div class="stat-sub">market exposure</div></div>
        <div class="stat-cell"><div class="stat-label">Net beta</div><div class="stat-value">{nbeta:+.2f}</div><div class="stat-sub">unrealized {upl:+,.0f}</div></div>
      </div>
      <h2>Top winners</h2>{_movers_table(winners)}
      <h2>Top losers</h2>{_movers_table(losers)}
      <div class="footer">Mediajedi Hedge Fund · automated daily report ·
        <a href="https://jarvis.mediajedi.net">open dashboard</a><br>
        Not investment advice. Paper-trading simulation.</div>
    </div></div></body></html>"""

    plain = (f"Mediajedi Hedge Fund — Daily Report ({today})\n\n"
             f"Balance: ${eq:,.0f} ({float(a.cash):,.0f} cash)\n"
             f"Today's P&L: {day:+,.0f} ({dpct:+.2f}%)\n"
             f"Total P&L: {tot:+,.0f} ({tpct:+.2f}% on ${basis:,.0f})\n"
             f"Book: {len(pos)} ({nL}L/{nS}S), gross {gross/eq:.2f}x, net {net/eq:+.1%}, "
             f"beta {nbeta:+.2f}, unrealized {upl:+,.0f}\n"
             f"Winners: {', '.join(f'{s} {p.unrealized_pl:+.0f}' for s,p in winners)}\n"
             f"Losers: {', '.join(f'{s} {p.unrealized_pl:+.0f}' for s,p in losers)}\n")
    return subject, plain, html


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily report email")
    ap.add_argument("--dry-run", action="store_true", help="build + print, do not send")
    args = ap.parse_args()
    subject, plain, html = build()
    if args.dry_run:
        print(subject)
        print(plain)
        print(f"[dry-run] HTML {len(html)} chars — not sent")
        return
    ok = send_email(subject, plain, html=html)
    print("sent:" if ok else "send FAILED:", subject)


if __name__ == "__main__":
    main()

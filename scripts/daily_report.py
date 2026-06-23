"""Daily report email — runs 5:00 PM ET weekdays (same time as the day-trader EOD).

Summarises the live paper book: balance, today's P&L, total P&L (cash-flow aware), book
exposure (gross/net/beta), JARVIS's daily commentary, and the day's biggest movers.
HTML uses the shared core.notify template (matches the day-trader emails).

  python3 -m scripts.daily_report            # build + send
  python3 -m scripts.daily_report --dry-run  # build + print, do not send
"""
from __future__ import annotations

import argparse
from datetime import date

from core.log import get_logger
from core.notify import html_email, send_email
from execution.broker import Broker
from portfolio import inputs
from reporting import jarvis, pnl

log = get_logger("daily_report")


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


def _commentary_html() -> str:
    """JARVIS's daily letter (cached per day). Omitted if unavailable."""
    try:
        letter = jarvis.lp_letter()
        paras = "".join(f"<p>{p.strip()}</p>" for p in letter.split("\n\n") if p.strip())
        return f'<h2>JARVIS commentary</h2><div class="letter">{paras}</div>' if paras else ""
    except Exception as e:  # noqa: BLE001
        log.warning("commentary unavailable: %s", e)
        return ""


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
    losers, winners = ranked[:5], ranked[::-1][:5]

    today = date.today().strftime("%A, %B %-d, %Y")
    subject = f"[Mediajedi HF] Daily Report {date.today():%Y-%m-%d} — {day:+,.0f} ({dpct:+.2f}%)"

    inner = f"""
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
        <div class="stat-cell"><div class="stat-label">Gross</div><div class="stat-value">{(gross/eq if eq else 0):.2f}x</div><div class="stat-sub">${gross:,.0f}</div></div>
        <div class="stat-cell"><div class="stat-label">Net</div><div class="stat-value">{(net/eq if eq else 0):+.1%}</div><div class="stat-sub">market exposure</div></div>
        <div class="stat-cell"><div class="stat-label">Net beta</div><div class="stat-value">{nbeta:+.2f}</div><div class="stat-sub">unrealized {upl:+,.0f}</div></div>
      </div>
      <h2>Top winners</h2>{_movers_table(winners)}
      <h2>Top losers</h2>{_movers_table(losers)}
      {_commentary_html()}
    """
    html = html_email("Mediajedi Hedge Fund — Daily Report", inner, subtitle=today)

    plain = (f"Mediajedi Hedge Fund — Daily Report ({today})\n\n"
             f"Balance: ${eq:,.0f} (${float(a.cash):,.0f} cash)\n"
             f"Today's P&L: {day:+,.0f} ({dpct:+.2f}%)\n"
             f"Total P&L: {tot:+,.0f} ({tpct:+.2f}% on ${basis:,.0f})\n"
             f"Book: {len(pos)} ({nL}L/{nS}S), gross {(gross/eq if eq else 0):.2f}x, "
             f"net {(net/eq if eq else 0):+.1%}, beta {nbeta:+.2f}, unrealized {upl:+,.0f}\n"
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

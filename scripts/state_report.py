"""One-off readiness report: data coverage, scoring, Claude analysis, execution state."""
import os
import sqlite3

from core.config import cfg

db = cfg.get("data.db_path", "cache/meridian.db")
c = sqlite3.connect(db)


def one(q):
    try:
        return c.execute(q).fetchone()[0]
    except Exception as e:  # noqa: BLE001
        return f"ERR {e}"


print("DB size MB:", round(os.path.getsize(db) / 1e6, 1))
print("tables:", ", ".join(r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")))

print("\n--- DATA COVERAGE ---")
print("universe:", one("SELECT COUNT(*) FROM universe"))
print("tickers w/ prices:", one("SELECT COUNT(DISTINCT ticker) FROM daily_prices"),
      "| latest:", one("SELECT MAX(date) FROM daily_prices"))
for t in ["fundamentals", "short_interest", "estimates", "earnings_calendar",
          "sec_documents", "insider_transactions", "institutional_holdings"]:
    print(f"{t}: rows={one(f'SELECT COUNT(*) FROM {t}')} "
          f"tickers={one(f'SELECT COUNT(DISTINCT ticker) FROM {t}')}")

print("\n--- SCORING ---")
print("latest asof:", one("SELECT MAX(asof_date) FROM scores"),
      "| names scored:", one("SELECT COUNT(*) FROM scores WHERE asof_date=(SELECT MAX(asof_date) FROM scores)"))

print("\n--- CLAUDE ANALYSIS ---")
print("analysis_results rows:", one("SELECT COUNT(*) FROM analysis_results"),
      "| tickers analyzed:", one("SELECT COUNT(DISTINCT ticker) FROM analysis_results"))

print("\n--- PORTFOLIO / EXECUTION ---")
print("target_portfolio latest:", one("SELECT MAX(asof_date) FROM target_portfolio"),
      "| names:", one("SELECT COUNT(*) FROM target_portfolio WHERE asof_date=(SELECT MAX(asof_date) FROM target_portfolio)"))
for t in ["positions", "orders", "fills", "round_trips"]:
    print(f"{t}:", one(f"SELECT COUNT(*) FROM {t}"))

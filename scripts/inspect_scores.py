#!/usr/bin/env python3
"""Dev tool: summarize the latest scores table — sector-neutrality + a sector drill-down.
Usage: python3 -m scripts.inspect_scores [SECTOR]"""
import sys

from core.db import get_conn


def main() -> None:
    sector = " ".join(sys.argv[1:]) or "Information Technology"
    with get_conn() as conn:
        print("composite span per sector (should be ~0..100):")
        for r in conn.execute(
            "SELECT sector, COUNT(*) n, ROUND(MIN(composite),1) lo, ROUND(MAX(composite),1) hi, "
            "ROUND(AVG(composite),1) avg FROM scores GROUP BY sector ORDER BY n DESC"
        ):
            print(f"  {r['sector'][:24]:24s} n={r['n']:3d}  min={r['lo']:>5}  max={r['hi']:>5}  avg={r['avg']:>5}")

        cols = "ticker,composite,momentum,value,quality,growth,piotroski,altman_z"
        for label, order in (("TOP", "DESC"), ("BOTTOM", "ASC")):
            print(f"\n{sector} — {label} 5:")
            for r in conn.execute(
                f"SELECT {cols} FROM scores WHERE sector=? ORDER BY composite {order} LIMIT 5", (sector,)
            ):
                print("  %-6s comp=%3.0f mom=%3.0f val=%3.0f qual=%3.0f grw=%3.0f F=%s Z=%.1f" % (
                    r["ticker"], r["composite"], r["momentum"], r["value"], r["quality"],
                    r["growth"], r["piotroski"], r["altman_z"] or 0))


if __name__ == "__main__":
    main()

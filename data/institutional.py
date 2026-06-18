"""Source 4 — Institutional Holdings (13-F). Latest two 13F-HR filings for 9
tracked funds, parsed from the information-table XML. 13-F reports CUSIPs, not
tickers, so we map CUSIP -> ticker using FMP company profiles (Premium) restricted
to the S&P 500 universe."""
from __future__ import annotations

import json
from datetime import datetime

import requests

from core.config import cfg, env
from core.db import ensure_tables, get_conn, set_meta
from core.log import get_logger
from data.sec_data import _get, _strip_ns, _SUBMISSIONS, _ARCHIVE  # reuse SEC fetch + throttle
from data.universe import get_universe_tickers
from xml.etree import ElementTree as ET

log = get_logger("institutional")

FMP_PROFILE = "https://financialmodelingprep.com/stable/profile"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS universe_cusip (
    cusip  TEXT PRIMARY KEY,
    ticker TEXT
);
CREATE TABLE IF NOT EXISTS institutional_holdings (
    fund_name    TEXT,
    ticker       TEXT,
    report_date  TEXT,
    shares_held  REAL,
    market_value REAL,
    updated_at   TEXT,
    PRIMARY KEY (fund_name, ticker, report_date)
);
CREATE INDEX IF NOT EXISTS idx_inst_ticker ON institutional_holdings(ticker);
"""


def build_cusip_map(force: bool = False, sleep: float = 0.0) -> int:
    """Map each universe ticker's CUSIP via FMP profile. Cached; rebuilt only if forced."""
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        have = conn.execute("SELECT COUNT(*) c FROM universe_cusip").fetchone()["c"]
    if have and not force:
        return have

    key = env("FMP_API_KEY", required=True)
    stored = 0
    for i, t in enumerate(get_universe_tickers(), 1):
        try:
            r = requests.get(FMP_PROFILE, params={"symbol": t, "apikey": key}, timeout=30)
            if r.status_code != 200:
                continue
            data = r.json()
            cusip = (data[0].get("cusip") if data else None)
        except Exception as e:  # noqa: BLE001
            log.warning("profile failed for %s: %s", t, e)
            continue
        if cusip:
            with get_conn() as conn:
                conn.execute("INSERT OR REPLACE INTO universe_cusip(cusip,ticker) VALUES(?,?)",
                             (cusip.strip().upper(), t))
            stored += 1
        if i % 100 == 0:
            log.info("cusip map: %d/%d", i, len(get_universe_tickers()))
    log.info("CUSIP map built: %d entries", stored)
    return stored


def _cusip_to_ticker() -> dict[str, str]:
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        rows = conn.execute("SELECT cusip, ticker FROM universe_cusip").fetchall()
    return {r["cusip"]: r["ticker"] for r in rows}


def _latest_13f(cik: int, n: int = 2) -> list[dict]:
    """Most recent n 13F-HR filings: accession, filing_date, report_date."""
    r = _get(_SUBMISSIONS.format(cik=cik))
    if not r:
        return []
    rec = r.json().get("filings", {}).get("recent", {})
    out = []
    for form, acc, fdate, rdate in zip(
        rec.get("form", []), rec.get("accessionNumber", []),
        rec.get("filingDate", []), rec.get("reportDate", [])
    ):
        if form == "13F-HR":
            out.append({"accession": acc, "filing_date": fdate, "report_date": rdate})
        if len(out) >= n:
            break
    return out


def _info_table_xml(cik: int, accession: str) -> str | None:
    """Find and fetch the 13-F information-table XML within a filing."""
    acc_nodash = accession.replace("-", "")
    idx = _get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/index.json")
    if not idx:
        return None
    items = idx.json().get("directory", {}).get("item", [])
    xmls = [it["name"] for it in items if it.get("name", "").lower().endswith(".xml")]
    # Prefer obvious info-table names, else probe each xml for <infoTable>
    xmls.sort(key=lambda n: ("infotable" not in n.lower() and "table" not in n.lower()))
    for name in xmls:
        doc = _get(_ARCHIVE.format(cik=cik, acc_nodash=acc_nodash, doc=name))
        if doc and ("infoTable" in doc.text or "informationTable" in doc.text):
            return doc.text
    return None


def _parse_info_table(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    holdings = []
    for node in root.iter():
        if _strip_ns(node.tag) != "infoTable":
            continue
        rec: dict = {}
        for child in node.iter():
            tag = _strip_ns(child.tag)
            if tag == "cusip":
                rec["cusip"] = (child.text or "").strip().upper()
            elif tag == "value":
                try:
                    rec["value"] = float(child.text)
                except (TypeError, ValueError):
                    rec["value"] = None
            elif tag == "sshPrnamt":
                try:
                    rec["shares"] = float(child.text)
                except (TypeError, ValueError):
                    rec["shares"] = None
        if rec.get("cusip"):
            holdings.append(rec)
    return holdings


def update_institutional(funds: dict | None = None) -> int:
    ensure_tables(_SCHEMA)
    build_cusip_map()
    c2t = _cusip_to_ticker()
    fund_ciks = funds or cfg.get("data.institutional.fund_ciks", {})
    now = datetime.utcnow().isoformat()
    stored = 0
    for name, cik in fund_ciks.items():
        for filing in _latest_13f(int(cik), n=2):
            xml = _info_table_xml(int(cik), filing["accession"])
            if not xml:
                log.warning("no info table for %s %s", name, filing["accession"])
                continue
            # Aggregate by ticker (a fund may list a name across multiple share classes/rows)
            agg: dict[str, dict] = {}
            for h in _parse_info_table(xml):
                tk = c2t.get(h["cusip"])
                if not tk:
                    continue  # not in our S&P 500 universe
                a = agg.setdefault(tk, {"shares": 0.0, "value": 0.0})
                a["shares"] += h.get("shares") or 0.0
                a["value"] += h.get("value") or 0.0
            with get_conn() as conn:
                for tk, a in agg.items():
                    conn.execute(
                        "INSERT OR REPLACE INTO institutional_holdings "
                        "(fund_name,ticker,report_date,shares_held,market_value,updated_at) "
                        "VALUES (?,?,?,?,?,?)",
                        (name, tk, filing["report_date"], a["shares"], a["value"], now),
                    )
                    stored += 1
    set_meta("institutional_updated_at", now)
    log.info("Institutional 13-F: stored %d holdings rows across %d funds", stored, len(fund_ciks))
    return stored


def institutional_summary(ticker: str) -> dict:
    """Funds holding, net aggregate-share change vs prior quarter, multi-fund open flag."""
    ensure_tables(_SCHEMA)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT fund_name, report_date, shares_held FROM institutional_holdings WHERE ticker=?",
            (ticker,),
        ).fetchall()
        dates = [r["report_date"] for r in conn.execute(
            "SELECT DISTINCT report_date FROM institutional_holdings ORDER BY report_date DESC"
        ).fetchall()]
    latest = dates[0] if dates else None
    prior = dates[1] if len(dates) > 1 else None

    by_fund_latest = {r["fund_name"]: r["shares_held"] for r in rows if r["report_date"] == latest}
    by_fund_prior = {r["fund_name"]: r["shares_held"] for r in rows if r["report_date"] == prior}

    num_funds = sum(1 for v in by_fund_latest.values() if v and v > 0)
    net_change = sum(by_fund_latest.values()) - sum(by_fund_prior.values())
    new_openers = sum(1 for f in by_fund_latest if f not in by_fund_prior)
    min_open = int(cfg.get("data.institutional.multi_fund_open_min", 3))
    return {
        "num_funds_holding": num_funds,
        "net_share_change": net_change,
        "multi_fund_open": new_openers >= min_open,
    }


if __name__ == "__main__":
    n = update_institutional()
    print(f"Stored {n} institutional holding rows")
    for t in ("AAPL", "MSFT"):
        print(t, institutional_summary(t))

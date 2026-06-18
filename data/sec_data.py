"""Source 3 — SEC EDGAR filings. Latest 10-K (Risk Factors), 10-Q (MD&A), recent
8-Ks, and Form 4 insider transactions (last 180 days) parsed from the ownership XML.

Fair-access compliant: real contact email in the User-Agent, <= 8 requests/sec."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

import requests

from core.config import cfg, env
from core.db import ensure_tables, get_conn, set_meta
from core.log import get_logger

log = get_logger("sec_data")

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"

_MIN_INTERVAL = 1.0 / float(cfg.get("data.sec.rate_limit_per_sec", 8))
_last_req = [0.0]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sec_filings (
    ticker      TEXT,
    accession   TEXT,
    form        TEXT,
    filing_date TEXT,
    primary_doc TEXT,
    url         TEXT,
    PRIMARY KEY (ticker, accession)
);
CREATE TABLE IF NOT EXISTS sec_documents (
    accession  TEXT PRIMARY KEY,
    ticker     TEXT,
    form       TEXT,
    content    TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS insider_transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker           TEXT,
    accession        TEXT,
    insider_name     TEXT,
    insider_title    TEXT,
    transaction_type TEXT,     -- BUY / SELL / GRANT / EXERCISE / TAX / OTHER
    transaction_code TEXT,     -- raw SEC code (P, S, A, M, F, ...)
    shares           REAL,
    price            REAL,
    date             TEXT,
    ownership_type   TEXT      -- D (direct) / I (indirect)
);
CREATE INDEX IF NOT EXISTS idx_insider_ticker_date ON insider_transactions(ticker, date);
"""

_CODE_TYPE = {"P": "BUY", "S": "SELL", "A": "GRANT", "M": "EXERCISE", "F": "TAX"}


def _headers() -> dict:
    email = env("SEC_USER_AGENT_EMAIL", required=True)
    return {"User-Agent": f"{cfg.get('fund.name')} {email}", "Accept-Encoding": "gzip, deflate"}


def _throttle() -> None:
    delta = time.monotonic() - _last_req[0]
    if delta < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - delta)
    _last_req[0] = time.monotonic()


def _get(url: str) -> requests.Response | None:
    _throttle()
    try:
        r = requests.get(url, headers=_headers(), timeout=30)
        if r.status_code == 200:
            return r
        log.warning("SEC GET %s -> HTTP %s", url, r.status_code)
    except Exception as e:  # noqa: BLE001
        log.warning("SEC GET %s failed: %s", url, e)
    return None


_cik_cache: dict[str, int] = {}


def _load_cik_map() -> dict[str, int]:
    if _cik_cache:
        return _cik_cache
    r = _get(_TICKERS_URL)
    if not r:
        return {}
    for row in r.json().values():
        _cik_cache[row["ticker"].upper().replace(".", "-")] = int(row["cik_str"])
    return _cik_cache


def cik_for(ticker: str) -> int | None:
    return _load_cik_map().get(ticker.upper())


def _recent(cik: int) -> list[dict]:
    r = _get(_SUBMISSIONS.format(cik=cik))
    if not r:
        return []
    recent = r.json().get("filings", {}).get("recent", {})
    keys = ("form", "accessionNumber", "filingDate", "primaryDocument")
    if not all(k in recent for k in keys):
        return []
    return [
        {"form": f, "accession": a, "filing_date": d, "primary_doc": p}
        for f, a, d, p in zip(recent["form"], recent["accessionNumber"],
                              recent["filingDate"], recent["primaryDocument"])
    ]


def _doc_url(cik: int, accession: str, doc: str) -> str:
    return _ARCHIVE.format(cik=cik, acc_nodash=accession.replace("-", ""), doc=doc)


def update_filings(tickers: list[str], forms: list[str] | None = None,
                   fetch_docs: bool = True) -> int:
    """Store latest 10-K, latest 10-Q, recent 8-Ks. Caches 10-K/10-Q document text
    (used by Layer 3 risk/filing analyzers). `forms` restricts to specific form types."""
    ensure_tables(_SCHEMA)
    want = set(forms or ["10-K", "10-Q", "8-K"])
    stored = 0
    for t in tickers:
        cik = cik_for(t)
        if not cik:
            continue
        filings = _recent(cik)
        picked: list[dict] = []
        # latest of each single-instance form, plus recent 8-Ks
        for form in ("10-K", "10-Q"):
            if form in want:
                hit = next((f for f in filings if f["form"] == form), None)
                if hit:
                    picked.append(hit)
        if "8-K" in want:
            picked.extend([f for f in filings if f["form"] == "8-K"][:5])

        for f in picked:
            url = _doc_url(cik, f["accession"], f["primary_doc"])
            with get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO sec_filings "
                    "(ticker,accession,form,filing_date,primary_doc,url) VALUES (?,?,?,?,?,?)",
                    (t, f["accession"], f["form"], f["filing_date"], f["primary_doc"], url),
                )
            if fetch_docs and f["form"] in ("10-K", "10-Q"):
                doc = _get(url)
                if doc:
                    with get_conn() as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO sec_documents "
                            "(accession,ticker,form,content,fetched_at) VALUES (?,?,?,?,?)",
                            (f["accession"], t, f["form"], doc.text, datetime.utcnow().isoformat()),
                        )
            stored += 1
    set_meta("sec_filings_updated_at", datetime.utcnow().isoformat())
    log.info("SEC filings: stored %d filings across %d tickers", stored, len(tickers))
    return stored


# --- Form 4 insider transactions ----------------------------------------------

def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _findtext(node, path: str) -> str | None:
    """Namespace-agnostic findtext over a simple slash path."""
    cur = node
    for part in path.split("/"):
        nxt = None
        for child in cur:
            if _strip_ns(child.tag) == part:
                nxt = child
                break
        if nxt is None:
            return None
        cur = nxt
    return (cur.text or "").strip() if cur.text else None


def _parse_form4(xml_text: str) -> tuple[dict, list[dict]]:
    """Return (owner_info, [transactions]) from a Form 4 ownership XML document."""
    root = ET.fromstring(xml_text)
    owner = {"name": None, "title": None, "is_officer": False}
    for ro in root.iter():
        if _strip_ns(ro.tag) == "reportingOwner":
            owner["name"] = _findtext(ro, "reportingOwnerId/rptOwnerName")
            rel = next((c for c in ro if _strip_ns(c.tag) == "reportingOwnerRelationship"), None)
            if rel is not None:
                owner["is_officer"] = (_findtext(rel, "isOfficer") in ("1", "true"))
                owner["title"] = _findtext(rel, "officerTitle")
            break

    txns = []
    for node in root.iter():
        if _strip_ns(node.tag) in ("nonDerivativeTransaction", "derivativeTransaction"):
            code = _findtext(node, "transactionCoding/transactionCode")
            shares = _findtext(node, "transactionAmounts/transactionShares/value")
            price = _findtext(node, "transactionAmounts/transactionPricePerShare/value")
            ad = _findtext(node, "transactionAmounts/transactionAcquiredDisposedCode/value")
            tdate = _findtext(node, "transactionDate/value")
            own = _findtext(node, "ownershipNature/directOrIndirectOwnership/value")
            txns.append({
                "code": code,
                "shares": float(shares) if shares else None,
                "price": float(price) if price else None,
                "acquired_disposed": ad,
                "date": tdate,
                "ownership_type": own,
            })
    return owner, txns


def update_form4(tickers: list[str]) -> int:
    """Fetch and parse Form 4 filings within the configured lookback window."""
    ensure_tables(_SCHEMA)
    lookback = int(cfg.get("data.sec.form4_lookback_days", 180))
    cutoff = (date.today() - timedelta(days=lookback)).isoformat()
    stored = 0
    for t in tickers:
        cik = cik_for(t)
        if not cik:
            continue
        form4s = [f for f in _recent(cik) if f["form"] == "4" and f["filing_date"] >= cutoff]
        # Clear prior rows for these accessions so re-runs don't duplicate
        with get_conn() as conn:
            conn.execute("DELETE FROM insider_transactions WHERE ticker=? AND date < ?", (t, cutoff))
        for f in form4s:
            # primary_doc is the XSLT-rendered HTML (xslF345X.../form4.xml); the raw
            # ownership XML is the same basename in the accession root.
            raw_doc = f["primary_doc"].split("/")[-1]
            doc = _get(_doc_url(cik, f["accession"], raw_doc))
            if not doc or "<ownershipDocument" not in doc.text:
                continue
            try:
                owner, txns = _parse_form4(doc.text)
            except ET.ParseError:
                continue
            with get_conn() as conn:
                conn.execute("DELETE FROM insider_transactions WHERE accession=?", (f["accession"],))
                for tx in txns:
                    conn.execute(
                        "INSERT INTO insider_transactions "
                        "(ticker,accession,insider_name,insider_title,transaction_type,"
                        "transaction_code,shares,price,date,ownership_type) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (t, f["accession"], owner["name"], owner["title"],
                         _CODE_TYPE.get(tx["code"], "OTHER"), tx["code"],
                         tx["shares"], tx["price"], tx["date"] or f["filing_date"],
                         tx["ownership_type"]),
                    )
                    stored += 1
    set_meta("insider_updated_at", datetime.utcnow().isoformat())
    log.info("Insider (Form 4): stored %d transactions across %d tickers", stored, len(tickers))
    return stored


def insider_summary(ticker: str, window_days: int = 90) -> dict:
    """Net open-market $ flow, CEO/CFO purchase flag, cluster-buy flag (Layer 2 insider factor)."""
    ensure_tables(_SCHEMA)
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT insider_name, insider_title, transaction_code, shares, price, date "
            "FROM insider_transactions WHERE ticker=? AND date>=?",
            (ticker, cutoff),
        ).fetchall()

    net_flow = 0.0
    ceo_cfo_buy = False
    ceo_cfo_buy_value = 0.0
    buy_dates: dict[str, list[str]] = {}
    for r in rows:
        if r["transaction_code"] not in ("P", "S"):  # open-market only
            continue
        val = (r["shares"] or 0) * (r["price"] or 0)
        if r["transaction_code"] == "P":
            net_flow += val
            title = (r["insider_title"] or "").upper()
            if "CEO" in title or "CHIEF EXECUTIVE" in title or "CFO" in title or "CHIEF FINANCIAL" in title:
                ceo_cfo_buy = True
                ceo_cfo_buy_value += val * 3.0  # CEO/CFO buys weighted 3x
            buy_dates.setdefault(r["insider_name"] or "?", []).append(r["date"])
        else:
            net_flow -= val

    # Cluster: 3+ distinct insiders buying within a 30-day window
    cluster = False
    win = int(cfg.get("data.sec.cluster_buy_window_days", 30))
    need = int(cfg.get("data.sec.cluster_buy_min_insiders", 3))
    all_buys = sorted((d, n) for n, ds in buy_dates.items() for d in ds)
    for i, (d0, _) in enumerate(all_buys):
        start = date.fromisoformat(d0)
        names = {n for d, n in all_buys[i:] if (date.fromisoformat(d) - start).days <= win}
        if len(names) >= need:
            cluster = True
            break

    return {
        "has_data": len(rows) > 0,
        "net_dollar_flow": net_flow,
        "ceo_cfo_purchase": ceo_cfo_buy,
        "ceo_cfo_buy_value": ceo_cfo_buy_value,
        "cluster_buy": cluster,
    }


if __name__ == "__main__":
    import sys
    test = sys.argv[1:] or ["AAPL", "NVDA"]
    update_filings(test, forms=["10-K", "10-Q"], fetch_docs=False)
    update_form4(test)
    for t in test:
        print(t, insider_summary(t))

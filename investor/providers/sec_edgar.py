"""
SEC EDGAR — insider transactions from Form 4 filings (free).
Docs: https://www.sec.gov/os/accessing-edgar-data  (needs a contact User-Agent)
"""

import logging
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import config
from providers import http

logger = logging.getLogger(__name__)

_cik_map = None


def _headers():
    return {"User-Agent": config.get("sec_user_agent")}


def cik_map() -> dict:
    global _cik_map
    if _cik_map is None:
        data = http.get("https://www.sec.gov/files/company_tickers.json", headers=_headers())
        _cik_map = {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}
    return _cik_map


def _text(node, path):
    el = node.find(path)
    return el.text.strip() if el is not None and el.text else None


def parse_form4(xml_text: str, ticker: str, filed_at: str) -> list:
    """Extract non-derivative open-market buys (P) and sales (S)."""
    root = ET.fromstring(xml_text)
    owner = _text(root, "reportingOwner/reportingOwnerId/rptOwnerName") or "Unknown"
    rel = root.find("reportingOwner/reportingOwnerRelationship")
    title = None
    if rel is not None:
        title = _text(rel, "officerTitle")
        if not title and (_text(rel, "isDirector") or "").lower() in ("1", "true"):
            title = "Director"
        if not title and (_text(rel, "isTenPercentOwner") or "").lower() in ("1", "true"):
            title = "10% Owner"
    out = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _text(tx, "transactionCoding/transactionCode")
        if code not in ("P", "S"):
            continue
        try:
            shares = float(_text(tx, "transactionAmounts/transactionShares/value") or 0)
            price = float(_text(tx, "transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError:
            continue
        out.append({"ticker": ticker, "filed_at": filed_at, "owner": owner.title(),
                    "title": title or "Insider", "code": code,
                    "shares": shares, "price": price, "value": shares * price})
    return out


def get_insider_trades(ticker: str, days: int = 90, max_filings: int = 12) -> list:
    cik = cik_map().get(ticker.upper())
    if not cik:
        return []
    sub = http.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=_headers())
    recent = (sub.get("filings") or {}).get("recent") or {}
    since = (date.today() - timedelta(days=days)).isoformat()
    out, seen = [], 0
    for form, filed, acc, doc in zip(recent.get("form", []), recent.get("filingDate", []),
                                     recent.get("accessionNumber", []), recent.get("primaryDocument", [])):
        if filed < since:
            break
        if form != "4" or seen >= max_filings:
            continue
        seen += 1
        # primaryDocument is the XSL-rendered path ("xslF345X05/doc.xml"); the raw XML sits beside it
        raw_doc = doc.split("/")[-1]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{raw_doc}"
        try:
            out.extend(parse_form4(http.get(url, headers=_headers(), as_json=False), ticker, filed))
        except Exception as e:
            logger.debug(f"Form 4 parse failed {ticker} {acc}: {e}")
    return out

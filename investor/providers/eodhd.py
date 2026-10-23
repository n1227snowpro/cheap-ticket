"""
EODHD (https://eodhd.com) — prices, fundamentals, estimates, news.

normalize_fundamentals() maps EODHD's fundamentals JSON into the
provider-agnostic stock dict described in metrics.py, so swapping data
vendors only means writing another normalize function.
"""

import logging
from datetime import date, timedelta

import config
from providers import http

logger = logging.getLogger(__name__)

BASE = "https://eodhd.com/api"


def _key():
    k = config.get("eodhd_key")
    if not k:
        raise RuntimeError("eodhd_key is not configured")
    return k


def _symbol(ticker: str) -> str:
    return ticker.replace(".", "-") + ".US"


def _call(path, **params):
    return http.get(f"{BASE}/{path}", params={"api_token": _key(), "fmt": "json", **params})


def _f(x):
    try:
        return float(x) if x not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


# ── Universe ─────────────────────────────────────────────────────────────────

def get_universe() -> list:
    """Constituents of configured indexes (S&P 500 + Nasdaq-100 by default)."""
    tickers = set(config.get("extra_tickers") or [])
    for idx in config.get("universe_indexes") or []:
        try:
            data = _call(f"fundamentals/{idx}")
            for comp in (data.get("Components") or {}).values():
                code = comp.get("Code")
                if code:
                    tickers.add(code.replace("-", "."))
        except Exception as e:
            logger.warning(f"Universe fetch failed for {idx}: {e}")
    return sorted(tickers)


# ── Prices ───────────────────────────────────────────────────────────────────

def get_prices(ticker: str, days: int = 420) -> list:
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = _call(f"eod/{_symbol(ticker)}", **{"from": since, "period": "d"})
    return [[r["date"], _f(r.get("adjusted_close")) or _f(r.get("close"))] for r in rows if r.get("date")]


# ── Fundamentals ─────────────────────────────────────────────────────────────

def get_fundamentals(ticker: str) -> dict:
    return normalize_fundamentals(ticker, _call(f"fundamentals/{_symbol(ticker)}"))


_INCOME = {
    "revenue": "totalRevenue", "gross_profit": "grossProfit", "operating_income": "operatingIncome",
    "net_income": "netIncome", "ebitda": "ebitda", "rnd": "researchDevelopment",
}
_BALANCE = {
    "total_assets": "totalAssets", "current_assets": "totalCurrentAssets",
    "current_liabilities": "totalCurrentLiabilities", "total_liabilities": "totalLiab",
    "long_term_debt": "longTermDebt", "short_term_debt": "shortTermDebt",
    "equity": "totalStockholderEquity", "retained_earnings": "retainedEarnings",
    "cash": "cashAndShortTermInvestments", "shares": "commonStockSharesOutstanding",
}
_CASH = {
    "operating_cash_flow": "totalCashFromOperatingActivities",
    "capex": "capitalExpenditures", "dividends_paid": "dividendsPaid",
}


def normalize_fundamentals(ticker: str, raw: dict) -> dict:
    g = raw.get("General") or {}
    hi = raw.get("Highlights") or {}
    fin = raw.get("Financials") or {}

    def yearly(section):
        return (fin.get(section) or {}).get("yearly") or {}

    inc, bal, cf = yearly("Income_Statement"), yearly("Balance_Sheet"), yearly("Cash_Flow")
    annual = []
    for d in sorted(inc)[-6:]:
        i, b, c = inc.get(d) or {}, bal.get(d) or {}, cf.get(d) or {}
        row = {"year": int(d[:4]), "date": d}
        for k, src in _INCOME.items():
            row[k] = _f(i.get(src))
        for k, src in _BALANCE.items():
            row[k] = _f(b.get(src))
        if row["cash"] is None:
            row["cash"] = _f(b.get("cash"))
        for k, src in _CASH.items():
            row[k] = _f(c.get(src))
        if row["ebitda"] is None and row["operating_income"] is not None:
            row["ebitda"] = row["operating_income"] + (_f(c.get("depreciation")) or 0)
        annual.append(row)
    shares_now = _f((raw.get("SharesStats") or {}).get("SharesOutstanding"))
    if annual and shares_now and not annual[-1].get("shares"):
        annual[-1]["shares"] = shares_now

    trend = (raw.get("Earnings") or {}).get("Trend") or {}
    by_period = {}
    for t in trend.values():
        by_period.setdefault(t.get("period"), t)  # keys are dates; first per period is enough
    cy, ny = by_period.get("0y") or {}, by_period.get("+1y") or {}
    ar = raw.get("AnalystRatings") or {}

    return {
        "ticker": ticker,
        "name": g.get("Name") or ticker,
        "sector": g.get("Sector") or "Other",
        "industry": g.get("Industry") or "",
        "exchange": g.get("Exchange"),
        "currency": g.get("CurrencyCode") or "USD",
        "description": (g.get("Description") or "")[:600],
        "market_cap": _f(hi.get("MarketCapitalization")),
        "annual": annual,
        "estimates": {
            "eps_current_year": _f(hi.get("EPSEstimateCurrentYear")) or _f(cy.get("earningsEstimateAvg")),
            "eps_next_year": _f(hi.get("EPSEstimateNextYear")) or _f(ny.get("earningsEstimateAvg")),
            "eps_growth_5y": _f((by_period.get("+5y") or {}).get("growth")),
            "eps_trend_now": _f(ny.get("epsTrendCurrent")),
            "eps_trend_90d": _f(ny.get("epsTrend90daysAgo")),
        },
        "analyst": {
            "target_price": _f(ar.get("TargetPrice")) or _f(hi.get("WallStreetTargetPrice")),
            "rating": _f(ar.get("Rating")),
            "strong_buy": ar.get("StrongBuy"), "buy": ar.get("Buy"), "hold": ar.get("Hold"),
            "sell": ar.get("Sell"), "strong_sell": ar.get("StrongSell"),
        },
    }


# ── News ─────────────────────────────────────────────────────────────────────

def get_news(ticker: str, limit: int = 15) -> list:
    items = _call("news", s=_symbol(ticker), limit=limit)
    out = []
    for n in items or []:
        sent = n.get("sentiment") or {}
        out.append({
            "url": n.get("link"),
            "ticker": ticker,
            "title": n.get("title"),
            "source": (n.get("link") or "").split("/")[2] if n.get("link", "").count("/") >= 2 else "EODHD",
            "published_at": n.get("date"),
            "sentiment": _f(sent.get("polarity")),
        })
    return [o for o in out if o["url"] and o["title"]]

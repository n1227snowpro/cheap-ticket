"""
Pure indicator functions. No I/O.

Input is the provider-agnostic stock dict produced by providers/eodhd.py
(or fixtures.py):

    {
      "ticker", "name", "sector", "industry", "price", "market_cap",
      "annual": [ {year, revenue, gross_profit, operating_income, net_income,
                   ebitda, total_assets, current_assets, current_liabilities,
                   total_liabilities, long_term_debt, short_term_debt, equity,
                   retained_earnings, cash, operating_cash_flow, capex,
                   dividends_paid, shares, rnd}, ... ]   # oldest → newest
      "estimates": {eps_current_year, eps_next_year, eps_growth_5y,
                    eps_trend_now, eps_trend_90d},
      "analyst": {target_price, rating},
    }

analyze() returns a flat dict of metrics. Ratios whose denominator is
negative (e.g. P/E of a loss-maker) are None and listed in "_negative" so the
scorer can rank them last instead of ignoring them.
"""

import math
import statistics

TAX_RATE = 0.21
DISCOUNT_RATE = 0.10
TERMINAL_GROWTH = 0.03


# ── Small helpers ────────────────────────────────────────────────────────────

def _num(x):
    return x if isinstance(x, (int, float)) and not math.isnan(x) else None


def safe_div(a, b):
    a, b = _num(a), _num(b)
    if a is None or b is None or b == 0:
        return None
    return a / b


def cagr(start, end, years):
    """Compound annual growth. None if either end is non-positive."""
    start, end = _num(start), _num(end)
    if start is None or end is None or start <= 0 or end <= 0 or years <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def debt(y: dict) -> float:
    return (y.get("long_term_debt") or 0) + (y.get("short_term_debt") or 0)


def fcf(y: dict):
    ocf = _num(y.get("operating_cash_flow"))
    if ocf is None:
        return None
    return ocf - abs(y.get("capex") or 0)


# ── Classic value formulas ───────────────────────────────────────────────────

def graham_number(eps, bvps):
    """Benjamin Graham's max fair price: sqrt(22.5 × EPS × BVPS)."""
    eps, bvps = _num(eps), _num(bvps)
    if not eps or not bvps or eps <= 0 or bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)


def dcf_per_share(fcf_ps, growth, years_high=5, years_fade=5,
                  discount=DISCOUNT_RATE, terminal=TERMINAL_GROWTH):
    """Two-stage DCF: `growth` for years_high, linear fade to `terminal`, then Gordon terminal value."""
    fcf_ps, growth = _num(fcf_ps), _num(growth)
    if fcf_ps is None or fcf_ps <= 0 or growth is None:
        return None
    growth = max(-0.05, min(growth, 0.15))
    value, cash, year = 0.0, fcf_ps, 0
    for _ in range(years_high):
        year += 1
        cash *= 1 + growth
        value += cash / (1 + discount) ** year
    for i in range(1, years_fade + 1):
        year += 1
        g = growth + (terminal - growth) * i / years_fade
        cash *= 1 + g
        value += cash / (1 + discount) ** year
    tv = cash * (1 + terminal) / (discount - terminal)
    value += tv / (1 + discount) ** year
    return value


def piotroski(cur: dict, prev: dict):
    """Piotroski F-Score (0–9). Returns (score, {test: passed})."""
    if not cur or not prev:
        return None, {}
    roa = safe_div(cur.get("net_income"), cur.get("total_assets"))
    roa_prev = safe_div(prev.get("net_income"), prev.get("total_assets"))
    ocf = cur.get("operating_cash_flow")
    lev = safe_div(cur.get("long_term_debt") or 0, cur.get("total_assets"))
    lev_prev = safe_div(prev.get("long_term_debt") or 0, prev.get("total_assets"))
    cr = safe_div(cur.get("current_assets"), cur.get("current_liabilities"))
    cr_prev = safe_div(prev.get("current_assets"), prev.get("current_liabilities"))
    gm = safe_div(cur.get("gross_profit"), cur.get("revenue"))
    gm_prev = safe_div(prev.get("gross_profit"), prev.get("revenue"))
    at = safe_div(cur.get("revenue"), cur.get("total_assets"))
    at_prev = safe_div(prev.get("revenue"), prev.get("total_assets"))

    def gt(a, b):
        return a is not None and b is not None and a > b

    tests = {
        "positive_roa": roa is not None and roa > 0,
        "positive_ocf": ocf is not None and ocf > 0,
        "roa_improving": gt(roa, roa_prev),
        "accruals": ocf is not None and roa is not None and cur.get("total_assets")
                    and ocf / cur["total_assets"] > roa,
        "leverage_falling": lev is not None and lev_prev is not None and lev <= lev_prev,
        "liquidity_rising": gt(cr, cr_prev),
        "no_dilution": (cur.get("shares") or 0) <= (prev.get("shares") or 0) * 1.005,
        "margin_rising": gt(gm, gm_prev),
        "turnover_rising": gt(at, at_prev),
    }
    tests = {k: bool(v) for k, v in tests.items()}
    return sum(tests.values()), tests


def altman_z(y: dict, market_cap):
    """Altman Z-Score (original manufacturing model). >3 safe, <1.8 distress."""
    ta = _num(y.get("total_assets"))
    tl = _num(y.get("total_liabilities"))
    if not ta or not tl or not _num(market_cap):
        return None
    wc = (y.get("current_assets") or 0) - (y.get("current_liabilities") or 0)
    return (1.2 * wc / ta
            + 1.4 * (y.get("retained_earnings") or 0) / ta
            + 3.3 * (y.get("operating_income") or 0) / ta
            + 0.6 * market_cap / tl
            + 1.0 * (y.get("revenue") or 0) / ta)


# ── Price-based helpers ──────────────────────────────────────────────────────

def closes(prices: list) -> list:
    return [p[1] for p in prices if _num(p[1])]


def sma(values: list, n: int):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def ret(values: list, days: int):
    if len(values) <= days or not values[-days - 1]:
        return None
    return values[-1] / values[-days - 1] - 1


# ── Main entry ───────────────────────────────────────────────────────────────

def analyze(s: dict, prices: list = None, spy_prices: list = None,
            signals: dict = None) -> dict:
    """
    Compute every indicator for one stock.
    `signals` (optional): {"news_sentiment", "news_count", "buzz_z",
                           "mentions_7d", "bull_ratio", "insider_buyers", "insider_net_value"}
    """
    annual = [y for y in (s.get("annual") or []) if y.get("revenue")]
    m = {"_negative": []}
    neg = m["_negative"]
    if not annual:
        return m
    cur = annual[-1]
    prev = annual[-2] if len(annual) >= 2 else None
    y3 = annual[-4] if len(annual) >= 4 else annual[0]
    span = len(annual) - 1 - annual.index(y3)

    px_series = closes(prices or [])
    price = _num(s.get("price")) or (px_series[-1] if px_series else None)
    shares = cur.get("shares")
    mcap = _num(s.get("market_cap")) or (price * shares if price and shares else None)
    m["price"], m["market_cap"] = price, mcap

    eps = safe_div(cur.get("net_income"), shares)
    bvps = safe_div(cur.get("equity"), shares)
    f = fcf(cur)
    total_debt = debt(cur)
    ev = mcap + total_debt - (cur.get("cash") or 0) if mcap else None

    def ratio(key, num, den):
        if den is not None and den <= 0:
            m[key] = None
            neg.append(key)
        else:
            m[key] = safe_div(num, den)

    # Value
    m["eps"] = eps
    ratio("pe", price, eps)
    ratio("pb", price, bvps)
    m["ps"] = safe_div(mcap, cur.get("revenue"))
    ratio("p_fcf", mcap, f)
    ratio("ev_ebitda", ev, cur.get("ebitda"))
    m["graham_number"] = graham_number(eps, bvps)
    m["graham_discount"] = (safe_div(m["graham_number"] - price, m["graham_number"])
                            if m["graham_number"] and price else None)
    m["fcf"] = f
    m["fcf_yield"] = safe_div(f, mcap)
    m["debt_equity"] = safe_div(total_debt, cur.get("equity")) if (cur.get("equity") or 0) > 0 else None
    if (cur.get("equity") or 0) <= 0:
        neg.append("debt_equity")
    m["current_ratio"] = safe_div(cur.get("current_assets"), cur.get("current_liabilities"))
    divs = abs(cur.get("dividends_paid") or 0)
    m["dividend_yield"] = safe_div(divs, mcap) if mcap else None
    m["payout_ratio"] = safe_div(divs, cur.get("net_income")) if (cur.get("net_income") or 0) > 0 else None
    m["piotroski"], m["piotroski_tests"] = piotroski(cur, prev)
    m["altman_z"] = altman_z(cur, mcap)

    # Growth
    m["rev_cagr_3y"] = cagr(y3.get("revenue"), cur.get("revenue"), span)
    eps_then = safe_div(y3.get("net_income"), y3.get("shares"))
    m["eps_cagr_3y"] = cagr(eps_then, eps, span)
    m["rev_growth_1y"] = (safe_div(cur["revenue"], prev["revenue"]) - 1) if prev and prev.get("revenue") else None
    est = s.get("estimates") or {}
    cy, ny = _num(est.get("eps_current_year")), _num(est.get("eps_next_year"))
    m["fwd_eps_growth"] = (ny / cy - 1) if cy and ny and cy > 0 else None
    now, ago = _num(est.get("eps_trend_now")), _num(est.get("eps_trend_90d"))
    m["eps_revision_90d"] = (now / ago - 1) if now and ago and ago > 0 else None
    growth_for_peg = _num(est.get("eps_growth_5y")) or m["fwd_eps_growth"] or m["eps_cagr_3y"]
    if m["pe"] and growth_for_peg and growth_for_peg > 0:
        m["peg"] = m["pe"] / (growth_for_peg * 100)
    else:
        m["peg"] = None
        neg.append("peg")
    gm = safe_div(cur.get("gross_profit"), cur.get("revenue"))
    gm_then = safe_div(y3.get("gross_profit"), y3.get("revenue"))
    m["gross_margin"] = gm
    m["gross_margin_trend"] = gm - gm_then if gm is not None and gm_then is not None else None
    fcf_margin = safe_div(f, cur.get("revenue"))
    m["fcf_margin"] = fcf_margin
    m["rule_of_40"] = ((m["rev_growth_1y"] or 0) + (fcf_margin or 0)) * 100 if m["rev_growth_1y"] is not None else None
    m["rnd_intensity"] = safe_div(cur.get("rnd"), cur.get("revenue"))

    # Quality
    invested = total_debt + (cur.get("equity") or 0) - (cur.get("cash") or 0)
    m["roic"] = safe_div((cur.get("operating_income") or 0) * (1 - TAX_RATE), invested) if invested > 0 else None
    m["roe"] = safe_div(cur.get("net_income"), cur.get("equity")) if (cur.get("equity") or 0) > 0 else None
    op_margins = [safe_div(y.get("operating_income"), y.get("revenue")) for y in annual[-5:]]
    op_margins = [x for x in op_margins if x is not None]
    m["op_margin"] = op_margins[-1] if op_margins else None
    m["op_margin_stability"] = statistics.pstdev(op_margins) if len(op_margins) >= 3 else None
    m["fcf_conversion"] = safe_div(f, cur.get("net_income")) if (cur.get("net_income") or 0) > 0 else None
    m["share_change_3y"] = (safe_div(shares, y3.get("shares")) - 1) if shares and y3.get("shares") else None

    # Fair value
    fcf_ps = safe_div(f, shares)
    g = growth_for_peg if growth_for_peg is not None else m["rev_cagr_3y"]
    m["dcf_value"] = dcf_per_share(fcf_ps, g if g is not None else 0.03)
    m["dcf_mos"] = safe_div(m["dcf_value"] - price, m["dcf_value"]) if m["dcf_value"] and price else None
    m["target_price"] = _num((s.get("analyst") or {}).get("target_price"))
    m["target_upside"] = (m["target_price"] / price - 1) if m["target_price"] and price else None

    # Momentum
    if px_series:
        m["ret_1m"] = ret(px_series, 21)
        m["ret_6m"] = ret(px_series, 126)
        m["ret_12m"] = ret(px_series, 252)
        s50, s200 = sma(px_series, 50), sma(px_series, 200)
        m["above_sma50"] = (px_series[-1] > s50) if s50 else None
        m["above_sma200"] = (px_series[-1] > s200) if s200 else None
        window = px_series[-252:]
        hi, lo = max(window), min(window)
        m["pos_52w"] = (px_series[-1] - lo) / (hi - lo) if hi > lo else None
        m["high_52w"], m["low_52w"] = hi, lo
    spy = closes(spy_prices or [])
    if px_series and spy:
        r, b = ret(px_series, 252) or ret(px_series, len(px_series) - 1), ret(spy, 252) or ret(spy, len(spy) - 1)
        m["rs_12m"] = (r - b) if r is not None and b is not None else None

    # Sentiment / alternative data
    for k in ("news_sentiment", "news_count", "buzz_z", "mentions_7d", "bull_ratio",
              "insider_buyers", "insider_net_value"):
        m[k] = (signals or {}).get(k)

    return m


# ── Plain-English checklist ──────────────────────────────────────────────────

def _pct(x):
    return f"{x * 100:.1f}%"


def _x(x):
    return f"{x:.1f}×"


# (key, group, label, test, explanation-format, display-format)
_CHECKS = [
    ("pe", "value", "P/E under 20", lambda v: v < 20, "Pays {d} earnings — {verdict} for a typical stock.", _x),
    ("peg", "growth", "PEG under 1.5", lambda v: v < 1.5, "Price relative to growth is {d} — {verdict}.", lambda v: f"{v:.2f}"),
    ("p_fcf", "value", "Price/FCF under 20", lambda v: v < 20, "Market cap is {d} free cash flow.", _x),
    ("ev_ebitda", "value", "EV/EBITDA under 12", lambda v: v < 12, "Enterprise value is {d} EBITDA.", _x),
    ("graham_discount", "value", "Below Graham Number", lambda v: v > 0, "Price is {d} vs Graham's fair-price ceiling.", lambda v: f"{v * 100:+.0f}%"),
    ("dcf_mos", "value", "DCF margin of safety ≥ 20%", lambda v: v >= 0.2, "Cash-flow model says the stock is {d} vs intrinsic value.", lambda v: f"{v * 100:+.0f}%"),
    ("piotroski", "quality", "Piotroski F-Score ≥ 7", lambda v: v >= 7, "Financial health score {d}/9.", lambda v: f"{v}"),
    ("altman_z", "quality", "Altman Z above 3 (safe zone)", lambda v: v > 3, "Bankruptcy-risk score {d} (below 1.8 = distress).", lambda v: f"{v:.1f}"),
    ("debt_equity", "quality", "Debt/Equity under 1", lambda v: v < 1, "Debt is {d} of shareholder equity.", _x),
    ("current_ratio", "quality", "Current ratio above 1.5", lambda v: v > 1.5, "Short-term assets cover short-term bills {d}.", _x),
    ("roic", "quality", "ROIC above 12%", lambda v: v > 0.12, "Earns {d} on every dollar invested.", _pct),
    ("roe", "quality", "ROE above 15%", lambda v: v > 0.15, "Return on shareholder equity of {d}.", _pct),
    ("op_margin_stability", "quality", "Stable margins", lambda v: v < 0.04, "Operating margin wobbled ±{d} over 5 years.", _pct),
    ("fcf_conversion", "quality", "Profits turn into cash", lambda v: v > 0.8, "{d} of net income shows up as free cash flow.", _pct),
    ("share_change_3y", "quality", "No heavy dilution", lambda v: v < 0.05, "Share count changed {d} over 3 years.", lambda v: f"{v * 100:+.1f}%"),
    ("rev_cagr_3y", "growth", "Revenue growing > 10%/yr", lambda v: v > 0.10, "Sales grew {d} a year for 3 years.", _pct),
    ("eps_cagr_3y", "growth", "EPS growing > 10%/yr", lambda v: v > 0.10, "Earnings per share grew {d} a year.", _pct),
    ("fwd_eps_growth", "growth", "Analysts expect EPS growth", lambda v: v > 0.08, "Next-year EPS expected to change {d}.", lambda v: f"{v * 100:+.1f}%"),
    ("eps_revision_90d", "growth", "Estimates rising", lambda v: v > 0, "EPS estimates moved {d} in 90 days.", lambda v: f"{v * 100:+.1f}%"),
    ("gross_margin_trend", "growth", "Gross margin expanding", lambda v: v > 0, "Gross margin changed {d} pts over 3 years.", lambda v: f"{v * 100:+.1f}"),
    ("rule_of_40", "growth", "Rule of 40", lambda v: v >= 40, "Growth % + FCF margin % = {d}.", lambda v: f"{v:.0f}"),
    ("dividend_yield", "value", "Dividend yield ≥ 2%", lambda v: v >= 0.02, "Pays {d} a year in dividends.", _pct),
    ("payout_ratio", "quality", "Dividend is covered", lambda v: v < 0.7, "Pays out {d} of earnings.", _pct),
    ("rs_12m", "momentum", "Beating the S&P 500", lambda v: v > 0, "12-month return vs S&P 500: {d}.", lambda v: f"{v * 100:+.1f}%"),
    ("above_sma200", "momentum", "Above 200-day average", lambda v: v is True, "Price is {d} its long-term trend line.", lambda v: "above" if v else "below"),
    ("news_sentiment", "momentum", "Positive news flow", lambda v: v > 0.1, "Average headline tone this week: {d}.", lambda v: f"{v:+.2f}"),
    ("insider_buyers", "momentum", "Insiders buying", lambda v: v >= 2, "{d} insiders bought shares on the open market (90d).", lambda v: f"{v}"),
]

_NEGATIVE_TEXT = {
    "pe": "Company is losing money, so P/E is not meaningful.",
    "p_fcf": "Free cash flow is negative.",
    "ev_ebitda": "EBITDA is negative.",
    "peg": "No positive earnings growth to justify the price.",
    "pb": "Book value is negative.",
    "debt_equity": "Shareholder equity is negative.",
}


def checklist(m: dict) -> list:
    out = []
    negatives = set(m.get("_negative", []))
    for key, group, label, test, expl, fmt in _CHECKS:
        v = m.get(key)
        if v is None:
            if key in negatives and key in _NEGATIVE_TEXT:
                out.append({"key": key, "group": group, "label": label, "pass": False,
                            "display": "n/m", "why": _NEGATIVE_TEXT[key]})
            continue
        ok = bool(test(v))
        d = fmt(v)
        out.append({
            "key": key, "group": group, "label": label, "pass": ok, "display": d,
            "why": expl.format(d=d, verdict="cheap" if ok else "expensive"),
        })
    return out

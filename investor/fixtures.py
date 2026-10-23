"""
Demo data: FICTIONAL companies with SYNTHETIC numbers, generated
deterministically. Used when no EODHD key is configured (FIXTURE_MODE) and
by the tests, so the whole app can run offline. Nothing here describes a real
company — the UI shows a "Demo data" banner whenever these are loaded.
"""

import math
import random
from datetime import date, datetime, timedelta, timezone

# ticker, name, sector, industry, rev0($B), growth, gross_m, op_m, debt/eq, payout, dilution/yr,
# target P/E (or P/S when loss-making), news tone (-1..1), buzz (x normal), insider buyers, analyst upside
PROFILES = [
    ("NOVA", "Novaline Software", "Technology", "Software—Application", 2.1, 0.32, 0.78, 0.18, 0.1, 0.0, 0.03, 48, 0.4, 1.2, 0, 0.12),
    ("QBIT", "Qubitron Systems", "Technology", "Semiconductors", 8.5, 0.22, 0.62, 0.30, 0.2, 0.05, 0.0, 30, 0.6, 3.5, 0, 0.18),
    ("CLDX", "Cloudex Networks", "Technology", "Software—Infrastructure", 1.2, 0.41, 0.74, -0.08, 0.3, 0.0, 0.06, 9, 0.2, 2.6, 0, 0.25),
    ("BYTE", "Bytewell Corp", "Technology", "Information Technology Services", 14.0, 0.05, 0.31, 0.13, 0.4, 0.35, -0.02, 13, 0.0, 0.8, 3, 0.15),
    ("PIXL", "Pixelforge Inc", "Technology", "Consumer Electronics", 22.0, 0.03, 0.38, 0.09, 0.9, 0.25, 0.0, 17, -0.3, 1.0, 0, 0.05),
    ("DATA", "Datastream Analytics", "Technology", "Software—Application", 3.4, 0.18, 0.70, 0.22, 0.2, 0.0, -0.01, 24, 0.3, 1.1, 2, 0.20),
    ("MEDI", "Medivance Health", "Healthcare", "Medical Devices", 6.0, 0.09, 0.64, 0.21, 0.5, 0.30, -0.01, 19, 0.2, 0.9, 0, 0.10),
    ("GENX", "Genexa Therapeutics", "Healthcare", "Biotechnology", 0.6, 0.55, 0.85, -0.35, 0.1, 0.0, 0.09, 12, 0.5, 4.0, 0, 0.45),
    ("CURA", "Curalink Pharma", "Healthcare", "Drug Manufacturers", 30.0, 0.02, 0.72, 0.28, 0.7, 0.55, -0.01, 11, -0.2, 0.7, 2, 0.12),
    ("VITA", "Vitacore Labs", "Healthcare", "Diagnostics & Research", 4.2, 0.12, 0.55, 0.17, 0.3, 0.15, 0.0, 22, 0.1, 0.9, 0, 0.08),
    ("CARE", "Carepoint Services", "Healthcare", "Healthcare Plans", 55.0, 0.07, 0.18, 0.06, 0.6, 0.30, -0.02, 12, -0.5, 1.4, 4, 0.22),
    ("BANKR", "Bankrest Financial", "Financial Services", "Banks—Regional", 9.0, 0.04, 0.95, 0.33, 1.2, 0.40, -0.02, 9, 0.0, 0.8, 2, 0.14),
    ("LEDG", "Ledgerline Payments", "Financial Services", "Credit Services", 12.0, 0.14, 0.80, 0.38, 0.5, 0.20, -0.02, 27, 0.4, 1.3, 0, 0.11),
    ("ASUR", "Assurance Mutual", "Financial Services", "Insurance—Diversified", 40.0, 0.05, 0.30, 0.12, 0.3, 0.35, -0.01, 12, 0.1, 0.6, 0, 0.09),
    ("COIN2", "Coinvault Exchange", "Financial Services", "Capital Markets", 2.8, 0.30, 0.82, 0.05, 0.2, 0.0, 0.05, 6, 0.3, 5.0, 0, 0.10),
    ("BREW", "Brewmaster Holdings", "Consumer Defensive", "Beverages—Brewers", 18.0, 0.03, 0.55, 0.22, 1.1, 0.65, -0.01, 18, 0.0, 0.7, 0, 0.06),
    ("GROC", "Grocerly Markets", "Consumer Defensive", "Grocery Stores", 70.0, 0.04, 0.26, 0.04, 0.8, 0.40, -0.02, 14, -0.1, 0.8, 2, 0.10),
    ("SOAP", "Soapstone Brands", "Consumer Defensive", "Household Products", 15.0, 0.02, 0.48, 0.20, 0.9, 0.62, -0.01, 21, 0.1, 0.6, 0, 0.04),
    ("SHOP2", "Shopwave Retail", "Consumer Cyclical", "Internet Retail", 9.5, 0.26, 0.45, 0.07, 0.4, 0.0, 0.02, 45, 0.5, 2.2, 0, 0.16),
    ("AUTO", "Autovance Motors", "Consumer Cyclical", "Auto Manufacturers", 60.0, 0.01, 0.16, 0.05, 1.6, 0.30, 0.0, 6, -0.6, 1.6, 3, 0.30),
    ("TRVL", "Travelnest Inc", "Consumer Cyclical", "Travel Services", 7.0, 0.16, 0.82, 0.19, 0.9, 0.0, -0.03, 20, 0.3, 1.1, 0, 0.13),
    ("SNKR", "Sneakerly Group", "Consumer Cyclical", "Footwear & Accessories", 11.0, 0.06, 0.44, 0.11, 0.5, 0.35, -0.01, 24, -0.4, 1.9, 0, 0.07),
    ("PETRO", "Petrolux Energy", "Energy", "Oil & Gas Integrated", 80.0, 0.00, 0.35, 0.14, 0.3, 0.45, -0.03, 8, -0.1, 0.9, 2, 0.18),
    ("SOLR", "Solaris Grid", "Energy", "Solar", 2.5, 0.35, 0.28, 0.06, 1.0, 0.0, 0.07, 10, 0.4, 2.8, 0, 0.35),
    ("PIPE", "Pipeway Midstream", "Energy", "Oil & Gas Midstream", 13.0, 0.03, 0.40, 0.24, 1.4, 0.80, 0.0, 12, 0.0, 0.5, 0, 0.08),
    ("FORG", "Forgeworks Industrial", "Industrials", "Specialty Industrial Machinery", 16.0, 0.08, 0.36, 0.16, 0.6, 0.30, -0.02, 19, 0.2, 0.7, 2, 0.12),
    ("RAIL", "Railcross Logistics", "Industrials", "Railroads", 20.0, 0.04, 0.50, 0.36, 1.2, 0.40, -0.02, 18, 0.0, 0.5, 0, 0.07),
    ("AERO", "Aerospan Defense", "Industrials", "Aerospace & Defense", 25.0, 0.07, 0.22, 0.11, 0.8, 0.35, -0.01, 17, 0.3, 1.0, 0, 0.10),
    ("DRON", "Dronetic Robotics", "Industrials", "Electrical Equipment", 1.4, 0.48, 0.42, -0.12, 0.5, 0.0, 0.08, 7, 0.6, 4.5, 0, 0.20),
    ("VOLT", "Voltgrid Utilities", "Utilities", "Utilities—Regulated Electric", 12.0, 0.03, 0.42, 0.22, 1.5, 0.68, 0.01, 17, 0.0, 0.4, 0, 0.06),
    ("AQUA", "Aquaflow Water", "Utilities", "Utilities—Regulated Water", 3.0, 0.05, 0.55, 0.30, 1.3, 0.60, 0.01, 22, 0.1, 0.4, 0, 0.05),
    ("TOWR", "Towerline REIT", "Real Estate", "REIT—Specialty", 6.5, 0.06, 0.72, 0.38, 1.9, 0.90, 0.01, 30, 0.0, 0.6, 0, 0.09),
    ("MALL", "Mallpoint Properties", "Real Estate", "REIT—Retail", 2.0, -0.02, 0.68, 0.30, 1.6, 0.95, 0.0, 11, -0.4, 0.7, 3, 0.20),
    ("STRM", "Streamly Media", "Communication Services", "Entertainment", 28.0, 0.11, 0.42, 0.17, 0.7, 0.0, -0.02, 26, 0.3, 1.8, 0, 0.12),
    ("TELX", "Telexa Communications", "Communication Services", "Telecom Services", 45.0, 0.01, 0.58, 0.18, 1.3, 0.70, 0.0, 9, -0.2, 0.5, 2, 0.11),
    ("ADSY", "Adsync Interactive", "Communication Services", "Internet Content & Information", 38.0, 0.15, 0.80, 0.32, 0.1, 0.0, -0.03, 21, 0.4, 1.5, 0, 0.17),
    ("MINE", "Minecrest Materials", "Basic Materials", "Copper", 9.0, 0.06, 0.34, 0.25, 0.4, 0.30, 0.0, 13, 0.2, 1.0, 3, 0.20),
    ("CHEM", "Chemlogic Corp", "Basic Materials", "Specialty Chemicals", 11.0, 0.02, 0.30, 0.10, 0.9, 0.50, 0.0, 15, -0.3, 0.6, 0, 0.08),
]

YEARS = list(range(2020, 2026))
N_DAYS = 300


def _rng(ticker):
    return random.Random(sum(ord(c) * (i + 1) for i, c in enumerate(ticker)))


def _price_series(rng, end_price, vol, drift, n=N_DAYS):
    rets = [rng.gauss(drift / 252, vol / math.sqrt(252)) for _ in range(n - 1)]
    levels = [1.0]
    for r in rets:
        levels.append(levels[-1] * math.exp(r))
    scale = end_price / levels[-1]
    days, d = [], date.today()
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    return [[days[i].isoformat(), round(levels[i] * scale, 2)] for i in range(n)]


def _company(p):
    (t, name, sector, industry, rev0, g, gm, opm, de, payout, dil, mult,
     tone, buzz, insiders, upside) = p
    rng = _rng(t)
    shares0 = rev0 * 1e9 / rng.uniform(20, 80)
    turnover = rng.uniform(0.5, 1.2)
    annual = []
    rev = rev0 * 1e9
    for i, year in enumerate(YEARS):
        if i:
            rev *= 1 + g + rng.uniform(-0.03, 0.03)
        gm_y = min(0.97, gm + (i - 5) * rng.uniform(-0.004, 0.008))
        op_y = opm + rng.uniform(-0.02, 0.02) + (0.01 * (i - 5) if opm < 0 else 0)
        shares = shares0 * (1 + dil) ** i
        assets = rev / turnover
        equity = assets / (1 + de * 1.4 + 0.3)
        debt = equity * de
        op_inc = rev * op_y
        net = op_inc * 0.79 - debt * 0.045
        ca = assets * rng.uniform(0.25, 0.45)
        annual.append({
            "year": year,
            "revenue": rev,
            "gross_profit": rev * gm_y,
            "operating_income": op_inc,
            "net_income": net,
            "ebitda": op_inc + rev * 0.05,
            "total_assets": assets,
            "current_assets": ca,
            "current_liabilities": ca / rng.uniform(0.9, 2.6),
            "total_liabilities": assets - equity,
            "long_term_debt": debt * 0.85,
            "short_term_debt": debt * 0.15,
            "equity": equity,
            "retained_earnings": equity * rng.uniform(0.2, 0.9),
            "cash": assets * rng.uniform(0.04, 0.18),
            "operating_cash_flow": net * rng.uniform(1.0, 1.35) + rev * 0.04,
            "capex": -rev * rng.uniform(0.02, 0.08),
            "dividends_paid": -max(net, 0) * payout,
            "shares": shares,
            "rnd": rev * (0.15 if sector in ("Technology", "Healthcare") else 0.01),
        })
    cur = annual[-1]
    eps = cur["net_income"] / cur["shares"]
    if eps > 0:
        price = eps * mult * rng.uniform(0.9, 1.1)
    else:
        price = cur["revenue"] / cur["shares"] * mult
    price = round(price, 2)
    eps_cy = eps * (1 + g * 0.8) if eps > 0 else eps * 0.7
    eps_ny = eps_cy * (1 + g * 0.8) if eps_cy > 0 else eps_cy * 0.5
    revision = tone * 0.04 + rng.uniform(-0.01, 0.01)
    stock = {
        "ticker": t, "name": name, "sector": sector, "industry": industry,
        "exchange": "DEMO", "currency": "USD", "price": price,
        "market_cap": price * cur["shares"],
        "description": f"{name} is a fictional {industry.lower()} company used for StockRadar demo data.",
        "annual": annual,
        "estimates": {
            "eps_current_year": eps_cy, "eps_next_year": eps_ny,
            "eps_growth_5y": g * 0.9 if g > 0 else None,
            "eps_trend_now": eps_ny, "eps_trend_90d": eps_ny / (1 + revision) if eps_ny > 0 else None,
        },
        "analyst": {"target_price": round(price * (1 + upside), 2), "rating": round(3.4 + upside * 4, 1)},
        "demo": True,
    }
    vol = 0.22 + abs(g) * 0.6 + (0.2 if buzz > 2 else 0)
    drift = 0.04 + g * 0.5 + tone * 0.1
    prices = _price_series(rng, price, vol, drift)
    return stock, prices, (tone, buzz, insiders)


_HEADLINES = {
    1: ["{n} beats earnings estimates and raises full-year guidance",
        "Analysts upgrade {n} citing strong demand",
        "{n} announces $2B share buyback program",
        "{n} wins multi-year contract with major customer"],
    0: ["{n} to present at industry conference next week",
        "{n} reports quarterly results in line with expectations",
        "{n} names new chief financial officer"],
    -1: ["{n} shares slide after weak quarterly outlook",
         "Regulators open inquiry into {n} business practices",
         "{n} misses revenue estimates as costs rise",
         "Short seller report targets {n}"],
}


def generate():
    """Returns dict with stocks, prices, spy, news, social, posts, insider."""
    stocks, prices, news, social, posts, insider = {}, {}, [], [], [], []
    now = datetime.now(timezone.utc)
    for p in PROFILES:
        s, px, (tone, buzz, insiders) = _company(p)
        t = s["ticker"]
        stocks[t], prices[t] = s, px
        rng = _rng(t + "news")
        for i in range(rng.randint(3, 6)):
            bucket = 1 if rng.random() < 0.5 + tone / 2 else (-1 if rng.random() < 0.6 else 0)
            title = rng.choice(_HEADLINES[bucket]).format(n=s["name"])
            sent = max(-1, min(1, bucket * rng.uniform(0.4, 0.9) + rng.uniform(-0.1, 0.1)))
            news.append({
                "url": f"https://example.com/demo/{t.lower()}/{i}",
                "ticker": t, "title": title, "source": "Demo Wire",
                "published_at": (now - timedelta(hours=rng.uniform(1, 160))).isoformat(),
                "sentiment": round(sent, 2),
                "impact": "high" if abs(sent) > 0.7 else "medium" if abs(sent) > 0.3 else "low",
                "summary": f"[Demo] {title}.",
            })
        base = rng.randint(5, 60)
        for d in range(31):
            day = (now - timedelta(days=30 - d)).date().isoformat()
            spike = buzz if d >= 27 else 1.0
            mentions = max(0, int(base * spike * rng.uniform(0.7, 1.3)))
            bull = int(mentions * (0.5 + tone / 3) * rng.uniform(0.8, 1.0))
            social.append((t, "reddit", day, mentions, bull, max(0, int(mentions * 0.8) - bull)))
        for j in range(min(3, int(buzz))):
            posts.append({
                "id": f"demo-{t}-{j}", "source": "reddit", "ticker": t,
                "title": f"[Demo] What do you all think about ${t}? " + ("Huge upside here" if tone > 0 else "Is this a value trap?"),
                "url": f"https://example.com/demo/r/{t.lower()}/{j}",
                "created_at": (now - timedelta(hours=rng.uniform(1, 72))).isoformat(),
                "score": rng.randint(10, 900), "sentiment": "bullish" if tone > 0 else "bearish",
            })
        for k in range(insiders):
            shares = rng.randint(2_000, 40_000)
            insider.append({
                "ticker": t, "filed_at": (now - timedelta(days=rng.randint(2, 80))).date().isoformat(),
                "owner": f"Demo Insider {k + 1}", "title": rng.choice(["CEO", "CFO", "Director", "COO"]),
                "code": "P", "shares": shares, "price": s["price"], "value": shares * s["price"],
            })
    spy = _price_series(random.Random(42), 520.0, 0.16, 0.10)
    return {"stocks": stocks, "prices": prices, "spy": spy, "news": news,
            "social": social, "posts": posts, "insider": insider}

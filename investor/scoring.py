"""
Turns per-stock metrics into 0–100 scores, style tags, "why it's here"
bullets and screener presets. Pure functions, no I/O.

Each group score is the average percentile rank of its metrics against peers
(same sector when the sector has enough names, otherwise the whole universe).
"""

from collections import defaultdict

import metrics as M

MIN_SECTOR_PEERS = 8

# metric -> (group, higher_is_better)
FACTORS = {
    # value
    "pe": ("value", False),
    "ev_ebitda": ("value", False),
    "p_fcf": ("value", False),
    "pb": ("value", False),
    "graham_discount": ("value", True),
    "dcf_mos": ("value", True),
    "fcf_yield": ("value", True),
    "dividend_yield": ("value", True),
    # growth
    "rev_cagr_3y": ("growth", True),
    "eps_cagr_3y": ("growth", True),
    "fwd_eps_growth": ("growth", True),
    "eps_revision_90d": ("growth", True),
    "peg": ("growth", False),
    "gross_margin_trend": ("growth", True),
    "rule_of_40": ("growth", True),
    # quality
    "roic": ("quality", True),
    "roe": ("quality", True),
    "gross_margin": ("quality", True),
    "op_margin_stability": ("quality", False),
    "fcf_conversion": ("quality", True),
    "share_change_3y": ("quality", False),
    "piotroski": ("quality", True),
    "altman_z": ("quality", True),
    "debt_equity": ("quality", False),
    # momentum & sentiment
    "rs_12m": ("momentum", True),
    "ret_6m": ("momentum", True),
    "pos_52w": ("momentum", True),
    "news_sentiment": ("momentum", True),
    "buzz_z": ("momentum", True),
    "insider_buyers": ("momentum", True),
}

GROUPS = ("value", "growth", "quality", "momentum")
WEIGHTS = {"value": 0.30, "growth": 0.30, "quality": 0.25, "momentum": 0.15}


def _percentile(value, peers, higher_better):
    """Share of peers this value beats (ties count half)."""
    if not peers:
        return None
    worse = sum(1 for p in peers if (p < value if higher_better else p > value))
    ties = sum(1 for p in peers if p == value) - 1
    return (worse + 0.5 * max(ties, 0)) / max(len(peers) - 1, 1)


def score_universe(items: dict) -> dict:
    """
    items: {ticker: {"sector": str, "metrics": dict}}
    returns {ticker: {"value", "growth", "quality", "momentum", "composite", "factor_pct"}}
    """
    by_sector = defaultdict(list)
    for t, it in items.items():
        by_sector[it.get("sector") or "Other"].append(t)

    def peer_values(tickers, key):
        out = []
        for t in tickers:
            v = items[t]["metrics"].get(key)
            if isinstance(v, bool):
                v = float(v)
            if isinstance(v, (int, float)):
                out.append(v)
        return out

    universe = list(items)
    cache = {}
    results = {}
    for t, it in items.items():
        sector = it.get("sector") or "Other"
        peers_t = by_sector[sector] if len(by_sector[sector]) >= MIN_SECTOR_PEERS else universe
        pool_key = sector if peers_t is not universe else "*"
        m = it["metrics"]
        negatives = set(m.get("_negative", []))
        group_vals = defaultdict(list)
        factor_pct = {}
        for key, (group, hib) in FACTORS.items():
            v = m.get(key)
            if isinstance(v, bool):
                v = float(v)
            if v is None:
                if key in negatives:
                    factor_pct[key] = 0.0
                    group_vals[group].append(0.0)
                continue
            ck = (pool_key, key)
            if ck not in cache:
                cache[ck] = peer_values(peers_t, key)
            p = _percentile(v, cache[ck], hib)
            if p is not None:
                factor_pct[key] = p
                group_vals[group].append(p)
        scores = {}
        for g in GROUPS:
            vals = group_vals.get(g)
            scores[g] = round(100 * sum(vals) / len(vals), 1) if vals else None
        avail = {g: s for g, s in scores.items() if s is not None}
        wsum = sum(WEIGHTS[g] for g in avail)
        scores["composite"] = round(sum(WEIGHTS[g] * s for g, s in avail.items()) / wsum, 1) if wsum else None
        scores["factor_pct"] = factor_pct
        results[t] = scores
    return results


# ── Style tags ───────────────────────────────────────────────────────────────

def _g(m, k, default=None):
    v = m.get(k)
    return default if v is None else v


TAGS = [
    ("Undervalued Quality", "Cheap vs peers and a high-quality business.",
     lambda m, s: (s["value"] or 0) >= 65 and (s["quality"] or 0) >= 65),
    ("GARP", "Growth at a reasonable price (PEG < 1.5 with solid growth).",
     lambda m, s: (s["growth"] or 0) >= 60 and (s["value"] or 0) >= 45 and 0 < _g(m, "peg", 9) < 1.5),
    ("Hypergrowth", "Revenue compounding 25%+ a year.",
     lambda m, s: _g(m, "rev_cagr_3y", 0) >= 0.25),
    ("Dividend Compounder", "2%+ yield, covered payout, high quality.",
     lambda m, s: _g(m, "dividend_yield", 0) >= 0.02 and 0 < _g(m, "payout_ratio", 9) < 0.7
                  and (s["quality"] or 0) >= 55),
    ("Deep Value", "Trades below Graham Number or a 30%+ DCF discount, with healthy books.",
     lambda m, s: (_g(m, "graham_discount", -1) > 0 or _g(m, "dcf_mos", -1) >= 0.3)
                  and _g(m, "piotroski", 0) >= 6 and (s["value"] or 0) >= 60),
    ("Turnaround", "Fundamentals improving while the price is still beaten down.",
     lambda m, s: _g(m, "piotroski", 0) >= 7 and _g(m, "pos_52w", 1) < 0.35),
    ("Insiders Buying", "Several insiders bought on the open market recently.",
     lambda m, s: _g(m, "insider_buyers", 0) >= 2),
    ("Buzzing", "Social-media mentions far above normal.",
     lambda m, s: _g(m, "buzz_z", 0) >= 2),
    ("Hype Warning", "Lots of chatter but weak fundamentals — be careful.",
     lambda m, s: _g(m, "buzz_z", 0) >= 2 and ((s["quality"] or 0) < 40 or (s["value"] or 0) < 25)),
]
TAG_INFO = {name: desc for name, desc, _ in TAGS}


def tags_for(m: dict, s: dict) -> list:
    return [name for name, _, rule in TAGS if rule(m, s)]


def reasons_for(checks: list, factor_pct: dict, n_good=3, n_bad=1) -> dict:
    """Pick the strongest passing checks and the weakest failing one."""
    def strength(c):
        return factor_pct.get(c["key"], 0.5)
    good = sorted([c for c in checks if c["pass"]], key=strength, reverse=True)[:n_good]
    bad = sorted([c for c in checks if not c["pass"]], key=strength)[:n_bad]
    return {"good": [c["why"] for c in good], "bad": [c["why"] for c in bad]}


# ── Screener presets ─────────────────────────────────────────────────────────

def _lt(m, k, x):
    v = m.get(k)
    return v is not None and v < x


def _gt(m, k, x):
    v = m.get(k)
    return v is not None and v > x


PRESETS = {
    "buffett": {
        "name": "Buffett-style",
        "desc": "Durable, high-return businesses with little debt at a fair price.",
        "rule": lambda m, s: _gt(m, "roe", 0.15) and _gt(m, "roic", 0.12) and _lt(m, "debt_equity", 0.8)
                             and _lt(m, "op_margin_stability", 0.05) and _gt(m, "fcf", 0) and (s["value"] or 0) >= 40,
    },
    "graham": {
        "name": "Graham Defensive",
        "desc": "Ben Graham's defensive investor: low P/E × P/B, strong balance sheet, pays dividends.",
        "rule": lambda m, s: _gt(m, "pe", 0) and _lt(m, "pe", 15) and (m.get("pe") or 99) * (m.get("pb") or 99) < 22.5
                             and _gt(m, "current_ratio", 1.5) and _gt(m, "dividend_yield", 0),
    },
    "garp": {
        "name": "GARP",
        "desc": "Growth at a reasonable price — PEG under 1.5, double-digit EPS growth, good returns.",
        "rule": lambda m, s: _gt(m, "peg", 0) and _lt(m, "peg", 1.5) and _gt(m, "eps_cagr_3y", 0.10) and _gt(m, "roe", 0.12),
    },
    "hypergrowth": {
        "name": "Hypergrowth",
        "desc": "Revenue growing 25%+ a year with strong gross margins.",
        "rule": lambda m, s: _gt(m, "rev_cagr_3y", 0.25) and _gt(m, "gross_margin", 0.5),
    },
    "dividend": {
        "name": "Dividend",
        "desc": "2.5%+ yield that earnings can comfortably cover, moderate debt.",
        "rule": lambda m, s: _gt(m, "dividend_yield", 0.025) and _gt(m, "payout_ratio", 0) and _lt(m, "payout_ratio", 0.75)
                             and _lt(m, "debt_equity", 1.5),
    },
    "deep_value": {
        "name": "Deep Value",
        "desc": "Below Graham Number or 30%+ under DCF value, with Piotroski ≥ 6.",
        "rule": lambda m, s: (_gt(m, "graham_discount", 0) or _gt(m, "dcf_mos", 0.3)) and (m.get("piotroski") or 0) >= 6
                             and (s["value"] or 0) >= 60,
    },
    "momentum_quality": {
        "name": "Quality Momentum",
        "desc": "High-quality companies already beating the market.",
        "rule": lambda m, s: (s["quality"] or 0) >= 60 and _gt(m, "rs_12m", 0) and m.get("above_sma200") is True,
    },
}


def screen(rows: list, preset: str = None, min_scores: dict = None, sector: str = None,
           max_pe: float = None, min_yield: float = None, tag: str = None, q: str = None) -> list:
    out = []
    for r in rows:
        m, s = r["metrics"], r
        if preset and preset in PRESETS and not PRESETS[preset]["rule"](m, s):
            continue
        if min_scores and any((s.get(g) or 0) < v for g, v in min_scores.items() if v):
            continue
        if sector and r.get("sector") != sector:
            continue
        if max_pe is not None and not (m.get("pe") and m["pe"] <= max_pe):
            continue
        if min_yield is not None and (m.get("dividend_yield") or 0) < min_yield:
            continue
        if tag and tag not in (r.get("tags") or []):
            continue
        if q and q.lower() not in (r["ticker"] + " " + (r.get("name") or "")).lower():
            continue
        out.append(r)
    return out


def build_rows(stocks: dict, prices: dict, spy: list, signals: dict) -> list:
    """Full pipeline: metrics → checklist → universe scores → tags/reasons."""
    items = {}
    for t, s in stocks.items():
        m = M.analyze(s, prices.get(t), spy, signals.get(t))
        if m.get("price") is None:
            continue
        items[t] = {"sector": s.get("sector"), "metrics": m, "stock": s}
    scores = score_universe(items)
    rows = []
    for t, it in items.items():
        m, sc = it["metrics"], scores[t]
        checks = M.checklist(m)
        rows.append({
            "ticker": t,
            "name": it["stock"].get("name"),
            "sector": it["sector"],
            "price": m.get("price"),
            "market_cap": m.get("market_cap"),
            **{g: sc[g] for g in GROUPS},
            "composite": sc["composite"],
            "tags": tags_for(m, sc),
            "metrics": m,
            "checks": checks,
            "reasons": reasons_for(checks, sc["factor_pct"]),
        })
    rows.sort(key=lambda r: r["composite"] or 0, reverse=True)
    return rows

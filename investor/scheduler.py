"""
Background jobs for StockRadar.

Same approach as CheapTicket's scheduler: each job self-reschedules with a
threading.Timer, and progress events go to a queue that /api/status/stream
relays as Server-Sent Events.
"""

import logging
import queue
import statistics
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import config
import db
import fixtures
import scoring
from providers import eodhd, llm, sec_edgar, social

logger = logging.getLogger(__name__)

BENCHMARK = "SPY"

_event_queue: queue.Queue = queue.Queue(maxsize=500)
_rescore_lock = threading.Lock()


def get_event_queue() -> queue.Queue:
    return _event_queue


def _push(data: dict):
    try:
        _event_queue.put_nowait(data)
    except queue.Full:
        pass


# ── Signals derived from news / social / insider tables ─────────────────────

def compute_signals() -> dict:
    sig = {}
    for t, (s, n) in db.news_sentiment(7).items():
        sig.setdefault(t, {}).update(news_sentiment=s, news_count=n)

    today = datetime.now(timezone.utc).date()
    for t, days in db.social_daily(31).items():
        by_day = {d: (m, b, s) for d, m, b, s in days}
        series = [by_day.get((today - timedelta(days=i)).isoformat(), (0, 0, 0)) for i in range(30, -1, -1)]
        recent = [x[0] for x in series[-3:]]
        base = [x[0] for x in series[:-3]]
        mean = statistics.mean(base) if base else 0
        sd = statistics.pstdev(base) if len(base) > 1 else 0
        cur = statistics.mean(recent)
        z = (cur - mean) / max(sd, 1, mean * 0.25) if (mean or cur) else 0
        last7 = series[-7:]
        bull, bear = sum(x[1] for x in last7), sum(x[2] for x in last7)
        sig.setdefault(t, {}).update(
            buzz_z=round(z, 2) if cur >= 5 else min(round(z, 2), 1.0),   # ignore spikes on tiny counts
            mentions_7d=sum(x[0] for x in last7),
            bull_ratio=bull / (bull + bear) if bull + bear else None,
        )

    buyers, net = {}, {}
    for tx in db.get_insider(days=90):
        if tx["code"] == "P":
            buyers.setdefault(tx["ticker"], set()).add(tx["owner"])
            net[tx["ticker"]] = net.get(tx["ticker"], 0) + (tx["value"] or 0)
        else:
            net[tx["ticker"]] = net.get(tx["ticker"], 0) - (tx["value"] or 0)
    for t in set(buyers) | set(net):
        sig.setdefault(t, {}).update(insider_buyers=len(buyers.get(t, ())), insider_net_value=net.get(t, 0))
    return sig


def rescore():
    with _rescore_lock:
        stocks = db.get_all_fundamentals()
        prices = db.get_all_prices()
        spy = prices.pop(BENCHMARK, [])
        rows = scoring.build_rows(stocks, prices, spy, compute_signals())
        db.put_analysis(rows)
        _push({"type": "rescored", "count": len(rows)})
        logger.info(f"Rescored {len(rows)} stocks")
        return len(rows)


# ── Demo data ────────────────────────────────────────────────────────────────

def seed_fixtures():
    d = fixtures.generate()
    db.clear_all()
    for t, s in d["stocks"].items():
        db.put_fundamentals(t, s)
        db.put_prices(t, d["prices"][t])
    db.put_prices(BENCHMARK, d["spy"])
    db.put_news(d["news"])
    for row in d["social"]:
        db.set_social(*row)
    db.put_posts(d["posts"])
    db.put_insider(d["insider"])
    db.put_digest(datetime.now(timezone.utc).date().isoformat(),
                  "Demo mode: these are fictional companies with synthetic numbers so you can explore "
                  "the dashboard. Add an EODHD API key to load real US stocks.\n\n"
                  "Educational only — not financial advice.")
    rescore()


# ── Live jobs ────────────────────────────────────────────────────────────────

def _universe() -> list:
    known = list(db.get_all_fundamentals())
    return known or eodhd.get_universe()


def job_fundamentals():
    tickers = eodhd.get_universe() or _universe()
    ok = err = 0
    for i, t in enumerate(tickers):
        try:
            db.put_fundamentals(t, eodhd.get_fundamentals(t))
            ok += 1
        except Exception as e:
            err += 1
            logger.warning(f"fundamentals {t}: {e}")
        _push({"type": "progress", "job": "fundamentals", "index": i + 1, "total": len(tickers), "ticker": t})
    return ok, err


def job_prices():
    ok = err = 0
    tickers = _universe() + [BENCHMARK]
    for i, t in enumerate(tickers):
        try:
            db.put_prices(t, eodhd.get_prices(t))
            ok += 1
        except Exception as e:
            err += 1
            logger.warning(f"prices {t}: {e}")
        _push({"type": "progress", "job": "prices", "index": i + 1, "total": len(tickers), "ticker": t})
    return ok, err


def _focus_tickers(n: int) -> list:
    """Highest-scoring + most-buzzing names get the frequent refreshes."""
    rows = db.get_analysis() or []
    top = [r["ticker"] for r in rows[:n]]
    buzz = sorted(rows, key=lambda r: (r["metrics"] or {}).get("mentions_7d") or 0, reverse=True)[: n // 4]
    return list(dict.fromkeys(top + [r["ticker"] for r in buzz])) or _universe()[:n]


def job_news():
    ok = err = 0
    for t in _focus_tickers(int(config.get("news_top_n"))):
        try:
            db.put_news(eodhd.get_news(t))
            ok += 1
        except Exception as e:
            err += 1
            logger.warning(f"news {t}: {e}")
    if llm.available():
        try:
            pending = db.untagged_news(limit=60)
            tagged = {x["id"]: x for x in llm.tag_headlines(pending)}
            db.put_news([{**p, **{k: tagged[p["id"]][k] for k in ("sentiment", "impact", "summary")}}
                         for p in pending if p["id"] in tagged])
        except Exception as e:
            logger.warning(f"news tagging: {e}")
    return ok, err


def job_social():
    universe = set(_universe())
    today = datetime.now(timezone.utc).date().isoformat()
    ok = err = 0
    try:
        mentions, posts = social.reddit_scan(universe)
        for t, n in mentions.items():
            db.add_social(t, "reddit", today, mentions=n)
        db.put_posts(posts)
        ok += 1
    except Exception as e:
        err += 1
        logger.warning(f"reddit: {e}")
    for t in _focus_tickers(int(config.get("stocktwits_top_n"))):
        try:
            n, bull, bear = social.stocktwits_symbol(t)
            db.set_social(t, "stocktwits", today, n, bull, bear)
            ok += 1
        except Exception as e:
            err += 1
            logger.debug(f"stocktwits {t}: {e}")
    return ok, err


def job_insider():
    ok = err = 0
    for t in _universe():
        try:
            db.put_insider(sec_edgar.get_insider_trades(t))
            ok += 1
        except Exception as e:
            err += 1
            logger.debug(f"insider {t}: {e}")
    return ok, err


def job_digest():
    if not llm.available():
        return 0, 0
    rows = db.get_analysis() or []

    def brief(r):
        return {"ticker": r["ticker"], "name": r["name"], "sector": r["sector"], "tags": r["tags"],
                "scores": {g: r[g] for g in ("value", "growth", "quality", "momentum")},
                "why": r["reasons"]["good"], "caution": r["reasons"]["bad"]}

    ctx = {
        "top_value": [brief(r) for r in sorted(rows, key=lambda r: r["value"] or 0, reverse=True)[:5]],
        "top_growth": [brief(r) for r in sorted(rows, key=lambda r: r["growth"] or 0, reverse=True)[:5]],
        "buzzing": [brief(r) for r in rows if "Buzzing" in r["tags"]][:5],
        "headlines": [{"ticker": n["ticker"], "title": n["title"], "sentiment": n["sentiment"]}
                      for n in db.get_news(limit=25, days=2)],
        "benchmark_1m": _benchmark_return(21),
    }
    db.put_digest(datetime.now(timezone.utc).date().isoformat(), llm.daily_digest(ctx))
    return 1, 0


def job_alerts():
    """E-mail Premium users when a watchlist stock's scores move ≥10 points or gains/loses a tag."""
    import entitlements
    import mailer
    rows = {r["ticker"]: r for r in db.get_analysis()}
    base = (config.get("base_url") or "").rstrip("/")
    sent = 0
    for u in db.list_users(limit=100000):
        if not u["email_verified"] or not entitlements.PLANS[entitlements.effective_plan(u)]["alerts"]:
            continue
        lines = []
        for t in db.watchlist_get(u["id"]):
            r = rows.get(t)
            if not r:
                continue
            snap = {g: r[g] for g in ("composite", "value", "growth", "quality", "momentum")} | {"tags": r["tags"]}
            prev = db.alert_snapshot(u["id"], t)
            db.put_alert_snapshot(u["id"], t, snap)
            if not prev:
                continue
            changes = [f"{g} {prev[g]:.0f} → {snap[g]:.0f}" for g in ("composite", "value", "growth", "quality", "momentum")
                       if prev.get(g) is not None and snap[g] is not None and abs(snap[g] - prev[g]) >= 10]
            changes += [f"new tag: {x}" for x in snap["tags"] if x not in prev["tags"]]
            changes += [f"lost tag: {x}" for x in prev["tags"] if x not in snap["tags"]]
            if changes:
                lines.append(f"{t} ({r['name']}): " + "; ".join(changes) + f"\n  {base}/stock/{t}")
        if lines:
            mailer.send(u["email"], f"StockRadar alerts: {len(lines)} watchlist change(s)",
                        "Changes since your last alert:\n\n" + "\n".join(lines) +
                        f"\n\nManage your watchlist: {base}/watchlist\n\nEducational only — not financial advice.")
            sent += 1
    return sent, 0


def _benchmark_return(days):
    px = [p[1] for p in db.get_prices(BENCHMARK)]
    return px[-1] / px[-days - 1] - 1 if len(px) > days else None


# ── Scheduling ───────────────────────────────────────────────────────────────

JOBS = {
    # name: (function, interval hours, rescore after?)
    "fundamentals": (job_fundamentals, 24 * 7, True),
    "prices": (job_prices, 24, True),
    "news": (job_news, 1, True),
    "social": (job_social, 1 / 3, True),
    "insider": (job_insider, 24, True),
    "digest": (job_digest, 24, False),
    "alerts": (job_alerts, 24, False),
}

_state = {name: {"running": False, "next_run": None} for name in JOBS}
_timers: dict = {}
_job_lock = threading.Lock()


def _run(name: str):
    fn, interval_h, rescore_after = JOBS[name]
    with _job_lock:
        if _state[name]["running"]:
            return
        _state[name]["running"] = True
    log_id = db.start_job(name)
    _push({"type": "job_start", "job": name})
    ok = err = 0
    try:
        ok, err = fn()
        if rescore_after and ok:
            rescore()
    except Exception as e:
        err += 1
        logger.error(f"Job {name} failed: {e}", exc_info=True)
    finally:
        db.finish_job(log_id, ok, err)
        _state[name]["running"] = False
        _push({"type": "job_done", "job": name, "ok": ok, "err": err})
        _schedule(name, interval_h * 3600)


def _schedule(name: str, delay_s: float):
    if _timers.get(name):
        _timers[name].cancel()
    _state[name]["next_run"] = (datetime.now(timezone.utc) + timedelta(seconds=delay_s)).isoformat()
    t = threading.Timer(delay_s, lambda: _run(name))
    t.daemon = True
    t.start()
    _timers[name] = t


def run_job(name: str) -> bool:
    if name not in JOBS or config.fixture_mode():
        return False
    threading.Thread(target=_run, args=(name,), daemon=True).start()
    return True


def get_status() -> dict:
    last = db.last_jobs()
    return {
        "demo": config.fixture_mode(),
        "llm": llm.available(),
        "jobs": {n: {**_state[n], "last": last.get(n)} for n in JOBS},
    }


def start():
    db.init_db()
    if config.fixture_mode():
        stocks = db.get_all_fundamentals()
        if not stocks or not next(iter(stocks.values())).get("demo"):
            logger.info("Demo mode: seeding synthetic fixtures")
            seed_fixtures()
        else:
            rescore()
        return
    stocks = db.get_all_fundamentals()
    if stocks and next(iter(stocks.values())).get("demo"):
        logger.info("Live key configured: clearing demo data")
        db.clear_all()
        stocks = {}
    order = ["fundamentals", "prices", "insider", "news", "social", "digest", "alerts"]
    if not stocks:
        # First boot: run everything once, in dependency order; each job then reschedules itself.
        threading.Thread(target=lambda: [_run(n) for n in order], daemon=True).start()
        return
    last = db.last_jobs()
    for i, name in enumerate(order):
        interval_s = JOBS[name][1] * 3600
        finished = (last.get(name) or {}).get("finished_at")
        age = ((datetime.now(timezone.utc) - datetime.fromisoformat(finished)).total_seconds()
               if finished else interval_s)
        _schedule(name, max(interval_s - age, 30 + i * 30))
    rescore()

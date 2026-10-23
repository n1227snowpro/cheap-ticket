import json
import logging
import os

from flask import Flask, Response, abort, jsonify, render_template, request, stream_with_context

import db
import scheduler
import scoring

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

KEY_METRICS = ("pe", "peg", "p_fcf", "dividend_yield", "rev_cagr_3y", "eps_cagr_3y", "roic", "roe",
               "piotroski", "altman_z", "dcf_mos", "ret_6m", "rs_12m", "buzz_z", "mentions_7d",
               "insider_buyers", "news_sentiment", "gross_margin", "debt_equity", "target_upside")


def _light(r: dict) -> dict:
    m = r.get("metrics") or {}
    return {
        **{k: r[k] for k in ("ticker", "name", "sector", "price", "market_cap", "composite",
                             "value", "growth", "quality", "momentum", "tags", "reasons")},
        "m": {k: m.get(k) for k in KEY_METRICS},
    }


# ── Pages ────────────────────────────────────────────────────────────────────

@app.route("/")
def page_today():
    return render_template("today.html", page="today")


@app.route("/screener")
def page_screener():
    return render_template("screener.html", page="screener")


@app.route("/stock/<ticker>")
def page_stock(ticker):
    return render_template("stock.html", page="stock", ticker=ticker.upper())


@app.route("/feed")
def page_feed():
    return render_template("feed.html", page="feed")


@app.route("/watchlist")
def page_watchlist():
    return render_template("watchlist.html", page="watchlist")


@app.route("/learn")
def page_learn():
    return render_template("learn.html", page="learn")


# ── JSON API ─────────────────────────────────────────────────────────────────

@app.route("/api/meta")
def api_meta():
    rows = db.get_analysis()
    return jsonify({
        "presets": {k: {"name": p["name"], "desc": p["desc"]} for k, p in scoring.PRESETS.items()},
        "tags": scoring.TAG_INFO,
        "sectors": sorted({r["sector"] for r in rows if r["sector"]}),
        "count": len(rows),
        "status": scheduler.get_status(),
    })


@app.route("/api/today")
def api_today():
    rows = db.get_analysis()

    def top(key, n=6, where=lambda r: True):
        pool = [r for r in rows if r.get(key) is not None and where(r)]
        return [_light(r) for r in sorted(pool, key=lambda r: r[key], reverse=True)[:n]]

    m = lambda r, k: (r["metrics"] or {}).get(k) or 0  # noqa: E731
    sectors = {}
    for r in rows:
        s = sectors.setdefault(r["sector"], {"sector": r["sector"], "n": 0, "ret_1m": 0.0, "composite": 0.0})
        s["n"] += 1
        s["ret_1m"] += m(r, "ret_1m")
        s["composite"] += r["composite"] or 0
    for s in sectors.values():
        s["ret_1m"] /= s["n"]
        s["composite"] /= s["n"]

    spy = db.get_prices(scheduler.BENCHMARK)
    spy_close = [p[1] for p in spy]
    bench = None
    if len(spy_close) > 22:
        bench = {"price": spy_close[-1], "ret_1d": spy_close[-1] / spy_close[-2] - 1,
                 "ret_1m": spy_close[-1] / spy_close[-22] - 1,
                 "spark": spy_close[-60:]}

    return jsonify({
        "status": scheduler.get_status(),
        "benchmark": bench,
        "sectors": sorted(sectors.values(), key=lambda s: s["ret_1m"], reverse=True),
        "digest": db.latest_digest(),
        "top_value": top("value", where=lambda r: (r["quality"] or 0) >= 40),
        "top_growth": top("growth", where=lambda r: (r["quality"] or 0) >= 35),
        "top_overall": top("composite"),
        "insiders": [_light(r) for r in sorted(
            [r for r in rows if m(r, "insider_buyers") >= 1],
            key=lambda r: (m(r, "insider_buyers"), m(r, "insider_net_value")), reverse=True)[:6]],
        "buzzing": [_light(r) for r in sorted(
            [r for r in rows if m(r, "mentions_7d") > 0],
            key=lambda r: m(r, "buzz_z"), reverse=True)[:6]],
    })


def _f(name):
    v = request.args.get(name)
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


@app.route("/api/screen")
def api_screen():
    rows = db.get_analysis()
    res = scoring.screen(
        rows,
        preset=request.args.get("preset") or None,
        min_scores={g: _f(f"min_{g}") for g in scoring.GROUPS},
        sector=request.args.get("sector") or None,
        max_pe=_f("max_pe"),
        min_yield=(_f("min_yield") / 100) if _f("min_yield") is not None else None,
        tag=request.args.get("tag") or None,
        q=request.args.get("q") or None,
    )
    sort = request.args.get("sort", "composite")
    desc = request.args.get("dir", "desc") == "desc"

    def key(r):
        v = r.get(sort) if sort in r else (r.get("metrics") or {}).get(sort)
        return (v is not None, v if v is not None else 0)

    res.sort(key=key, reverse=desc)
    limit = int(request.args.get("limit", 200))
    return jsonify({"total": len(res), "results": [_light(r) for r in res[:limit]]})


@app.route("/api/stock/<ticker>")
def api_stock(ticker):
    t = ticker.upper()
    row = db.get_analysis(t)
    if not row:
        abort(404)
    stocks = db.get_all_fundamentals()
    s = stocks.get(t, {})
    peers = [_light(r) for r in db.get_analysis()
             if r["sector"] == row["sector"] and r["ticker"] != t][:8]
    social = db.social_daily(31).get(t, [])
    return jsonify({
        **row,
        "profile": {k: s.get(k) for k in ("industry", "description", "exchange", "currency", "analyst", "demo")},
        "annual": [{k: y.get(k) for k in ("year", "revenue", "net_income", "operating_cash_flow", "capex",
                                          "gross_profit", "shares", "dividends_paid")} for y in s.get("annual", [])],
        "prices": db.get_prices(t)[-260:],
        "benchmark": db.get_prices(scheduler.BENCHMARK)[-260:],
        "news": db.get_news(t, limit=20),
        "posts": db.get_posts(t, limit=10),
        "insider": db.get_insider(t, days=180),
        "social": [{"day": d, "mentions": m, "bullish": b, "bearish": br} for d, m, b, br in social],
        "peers": peers,
        "tag_info": {k: scoring.TAG_INFO[k] for k in row["tags"] if k in scoring.TAG_INFO},
    })


@app.route("/api/feed")
def api_feed():
    ticker = (request.args.get("ticker") or "").upper() or None
    kind = request.args.get("kind")
    items = []
    if kind in (None, "", "news"):
        for n in db.get_news(ticker, limit=150):
            items.append({"kind": "news", "ticker": n["ticker"], "title": n["title"], "url": n["url"],
                          "source": n["source"], "time": n["published_at"], "sentiment": n["sentiment"],
                          "impact": n["impact"], "summary": n["summary"]})
    if kind in (None, "", "social"):
        for p in db.get_posts(ticker, limit=150):
            s = {"bullish": 0.5, "bearish": -0.5}.get(p["sentiment"])
            items.append({"kind": "social", "ticker": p["ticker"], "title": p["title"], "url": p["url"],
                          "source": p["source"], "time": p["created_at"], "sentiment": s,
                          "score": p["score"]})
    mood = request.args.get("mood")
    if mood == "positive":
        items = [i for i in items if (i["sentiment"] or 0) > 0.1]
    elif mood == "negative":
        items = [i for i in items if (i["sentiment"] or 0) < -0.1]
    items.sort(key=lambda i: i["time"] or "", reverse=True)
    return jsonify({"items": items[:200]})


@app.route("/api/quotes")
def api_quotes():
    """Light rows for a comma-separated list (used by the watchlist)."""
    wanted = [t.strip().upper() for t in (request.args.get("tickers") or "").split(",") if t.strip()]
    rows = {r["ticker"]: r for r in db.get_analysis()}
    return jsonify({"results": [_light(rows[t]) for t in wanted if t in rows]})


@app.route("/api/status")
def api_status():
    return jsonify(scheduler.get_status())


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    job = request.args.get("job", "")
    if not scheduler.run_job(job):
        return jsonify({"error": f"Cannot run '{job}' (unknown job, or demo mode)"}), 400
    return jsonify({"message": f"{job} started"})


@app.route("/api/status/stream")
def api_status_stream():
    """Server-Sent Events: job progress and rescore notifications."""
    q = scheduler.get_event_queue()

    def generate():
        yield f"data: {json.dumps({'type': 'status', **scheduler.get_status()})}\n\n"
        while True:
            try:
                yield f"data: {json.dumps(q.get(timeout=20))}\n\n"
            except Exception:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "not found"}), 404
    return render_template("base.html", page="", not_found=True), 404


scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 9003)), threaded=True)

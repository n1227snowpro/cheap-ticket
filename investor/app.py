import csv
import io
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from flask import (Flask, Response, abort, jsonify, render_template, request, session,
                   stream_with_context)
from werkzeug.middleware.proxy_fix import ProxyFix

import auth
import billing
import config
import db
import entitlements as ent
import scheduler
import scoring

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # behind Traefik
app.config.update(
    SECRET_KEY=config.secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(config.get("base_url") or "").startswith("https://"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=1024 * 1024,
)
app.register_blueprint(auth.bp)
app.register_blueprint(billing.bp)

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


# ── CSRF & template context ─────────────────────────────────────────────────

CSRF_EXEMPT = {"billing.webhook"}


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@app.before_request
def check_csrf():
    if request.method in ("POST", "PUT", "DELETE") and request.endpoint not in CSRF_EXEMPT:
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        if not session.get("csrf") or not secrets.compare_digest(sent, session["csrf"]):
            if request.path.startswith("/api/"):
                return jsonify({"error": "invalid CSRF token — reload the page"}), 400
            abort(400, "Invalid form token — please reload the page and try again.")


@app.context_processor
def inject_globals():
    return {"viewer": ent.viewer_info(), "csrf_token": csrf_token}


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.template_filter("datetimeformat")
def datetimeformat(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%b %d, %Y")


def _lock(feature: str, plan: str) -> dict:
    return {"feature": feature, "required_plan": plan, "plan_name": ent.PLANS[plan]["name"]}


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


@app.route("/terms")
def page_terms():
    return render_template("legal/terms.html", page="terms")


@app.route("/privacy")
def page_privacy():
    return render_template("legal/privacy.html", page="privacy")


@app.route("/admin")
@ent.login_required
def page_admin():
    if not ent.is_admin():
        abort(404)
    users = db.list_users()
    counts = {p: 0 for p in ent.PLAN_ORDER}
    mrr = 0.0
    for u in users:
        p = ent.effective_plan(u)
        counts[p] += 1
        if p != "free":
            price = ent.PLANS[p]["price_year"] / 12 if u.get("plan_interval") == "year" else ent.PLANS[p]["price_month"]
            mrr += price if u.get("plan_status") == "active" else 0
    return render_template("admin.html", page="admin", users=users, counts=counts, mrr=mrr,
                           effective_plan=ent.effective_plan, status=scheduler.get_status())


# ── JSON API ─────────────────────────────────────────────────────────────────

@app.route("/api/me")
def api_me():
    return jsonify({**ent.viewer_info(), "csrf": csrf_token()})


@app.route("/api/meta")
def api_meta():
    rows = db.get_analysis()
    return jsonify({
        "presets": {k: {"name": p["name"], "desc": p["desc"]} for k, p in scoring.PRESETS.items()},
        "tags": scoring.TAG_INFO,
        "sectors": sorted({r["sector"] for r in rows if r["sector"]}),
        "count": len(rows),
        "status": {"demo": scheduler.get_status()["demo"]},
        "viewer": ent.viewer_info(),
        "csrf": csrf_token(),
    })


@app.route("/api/today")
def api_today():
    rows = db.get_analysis()
    lim = ent.limits()
    n_show = lim["today_per_section"] or 6

    def top(key, where=lambda r: True):
        pool = [r for r in rows if r.get(key) is not None and where(r)]
        return [_light(r) for r in sorted(pool, key=lambda r: r[key], reverse=True)[:n_show]]

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

    spy_close = [p[1] for p in db.get_prices(scheduler.BENCHMARK)]
    bench = None
    if len(spy_close) > 22:
        bench = {"price": spy_close[-1], "ret_1d": spy_close[-1] / spy_close[-2] - 1,
                 "ret_1m": spy_close[-1] / spy_close[-22] - 1, "spark": spy_close[-60:]}

    locked = {}
    digest = db.latest_digest()
    if not lim["ai"]:
        digest = None
        locked["digest"] = _lock("AI morning brief", "premium")
    if lim["today_per_section"]:
        locked["more"] = _lock("Full lists", "pro")

    return jsonify({
        "status": {"demo": scheduler.get_status()["demo"]},
        "benchmark": bench,
        "sectors": sorted(sectors.values(), key=lambda s: s["ret_1m"], reverse=True),
        "digest": digest,
        "top_value": top("value", where=lambda r: (r["quality"] or 0) >= 40),
        "top_growth": top("growth", where=lambda r: (r["quality"] or 0) >= 35),
        "insiders": [_light(r) for r in sorted(
            [r for r in rows if m(r, "insider_buyers") >= 1],
            key=lambda r: (m(r, "insider_buyers"), m(r, "insider_net_value")), reverse=True)[:n_show]],
        "buzzing": [_light(r) for r in sorted(
            [r for r in rows if m(r, "mentions_7d") > 0],
            key=lambda r: m(r, "buzz_z"), reverse=True)[:n_show]],
        "locked": locked,
    })


def _f(name):
    v = request.args.get(name)
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _screen_rows():
    """Applies the request's filters within what the viewer's plan allows."""
    lim = ent.limits()
    locked = {}
    preset = request.args.get("preset") or None
    if preset and lim["presets"] is not None and preset not in lim["presets"]:
        locked["preset"] = _lock(f"{scoring.PRESETS.get(preset, {}).get('name', preset)} preset", "pro")
        preset = "__none__"
    filters = dict(
        min_scores={g: _f(f"min_{g}") for g in scoring.GROUPS},
        sector=request.args.get("sector") or None,
        max_pe=_f("max_pe"),
        min_yield=(_f("min_yield") / 100) if _f("min_yield") is not None else None,
        tag=request.args.get("tag") or None,
    )
    if not lim["filters"]:
        if any(v for k, v in filters.items() if k != "min_scores") or any(filters["min_scores"].values()):
            locked["filters"] = _lock("Custom filters", "pro")
        filters = {}
    rows = db.get_analysis()
    res = [] if preset == "__none__" else scoring.screen(rows, preset=preset, q=request.args.get("q") or None, **filters)
    sort = request.args.get("sort", "composite")
    desc = request.args.get("dir", "desc") == "desc"

    def key(r):
        v = r.get(sort) if sort in r else (r.get("metrics") or {}).get(sort)
        if isinstance(v, (list, dict)):
            v = None
        return (v is not None, v if v is not None else 0)

    res.sort(key=key, reverse=desc)
    return res, locked


@app.route("/api/screen")
def api_screen():
    res, locked = _screen_rows()
    lim = ent.limits()
    limit = min(int(request.args.get("limit", 200)), 2000)
    if lim["screener_rows"] and len(res) > lim["screener_rows"]:
        locked["rows"] = _lock(f"All {len(res)} results", "pro")
        limit = lim["screener_rows"]
    return jsonify({"total": len(res), "results": [_light(r) for r in res[:limit]], "locked": locked})


@app.route("/api/screen.csv")
@ent.require_plan("premium")
def api_screen_csv():
    res, _ = _screen_rows()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ticker", "name", "sector", "price", "market_cap", "composite", "value", "growth",
                "quality", "momentum", "tags", *KEY_METRICS])
    for r in res:
        m = r.get("metrics") or {}
        w.writerow([r["ticker"], r["name"], r["sector"], r["price"], r["market_cap"], r["composite"],
                    r["value"], r["growth"], r["quality"], r["momentum"], "; ".join(r["tags"]),
                    *[m.get(k) for k in KEY_METRICS]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=stockradar-screen.csv"})


@app.route("/api/stock/<ticker>")
def api_stock(ticker):
    t = ticker.upper()
    row = db.get_analysis(t)
    if not row:
        abort(404)
    lim = ent.limits()
    if lim["stock_views_per_day"]:
        subj = ent.subject()
        seen = db.stock_views_today(subj)
        if t not in seen and len(seen) >= lim["stock_views_per_day"]:
            return jsonify({"error": "daily limit reached", "locked": True,
                            "required_plan": "pro", "limit": lim["stock_views_per_day"],
                            "viewed_today": seen}), 402
        seen = db.record_stock_view(subj, t)
        views_left = max(lim["stock_views_per_day"] - len(seen), 0)
    else:
        views_left = None

    s = db.get_all_fundamentals().get(t, {})
    peers = [_light(r) for r in db.get_analysis()
             if r["sector"] == row["sector"] and r["ticker"] != t][:8]
    locked = {}
    news = db.get_news(t, limit=20)
    if not lim["ai"]:
        for n in news:
            n["summary"] = None
        locked["ai_summaries"] = _lock("AI news summaries", "premium")
    insider = posts = social = []
    if lim["insider_social"]:
        insider = db.get_insider(t, days=180)
        posts = db.get_posts(t, limit=10)
        social = [{"day": d, "mentions": m, "bullish": b, "bearish": br}
                  for d, m, b, br in db.social_daily(31).get(t, [])]
    else:
        locked["insider_social"] = _lock("Insider trades & social buzz", "pro")

    return jsonify({
        **row,
        "profile": {k: s.get(k) for k in ("industry", "description", "exchange", "currency", "analyst", "demo")},
        "annual": [{k: y.get(k) for k in ("year", "revenue", "net_income", "operating_cash_flow", "capex",
                                          "gross_profit", "shares", "dividends_paid")} for y in s.get("annual", [])],
        "prices": db.get_prices(t)[-260:],
        "benchmark": db.get_prices(scheduler.BENCHMARK)[-260:],
        "news": news,
        "posts": posts,
        "insider": insider,
        "social": social,
        "peers": peers,
        "tag_info": {k: scoring.TAG_INFO[k] for k in row["tags"] if k in scoring.TAG_INFO},
        "locked": locked,
        "views_left": views_left,
    })


@app.route("/api/feed")
def api_feed():
    ticker = (request.args.get("ticker") or "").upper() or None
    kind = request.args.get("kind")
    lim = ent.limits()
    items = []
    if kind in (None, "", "news"):
        for n in db.get_news(ticker, limit=150):
            items.append({"kind": "news", "ticker": n["ticker"], "title": n["title"], "url": n["url"],
                          "source": n["source"], "time": n["published_at"], "sentiment": n["sentiment"],
                          "impact": n["impact"], "summary": n["summary"] if lim["ai"] else None})
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
    locked = {}
    cap = lim["feed_items"] or 200
    if lim["feed_items"] and len(items) > cap:
        locked["more"] = _lock("Full news & social feed", "pro")
    if not lim["ai"]:
        locked["ai_summaries"] = _lock("AI news summaries", "premium")
    return jsonify({"items": items[:cap], "locked": locked})


@app.route("/api/tickers")
def api_tickers():
    """Ticker + name for search autocomplete (no scores)."""
    return jsonify({"results": [{"ticker": r["ticker"], "name": r["name"]} for r in db.get_analysis()]})


@app.route("/api/quotes")
def api_quotes():
    """Light rows for a comma-separated list (used by the watchlist)."""
    # Capped at the plan's watchlist size so it can't be used to pull every score for free.
    wanted = [t.strip().upper() for t in (request.args.get("tickers") or "").split(",") if t.strip()]
    wanted = wanted[:ent.limits()["watchlist"]]
    rows = {r["ticker"]: r for r in db.get_analysis()}
    return jsonify({"results": [_light(rows[t]) for t in wanted if t in rows]})


@app.route("/api/watchlist", methods=["GET", "POST", "DELETE"])
@ent.login_required
def api_watchlist():
    u = ent.current_user()
    if request.method == "GET":
        return jsonify({"tickers": db.watchlist_get(u["id"]), "max": ent.limits()["watchlist"]})
    body = request.get_json(silent=True) or {}
    tickers = [t.strip().upper() for t in (body.get("tickers") or [body.get("ticker", "")]) if t and t.strip()]
    known = {r["ticker"] for r in db.get_analysis()}
    if request.method == "DELETE":
        for t in tickers:
            db.watchlist_remove(u["id"], t)
    else:
        current = db.watchlist_get(u["id"])
        cap = ent.limits()["watchlist"]
        for t in tickers:
            if t in current or t not in known:
                continue
            if len(current) >= cap:
                return jsonify({"error": f"Your plan allows {cap} watchlist stocks.", "locked": True,
                                "required_plan": "pro" if ent.plan() == "free" else "premium",
                                "tickers": current}), 402
            db.watchlist_add(u["id"], t)
            current.append(t)
    return jsonify({"tickers": db.watchlist_get(u["id"]), "max": ent.limits()["watchlist"]})


@app.route("/api/status")
def api_status():
    if not ent.is_admin():
        return jsonify({"demo": scheduler.get_status()["demo"]})
    return jsonify(scheduler.get_status())


@app.route("/api/refresh", methods=["POST"])
@ent.login_required
def api_refresh():
    if not ent.is_admin():
        abort(404)
    job = request.args.get("job", "")
    if not scheduler.run_job(job):
        return jsonify({"error": f"Cannot run '{job}' (unknown job, or demo mode)"}), 400
    return jsonify({"message": f"{job} started"})


@app.route("/api/status/stream")
@ent.login_required
def api_status_stream():
    """Server-Sent Events for admins: job progress and rescore notifications."""
    if not ent.is_admin():
        abort(404)
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

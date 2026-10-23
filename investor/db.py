import json
import sqlite3
from datetime import datetime, timedelta, timezone

import config

DB_PATH = config.DATA_DIR / "stockradar.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript("""
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS fundamentals (
                ticker      TEXT PRIMARY KEY,
                data        TEXT NOT NULL,      -- normalized stock JSON (see providers/eodhd.py)
                updated_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS prices (
                ticker      TEXT PRIMARY KEY,
                data        TEXT NOT NULL,      -- [[date, close], ...] oldest first
                updated_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS analysis (
                ticker      TEXT PRIMARY KEY,
                name        TEXT,
                sector      TEXT,
                price       REAL,
                market_cap  REAL,
                composite   REAL,
                value       REAL,
                growth      REAL,
                quality     REAL,
                momentum    REAL,
                tags        TEXT,
                metrics     TEXT,
                checks      TEXT,
                reasons     TEXT,
                updated_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS news (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                url          TEXT UNIQUE,
                ticker       TEXT,
                title        TEXT,
                source       TEXT,
                published_at TEXT,
                sentiment    REAL,             -- -1 .. 1
                impact       TEXT,             -- low | medium | high
                summary      TEXT
            );
            CREATE INDEX IF NOT EXISTS news_ticker ON news(ticker, published_at);

            CREATE TABLE IF NOT EXISTS social (
                ticker       TEXT,
                source       TEXT,             -- reddit | stocktwits
                bucket       TEXT,             -- UTC date (YYYY-MM-DD)
                mentions     INTEGER DEFAULT 0,
                bullish      INTEGER DEFAULT 0,
                bearish      INTEGER DEFAULT 0,
                PRIMARY KEY (ticker, source, bucket)
            );

            CREATE TABLE IF NOT EXISTS posts (
                id           TEXT PRIMARY KEY,
                source       TEXT,
                ticker       TEXT,
                title        TEXT,
                url          TEXT,
                created_at   TEXT,
                score        INTEGER,
                sentiment    TEXT
            );

            CREATE TABLE IF NOT EXISTS insider (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker       TEXT,
                filed_at     TEXT,
                owner        TEXT,
                title        TEXT,
                code         TEXT,             -- P = open-market buy, S = sale
                shares       REAL,
                price        REAL,
                value        REAL,
                UNIQUE (ticker, filed_at, owner, code, shares)
            );

            CREATE TABLE IF NOT EXISTS digests (
                day          TEXT PRIMARY KEY,
                text         TEXT,
                created_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                email                  TEXT UNIQUE NOT NULL,
                password_hash          TEXT,
                google_sub             TEXT UNIQUE,
                email_verified         INTEGER DEFAULT 0,
                plan                   TEXT DEFAULT 'free',     -- free | pro | premium
                plan_status            TEXT,                     -- Stripe subscription status
                plan_interval          TEXT,                     -- month | year
                current_period_end     INTEGER,                  -- unix seconds
                cancel_at_period_end   INTEGER DEFAULT 0,
                stripe_customer_id     TEXT UNIQUE,
                stripe_subscription_id TEXT,
                created_at             TEXT,
                last_login_at          TEXT
            );

            CREATE TABLE IF NOT EXISTS auth_tokens (
                token_hash   TEXT PRIMARY KEY,
                user_id      INTEGER NOT NULL,
                kind         TEXT NOT NULL,                      -- verify | reset
                expires_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS usage (
                subject      TEXT,                               -- "u:<id>" or "a:<anon id>"
                day          TEXT,
                stock_views  TEXT DEFAULT '[]',                  -- distinct tickers viewed
                PRIMARY KEY (subject, day)
            );

            CREATE TABLE IF NOT EXISTS user_watchlist (
                user_id      INTEGER,
                ticker       TEXT,
                added_at     TEXT,
                PRIMARY KEY (user_id, ticker)
            );

            CREATE TABLE IF NOT EXISTS stripe_events (
                id           TEXT PRIMARY KEY,
                type         TEXT,
                received_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS alert_state (
                user_id      INTEGER,
                ticker       TEXT,
                snapshot     TEXT,                               -- last scores/tags e-mailed about
                PRIMARY KEY (user_id, ticker)
            );

            CREATE TABLE IF NOT EXISTS job_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                job          TEXT,
                started_at   TEXT,
                finished_at  TEXT,
                ok           INTEGER DEFAULT 0,
                err          INTEGER DEFAULT 0,
                note         TEXT
            );
        """)


# ── Raw data ─────────────────────────────────────────────────────────────────

def put_fundamentals(ticker: str, data: dict):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO fundamentals VALUES (?, ?, ?)",
                  (ticker, json.dumps(data), _now()))


def get_all_fundamentals() -> dict:
    with _conn() as c:
        return {r["ticker"]: json.loads(r["data"])
                for r in c.execute("SELECT ticker, data FROM fundamentals")}


def put_prices(ticker: str, series: list):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO prices VALUES (?, ?, ?)",
                  (ticker, json.dumps(series), _now()))


def get_prices(ticker: str) -> list:
    with _conn() as c:
        r = c.execute("SELECT data FROM prices WHERE ticker = ?", (ticker,)).fetchone()
        return json.loads(r["data"]) if r else []


def get_all_prices() -> dict:
    with _conn() as c:
        return {r["ticker"]: json.loads(r["data"])
                for r in c.execute("SELECT ticker, data FROM prices")}


# ── Analysis ─────────────────────────────────────────────────────────────────

_JSON_COLS = ("tags", "metrics", "checks", "reasons")


def put_analysis(rows: list):
    now = _now()
    with _conn() as c:
        c.execute("DELETE FROM analysis")
        c.executemany("""
            INSERT INTO analysis VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [(
            r["ticker"], r["name"], r["sector"], r["price"], r["market_cap"],
            r["composite"], r["value"], r["growth"], r["quality"], r["momentum"],
            json.dumps(r["tags"]), json.dumps(r["metrics"]),
            json.dumps(r["checks"]), json.dumps(r["reasons"]), now,
        ) for r in rows])


def _decode(row) -> dict:
    d = dict(row)
    for k in _JSON_COLS:
        if k in d and d[k] is not None:
            d[k] = json.loads(d[k])
    return d


def get_analysis(ticker: str = None):
    with _conn() as c:
        if ticker:
            r = c.execute("SELECT * FROM analysis WHERE ticker = ?", (ticker,)).fetchone()
            return _decode(r) if r else None
        return [_decode(r) for r in c.execute("SELECT * FROM analysis ORDER BY composite DESC")]


# ── News / social / insider ──────────────────────────────────────────────────

def put_news(items: list):
    with _conn() as c:
        c.executemany("""
            INSERT INTO news (url, ticker, title, source, published_at, sentiment, impact, summary)
            VALUES (:url, :ticker, :title, :source, :published_at, :sentiment, :impact, :summary)
            ON CONFLICT(url) DO UPDATE SET
                sentiment = COALESCE(excluded.sentiment, news.sentiment),
                impact    = COALESCE(excluded.impact, news.impact),
                summary   = COALESCE(excluded.summary, news.summary)
        """, [{"impact": None, "summary": None, "sentiment": None, **i} for i in items])


def untagged_news(limit: int = 100) -> list:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM news WHERE summary IS NULL ORDER BY published_at DESC LIMIT ?", (limit,))]


def get_news(ticker: str = None, limit: int = 50, days: int = None) -> list:
    q, args = "SELECT * FROM news WHERE 1=1", []
    if ticker:
        q += " AND ticker = ?"
        args.append(ticker)
    if days:
        q += " AND published_at >= ?"
        args.append((datetime.now(timezone.utc) - timedelta(days=days)).isoformat())
    q += " ORDER BY published_at DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(q, args)]


def news_sentiment(days: int = 7) -> dict:
    """Average headline sentiment per ticker over the window."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        return {r["ticker"]: (r["s"], r["n"]) for r in c.execute(
            "SELECT ticker, AVG(sentiment) s, COUNT(*) n FROM news "
            "WHERE published_at >= ? AND sentiment IS NOT NULL GROUP BY ticker", (since,))}


def add_social(ticker: str, source: str, bucket: str, mentions=0, bullish=0, bearish=0):
    with _conn() as c:
        c.execute("""
            INSERT INTO social VALUES (?,?,?,?,?,?)
            ON CONFLICT(ticker, source, bucket) DO UPDATE SET
                mentions = social.mentions + excluded.mentions,
                bullish  = social.bullish + excluded.bullish,
                bearish  = social.bearish + excluded.bearish
        """, (ticker, source, bucket, mentions, bullish, bearish))


def set_social(ticker: str, source: str, bucket: str, mentions=0, bullish=0, bearish=0):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO social VALUES (?,?,?,?,?,?)",
                  (ticker, source, bucket, mentions, bullish, bearish))


def social_daily(days: int = 31) -> dict:
    """{ticker: [(day, mentions, bullish, bearish), ...]} summed over sources."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    out = {}
    with _conn() as c:
        for r in c.execute(
            "SELECT ticker, bucket, SUM(mentions) m, SUM(bullish) b, SUM(bearish) s FROM social "
            "WHERE bucket >= ? GROUP BY ticker, bucket ORDER BY bucket", (since,)):
            out.setdefault(r["ticker"], []).append((r["bucket"], r["m"], r["b"], r["s"]))
    return out


def put_posts(items: list):
    with _conn() as c:
        c.executemany("""
            INSERT OR IGNORE INTO posts VALUES (:id,:source,:ticker,:title,:url,:created_at,:score,:sentiment)
        """, [{"sentiment": None, "score": 0, **i} for i in items])


def get_posts(ticker: str = None, limit: int = 50) -> list:
    q, args = "SELECT * FROM posts", []
    if ticker:
        q += " WHERE ticker = ?"
        args.append(ticker)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(q, args)]


def put_insider(items: list):
    with _conn() as c:
        c.executemany("""
            INSERT OR IGNORE INTO insider (ticker, filed_at, owner, title, code, shares, price, value)
            VALUES (:ticker,:filed_at,:owner,:title,:code,:shares,:price,:value)
        """, items)


def get_insider(ticker: str = None, days: int = 90) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    q, args = "SELECT * FROM insider WHERE filed_at >= ?", [since]
    if ticker:
        q += " AND ticker = ?"
        args.append(ticker)
    with _conn() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY filed_at DESC", args)]


def put_digest(day: str, text: str):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO digests VALUES (?,?,?)", (day, text, _now()))


def latest_digest():
    with _conn() as c:
        r = c.execute("SELECT * FROM digests ORDER BY day DESC LIMIT 1").fetchone()
        return dict(r) if r else None


# ── Job log ──────────────────────────────────────────────────────────────────

def start_job(job: str) -> int:
    with _conn() as c:
        return c.execute("INSERT INTO job_log (job, started_at) VALUES (?, ?)", (job, _now())).lastrowid


def finish_job(log_id: int, ok: int, err: int, note: str = ""):
    with _conn() as c:
        c.execute("UPDATE job_log SET finished_at=?, ok=?, err=?, note=? WHERE id=?",
                  (_now(), ok, err, note, log_id))


def last_jobs() -> dict:
    with _conn() as c:
        return {r["job"]: dict(r) for r in c.execute(
            "SELECT * FROM job_log WHERE id IN (SELECT MAX(id) FROM job_log GROUP BY job)")}


def clear_all():
    """Used when switching between demo and live data."""
    with _conn() as c:
        for t in ("fundamentals", "prices", "analysis", "news", "social", "posts", "insider", "digests"):
            c.execute(f"DELETE FROM {t}")


# ── Users ────────────────────────────────────────────────────────────────────

USER_FIELDS = ("email", "password_hash", "google_sub", "email_verified", "plan", "plan_status",
               "plan_interval", "current_period_end", "cancel_at_period_end", "stripe_customer_id",
               "stripe_subscription_id", "last_login_at")


def create_user(email: str, password_hash: str = None, google_sub: str = None, verified=False) -> int:
    with _conn() as c:
        return c.execute(
            "INSERT INTO users (email, password_hash, google_sub, email_verified, created_at) VALUES (?,?,?,?,?)",
            (email.lower(), password_hash, google_sub, int(verified), _now())).lastrowid


def get_user(user_id=None, email=None, google_sub=None, stripe_customer_id=None):
    for col, val in (("id", user_id), ("email", email and email.lower()), ("google_sub", google_sub),
                     ("stripe_customer_id", stripe_customer_id)):
        if val is not None:
            with _conn() as c:
                r = c.execute(f"SELECT * FROM users WHERE {col} = ?", (val,)).fetchone()
                return dict(r) if r else None
    return None


def update_user(user_id: int, **fields):
    bad = set(fields) - set(USER_FIELDS)
    if bad:
        raise ValueError(f"Unknown user fields: {bad}")
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _conn() as c:
        c.execute(f"UPDATE users SET {cols} WHERE id = ?", (*fields.values(), user_id))


def delete_user(user_id: int):
    with _conn() as c:
        for t in ("user_watchlist", "auth_tokens", "alert_state"):
            c.execute(f"DELETE FROM {t} WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM usage WHERE subject = ?", (f"u:{user_id}",))
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))


def list_users(limit: int = 500) -> list:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM users ORDER BY id DESC LIMIT ?", (limit,))]


# ── Auth tokens (e-mail verification, password reset) ───────────────────────

def put_token(token_hash: str, user_id: int, kind: str, ttl_hours: int):
    exp = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
    with _conn() as c:
        c.execute("DELETE FROM auth_tokens WHERE user_id = ? AND kind = ?", (user_id, kind))
        c.execute("INSERT INTO auth_tokens VALUES (?,?,?,?)", (token_hash, user_id, kind, exp))


def take_token(token_hash: str, kind: str):
    """Single use: returns user_id and deletes the token, or None if missing/expired."""
    with _conn() as c:
        r = c.execute("SELECT * FROM auth_tokens WHERE token_hash = ? AND kind = ?", (token_hash, kind)).fetchone()
        if not r:
            return None
        c.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
        return r["user_id"] if r["expires_at"] > _now() else None


# ── Metering ────────────────────────────────────────────────────────────────

def record_stock_view(subject: str, ticker: str) -> list:
    """Adds ticker to today's distinct views for subject; returns the list."""
    day = datetime.now(timezone.utc).date().isoformat()
    with _conn() as c:
        r = c.execute("SELECT stock_views FROM usage WHERE subject = ? AND day = ?", (subject, day)).fetchone()
        views = json.loads(r["stock_views"]) if r else []
        if ticker not in views:
            views.append(ticker)
            c.execute("INSERT OR REPLACE INTO usage VALUES (?,?,?)", (subject, day, json.dumps(views)))
        return views


def stock_views_today(subject: str) -> list:
    day = datetime.now(timezone.utc).date().isoformat()
    with _conn() as c:
        r = c.execute("SELECT stock_views FROM usage WHERE subject = ? AND day = ?", (subject, day)).fetchone()
        return json.loads(r["stock_views"]) if r else []


# ── Account watchlist ───────────────────────────────────────────────────────

def watchlist_get(user_id: int) -> list:
    with _conn() as c:
        return [r["ticker"] for r in c.execute(
            "SELECT ticker FROM user_watchlist WHERE user_id = ? ORDER BY added_at", (user_id,))]


def watchlist_add(user_id: int, ticker: str):
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO user_watchlist VALUES (?,?,?)", (user_id, ticker, _now()))


def watchlist_remove(user_id: int, ticker: str):
    with _conn() as c:
        c.execute("DELETE FROM user_watchlist WHERE user_id = ? AND ticker = ?", (user_id, ticker))


# ── Stripe idempotency & alerts ─────────────────────────────────────────────

def stripe_event_seen(event_id: str) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM stripe_events WHERE id = ?", (event_id,)).fetchone() is not None


def mark_stripe_event(event_id: str, event_type: str):
    """Called only after successful processing, so failed events are retried by Stripe."""
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO stripe_events VALUES (?,?,?)", (event_id, event_type, _now()))


def alert_snapshot(user_id: int, ticker: str):
    with _conn() as c:
        r = c.execute("SELECT snapshot FROM alert_state WHERE user_id = ? AND ticker = ?", (user_id, ticker)).fetchone()
        return json.loads(r["snapshot"]) if r else None


def put_alert_snapshot(user_id: int, ticker: str, snap: dict):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO alert_state VALUES (?,?,?)", (user_id, ticker, json.dumps(snap)))

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

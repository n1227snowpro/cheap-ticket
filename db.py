import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get(
    "CHEAPTICKET_DATA",
    str(Path.home() / "Library" / "Application Support" / "CheapTicket")
))
DB_PATH = DATA_DIR / "flights.db"

DESTINATIONS = [
    {"iata": "NRT", "destination": "Tokyo",            "region": "Japan",     "flag": "🇯🇵", "slug": "taipei-to-tokyo"},
    {"iata": "KIX", "destination": "Osaka",            "region": "Japan",     "flag": "🇯🇵", "slug": "taipei-to-osaka"},
    {"iata": "CTS", "destination": "Sapporo",          "region": "Japan",     "flag": "🇯🇵", "slug": "taipei-to-sapporo"},
    {"iata": "ICN", "destination": "Seoul",            "region": "Korea",     "flag": "🇰🇷", "slug": "taipei-to-seoul"},
    {"iata": "HKG", "destination": "Hong Kong",        "region": "HK",        "flag": "🇭🇰", "slug": "taipei-to-hong-kong"},
    {"iata": "BKK", "destination": "Bangkok",          "region": "Thailand",  "flag": "🇹🇭", "slug": "taipei-to-bangkok"},
    {"iata": "SGN", "destination": "Ho Chi Minh City", "region": "Vietnam",   "flag": "🇻🇳", "slug": "taipei-to-ho-chi-minh-city"},
    {"iata": "HAN", "destination": "Hanoi",            "region": "Vietnam",   "flag": "🇻🇳", "slug": "taipei-to-hanoi"},
    {"iata": "SIN", "destination": "Singapore",        "region": "SE Asia",   "flag": "🇸🇬", "slug": "taipei-to-singapore"},
    {"iata": "DPS", "destination": "Bali",             "region": "SE Asia",   "flag": "🇮🇩", "slug": "taipei-to-bali"},
    {"iata": "MNL", "destination": "Manila",           "region": "SE Asia",   "flag": "🇵🇭", "slug": "taipei-to-manila"},
    {"iata": "CDG", "destination": "Paris",            "region": "Europe",    "flag": "🇫🇷", "slug": "taipei-to-paris"},
    {"iata": "LHR", "destination": "London",           "region": "Europe",    "flag": "🇬🇧", "slug": "taipei-to-london"},
    {"iata": "LAX", "destination": "Los Angeles",      "region": "Americas",  "flag": "🇺🇸", "slug": "taipei-to-los-angeles"},
    {"iata": "SYD", "destination": "Sydney",           "region": "Australia", "flag": "🇦🇺", "slug": "taipei-to-sydney"},
    {"iata": "FUK", "destination": "Fukuoka",          "region": "Japan",     "flag": "🇯🇵", "slug": "taipei-to-fukuoka"},
    {"iata": "OKA", "destination": "Okinawa",          "region": "Japan",     "flag": "🇯🇵", "slug": "taipei-to-okinawa"},
    {"iata": "CEB", "destination": "Cebu",             "region": "SE Asia",   "flag": "🇵🇭", "slug": "taipei-to-cebu"},
    {"iata": "KUL", "destination": "Kuala Lumpur",     "region": "SE Asia",   "flag": "🇲🇾", "slug": "taipei-to-kuala-lumpur"},
    {"iata": "HKT", "destination": "Phuket",           "region": "Thailand",  "flag": "🇹🇭", "slug": "taipei-to-phuket"},
    {"iata": "DAD", "destination": "Da Nang",          "region": "Vietnam",   "flag": "🇻🇳", "slug": "taipei-to-da-nang"},
    {"iata": "MFM", "destination": "Macau",            "region": "Macau",     "flag": "🇲🇴", "slug": "taipei-to-macau"},
    {"iata": "GUM", "destination": "Guam",             "region": "Pacific",   "flag": "🇺🇸", "slug": "taipei-to-guam"},
]


def _conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS flight_cache (
                iata         TEXT PRIMARY KEY,
                destination  TEXT NOT NULL,
                region       TEXT NOT NULL,
                flag         TEXT NOT NULL,
                slug         TEXT NOT NULL,
                price        REAL,
                currency     TEXT DEFAULT 'TWD',
                best_date    TEXT,
                booking_url  TEXT,
                airline_name TEXT,
                duration     TEXT,
                status       TEXT DEFAULT 'pending',
                error_msg    TEXT,
                cached_at    TEXT,
                updated_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS scan_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at       TEXT NOT NULL,
                finished_at      TEXT,
                destinations_ok  INTEGER DEFAULT 0,
                destinations_err INTEGER DEFAULT 0,
                trigger          TEXT DEFAULT 'auto'
            );
        """)
        # Migrate: add columns if they don't exist yet
        for col in ["ALTER TABLE flight_cache ADD COLUMN airline_name TEXT",
                    "ALTER TABLE flight_cache ADD COLUMN duration TEXT"]:
            try:
                c.execute(col)
            except Exception:
                pass  # column already exists

        # Seed rows for all destinations (INSERT OR IGNORE)
        now = datetime.now(timezone.utc).isoformat()
        for d in DESTINATIONS:
            c.execute("""
                INSERT OR IGNORE INTO flight_cache
                    (iata, destination, region, flag, slug, status, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """, (d["iata"], d["destination"], d["region"], d["flag"], d["slug"], now))


def get_all_cached():
    with _conn() as c:
        rows = c.execute("SELECT * FROM flight_cache ORDER BY price ASC NULLS LAST").fetchall()
        return [dict(r) for r in rows]


def get_one_cached(iata: str):
    with _conn() as c:
        row = c.execute("SELECT * FROM flight_cache WHERE iata = ?", (iata,)).fetchone()
        return dict(row) if row else None


def upsert_result(iata: str, data: dict):
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("""
            UPDATE flight_cache SET
                price        = ?,
                currency     = ?,
                best_date    = ?,
                booking_url  = ?,
                airline_name = ?,
                duration     = ?,
                status       = ?,
                error_msg    = ?,
                cached_at    = CASE WHEN ? = 'ok' THEN ? ELSE cached_at END,
                updated_at   = ?
            WHERE iata = ?
        """, (
            data.get("price"),
            data.get("currency", "TWD"),
            data.get("best_date"),
            data.get("booking_url"),
            data.get("airline_name", ""),
            data.get("duration", ""),
            data.get("status", "error"),
            data.get("error_msg"),
            data.get("status", "error"), now,
            now,
            iata,
        ))


def is_cache_fresh(iata: str, max_age_hours: int = 3) -> bool:
    row = get_one_cached(iata)
    if not row or not row.get("cached_at"):
        return False
    cached_at = datetime.fromisoformat(row["cached_at"])
    age = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600
    return age < max_age_hours


def all_fresh(max_age_hours: int = 3) -> bool:
    return all(is_cache_fresh(d["iata"], max_age_hours) for d in DESTINATIONS)


def start_scan_log(trigger: str = "auto") -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO scan_log (started_at, trigger) VALUES (?, ?)", (now, trigger)
        )
        return cur.lastrowid


def finish_scan_log(log_id: int, ok: int, err: int):
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("""
            UPDATE scan_log SET finished_at = ?, destinations_ok = ?, destinations_err = ?
            WHERE id = ?
        """, (now, ok, err, log_id))


def get_scan_meta():
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM scan_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

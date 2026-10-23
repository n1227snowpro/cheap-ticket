"""
StockRadar configuration.
API keys live in <INVESTOR_DATA>/config.json so they're never committed.
Environment variables of the same name (upper-cased) override the file.
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get(
    "INVESTOR_DATA",
    str(Path.home() / ".stockradar")
))
CONFIG_FILE = DATA_DIR / "config.json"

_DEFAULTS = {
    "eodhd_key": "",                 # https://eodhd.com — All-In-One plan
    "anthropic_key": "",             # optional: news tagging + daily digest
    "llm_model": "claude-opus-5-5",
    "reddit_client_id": "",          # https://www.reddit.com/prefs/apps (script app)
    "reddit_client_secret": "",
    "sec_user_agent": "StockRadar admin@example.com",  # SEC requires a contact UA
    "universe_indexes": ["GSPC.INDX", "NDX.INDX"],     # S&P 500 + Nasdaq-100
    "extra_tickers": [],
    "news_top_n": 80,                # tickers whose news is refreshed hourly
    "stocktwits_top_n": 30,
    "subreddits": ["stocks", "investing", "ValueInvesting", "wallstreetbets", "StockMarket"],

    # ── SaaS ──
    "secret_key": "",                # session signing key; generated & persisted if empty
    "base_url": "http://localhost:9003",
    "stripe_secret_key": "",
    "stripe_webhook_secret": "",
    "stripe_price_pro_month": "",
    "stripe_price_pro_year": "",
    "stripe_price_premium_month": "",
    "stripe_price_premium_year": "",
    "trial_days": 7,                 # free trial on Pro
    "google_client_id": "",
    "google_client_secret": "",
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "StockRadar <no-reply@example.com>",
    "admin_emails": "",              # comma-separated
}


def load() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = dict(_DEFAULTS)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg.update(json.load(f))
    for k in _DEFAULTS:
        env = os.environ.get(k.upper())
        if env:
            cfg[k] = env
    return cfg


def save(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            current = json.load(f)
    current.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(current, f, indent=2)


def get(key: str):
    return load().get(key)


def secret_key() -> str:
    """Session signing key: config/env value, else a random one persisted in the data dir."""
    key = load().get("secret_key")
    if key:
        return key
    path = DATA_DIR / "secret_key"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        import secrets
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def admin_emails() -> set:
    raw = load().get("admin_emails") or ""
    items = raw if isinstance(raw, list) else raw.split(",")
    return {e.strip().lower() for e in items if e.strip()}


def fixture_mode() -> bool:
    """Demo mode: synthetic data, no API calls. On automatically when no EODHD key."""
    flag = os.environ.get("FIXTURE_MODE")
    if flag is not None:
        return flag not in ("0", "false", "")
    return not load().get("eodhd_key")

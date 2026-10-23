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


def fixture_mode() -> bool:
    """Demo mode: synthetic data, no API calls. On automatically when no EODHD key."""
    flag = os.environ.get("FIXTURE_MODE")
    if flag is not None:
        return flag not in ("0", "false", "")
    return not load().get("eodhd_key")

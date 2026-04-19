"""
CheapTicket configuration.
Sensitive values are stored in ~/Library/Application Support/CheapTicket/config.json
so they survive worktree changes and aren't committed to git.
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get(
    "CHEAPTICKET_DATA",
    str(Path.home() / "Library" / "Application Support" / "CheapTicket")
))
CONFIG_FILE = DATA_DIR / "config.json"

_DEFAULTS = {
    "serpapi_keys": [],      # list of API keys — rotated round-robin
    "serpapi_key": "",       # legacy single key (still supported)
    "trip_allianceid": "8078932",
    "trip_sid": "305617530",
    "trip_sub1": "",
    "trip_sub3": "D15507018",
    "refresh_interval_hours": 24,   # daily by default
    "search_days_ahead": 28,        # search this many days from today (4 weeks out)
}


def load() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            saved = json.load(f)
        return {**_DEFAULTS, **saved}
    return dict(_DEFAULTS)


def save(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current = load()
    current.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(current, f, indent=2)


def trip_affiliate_params() -> str:
    cfg = load()
    parts = [
        f"Allianceid={cfg['trip_allianceid']}",
        f"SID={cfg['trip_sid']}",
        f"trip_sub1={cfg['trip_sub1']}",
        f"trip_sub3={cfg['trip_sub3']}",
    ]
    return "&".join(parts)


def get_api_keys() -> list:
    """Return list of active SerpAPI keys (deduped, non-empty)."""
    cfg = load()
    keys = list(cfg.get("serpapi_keys") or [])
    # Also include legacy single key if not already in the list
    legacy = cfg.get("serpapi_key", "")
    if legacy and legacy not in keys:
        keys.append(legacy)
    return [k for k in keys if k]


def add_api_key(key: str):
    """Add a new API key to the rotation list."""
    keys = get_api_keys()
    if key and key not in keys:
        keys.append(key)
        save({"serpapi_keys": keys})


def refresh_interval_hours() -> int:
    return int(load().get("refresh_interval_hours", 24))


def search_days_ahead() -> int:
    return int(load().get("search_days_ahead", 28))

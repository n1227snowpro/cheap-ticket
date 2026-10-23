"""
Social buzz: Reddit (app-only OAuth) and StockTwits public streams.
"""

import logging
import re
from datetime import datetime, timezone

import config
from providers import http

logger = logging.getLogger(__name__)

UA = "StockRadar/1.0 (investor dashboard)"

# Upper-case words that look like tickers but usually aren't
STOPWORDS = {
    "A", "I", "AI", "ALL", "AM", "AN", "ARE", "AT", "BE", "BY", "CEO", "CFO", "DD", "EPS", "ETF", "EV",
    "FOR", "GDP", "GO", "HAS", "IMO", "IPO", "IRA", "IT", "LOL", "NEW", "NOW", "ON", "ONE", "OR", "OUT",
    "PE", "SEC", "SO", "THE", "TO", "UK", "US", "USA", "USD", "YOLO", "ATH", "FED", "CPI", "OP", "EU",
    "RE", "OK", "TV", "PM", "UP", "ANY", "CAN", "CEOS", "EDIT", "TLDR", "FOMO", "WSB", "BIG", "REAL",
}
_DOLLAR = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b")
_CAPS = re.compile(r"\b([A-Z]{2,5})\b")


def extract_tickers(text: str, universe: set) -> set:
    """$TSLA always counts (if in universe); bare CAPS only if in universe and not a stopword."""
    found = {t for t in _DOLLAR.findall(text or "") if t in universe}
    found |= {t for t in _CAPS.findall(text or "") if t in universe and t not in STOPWORDS}
    return found


# ── Reddit ───────────────────────────────────────────────────────────────────

_token = {"value": None, "exp": 0}


def _reddit_token():
    now = datetime.now(timezone.utc).timestamp()
    if _token["value"] and _token["exp"] > now + 60:
        return _token["value"]
    cid, secret = config.get("reddit_client_id"), config.get("reddit_client_secret")
    if not cid or not secret:
        return None
    data = http.post("https://www.reddit.com/api/v1/access_token",
                     data={"grant_type": "client_credentials"}, auth=(cid, secret),
                     headers={"User-Agent": UA})
    _token["value"], _token["exp"] = data["access_token"], now + data.get("expires_in", 3600)
    return _token["value"]


def reddit_scan(universe: set, limit: int = 100):
    """
    Returns (mentions, posts):
      mentions: {ticker: count} across the newest `limit` posts of each subreddit
      posts:    feed items for the tickers mentioned
    """
    token = _reddit_token()
    if not token:
        return {}, []
    headers = {"Authorization": f"bearer {token}", "User-Agent": UA}
    mentions, posts = {}, []
    for sub in config.get("subreddits") or []:
        try:
            data = http.get(f"https://oauth.reddit.com/r/{sub}/new", params={"limit": limit}, headers=headers)
        except Exception as e:
            logger.warning(f"Reddit r/{sub} failed: {e}")
            continue
        for child in (data.get("data") or {}).get("children", []):
            p = child.get("data") or {}
            text = f"{p.get('title', '')} {p.get('selftext', '')[:2000]}"
            for t in extract_tickers(text, universe):
                mentions[t] = mentions.get(t, 0) + 1
                posts.append({
                    "id": f"reddit-{p.get('id')}-{t}", "source": f"r/{sub}", "ticker": t,
                    "title": p.get("title", "")[:300],
                    "url": "https://www.reddit.com" + p.get("permalink", ""),
                    "created_at": datetime.fromtimestamp(p.get("created_utc", 0), timezone.utc).isoformat(),
                    "score": p.get("score", 0),
                })
    return mentions, posts


# ── StockTwits ───────────────────────────────────────────────────────────────

def stocktwits_symbol(ticker: str):
    """(messages, bullish, bearish) posted today (UTC) among the latest ~30 messages."""
    data = http.get(f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json",
                    headers={"User-Agent": UA}, retries=1)
    today = datetime.now(timezone.utc).date().isoformat()
    msgs = [m for m in data.get("messages") or [] if (m.get("created_at") or "").startswith(today)]
    bull = sum(1 for m in msgs if ((m.get("entities") or {}).get("sentiment") or {}).get("basic") == "Bullish")
    bear = sum(1 for m in msgs if ((m.get("entities") or {}).get("sentiment") or {}).get("basic") == "Bearish")
    return len(msgs), bull, bear

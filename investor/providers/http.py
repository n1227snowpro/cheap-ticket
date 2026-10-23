"""Shared HTTP session with retry/backoff and a simple per-host rate limit."""

import logging
import threading
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_session = requests.Session()
_lock = threading.Lock()
_last_call = {}
_MIN_INTERVAL = {           # seconds between calls per host
    "www.sec.gov": 0.12,    # SEC fair-access: max 10 req/s
    "data.sec.gov": 0.12,
    "api.stocktwits.com": 1.0,
    "oauth.reddit.com": 1.0,
    "eodhd.com": 0.02,
}


def _throttle(host: str):
    gap = _MIN_INTERVAL.get(host, 0)
    if not gap:
        return
    with _lock:
        wait = _last_call.get(host, 0) + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def get(url, params=None, headers=None, retries=3, timeout=20, as_json=True, **kw):
    host = urlparse(url).hostname
    for attempt in range(retries + 1):
        _throttle(host)
        try:
            r = _session.get(url, params=params, headers=headers, timeout=timeout, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            r.raise_for_status()
            return r.json() if as_json else r.text
        except requests.RequestException as e:
            if attempt >= retries:
                raise
            logger.debug(f"GET {host} failed ({e}); retrying")
            time.sleep(2 ** attempt)


def post(url, data=None, auth=None, headers=None, timeout=20):
    r = _session.post(url, data=data, auth=auth, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

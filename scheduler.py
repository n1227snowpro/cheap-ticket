"""
Background scheduler for CheapTicket.

Uses threading.Timer for self-rescheduling. Interval is read from config
(default 24 hours) so it can be changed without restarting the app.

SSE progress events are pushed via a queue.Queue shared with app.py.
"""

import logging
import queue
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import config
import db
import scraper

logger = logging.getLogger(__name__)

# Shared state
_scanning = False
_scan_lock = threading.Lock()
_next_scan_time: Optional[datetime] = None
_event_queue: queue.Queue = queue.Queue(maxsize=200)
_timer: Optional[threading.Timer] = None
_flask_app = None


def get_status() -> dict:
    meta = db.get_scan_meta()
    interval_h = config.refresh_interval_hours()
    keys_count = len(config.get_api_keys())
    return {
        "scanning": _scanning,
        "last_updated": meta["finished_at"] if meta else None,
        "next_refresh": _next_scan_time.isoformat() if _next_scan_time else None,
        "refresh_interval_hours": interval_h,
        "api_keys_count": keys_count,
        "monthly_calls_estimate": 15 * 30,   # 1 call/dest × 15 dests × 30 days
        "monthly_free_limit": keys_count * 250,
    }


def get_event_queue() -> queue.Queue:
    return _event_queue


def _push_event(data: dict):
    try:
        _event_queue.put_nowait(data)
    except queue.Full:
        pass


def _do_scan(trigger: str = "auto"):
    global _scanning, _next_scan_time, _timer

    with _scan_lock:
        if _scanning:
            logger.info("Scan already running, skipping")
            return
        _scanning = True

    log_id = db.start_scan_log(trigger)
    ok_count = 0
    err_count = 0
    destinations = db.DESTINATIONS

    _push_event({"type": "scan_start", "total": len(destinations)})
    logger.info(f"Scan started (trigger={trigger}), {len(destinations)} destinations")

    def on_progress(iata, index, total, result):
        nonlocal ok_count, err_count
        if result.get("status") == "ok":
            ok_count += 1
        else:
            err_count += 1
        db.upsert_result(iata, result)
        _push_event({
            "type": "destination_done",
            "iata": iata,
            "index": index,
            "total": total,
            **result,
        })

    try:
        scraper.scrape_all(destinations, progress_callback=on_progress)
    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
    finally:
        db.finish_scan_log(log_id, ok_count, err_count)
        _scanning = False
        _push_event({"type": "scan_done", "ok": ok_count, "err": err_count})
        logger.info(f"Scan finished: {ok_count} ok, {err_count} errors")
        _schedule_next()


def _schedule_next():
    global _next_scan_time, _timer
    interval_s = config.refresh_interval_hours() * 3600
    _next_scan_time = datetime.now(timezone.utc) + timedelta(seconds=interval_s)
    if _timer:
        _timer.cancel()
    _timer = threading.Timer(interval_s, lambda: run_scan("auto"))
    _timer.daemon = True
    _timer.start()
    logger.info(f"Next scan in {config.refresh_interval_hours()}h at {_next_scan_time.isoformat()}")


def run_scan(trigger: str = "manual"):
    """Kick off a background scan (non-blocking)."""
    t = threading.Thread(target=_do_scan, args=(trigger,), daemon=True)
    t.start()


def run_scan_dest(iata: str):
    """Kick off a background scan for a single destination."""
    dest_list = [d for d in db.DESTINATIONS if d["iata"] == iata]
    if not dest_list:
        return False

    def _run():
        result = scraper.scrape_destination(dest_list[0])
        db.upsert_result(iata, result)
        _push_event({
            "type": "destination_done",
            "iata": iata,
            "index": 1,
            "total": 1,
            **result,
        })

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return True


def start(app):
    """Called from app.py on startup."""
    global _flask_app
    _flask_app = app

    interval_h = config.refresh_interval_hours()
    if db.all_fresh(max_age_hours=interval_h):
        logger.info(f"Cache fresh — next scan in {interval_h}h")
        _schedule_next()
    else:
        logger.info("Stale or missing cache — running initial scan now")
        run_scan("auto")
        global _next_scan_time
        _next_scan_time = datetime.now(timezone.utc) + timedelta(hours=interval_h)

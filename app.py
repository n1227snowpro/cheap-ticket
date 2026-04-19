import json
import logging
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context

import config
import card_generator
import db
import scheduler
import scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / "Library" / "Application Support" / "CheapTicket"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/flights")
def api_flights():
    rows = db.get_all_cached()
    status = scheduler.get_status()
    return jsonify({
        "scanning": status["scanning"],
        "last_updated": status["last_updated"],
        "next_refresh": status["next_refresh"],
        "results": rows,
    })


@app.route("/api/status")
def api_status():
    return jsonify(scheduler.get_status())


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    iata = request.args.get("iata", "").upper() or None

    if iata:
        ok = scheduler.run_scan_dest(iata)
        if not ok:
            return jsonify({"error": f"Unknown destination: {iata}"}), 400
        return jsonify({"message": f"Refresh triggered for {iata}"})
    else:
        if scheduler.get_status()["scanning"]:
            return jsonify({"message": "Scan already in progress"}), 200
        scheduler.run_scan("manual")
        return jsonify({"message": "Full refresh triggered"})


@app.route("/api/status/stream")
def api_status_stream():
    """Server-Sent Events endpoint for real-time scan progress."""
    q = scheduler.get_event_queue()

    def generate():
        # Send current status immediately
        status = scheduler.get_status()
        yield f"data: {json.dumps({'type': 'status', **status})}\n\n"

        # Stream events from the queue
        while True:
            try:
                event = q.get(timeout=20)
                yield f"data: {json.dumps(event)}\n\n"
                # Stop streaming once scan finishes
                if event.get("type") == "scan_done":
                    break
            except Exception:
                # Heartbeat to keep connection alive
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Query API ────────────────────────────────────────────────────────────────

def _lookup_destination(query: str):
    """Find a destination by IATA code or name (case-insensitive, partial match)."""
    q_upper = query.upper()
    q_lower = query.lower()
    # Exact IATA match
    for d in db.DESTINATIONS:
        if d["iata"] == q_upper:
            return d
    # Exact name match
    for d in db.DESTINATIONS:
        if d["destination"].lower() == q_lower:
            return d
    # Partial name match
    for d in db.DESTINATIONS:
        if q_lower in d["destination"].lower():
            return d
    return None


@app.route("/api/query", methods=["POST"])
def api_query():
    """
    Query flight price for a single destination.
    Request body: {"destination": "Cebu"}  or  {"destination": "CEB"}
    Returns cached data (refreshes live if stale).
    """
    body = request.get_json(force=True, silent=True) or {}
    raw = (body.get("destination") or body.get("iata") or "").strip()
    if not raw:
        return jsonify({"error": "destination is required"}), 400

    dest = _lookup_destination(raw)
    if not dest:
        return jsonify({
            "error": "Destination not found",
            "query": raw,
            "available": [
                {"iata": d["iata"], "destination": d["destination"], "flag": d["flag"]}
                for d in db.DESTINATIONS
            ],
        }), 404

    iata = dest["iata"]

    # If stale or never scanned, scrape now (synchronous, ~30s)
    if not db.is_cache_fresh(iata, max_age_hours=12):
        result = scraper.scrape_destination(dest)
        db.upsert_result(iata, result)

    row = db.get_one_cached(iata)
    if not row:
        return jsonify({"error": "Failed to fetch data", "iata": iata}), 500

    # Generate card image (only if price data is available)
    image_url = None
    if row.get("status") == "ok" and row.get("price"):
        try:
            card_path = card_generator.generate_card(row)
            base = request.host_url.rstrip("/")
            image_url = f"{base}/cards/{card_path.name}"
        except Exception as e:
            logger.warning(f"Card generation failed for {iata}: {e}")

    return jsonify({
        "destination": row["destination"],
        "iata": row["iata"],
        "flag": row["flag"],
        "region": row["region"],
        "price": row["price"],
        "currency": row["currency"],
        "best_date": row["best_date"],
        "booking_url": row["booking_url"],
        "status": row["status"],
        "cached_at": row["cached_at"],
        "fresh": db.is_cache_fresh(iata, max_age_hours=12),
        "image_url": image_url,
    })


# ── Card images ──────────────────────────────────────────────────────────────

@app.route("/cards/<filename>")
def serve_card(filename):
    card_path = card_generator.CARDS_DIR / filename
    if not card_path.exists() or card_path.suffix != ".png":
        return jsonify({"error": "Card not found or expired"}), 404
    return send_file(card_path, mimetype="image/png")


# ── Settings ─────────────────────────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    cfg = config.load()
    keys = config.get_api_keys()
    return jsonify({
        "api_keys_count": len(keys),
        "api_keys_masked": [f"...{k[-6:]}" for k in keys],
        "refresh_interval_hours": cfg.get("refresh_interval_hours", 24),
        "search_days_ahead": cfg.get("search_days_ahead", 28),
        "monthly_calls_estimate": 15 * 30,
        "monthly_free_limit": len(keys) * 250,
    })


@app.route("/api/settings/add-key", methods=["POST"])
def api_add_key():
    body = request.get_json(silent=True) or {}
    key = (body.get("key") or "").strip()
    if not key:
        return jsonify({"error": "key is required"}), 400
    config.add_api_key(key)
    return jsonify({"message": f"Key …{key[-6:]} added", "total_keys": len(config.get_api_keys())})


# ── Startup ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    scheduler.start(app)
    logger.info("CheapTicket starting on http://localhost:9002")
    app.run(host="0.0.0.0", debug=False, port=9002, threaded=True)

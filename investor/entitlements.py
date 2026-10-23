"""
Plans, limits and who the current visitor is.

Limits are enforced in the JSON API (app.py), so hiding something in the UI
is never the only protection.
"""

import secrets
import time
from functools import wraps

from flask import g, jsonify, redirect, request, session, url_for

import config
import db

PLAN_ORDER = ["free", "pro", "premium"]

PLANS = {
    "free": {
        "name": "Free", "price_month": 0, "price_year": 0,
        "today_per_section": 3, "stock_views_per_day": 3,
        "presets": {"buffett", "dividend"}, "screener_rows": 10, "filters": False,
        "feed_items": 10, "watchlist": 5,
        "insider_social": False, "ai": False, "alerts": False, "csv": False,
    },
    "pro": {
        "name": "Pro", "price_month": 12, "price_year": 120,
        "today_per_section": None, "stock_views_per_day": None,
        "presets": None, "screener_rows": None, "filters": True,
        "feed_items": None, "watchlist": 50,
        "insider_social": True, "ai": False, "alerts": False, "csv": False,
    },
    "premium": {
        "name": "Premium", "price_month": 29, "price_year": 290,
        "today_per_section": None, "stock_views_per_day": None,
        "presets": None, "screener_rows": None, "filters": True,
        "feed_items": None, "watchlist": 200,
        "insider_social": True, "ai": True, "alerts": True, "csv": True,
    },
}

PAID_STATUSES = {"active", "trialing"}
GRACE_SECONDS = 3 * 86400   # keep access briefly if a renewal webhook is late


def effective_plan(user) -> str:
    if not user:
        return "free"
    if user.get("plan") in ("pro", "premium") and user.get("plan_status") in PAID_STATUSES:
        end = user.get("current_period_end")
        if not end or end + GRACE_SECONDS > time.time():
            return user["plan"]
    return "free"


def current_user():
    if "user" not in g:
        uid = session.get("uid")
        u = db.get_user(user_id=uid) if uid else None
        # Invalidate sessions created before a password change / account deletion.
        if u and session.get("pwv") != _pw_version(u):
            u = None
            session.clear()
        g.user = u
    return g.user


def _pw_version(user) -> str:
    return (user.get("password_hash") or "")[-12:]


def login_user(user):
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    session["pwv"] = _pw_version(user)
    g.pop("user", None)
    db.update_user(user["id"], last_login_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def logout_user():
    session.clear()
    g.pop("user", None)


def plan() -> str:
    return effective_plan(current_user())


def limits() -> dict:
    return PLANS[plan()]


def is_admin(user=None) -> bool:
    user = user or current_user()
    return bool(user and user.get("email_verified") and user["email"].lower() in config.admin_emails())


def subject() -> str:
    """Metering key: the user, or an anonymous id kept in the session cookie."""
    u = current_user()
    if u:
        return f"u:{u['id']}"
    if "anon" not in session:
        session["anon"] = secrets.token_urlsafe(12)
    return f"a:{session['anon']}"


def at_least(p: str) -> bool:
    return PLAN_ORDER.index(plan()) >= PLAN_ORDER.index(p)


def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify({"error": "login required"}), 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*a, **kw)
    return wrapper


def require_plan(p: str):
    def deco(view):
        @wraps(view)
        def wrapper(*a, **kw):
            if not at_least(p):
                return jsonify({"error": "upgrade required", "required_plan": p, "locked": True}), 402
            return view(*a, **kw)
        return wrapper
    return deco


def viewer_info() -> dict:
    """What the front-end needs to render nav, badges and locks."""
    u = current_user()
    p = plan()
    lim = PLANS[p]
    return {
        "logged_in": bool(u),
        "email": u["email"] if u else None,
        "verified": bool(u and u["email_verified"]),
        "plan": p,
        "plan_name": lim["name"],
        "admin": is_admin(u),
        "limits": {k: (sorted(v) if isinstance(v, set) else v) for k, v in lim.items()
                   if k not in ("name", "price_month", "price_year")},
    }

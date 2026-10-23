"""Sign-up, login, e-mail verification, password reset, Google sign-in, account page."""

import hashlib
import logging
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlencode, urlparse

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import config
import db
import mailer
from entitlements import current_user, login_required, login_user, logout_user
from providers import http

logger = logging.getLogger(__name__)
bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8

# ── Brute-force protection: max 10 failed attempts per IP / e-mail per 15 min ──
_fails = defaultdict(deque)
_fails_lock = threading.Lock()
WINDOW, MAX_FAILS = 15 * 60, 10


def _too_many(*keys) -> bool:
    now = time.time()
    with _fails_lock:
        for k in keys:
            q = _fails[k]
            while q and q[0] < now - WINDOW:
                q.popleft()
            if len(q) >= MAX_FAILS:
                return True
    return False


def _fail(*keys):
    with _fails_lock:
        for k in keys:
            _fails[k].append(time.time())


def _client_ip() -> str:
    return request.remote_addr or "?"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _safe_next(target: str) -> str:
    """Only allow same-site relative redirects."""
    if target and target.startswith("/") and not target.startswith("//") and not urlparse(target).netloc:
        return target
    return url_for("page_today")


def _base_url() -> str:
    return (config.get("base_url") or request.host_url).rstrip("/")


def send_verification(user):
    token = secrets.token_urlsafe(32)
    db.put_token(_hash(token), user["id"], "verify", ttl_hours=48)
    link = f"{_base_url()}{url_for('auth.verify', token=token)}"
    mailer.send(user["email"], "Confirm your StockRadar e-mail",
                f"Welcome to StockRadar!\n\nConfirm your e-mail address:\n{link}\n\n"
                "This link expires in 48 hours. If you didn't sign up, ignore this message.")


# ── Sign up / login ─────────────────────────────────────────────────────────

@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user():
        return redirect(url_for("page_today"))
    nxt = request.values.get("next", "")
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        if not EMAIL_RE.match(email):
            flash("Please enter a valid e-mail address.", "error")
        elif len(pw) < MIN_PASSWORD:
            flash(f"Password must be at least {MIN_PASSWORD} characters.", "error")
        elif not request.form.get("agree"):
            flash("Please accept the Terms to continue.", "error")
        elif _too_many(f"ip:{_client_ip()}"):
            flash("Too many attempts. Please wait a few minutes.", "error")
        elif db.get_user(email=email):
            _fail(f"ip:{_client_ip()}")
            flash("An account with this e-mail already exists. Try logging in.", "error")
        else:
            uid = db.create_user(email, generate_password_hash(pw))
            user = db.get_user(user_id=uid)
            send_verification(user)
            login_user(user)
            flash("Account created! Check your inbox to confirm your e-mail.", "ok")
            return redirect(_safe_next(nxt) if nxt else url_for("billing.pricing"))
    return render_template("auth/signup.html", page="signup", next=nxt,
                           google=bool(config.get("google_client_id")))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("page_today"))
    nxt = request.values.get("next", "")
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        keys = (f"ip:{_client_ip()}", f"email:{email}")
        if _too_many(*keys):
            flash("Too many failed attempts. Please wait 15 minutes.", "error")
        else:
            user = db.get_user(email=email)
            if user and user["password_hash"] and check_password_hash(user["password_hash"], pw):
                login_user(user)
                return redirect(_safe_next(nxt))
            _fail(*keys)
            flash("Wrong e-mail or password.", "error")
    return render_template("auth/login.html", page="login", next=nxt,
                           google=bool(config.get("google_client_id")))


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("page_today"))


@bp.route("/verify/<token>")
def verify(token):
    uid = db.take_token(_hash(token), "verify")
    if not uid:
        flash("That confirmation link is invalid or has expired.", "error")
    else:
        db.update_user(uid, email_verified=1)
        flash("E-mail confirmed. Thanks!", "ok")
    return redirect(url_for("auth.account") if current_user() else url_for("auth.login"))


@bp.route("/verify/resend", methods=["POST"])
@login_required
def resend_verification():
    u = current_user()
    if not u["email_verified"]:
        send_verification(u)
        flash("Confirmation e-mail sent.", "ok")
    return redirect(url_for("auth.account"))


# ── Password reset ──────────────────────────────────────────────────────────

@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if not _too_many(f"reset:{_client_ip()}"):
            _fail(f"reset:{_client_ip()}")       # counts requests, not failures
            user = db.get_user(email=email)
            if user:
                token = secrets.token_urlsafe(32)
                db.put_token(_hash(token), user["id"], "reset", ttl_hours=1)
                link = f"{_base_url()}{url_for('auth.reset', token=token)}"
                mailer.send(email, "Reset your StockRadar password",
                            f"Reset your password here (valid for 1 hour):\n{link}\n\n"
                            "If you didn't ask for this, you can ignore this e-mail.")
        # Same answer either way so the form can't be used to discover accounts.
        flash("If that e-mail has an account, a reset link is on its way.", "ok")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", page="forgot")


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    if request.method == "POST":
        pw = request.form.get("password") or ""
        if len(pw) < MIN_PASSWORD:
            flash(f"Password must be at least {MIN_PASSWORD} characters.", "error")
            return render_template("auth/reset.html", page="reset", token=token)
        uid = db.take_token(_hash(token), "reset")
        if not uid:
            flash("That reset link is invalid or has expired.", "error")
            return redirect(url_for("auth.forgot"))
        # Following the e-mailed link proves ownership of the address.
        db.update_user(uid, password_hash=generate_password_hash(pw), email_verified=1)
        login_user(db.get_user(user_id=uid))
        flash("Password updated.", "ok")
        return redirect(url_for("page_today"))
    return render_template("auth/reset.html", page="reset", token=token)


# ── Google sign-in (OAuth 2.0 authorization-code flow) ──────────────────────

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


def _google_redirect_uri() -> str:
    return f"{_base_url()}{url_for('auth.google_callback')}"


@bp.route("/auth/google")
def google_start():
    if not config.get("google_client_id"):
        abort(404)
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    session["oauth_next"] = request.args.get("next", "")
    return redirect(GOOGLE_AUTH + "?" + urlencode({
        "client_id": config.get("google_client_id"),
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }))


@bp.route("/auth/google/callback")
def google_callback():
    state = session.pop("oauth_state", None)
    if not state or request.args.get("state") != state or not request.args.get("code"):
        flash("Google sign-in failed. Please try again.", "error")
        return redirect(url_for("auth.login"))
    try:
        tok = http.post(GOOGLE_TOKEN, data={
            "code": request.args["code"],
            "client_id": config.get("google_client_id"),
            "client_secret": config.get("google_client_secret"),
            "redirect_uri": _google_redirect_uri(),
            "grant_type": "authorization_code",
        })
        info = http.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {tok['access_token']}"}, retries=1)
    except Exception as e:
        logger.warning(f"Google OAuth error: {e}")
        flash("Google sign-in failed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    sub, email = info.get("sub"), (info.get("email") or "").lower()
    if not sub or not email or not info.get("email_verified"):
        flash("Your Google account has no verified e-mail address.", "error")
        return redirect(url_for("auth.login"))

    me = current_user()
    user = db.get_user(google_sub=sub)
    if me:                                   # "Connect Google" from the account page
        if user and user["id"] != me["id"]:
            flash("That Google account is linked to another StockRadar account.", "error")
        else:
            db.update_user(me["id"], google_sub=sub)
            flash("Google account connected.", "ok")
        return redirect(url_for("auth.account"))
    if not user:
        user = db.get_user(email=email)
        if user:                             # same verified e-mail → link accounts
            db.update_user(user["id"], google_sub=sub, email_verified=1)
        else:
            user = db.get_user(user_id=db.create_user(email, google_sub=sub, verified=True))
    login_user(db.get_user(user_id=user["id"]))
    return redirect(_safe_next(session.pop("oauth_next", "")))


# ── Account ─────────────────────────────────────────────────────────────────

@bp.route("/account")
@login_required
def account():
    return render_template("auth/account.html", page="account", user=current_user(),
                           google=bool(config.get("google_client_id")))


@bp.route("/account/password", methods=["POST"])
@login_required
def change_password():
    u = current_user()
    cur, new = request.form.get("current") or "", request.form.get("password") or ""
    if u["password_hash"] and not check_password_hash(u["password_hash"], cur):
        flash("Current password is wrong.", "error")
    elif len(new) < MIN_PASSWORD:
        flash(f"New password must be at least {MIN_PASSWORD} characters.", "error")
    else:
        db.update_user(u["id"], password_hash=generate_password_hash(new))
        login_user(db.get_user(user_id=u["id"]))   # signs out other sessions, keeps this one
        flash("Password updated.", "ok")
    return redirect(url_for("auth.account"))


@bp.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    import billing
    u = current_user()
    if (request.form.get("confirm") or "").strip().lower() != u["email"]:
        flash("Type your e-mail address to confirm deletion.", "error")
        return redirect(url_for("auth.account"))
    billing.cancel_subscription_now(u)
    db.delete_user(u["id"])
    logout_user()
    flash("Your account has been deleted.", "ok")
    return redirect(url_for("page_today"))

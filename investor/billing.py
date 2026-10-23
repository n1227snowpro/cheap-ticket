"""Stripe subscriptions: pricing page, Checkout, Customer Portal, webhooks."""

import json
import logging

import stripe
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import config
import db
from entitlements import PLANS, current_user, effective_plan, login_required

logger = logging.getLogger(__name__)
bp = Blueprint("billing", __name__)

INTERVALS = ("month", "year")


def enabled() -> bool:
    return bool(config.get("stripe_secret_key"))


def _stripe():
    stripe.api_key = config.get("stripe_secret_key")
    return stripe


def price_id(plan: str, interval: str) -> str:
    return config.get(f"stripe_price_{plan}_{interval}") or ""


def plan_for_price(pid: str):
    """Stripe price id → (plan, interval)."""
    for p in ("pro", "premium"):
        for i in INTERVALS:
            if pid and pid == price_id(p, i):
                return p, i
    return None, None


def _base_url() -> str:
    return (config.get("base_url") or request.host_url).rstrip("/")


# ── Pages ───────────────────────────────────────────────────────────────────

@bp.route("/pricing")
def pricing():
    u = current_user()
    return render_template("pricing.html", page="pricing", plans=PLANS, user=u,
                           current=effective_plan(u), billing_enabled=enabled(),
                           trial_days=int(config.get("trial_days") or 0))


@bp.route("/billing/checkout", methods=["POST"])
@login_required
def checkout():
    u = current_user()
    plan, interval = request.form.get("plan"), request.form.get("interval", "month")
    if plan not in ("pro", "premium") or interval not in INTERVALS or not price_id(plan, interval):
        flash("That plan isn't available right now.", "error")
        return redirect(url_for("billing.pricing"))
    if not enabled():
        flash("Payments aren't configured yet.", "error")
        return redirect(url_for("billing.pricing"))
    if effective_plan(u) != "free" and u.get("stripe_subscription_id"):
        # Existing subscribers change plans in the portal (handles proration).
        return portal()
    s = _stripe()
    params = {
        "mode": "subscription",
        "line_items": [{"price": price_id(plan, interval), "quantity": 1}],
        "client_reference_id": str(u["id"]),
        "success_url": f"{_base_url()}{url_for('auth.account')}?checkout=success",
        "cancel_url": f"{_base_url()}{url_for('billing.pricing')}?checkout=cancelled",
        "allow_promotion_codes": True,
        "subscription_data": {"metadata": {"user_id": str(u["id"])}},
    }
    trial = int(config.get("trial_days") or 0)
    if plan == "pro" and trial and not u.get("stripe_subscription_id"):   # one trial per account
        params["subscription_data"]["trial_period_days"] = trial
    if u.get("stripe_customer_id"):
        params["customer"] = u["stripe_customer_id"]
    else:
        params["customer_email"] = u["email"]
    session = s.checkout.Session.create(**params)
    return redirect(session.url, code=303)


@bp.route("/billing/portal", methods=["POST"])
@login_required
def portal():
    u = current_user()
    if not enabled() or not u.get("stripe_customer_id"):
        flash("No billing account yet — pick a plan first.", "error")
        return redirect(url_for("billing.pricing"))
    session = _stripe().billing_portal.Session.create(
        customer=u["stripe_customer_id"], return_url=f"{_base_url()}{url_for('auth.account')}")
    return redirect(session.url, code=303)


def cancel_subscription_now(user):
    """Used when an account is deleted."""
    if enabled() and user.get("stripe_subscription_id"):
        try:
            _stripe().Subscription.cancel(user["stripe_subscription_id"])
        except Exception as e:
            logger.error(f"Cancel subscription {user['stripe_subscription_id']} failed: {e}")


# ── Webhook ─────────────────────────────────────────────────────────────────

def _period_end(sub: dict):
    # Newer Stripe API versions moved current_period_end onto subscription items.
    if sub.get("current_period_end"):
        return sub["current_period_end"]
    items = (sub.get("items") or {}).get("data") or []
    ends = [i.get("current_period_end") for i in items if i.get("current_period_end")]
    return max(ends) if ends else None


def apply_subscription(sub: dict, user_id=None):
    """Mirror a Stripe subscription object onto our user row."""
    customer = sub.get("customer")
    user = db.get_user(stripe_customer_id=customer) if customer else None
    if not user:
        uid = user_id or (sub.get("metadata") or {}).get("user_id")
        user = db.get_user(user_id=int(uid)) if uid else None
    if not user:
        logger.warning(f"Subscription {sub.get('id')} for unknown customer {customer}")
        return
    items = (sub.get("items") or {}).get("data") or []
    pid = ((items[0].get("price") or {}).get("id")) if items else None
    plan, interval = plan_for_price(pid)
    status = sub.get("status")
    if status in ("canceled", "incomplete_expired") or not plan:
        if not plan and status not in ("canceled", "incomplete_expired"):
            logger.warning(f"Unknown Stripe price {pid} on subscription {sub.get('id')}")
        db.update_user(user["id"], plan="free", plan_status=status, stripe_customer_id=customer,
                       stripe_subscription_id=sub.get("id"), cancel_at_period_end=0)
        return
    db.update_user(user["id"], plan=plan, plan_interval=interval, plan_status=status,
                   current_period_end=_period_end(sub),
                   cancel_at_period_end=int(bool(sub.get("cancel_at_period_end"))),
                   stripe_customer_id=customer, stripe_subscription_id=sub.get("id"))


def _fetch_subscription(sub_id: str) -> dict:
    sub = _stripe().Subscription.retrieve(sub_id)
    return sub.to_dict() if hasattr(sub, "to_dict") else dict(sub)


@bp.route("/billing/webhook", methods=["POST"])
def webhook():
    payload = request.get_data()
    secret = config.get("stripe_webhook_secret")
    if not secret:
        return jsonify({"error": "webhook not configured"}), 503
    try:
        stripe.WebhookSignature.verify_header(payload.decode(), request.headers.get("Stripe-Signature", ""), secret)
    except Exception:
        return jsonify({"error": "bad signature"}), 400
    event = json.loads(payload)
    if db.stripe_event_seen(event["id"]):
        return jsonify({"ok": True, "duplicate": True})

    obj = event["data"]["object"]
    etype = event["type"]
    try:
        if etype == "checkout.session.completed" and obj.get("mode") == "subscription":
            uid = obj.get("client_reference_id")
            if uid and db.get_user(user_id=int(uid)):
                db.update_user(int(uid), stripe_customer_id=obj.get("customer"))
            if obj.get("subscription") and enabled():
                apply_subscription(_fetch_subscription(obj["subscription"]), uid)
        elif etype in ("customer.subscription.created", "customer.subscription.updated",
                       "customer.subscription.deleted", "customer.subscription.paused",
                       "customer.subscription.resumed"):
            # Events can arrive out of order; re-read the live state when we can.
            apply_subscription(_fetch_subscription(obj["id"]) if enabled() else obj)
        elif etype == "invoice.payment_failed":
            user = db.get_user(stripe_customer_id=obj.get("customer"))
            if user:
                import mailer
                mailer.send(user["email"], "StockRadar: payment failed",
                            "We couldn't charge your card for StockRadar. Please update your payment method:\n"
                            f"{_base_url()}{url_for('auth.account')}")
    except Exception as e:
        logger.error(f"Webhook {etype} failed: {e}", exc_info=True)
        return jsonify({"error": "processing failed"}), 500   # Stripe will retry
    db.mark_stripe_event(event["id"], etype)
    return jsonify({"ok": True})

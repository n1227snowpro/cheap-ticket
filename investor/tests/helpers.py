import hashlib
import hmac
import json
import time
import uuid

import db


def make_user(plan="free", status=None, verified=True, email=None, password_hash="x" * 20):
    email = email or f"{uuid.uuid4().hex[:10]}@example.com"
    uid = db.create_user(email, password_hash=password_hash, verified=verified)
    if plan != "free":
        db.update_user(uid, plan=plan, plan_status=status or "active", plan_interval="month",
                       current_period_end=int(time.time()) + 30 * 86400)
    return db.get_user(user_id=uid)


def login_as(client, user):
    with client.session_transaction() as s:
        s["uid"] = user["id"]
        s["pwv"] = (user.get("password_hash") or "")[-12:]
        s["csrf"] = "test-csrf"


def csrf(client) -> str:
    return client.get("/api/me").get_json()["csrf"]


def stripe_signature(payload: str, secret: str) -> str:
    t = int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


def subscription_event(event_id, etype, customer, price, status="active", user_id=None, sub_id="sub_1",
                       period_end=None, cancel=False):
    obj = {"id": sub_id, "object": "subscription", "customer": customer, "status": status,
           "cancel_at_period_end": cancel, "metadata": {"user_id": str(user_id)} if user_id else {},
           "items": {"data": [{"price": {"id": price},
                               "current_period_end": period_end or int(time.time()) + 30 * 86400}]}}
    return json.dumps({"id": event_id, "type": etype, "data": {"object": obj}})

import re

import pytest

import db
import mailer
from helpers import csrf, login_as, make_user, stripe_signature, subscription_event


@pytest.fixture()
def client():
    import app as app_module
    return app_module.app.test_client()


# ── Auth ────────────────────────────────────────────────────────────────────

def test_post_without_csrf_is_rejected(client):
    r = client.post("/signup", data={"email": "a@b.co", "password": "longpassword", "agree": "1"})
    assert r.status_code == 400


def test_signup_verify_login_logout(client):
    token = csrf(client)
    r = client.post("/signup", data={"csrf_token": token, "email": "New@Example.com",
                                     "password": "s3cret-pass", "agree": "1"})
    assert r.status_code == 302
    user = db.get_user(email="new@example.com")
    assert user and not user["email_verified"] and user["password_hash"] != "s3cret-pass"
    me = client.get("/api/me").get_json()
    assert me["logged_in"] and me["plan"] == "free"

    link = re.search(r"/verify/\S+", mailer.outbox[-1]["text"]).group(0)
    client.get(link)
    assert db.get_user(email="new@example.com")["email_verified"] == 1
    assert client.get(link).status_code == 302          # single-use: second click is a no-op
    client.post("/logout", data={"csrf_token": csrf(client)})
    assert client.get("/api/me").get_json()["logged_in"] is False

    r = client.post("/login", data={"csrf_token": csrf(client), "email": "new@example.com", "password": "wrong-pass"})
    assert b"Wrong e-mail or password" in r.data
    client.post("/login", data={"csrf_token": csrf(client), "email": "new@example.com", "password": "s3cret-pass"})
    assert client.get("/api/me").get_json()["logged_in"] is True


def test_duplicate_signup_and_open_redirect(client):
    make_user(email="dupe@example.com")
    r = client.post("/signup", data={"csrf_token": csrf(client), "email": "dupe@example.com",
                                     "password": "password123", "agree": "1"})
    assert b"already exists" in r.data
    r = client.post("/signup", data={"csrf_token": csrf(client), "email": "safe@example.com",
                                     "password": "password123", "agree": "1", "next": "//evil.com"})
    assert r.headers["Location"] in ("/", "http://localhost/")


def test_password_reset(client):
    from werkzeug.security import generate_password_hash
    make_user(email="forgot@example.com", password_hash=generate_password_hash("old-password"))
    client.post("/forgot", data={"csrf_token": csrf(client), "email": "forgot@example.com"})
    link = re.search(r"/reset/\S+", mailer.outbox[-1]["text"]).group(0)
    client.post(link, data={"csrf_token": csrf(client), "password": "brand-new-pass"})
    client.post("/logout", data={"csrf_token": csrf(client)})
    client.post("/login", data={"csrf_token": csrf(client), "email": "forgot@example.com", "password": "brand-new-pass"})
    assert client.get("/api/me").get_json()["logged_in"]
    # unknown e-mail gets the same response and sends nothing
    n = len(mailer.outbox)
    r = client.post("/forgot", data={"csrf_token": csrf(client), "email": "nobody@example.com"})
    assert r.status_code == 302 and len(mailer.outbox) == n


def test_google_callback_creates_and_links(client, monkeypatch):
    from providers import http
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsecret")
    existing = make_user(email="gfan@example.com", verified=False)
    monkeypatch.setattr(http, "post", lambda *a, **k: {"access_token": "tok"})
    monkeypatch.setattr(http, "get", lambda *a, **k: {"sub": "g-123", "email": "GFan@example.com", "email_verified": True})
    r = client.get("/auth/google")
    state = re.search(r"state=([^&]+)", r.headers["Location"]).group(1)
    assert client.get("/auth/google/callback?state=bad&code=x").status_code == 302
    assert client.get("/api/me").get_json()["logged_in"] is False
    client.get("/auth/google")
    with client.session_transaction() as s:
        state = s["oauth_state"]
    client.get(f"/auth/google/callback?state={state}&code=abc")
    u = db.get_user(google_sub="g-123")
    assert u["id"] == existing["id"] and u["email_verified"] == 1
    assert client.get("/api/me").get_json()["email"] == "gfan@example.com"


# ── Entitlements ────────────────────────────────────────────────────────────

def test_free_stock_view_meter(client):
    tickers = ["NOVA", "BYTE", "CARE", "PETRO"]
    for t in tickers[:3]:
        assert client.get(f"/api/stock/{t}").status_code == 200
    r = client.get("/api/stock/PETRO")
    assert r.status_code == 402 and r.get_json()["required_plan"] == "pro"
    assert client.get("/api/stock/NOVA").status_code == 200        # already viewed today
    login_as(client, make_user("pro"))
    assert client.get("/api/stock/PETRO").status_code == 200


def test_plan_gating_of_fields(client):
    d = client.get("/api/stock/BYTE").get_json()
    assert d["insider"] == [] and "insider_social" in d["locked"]
    assert all(n["summary"] is None for n in d["news"])

    login_as(client, make_user("pro"))
    d = client.get("/api/stock/BYTE").get_json()
    assert d["insider"] and "insider_social" not in d["locked"] and "ai_summaries" in d["locked"]
    assert client.get("/api/screen.csv").status_code == 402

    login_as(client, make_user("premium"))
    d = client.get("/api/stock/BYTE").get_json()
    assert not d["locked"] and any(n["summary"] for n in d["news"])
    r = client.get("/api/screen.csv?preset=dividend")
    assert r.status_code == 200 and r.data.startswith(b"ticker,name")


def test_free_screener_limits(client):
    d = client.get("/api/screen").get_json()
    assert len(d["results"]) == 10 and d["total"] > 10 and "rows" in d["locked"]
    d = client.get("/api/screen?preset=garp").get_json()
    assert d["results"] == [] and "preset" in d["locked"]
    d = client.get("/api/screen?min_quality=99").get_json()
    assert "filters" in d["locked"] and d["total"] > 0             # filter ignored, not applied
    today = client.get("/api/today").get_json()
    assert len(today["top_value"]) == 3 and today["digest"] is None and "digest" in today["locked"]


def test_expired_or_past_due_falls_back_to_free(client):
    import time
    u = make_user("premium", status="past_due")
    login_as(client, u)
    assert client.get("/api/me").get_json()["plan"] == "free"
    db.update_user(u["id"], plan_status="active", current_period_end=int(time.time()) - 10 * 86400)
    assert client.get("/api/me").get_json()["plan"] == "free"


def test_watchlist_sync_and_cap(client):
    assert client.get("/api/watchlist").status_code == 401
    login_as(client, make_user())
    hdr = {"X-CSRF-Token": "test-csrf"}
    r = client.post("/api/watchlist", json={"tickers": ["NOVA", "BYTE", "CARE", "PETRO", "TELX", "NOPE"]}, headers=hdr)
    assert r.get_json()["tickers"] == ["NOVA", "BYTE", "CARE", "PETRO", "TELX"]
    r = client.post("/api/watchlist", json={"ticker": "MINE"}, headers=hdr)
    assert r.status_code == 402
    r = client.delete("/api/watchlist", json={"ticker": "NOVA"}, headers=hdr)
    assert "NOVA" not in r.get_json()["tickers"]


def test_admin_only_endpoints(client):
    assert client.post("/api/refresh?job=prices", headers={"X-CSRF-Token": "x"}).status_code in (400, 401)
    login_as(client, make_user("free"))
    assert client.get("/admin").status_code == 404


def test_admin_page(client, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    login_as(client, make_user(email="boss@example.com"))
    r = client.get("/admin")
    assert r.status_code == 200 and b"Est. MRR" in r.data


# ── Stripe webhook ──────────────────────────────────────────────────────────

@pytest.fixture()
def stripe_env(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTH", "price_pro_m")
    monkeypatch.setenv("STRIPE_PRICE_PREMIUM_YEAR", "price_prem_y")


def _send(client, payload, secret="whsec_test"):
    return client.post("/billing/webhook", data=payload, content_type="application/json",
                       headers={"Stripe-Signature": stripe_signature(payload, secret)})


def test_webhook_rejects_bad_signature(client, stripe_env):
    payload = subscription_event("evt_bad", "customer.subscription.created", "cus_x", "price_pro_m")
    assert _send(client, payload, secret="wrong").status_code == 400


def test_webhook_subscription_lifecycle(client, stripe_env):
    u = make_user()
    created = subscription_event("evt_1", "customer.subscription.created", "cus_A", "price_pro_m",
                                 status="trialing", user_id=u["id"])
    assert _send(client, created).status_code == 200
    row = db.get_user(user_id=u["id"])
    assert (row["plan"], row["plan_status"], row["stripe_customer_id"]) == ("pro", "trialing", "cus_A")

    # replayed event is ignored
    assert _send(client, created).get_json().get("duplicate") is True

    upgraded = subscription_event("evt_2", "customer.subscription.updated", "cus_A", "price_prem_y")
    _send(client, upgraded)
    row = db.get_user(user_id=u["id"])
    assert (row["plan"], row["plan_interval"], row["plan_status"]) == ("premium", "year", "active")
    login_as(client, row)
    assert client.get("/api/me").get_json()["plan"] == "premium"

    deleted = subscription_event("evt_3", "customer.subscription.deleted", "cus_A", "price_prem_y", status="canceled")
    _send(client, deleted)
    assert db.get_user(user_id=u["id"])["plan"] == "free"
    assert client.get("/api/me").get_json()["plan"] == "free"


def test_checkout_creates_stripe_session(client, monkeypatch, stripe_env):
    import stripe
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    seen = {}

    class FakeSession:
        url = "https://checkout.stripe.com/c/pay/test"

    def fake_create(**params):
        seen.update(params)
        return FakeSession()

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(fake_create))
    u = make_user()
    login_as(client, u)
    r = client.post("/billing/checkout", data={"csrf_token": "test-csrf", "plan": "pro", "interval": "month"})
    assert r.status_code == 303 and r.headers["Location"] == FakeSession.url
    assert seen["line_items"] == [{"price": "price_pro_m", "quantity": 1}]
    assert seen["client_reference_id"] == str(u["id"])
    assert seen["subscription_data"]["trial_period_days"] == 7
    # unknown / unconfigured price is refused
    r = client.post("/billing/checkout", data={"csrf_token": "test-csrf", "plan": "premium", "interval": "month"})
    assert r.status_code == 302 and "/pricing" in r.headers["Location"]


def test_saas_pages_render(client):
    for path in ("/pricing", "/login", "/signup", "/forgot", "/terms", "/privacy"):
        assert client.get(path).status_code == 200, path
    assert client.get("/account").status_code == 302
    login_as(client, make_user("pro"))
    r = client.get("/account")
    assert r.status_code == 200 and b"Renews" in r.data


def test_delete_account(client):
    u = make_user(email="bye@example.com")
    login_as(client, u)
    client.post("/account/delete", data={"csrf_token": "test-csrf", "confirm": "wrong"})
    assert db.get_user(user_id=u["id"])
    client.post("/account/delete", data={"csrf_token": "test-csrf", "confirm": "bye@example.com"})
    assert db.get_user(user_id=u["id"]) is None
    assert client.get("/api/me").get_json()["logged_in"] is False

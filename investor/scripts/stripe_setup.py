"""
Create the StockRadar products and prices in Stripe and print the env lines to paste.

    STRIPE_SECRET_KEY=sk_test_... python3 scripts/stripe_setup.py

Run once with a test key, then again with the live key. Safe to re-run: it reuses
products/prices it created before (matched by lookup_key).
"""

import os
import sys

import stripe

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from entitlements import PLANS  # noqa: E402

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or sys.exit("Set STRIPE_SECRET_KEY first.")

lines = []
for plan in ("pro", "premium"):
    p = PLANS[plan]
    product = next((x for x in stripe.Product.search(query=f"metadata['stockradar_plan']:'{plan}'").data), None)
    if not product:
        product = stripe.Product.create(name=f"StockRadar {p['name']}", metadata={"stockradar_plan": plan})
    for interval, amount in (("month", p["price_month"]), ("year", p["price_year"])):
        key = f"stockradar_{plan}_{interval}"
        existing = stripe.Price.list(lookup_keys=[key], limit=1).data
        price = existing[0] if existing else stripe.Price.create(
            product=product.id, currency="usd", unit_amount=int(amount * 100),
            recurring={"interval": interval}, lookup_key=key)
        lines.append(f"STRIPE_PRICE_{plan.upper()}_{interval.upper()}={price.id}")

print("\n".join(lines))
print("\nNext: Stripe Dashboard → Developers → Webhooks → add endpoint\n"
      "  https://<your-domain>/billing/webhook\n"
      "  events: checkout.session.completed, customer.subscription.created, customer.subscription.updated,\n"
      "          customer.subscription.deleted, invoice.payment_failed\n"
      "and put its signing secret in STRIPE_WEBHOOK_SECRET.\n"
      "Also enable the Customer Portal (Settings → Billing → Customer portal) with plan switching.")

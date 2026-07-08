"""Tier-1 model-sync tests: the SDK types now surface the lifecycle / enrichment
fields the API already returns (scheduled cancel, MRR, account credit, plan
features / billing mode / family config, invoice line items)."""

import httpx

from ubilltu import UbilltuClient
from ubilltu.models import (
    AccountBalance,
    Invoice,
    Plan,
    Subscription,
    UsageMetrics,
)


def make_client(handler):
    return UbilltuClient("demo", transport=httpx.MockTransport(handler))


# ── Plan enrichment ────────────────────────────────────────────────────────

def test_plan_surfaces_features_billing_mode_and_family_config():
    p = Plan.from_json(
        {
            "plan_name": "feature-monthly",
            "product_name": "Feature",
            "prices": [{"amount": 250, "currency": "ZAR", "billing_period": "MONTHLY"}],
            "features": ["Unlimited boards", "Priority support"],
            "billingMode": "pro_rata",
            "billingDay": 1,
            "familyConfig": {"enabled": True, "includedSeats": 5},
        }
    )
    assert p.features == ["Unlimited boards", "Priority support"]
    assert p.billing_mode == "pro_rata"
    assert p.billing_day == 1
    assert p.is_pro_rata is True
    assert p.family_config == {"enabled": True, "includedSeats": 5}
    assert p.is_family is True


def test_plan_defaults_when_unenriched():
    p = Plan.from_json({"plan_name": "basic-monthly", "price": 99})
    assert p.features == []
    assert p.billing_mode is None
    assert p.family_config is None
    assert p.is_family is False
    assert p.is_pro_rata is False


# ── Subscription lifecycle + helpers ───────────────────────────────────────

def test_subscription_surfaces_scheduled_cancel_and_mrr():
    s = Subscription.from_json(
        {
            "subscription": {
                "subscription_id": "s1",
                "state": "ACTIVE",
                "cancelled_date": "2026-09-01",
                "charged_through_date": "2026-09-01",
                "billing_end_date": "2026-09-01",
                "mrr_monthly": 250.0,
                "last_payment_amount": 250.0,
            },
            "events": [{"eventType": "STOP_ENTITLEMENT"}],
        }
    )
    assert s.cancelled_date == "2026-09-01"
    assert s.charged_through_date == "2026-09-01"
    assert s.mrr_monthly == 250.0
    assert s.last_payment_amount == 250.0
    assert len(s.events) == 1
    # Scheduled end-of-term cancel: still ACTIVE + cancelled_date set.
    assert s.is_cancellation_scheduled is True
    assert s.is_paused is False


def test_subscription_active_without_cancel_is_not_cancelling():
    s = Subscription.from_json({"subscription_id": "s2", "state": "ACTIVE"})
    assert s.is_cancellation_scheduled is False
    assert s.is_paused is False


def test_subscription_blocked_is_paused():
    s = Subscription.from_json({"subscription_id": "s3", "state": "BLOCKED"})
    assert s.is_paused is True
    assert s.is_cancellation_scheduled is False


# ── Invoice line items + empty detection ───────────────────────────────────

def test_invoice_surfaces_items_balance_and_empty_flag():
    inv = Invoice.from_json(
        {
            "invoice_id": "i1",
            "invoice_number": "1001",
            "amount": 250,
            "balance": 0,
            "credit_adj": -50,
            "items": [
                {"plan_name": "feature-monthly", "phase": "EVERGREEN", "amount": 250},
            ],
        }
    )
    assert inv.invoice_number == "1001"
    assert inv.balance == 0
    assert inv.credit_adj == -50
    assert len(inv.items) == 1
    assert inv.items[0].plan_name == "feature-monthly"
    assert inv.items[0].amount == 250
    assert inv.is_empty is False


def test_invoice_zero_total_zero_item_is_empty():
    inv = Invoice.from_json({"invoice_id": "i2", "amount": 0, "items": []})
    assert inv.is_empty is True


# ── Typed account balance + usage via the client ───────────────────────────

def test_balance_returns_typed_account_balance():
    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path == "/api/v1/account/balance":
            return httpx.Response(200, json={"balance": 0, "credit": 151.0, "currency": "ZAR"})
        return httpx.Response(404, json={})

    client = make_client(handler)
    client.login("a@b.com", "pw")
    bal = client.balance()
    assert isinstance(bal, AccountBalance)
    assert bal.balance == 0
    assert bal.credit == 151.0
    assert bal.currency == "ZAR"


def test_usage_returns_typed_metrics():
    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path == "/api/v1/account/usage":
            return httpx.Response(
                200,
                json={
                    "total_subscriptions": 3,
                    "active_subscriptions": 1,
                    "total_invoices": 5,
                    "unpaid_invoices": 1,
                    "total_spent": 999.0,
                    "currency": "ZAR",
                },
            )
        return httpx.Response(404, json={})

    client = make_client(handler)
    client.login("a@b.com", "pw")
    u = client.usage()
    assert isinstance(u, UsageMetrics)
    assert u.total_subscriptions == 3
    assert u.active_subscriptions == 1
    assert u.total_spent == 999.0

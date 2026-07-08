"""Tier-2 remainder: payment-method management, one-off, payment status,
self-resume check, invoice HTML, GDPR erase."""

import httpx

from ubilltu import Payment, PaymentMethod, UbilltuClient


def _logged_in(handler):
    def wrapped(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)

    c = UbilltuClient("demo", transport=httpx.MockTransport(wrapped))
    c.login("a@b.com", "pw")
    return c


def test_add_payment_method_posts_token():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = request.read().decode()
        return httpx.Response(201, json={"payment_method_id": "pm1", "is_default": True})

    pm = _logged_in(handler).add_payment_method("tok_abc", is_default=True)
    assert isinstance(pm, PaymentMethod)
    assert pm.id == "pm1"
    assert seen["path"] == "/api/v1/payments/methods"
    assert "tok_abc" in seen["body"]


def test_delete_and_set_default_payment_method():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"success": True, "message": "ok"})

    c = _logged_in(handler)
    c.delete_payment_method("pm1")
    c.set_default_payment_method("pm2")
    c.reconcile_default_payment_method()
    assert ("DELETE", "/api/v1/payments/methods/pm1") in calls
    assert ("PUT", "/api/v1/payments/methods/pm2/default") in calls
    assert ("POST", "/api/v1/payments/methods/reconcile-default") in calls


def test_get_payment_returns_typed_status():
    def handler(request):
        assert request.url.path == "/api/v1/payments/pay1"
        return httpx.Response(
            200, json={"payment_id": "pay1", "status": "SUCCEEDED", "amount": 250, "currency": "ZAR"}
        )

    p = _logged_in(handler).get_payment("pay1")
    assert isinstance(p, Payment)
    assert p.id == "pay1"
    assert p.status == "SUCCEEDED"


def test_create_one_off_payment_posts_source_and_settlement():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = request.read().decode()
        return httpx.Response(
            200, json={"status": "PENDING", "requires_redirect": True, "redirect_url": "https://pay", "payment_id": "p1"}
        )

    r = _logged_in(handler).create_one_off_payment(
        source={"type": "ad_hoc", "amount": 50, "currency": "ZAR", "description": "Top-up"},
        settlement={"mode": "hosted", "return_url": "https://store/done"},
    )
    assert r["requires_redirect"] is True
    assert seen["path"] == "/api/v1/payments/one-off"
    assert '"ad_hoc"' in seen["body"] and '"hosted"' in seen["body"]


def test_self_resume_allowed_returns_bool():
    def handler(request):
        assert request.url.path == "/api/v1/subscriptions/s1/self-resume-allowed"
        return httpx.Response(200, json={"subscription_id": "s1", "allowed": True})

    assert _logged_in(handler).self_resume_allowed("s1") is True


def test_invoice_html_returns_string():
    def handler(request):
        assert request.url.path == "/api/v1/invoices/i1/html"
        return httpx.Response(200, text="<html><body>Invoice</body></html>")

    html = _logged_in(handler).invoice_html("i1")
    assert html.startswith("<html>")


def test_erase_account_posts_confirmation():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"erasure_id": "er1", "erased_fields": ["email", "name"]})

    r = _logged_in(handler).erase_account("a@b.com")
    assert r["erasure_id"] == "er1"
    assert seen["path"] == "/api/v1/account/erase"
    assert "ERASE" in seen["body"]

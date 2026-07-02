import httpx
import pytest

from ubilltu import UbilltuApiError, UbilltuAuthError, UbilltuClient


def make_client(handler):
    return UbilltuClient("demo", transport=httpx.MockTransport(handler))


def test_login_stores_token_and_attaches_headers():
    seen = {}

    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "tok_123", "token_type": "bearer"})
        seen["req"] = request
        return httpx.Response(200, json={"items": [], "total": 0, "page": 1, "per_page": 20})

    client = make_client(handler)
    tokens = client.login("a@b.com", "pw")
    assert tokens.access_token == "tok_123"
    assert client.is_authenticated

    plans = client.list_plans()
    assert plans.items == []
    assert seen["req"].headers["authorization"] == "Bearer tok_123"
    assert seen["req"].headers["x-storefront-slug"] == "demo"


def test_authed_call_before_login_raises():
    client = make_client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(UbilltuAuthError):
        client.list_plans()


def test_non_2xx_maps_to_api_error():
    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(402, json={"detail": "no active subscription"})

    client = make_client(handler)
    client.login("a@b.com", "pw")
    with pytest.raises(UbilltuApiError) as exc:
        client.list_subscriptions()
    assert exc.value.status_code == 402
    assert "no active subscription" in str(exc.value)


def test_plans_page_parses_trial_days_from_trial_phase():
    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "name": "premium-monthly",
                        "price": 149,
                        "currency": "ZAR",
                        "phases": [
                            {"phase_type": "TRIAL", "duration_length": 14},
                            {"phase_type": "EVERGREEN"},
                        ],
                    }
                ],
                "total": 1,
                "page": 1,
                "per_page": 20,
            },
        )

    client = make_client(handler)
    client.login("a@b.com", "pw")
    plans = client.list_plans()
    assert plans.items[0].name == "premium-monthly"
    assert plans.items[0].price == 149
    assert plans.items[0].trial_days == 14


def test_change_plan_sends_put_with_body():
    seen = {}

    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        seen["req"] = request
        return httpx.Response(
            200, json={"subscription_id": "sub_1", "state": "ACTIVE", "plan_name": "premium-annual"}
        )

    client = make_client(handler)
    client.login("a@b.com", "pw")
    sub = client.change_plan("sub_1", "premium-annual", policy="IMMEDIATE")

    req = seen["req"]
    assert req.method == "PUT"
    assert req.url.path == "/api/v1/subscriptions/sub_1"
    import json as _json

    body = _json.loads(req.content)
    assert body["plan_id"] == "premium-annual"
    assert body["billing_policy"] == "IMMEDIATE"
    assert sub.plan_name == "premium-annual"


def test_preview_change_adds_query_param():
    seen = {}

    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        seen["req"] = request
        return httpx.Response(200, json={"amount": 50, "currency": "ZAR"})

    client = make_client(handler)
    client.login("a@b.com", "pw")
    client.preview_change("sub_1", new_plan="premium-annual")

    req = seen["req"]
    assert req.url.path == "/api/v1/subscriptions/sub_1/dry-run"
    assert req.url.params.get("new_plan") == "premium-annual"


def test_invoice_pdf_returns_bytes():
    pdf = b"%PDF-1.4 fake"

    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})

    client = make_client(handler)
    client.login("a@b.com", "pw")
    assert client.invoice_pdf("inv_1") == pdf

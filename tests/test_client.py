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
        client.list_subscriptions()  # genuinely authed (list_plans is public)


def test_non_2xx_maps_to_api_error():
    # The API nests error messages as {"error": {"message": ...}}.
    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(402, json={"error": {"message": "no active subscription"}})

    client = make_client(handler)
    client.login("a@b.com", "pw")
    with pytest.raises(UbilltuApiError) as exc:
        client.list_subscriptions()
    assert exc.value.status_code == 402
    assert "no active subscription" in str(exc.value)


def test_plans_page_parses_real_api_shape():
    # Mirrors the real /plans payload: slug in plan_name, display in
    # product_name, price/currency inside prices[].
    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "plan_id": "lite-monthly",
                        "plan_name": "lite-monthly",
                        "product_name": "Lite",
                        "billing_period": "MONTHLY",
                        "prices": [
                            {"currency": "ZAR", "amount": 50.0, "billing_period": "MONTHLY"}
                        ],
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
    plan = client.list_plans().items[0]
    assert plan.id == "lite-monthly"       # slug — what you pass to subscribe()
    assert plan.name == "Lite"             # product display name
    assert plan.price == 50.0              # pulled from prices[]
    assert plan.currency == "ZAR"          # pulled from prices[]
    assert plan.billing_period == "MONTHLY"
    assert plan.trial_days == 14


def test_register_sends_tos_accepted():
    seen = {}

    def handler(request):
        seen["req"] = request
        return httpx.Response(200, json={"access_token": "t"})

    client = make_client(handler)
    client.register("new@example.com", "password123", name="New User")
    import json as _json

    body = _json.loads(seen["req"].content)
    assert body["tos_accepted"] is True
    assert body["email"] == "new@example.com"


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


def test_get_subscription_unwraps_detail_shape():
    # The detail endpoint wraps as {"subscription": {...}, "events": [...]}.
    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(
            200,
            json={
                "subscription": {
                    "subscription_id": "sub_1",
                    "plan_name": "premium-monthly",
                    "state": "ACTIVE",
                },
                "events": [],
            },
        )

    client = make_client(handler)
    client.login("a@b.com", "pw")
    s = client.get_subscription("sub_1")
    assert s.id == "sub_1"
    assert s.plan_name == "premium-monthly"
    assert s.state == "ACTIVE"


def test_subscription_surfaces_product_name_and_price():
    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "subscription_id": "sub_1",
                        "plan_name": "lite-monthly",
                        "product_name": "Lite",
                        "state": "ACTIVE",
                        "price": 50.0,
                        "currency": "ZAR",
                    }
                ],
                "total": 1,
                "page": 1,
                "per_page": 20,
            },
        )

    client = make_client(handler)
    client.login("a@b.com", "pw")
    s = client.list_subscriptions().items[0]
    assert s.product_name == "Lite"      # display name (plan_name is the slug)
    assert s.price == 50.0
    assert s.currency == "ZAR"


def test_signup_and_setup_payment_method():
    seen = {}

    def handler(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        seen[request.url.path] = request
        if request.url.path.endswith("/signup"):
            return httpx.Response(201, json={
                "subscription_id": "sub_1", "payment_id": "pay_1",
                "redirect_url": "https://pay.example/abc",
            })
        return httpx.Response(200, json={"redirect_url": "https://pay.example/setup"})

    client = make_client(handler)
    client.login("a@b.com", "pw")

    su = client.signup("lite-monthly", "https://app/return")
    assert su["redirect_url"] == "https://pay.example/abc"
    import json as _json
    assert _json.loads(seen["/api/v1/subscriptions/signup"].content)["plan_id"] == "lite-monthly"

    setup = client.setup_payment_method("https://app/return", is_default=True)
    assert setup["redirect_url"] == "https://pay.example/setup"
    body = _json.loads(seen["/api/v1/payments/methods/setup"].content)
    assert body["return_url"] == "https://app/return"
    assert body["is_default"] is True

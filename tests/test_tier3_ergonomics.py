"""Tier-3 ergonomics: pagination params on list methods + price-derive helper."""

import httpx

from ubilltu import Plan, Subscription, UbilltuClient, resolve_subscription_price


def _logged_in(handler):
    def wrapped(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)

    c = UbilltuClient("demo", transport=httpx.MockTransport(wrapped))
    c.login("a@b.com", "pw")
    return c


def test_list_methods_send_pagination_params():
    seen = {}

    def handler(request):
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={"items": [], "total": 0, "page": 2, "per_page": 5})

    c = _logged_in(handler)
    page = c.list_plans(page=2, per_page=5)
    assert seen["query"] == {"page": "2", "per_page": "5"}
    assert page.page == 2 and page.per_page == 5


def test_list_methods_omit_params_when_unset():
    seen = {}

    def handler(request):
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={"items": [], "total": 0})

    _logged_in(handler).list_subscriptions()
    assert seen["query"] == {}


def test_resolve_price_uses_subscription_price_when_present():
    sub = Subscription.from_json({"subscription_id": "s1", "plan_name": "feature-monthly", "price": 250})
    assert resolve_subscription_price(sub, []) == 250


def test_resolve_price_derives_from_plan_when_null():
    sub = Subscription.from_json({"subscription_id": "s1", "plan_name": "feature-monthly"})
    plans = [
        Plan.from_json({"plan_name": "basic-monthly", "price": 99}),
        Plan.from_json({"plan_name": "feature-monthly", "prices": [{"amount": 250}]}),
    ]
    assert resolve_subscription_price(sub, plans) == 250


def test_resolve_price_none_when_unresolvable():
    sub = Subscription.from_json({"subscription_id": "s1", "plan_name": "gone-plan"})
    assert resolve_subscription_price(sub, []) is None

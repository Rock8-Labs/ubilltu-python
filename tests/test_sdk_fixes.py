"""Fixes from integration testing: public plans, auto-refresh on 401,
cancel policy, and pause/resume returning PauseResult."""

import httpx

from ubilltu import PauseResult, UbilltuClient


def make_client(handler):
    return UbilltuClient("demo", transport=httpx.MockTransport(handler))


def _logged_in(handler):
    def wrapped(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "tok", "refresh_token": "r1"})
        return handler(request)

    c = make_client(wrapped)
    c.login("a@b.com", "pw")
    return c


def test_list_plans_is_public_no_login():
    def handler(request):
        assert "authorization" not in {k.lower() for k in request.headers.keys()}
        assert request.url.path == "/api/v1/plans"
        return httpx.Response(200, json={"items": [{"plan_name": "basic", "price": 99}], "total": 1})

    page = make_client(handler).list_plans()  # no login
    assert len(page.items) == 1


def test_pause_returns_pause_result():
    c = _logged_in(lambda r: httpx.Response(200, json={"success": True, "message": "ok", "paused_until": "2026-09-01"}))
    result = c.pause_subscription("s1")
    assert isinstance(result, PauseResult)
    assert result.success is True
    assert result.paused_until == "2026-09-01"


def test_cancel_default_end_of_term_and_policy():
    seen = {}

    def handler(request):
        seen["body"] = request.read().decode() if request.content else None
        return httpx.Response(200, json={"success": True})

    c = _logged_in(handler)
    c.cancel_subscription("s1")
    assert "END_OF_TERM" in (seen["body"] or "")
    c.cancel_subscription("s2", policy="IMMEDIATE")
    assert "IMMEDIATE" in (seen["body"] or "")
    c.cancel_subscription("s3", policy=None)
    assert seen["body"] is None  # no body -> server default


def test_auto_refresh_on_401():
    calls = {"account": 0}

    def handler(request):
        p = request.url.path
        if p == "/api/v1/auth/refresh":
            return httpx.Response(200, json={"access_token": "new", "refresh_token": "r2"})
        if p == "/api/v1/account":
            calls["account"] += 1
            if request.headers.get("authorization") == "Bearer tok":
                return httpx.Response(401, json={"detail": "expired"})
            return httpx.Response(200, json={"email": "a@b.com"})
        return httpx.Response(200, json={})

    c = _logged_in(handler)
    acct = c.account()
    assert acct["email"] == "a@b.com"
    assert calls["account"] == 2  # original 401 + retry
    assert c.tokens.access_token == "new"

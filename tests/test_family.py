"""Tier-2 family-domain coverage: /me/family self-service + public invite validate."""

import httpx
import pytest

from ubilltu import Family, InviteCode, InvitePreview, UbilltuAuthError, UbilltuClient


def make_client(handler):
    return UbilltuClient("demo", transport=httpx.MockTransport(handler))


def _logged_in(handler):
    def wrapped(request):
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)

    c = make_client(wrapped)
    c.login("a@b.com", "pw")
    return c


def test_get_family_parses_view_and_members():
    def handler(request):
        assert request.url.path == "/api/v1/me/family"
        return httpx.Response(
            200,
            json={
                "family": {
                    "family_subscription_id": "fam1",
                    "plan_name": "Premium Family",
                    "is_owner": True,
                    "owner_name": "Jarod",
                    "owner_email": "j@x.com",
                    "total_seats": 5,
                    "active_members": 2,
                    "extra_seats_purchased": 0,
                    "members": [
                        {"member_id": "m1", "member_email": "j@x.com", "is_owner": True,
                         "joined_date": "2026-01-01", "is_self": True},
                        {"member_id": "m2", "member_email": "k@x.com", "is_owner": False,
                         "joined_date": "2026-02-01", "is_self": False},
                    ],
                }
            },
        )

    fam = _logged_in(handler).get_family()
    assert isinstance(fam, Family)
    assert fam.family_subscription_id == "fam1"
    assert fam.is_owner is True
    assert fam.total_seats == 5
    assert fam.active_members == 2
    assert fam.seats_available == 3
    assert len(fam.members) == 2
    assert fam.members[0].is_self is True


def test_get_family_returns_none_when_not_in_family():
    def handler(request):
        return httpx.Response(200, json={"family": None})

    assert _logged_in(handler).get_family() is None


def test_create_family_invite_unwraps_data_and_sends_expiry():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = request.read().decode() if request.content else ""
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "code": "ABC123",
                    "family_subscription_id": "fam1",
                    "created_by": "j@x.com",
                    "created_at": "2026-07-01",
                    "expires_at": "2026-07-04",
                    "current_uses": 0,
                    "status": "ACTIVE",
                },
                "message": "",
            },
        )

    inv = _logged_in(handler).create_family_invite(expires_in_hours=48)
    assert isinstance(inv, InviteCode)
    assert inv.code == "ABC123"
    assert inv.status == "ACTIVE"
    assert seen["path"] == "/api/v1/me/family/invite"
    assert "48" in seen["body"]


def test_list_family_invites_unwraps_data_list():
    def handler(request):
        assert request.url.path == "/api/v1/me/family/invites"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {"code": "AAA", "status": "ACTIVE", "current_uses": 0},
                    {"code": "BBB", "status": "REVOKED", "current_uses": 1},
                ],
                "total": 2,
            },
        )

    codes = _logged_in(handler).list_family_invites()
    assert [c.code for c in codes] == ["AAA", "BBB"]
    assert all(isinstance(c, InviteCode) for c in codes)


def test_validate_invite_is_public_and_returns_preview():
    """validate_invite must NOT require auth (join page runs pre-login)."""
    def handler(request):
        # No Authorization header should be attached on this public call.
        assert "authorization" not in {k.lower() for k in request.headers.keys()}
        assert request.url.path == "/api/v1/invite/ABC123/validate"
        return httpx.Response(
            200,
            json={
                "success": True,
                "preview": {
                    "family_subscription_id": "fam1",
                    "plan_name": "Premium Family",
                    "owner_name": "Jarod",
                    "owner_email": "j@x.com",
                    "seats_available": 3,
                    "expires_at": "2026-07-04",
                },
            },
        )

    # Fresh (unauthenticated) client — public endpoint must still work.
    preview = make_client(handler).validate_invite("ABC123")
    assert isinstance(preview, InvitePreview)
    assert preview.owner_name == "Jarod"
    assert preview.seats_available == 3


def test_family_mutations_before_login_raise():
    client = make_client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(UbilltuAuthError):
        client.get_family()
    with pytest.raises(UbilltuAuthError):
        client.leave_family()

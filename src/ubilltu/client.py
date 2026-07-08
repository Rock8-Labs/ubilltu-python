"""The ubilltu API client (customer/storefront plane)."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .errors import UbilltuApiError, UbilltuAuthError
from .models import (
    AccountBalance,
    Family,
    Invoice,
    InviteCode,
    InvitePreview,
    Page,
    Payment,
    PaymentMethod,
    Plan,
    Subscription,
    Tokens,
    UsageMetrics,
)

_DEFAULT_BASE_URL = "https://api.ubilltu.com"


class UbilltuClient:
    """A client for the ubilltu subscription commerce API.

    Every request is scoped to a tenant via the ``X-Storefront-Slug`` header.
    After :meth:`login`, the bearer token is attached automatically.

    >>> client = UbilltuClient("your-store-slug")
    >>> client.login("user@example.com", "password")   # doctest: +SKIP
    >>> plans = client.list_plans()                     # doctest: +SKIP

    Usable as a context manager::

        with UbilltuClient("slug") as client:
            client.login(email, password)
            ...
    """

    def __init__(
        self,
        storefront_slug: str,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.storefront_slug = storefront_slug
        self.base_url = base_url.rstrip("/")
        self._tokens: Optional[Tokens] = None
        self._http = httpx.Client(
            base_url=self.base_url, timeout=timeout, transport=transport
        )

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "UbilltuClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    # -- session -----------------------------------------------------------

    @property
    def tokens(self) -> Optional[Tokens]:
        """The active session tokens, or ``None`` if not authenticated."""
        return self._tokens

    @property
    def is_authenticated(self) -> bool:
        return self._tokens is not None and bool(self._tokens.access_token)

    def restore_session(self, tokens: Tokens) -> None:
        """Restore a session from previously persisted tokens."""
        self._tokens = tokens

    # -- auth --------------------------------------------------------------

    def login(self, email: str, password: str) -> Tokens:
        """Authenticate a subscriber and store the session."""
        data = self._post(
            "/api/v1/auth/login", {"email": email, "password": password}, auth=False
        )
        self._tokens = Tokens.from_json(data)
        return self._tokens

    def register(
        self,
        email: str,
        password: str,
        name: Optional[str] = None,
        *,
        tos_accepted: bool = True,
    ) -> Tokens:
        """Register a new subscriber; stores the session if tokens are returned.

        The API requires ``tos_accepted=True`` (the caller's user must accept the
        Terms of Service); it defaults to ``True`` here for convenience.
        """
        body: dict = {
            "email": email,
            "password": password,
            "tos_accepted": tos_accepted,
        }
        if name is not None:
            body["name"] = name
        tokens = Tokens.from_json(self._post("/api/v1/auth/register", body, auth=False))
        if tokens.access_token:
            self._tokens = tokens
        return tokens

    def refresh(self) -> Tokens:
        """Refresh the access token using the stored refresh token."""
        rt = self._tokens.refresh_token if self._tokens else None
        if not rt:
            raise UbilltuAuthError("No refresh token available.")
        data = self._post("/api/v1/auth/refresh", {"refresh_token": rt}, auth=False)
        self._tokens = Tokens.from_json(data)
        return self._tokens

    def logout(self) -> None:
        """Clear the local session (does not revoke the token server-side)."""
        self._tokens = None

    def me(self) -> dict:
        """The authenticated subscriber's profile."""
        return self._get("/api/v1/auth/me")

    # -- account -----------------------------------------------------------

    def account(self) -> dict:
        """The authenticated subscriber's account details."""
        return self._get("/api/v1/account")

    def update_account(self, fields: dict) -> dict:
        """Update the subscriber's profile fields (e.g. ``name``, ``phone``)."""
        return self._put("/api/v1/account", fields)

    def balance(self) -> AccountBalance:
        """The subscriber's outstanding balance + available credit."""
        return AccountBalance.from_json(self._get("/api/v1/account/balance"))

    def usage(self) -> UsageMetrics:
        """The subscriber's usage metrics."""
        return UsageMetrics.from_json(self._get("/api/v1/account/usage"))

    def list_payments(self) -> Page:
        """The subscriber's payment history."""
        return Page.from_json(self._get("/api/v1/account/payments"), Payment.from_json)

    def erase_account(
        self, confirm_email: str, confirm_phrase: str = "ERASE"
    ) -> dict:
        """Right-to-erasure (GDPR Art. 17 / POPIA s24). Cancels subscriptions,
        scrubs PII, and pseudonymizes the account — IRREVERSIBLE.

        ``confirm_email`` must match the account email and ``confirm_phrase`` must
        be exactly ``"ERASE"``. Returns ``{"erasure_id", "erased_fields": [...]}``.
        """
        return self._post(
            "/api/v1/account/erase",
            {"confirm_email": confirm_email, "confirm_phrase": confirm_phrase},
        )

    # -- plans -------------------------------------------------------------

    def list_plans(self) -> Page:
        """List available plans from the tenant catalog."""
        return Page.from_json(self._get("/api/v1/plans"), Plan.from_json)

    def get_plan(self, plan_id: str) -> Plan:
        """Fetch a single plan by id."""
        return Plan.from_json(self._get(f"/api/v1/plans/{plan_id}"))

    # -- subscriptions -----------------------------------------------------

    def list_subscriptions(self) -> Page:
        """List the subscriber's subscriptions."""
        return Page.from_json(
            self._get("/api/v1/subscriptions"), Subscription.from_json
        )

    def get_subscription(self, subscription_id: str) -> Subscription:
        """Fetch a single subscription."""
        return Subscription.from_json(
            self._get(f"/api/v1/subscriptions/{subscription_id}")
        )

    def subscribe(self, plan_id: str, **extra: Any) -> Subscription:
        """Subscribe to a plan. Extra body fields may be passed as kwargs."""
        body = {"plan_id": plan_id, **extra}
        return Subscription.from_json(self._post("/api/v1/subscriptions", body))

    def change_plan(
        self,
        subscription_id: str,
        new_plan_id: str,
        *,
        policy: str = "END_OF_TERM",
        price_list: Optional[str] = None,
    ) -> Subscription:
        """Change a subscription's plan (upgrade/downgrade/period change).

        The billing period is encoded in ``new_plan_id`` (e.g. ``premium-annual``).
        ``policy`` defaults to ``END_OF_TERM``; pass ``IMMEDIATE`` to apply now.
        """
        body: dict = {"plan_id": new_plan_id, "billing_policy": policy}
        if price_list:
            body["price_list"] = price_list
        return Subscription.from_json(
            self._put(f"/api/v1/subscriptions/{subscription_id}", body)
        )

    def preview_change(
        self, subscription_id: str, new_plan: Optional[str] = None
    ) -> dict:
        """Preview the pro-rata invoice for a plan change before committing."""
        params = {"new_plan": new_plan} if new_plan else None
        return self._get(f"/api/v1/subscriptions/{subscription_id}/dry-run", params=params)

    def cancel_subscription(self, subscription_id: str) -> dict:
        """Cancel a subscription."""
        return self._delete(f"/api/v1/subscriptions/{subscription_id}")

    def pause_subscription(self, subscription_id: str) -> Subscription:
        """Pause a subscription."""
        return Subscription.from_json(
            self._post(f"/api/v1/subscriptions/{subscription_id}/pause", {})
        )

    def resume_subscription(self, subscription_id: str) -> Subscription:
        """Resume a paused subscription."""
        return Subscription.from_json(
            self._post(f"/api/v1/subscriptions/{subscription_id}/resume", {})
        )

    def reactivate_subscription(self, subscription_id: str) -> Subscription:
        """Reactivate a cancelled subscription."""
        return Subscription.from_json(
            self._post(f"/api/v1/subscriptions/{subscription_id}/reactivate", {})
        )

    def self_resume_allowed(self, subscription_id: str) -> bool:
        """Whether the customer may resume this (paused) subscription themselves
        (the tenant admin can disable self-resume; SEC-019)."""
        return bool(
            self._get(
                f"/api/v1/subscriptions/{subscription_id}/self-resume-allowed"
            ).get("allowed")
        )

    # -- invoices ----------------------------------------------------------

    def list_invoices(self) -> Page:
        """List the subscriber's invoices."""
        return Page.from_json(self._get("/api/v1/invoices"), Invoice.from_json)

    def get_invoice(self, invoice_id: str) -> dict:
        """Fetch a single invoice with line-item detail."""
        return self._get(f"/api/v1/invoices/{invoice_id}")

    def invoice_pdf(self, invoice_id: str) -> bytes:
        """Download an invoice as raw PDF bytes."""
        resp = self._http.get(
            f"/api/v1/invoices/{invoice_id}/pdf", headers=self._headers()
        )
        if resp.status_code // 100 != 2:
            self._raise(resp)
        return resp.content

    def invoice_html(self, invoice_id: str) -> str:
        """Render an invoice as branded HTML (string)."""
        resp = self._http.get(
            f"/api/v1/invoices/{invoice_id}/html", headers=self._headers()
        )
        if resp.status_code // 100 != 2:
            self._raise(resp)
        return resp.text

    # -- family ------------------------------------------------------------

    def get_family(self) -> Optional[Family]:
        """The caller's family view (owner or member), or ``None`` if not in one."""
        fam = self._get("/api/v1/me/family").get("family")
        return Family.from_json(fam) if isinstance(fam, dict) else None

    def remove_family_member(self, member_id: str) -> dict:
        """Owner removes a member from their family."""
        return self._post(f"/api/v1/me/family/members/{member_id}/remove", {})

    def leave_family(self) -> dict:
        """Leave the family the caller currently belongs to (members only)."""
        return self._post("/api/v1/me/family-memberships/leave", {})

    def create_family_invite(self, expires_in_hours: int = 72) -> InviteCode:
        """Owner generates a fresh invite code (invalidates any existing one)."""
        r = self._post(
            "/api/v1/me/family/invite", {"expires_in_hours": expires_in_hours}
        )
        return InviteCode.from_json(r.get("data") or {})

    def list_family_invites(self) -> list:
        """List invite codes for the caller's owned family."""
        r = self._get("/api/v1/me/family/invites")
        return [InviteCode.from_json(c) for c in (r.get("data") or [])]

    def revoke_family_invite(self, code: str) -> dict:
        """Owner revokes an invite code."""
        return self._post(f"/api/v1/me/family/invite/{code}/revoke", {})

    def accept_family_invite(self, code: str) -> dict:
        """Redeem an invite code to join a family (identity comes from the session)."""
        return self._post(f"/api/v1/me/family/invite/{code}/accept", {})

    def validate_invite(self, code: str) -> InvitePreview:
        """Public preview of an invite code (no auth) — for a join page pre-login."""
        r = self._request("GET", f"/api/v1/invite/{code}/validate", auth=False)
        return InvitePreview.from_json(r.get("preview") or {})

    # -- payments ----------------------------------------------------------

    def list_payment_methods(self) -> Page:
        """List the subscriber's saved payment methods (cards on file)."""
        return Page.from_json(
            self._get("/api/v1/payments/methods"), PaymentMethod.from_json
        )

    def add_payment_method(
        self, card_token: str, is_default: bool = False
    ) -> PaymentMethod:
        """Save a payment method from a PSP card token."""
        return PaymentMethod.from_json(
            self._post(
                "/api/v1/payments/methods",
                {"card_token": card_token, "is_default": is_default},
            )
        )

    def delete_payment_method(self, method_id: str) -> dict:
        """Remove a saved payment method (re-promotes another card if it was default)."""
        return self._delete(f"/api/v1/payments/methods/{method_id}")

    def set_default_payment_method(self, method_id: str) -> dict:
        """Make a saved payment method the account default."""
        return self._put(f"/api/v1/payments/methods/{method_id}/default", {})

    def reconcile_default_payment_method(self) -> dict:
        """Ensure the account default points at a real, chargeable card
        (promotes the first real card if the default is an incomplete shell)."""
        return self._post("/api/v1/payments/methods/reconcile-default", {})

    def get_payment(self, payment_id: str) -> Payment:
        """Fetch a single payment's live status (reconciles PENDING with the gateway)."""
        return Payment.from_json(self._get(f"/api/v1/payments/{payment_id}"))

    def create_one_off_payment(self, source: dict, settlement: dict) -> dict:
        """Make an ad-hoc / one-off payment.

        ``source`` describes what to pay, e.g.
        ``{"type": "ad_hoc", "amount": 50, "currency": "ZAR", "description": "..."}``
        (or ``{"type": "invoice", "invoice_id": ...}`` / ``{"type": "addon", "plan_id": ...}``).
        ``settlement`` describes how, e.g. ``{"mode": "saved", "payment_method_id": ...}``
        or ``{"mode": "hosted", "return_url": ...}``.

        Returns the raw response (``status``, ``requires_redirect``, ``redirect_url``,
        ``payment_id``); on a hosted settlement send the customer to ``redirect_url``.
        """
        return self._post(
            "/api/v1/payments/one-off", {"source": source, "settlement": settlement}
        )

    def setup_payment_method(
        self, return_url: str, is_default: bool = False
    ) -> dict:
        """Start a zero-amount card-on-file setup.

        Returns ``{"redirect_url": ...}`` — send the customer to that hosted page
        to enter their card. The card becomes usable once they complete it.
        """
        return self._post(
            "/api/v1/payments/methods/setup",
            {"return_url": return_url, "is_default": is_default},
        )

    def signup(self, plan_id: str, return_url: str) -> dict:
        """Subscribe to a plan AND start payment collection in one call.

        Returns ``{"subscription_id", "payment_id", "redirect_url"}`` — the
        subscription exists immediately; send the customer to ``redirect_url`` to
        pay the first invoice on the hosted checkout page.
        """
        return self._post(
            "/api/v1/subscriptions/signup",
            {"plan_id": plan_id, "return_url": return_url},
        )

    def checkout(
        self,
        amount: float,
        currency: str = "ZAR",
        invoice_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
    ) -> dict:
        """Start a hosted checkout for an amount.

        Returns ``{"payment_id", "redirect_url"}``.
        """
        body: dict = {"amount": amount, "currency": currency}
        if invoice_id:
            body["invoice_id"] = invoice_id
        if subscription_id:
            body["subscription_id"] = subscription_id
        return self._post("/api/v1/payments/checkout", body)

    # -- internals ---------------------------------------------------------

    def _headers(self, json: bool = False, auth: bool = True) -> dict:
        h = {
            "X-Storefront-Slug": self.storefront_slug,
            "Accept": "application/json",
        }
        if json:
            h["Content-Type"] = "application/json"
        if auth:
            if not self.is_authenticated:
                raise UbilltuAuthError()
            assert self._tokens is not None
            h["Authorization"] = f"Bearer {self._tokens.access_token}"
        return h

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: dict, auth: bool = True) -> dict:
        return self._request("POST", path, body=body, auth=auth)

    def _put(self, path: str, body: dict) -> dict:
        return self._request("PUT", path, body=body)

    def _delete(self, path: str) -> dict:
        return self._request("DELETE", path)

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        auth: bool = True,
        params: Optional[dict] = None,
    ) -> dict:
        resp = self._http.request(
            method,
            path,
            headers=self._headers(json=body is not None, auth=auth),
            json=body if body is not None else None,
            params=params,
        )
        if resp.status_code // 100 != 2:
            self._raise(resp)
        if not resp.content:
            return {}
        try:
            data = resp.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {"data": data}

    def _raise(self, resp: httpx.Response) -> None:
        body: Optional[dict] = None
        message = resp.reason_phrase or "Request failed"
        try:
            parsed = resp.json()
            if isinstance(parsed, dict):
                body = parsed
                err = parsed.get("error")
                if isinstance(err, dict) and err.get("message"):
                    message = err["message"]
                else:
                    message = parsed.get("detail") or parsed.get("message") or message
        except Exception:
            pass
        raise UbilltuApiError(resp.status_code, str(message), body)

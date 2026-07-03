"""Typed models returned by the ubilltu client.

Each model exposes the common fields plus ``raw`` — the full JSON payload — so
nothing is lost even when the API adds fields the typed layer doesn't surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    """A paginated list envelope (``{items, total, page, per_page}``)."""

    items: list
    total: int
    page: int
    per_page: int

    @classmethod
    def from_json(cls, r: dict, mapper: Callable[[dict], T]) -> "Page[T]":
        items = r.get("items") or []
        return cls(
            items=[mapper(i) for i in items],
            total=int(r.get("total", len(items))),
            page=int(r.get("page", 1)),
            per_page=int(r.get("per_page", len(items))),
        )


@dataclass
class Tokens:
    """Auth tokens returned by login/register/refresh."""

    access_token: str
    refresh_token: Optional[str] = None
    token_type: Optional[str] = None

    @classmethod
    def from_json(cls, r: dict) -> "Tokens":
        return cls(
            access_token=str(r.get("access_token") or r.get("token") or ""),
            refresh_token=r.get("refresh_token"),
            token_type=r.get("token_type"),
        )


@dataclass
class Plan:
    """A subscription plan from the tenant catalog."""

    id: str
    name: str
    price: Optional[float]
    currency: Optional[str]
    billing_period: Optional[str]
    trial_days: Optional[int]
    raw: dict

    @classmethod
    def from_json(cls, r: dict) -> "Plan":
        phases = r.get("phases") or []
        trial = next(
            (p for p in phases if (p.get("phase_type") or p.get("phaseType")) == "TRIAL"),
            None,
        )
        # The API returns price/currency inside a `prices[]` array and the
        # display name in `product_name`; fall back to flat fields for safety.
        prices = r.get("prices") or []
        first = prices[0] if prices else {}
        price = r.get("price")
        if price is None:
            price = r.get("amount")
        if price is None:
            price = first.get("amount")
        return cls(
            id=str(r.get("plan_id") or r.get("id") or r.get("plan_name") or r.get("name") or ""),
            name=str(r.get("product_name") or r.get("plan_name") or r.get("name") or ""),
            price=price,
            currency=r.get("currency") or first.get("currency"),
            billing_period=r.get("billing_period")
            or r.get("billingPeriod")
            or first.get("billing_period"),
            trial_days=(trial.get("duration_length") or trial.get("durationLength"))
            if trial
            else None,
            raw=r,
        )


@dataclass
class Subscription:
    """A subscriber's subscription."""

    id: str
    plan_name: Optional[str]
    product_name: Optional[str]
    state: Optional[str]
    price: Optional[float]
    currency: Optional[str]
    raw: dict

    @classmethod
    def from_json(cls, r: dict) -> "Subscription":
        # The detail endpoint wraps it as {"subscription": {...}, "events": [...]};
        # the list returns it flat. Unwrap so both shapes parse.
        sub = r.get("subscription") if isinstance(r.get("subscription"), dict) else r
        return cls(
            id=str(sub.get("subscription_id") or sub.get("id") or ""),
            plan_name=sub.get("plan_name") or sub.get("planName"),
            product_name=sub.get("product_name") or sub.get("productName"),
            state=sub.get("state") or sub.get("status"),
            price=sub.get("price"),
            currency=sub.get("currency"),
            raw=r,
        )


@dataclass
class Invoice:
    """An invoice."""

    id: str
    amount: Optional[float]
    currency: Optional[str]
    status: Optional[str]
    raw: dict

    @classmethod
    def from_json(cls, r: dict) -> "Invoice":
        amount = r.get("amount")
        return cls(
            id=str(r.get("invoice_id") or r.get("id") or ""),
            amount=amount if amount is not None else r.get("balance"),
            currency=r.get("currency"),
            status=r.get("status"),
            raw=r,
        )


@dataclass
class Payment:
    """A payment record."""

    id: str
    amount: Optional[float]
    currency: Optional[str]
    status: Optional[str]
    raw: dict

    @classmethod
    def from_json(cls, r: dict) -> "Payment":
        amount = r.get("amount")
        return cls(
            id=str(r.get("payment_id") or r.get("id") or ""),
            amount=amount if amount is not None else r.get("purchased_amount"),
            currency=r.get("currency"),
            status=r.get("status") or r.get("state"),
            raw=r,
        )


@dataclass
class PaymentMethod:
    """A saved payment method (card on file)."""

    id: str
    is_default: bool
    card_brand: Optional[str]
    card_last4: Optional[str]
    expiry_month: Optional[int]
    expiry_year: Optional[int]
    raw: dict

    @classmethod
    def from_json(cls, r: dict) -> "PaymentMethod":
        return cls(
            id=str(r.get("payment_method_id") or r.get("id") or ""),
            is_default=bool(r.get("is_default")),
            card_brand=r.get("card_brand"),
            card_last4=r.get("card_last_four") or r.get("last4"),
            expiry_month=r.get("expiry_month"),
            expiry_year=r.get("expiry_year"),
            raw=r,
        )

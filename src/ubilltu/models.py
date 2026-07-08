"""Typed models returned by the ubilltu client.

Each model exposes the common fields plus ``raw`` — the full JSON payload — so
nothing is lost even when the API adds fields the typed layer doesn't surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, List, Optional, TypeVar

T = TypeVar("T")


def _first(d: dict, *keys):
    """Return the first present, non-None value among ``keys`` (snake/camel)."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


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
    # Enrichment the API merges onto plans (not in the raw Kill Bill catalog):
    features: List[str] = field(default_factory=list)
    billing_mode: Optional[str] = None  # "full_price" | "pro_rata"
    billing_day: Optional[int] = None   # set only for pro_rata plans
    family_config: Optional[dict] = None  # {"enabled": bool, "includedSeats": int} | None
    raw: dict = field(default_factory=dict)

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
        price = _first(r, "price", "amount") or first.get("amount")
        return cls(
            id=str(_first(r, "plan_id", "id", "plan_name", "name") or ""),
            name=str(_first(r, "product_name", "plan_name", "name") or ""),
            price=price,
            currency=r.get("currency") or first.get("currency"),
            billing_period=_first(r, "billing_period", "billingPeriod")
            or first.get("billing_period"),
            trial_days=(trial.get("duration_length") or trial.get("durationLength"))
            if trial
            else _first(r, "trial_days", "trialDays"),
            features=list(r.get("features") or []),
            billing_mode=_first(r, "billing_mode", "billingMode"),
            billing_day=_first(r, "billing_day", "billingDay"),
            family_config=_first(r, "family_config", "familyConfig"),
            raw=r,
        )

    @property
    def is_family(self) -> bool:
        """True when this plan is family/group-enabled."""
        fc = self.family_config or {}
        return bool(isinstance(fc, dict) and fc.get("enabled"))

    @property
    def is_pro_rata(self) -> bool:
        return (self.billing_mode or "").lower() == "pro_rata"


@dataclass
class Subscription:
    """A subscriber's subscription."""

    id: str
    plan_name: Optional[str]
    product_name: Optional[str]
    state: Optional[str]
    price: Optional[float]
    currency: Optional[str]
    # Lifecycle / display fields the API returns but the 0.2.0 model dropped:
    cancelled_date: Optional[str] = None      # future date => scheduled end-of-term cancel
    charged_through_date: Optional[str] = None
    billing_end_date: Optional[str] = None
    mrr_monthly: Optional[float] = None        # catalog price normalized to monthly
    last_payment_amount: Optional[float] = None
    last_payment_date: Optional[str] = None
    last_payment_currency: Optional[str] = None
    events: List[dict] = field(default_factory=list)  # detail endpoint's event stream
    raw: dict = field(default_factory=dict)

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
            cancelled_date=_first(sub, "cancelled_date", "cancelledDate"),
            charged_through_date=_first(sub, "charged_through_date", "chargedThroughDate"),
            billing_end_date=_first(sub, "billing_end_date", "billingEndDate"),
            mrr_monthly=_first(sub, "mrr_monthly", "mrrMonthly"),
            last_payment_amount=_first(sub, "last_payment_amount", "lastPaymentAmount"),
            last_payment_date=_first(sub, "last_payment_date", "lastPaymentDate"),
            last_payment_currency=_first(sub, "last_payment_currency", "lastPaymentCurrency"),
            events=list(r.get("events") or sub.get("events") or []),
            raw=r,
        )

    @property
    def is_cancellation_scheduled(self) -> bool:
        """True when an end-of-term cancel is pending: ``cancelled_date`` is set
        while the subscription is still ACTIVE (i.e. "Cancelling", keeps access
        until the period end). Mirrors the storefront/portal UI logic."""
        return self.cancelled_date is not None and (self.state or "").upper() == "ACTIVE"

    @property
    def is_paused(self) -> bool:
        """True when the subscription is currently paused (Kill Bill BLOCKED).
        A *scheduled* (future) pause is not this — it lives in ``events`` as a
        future PAUSE_* event (no top-level field exists yet)."""
        return (self.state or "").upper() == "BLOCKED"


@dataclass
class InvoiceItem:
    """A single line on an invoice."""

    description: Optional[str]
    plan_name: Optional[str]
    phase: Optional[str]
    amount: Optional[float]
    currency: Optional[str]
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, r: dict) -> "InvoiceItem":
        return cls(
            description=r.get("description"),
            plan_name=_first(r, "plan_name", "planName"),
            phase=r.get("phase"),
            amount=r.get("amount"),
            currency=r.get("currency"),
            start_date=_first(r, "start_date", "startDate"),
            end_date=_first(r, "end_date", "endDate"),
            raw=r,
        )


@dataclass
class Invoice:
    """An invoice."""

    id: str
    amount: Optional[float]
    currency: Optional[str]
    status: Optional[str]
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    balance: Optional[float] = None
    credit_adj: Optional[float] = None
    refund_adj: Optional[float] = None
    items: List[InvoiceItem] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, r: dict) -> "Invoice":
        amount = r.get("amount")
        return cls(
            id=str(r.get("invoice_id") or r.get("id") or ""),
            amount=amount if amount is not None else r.get("balance"),
            currency=r.get("currency"),
            status=r.get("status"),
            invoice_number=_first(r, "invoice_number", "invoiceNumber"),
            invoice_date=_first(r, "invoice_date", "invoiceDate"),
            balance=r.get("balance"),
            credit_adj=_first(r, "credit_adj", "creditAdj"),
            refund_adj=_first(r, "refund_adj", "refundAdj"),
            items=[InvoiceItem.from_json(i) for i in (r.get("items") or [])],
            raw=r,
        )

    @property
    def is_empty(self) -> bool:
        """True for the zero-total, zero-item invoices Kill Bill commits on
        subscription setup (findings #1) — useful to filter from a customer list."""
        return (self.amount or 0) == 0 and not self.items


@dataclass
class Payment:
    """A payment record."""

    id: str
    amount: Optional[float]
    currency: Optional[str]
    status: Optional[str]
    payment_number: Optional[str] = None
    payment_date: Optional[str] = None
    invoice_id: Optional[str] = None
    invoice_number: Optional[str] = None
    refunded_amount: Optional[float] = None
    description: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, r: dict) -> "Payment":
        amount = r.get("amount")
        return cls(
            id=str(r.get("payment_id") or r.get("id") or ""),
            amount=amount if amount is not None else r.get("purchased_amount"),
            currency=r.get("currency"),
            status=r.get("status") or r.get("state"),
            payment_number=_first(r, "payment_number", "paymentNumber"),
            payment_date=_first(r, "payment_date", "paymentDate"),
            invoice_id=_first(r, "invoice_id", "invoiceId"),
            invoice_number=_first(r, "invoice_number", "invoiceNumber"),
            refunded_amount=_first(r, "refunded_amount", "refundedAmount"),
            description=r.get("description"),
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
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, r: dict) -> "PaymentMethod":
        return cls(
            id=str(r.get("payment_method_id") or r.get("id") or ""),
            is_default=bool(r.get("is_default")),
            card_brand=_first(r, "card_brand", "card_type"),
            card_last4=_first(r, "card_last_four", "last4"),
            expiry_month=r.get("expiry_month"),
            expiry_year=r.get("expiry_year"),
            raw=r,
        )


@dataclass
class AccountBalance:
    """Outstanding balance + available credit for the account."""

    balance: Optional[float]   # what's owed (Kill Bill accountBalance)
    credit: Optional[float]    # available credit / CBA (offsets future invoices)
    currency: Optional[str]
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, r: dict) -> "AccountBalance":
        return cls(
            balance=r.get("balance"),
            credit=r.get("credit"),
            currency=r.get("currency"),
            raw=r,
        )


@dataclass
class UsageMetrics:
    """Account usage/rollup metrics (``GET /account/usage``)."""

    total_subscriptions: Optional[int]
    active_subscriptions: Optional[int]
    total_invoices: Optional[int]
    unpaid_invoices: Optional[int]
    total_spent: Optional[float]
    currency: Optional[str]
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, r: dict) -> "UsageMetrics":
        return cls(
            total_subscriptions=_first(r, "total_subscriptions", "totalSubscriptions"),
            active_subscriptions=_first(r, "active_subscriptions", "activeSubscriptions"),
            total_invoices=_first(r, "total_invoices", "totalInvoices"),
            unpaid_invoices=_first(r, "unpaid_invoices", "unpaidInvoices"),
            total_spent=_first(r, "total_spent", "totalSpent"),
            currency=r.get("currency"),
            raw=r,
        )


@dataclass
class FamilyMember:
    """A member row in the caller's family view (``GET /me/family``)."""

    member_id: str
    member_email: Optional[str]
    is_owner: bool
    joined_date: Optional[str]
    is_self: bool
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, r: dict) -> "FamilyMember":
        return cls(
            member_id=str(_first(r, "member_id", "id") or ""),
            member_email=r.get("member_email"),
            is_owner=bool(r.get("is_owner")),
            joined_date=_first(r, "joined_date", "joinedDate"),
            is_self=bool(r.get("is_self")),
            raw=r,
        )


@dataclass
class Family:
    """The caller's family (owner or member view) from ``GET /me/family``."""

    family_subscription_id: str
    plan_name: Optional[str]
    is_owner: bool
    owner_name: Optional[str]
    owner_email: Optional[str]
    total_seats: int
    active_members: int
    extra_seats_purchased: int
    members: List[FamilyMember] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, r: dict) -> "Family":
        return cls(
            family_subscription_id=str(
                _first(r, "family_subscription_id", "familySubscriptionId") or ""
            ),
            plan_name=_first(r, "plan_name", "planName"),
            is_owner=bool(r.get("is_owner")),
            owner_name=_first(r, "owner_name", "ownerName"),
            owner_email=_first(r, "owner_email", "ownerEmail"),
            total_seats=int(_first(r, "total_seats", "totalSeats") or 0),
            active_members=int(_first(r, "active_members", "activeMembers") or 0),
            extra_seats_purchased=int(
                _first(r, "extra_seats_purchased", "extraSeatsPurchased") or 0
            ),
            members=[FamilyMember.from_json(m) for m in (r.get("members") or [])],
            raw=r,
        )

    @property
    def seats_available(self) -> int:
        return max(0, self.total_seats - self.active_members)


@dataclass
class InviteCode:
    """A family invite code (``POST/GET /me/family/invite(s)``)."""

    code: str
    family_subscription_id: Optional[str]
    created_by: Optional[str]
    created_at: Optional[str]
    expires_at: Optional[str]
    max_uses: Optional[int]
    current_uses: int
    status: str
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, r: dict) -> "InviteCode":
        return cls(
            code=str(r.get("code") or ""),
            family_subscription_id=_first(
                r, "family_subscription_id", "familySubscriptionId"
            ),
            created_by=_first(r, "created_by", "createdBy"),
            created_at=_first(r, "created_at", "createdAt"),
            expires_at=_first(r, "expires_at", "expiresAt"),
            max_uses=_first(r, "max_uses", "maxUses"),
            current_uses=int(_first(r, "current_uses", "currentUses") or 0),
            status=str(r.get("status") or "ACTIVE"),
            raw=r,
        )


@dataclass
class InvitePreview:
    """Public preview of an invite code (``GET /invite/{code}/validate``)."""

    family_subscription_id: Optional[str]
    plan_name: Optional[str]
    owner_name: Optional[str]
    owner_email: Optional[str]
    seats_available: Optional[int]
    expires_at: Optional[str]
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, r: dict) -> "InvitePreview":
        return cls(
            family_subscription_id=_first(
                r, "family_subscription_id", "familySubscriptionId"
            ),
            plan_name=_first(r, "plan_name", "planName"),
            owner_name=_first(r, "owner_name", "ownerName"),
            owner_email=_first(r, "owner_email", "ownerEmail"),
            seats_available=_first(r, "seats_available", "seatsAvailable"),
            expires_at=_first(r, "expires_at", "expiresAt"),
            raw=r,
        )

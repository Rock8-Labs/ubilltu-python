# ubilltu

Official Python client for the [ubilltu](https://ubilltu.com) subscription commerce API.

```bash
pip install ubilltu
```

## Usage

```python
from ubilltu import UbilltuClient

client = UbilltuClient("your-store-slug")
client.login("user@example.com", "password")

for plan in client.list_plans().items:
    print(plan.name, plan.currency, plan.price)

sub = client.subscribe(client.list_plans().items[0].id)
client.change_plan(sub.id, "premium-annual", policy="IMMEDIATE")
client.pause_subscription(sub.id)
client.cancel_subscription(sub.id)
```

Every request is scoped to a tenant via the `X-Storefront-Slug` header; the bearer token
from `login()` is attached automatically. Use it as a context manager to close the
connection pool:

```python
with UbilltuClient("your-store-slug") as client:
    client.login(email, password)
    invoices = client.list_invoices()
```

## API

| Area | Methods |
|---|---|
| Auth | `login`, `register`, `refresh`, `logout`, `me`, `restore_session` |
| Account | `account`, `update_account`, `balance`, `usage`, `list_payments` |
| Plans | `list_plans`, `get_plan` |
| Subscriptions | `list_subscriptions`, `get_subscription`, `subscribe`, `change_plan`, `preview_change`, `cancel_subscription`, `pause_subscription`, `resume_subscription`, `reactivate_subscription` |
| Invoices | `list_invoices`, `get_invoice`, `invoice_pdf` |

List calls return a `Page` (`items`, `total`, `page`, `per_page`). Typed models
(`Plan`, `Subscription`, `Invoice`, `Payment`) expose common fields plus `.raw`.
Errors raise `UbilltuApiError` (non-2xx, with `.status_code`) or `UbilltuAuthError`.

## Error handling

```python
from ubilltu import UbilltuApiError, UbilltuAuthError

try:
    client.subscribe(plan_id)
except UbilltuApiError as e:
    print(e.status_code, e)
except UbilltuAuthError:
    print("log in first")
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

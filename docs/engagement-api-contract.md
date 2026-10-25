# Engagement API Contract (V3)

Internal HTTP contract between **Bot Core** and the **Engagement API**.
The Engagement API is stateless and is never exposed publicly.

## Ownership Boundary

| Data | Owner |
|------|-------|
| Platforms, categories, allow-listed provider services | Engagement API |
| Live provider catalog, provider cost, provider order calls | Engagement API |
| Provider credentials and provider error rules | Engagement API |
| Users, wallets, deposits, ledger, orders, payments | Bot Core / Turso |
| Durable idempotency (`orders.request_key`) | Bot Core / Turso |
| Provider confirmation (`provider_orders`) | Bot Core / Turso |
| Refunds and reconciliation state | Bot Core / Turso |

The Engagement API has **no database** and must not receive Turso credentials.

## Authentication

Every `/v1/*` endpoint requires the shared internal token:

```http
X-Internal-Token: <ENGAGEMENT_INTERNAL_TOKEN>
```

`Authorization: Bearer <token>` is also accepted. Missing or invalid tokens
return `401` with `{"detail": "Invalid internal token"}`.

Health endpoints are unauthenticated.

## Health

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health/live` | Liveness only; never checks the provider |
| `GET` | `/health/ready` | Catalog loaded and at least one provider configured |
| `GET` | `/health/dependencies` | Informational provider check; always HTTP 200 |
| `GET` | `/health` | Legacy aggregate health response |

`/health/ready` returns `503` with `status="not_ready"` when no provider is
configured. It deliberately does not fail on a transient provider outage, so a
provider incident cannot restart the container.

## Catalog

All prices in this API are **provider cost**, not customer sale prices:

- `rate_milli` = cost in 1/1000 VND per 1,000 units.
- Bot Core applies its own markup before showing a price.
- `cost_source="provider"` means the value came from the live provider.
- `cost_source="configured"` means the provider catalog was unavailable and the
  code-owned fallback cost was used.

| Method | Path | Response |
|--------|------|----------|
| `GET` | `/v1/platforms` | `{"platforms": [...]}` including Coming Soon platforms |
| `GET` | `/v1/platforms/{slug}/categories` | `{"categories": [...]}` |
| `GET` | `/v1/categories/{id}` | Category object |
| `GET` | `/v1/categories/{id}/services` | `{"services": [...]}` |
| `GET` | `/v1/services/{id}` | Provider service object |

Only service IDs in the Engagement API allow-list are returned, even if the
provider exposes additional services.

### Example service

```json
{
  "id": 1720,
  "category_id": 101,
  "category_slug": "members",
  "platform_slug": "telegram",
  "provider_id": "vietnamfb",
  "provider_service_id": "1720",
  "name": "Telegram Members HQ",
  "min_quantity": 10,
  "max_quantity": 1000000,
  "rate_milli": 40686,
  "status": "active",
  "cost_source": "provider"
}
```

## Orders

### Create order

```http
POST /v1/orders
Content-Type: application/json
X-Internal-Token: <token>

{
  "service_id": 1720,
  "quantity": 1000,
  "link": "https://t.me/example",
  "idempotency_key": "eng:<user>:<service>:<hash>"
}
```

Successful provider acceptance:

```json
{
  "success": true,
  "definitive": true,
  "provider_order_id": "987654",
  "charge_milli": 40686000,
  "status": "processing",
  "error": null,
  "reconciliation_required": false
}
```

Definitive provider rejection (no order was created):

```json
{
  "success": false,
  "definitive": true,
  "provider_order_id": null,
  "charge_milli": null,
  "status": "failed",
  "error": "Service unavailable",
  "reconciliation_required": false
}
```

Ambiguous outcome (timeout, transport failure, provider 5xx, missing order ID):

```json
{
  "success": false,
  "definitive": false,
  "provider_order_id": null,
  "charge_milli": null,
  "status": "pending_reconciliation",
  "error": "VietnamFB add timed out",
  "reconciliation_required": true
}
```

Provider `POST /add` is **never retried**. A timeout or 5xx may still have
created a provider order, so it must be treated as ambiguous.

### HTTP status codes for `POST /v1/orders`

| Code | Meaning |
|------|---------|
| `200` | Request processed; inspect `success` and `definitive` |
| `400` | Invalid quantity/request |
| `401` | Missing/invalid internal token |
| `404` | Unknown or unavailable service |
| `409` | Same idempotency key already in flight in this API process |
| `429` | Internal rate limit exceeded |
| `502` | Last-resort provider error |
| `503` | Provider not configured/unavailable |

Bot Core treats `408`, `409`, `425`, `429`, network errors and all `5xx`
responses as **ambiguous**: it keeps the charge and marks the order
`pending_reconciliation` rather than refunding. A `409` means another request
with the same idempotency key is still in flight and may still create the
provider order.

### Order status

```http
GET /v1/orders/{provider_order_id}/status?provider=vietnamfb
X-Internal-Token: <token>
```

Returns the live provider status. The Engagement API stores no order history.

## Bot Core Order Sequence

1. Fetch and validate the selected service from the Engagement API.
2. Validate link and quantity locally.
3. In one Bot Core transaction:
   - insert the local order with a unique `request_key`;
   - debit the wallet;
   - write the `provider_payment` ledger entry.
4. Call `POST /v1/orders`.
5. On success with a provider order ID: persist `provider_orders` and keep the charge.
6. On definitive rejection: refund exactly once and mark the order `rejected`.
7. On ambiguous failure: keep the charge, mark `pending_reconciliation`, and alert admins.
8. Replayed confirmations find the existing `request_key` and cannot charge or order twice.

## Environment Requirements

Engagement API:

```env
ENVIRONMENT=production
ENGAGEMENT_INTERNAL_TOKEN=<shared secret>
VIETNAMFB_API_KEY=<provider key>
VIETNAMFB_BASE_URL=https://vietnamfb.com
```

Bot Core:

```env
ENGAGEMENT_API_URL=http://toolnet-engagement:8000
ENGAGEMENT_API_TOKEN=<same shared secret>
```

Do not add `TURSO_URL`, `TURSO_TOKEN`, `DATABASE_URL` or `DATABASE_TOKEN` to
the Engagement API. Do not add `VIETNAMFB_API_KEY` to Bot Core.

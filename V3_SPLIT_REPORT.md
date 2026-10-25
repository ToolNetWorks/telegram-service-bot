# ToolNet V3 Split — Final Report

**Date:** 2026-10-25  
**Branch:** `master` (local, uncommitted)  
**Repo:** `ToolNetWorks/telegram-service-bot`

---

## Executive Summary

ToolNet V3 splits the monorepo into **two independently deployable Northflank services**:

| Service | Type | Responsibility | Database |
|---------|------|----------------|----------|
| **Bot Core** (`apps/bot-core/`) | Worker (1 replica, long polling) | Telegram UI, users, wallet, orders, payments, referrals, admin, Turso | Turso (libSQL) |
| **Engagement API** (`apps/engagement-api/`) | Stateless FastAPI (1+ replicas, internal :8000) | Catalog, provider integration (VietnamFB), order orchestration | **None** |

Communication: authenticated internal HTTP (`X-Internal-Token`).  
**Canonical path:** `apps/engagement-api/` (Northflank builds `/apps/engagement-api/Dockerfile`). Duplicate `apps/engagement_api/` removed.

All tests pass (92 total), Docker images build cleanly, smoke tests verified, no secrets in images.

---

## 1. Bot Core (`apps/bot-core/`)

### 1.1 Major Changes

#### Catalog Source Migration
- **Removed**: Local `engagement_platforms`, `engagement_categories`, `engagement_provider_services` tables + seed data from migrations.
- **Added**: `EngagementRepository` → `EngagementClient` → Engagement API for **all** catalog data.
- Bot Core now contains **zero** hardcoded provider IDs, provider costs, category lists, or service definitions.

#### EngagementClient (`app/clients/engagement.py`)
```python
@dataclass
class OrderResult:
    success: bool
    definitive: bool = True          # NEW: provider outcome classification
    reconciliation_required: bool = False
    status: str | None = None
    provider_order_id: str | None = None
    charge_milli: int | None = None
    error: str | None = None
```
- HTTP error classification:
  - `408, 409, 425, 429` and all `5xx` → **ambiguous** (`definitive=False`)
  - Other `4xx` → **definitive** (`definitive=True`)
  - Network/timeout/JSON decode → ambiguous
- Malformed API response (missing `success` field) → ambiguous
- Legacy callbacks preserved: `engagement:telegram_members`, `tg_member_select:<id>`, `tg_member_confirm_pay[...]`

#### OrderRepository (`app/modules/orders/repository.py`)
| Method | Safety Guarantee |
|--------|------------------|
| `begin_provider_order` | Atomic: insert order + debit wallet + ledger. Returns `"duplicate"` on `request_key` race or lost commit. **Caller never calls provider for duplicate.** |
| `refund_provider_order` | Refunds **exactly once**; guarded by `ledger.UNIQUE(kind, reference)` |
| `mark_pending_reconciliation` | Keeps charge, flags order for admin/manual reconciliation |
| `attach_provider_order` | Idempotent provider confirmation write |
| `find_by_request_key` | Used after ambiguous local write to detect existing order |

#### Handlers (`app/telegram/handlers.py`)
- **Navigation**: Engagement Services → 6 platforms (Telegram, YouTube, Twitter/X, Facebook, Instagram, Shopee)
- **Telegram submenu**: Member Telegram / View Telegram
- **Back buttons**: `← Tool Access`, `← Engagement Services`
- **View Telegram (no provider)**: Shows "service being updated" — **no fake orders**
- **Unimplemented platforms**: Show "Coming Soon" label, no services
- **Order flow**: validate → `begin_provider_order` → `place_order` → `attach_provider_order` / `mark_pending_reconciliation` / `refund_provider_order`
- **Duplicate click protection**: State claim + `begin_provider_order` duplicate detection → "đã đặt", no second provider call

#### StateManager (`app/core/state.py`)
- Fixed `get_state()` bug (was calling non-existent `Database.get_user()`)
- Now queries `users` table directly, clears expired state on read

#### Database Connection (`app/database/connection.py`)
- **Hard fail** when Turso credentials present without `DB_BACKEND=sqlite`
- No silent SQLite fallback in production

#### Health Check (`healthcheck.py`)
- Validates `TURSO_URL` + `TURSO_TOKEN` when `DB_BACKEND=turso`

#### Migrations (`app/database/migrations.py`)
- Removed engagement catalog tables/seeds
- Added indexes: `idx_orders_request_key`, `idx_provider_orders_provider`

#### ServicesRepository (`app/modules/orders/services_repository.py`)
- `get_or_create_engagement_service()`: Creates local label row; provider identity stored in `provider_orders`

#### i18n (`app/i18n/__init__.py`)
Added keys: `engagement_updating`, `engagement_api_unavailable`, `engagement_choose_package`, `engagement_package_details`, `engagement_generic_link_prompt`, `engagement_confirm_summary`, `engagement_invalid_link`, `back_to_platform`, `engagement_coming_soon`

#### Dockerfile
- Copies `turso_client.py` explicitly
- No Engagement API code
- `.dockerignore` excludes `.env`, tests, caches

### 1.2 Tests (`apps/bot-core/tests/`)

| File | Coverage |
|------|----------|
| `test_bot_core.py` | UI navigation, legacy callbacks, order safety (single charge, definitive refund once, ambiguous → pending_reconciliation), Turso fallback prevention, 409/malformed classification |
| `test_engagement_api_integration.py` | Real Engagement API subprocess + mock VietnamFB HTTP server; full handler E2E without real provider orders |

**Result:** `28 passed`

### 1.3 Deployment Configuration
- **Northflank service:** `toolnet-bot-core` (Worker, 1 replica)
- **Build context:** `/` | **Dockerfile:** `apps/bot-core/Dockerfile`
- **Required env:**
  ```
  BOT_TOKEN, ADMIN_IDS, TURSO_URL, TURSO_TOKEN,
  ENGAGEMENT_API_URL=http://toolnet-engagement:8000,
  ENGAGEMENT_API_TOKEN=<shared>, DB_BACKEND=turso
  ```
- **Must NOT set:** `VIETNAMFB_API_KEY`, `VIETNAMFB_BASE_URL`, `ENGAGEMENT_INTERNAL_TOKEN`

---

## 2. Engagement API (`apps/engagement-api/`)

### 2.1 Architecture
- **Stateless**: No database, no Turso client, no migrations
- **Dockerfile**: Minimal (python:3.12-slim, non-root, healthcheck `/health/live`)
- **Build context:** `/` | **Dockerfile:** `apps/engagement-api/Dockerfile`

### 2.2 Configuration (`app/core/config.py`)
```python
ENVIRONMENT=production          # required
ENGAGEMENT_INTERNAL_TOKEN=...   # required
VIETNAMFB_API_KEY=...           # required in production
VIETNAMFB_BASE_URL=https://vietnamfb.com
# Transport, rate limit, logging knobs...
```
- Production fails fast without `VIETNAMFB_API_KEY`
- **No Turso/database credentials accepted**

### 2.3 Authentication (`app/core/security.py`)
- `X-Internal-Token` (or `Authorization: Bearer`) on **all `/v1/*` endpoints**
- `secrets.compare_digest` for timing-safe comparison
- Includes `GET /v1/orders/{id}/status` (fixed security gap)

### 2.4 Rate Limiting (`app/core/rate_limit.py`)
- Fixed-window per client IP on mutating endpoints
- Backstop only; Bot Core owns durable idempotency

### 2.5 Structured Logging (`app/core/logging.py`)
- JSON formatter, correlation ID middleware
- No token leakage

### 2.6 Provider Abstraction (`app/providers/`)
- `Provider` ABC, `ProviderError(definitive: bool)`, `ProviderRegistry`
- **VietnamFB provider** (`vietnamfb.py`):
  - Async `httpx` client, endpoint `/api/v2`
  - Actions: `services`, `add`, `status`, `balance`
  - `get_services`: cached (TTL 300s), merged with code-owned allow-list
  - `create_order`: **never retried**; timeout/5xx/missing order ID → `definitive=False`
  - Error classification:
    - 408, 425 → ambiguous
    - Other 4xx → definitive
    - 5xx/transport → ambiguous

### 2.7 Catalog (`app/catalog/catalog.py`)
Code-owned **allow-list** (never exposes provider services outside this list):
- **6 platforms**: Telegram (enabled), YouTube/Twitter/Facebook/Instagram/Shopee (Coming Soon)
- **Telegram categories**: Member Telegram (enabled), View Telegram (Coming Soon)
- **3 Member services** mapped to VietnamFB IDs:
  - 1720: Telegram Members HQ (fallback 40,686 milli-VND/1K)
  - 1510: Telegram Members PLUS (fallback 47,664)
  - 1694: Telegram Premium Members (fallback 142,330)

### 2.8 CatalogService (`app/services/catalog.py`)
- Merges live provider data with allow-list
- On provider outage: exposes configured cost with `cost_source="configured"`
- Provider IDs not in allow-list **never leak** to Bot Core

### 2.9 OrderService (`app/services/orders.py`)
- In-flight duplicate guard (`_inflight` set per process)
- Returns `OrderResult(definitive=..., reconciliation_required=...)`
- **No durable order storage** — that belongs to Bot Core

### 2.10 Routes (`app/api/routes/`)
| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/health/live` | ❌ | Liveness only |
| GET | `/health/ready` | ❌ | 503 if no provider configured |
| GET | `/health/dependencies` | ❌ | Informational, always 200 |
| GET | `/v1/platforms` | ✅ | Includes Coming Soon |
| GET | `/v1/platforms/{slug}/categories` | ✅ | |
| GET | `/v1/categories/{id}` | ✅ | |
| GET | `/v1/categories/{id}/services` | ✅ | Merged live + allow-list |
| GET | `/v1/services/{id}` | ✅ | |
| POST | `/v1/orders` | ✅ | 409 if duplicate in-flight; returns `success`, `definitive`, `provider_order_id`, `charge_milli`, `status`, `error`, `reconciliation_required` |
| GET | `/v1/orders/{id}/status` | ✅ | Live provider status |

### 2.11 Tests (`apps/engagement-api/tests/`)
- 23 tests: health, auth, catalog, order success/definitive/ambiguous, quantity validation, unknown service, duplicate in-flight, order status auth

**Result:** `23 passed` (StarletteDeprecationWarning from test client only)

### 2.12 Smoke Test (Docker)
```bash
# toolnet-engagement:v3-test
curl /health/live                      → {"status":"alive"}
curl /v1/platforms (no auth)           → 401
curl /v1/platforms -H "X-Internal-Token: smoke_token" → 200, 6 platforms
curl /v1/orders/abc/status (no auth)   → 401
curl /health/ready                     → 503 (no VIETNAMFB_API_KEY)
```
**Image hygiene:** No `.env`, no tests, no `__pycache__`, no `turso_client.py`

### 2.13 Deployment Configuration
- **Northflank service:** `toolnet-engagement` (Service, 1+ replicas, internal :8000)
- **Required env:**
  ```
  ENVIRONMENT=production
  ENGAGEMENT_INTERNAL_TOKEN=<shared>
  VIETNAMFB_API_KEY=<provider key>
  VIETNAMFB_BASE_URL=https://vietnamfb.com
  LOG_LEVEL=INFO
  ```
- **Must NOT set:** `TURSO_URL`, `TURSO_TOKEN`, `DATABASE_URL`, `DATABASE_TOKEN`, `BOT_TOKEN`, `ADMIN_IDS`

---

## 3. Integration Contract

### 3.1 Ownership Boundary (from `docs/engagement-api-contract.md`)

| Data | Owner |
|------|-------|
| Platforms, categories, allow-listed provider services | Engagement API |
| Live provider catalog, provider cost, provider order calls | Engagement API |
| Provider credentials & error rules | Engagement API |
| Users, wallets, deposits, ledger, orders, payments | Bot Core / Turso |
| Durable idempotency (`orders.request_key`) | Bot Core / Turso |
| Provider confirmations (`provider_orders`) | Bot Core / Turso |
| Refunds & reconciliation state | Bot Core / Turso |

### 3.2 Order Sequence
1. Bot Core fetches service from API, validates link/quantity
2. **Single transaction**: insert order (`request_key` UNIQUE) + debit wallet + `provider_payment` ledger
3. `POST /v1/orders` with same `idempotency_key`
4. **Success** → persist `provider_orders`
   **Definitive failure** → `refund_provider_order` (once)
   **Ambiguous failure** → `mark_pending_reconciliation` + admin alert
5. Replayed confirmations find existing `request_key` → "duplicate" → no provider call

### 3.3 Error Semantics
| API Response | Bot Core Action |
|--------------|-----------------|
| `success=true, definitive=true` | Persist provider order, keep charge |
| `success=false, definitive=true` | Refund once, mark `rejected` |
| `success=false, definitive=false` | Keep charge, mark `pending_reconciliation`, alert admin |
| HTTP 409 / 5xx / timeout / malformed | Treat as ambiguous → `pending_reconciliation` |

### 3.4 Markup
- Default 100%
- Sale price per 1,000 = `rate_milli * 200 // 100` (VNĐ)

### 3.5 Environment Separation

| Variable | Bot Core | Engagement API |
|----------|----------|----------------|
| `TURSO_URL` / `TURSO_TOKEN` | ✅ required | ❌ never |
| `VIETNAMFB_API_KEY` | ❌ never | ✅ production |
| `ENGAGEMENT_API_TOKEN` | ✅ client | ❌ |
| `ENGAGEMENT_INTERNAL_TOKEN` | ❌ | ✅ server |
| `ENGAGEMENT_API_URL` | ✅ `http://toolnet-engagement:8000` | — |

### 3.6 End-to-End Test
`test_engagement_api_integration.py`:
- Starts mock VietnamFB HTTP server
- Starts Engagement API subprocess (mock provider URL)
- Runs Bot Core handlers against real API → mock provider
- Verifies: catalog fetch, order success → `provider_orders` persisted, wallet debited, user notified; definitive rejection → refund once; ambiguous → pending_reconciliation; wrong token → 401

---

## 4. Git Status

```
Tracked changes:    41 files (2066 insertions, 1907 deletions)
  - Includes deletion of duplicate apps/engagement_api/* (4 tracked files)
Untracked (new):    23 files
  - apps/bot-core/tests/* (4 files)
  - apps/engagement-api/* (routes, catalog, services, providers, schemas, tests, .dockerignore, .env.example)
Ignored (never staged):
  - .env, apps/bot-core/.env, backups/
```

---

## 5. Verification Checklist

| Check | Status |
|-------|--------|
| Bot Core unit tests | ✅ 28 passed |
| Engagement API unit tests | ✅ 23 passed |
| Root regression tests | ✅ 41 passed |
| Docker build: Bot Core | ✅ builds, imports, migrations, healthcheck OK |
| Docker build: Engagement API | ✅ builds, health/live, catalog auth, order auth OK |
| Image hygiene (no .env/tests/secrets) | ✅ both images clean |
| No hardcoded provider data in Bot Core | ✅ verified |
| No Turso credentials in Engagement API | ✅ verified |
| Legacy callbacks preserved | ✅ verified |
| Order safety (no double charge/refund/duplicate) | ✅ verified |
| Documentation updated | ✅ README, NORTHFLANK_DEPLOY, env-config, API contract |

---

## 6. Go/No-Go for Push to `master`

✅ **All technical criteria met**  
⚠️ **Pending explicit user approval**

> Northflank auto-deploy is enabled on `master`. Push will trigger builds for both services. Production impact cannot be verified without Northflank access. **Awaiting confirmation before `git push origin master`.**

---

## 7. Next Steps (after approval)

1. `git add -A` (stages all safe changes; `.env`/backups remain ignored)
2. `git commit -m "V3 split: Bot Core + Engagement API as independent Northflank services"`
3. `git push origin master`
4. Monitor Northflank deployments:
   - Engagement API: `/health/ready` → 200, `/v1/platforms` returns catalog
   - Bot Core: logs show "Database backend: Turso (remote)", "Bot @... đã hoạt động"
5. Post-deploy verification:
   - Tool Access → Engagement Services → 6 platforms
   - Telegram → Member Telegram → packages with sale prices
   - Telegram → View Telegram → "đang cập nhật"
   - Other platforms → "Coming Soon"
   - Wallet, deposits, orders, admin panel functional
   - No traceback, no tokens in logs

---

*Report generated automatically from verification run on 2026-10-25.*
# ToolNet Telegram Service Bot — Monorepo

Modular monorepo with two independently deployable Northflank services:

- **Bot Core** (`apps/bot-core/`) — Telegram Bot API, users, wallet, orders, payments, admin, Turso.
- **Engagement API** (`apps/engagement-api/`) — stateless FastAPI catalog and provider integration.

The services communicate only through an authenticated internal HTTP API. Bot Core never
contains provider credentials, provider service IDs, provider cost prices or a hardcoded
engagement catalog.

## Architecture

```
Telegram
   |
   v
Bot Core (Northflank worker, 1 replica)
   |-- Turso (users, wallets, orders, ledger, deposits, referrals, settings)
   |
   +--> Engagement API (internal HTTP, token protected)
             |
             +--> VietnamFB SMM panel (provider orders/status)
```

```
telegram-service-bot/
├── apps/
│   ├── bot-core/                  # Northflank Service 1: Telegram bot
│   │   ├── app/
│   │   │   ├── core/              # Config, logging, Telegram client, state
│   │   │   ├── telegram/          # Handlers, keyboards, callbacks
│   │   │   ├── modules/           # Users, wallet, orders, deposits, admin
│   │   │   ├── database/          # Turso/SQLite connection and migrations
│   │   │   ├── clients/           # Engagement API client
│   │   │   └── i18n/              # Translations
│   │   ├── tests/                 # UI, order-safety and API integration tests
│   │   ├── bot.py                 # Entry point
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── healthcheck.py
│   │
│   └── engagement-api/            # Northflank Service 2: stateless FastAPI
│       ├── app/
│       │   ├── api/routes/        # Health, catalog and order endpoints
│       │   ├── catalog/           # Code-owned platform/category/service allow-list
│       │   ├── core/              # Config, auth, rate limit, logging, runtime
│       │   ├── providers/         # Provider abstraction and VietnamFB client
│       │   ├── services/          # Catalog merge and order orchestration
│       │   ├── schemas/           # Pydantic v2 request/response models
│       │   └── main.py            # FastAPI entry point
│       ├── tests/                 # Contract, safety and provider tests
│       ├── Dockerfile
│       ├── requirements.txt
│       └── .env.example
│
├── packages/contracts/            # Shared API types/documentation
├── database/migrations/           # Legacy SQL migrations (Bot Core uses Python migrations)
├── assets/                        # Images, GIFs
├── tests/                         # Legacy root-bot regression tests
├── docs/                          # Deployment, environment and API contract docs
└── README.md
```

## Services

### Bot Core (Northflank 1)
- **Runtime**: Python 3.12, standard library only.
- **Protocol**: Telegram long polling.
- **Database**: Turso (libSQL) in production; SQLite only for local development/tests.
- **Owns**: users, wallet, deposits, ledger, orders, payments, referrals, subscriptions,
  admin, banking configuration and audit logs.
- **Engagement behavior**:
  - Fetches all platforms, categories and provider services from the Engagement API.
  - Applies the Bot Core markup to provider cost before showing a sale price.
  - Creates the local order and debits the wallet atomically **before** calling the provider.
  - Stores durable idempotency in `orders.request_key` and provider confirmation in
    `provider_orders`.
  - Refunds exactly once on a definitive provider rejection.
  - Keeps the charge and marks `pending_reconciliation` when the provider outcome is unknown.

### Engagement API (Northflank 2)
- **Runtime**: Python 3.12, FastAPI + Pydantic v2 + HTTPX.
- **Protocol**: HTTP/JSON on the private network, protected by `ENGAGEMENT_INTERNAL_TOKEN`.
- **Database**: **none**. The service is stateless; it must not receive `TURSO_URL`,
  `TURSO_TOKEN`, `DATABASE_URL` or `DATABASE_TOKEN`.
- **Owns**:
  - Code-owned platform/category metadata and the real-provider service allow-list.
  - Live provider catalog synchronization.
  - Provider order placement and order-status lookup.
  - Provider error classification (definitive vs ambiguous).
  - Correlation IDs and in-flight duplicate protection.
- **Does not own**: customer data, wallets, payments, durable orders, idempotency records or
  refunds. Those stay in Bot Core.

## Deployment

### Northflank Service 1: `toolnet-bot-core`
- **Dockerfile**: `apps/bot-core/Dockerfile`
- **Build context**: repository root (`/`)
- **Instances**: 1 (long polling; never scale above 1)
- **Ports**: none (worker)
- **Environment**: see `apps/bot-core/.env.example`
- **Required integration env**: `ENGAGEMENT_API_URL`, `ENGAGEMENT_API_TOKEN`

### Northflank Service 2: `toolnet-engagement`
- **Dockerfile**: `apps/engagement-api/Dockerfile`
- **Build context**: repository root (`/`)
- **Instances**: 1+ (stateless)
- **Port**: 8000 (internal/private)
- **Environment**: see `apps/engagement-api/.env.example`
- **Required env**: `ENVIRONMENT`, `ENGAGEMENT_INTERNAL_TOKEN`, `VIETNAMFB_API_KEY`
- **Never add**: `TURSO_URL`, `TURSO_TOKEN`, `BOT_TOKEN`, `ADMIN_IDS`

`ENGAGEMENT_API_TOKEN` in Bot Core must equal `ENGAGEMENT_INTERNAL_TOKEN` in the
Engagement API. Use the internal service hostname, for example
`http://toolnet-engagement:8000`.

## Development

```bash
# Install dependencies
cd apps/bot-core && pip install -r requirements.txt
cd apps/engagement-api && pip install -r requirements.txt

# Run Bot Core locally (requires a test bot token)
cd apps/bot-core && python3 bot.py

# Run Engagement API locally (use a mock/test provider key outside production)
cd apps/engagement-api && ENVIRONMENT=development \
  ENGAGEMENT_INTERNAL_TOKEN=dev-token \
  VIETNAMFB_API_KEY=dev-key \
  python3 -m app.main
```

## Environment Variables

### Bot Core
| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | Yes | Telegram Bot Token from @BotFather |
| `ADMIN_IDS` | Yes | Comma-separated admin Telegram user IDs |
| `BOT_NAME` | No | Bot display name |
| `SUPPORT_USERNAME` | No | Support username (without @) |
| `DB_BACKEND` | Production | `turso` in production; `sqlite` for local tests |
| `TURSO_URL` | Turso only | Turso database URL |
| `TURSO_TOKEN` | Turso only | Turso auth token |
| `DB_PATH` | No | SQLite path for local development |
| `BANK_NAME` | Deposits | Bank name for manual deposits |
| `BANK_ACCOUNT` | Deposits | Bank account number |
| `BANK_OWNER` | Deposits | Bank account owner |
| `ENGAGEMENT_API_URL` | Yes | Engagement API base URL (internal) |
| `ENGAGEMENT_API_TOKEN` | Yes | Internal API token (must match API) |
| `LOG_LEVEL` | No | Logging level (default: INFO) |

Bot Core must **not** receive `VIETNAMFB_API_KEY` or `VIETNAMFB_BASE_URL`.

### Engagement API
| Variable | Required | Description |
|----------|----------|-------------|
| `ENVIRONMENT` | Yes | `production` (fails fast without a provider key) or `test`/`development` |
| `ENGAGEMENT_INTERNAL_TOKEN` | Yes | Internal auth token (must match Bot Core) |
| `VIETNAMFB_API_KEY` | Production | VietnamFB SMM Panel API key |
| `VIETNAMFB_BASE_URL` | No | VietnamFB base URL (default `https://vietnamfb.com`) |
| `HOST` | No | Bind host (default `0.0.0.0`) |
| `PORT` | No | Bind port (default `8000`) |
| `LOG_LEVEL` | No | Logging level |

The Engagement API must **not** receive Turso/database credentials.

## Northflank Networking

**Same project (recommended)**: Both services in same Northflank project → private DNS works.
- Bot Core: `ENGAGEMENT_API_URL=http://toolnet-engagement:8000`
- Engagement API: **no public port**, internal only.

**Different projects/teams**: Private DNS **does not work** across projects.
- Engagement API: enable **Public Port 8000** → gets `https://<service>-<project>.northflank.app` with TLS.
- Bot Core: `ENGAGEMENT_API_URL=https://<engagement-service>-<project>.northflank.app`
- Auth: `X-Internal-Token` header (shared secret) validates every request.

## Security

- All secrets live in Northflank environment variables, never in the repository.
- `.gitignore` excludes `.env`, `backups/`, `data/`, `*.sqlite3*`.
- `.dockerignore` excludes secrets, backups, git data and tests.
- The internal API uses a shared token, correlation IDs and a small rate limiter.
- Provider credentials and provider-specific rules exist only in the Engagement API.
- Turso credentials and all financial state exist only in Bot Core.
- SQLite is never used as a silent production fallback when `DB_BACKEND=turso`.

## Testing

```bash
# Bot Core: UI, order safety, and real client -> real API -> mock VietnamFB
cd apps/bot-core && python3 -m pytest tests -q

# Engagement API: contract, auth, catalog and provider classification
cd apps/engagement-api && ENVIRONMENT=test \
  ENGAGEMENT_INTERNAL_TOKEN=test_token python3 -m pytest tests -q

# Legacy root bot regression tests
python3 -m pytest tests -q

# Docker builds
docker build -t toolnet-bot-core -f apps/bot-core/Dockerfile .
docker build -t toolnet-engagement -f apps/engagement-api/Dockerfile .
```

The integration test starts a local mock VietnamFB HTTP server and the Engagement API
as a subprocess. It never places a real provider order.

See `docs/engagement-api-contract.md` for the HTTP contract and
`docs/env-configuration.md` for the full environment matrix.

## License

Proprietary - ToolNet Works

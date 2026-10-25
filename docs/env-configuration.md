# Environment Configuration — ToolNet V3

V3 runs two independent Northflank services. Each service receives only the
credentials it needs; do not copy a shared `.env` between them.

## Bot Core (`apps/bot-core/`)
**Northflank Service: `toolnet-bot-core`**

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `BOT_TOKEN` | ✅ Yes | Telegram Bot Token from @BotFather | `123456:ABC-DEF...` |
| `ADMIN_IDS` | ✅ Yes | Comma-separated admin Telegram user IDs | `1208342332,987654321` |
| `BOT_NAME` | No | Bot display name | `ToolNet Services` |
| `SUPPORT_USERNAME` | No | Support username (without @) | `toolnet_support` |
| `DB_BACKEND` | Production | `turso` in production; `sqlite` for local dev/test | `turso` |
| `TURSO_URL` | Turso only | Turso database URL | `libsql://xxx.turso.io` |
| `TURSO_TOKEN` | Turso only | Turso auth token | `eyJhbGci...` |
| `DB_PATH` | No | SQLite path for local development only | `./data/bot.sqlite3` |
| `BANK_NAME` | Deposits | Bank name for manual deposits | `Vietcombank` |
| `BANK_ACCOUNT` | Deposits | Bank account number | `1234567890` |
| `BANK_OWNER` | Deposits | Bank account owner name | `CONG TY TNHH TOOLNET` |
| `ENGAGEMENT_API_URL` | ✅ Yes | Engagement API base URL (internal) | `http://toolnet-engagement:8000` |
| `ENGAGEMENT_API_TOKEN` | ✅ Yes | Internal API shared secret | `super-secret-token-123` |
| `LOG_LEVEL` | No | Logging level | `INFO` |

**Must not be set on Bot Core:** `VIETNAMFB_API_KEY`, `VIETNAMFB_BASE_URL`,
`ENGAGEMENT_INTERNAL_TOKEN` (Bot Core uses `ENGAGEMENT_API_TOKEN`).

Bot Core owns users, wallets, deposits, ledger, orders, payments, referrals,
subscriptions, admin data, banking configuration and audit logs.

---

## Engagement API (`apps/engagement-api/`)
**Northflank Service: `toolnet-engagement`**

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `ENVIRONMENT` | ✅ Yes | `production` (fail-fast provider validation) or `test`/`development` | `production` |
| `ENGAGEMENT_INTERNAL_TOKEN` | ✅ Yes | Internal API auth (must match Bot Core) | `super-secret-token-123` |
| `VIETNAMFB_API_KEY` | ✅ Production | VietnamFB SMM Panel API key | `f3a36a51caf9...` |
| `VIETNAMFB_BASE_URL` | No | VietnamFB API base URL | `https://vietnamfb.com` |
| `HOST` | No | Bind host | `0.0.0.0` |
| `PORT` | No | Bind port | `8000` |
| `LOG_LEVEL` | No | Logging level | `INFO` |
| `REQUEST_TIMEOUT` | No | Provider request timeout (seconds) | `20` |
| `CONNECT_TIMEOUT` | No | Provider connect timeout (seconds) | `5` |
| `MAX_RETRIES` | No | Retries for read-only provider calls (never `add`) | `2` |
| `PROVIDER_CACHE_TTL` | No | Provider catalog cache (seconds) | `300` |
| `RATE_LIMIT_REQUESTS` | No | Order requests per window per client | `120` |
| `RATE_LIMIT_WINDOW` | No | Rate-limit window (seconds) | `60` |

**Must not be set on Engagement API:** `TURSO_URL`, `TURSO_TOKEN`,
`DATABASE_URL`, `DATABASE_TOKEN`, `BOT_TOKEN`, `ADMIN_IDS`.

The Engagement API is stateless. It does not own customer data, orders,
wallets, payments or idempotency records. Durable idempotency is enforced by
Bot Core's `orders.request_key` unique constraint before the API is called.

---

## Key Separation Principle

| Secret | Bot Core | Engagement API |
|--------|----------|----------------|
| `BOT_TOKEN` | ✅ | ❌ |
| `ADMIN_IDS` | ✅ | ❌ |
| `TURSO_URL` / `TURSO_TOKEN` | ✅ (Bot Core owns the DB) | ❌ **never** |
| `VIETNAMFB_API_KEY` | ❌ **never** | ✅ **only here** |
| `ENGAGEMENT_API_TOKEN` | ✅ (client) | ❌ |
| `ENGAGEMENT_INTERNAL_TOKEN` | ❌ | ✅ (server) |

`ENGAGEMENT_API_TOKEN` and `ENGAGEMENT_INTERNAL_TOKEN` must contain the same
value. They are different variable names because they are consumed by
different services.

---

## Northflank Setup

### Bot Core Service
- **Dockerfile**: `/apps/bot-core/Dockerfile`
- **Build context**: `/`
- **Port**: none (worker, long polling)
- **Instances**: 1 (never scale above 1)
- **Auto-deploy**: only after the V3 rollout is approved

### Engagement API Service
- **Dockerfile**: `/apps/engagement-api/Dockerfile`
- **Build context**: `/`
- **Port**: 8000 (internal/private only)
- **Instances**: 1+ (stateless)
- **Auto-deploy**: only after the V3 rollout is approved

### Internal Networking

**Option A: Same Northflank project (recommended)**
- Both services in same project/network.
- Bot Core reaches API at `http://toolnet-engagement:8000` (private DNS).
- No public port on Engagement API.

**Option B: Different Northflank projects/teams**
- Private DNS **does not work** across projects.
- Engagement API: enable **Public Port 8000** → Northflank provisions `https://<service>-<project>.northflank.app` with TLS.
- Bot Core: set `ENGAGEMENT_API_URL=https://<engagement-service>-<project>.northflank.app`.
- Authentication: `X-Internal-Token` header (shared secret) validates every request.
- No additional IP allowlist needed; token is timing-safe compared.

## Production Safety

- Never put `TURSO_TOKEN` in the Engagement API service.
- Never put `VIETNAMFB_API_KEY` in the Bot Core service.
- Do not use SQLite as a production fallback when Turso is configured.
- Do not enable public access to the Engagement API; it is internal-only.
- Rotate `ENGAGEMENT_INTERNAL_TOKEN` on both services at the same time.

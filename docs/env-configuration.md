# Environment Configuration for ToolNet Monorepo V3

## Bot Core (apps/bot-core/)
**Northflank Service: toolnet-bot-core**

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `BOT_TOKEN` | ✅ Yes | Telegram Bot Token from @BotFather | `123456:ABC-DEF...` |
| `ADMIN_IDS` | ✅ Yes | Comma-separated admin Telegram user IDs | `1208342332,987654321` |
| `BOT_NAME` | No | Bot display name | `ToolNet Services` |
| `SUPPORT_USERNAME` | No | Support username (without @) | `toolnet_support` |
| `DB_PATH` | No | SQLite path (dev only) | `/data/bot.sqlite3` |
| `DB_BACKEND` | No | `sqlite` or `turso` | `turso` |
| `TURSO_URL` | Turso only | Turso database URL | `libsql://xxx.turso.io` |
| `TURSO_TOKEN` | Turso only | Turso auth token | `eyJhbGci...` |
| `BANK_NAME` | Deposits | Bank name for manual deposits | `Vietcombank` |
| `BANK_ACCOUNT` | Deposits | Bank account number | `1234567890` |
| `BANK_OWNER` | Deposits | Bank account owner name | `CONG TY TNHH TOOLNET` |
| `ENGAGEMENT_API_URL` | ✅ Yes | Engagement API base URL (internal) | `http://toolnet-engagement:8000` |
| `ENGAGEMENT_API_TOKEN` | ✅ Yes | Internal API shared secret | `super-secret-token-123` |
| `LOG_LEVEL` | No | Logging level | `INFO` |

---

## Engagement API (apps/engagement-api/)
**Northflank Service: toolnet-engagement**

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `ENGAGEMENT_INTERNAL_TOKEN` | ✅ Yes | Internal API auth (shared with Bot Core) | `super-secret-token-123` |
| `DATABASE_URL` | Turso only | Turso database URL | `libsql://xxx.turso.io` |
| `DATABASE_TOKEN` | Turso only | Turso auth token | `eyJhbGci...` |
| `DB_PATH` | No | SQLite path (dev only) | `/data/engagement.sqlite3` |
| `VIETNAMFB_API_KEY` | ✅ Yes | VietnamFB SMM Panel API key | `f3a36a51caf9...` |
| `VIETNAMFB_BASE_URL` | No | VietnamFB API base URL | `https://vietnamfb.com` |
| `HOST` | No | Bind host | `0.0.0.0` |
| `PORT` | No | Bind port | `8000` |
| `LOG_LEVEL` | No | Logging level | `INFO` |

---

## Key Separation Principle

| Secret | Bot Core | Engagement API |
|--------|----------|----------------|
| `BOT_TOKEN` | ✅ | ❌ |
| `ADMIN_IDS` | ✅ | ❌ |
| `TURSO_URL/TOKEN` | ✅ (own DB) | ✅ (own DB or shared) |
| `VIETNAMFB_API_KEY` | ❌ **REMOVED** | ✅ **ONLY HERE** |
| `ENGAGEMENT_API_TOKEN` | ✅ (client) | ✅ (server) |

**Critical:** `VIETNAMFB_API_KEY` is ONLY in Engagement API. Bot Core calls Engagement API via internal HTTP.

---

## Northflank Setup

### Bot Core Service
- **Dockerfile**: `/apps/bot-core/Dockerfile`
- **Build Context**: `/`
- **Port**: None (worker, long polling)
- **Instances**: 1
- **Auto-deploy**: Enabled

### Engagement API Service
- **Dockerfile**: `/apps/engagement-api/Dockerfile`
- **Build Context**: `/`
- **Port**: 8000 (internal only)
- **Instances**: 1+
- **Auto-deploy**: Enabled

### Internal Networking
Both services in same Northflank project → communicate via `http://toolnet-engagement:8000`

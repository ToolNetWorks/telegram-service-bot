# ToolNet Telegram Service Bot — Monorepo

Modular monorepo for ToolNet services with two independent Northflank services:

- **Bot Core** (`apps/bot-core/`) — Telegram Bot API, user management, wallet, orders, admin
- **Engagement API** (`apps/engagement-api/`) — FastAPI service for multi-platform engagement services

## Architecture

```
telegram-service-bot/
├── apps/
│   ├── bot-core/              # Northflank Service 1: Telegram Bot
│   │   ├── app/
│   │   │   ├── core/          # Config, logging, Telegram client, state
│   │   │   ├── telegram/      # Handlers, keyboards, callbacks
│   │   │   ├── modules/       # Domain modules (users, wallet, orders, etc.)
│   │   │   ├── database/      # Connection, migrations, repositories
│   │   │   ├── clients/       # External API clients (Engagement API)
│   │   │   └── i18n/          # Translations
│   │   ├── bot.py             # Entry point
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── healthcheck.py
│   │
│   └── engagement-api/        # Northflank Service 2: FastAPI
│       ├── app/
│       │   ├── api/           # FastAPI routes
│       │   ├── core/          # Config, database
│       │   ├── platforms/     # Platform-specific logic
│       │   ├── providers/     # Provider integrations (VietnamFB)
│       │   ├── services/      # Business logic
│       │   └── schemas/       # Pydantic models
│       ├── main.py            # Entry point
│       ├── Dockerfile
│       └── requirements.txt
│
├── packages/
│   └── contracts/             # Shared types & API contracts
│
├── database/
│   └── migrations/            # SQL migrations
│
├── assets/                    # Images, GIFs
├── tests/                     # Shared tests
├── scripts/                   # Deployment scripts
├── docs/                      # Documentation
└── README.md
```

## Services

### Bot Core (Northflank 1)
- **Runtime**: Python 3.12, stdlib only (no external deps)
- **Protocol**: Telegram Long Polling
- **Database**: Turso (libSQL) or SQLite
- **Responsibilities**:
  - Telegram Bot API (messages, callbacks, inline keyboards)
  - User management, CAPTCHA, i18n
  - Wallet & deposits (manual verification)
  - Orders & financial transactions (idempotent, atomic)
  - Admin panel
  - Referral system
  - Calls Engagement API via internal HTTP

### Engagement API (Northflank 2)
- **Runtime**: Python 3.12, FastAPI + Pydantic v2 + HTTPX
- **Protocol**: HTTP/JSON (internal only)
- **Database**: Turso (libSQL) or SQLite
- **Responsibilities**:
  - Platform & category catalog
  - Provider service management
  - Order placement via SMM panels (VietnamFB)
  - Order status tracking
  - Reconciliation
  - Rate limiting, idempotency, correlation IDs

## Deployment

### Northflank Service 1: `toolnet-bot-core`
- **Dockerfile**: `apps/bot-core/Dockerfile`
- **Build Context**: Repository root (`/`)
- **Instances**: 1 (long polling)
- **Ports**: None (worker)
- **Environment**: See `.env.example`

### Northflank Service 2: `toolnet-engagement`
- **Dockerfile**: `apps/engagement-api/Dockerfile`
- **Build Context**: Repository root (`/`)
- **Instances**: 1+
- **Port**: 8000 (internal)
- **Environment**: See `.env.example`

## Development

```bash
# Install dependencies
cd apps/bot-core && pip install -r requirements.txt
cd apps/engagement-api && pip install -r requirements.txt

# Run Bot Core locally
cd apps/bot-core && python3 bot.py

# Run Engagement API locally
cd apps/engagement-api && python3 app/main.py

# Run tests
python3 -m pytest tests/ -v

# Docker build
docker build -t toolnet-bot-core -f apps/bot-core/Dockerfile .
docker build -t toolnet-engagement -f apps/engagement-api/Dockerfile .
```

## Environment Variables

### Bot Core
| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | Yes | Telegram Bot Token from @BotFather |
| `ADMIN_IDS` | Yes | Comma-separated admin user IDs |
| `BOT_NAME` | No | Bot display name |
| `SUPPORT_USERNAME` | No | Support username (without @) |
| `DB_PATH` | No | SQLite path (default: `./data/bot.sqlite3`) |
| `DB_BACKEND` | No | `sqlite` or `turso` |
| `TURSO_URL` | Turso only | Turso database URL |
| `TURSO_TOKEN` | Turso only | Turso auth token |
| `BANK_NAME` | Deposits | Bank name for deposits |
| `BANK_ACCOUNT` | Deposits | Bank account number |
| `BANK_OWNER` | Deposits | Bank account owner |
| `ENGAGEMENT_API_URL` | Yes | Engagement API base URL |
| `ENGAGEMENT_API_TOKEN` | Yes | Internal API token |
| `LOG_LEVEL` | No | Logging level (default: INFO) |

### Engagement API
| Variable | Required | Description |
|----------|----------|-------------|
| `ENGAGEMENT_INTERNAL_TOKEN` | Yes | Internal auth token (shared with Bot Core) |
| `DATABASE_URL` | Turso only | Turso database URL |
| `DATABASE_TOKEN` | Turso only | Turso auth token |
| `VIETNAMFB_API_KEY` | Yes | VietnamFB SMM Panel API key |
| `VIETNAMFB_BASE_URL` | No | VietnamFB base URL |
| `HOST` | No | Bind host (default: 0.0.0.0) |
| `PORT` | No | Bind port (default: 8000) |
| `LOG_LEVEL` | No | Logging level |

## Security

- All secrets in Northflank environment variables (not in repo)
- `.gitignore` excludes `.env`, `backups/`, `data/`, `*.sqlite3*`
- `.dockerignore` excludes secrets, backups, git, docs
- Internal API uses shared token + correlation IDs
- No provider credentials exposed to Bot Core
- Database uses WAL mode, foreign keys, busy timeout

## Testing

```bash
# Unit tests
python3 -m pytest tests/ -v

# Docker smoke test
./docker-smoke-test.sh

# Integration test (requires running services)
python3 -m pytest tests/integration/ -v
```

## License

Proprietary - ToolNet Works